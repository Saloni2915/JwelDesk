"""
girvi/services.py
-----------------
Core business logic and financial calculations for the JwelDesk Girvi module.

Rules:
1. All financial calculations use Decimal arithmetic, never floats.
2. Loan interest rates and calculation terms are snapshotted on GirviLoan.
   Changing GirviSetting defaults never alters historical or active loans.
3. Inventory safety: Collateral pieces are recorded in GirviItem only.
   Zero interaction or mutation with inventory.JewelleryItem stock counts.
4. Tenant and branch isolation is strictly enforced at database query level.
5. All financial mutations (loan creation, payments, reversals, waivers, releases)
   run inside database transactions and write immutable GirviAuditLog entries.
"""

from decimal import Decimal, ROUND_HALF_UP
import datetime
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied

from .models import (
    GirviSetting,
    GirviSequence,
    GirviLoan,
    GirviItem,
    GirviPayment,
    GirviWaiver,
    GirviAuditLog,
)


def get_or_create_girvi_settings(tenant):
    """Retrieve or create showroom-level Girvi configuration defaults for the tenant."""
    settings_obj, _ = GirviSetting.objects.get_or_create(
        tenant=tenant,
        defaults={
            'loan_number_prefix': 'GIR-',
            'payment_number_prefix': 'PAY-GIR-',
            'default_interest_rate_monthly': Decimal('2.00'),
            'default_interest_period': 'monthly',
            'default_calculation_type': 'simple_monthly',
            'default_loan_duration_months': 12,
            'default_grace_period_days': 7,
            'standard_terms_conditions': (
                "1. All pledged articles are held under showroom custody in safe vault.\n"
                "2. Interest is payable monthly on or before the due date.\n"
                "3. In case of default beyond the grace period, notice will be served before auction.\n"
                "4. Customer must present this original voucher and valid ID at the time of redemption.\n"
                "5. Release of pledged articles is subject to complete settlement of principal and interest."
            ),
        }
    )
    return settings_obj


def get_next_sequence_number(tenant, sequence_type='loan', prefix=None):
    """
    Atomically increment and return the next formatted sequence number for a tenant.
    Uses select_for_update inside a transaction to prevent race conditions.
    """
    with transaction.atomic():
        seq, _ = GirviSequence.objects.select_for_update().get_or_create(
            tenant=tenant,
            sequence_type=sequence_type,
            defaults={'last_number': 0}
        )
        seq.last_number += 1
        seq.save(update_fields=['last_number'])
        number = seq.last_number

    if prefix is None:
        settings_obj = get_or_create_girvi_settings(tenant)
        if sequence_type == 'loan':
            prefix = settings_obj.loan_number_prefix or 'GIR-'
        elif sequence_type == 'payment':
            prefix = settings_obj.payment_number_prefix or 'PAY-GIR-'
        elif sequence_type == 'release':
            prefix = 'REL-GIR-'
        else:
            prefix = f"{sequence_type.upper()}-"

    return f"{prefix}{number:05d}"


