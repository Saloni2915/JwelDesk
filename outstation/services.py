"""
outstation/services.py
----------------------
Core transactional service functions for Outstation Jewellery Sales & Stock Tracking.
Guarantees database atomicity, row-level locking, and prevents duplicate stock issuance/sales.
"""

from decimal import Decimal
import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from inventory import stock
from inventory.models import JewelleryItem, StockMovement
from sales.models import Sale, Payment
from .models import (
    OutstationTrip,
    OutstationTripItem,
    OutstationTripSale,
    OutstationTripAuditLog,
    Exhibition,
    ExhibitionExpense,
    ExhibitionItem,
    ExhibitionSale,
    ExhibitionAuditLog,
)

logger = logging.getLogger('outstation.services')


def issue_items_to_trip(trip, item_ids, user=None):
    """
    Atomically issue tagged jewellery items to an OutstationTrip.

    Security & Stock Invariants:
    1. Items must belong to the same tenant as the trip.
    2. Items must have status == 'Available' and quantity > 0.
    3. Items must not already be issued to any active outstation trip.
    4. Row-level locking (select_for_update) prevents concurrent double-issuance.
    5. Transferred items are marked 'Reserved', removing them from showroom available stock.
    6. Immutable StockMovement records are generated for full traceability.
    """
    if not item_ids:
        raise ValidationError("No jewellery items selected for issuance.")

    issued_count = 0
    with transaction.atomic():
        # Lock trip to serialize issuance requests
        locked_trip = OutstationTrip.objects.select_for_update().get(id=trip.id)
        if locked_trip.status in [OutstationTrip.STATUS_CLOSED, OutstationTrip.STATUS_CANCELLED]:
            raise ValidationError(f"Cannot issue stock to a {locked_trip.get_status_display()} trip.")

        # Lock candidate items to prevent race conditions
        items = list(
            JewelleryItem.objects
            .select_for_update()
            .filter(id__in=item_ids, tenant_id=locked_trip.tenant_id)
        )

        if len(items) != len(set(item_ids)):
            raise ValidationError("One or more selected items do not belong to this showroom.")

        # Check existing active trip issuances across the tenant
        active_issued_item_ids = set(
            OutstationTripItem.objects.filter(
                trip__tenant_id=locked_trip.tenant_id,
                trip__status__in=[
                    OutstationTrip.STATUS_DRAFT,
                    OutstationTrip.STATUS_ISSUED,
                    OutstationTrip.STATUS_IN_PROGRESS,
                    OutstationTrip.STATUS_RECONCILING,
                ],
                status=OutstationTripItem.STATUS_ISSUED,
                item_id__in=item_ids
            ).values_list('item_id', flat=True)
        )

        # Check existing active exhibition issuances across the tenant
        active_exhibition_item_ids = set(
            ExhibitionItem.objects.filter(
                exhibition__tenant_id=locked_trip.tenant_id,
                exhibition__status__in=[
                    Exhibition.STATUS_DRAFT,
                    Exhibition.STATUS_ISSUED,
                    Exhibition.STATUS_IN_PROGRESS,
                    Exhibition.STATUS_RECONCILING,
                ],
                status=ExhibitionItem.STATUS_ISSUED,
                item_id__in=item_ids
            ).values_list('item_id', flat=True)
        )

        for item in items:
            if item.id in active_issued_item_ids:
                raise ValidationError(
                    f"Item '{item.name}' ({item.tag_number or item.item_code}) is already issued to an active trip."
                )

            if item.id in active_exhibition_item_ids:
                raise ValidationError(
                    f"Item '{item.name}' ({item.tag_number or item.item_code}) is already issued to an active exhibition."
                )

            if item.status != 'Available' or (item.quantity or 0) <= 0:
                raise ValidationError(
                    f"Item '{item.name}' ({item.tag_number or item.item_code}) is not available (Current status: {item.status})."
                )

            # Record trip item
            trip_item, created = OutstationTripItem.objects.get_or_create(
                trip=locked_trip,
                item=item,
                defaults={
                    'status': OutstationTripItem.STATUS_ISSUED,
                    'issue_price': item.selling_price or Decimal('0.00'),
                    'issue_gross_weight': item.gross_weight,
                    'issue_net_weight': item.net_weight,
                    'issued_at': timezone.now(),
                    'issued_by': user,
                }
            )

            if not created:
                if trip_item.status != OutstationTripItem.STATUS_ISSUED:
                    trip_item.status = OutstationTripItem.STATUS_ISSUED
                    trip_item.issued_at = timezone.now()
                    trip_item.issued_by = user
                    trip_item.save(update_fields=['status', 'issued_at', 'issued_by'])

            # Transition showroom item status to 'Reserved' (in transit on trip)
            item.status = 'Reserved'
            item.save(update_fields=['status', 'updated_at'])

            issued_count += 1

        # Advance trip status from Draft to Stock Issued if appropriate
        if locked_trip.status == OutstationTrip.STATUS_DRAFT and issued_count > 0:
            locked_trip.status = OutstationTrip.STATUS_ISSUED
            locked_trip.save(update_fields=['status', 'updated_at'])

        OutstationTripAuditLog.objects.create(
            trip=locked_trip,
            action=OutstationTripAuditLog.ACTION_STOCK_ISSUED,
            user=user,
            details=f"Issued {issued_count} jewellery pieces to trip {locked_trip.trip_number}."
        )

    return issued_count


