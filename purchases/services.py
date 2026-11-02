"""
purchases/services.py
---------------------
Core business logic for the Purchase Management Module:
- Inward invoice confirmation & atomic inventory intake
- Supplier accounts payable ledger maintenance
- Outward supplier payments & invoice balance settlements
- Purchase returns & stock adjustments
"""
from decimal import Decimal
import logging
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from inventory.models import JewelleryItem, StockMovement, Category
from inventory import stock as inventory_stock
from .models import (
    Supplier,
    PurchaseSetting,
    PurchaseInvoice,
    PurchaseItem,
    SupplierPayment,
    SupplierLedgerEntry,
    PurchaseReturn,
    PurchaseReturnItem,
)

logger = logging.getLogger('purchases.services')


# ==============================================================================
# INVOICE CONFIRMATION & INVENTORY SYNC
# ==============================================================================

def confirm_purchase_invoice(invoice_id, user=None):
    """
    Idempotent confirmation of a draft purchase invoice.
    1. Locks the invoice row using select_for_update().
    2. Recalculates exact financial totals.
    3. Auto-creates inventory JewelleryItems for ready-made & bullion items.
    4. Records immutable StockMovement audit entries via inventory.stock.
    5. Posts credit entry to SupplierLedgerEntry.
    6. Updates Supplier.current_balance.
    """
    with transaction.atomic():
        invoice = PurchaseInvoice.objects.select_for_update().get(pk=invoice_id)

        if invoice.status != 'DRAFT':
            raise ValidationError(f"Invoice {invoice.purchase_number} is already {invoice.get_status_display()} and cannot be confirmed again.")

        if invoice.inventory_status == 'STOCKED':
            raise ValidationError(f"Inventory has already been stocked for invoice {invoice.purchase_number}.")

        # Ensure all totals are up to date
        invoice.recalculate_totals(save=True)

        settings_obj = PurchaseSetting.load(tenant=invoice.tenant)
        items = invoice.items.select_for_update().all()

        if not items.exists():
            raise ValidationError("Cannot confirm a purchase invoice with zero line items.")

        # Inventory Intake
        should_stock_ready_made = settings_obj.auto_create_inventory_for_ready_made
        should_stock_bullion = settings_obj.auto_create_inventory_for_bullion

        created_inventory_count = 0

        for item in items:
            is_ready_made = (invoice.purchase_type == 'READY_MADE' or item.metal_type in ['Gold', 'Silver', 'Diamond', 'Platinum', 'Gemstone'])
            is_bullion = (invoice.purchase_type in ['BULLION', 'GOLD', 'SILVER'] and 'bullion' in (item.item_name or '').lower())

            create_stock = (is_ready_made and should_stock_ready_made) or (is_bullion and should_stock_bullion)

            if create_stock and not item.inventory_item:
                # Generate unique piece code based on shop's series settings
                generated_code = JewelleryItem.generate_next_item_code(
                    tenant=invoice.tenant,
                    metal_type=item.metal_type,
                    category=item.category
                )

                # Ensure a valid category fallback
                cat = item.category
                if not cat:
                    cat = Category.objects.filter(tenant=invoice.tenant, name__iexact='General').first()
                    if not cat:
                        cat = Category.objects.filter(tenant=invoice.tenant).first()

                # Calculate item selling price (cost basis from purchase)
                cost_price = item.line_total

                jewellery_item = JewelleryItem(
                    tenant=invoice.tenant,
                    branch=invoice.branch,
                    item_code=generated_code,
                    name=item.item_name,
                    category=cat,
                    metal_type=item.metal_type if item.metal_type in ['Gold', 'Silver', 'Platinum', 'Diamond'] else 'Gold',
                    purity=item.purity or '22K',
                    gross_weight=item.gross_weight or Decimal('0.000'),
                    stone_weight=item.stone_weight or Decimal('0.000'),
                    net_weight=item.net_weight or Decimal('0.000'),
                    quantity=item.quantity or 1,
                    status='Available',
                    huid=item.huid or '',
                    selling_price=cost_price # Default initial tag price matching procurement cost
                )
                jewellery_item.full_clean()
                jewellery_item.save()

                # Record immutable StockMovement audit
                inventory_stock.record_initial_stock(
                    jewellery_item,
                    user=user,
                    reason='New Stock Received',
                    notes=f"Purchase Intake from #{invoice.purchase_number} (Supplier: {invoice.supplier.name})"
                )

                item.inventory_item = jewellery_item
                item.save(update_fields=['inventory_item'])
                created_inventory_count += 1

        # Transition invoice state
        invoice.status = 'CONFIRMED'
        invoice.inventory_status = 'STOCKED' if created_inventory_count > 0 else 'NOT_APPLICABLE'
        invoice.confirmed_by = user
        invoice.confirmed_at = timezone.now()
        invoice.save(update_fields=['status', 'inventory_status', 'confirmed_by', 'confirmed_at', 'updated_at'])

        # Post Credit to Supplier Ledger (increases amount shop owes supplier)
        SupplierLedgerEntry.objects.create(
            tenant=invoice.tenant,
            branch=invoice.branch,
            supplier=invoice.supplier,
            entry_type='PURCHASE_INVOICE',
            entry_date=invoice.purchase_date,
            reference_number=invoice.purchase_number,
            debit_amount=Decimal('0.00'),
            credit_amount=invoice.grand_total,
            balance_after=Decimal('0.00'), # recalculated next
            purchase_invoice=invoice,
            description=f"Purchase Invoice #{invoice.purchase_number} (Vendor Bill: {invoice.supplier_invoice_number or 'N/A'})"
        )

        invoice.supplier.recalculate_balance()
        logger.info(f"Purchase invoice {invoice.purchase_number} confirmed successfully. Created {created_inventory_count} inventory items.")
        return invoice