def calculate_loan_financials(loan, as_of_date=None):
    """
    Calculate full financial position of a Girvi loan as of a specific date (defaults to today).
    
    Returns a dictionary with:
    - as_of_date: Date calculated up to
    - days_elapsed: Calendar days between loan_date and as_of_date
    - effective_days: Days used for interest calculation (considering minimum_interest_days)
    - accrued_interest: Total interest accrued from loan date to as_of_date
    - processing_charges: Contractual processing charges
    - total_principal: Original disbursed principal
    - principal_paid: Sum of non-reversed payments allocated to principal
    - interest_paid: Sum of non-reversed payments allocated to interest
    - charges_paid: Sum of non-reversed payments allocated to processing charges
    - total_paid: Sum of all non-reversed payments
    - interest_waived: Sum of explicit interest waivers
    - charges_waived: Sum of explicit charges waivers
    - total_waived: Sum of all waivers
    - remaining_principal: Outstanding principal balance
    - remaining_interest: Outstanding accrued interest balance (accrued - paid - waived)
    - remaining_charges: Outstanding charges balance (charges - paid - waived)
    - outstanding_balance: Grand total remaining payable (principal + interest + charges)
    - is_settled: True if outstanding_balance <= 0
    - is_overdue: True if loan is active and maturity_date + grace_period_days < as_of_date
    - days_overdue: Days past maturity
    """
    if as_of_date is None:
        as_of_date = timezone.localdate()

    if isinstance(as_of_date, datetime.datetime):
        as_of_date = as_of_date.date()

    loan_date = loan.loan_date
    if isinstance(loan_date, datetime.datetime):
        loan_date = loan_date.date()

    # Days elapsed
    days_elapsed = max(0, (as_of_date - loan_date).days)
    effective_days = max(days_elapsed, loan.minimum_interest_days or 0)

    # Base financial parameters from snapshotted contract
    principal = loan.principal_amount or Decimal('0.00')
    rate_percent = loan.interest_rate_percent or Decimal('0.00')
    period = loan.interest_period or GirviLoan.PERIOD_MONTHLY
    calc_type = loan.interest_calculation_type or GirviLoan.CALC_SIMPLE_MONTHLY
    rate_decimal = rate_percent / Decimal('100.00')

    # Calculate Accrued Interest
    accrued_interest = Decimal('0.00')
    if principal > 0 and rate_percent > 0:
        if calc_type == GirviLoan.CALC_SIMPLE_DAILY:
            # Exact daily interest
            if period == GirviLoan.PERIOD_MONTHLY:
                # rate per month -> daily = rate / 30
                daily_rate = rate_decimal / Decimal('30.00')
            elif period == GirviLoan.PERIOD_YEARLY:
                # rate per year -> daily = rate / 365
                daily_rate = rate_decimal / Decimal('365.00')
            else:  # daily
                daily_rate = rate_decimal

            accrued_interest = (principal * daily_rate * Decimal(str(effective_days))).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )

        elif calc_type == GirviLoan.CALC_FIXED_MONTHLY:
            # Rounded up to full month (minimum 1 month if effective_days > 0)
            if effective_days == 0:
                months_count = Decimal('0')
            else:
                months_count = Decimal(str((effective_days + 29) // 30))
            
            if period == GirviLoan.PERIOD_MONTHLY:
                monthly_rate = rate_decimal
            elif period == GirviLoan.PERIOD_YEARLY:
                monthly_rate = rate_decimal / Decimal('12.00')
            else:
                monthly_rate = rate_decimal * Decimal('30.00')

            accrued_interest = (principal * monthly_rate * months_count).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )

        else:
            # CALC_SIMPLE_MONTHLY (default): standard Indian jewellery pawnshop formula
            # Full months count + remaining days pro-rata (days % 30) / 30
            full_months = effective_days // 30
            remainder_days = effective_days % 30
            effective_months = Decimal(str(full_months)) + (Decimal(str(remainder_days)) / Decimal('30.00'))

            if period == GirviLoan.PERIOD_MONTHLY:
                monthly_rate = rate_decimal
            elif period == GirviLoan.PERIOD_YEARLY:
                monthly_rate = rate_decimal / Decimal('12.00')
            else:
                monthly_rate = rate_decimal * Decimal('30.00')

            accrued_interest = (principal * monthly_rate * effective_months).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )

    # Payments aggregation (filter out reversed payments and reversal entries)
    payments_qs = loan.payments.filter(is_reversal=False)
    principal_paid = Decimal('0.00')
    interest_paid = Decimal('0.00')
    charges_paid = Decimal('0.00')
    total_paid = Decimal('0.00')

    for p in payments_qs:
        principal_paid += (p.principal_portion or Decimal('0.00'))
        interest_paid += (p.interest_portion or Decimal('0.00'))
        charges_paid += (p.charges_portion or Decimal('0.00'))
        total_paid += (p.total_amount_received or Decimal('0.00'))

    # Waivers aggregation
    waivers_qs = loan.waivers.all()
    interest_waived = Decimal('0.00')
    charges_waived = Decimal('0.00')
    penalty_waived = Decimal('0.00')

    for w in waivers_qs:
        if w.waiver_type == GirviWaiver.WAIVER_INTEREST:
            interest_waived += w.amount
        elif w.waiver_type == GirviWaiver.WAIVER_CHARGES:
            charges_waived += w.amount
        elif w.waiver_type == GirviWaiver.WAIVER_PENALTY:
            penalty_waived += w.amount

    total_waived = interest_waived + charges_waived + penalty_waived

    # Remaining balances
    processing_charges = loan.processing_charges or Decimal('0.00')
    remaining_charges = max(Decimal('0.00'), processing_charges - charges_paid - charges_waived)
    remaining_principal = max(Decimal('0.00'), principal - principal_paid)
    remaining_interest = max(Decimal('0.00'), accrued_interest - interest_paid - interest_waived)
    outstanding_balance = remaining_principal + remaining_interest + remaining_charges

    # Overdue checks
    is_overdue = False
    days_overdue = 0
    if loan.status in [GirviLoan.STATUS_ACTIVE, GirviLoan.STATUS_OVERDUE] and loan.maturity_date:
        mat_date = loan.maturity_date
        if isinstance(mat_date, datetime.datetime):
            mat_date = mat_date.date()
        grace_days = loan.grace_period_days or 0
        overdue_threshold = mat_date + datetime.timedelta(days=grace_days)
        if as_of_date > overdue_threshold:
            is_overdue = True
            days_overdue = (as_of_date - mat_date).days

    return {
        'as_of_date': as_of_date,
        'days_elapsed': days_elapsed,
        'effective_days': effective_days,
        'accrued_interest': accrued_interest,
        'processing_charges': processing_charges,
        'total_principal': principal,
        'principal_paid': principal_paid,
        'interest_paid': interest_paid,
        'charges_paid': charges_paid,
        'total_paid': total_paid,
        'interest_waived': interest_waived,
        'charges_waived': charges_waived,
        'penalty_waived': penalty_waived,
        'total_waived': total_waived,
        'remaining_principal': remaining_principal,
        'remaining_interest': remaining_interest,
        'remaining_charges': remaining_charges,
        'outstanding_balance': outstanding_balance,
        'is_settled': outstanding_balance <= Decimal('0.00'),
        'is_overdue': is_overdue,
        'days_overdue': days_overdue,
    }