def record_outstation_sale(
    trip,
    item_id,
    customer,
    sale_price,
    payment_method='Cash',
    buyer_type='B2C',
    business_name='',
    business_gstin='',
    notes='',
    user=None,
    paid_amount=None,
    payment_ref=''
):
    """
    Atomically record a sale made during an outstation trip to a B2B or B2C buyer.

    Reuses:
    - sales.Sale (Standard invoice & tax calculation engine)
    - sales.Payment (Payment ledger & outstanding amounts)
    - inventory.stock.record_sale (Inventory deduction & StockMovement)
    """
    with transaction.atomic():
        locked_trip = OutstationTrip.objects.select_for_update().get(id=trip.id)
        if locked_trip.status in [OutstationTrip.STATUS_CLOSED, OutstationTrip.STATUS_CANCELLED]:
            raise ValidationError(f"Cannot record sales on a {locked_trip.get_status_display()} trip.")

        # Find and lock trip item
        try:
            trip_item = (
                OutstationTripItem.objects
                .select_for_update()
                .get(trip=locked_trip, item_id=item_id, status=OutstationTripItem.STATUS_ISSUED)
            )
        except OutstationTripItem.DoesNotExist:
            raise ValidationError("This jewellery piece is not currently in transit or issued to this trip.")

        try:
            locked_item = JewelleryItem.objects.select_for_update().get(id=item_id, tenant_id=locked_trip.tenant_id)
        except JewelleryItem.DoesNotExist:
            raise ValidationError("This jewellery item does not exist or does not belong to this showroom.")

        # Cross-tenant customer check
        if customer.tenant_id != locked_trip.tenant_id:
            raise ValidationError("Selected buyer/customer belongs to a different showroom.")

        # Create core Sale record
        sale = Sale.objects.create(
            tenant=locked_trip.tenant,
            customer=customer,
            jewellery_item=locked_item,
            sale_price=Decimal(str(sale_price)),
            sale_date=timezone.now(),
            payment_method=payment_method,
            notes=f"Outstation Sale (Trip {locked_trip.trip_number} - {locked_trip.destination_city}). {notes}".strip()
        )

        # Record payment if provided
        paid_dec = Decimal(str(paid_amount)) if paid_amount is not None else Decimal(str(sale_price))
        if paid_dec > 0:
            Payment.objects.create(
                tenant=locked_trip.tenant,
                sale=sale,
                amount=paid_dec,
                payment_method=payment_method,
                payment_date=timezone.now(),
                reference=payment_ref,
                notes=f"Payment received during Outstation Trip {locked_trip.trip_number}"
            )

        # Execute stock reduction via single source of truth
        # First temporarily reset status so stock.record_sale succeeds
        locked_item.status = 'Available'
        locked_item.save(update_fields=['status'])
        stock.record_sale(locked_item, sale, user=user, notes=f"Sold on Outstation Trip #{locked_trip.trip_number}")

        # Update TripItem status
        trip_item.status = OutstationTripItem.STATUS_SOLD
        trip_item.reconciled_at = timezone.now()
        trip_item.reconciled_by = user
        trip_item.reconciliation_notes = f"Sold on trip (Invoice #{sale.id} to {customer.name})"
        trip_item.save(update_fields=['status', 'reconciled_at', 'reconciled_by', 'reconciliation_notes'])

        # Create TripSale link
        trip_sale = OutstationTripSale.objects.create(
            trip=locked_trip,
            sale=sale,
            trip_item=trip_item,
            buyer_type=buyer_type,
            business_name=business_name.strip(),
            business_gstin=business_gstin.strip().upper(),
            notes=notes.strip()
        )

        # Advance trip status to 'In Progress' if currently 'Stock Issued'
        if locked_trip.status == OutstationTrip.STATUS_ISSUED:
            locked_trip.status = OutstationTrip.STATUS_IN_PROGRESS
            locked_trip.save(update_fields=['status', 'updated_at'])

        OutstationTripAuditLog.objects.create(
            trip=locked_trip,
            action=OutstationTripAuditLog.ACTION_SALE_RECORDED,
            user=user,
            details=(
                f"Recorded {buyer_type} sale of {locked_item.name} ({locked_item.tag_number}) "
                f"to {customer.name} for ₹{sale.sale_price:,.2f} (Sale #{sale.id})."
            )
        )

    return sale