def cancel_purchase_invoice(invoice_id, user=None, reason=''):
    """
    Safely cancel a purchase invoice.
    - If DRAFT: cancels directly.
    - If CONFIRMED: reverses inventory if not sold, reverses ledger credit.
    """
    with transaction.atomic():
        invoice = PurchaseInvoice.objects.select_for_update().get(pk=invoice_id)

        if invoice.status == 'CANCELLED':
            raise ValidationError(f"Invoice {invoice.purchase_number} is already cancelled.")

        if invoice.amount_paid > Decimal('0.00'):
            raise ValidationError(f"Cannot cancel invoice {invoice.purchase_number} because payments of ₹{invoice.amount_paid:,.2f} have already been recorded. Please cancel linked payments first.")

        if invoice.returns.filter(status='CONFIRMED').exists():
            raise ValidationError(f"Cannot cancel invoice {invoice.purchase_number} because active purchase returns exist.")

        if invoice.status == 'CONFIRMED':
            # Reverse inventory stock for items created from this purchase
            for item in invoice.items.all():
                if item.inventory_item:
                    inv = item.inventory_item
                    if inv.status == 'Sold' or inv.quantity < item.quantity:
                        raise ValidationError(f"Cannot cancel invoice: inventory item '{inv.item_code}' ({inv.name}) has already been sold or transferred.")
                    # Remove from stock
                    inventory_stock.apply_stock_change(
                        inv,
                        -item.quantity,
                        movement_type=StockMovement.REDUCTION,
                        reason='Stock Correction',
                        notes=f"Cancelled Purchase #{invoice.purchase_number}: {reason}",
                        user=user
                    )

            # Reverse Supplier Ledger Credit
            SupplierLedgerEntry.objects.create(
                tenant=invoice.tenant,
                branch=invoice.branch,
                supplier=invoice.supplier,
                entry_type='ADJUSTMENT',
                entry_date=timezone.localdate(),
                reference_number=f"CNL-{invoice.purchase_number}",
                debit_amount=invoice.grand_total,
                credit_amount=Decimal('0.00'),
                balance_after=Decimal('0.00'),
                purchase_invoice=invoice,
                description=f"Cancellation reversal of Purchase Invoice #{invoice.purchase_number} ({reason or 'Invoice Cancelled'})"
            )
            invoice.supplier.recalculate_balance()

        invoice.status = 'CANCELLED'
        invoice.notes = f"{invoice.notes}\n[Cancelled by {getattr(user, 'username', 'System')} on {timezone.now().strftime('%Y-%m-%d %H:%M')}: {reason}]".strip()
        invoice.save(update_fields=['status', 'notes', 'updated_at'])
        return invoice