def record_payment(loan, data, user, ip_address=None):
    """
    Record an immutable payment against a Girvi loan.
    Validates payment distribution, updates status, and logs audit trail.
    """
    amount = Decimal(str(data.get('total_amount_received', '0.00')))
    if amount <= Decimal('0.00'):
        raise ValidationError("Payment amount must be greater than zero.")

    interest_portion = Decimal(str(data.get('interest_portion', '0.00')))
    principal_portion = Decimal(str(data.get('principal_portion', '0.00')))
    charges_portion = Decimal(str(data.get('charges_portion', '0.00')))

    # Ensure portions sum to total received
    allocated_sum = interest_portion + principal_portion + charges_portion
    if allocated_sum != amount:
        # If user didn't manually allocate, perform intelligent default allocation:
        # 1. Charges first, 2. Accrued interest second, 3. Principal third
        fin = calculate_loan_financials(loan, as_of_date=data.get('payment_date'))
        rem_charges = fin['remaining_charges']
        rem_interest = fin['remaining_interest']

        charges_portion = min(amount, rem_charges)
        rem_amount = amount - charges_portion

        interest_portion = min(rem_amount, rem_interest)
        rem_amount = rem_amount - interest_portion

        principal_portion = rem_amount

    with transaction.atomic():
        receipt_num = get_next_sequence_number(loan.tenant, sequence_type='payment')

        payment = GirviPayment.objects.create(
            tenant=loan.tenant,
            branch=loan.branch,
            loan=loan,
            receipt_number=receipt_num,
            payment_date=data.get('payment_date') or timezone.localdate(),
            total_amount_received=amount,
            interest_portion=interest_portion,
            principal_portion=principal_portion,
            charges_portion=charges_portion,
            payment_method=data.get('payment_method', 'Cash'),
            reference_number=data.get('reference_number', '').strip(),
            received_by=user,
            notes=data.get('notes', '').strip(),
        )

        # Check if loan is now fully settled
        fin_after = calculate_loan_financials(loan, as_of_date=payment.payment_date)
        if fin_after['is_settled'] and loan.status in [GirviLoan.STATUS_ACTIVE, GirviLoan.STATUS_OVERDUE]:
            loan.status = GirviLoan.STATUS_SETTLED
            loan.save(update_fields=['status', 'updated_at'])

        # Audit Log
        GirviAuditLog.objects.create(
            tenant=loan.tenant,
            loan=loan,
            action='PAYMENT_RECEIVED',
            user=user,
            ip_address=ip_address,
            details=(
                f"Recorded payment of ₹{amount} (Principal: ₹{principal_portion}, "
                f"Interest: ₹{interest_portion}, Charges: ₹{charges_portion}) via {payment.payment_method}. "
                f"Receipt #{payment.receipt_number}. Remaining Balance: ₹{fin_after['outstanding_balance']}."
            )
        )

    return payment