def reconcile_trip_item(trip_item, outcome, discrepancy_reason='', notes='', user=None):
    """
    Reconcile an individual issued jewellery piece when returning to the showroom.
    Outcomes:
    - 'Returned': Restores piece back to 'Available' showroom stock atomically.
    - 'Damaged': Flags piece as damaged with reason.
    - 'Missing': Flags piece as missing with reason.
    """
    if outcome not in [
        OutstationTripItem.STATUS_RETURNED,
        OutstationTripItem.STATUS_DAMAGED,
        OutstationTripItem.STATUS_MISSING
    ]:
        raise ValidationError(f"Invalid reconciliation outcome: {outcome}")

    with transaction.atomic():
        locked_item_row = (
            OutstationTripItem.objects
            .select_for_update()
            .select_related('trip', 'item')
            .get(id=trip_item.id)
        )

        if locked_item_row.status == OutstationTripItem.STATUS_SOLD:
            raise ValidationError("Cannot return or mark missing an item that has already been sold on this trip.")

        item = JewelleryItem.objects.select_for_update().get(id=locked_item_row.item_id)

        if outcome == OutstationTripItem.STATUS_RETURNED:
            # Safely restore item to available showroom stock
            item.status = 'Available'
            item.save(update_fields=['status', 'updated_at'])

            locked_item_row.status = OutstationTripItem.STATUS_RETURNED
            locked_item_row.reconciled_at = timezone.now()
            locked_item_row.reconciled_by = user
            locked_item_row.reconciliation_notes = notes.strip()
            locked_item_row.discrepancy_resolved = True
            locked_item_row.save(update_fields=[
                'status', 'reconciled_at', 'reconciled_by', 'reconciliation_notes', 'discrepancy_resolved'
            ])

            OutstationTripAuditLog.objects.create(
                trip=locked_item_row.trip,
                action=OutstationTripAuditLog.ACTION_STOCK_RETURNED,
                user=user,
                details=f"Item {item.name} ({item.tag_number or item.item_code}) returned safely to showroom."
            )

        elif outcome in [OutstationTripItem.STATUS_DAMAGED, OutstationTripItem.STATUS_MISSING]:
            if not discrepancy_reason.strip():
                raise ValidationError("Discrepancy explanation reason is strictly required.")

            locked_item_row.status = outcome
            locked_item_row.reconciled_at = timezone.now()
            locked_item_row.reconciled_by = user
            locked_item_row.discrepancy_reason = discrepancy_reason.strip()
            locked_item_row.discrepancy_resolved = False
            locked_item_row.reconciliation_notes = notes.strip()
            locked_item_row.save(update_fields=[
                'status', 'reconciled_at', 'reconciled_by', 'discrepancy_reason',
                'discrepancy_resolved', 'reconciliation_notes'
            ])

            OutstationTripAuditLog.objects.create(
                trip=locked_item_row.trip,
                action=OutstationTripAuditLog.ACTION_DISCREPANCY_LOGGED,
                user=user,
                details=(
                    f"Discrepancy logged for {item.name} ({item.tag_number or item.item_code}): "
                    f"{outcome.upper()} — Reason: {discrepancy_reason}"
                )
            )

        # Transition trip status to 'Reconciling' if currently 'In Progress' or 'Stock Issued'
        if locked_item_row.trip.status in [OutstationTrip.STATUS_ISSUED, OutstationTrip.STATUS_IN_PROGRESS]:
            locked_item_row.trip.status = OutstationTrip.STATUS_RECONCILING
            locked_item_row.trip.save(update_fields=['status', 'updated_at'])

    return locked_item_row