# ==============================================================================
# SUPPLIER PAYMENTS & SETTLEMENTS
# ==============================================================================

def record_supplier_payment(tenant, supplier, amount, payment_method='Bank Transfer',
                            purchase_invoice=None, branch=None, user=None,
                            reference='', bank_name='', notes='', payment_date=None):
    """
    Record an outward settlement payment made to a supplier.
    - If purchase_invoice is provided, updates invoice.amount_paid and invoice.balance_amount.
    - Updates invoice status to PAID or PARTIALLY_PAID.
    - Posts debit entry to SupplierLedgerEntry (reduces liability).
    - Recalculates supplier balance.
    """
    amount = Decimal(str(amount)).quantize(Decimal('0.01'))
    if amount <= Decimal('0.00'):
        raise ValidationError("Payment amount must be greater than zero.")

    payment_date = payment_date or timezone.localdate()

    with transaction.atomic():
        if purchase_invoice:
            invoice = PurchaseInvoice.objects.select_for_update().get(pk=purchase_invoice.pk)
            if invoice.status not in ['CONFIRMED', 'PARTIALLY_PAID']:
                raise ValidationError(f"Cannot record payment for invoice {invoice.purchase_number} with status '{invoice.get_status_display()}'.")
            if amount > invoice.balance_amount:
                raise ValidationError(f"Payment amount (₹{amount:,.2f}) cannot exceed invoice balance (₹{invoice.balance_amount:,.2f}).")
        else:
            invoice = None

        payment = SupplierPayment(
            tenant=tenant,
            branch=branch or (invoice.branch if invoice else None),
            supplier=supplier,
            purchase_invoice=invoice,
            payment_date=payment_date,
            amount=amount,
            payment_method=payment_method,
            reference=reference,
            bank_name=bank_name,
            notes=notes,
            created_by=user
        )
        payment.save()

        # Update invoice balance if payment is tied to an invoice
        if invoice:
            invoice.amount_paid += amount
            invoice.balance_amount = max(Decimal('0.00'), invoice.grand_total - invoice.amount_paid)
            if invoice.balance_amount == Decimal('0.00'):
                invoice.status = 'PAID'
            else:
                invoice.status = 'PARTIALLY_PAID'
            invoice.save(update_fields=['amount_paid', 'balance_amount', 'status', 'updated_at'])

        # Post Debit to Supplier Ledger (reduces amount shop owes)
        ref_text = f"Payment #{payment.payment_number}"
        if invoice:
            ref_text += f" for Inv #{invoice.purchase_number}"

        SupplierLedgerEntry.objects.create(
            tenant=tenant,
            branch=branch or (invoice.branch if invoice else None),
            supplier=supplier,
            entry_type='PAYMENT',
            entry_date=payment_date,
            reference_number=payment.payment_number,
            debit_amount=amount,
            credit_amount=Decimal('0.00'),
            balance_after=Decimal('0.00'),
            payment=payment,
            purchase_invoice=invoice,
            description=f"Payment via {payment_method} ({reference or 'Direct'}) - {notes or 'Supplier Settlement'}"
        )

        supplier.recalculate_balance()
        logger.info(f"Recorded supplier payment {payment.payment_number} of ₹{amount:,.2f} for {supplier.name}.")
        return payment