def reverse_payment(payment, reason, user, ip_address=None):
    """
    Perform an auditable correction by reversing an earlier payment.
    Creates a counter-entry (is_reversal=True) and restores loan balance.
    """
    if payment.is_reversal:
        raise ValidationError("Cannot reverse a reversal entry.")

    if hasattr(payment, 'reversal_entry') and payment.reversal_entry is not None:
        raise ValidationError("This payment has already been reversed.")

    if not reason or not reason.strip():
        raise ValidationError("A clear reason is required to reverse a completed payment.")

    loan = payment.loan

    if loan.status == GirviLoan.STATUS_RELEASED:
        raise ValidationError(
            "Cannot reverse payment: Jewellery collateral has already been released to the customer."
        )

    with transaction.atomic():
        reversal_receipt = f"REV-{payment.receipt_number}"

        reversal = GirviPayment.objects.create(
            tenant=payment.tenant,
            branch=payment.branch,
            loan=loan,
            receipt_number=reversal_receipt,
            payment_date=timezone.localdate(),
            total_amount_received=-payment.total_amount_received,
            interest_portion=-payment.interest_portion,
            principal_portion=-payment.principal_portion,
            charges_portion=-payment.charges_portion,
            payment_method=payment.payment_method,
            reference_number=payment.reference_number,
            received_by=user,
            notes=f"Reversal of {payment.receipt_number}. Reason: {reason.strip()}",
            is_reversal=True,
            reversed_payment=payment,
            reversal_reason=reason.strip(),
            reversed_at=timezone.now(),
            reversed_by=user,
        )

        payment.is_reversal = True
        payment.reversal_reason = reason.strip()
        payment.reversed_at = timezone.now()
        payment.reversed_by = user
        payment.save(update_fields=['is_reversal', 'reversal_reason', 'reversed_at', 'reversed_by'])

        # Check and restore loan status if it was marked settled
        fin_after = calculate_loan_financials(loan)
        if not fin_after['is_settled'] and loan.status == GirviLoan.STATUS_SETTLED:
            loan.status = GirviLoan.STATUS_OVERDUE if fin_after['is_overdue'] else GirviLoan.STATUS_ACTIVE
            loan.save(update_fields=['status', 'updated_at'])

        GirviAuditLog.objects.create(
            tenant=loan.tenant,
            loan=loan,
            action='PAYMENT_REVERSED',
            user=user,
            ip_address=ip_address,
            details=(
                f"Reversed payment #{payment.receipt_number} of ₹{payment.total_amount_received}. "
                f"Reason: {reason.strip()}. Reversal entry: #{reversal.receipt_number}. "
                f"New Outstanding Balance: ₹{fin_after['outstanding_balance']}."
            )
        )

    return reversal