def resolve_item_discrepancy(trip_item, resolution_notes, write_off_stock=True, user=None):
    """
    Authorize and resolve a stock discrepancy (Damaged or Missing piece).
    If write_off_stock is True, records an official reduction stock movement so the
    lost/damaged piece is permanently written off the active ledger.
    """
    if not resolution_notes.strip():
        raise ValidationError("Resolution authorization notes are required.")

    with transaction.atomic():
        locked_item_row = (
            OutstationTripItem.objects
            .select_for_update()
            .select_related('trip', 'item')
            .get(id=trip_item.id)
        )

        if locked_item_row.status not in [OutstationTripItem.STATUS_DAMAGED, OutstationTripItem.STATUS_MISSING]:
            raise ValidationError("This item does not have an active Damaged or Missing discrepancy.")

        item = JewelleryItem.objects.select_for_update().get(id=locked_item_row.item_id)

        if write_off_stock and (item.quantity or 0) > 0:
            # Deduct stock permanently using inventory service
            reason = 'Lost Item' if locked_item_row.status == OutstationTripItem.STATUS_MISSING else 'Damaged Item'
            stock.apply_stock_change(
                item,
                -1,
                StockMovement.REDUCTION,
                reason=reason,
                notes=f"Discrepancy resolution on Trip {locked_item_row.trip.trip_number}: {resolution_notes}",
                user=user
            )

        locked_item_row.discrepancy_resolved = True
        locked_item_row.discrepancy_resolved_by = user
        locked_item_row.discrepancy_resolution_notes = resolution_notes.strip()
        locked_item_row.save(update_fields=[
            'discrepancy_resolved', 'discrepancy_resolved_by', 'discrepancy_resolution_notes'
        ])

        OutstationTripAuditLog.objects.create(
            trip=locked_item_row.trip,
            action=OutstationTripAuditLog.ACTION_DISCREPANCY_RESOLVE,
            user=user,
            details=(
                f"Resolved discrepancy for {item.name} ({item.tag_number}): "
                f"{locked_item_row.status} — Notes: {resolution_notes}"
            )
        )

    return locked_item_row


def close_outstation_trip(trip, user, actual_return_date=None, notes=''):
    """
    Finalize and close an OutstationTrip.
    Pre-conditions:
    - All issued items must be resolved (Sold or Returned to showroom).
    - No items may remain with status 'Issued' (still in transit).
    - All damaged/missing discrepancies must be officially authorized.
    """
    with transaction.atomic():
        locked_trip = OutstationTrip.objects.select_for_update().get(id=trip.id)

        if locked_trip.status == OutstationTrip.STATUS_CLOSED:
            raise ValidationError("This trip is already closed.")

        outstanding = locked_trip.issued_items.filter(status=OutstationTripItem.STATUS_ISSUED).count()
        if outstanding > 0:
            raise ValidationError(
                f"Cannot close trip: {outstanding} jewellery item(s) are still recorded as in-transit with the employee. "
                "Every item must be either marked as Sold, Returned to showroom, or logged as a discrepancy."
            )

        unresolved = locked_trip.unresolved_discrepancies_count
        if unresolved > 0:
            raise ValidationError(
                f"Cannot close trip: {unresolved} damaged or missing item discrepancy requires manager resolution."
            )

        return_date = actual_return_date or timezone.now().date()
        if return_date < locked_trip.departure_date:
            raise ValidationError("Actual return date cannot be earlier than the departure date.")

        locked_trip.status = OutstationTrip.STATUS_CLOSED
        locked_trip.actual_return_date = return_date
        if notes.strip():
            locked_trip.notes = (locked_trip.notes + "\n" + f"[Closure Notes]: {notes}").strip()
        locked_trip.save(update_fields=['status', 'actual_return_date', 'notes', 'updated_at'])

        OutstationTripAuditLog.objects.create(
            trip=locked_trip,
            action=OutstationTripAuditLog.ACTION_TRIP_CLOSED,
            user=user,
            details=f"Trip {locked_trip.trip_number} successfully concluded and closed."
        )

    return locked_trip