def cancel_supplier_payment(payment_id, user=None, reason=''):
    """
    Auditable cancellation of a supplier payment.
    Reverses invoice amount_paid, restores status, and logs reversing ledger debit.
    """
    with transaction.atomic():
        payment = SupplierPayment.objects.select_for_update().get(pk=payment_id)

        if payment.is_cancelled:
            raise ValidationError(f"Payment {payment.payment_number} is already cancelled.")

        if payment.purchase_invoice:
            invoice = PurchaseInvoice.objects.select_for_update().get(pk=payment.purchase_invoice.pk)
            invoice.amount_paid = max(Decimal('0.00'), invoice.amount_paid - payment.amount)
            invoice.balance_amount = max(Decimal('0.00'), invoice.grand_total - invoice.amount_paid)
            if invoice.balance_amount >= invoice.grand_total:
                invoice.status = 'CONFIRMED'
            else:
                invoice.status = 'PARTIALLY_PAID'
            invoice.save(update_fields=['amount_paid', 'balance_amount', 'status', 'updated_at'])

        # Post Reversing Ledger Entry (Credit to restore balance owed)
        SupplierLedgerEntry.objects.create(
            tenant=payment.tenant,
            branch=payment.branch,
            supplier=payment.supplier,
            entry_type='ADJUSTMENT',
            entry_date=timezone.localdate(),
            reference_number=f"REV-{payment.payment_number}",
            debit_amount=Decimal('0.00'),
            credit_amount=payment.amount,
            balance_after=Decimal('0.00'),
            payment=payment,
            purchase_invoice=payment.purchase_invoice,
            description=f"Reversal of cancelled payment #{payment.payment_number} ({reason or 'Cancelled'})"
        )

        payment.is_cancelled = True
        payment.cancelled_by = user
        payment.cancelled_at = timezone.now()
        payment.cancellation_reason = reason
        payment.save(update_fields=['is_cancelled', 'cancelled_by', 'cancelled_at', 'cancellation_reason'])

        payment.supplier.recalculate_balance()
        logger.info(f"Cancelled supplier payment {payment.payment_number} of ₹{payment.amount:,.2f}.")
        return payment


# ==============================================================================
# PURCHASE RETURNS & DEBIT NOTES
# ==============================================================================

