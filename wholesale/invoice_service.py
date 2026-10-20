"""
wholesale/invoice_service.py
----------------------------
Billing, invoicing, payment posting, and double-entry ledger management
for Wholesale Jewellery Suppliers.
"""

from decimal import Decimal
import logging
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    WholesaleOrder,
    WholesaleDispatch,
    WholesaleInvoice,
    WholesaleInvoiceItem,
    WholesaleSequence,
    RetailerPayment,
    RetailerPaymentAllocation,
    RetailerLedgerEntry,
    WholesaleReturn,
)

logger = logging.getLogger('wholesale.invoice_service')


def create_invoice_for_order(order, dispatch=None, due_days=None, notes='', user=None):
    """
    Generate a WholesaleInvoice from an order or dispatch:
      1. Generates unique sequential invoice number (e.g. WINV-00001).
      2. Snapshots items, quantities, locked prices and tax rates.
      3. Records immutable RetailerLedgerEntry debit against the party.
    """
    tenant = order.tenant
    party = order.party

    with transaction.atomic():
        invoice_num = WholesaleSequence.get_next_number(tenant, 'invoice', prefix='WINV')

        if due_days is None:
            due_days = party.payment_terms_days or 30

        inv_date = timezone.localdate()
        due_date = inv_date + timezone.timedelta(days=int(due_days))

        # Items to invoice: if dispatch provided, invoice dispatched items; else all order items
        if dispatch:
            invoice_source_items = [
                (di.item, di.quantity, di.order_item.unit_price, di.order_item.tax_rate)
                for di in dispatch.items.select_related('item', 'order_item').all()
            ]
        else:
            invoice_source_items = [
                (oi.item, oi.quantity, oi.unit_price, oi.tax_rate)
                for oi in order.items.select_related('item').all()
            ]

        if not invoice_source_items:
            raise ValidationError("Cannot create an invoice with zero items.")

        subtotal = Decimal('0.00')
        tax_total = Decimal('0.00')

        invoice = WholesaleInvoice.objects.create(
            tenant=tenant,
            invoice_number=invoice_num,
            order=order,
            dispatch=dispatch,
            party=party,
            invoice_date=inv_date,
            due_date=due_date,
            subtotal=Decimal('0.00'),
            tax_amount=Decimal('0.00'),
            total_amount=Decimal('0.00'),
            notes=notes,
            created_by=user,
            status=WholesaleInvoice.STATUS_UNPAID,
        )

        for itm, qty, u_price, t_rate in invoice_source_items:
            line_sub = (Decimal(str(qty)) * Decimal(str(u_price))).quantize(Decimal('0.01'))
            line_tax = (line_sub * (Decimal(str(t_rate)) / Decimal('100.00'))).quantize(Decimal('0.01'))
            subtotal += line_sub
            tax_total += line_tax

            WholesaleInvoiceItem.objects.create(
                invoice=invoice,
                item=itm,
                quantity=qty,
                unit_price=u_price,
                tax_rate=t_rate,
                tax_amount=line_tax,
                total_price=line_sub + line_tax,
            )

        total_amount = subtotal + tax_total
        invoice.subtotal = subtotal
        invoice.tax_amount = tax_total
        invoice.total_amount = total_amount
        invoice.save(update_fields=['subtotal', 'tax_amount', 'total_amount'])

        # Record debit in RetailerLedgerEntry
        RetailerLedgerEntry.record_entry(
            tenant=tenant,
            party=party,
            entry_type=RetailerLedgerEntry.TYPE_INVOICE,
            reference_number=invoice.invoice_number,
            debit_amount=total_amount,
            credit_amount=Decimal('0.00'),
            description=f"Tax Invoice #{invoice.invoice_number} for Order #{order.order_number}",
            invoice=invoice,
            entry_date=inv_date
        )

        return invoice