# ==============================================================================
# EXHIBITION TRANSACTIONAL SERVICES
# ==============================================================================

def issue_items_to_exhibition(exhibition, item_ids, user=None):
    """
    Atomically issue tagged jewellery pieces to an Exhibition booth.

    Security & Stock Invariants:
    1. Items must belong to the exhibition's tenant.
    2. Items must have status == 'Available' and quantity > 0.
    3. Items must not be issued to another active exhibition OR an active outstation trip.
    4. Row-level locking (select_for_update) serializes requests.
    5. Items marked 'Reserved', safely excluding them from showroom counter sales.
    """
    if not item_ids:
        raise ValidationError("No jewellery items selected for exhibition issuance.")

    issued_count = 0
    with transaction.atomic():
        locked_exhibition = Exhibition.objects.select_for_update().get(id=exhibition.id)

        if locked_exhibition.status in [Exhibition.STATUS_CLOSED, Exhibition.STATUS_CANCELLED]:
            raise ValidationError(f"Cannot issue stock to a {locked_exhibition.get_status_display()} exhibition.")

        items = list(
            JewelleryItem.objects
            .select_for_update()
            .filter(id__in=item_ids, tenant_id=locked_exhibition.tenant_id)
        )

        if len(items) != len(set(item_ids)):
            raise ValidationError("One or more selected items do not belong to this showroom.")

        # Check existing active exhibition issuances
        active_exhibition_item_ids = set(
            ExhibitionItem.objects.filter(
                exhibition__tenant_id=locked_exhibition.tenant_id,
                exhibition__status__in=[
                    Exhibition.STATUS_DRAFT,
                    Exhibition.STATUS_ISSUED,
                    Exhibition.STATUS_IN_PROGRESS,
                    Exhibition.STATUS_RECONCILING,
                ],
                status=ExhibitionItem.STATUS_ISSUED,
                item_id__in=item_ids
            ).values_list('item_id', flat=True)
        )

        # Check existing active trip issuances
        active_trip_item_ids = set(
            OutstationTripItem.objects.filter(
                trip__tenant_id=locked_exhibition.tenant_id,
                trip__status__in=[
                    OutstationTrip.STATUS_DRAFT,
                    OutstationTrip.STATUS_ISSUED,
                    OutstationTrip.STATUS_IN_PROGRESS,
                    OutstationTrip.STATUS_RECONCILING,
                ],
                status=OutstationTripItem.STATUS_ISSUED,
                item_id__in=item_ids
            ).values_list('item_id', flat=True)
        )

        for item in items:
            if item.id in active_exhibition_item_ids:
                raise ValidationError(
                    f"Item '{item.name}' ({item.tag_number or item.item_code}) is already issued to an active exhibition."
                )

            if item.id in active_trip_item_ids:
                raise ValidationError(
                    f"Item '{item.name}' ({item.tag_number or item.item_code}) is already issued to an active outstation trip."
                )

            if item.status != 'Available' or (item.quantity or 0) <= 0:
                raise ValidationError(
                    f"Item '{item.name}' ({item.tag_number or item.item_code}) is not available (Current status: {item.status})."
                )

            # Record or update ExhibitionItem
            exh_item, created = ExhibitionItem.objects.get_or_create(
                exhibition=locked_exhibition,
                item=item,
                defaults={
                    'status': ExhibitionItem.STATUS_ISSUED,
                    'issue_price': item.selling_price or Decimal('0.00'),
                    'issue_gross_weight': item.gross_weight,
                    'issue_net_weight': item.net_weight,
                    'issued_at': timezone.now(),
                    'issued_by': user,
                }
            )

            if not created:
                if exh_item.status != ExhibitionItem.STATUS_ISSUED:
                    exh_item.status = ExhibitionItem.STATUS_ISSUED
                    exh_item.issued_at = timezone.now()
                    exh_item.issued_by = user
                    exh_item.save(update_fields=['status', 'issued_at', 'issued_by'])

            # Transition showroom item status to 'Reserved'
            item.status = 'Reserved'
            item.save(update_fields=['status', 'updated_at'])

            issued_count += 1

        if locked_exhibition.status == Exhibition.STATUS_DRAFT and issued_count > 0:
            locked_exhibition.status = Exhibition.STATUS_ISSUED
            locked_exhibition.save(update_fields=['status', 'updated_at'])

        ExhibitionAuditLog.objects.create(
            exhibition=locked_exhibition,
            action=ExhibitionAuditLog.ACTION_STOCK_ISSUED,
            user=user,
            details=f"Issued {issued_count} jewellery pieces to {locked_exhibition.name} ({locked_exhibition.exhibition_number})."
        )

    return issued_count