def process_purchase_return(invoice_id, return_items_data, reason='Defective',
                            adjustment_mode='REDUCE_INVOICE_BALANCE', user=None,
                            notes='', return_date=None):
    """
    Executes a purchase return against a confirmed purchase invoice.
    1. Validates return quantity does not exceed original item quantity minus previous returns.
    2. Decrements inventory stock using inventory.stock.apply_stock_change.
    3. Issues PurchaseReturn voucher.
    4. Posts Debit to SupplierLedgerEntry.
    5. Adjusts invoice balance or marks as returned.
    """
    return_date = return_date or timezone.localdate()

    with transaction.atomic():
        invoice = PurchaseInvoice.objects.select_for_update().get(pk=invoice_id)

        if invoice.status not in ['CONFIRMED', 'PARTIALLY_PAID', 'PAID']:
            raise ValidationError(f"Returns can only be processed against confirmed invoices, not '{invoice.get_status_display()}'.")

        purchase_return = PurchaseReturn(
            tenant=invoice.tenant,
            branch=invoice.branch,
            original_invoice=invoice,
            supplier=invoice.supplier,
            return_date=return_date,
            adjustment_mode=adjustment_mode,
            reason=reason,
            notes=notes,
            status='CONFIRMED',
            created_by=user
        )
        purchase_return.save()

        total_qty = 0
        total_wt = Decimal('0.000')
        total_amt = Decimal('0.00')

        for data in return_items_data:
            item_id = data.get('item_id')
            ret_qty = int(data.get('quantity', 0))
            ret_wt = Decimal(str(data.get('weight', 0))).quantize(Decimal('0.001'))

            if ret_qty <= 0:
                continue

            purchase_item = PurchaseItem.objects.select_for_update().get(pk=item_id, purchase=invoice)

            avail_return_qty = purchase_item.quantity - purchase_item.returned_quantity
            if ret_qty > avail_return_qty:
                raise ValidationError(f"Cannot return {ret_qty} pcs of '{purchase_item.item_name}': only {avail_return_qty} pcs remaining on invoice.")

            # Calculate return rate & amount based on line total per piece
            unit_rate = (purchase_item.line_total / Decimal(purchase_item.quantity)).quantize(Decimal('0.01'))
            ret_amt = (unit_rate * Decimal(ret_qty)).quantize(Decimal('0.01'))

            # Decrement inventory stock if linked
            if purchase_item.inventory_item:
                inv = purchase_item.inventory_item
                if inv.quantity < ret_qty:
                    raise ValidationError(f"Cannot return {ret_qty} pcs of '{inv.name}': only {inv.quantity} pcs physically remaining in stock.")
                inventory_stock.apply_stock_change(
                    inv,
                    -ret_qty,
                    movement_type=StockMovement.REDUCTION,
                    reason='Stock Correction',
                    notes=f"Purchase Return on Debit Note #{purchase_return.return_number} (Invoice #{invoice.purchase_number})",
                    user=user
                )

            PurchaseReturnItem.objects.create(
                purchase_return=purchase_return,
                purchase_item=purchase_item,
                returned_quantity=ret_qty,
                returned_weight=ret_wt,
                return_rate=unit_rate,
                return_amount=ret_amt,
                reason=data.get('reason', reason)
            )

            purchase_item.returned_quantity += ret_qty
            purchase_item.returned_weight += ret_wt
            purchase_item.save(update_fields=['returned_quantity', 'returned_weight'])

            total_qty += ret_qty
            total_wt += ret_wt
            total_amt += ret_amt

        if total_qty == 0:
            raise ValidationError("No valid items or quantities specified for return.")

        purchase_return.total_return_quantity = total_qty
        purchase_return.total_return_weight = total_wt
        purchase_return.total_return_amount = total_amt
        purchase_return.save(update_fields=['total_return_quantity', 'total_return_weight', 'total_return_amount'])

        # Update invoice inventory status
        total_purchased_qty = sum(item.quantity for item in invoice.items.all())
        total_returned_qty = sum(item.returned_quantity for item in invoice.items.all())

        if total_returned_qty >= total_purchased_qty:
            invoice.inventory_status = 'RETURNED'
        else:
            invoice.inventory_status = 'PARTIALLY_RETURNED'

        # Financial Adjustment
        if adjustment_mode == 'REDUCE_INVOICE_BALANCE':
            invoice.balance_amount = max(Decimal('0.00'), invoice.balance_amount - total_amt)
            if invoice.balance_amount == Decimal('0.00') and invoice.amount_paid > Decimal('0.00'):
                invoice.status = 'PAID'
        invoice.save(update_fields=['inventory_status', 'balance_amount', 'status', 'updated_at'])

        # Post Debit to Supplier Ledger (reduces amount shop owes)
        SupplierLedgerEntry.objects.create(
            tenant=invoice.tenant,
            branch=invoice.branch,
            supplier=invoice.supplier,
            entry_type='PURCHASE_RETURN',
            entry_date=return_date,
            reference_number=purchase_return.return_number,
            debit_amount=total_amt,
            credit_amount=Decimal('0.00'),
            balance_after=Decimal('0.00'),
            purchase_return=purchase_return,
            purchase_invoice=invoice,
            description=f"Purchase Return #{purchase_return.return_number} for Invoice #{invoice.purchase_number} ({reason})"
        )

        invoice.supplier.recalculate_balance()
        logger.info(f"Processed purchase return {purchase_return.return_number} of {total_qty} pcs (₹{total_amt:,.2f}) for {invoice.supplier.name}.")
        return purchase_return