def record_retailer_payment(party, amount, payment_method='Bank Transfer', reference='', notes='', allocations_data=None, user=None):
    """
    Record payment received from a retailer party:
      1. Generates unique payment reference (WREC-00001).
      2. Creates RetailerPayment record.
      3. Allocates payment towards specified invoices (or auto-allocates to oldest unpaid invoices).
      4. Updates invoice payment statuses.
      5. Records immutable RetailerLedgerEntry credit.
    """
    tenant = party.tenant
    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValidationError("Payment amount must be greater than zero.")

    with transaction.atomic():
        payment_num = WholesaleSequence.get_next_number(tenant, 'payment', prefix='WREC')
        pay_date = timezone.localdate()

        payment = RetailerPayment.objects.create(
            tenant=tenant,
            payment_number=payment_num,
            party=party,
            amount=amount,
            payment_date=pay_date,
            payment_method=payment_method,
            reference=reference,
            notes=notes,
            created_by=user,
        )

        remaining_to_allocate = amount

        # Handle specific allocations if provided
        if allocations_data:
            for alloc in allocations_data:
                inv_id = alloc.get('invoice_id')
                alloc_amt = Decimal(str(alloc.get('amount', 0)))
                if alloc_amt <= 0 or remaining_to_allocate <= 0:
                    continue

                actual_alloc = min(alloc_amt, remaining_to_allocate)
                inv = WholesaleInvoice.objects.select_for_update().get(pk=inv_id, party=party)
                if actual_alloc > inv.outstanding_amount:
                    actual_alloc = inv.outstanding_amount

                if actual_alloc > 0:
                    RetailerPaymentAllocation.objects.create(
                        payment=payment,
                        invoice=inv,
                        allocated_amount=actual_alloc
                    )
                    inv.update_payment_status()
                    remaining_to_allocate -= actual_alloc

        # If any payment amount remains unallocated, auto-allocate to oldest unpaid invoices
        if remaining_to_allocate > 0:
            unpaid_invoices = WholesaleInvoice.objects.filter(
                party=party,
                status__in=[WholesaleInvoice.STATUS_UNPAID, WholesaleInvoice.STATUS_PARTIALLY_PAID]
            ).exclude(status=WholesaleInvoice.STATUS_CANCELLED).order_by('invoice_date', 'id').select_for_update()

            for inv in unpaid_invoices:
                if remaining_to_allocate <= 0:
                    break
                due = inv.outstanding_amount
                if due <= 0:
                    continue
                alloc_amt = min(due, remaining_to_allocate)
                RetailerPaymentAllocation.objects.create(
                    payment=payment,
                    invoice=inv,
                    allocated_amount=alloc_amt
                )
                inv.update_payment_status()
                remaining_to_allocate -= alloc_amt

        # Record credit in RetailerLedgerEntry
        RetailerLedgerEntry.record_entry(
            tenant=tenant,
            party=party,
            entry_type=RetailerLedgerEntry.TYPE_PAYMENT,
            reference_number=payment.payment_number,
            debit_amount=Decimal('0.00'),
            credit_amount=amount,
            description=f"Payment Received via {payment.payment_method} Ref: {reference or 'N/A'}",
            payment=payment,
            entry_date=pay_date
        )

        return payment


def issue_wholesale_credit_note(wholesale_return, user=None):
    """
    Issue an official credit note for an approved wholesale return:
      1. Generates unique Credit Note reference (WCN-00001).
      2. Marks return as credit_note_issued.
      3. Records immutable RetailerLedgerEntry credit against party receivables.
    """
    tenant = wholesale_return.tenant
    party = wholesale_return.party

    with transaction.atomic():
        wholesale_return = WholesaleReturn.objects.select_for_update().get(pk=wholesale_return.pk)
        if wholesale_return.status not in (WholesaleReturn.STATUS_APPROVED, WholesaleReturn.STATUS_RESTOCKED, WholesaleReturn.STATUS_COMPLETED):
            raise ValidationError(f"Cannot issue credit note for return in '{wholesale_return.status}' status.")

        if wholesale_return.credit_note_issued:
            raise ValidationError("Credit note has already been issued for this return.")

        cn_num = WholesaleSequence.get_next_number(tenant, 'credit_note', prefix='WCN')
        wholesale_return.credit_note_number = cn_num
        wholesale_return.credit_note_issued = True
        wholesale_return.status = WholesaleReturn.STATUS_COMPLETED
        wholesale_return.save(update_fields=['credit_note_number', 'credit_note_issued', 'status'])

        RetailerLedgerEntry.record_entry(
            tenant=tenant,
            party=party,
            entry_type=RetailerLedgerEntry.TYPE_CREDIT_NOTE,
            reference_number=cn_num,
            debit_amount=Decimal('0.00'),
            credit_amount=wholesale_return.total_credit_amount,
            description=f"Credit Note #{cn_num} for Return #{wholesale_return.return_number} ({wholesale_return.reason})",
            return_ref=wholesale_return,
            entry_date=timezone.localdate()
        )

        return wholesale_return