def record_exhibition_sale(
    exhibition,
    item_id,
    customer,
    sale_price,
    payment_method='Cash',
    buyer_type='B2C',
    business_name='',
    business_gstin='',
    notes='',
    user=None,
    paid_amount=None,
    payment_ref='',
    sale_datetime=None
):
    """
    Record an on-site exhibition sale (B2B wholesale or B2C retail).
    Reuses existing sales.Sale, sales.Payment, and inventory.stock.record_sale.
    """
    with transaction.atomic():
        locked_exhibition = Exhibition.objects.select_for_update().get(id=exhibition.id)
        if locked_exhibition.status in [Exhibition.STATUS_CLOSED, Exhibition.STATUS_CANCELLED]:
            raise ValidationError(f"Cannot record sales on a {locked_exhibition.get_status_display()} exhibition.")

        try:
            exh_item = (
                ExhibitionItem.objects
                .select_for_update()
                .get(exhibition=locked_exhibition, item_id=item_id, status=ExhibitionItem.STATUS_ISSUED)
            )
        except ExhibitionItem.DoesNotExist:
            raise ValidationError("This jewellery piece is not currently in transit or issued to this exhibition booth.")

        try:
            locked_item = JewelleryItem.objects.select_for_update().get(id=item_id, tenant_id=locked_exhibition.tenant_id)
        except JewelleryItem.DoesNotExist:
            raise ValidationError("This jewellery item does not exist or does not belong to this showroom.")

        if customer.tenant_id != locked_exhibition.tenant_id:
            raise ValidationError("Selected buyer/customer belongs to a different showroom.")

        dt = sale_datetime or timezone.now()

        # Core Sale record
        sale = Sale.objects.create(
            tenant=locked_exhibition.tenant,
            customer=customer,
            jewellery_item=locked_item,
            sale_price=Decimal(str(sale_price)),
            sale_date=dt,
            payment_method=payment_method,
            notes=f"Exhibition Sale ({locked_exhibition.name} - Stall {locked_exhibition.stall_number}). {notes}".strip()
        )

        paid_dec = Decimal(str(paid_amount)) if paid_amount is not None else Decimal(str(sale_price))
        if paid_dec > 0:
            Payment.objects.create(
                tenant=locked_exhibition.tenant,
                sale=sale,
                amount=paid_dec,
                payment_method=payment_method,
                payment_date=dt.date() if hasattr(dt, 'date') else dt,
                reference=payment_ref,
                notes=f"Payment received at {locked_exhibition.name}"
            )

        # Execute stock deduction via inventory single source of truth
        locked_item.status = 'Available'
        locked_item.save(update_fields=['status'])
        stock.record_sale(locked_item, sale, user=user, notes=f"Sold at Exhibition #{locked_exhibition.exhibition_number}")

        # Update ExhibitionItem
        exh_item.status = ExhibitionItem.STATUS_SOLD
        exh_item.reconciled_at = timezone.now()
        exh_item.reconciled_by = user
        exh_item.reconciliation_notes = f"Sold at expo (Invoice #{sale.id} to {customer.name})"
        exh_item.save(update_fields=['status', 'reconciled_at', 'reconciled_by', 'reconciliation_notes'])

        # Create ExhibitionSale link
        exh_sale = ExhibitionSale.objects.create(
            exhibition=locked_exhibition,
            sale=sale,
            exhibition_item=exh_item,
            buyer_type=buyer_type,
            business_name=business_name.strip(),
            business_gstin=business_gstin.strip().upper(),
            sale_datetime=dt,
            notes=notes.strip()
        )

        if locked_exhibition.status == Exhibition.STATUS_ISSUED:
            locked_exhibition.status = Exhibition.STATUS_IN_PROGRESS
            locked_exhibition.save(update_fields=['status', 'updated_at'])

        ExhibitionAuditLog.objects.create(
            exhibition=locked_exhibition,
            action=ExhibitionAuditLog.ACTION_SALE_RECORDED,
            user=user,
            details=f"Recorded sale #{sale.id} for piece {locked_item.tag_number or locked_item.item_code} at ₹{sale.sale_price:,.2f}."
        )

    return sale