def record_waiver(loan, waiver_type, amount, reason, user, ip_address=None):
    """
    Record an explicit, authorized financial waiver/discount.
    Never silently erases outstanding interest or fees.
    """
    amt = Decimal(str(amount))
    if amt <= Decimal('0.00'):
        raise ValidationError("Waiver amount must be greater than zero.")

    if not reason or not reason.strip():
        raise ValidationError("A mandatory business reason is required for approving a waiver.")

    fin = calculate_loan_financials(loan)
    if waiver_type == GirviWaiver.WAIVER_INTEREST and amt > fin['remaining_interest']:
        raise ValidationError(
            f"Waiver of ₹{amt} exceeds remaining interest balance of ₹{fin['remaining_interest']}."
        )
    if waiver_type == GirviWaiver.WAIVER_CHARGES and amt > fin['remaining_charges']:
        raise ValidationError(
            f"Waiver of ₹{amt} exceeds remaining charges of ₹{fin['remaining_charges']}."
        )

    with transaction.atomic():
        waiver = GirviWaiver.objects.create(
            tenant=loan.tenant,
            branch=loan.branch,
            loan=loan,
            waiver_type=waiver_type,
            amount=amt,
            reason=reason.strip(),
            authorized_by=user,
        )

        fin_after = calculate_loan_financials(loan)
        if fin_after['is_settled'] and loan.status in [GirviLoan.STATUS_ACTIVE, GirviLoan.STATUS_OVERDUE]:
            loan.status = GirviLoan.STATUS_SETTLED
            loan.save(update_fields=['status', 'updated_at'])

        GirviAuditLog.objects.create(
            tenant=loan.tenant,
            loan=loan,
            action='WAIVER_APPLIED',
            user=user,
            ip_address=ip_address,
            details=(
                f"Authorized {waiver.get_waiver_type_display()} of ₹{amt}. "
                f"Reason: {reason.strip()}. Authorized by: {user.get_full_name() or user.username}."
            )
        )

    return waiver


def release_collateral(loan, user, notes='', ip_address=None):
    """
    Authorize and record the physical release of pledged jewellery collateral to the borrower.
    Requires that outstanding balance is <= 0.
    Updates custody status of all pieces to CUSTODY_RELEASED.
    """
    fin = calculate_loan_financials(loan)
    if not fin['is_settled']:
        raise ValidationError(
            f"Cannot release collateral: Loan has an outstanding balance of ₹{fin['outstanding_balance']}. "
            f"Full settlement or an authorized waiver is required before physical release."
        )

    if loan.status == GirviLoan.STATUS_RELEASED:
        raise ValidationError("Collateral for this loan has already been released.")

    with transaction.atomic():
        receipt_num = get_next_sequence_number(loan.tenant, sequence_type='release')

        loan.status = GirviLoan.STATUS_RELEASED
        loan.release_date = timezone.now()
        loan.released_by = user
        loan.release_notes = notes.strip()
        loan.release_receipt_number = receipt_num
        loan.save(update_fields=[
            'status', 'release_date', 'released_by', 'release_notes',
            'release_receipt_number', 'updated_at'
        ])

        # Update custody status on all pledged collateral pieces
        loan.items.update(custody_status=GirviItem.CUSTODY_RELEASED)

        GirviAuditLog.objects.create(
            tenant=loan.tenant,
            loan=loan,
            action='JEWELLERY_RELEASED',
            user=user,
            ip_address=ip_address,
            details=(
                f"Released all pledged jewellery collateral to borrower {loan.customer.name}. "
                f"Release Voucher #{receipt_num}. Released by: {user.get_full_name() or user.username}. "
                f"Notes: {notes.strip() or 'None'}."
            )
        )

    return loan