def record_exhibition_expense(
    exhibition,
    category,
    amount,
    payee,
    expense_date=None,
    payment_method='Bank Transfer',
    reference_number='',
    notes='',
    user=None
):
    """
    Log an exhibition-specific expense (stall rent, airfare, hotel, etc.).
    """
    amount_dec = Decimal(str(amount))
    if amount_dec <= 0:
        raise ValidationError("Expense amount must be greater than zero.")

    with transaction.atomic():
        locked_exhibition = Exhibition.objects.select_for_update().get(id=exhibition.id)

        exp = ExhibitionExpense.objects.create(
            tenant=locked_exhibition.tenant,
            exhibition=locked_exhibition,
            category=category,
            amount=amount_dec,
            expense_date=expense_date or timezone.now().date(),
            payee=payee.strip(),
            payment_method=payment_method,
            reference_number=reference_number.strip(),
            notes=notes.strip(),
            recorded_by=user
        )

        ExhibitionAuditLog.objects.create(
            exhibition=locked_exhibition,
            action=ExhibitionAuditLog.ACTION_EXPENSE_LOGGED,
            user=user,
            details=f"Logged expense: {exp.category} — ₹{exp.amount:,.2f} paid to {exp.payee}."
        )

    return exp


def reconcile_exhibition_item(
    exhibition_item,
    outcome,
    discrepancy_reason='',
    notes='',
    user=None
):
    """
    Reconcile an exhibition item upon return from expo:
    - Returned: Item restored to showroom 'Available' stock.
    - Damaged / Missing: Requires reason, stays unreconciled until manager authorization.
    """
    if outcome not in [ExhibitionItem.STATUS_RETURNED, ExhibitionItem.STATUS_DAMAGED, ExhibitionItem.STATUS_MISSING]:
        raise ValidationError(f"Invalid reconciliation outcome: '{outcome}'.")

    with transaction.atomic():
        locked_item_row = (
            ExhibitionItem.objects
            .select_for_update()
            .select_related('exhibition', 'item')
            .get(id=exhibition_item.id)
        )

        if locked_item_row.status == ExhibitionItem.STATUS_SOLD:
            raise ValidationError("Cannot return or mark missing an item that has already been sold at this exhibition.")

        item = JewelleryItem.objects.select_for_update().get(id=locked_item_row.item_id)

        if outcome == ExhibitionItem.STATUS_RETURNED:
            # Restore to showroom available stock
            item.status = 'Available'
            item.save(update_fields=['status', 'updated_at'])

            locked_item_row.status = ExhibitionItem.STATUS_RETURNED
            locked_item_row.reconciled_at = timezone.now()
            locked_item_row.reconciled_by = user
            locked_item_row.reconciliation_notes = notes.strip()
            locked_item_row.discrepancy_resolved = True
            locked_item_row.save(update_fields=[
                'status', 'reconciled_at', 'reconciled_by', 'reconciliation_notes', 'discrepancy_resolved'
            ])

            ExhibitionAuditLog.objects.create(
                exhibition=locked_item_row.exhibition,
                action=ExhibitionAuditLog.ACTION_STOCK_RETURNED,
                user=user,
                details=f"Item {item.name} ({item.tag_number or item.item_code}) returned safely to showroom stock."
            )

        elif outcome in [ExhibitionItem.STATUS_DAMAGED, ExhibitionItem.STATUS_MISSING]:
            if not discrepancy_reason.strip():
                raise ValidationError("Discrepancy explanation reason is strictly required.")

            locked_item_row.status = outcome
            locked_item_row.reconciled_at = timezone.now()
            locked_item_row.reconciled_by = user
            locked_item_row.discrepancy_reason = discrepancy_reason.strip()
            locked_item_row.discrepancy_resolved = False
            locked_item_row.reconciliation_notes = notes.strip()
            locked_item_row.save(update_fields=[
                'status', 'reconciled_at', 'reconciled_by', 'discrepancy_reason',
                'discrepancy_resolved', 'reconciliation_notes'
            ])

            ExhibitionAuditLog.objects.create(
                exhibition=locked_item_row.exhibition,
                action=ExhibitionAuditLog.ACTION_DISCREPANCY_LOGGED,
                user=user,
                details=(
                    f"Discrepancy logged for {item.name} ({item.tag_number or item.item_code}): "
                    f"{outcome.upper()} — Reason: {discrepancy_reason}"
                )
            )

        if locked_item_row.exhibition.status in [Exhibition.STATUS_ISSUED, Exhibition.STATUS_IN_PROGRESS]:
            locked_item_row.exhibition.status = Exhibition.STATUS_RECONCILING
            locked_item_row.exhibition.save(update_fields=['status', 'updated_at'])

    return locked_item_row


def resolve_exhibition_discrepancy(exhibition_item, resolution_notes, write_off_stock=True, user=None):
    """
    Manager / Administrator authorization to resolve an exhibition discrepancy.
    """
    if not resolution_notes.strip():
        raise ValidationError("Resolution authorization notes are required.")

    with transaction.atomic():
        locked_item_row = (
            ExhibitionItem.objects
            .select_for_update()
            .select_related('exhibition', 'item')
            .get(id=exhibition_item.id)
        )

        if locked_item_row.status not in [ExhibitionItem.STATUS_DAMAGED, ExhibitionItem.STATUS_MISSING]:
            raise ValidationError("This item does not have an active Damaged or Missing discrepancy.")

        item = JewelleryItem.objects.select_for_update().get(id=locked_item_row.item_id)

        if write_off_stock and (item.quantity or 0) > 0:
            reason = 'Lost Item' if locked_item_row.status == ExhibitionItem.STATUS_MISSING else 'Damaged Item'
            stock.apply_stock_change(
                item,
                -1,
                StockMovement.REDUCTION,
                reason=reason,
                notes=f"Discrepancy resolution on Exhibition {locked_item_row.exhibition.exhibition_number}: {resolution_notes}",
                user=user
            )

        locked_item_row.discrepancy_resolved = True
        locked_item_row.discrepancy_resolved_by = user
        locked_item_row.discrepancy_resolution_notes = resolution_notes.strip()
        locked_item_row.save(update_fields=[
            'discrepancy_resolved', 'discrepancy_resolved_by', 'discrepancy_resolution_notes'
        ])

        ExhibitionAuditLog.objects.create(
            exhibition=locked_item_row.exhibition,
            action=ExhibitionAuditLog.ACTION_DISCREPANCY_RESOLVE,
            user=user,
            details=f"Resolved discrepancy for {item.name} ({item.tag_number}): {resolution_notes}."
        )

    return locked_item_row


def close_exhibition(exhibition, user=None, actual_return_date=None, notes=''):
    """
    Conclude and close an exhibition.
    Safeguards:
    1. Zero pieces in transit / at booth (status 'Issued').
    2. Zero unresolved damaged or missing discrepancies.
    """
    with transaction.atomic():
        locked_exhibition = Exhibition.objects.select_for_update().get(id=exhibition.id)

        if locked_exhibition.status == Exhibition.STATUS_CLOSED:
            raise ValidationError("This exhibition is already closed.")

        outstanding = locked_exhibition.issued_items.filter(status=ExhibitionItem.STATUS_ISSUED).count()
        if outstanding > 0:
            raise ValidationError(
                f"Cannot close exhibition: {outstanding} jewellery item(s) are still recorded as in-transit at the booth. "
                "Every item must be either marked as Sold, Returned to showroom, or logged as a discrepancy."
            )

        unresolved = locked_exhibition.unresolved_discrepancies_count
        if unresolved > 0:
            raise ValidationError(
                f"Cannot close exhibition: {unresolved} damaged or missing item discrepancy requires manager resolution."
            )

        return_date = actual_return_date or timezone.now().date()
        if return_date < locked_exhibition.start_date:
            raise ValidationError("Actual return date cannot be earlier than the exhibition start date.")

        locked_exhibition.status = Exhibition.STATUS_CLOSED
        locked_exhibition.actual_return_date = return_date
        if notes.strip():
            locked_exhibition.notes = (locked_exhibition.notes + "\n" + f"[Closure Notes]: {notes}").strip()
        locked_exhibition.save(update_fields=['status', 'actual_return_date', 'notes', 'updated_at'])

        ExhibitionAuditLog.objects.create(
            exhibition=locked_exhibition,
            action=ExhibitionAuditLog.ACTION_EXHIBITION_CLOSED,
            user=user,
            details=f"Exhibition {locked_exhibition.exhibition_number} successfully concluded and closed."
        )

    return locked_exhibition
