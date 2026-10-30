"""
girvi/models.py
----------------
Complete data models for the JwelDesk Girvi (Jewellery Pledge & Loan Management) module.

Includes:
1. GirviSetting: Showroom-level default rates, prefixes, and loan terms.
2. GirviSequence: Atomic sequence counter for collision-free voucher numbers.
3. GirviLoan: Master pledge agreement with snapshot financial terms.
4. GirviItem: Pledged jewellery collateral pieces (held in custody; strictly separated from stock).
5. GirviPayment: Immutable financial payment ledger with auditable reversal entries.
6. GirviWaiver: Explicit authorized financial adjustments (interest, fees, penalties).
7. GirviAuditLog: Append-only compliance and lifecycle audit trail.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from inventory.models import JewelleryItem


class GirviSetting(models.Model):
    """
    Showroom-level defaults for newly generated Girvi loans.
    Editing these defaults never affects existing historical or active loans.
    """
    tenant = models.OneToOneField(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='girvi_setting',
        help_text="Tenant showroom owning these Girvi configuration defaults"
    )
    loan_number_prefix = models.CharField(
        max_length=15,
        default='GIR-',
        help_text="Prefix for pledge loan vouchers (e.g. GIR-)"
    )
    payment_number_prefix = models.CharField(
        max_length=15,
        default='PAY-GIR-',
        help_text="Prefix for payment receipts (e.g. PAY-GIR-)"
    )
    default_interest_rate_monthly = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('2.00'),
        help_text="Default monthly interest rate percentage (e.g. 2.00%)"
    )
    default_interest_period = models.CharField(
        max_length=20,
        choices=[
            ('monthly', 'Per Month (% / month)'),
            ('yearly',  'Per Annum (% / year)'),
            ('daily',   'Per Day (% / day)'),
        ],
        default='monthly'
    )
    default_calculation_type = models.CharField(
        max_length=30,
        choices=[
            ('simple_monthly', 'Simple Interest (Monthly Basis)'),
            ('simple_daily',   'Simple Interest (Exact Daily Basis)'),
            ('fixed_monthly',  'Fixed Monthly (Rounded Up to Next Month)'),
        ],
        default='simple_monthly'
    )
    default_loan_duration_months = models.PositiveIntegerField(
        default=12,
        help_text="Standard loan maturity duration in months"
    )
    default_grace_period_days = models.PositiveIntegerField(
        default=7,
        help_text="Standard grace period in days before loan is flagged overdue"
    )
    standard_terms_conditions = models.TextField(
        blank=True,
        help_text="Standard legal disclaimer and terms printed on pawn agreement vouchers"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Girvi Setting'
        verbose_name_plural = 'Girvi Settings'

    def __str__(self):
        return f"Girvi Settings: {self.tenant.name}"


class GirviSequence(models.Model):
    """
    Atomic sequence generator ensuring collision-free, gapless voucher numbering
    across concurrent multi-user requests.
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='girvi_sequences',
        help_text="Tenant owning this sequence counter"
    )
    sequence_type = models.CharField(
        max_length=30,
        help_text="Type of sequence (e.g. loan, payment, release)"
    )
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Girvi Sequence'
        verbose_name_plural = 'Girvi Sequences'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'sequence_type'],
                name='unique_tenant_girvi_sequence'
            )
        ]

    def __str__(self):
        return f"{self.sequence_type}: {self.last_number} ({self.tenant.name})"


class GirviLoan(models.Model):
    """
    Authoritative master pledge and loan contract.
    Snapshots all financial and interest calculation terms at creation time so
    subsequent showroom default changes never alter existing loan contracts.
    """
    STATUS_ACTIVE    = 'active'
    STATUS_OVERDUE   = 'overdue'
    STATUS_SETTLED   = 'settled'
    STATUS_RELEASED  = 'released'
    STATUS_DEFAULTED = 'defaulted'

    STATUS_CHOICES = [
        (STATUS_ACTIVE,    'Active'),
        (STATUS_OVERDUE,   'Overdue'),
        (STATUS_SETTLED,   'Settled (Paid in Full)'),
        (STATUS_RELEASED,  'Jewellery Released'),
        (STATUS_DEFAULTED, 'Defaulted / Forfeited'),
    ]

    PERIOD_MONTHLY = 'monthly'
    PERIOD_YEARLY  = 'yearly'
    PERIOD_DAILY   = 'daily'

    PERIOD_CHOICES = [
        (PERIOD_MONTHLY, 'Per Month (% / month)'),
        (PERIOD_YEARLY,  'Per Annum (% / year)'),
        (PERIOD_DAILY,   'Per Day (% / day)'),
    ]

    CALC_SIMPLE_MONTHLY = 'simple_monthly'
    CALC_SIMPLE_DAILY   = 'simple_daily'
    CALC_FIXED_MONTHLY  = 'fixed_monthly'

    CALC_CHOICES = [
        (CALC_SIMPLE_MONTHLY, 'Simple Interest (Monthly Basis)'),
        (CALC_SIMPLE_DAILY,   'Simple Interest (Exact Daily Basis)'),
        (CALC_FIXED_MONTHLY,  'Fixed Monthly (Rounded Up to Next Month)'),
    ]

    # Tenancy & Branch
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='girvi_loans',
        db_index=True,
        help_text="Tenant showroom owning this Girvi contract"
    )
    branch = models.ForeignKey(
        'team.Branch',
        on_delete=models.PROTECT,
        related_name='girvi_loans',
        db_index=True,
        help_text="Showroom branch where loan was booked and collateral is held"
    )
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='girvi_loans',
        db_index=True,
        help_text="Borrower customer record"
    )

    # Identifiers & Dates
    loan_number = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Unique sequential loan number (e.g. GIR-00001)"
    )
    loan_date = models.DateField(
        default=timezone.localdate,
        db_index=True,
        help_text="Date the loan agreement was executed"
    )
    maturity_date = models.DateField(
        null=True,
        blank=True,
        help_text="Contractual repayment due date"
    )

    # Contractual Financial Snapshots (Immutable to setting changes)
    principal_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Principal amount disbursed in INR (₹)"
    )
    interest_rate_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Agreed contractual interest rate percentage"
    )
    interest_period = models.CharField(
        max_length=20,
        choices=PERIOD_CHOICES,
        default=PERIOD_MONTHLY
    )
    interest_calculation_type = models.CharField(
        max_length=30,
        choices=CALC_CHOICES,
        default=CALC_SIMPLE_MONTHLY
    )
    loan_duration_months = models.PositiveIntegerField(
        default=12,
        help_text="Agreed duration of loan in months"
    )
    grace_period_days = models.PositiveIntegerField(
        default=0,
        help_text="Days past maturity before marking overdue"
    )
    minimum_interest_days = models.PositiveIntegerField(
        default=0,
        help_text="Minimum chargeable days of interest upon early redemption"
    )
    processing_charges = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Administrative or document charges disbursed/charged"
    )
    valuation_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Combined estimated market valuation of pledged collateral pieces"
    )

    # Lifecycle Status & Physical Custody
    status = models.CharField(
        max_length=25,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True
    )
    custody_location = models.CharField(
        max_length=150,
        blank=True,
        help_text="Strongroom safe / locker / box location reference"
    )
    release_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when physical custody was returned to borrower"
    )
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='released_girvi_loans'
    )
    release_notes = models.TextField(blank=True)
    release_receipt_number = models.CharField(max_length=50, blank=True)

    terms_conditions = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_girvi_loans'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-loan_date', '-id']
        verbose_name = 'Girvi Loan'
        verbose_name_plural = 'Girvi Loans'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'loan_number'],
                name='unique_tenant_girvi_loan_number'
            )
        ]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'branch', 'status']),
            models.Index(fields=['tenant', 'loan_date']),
        ]

    def __str__(self):
        return f"{self.loan_number} - {self.customer.name} (₹{self.principal_amount})"

    @property
    def total_weight(self):
        """Aggregate gross weight across all pledged collateral items."""
        return sum(it.gross_weight for it in self.items.all())

    @property
    def total_net_weight(self):
        """Aggregate net precious metal weight across all pledged collateral items."""
        return sum(it.net_weight for it in self.items.all())


class GirviItem(models.Model):
    """
    Physical jewellery pieces held in custody as collateral for a GirviLoan.
    Strictly independent from inventory.JewelleryItem to prevent accidental stock contamination.
    """
    CUSTODY_IN_VAULT  = 'in_vault'
    CUSTODY_RELEASED  = 'released_to_borrower'
    CUSTODY_FORFEITED = 'forfeited'

    CUSTODY_CHOICES = [
        (CUSTODY_IN_VAULT,  'In Shop Safe / Vault'),
        (CUSTODY_RELEASED,  'Released to Customer'),
        (CUSTODY_FORFEITED, 'Forfeited / Auctioned'),
    ]

    loan = models.ForeignKey(
        GirviLoan,
        on_delete=models.CASCADE,
        related_name='items',
        help_text="Parent Girvi loan agreement"
    )
    item_name = models.CharField(
        max_length=150,
        help_text="Description of pledged piece (e.g. Gold Haar 22K, Silver Payal 925)"
    )
    category = models.ForeignKey(
        'inventory.Category',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Standard inventory category classification"
    )
    metal_type = models.CharField(
        max_length=20,
        choices=JewelleryItem.METAL_CHOICES,
        default='Gold'
    )
    purity = models.CharField(
        max_length=50,
        choices=JewelleryItem.PURITY_CHOICES,
        default='22K'
    )
    quantity = models.PositiveIntegerField(default=1)

    # Weights in grams (milligram precision matching inventory standard)
    gross_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        help_text="Total scale weight in grams"
    )
    stone_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Deductible stone / wax / enamel weight in grams"
    )
    net_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        help_text="Net precious metal weight in grams (gross - stone)"
    )
    purity_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('91.60'),
        help_text="Fine metal purity percentage"
    )
    fine_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Calculated pure metal weight: net_weight * (purity / 100)"
    )

    estimated_market_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Metal market rate per gram applied at booking"
    )
    market_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Estimated market value of this collateral item"
    )
    loan_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Sanctioned loan value against this specific collateral piece"
    )

    huid = models.CharField(
        max_length=10,
        blank=True,
        help_text="BIS Hallmarking Unique ID if stamped"
    )
    description = models.TextField(
        blank=True,
        help_text="Identifying details: stones, color, condition, stamps"
    )
    custody_status = models.CharField(
        max_length=25,
        choices=CUSTODY_CHOICES,
        default=CUSTODY_IN_VAULT
    )
    item_photo = models.ImageField(
        upload_to='girvi/items/%Y/%m/',
        null=True,
        blank=True,
        help_text="Photograph of physical pledged item"
    )

    class Meta:
        ordering = ['id']
        verbose_name = 'Girvi Collateral Item'
        verbose_name_plural = 'Girvi Collateral Items'

    def __str__(self):
        return f"{self.item_name} ({self.gross_weight}g {self.purity}) - Loan #{self.loan.loan_number}"

    def save(self, *args, **kwargs):
        # Auto-compute net weight and fine weight
        if self.gross_weight is not None:
            sw = self.stone_weight or Decimal('0.000')
            self.net_weight = max(Decimal('0.000'), self.gross_weight - sw)
            if self.purity_percentage:
                self.fine_weight = (self.net_weight * (self.purity_percentage / Decimal('100.00'))).quantize(Decimal('0.001'))
        super().save(*args, **kwargs)


class GirviPayment(models.Model):
    """
    Immutable ledger of monies received against a GirviLoan.
    Entries cannot be edited or deleted; corrections require explicit reversal.
    """
    PAYMENT_METHODS = [
        ('Cash',          'Cash'),
        ('UPI',           'UPI / QR Code'),
        ('Bank Transfer', 'NEFT / RTGS / IMPS'),
        ('Card',          'Credit / Debit Card'),
        ('Cheque',        'Cheque'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='girvi_payments'
    )
    branch = models.ForeignKey(
        'team.Branch',
        on_delete=models.PROTECT,
        related_name='girvi_payments'
    )
    loan = models.ForeignKey(
        GirviLoan,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    receipt_number = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Unique sequential payment receipt number (e.g. PAY-GIR-00001)"
    )
    payment_date = models.DateField(
        default=timezone.localdate,
        db_index=True
    )
    total_amount_received = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Total money received in INR (₹)"
    )
    interest_portion = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Portion credited towards accrued interest"
    )
    principal_portion = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Portion credited towards principal reduction"
    )
    charges_portion = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Portion credited towards fees or charges"
    )
    payment_method = models.CharField(
        max_length=30,
        choices=PAYMENT_METHODS,
        default='Cash'
    )
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="UTR number, UPI transaction ID, or cheque number"
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_girvi_payments'
    )
    notes = models.TextField(blank=True)

    # Reversal Mechanism (Auditable accounting correction)
    is_reversal = models.BooleanField(
        default=False,
        help_text="True if this row reverses an earlier incorrect payment"
    )
    reversed_payment = models.OneToOneField(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversal_entry',
        help_text="The original payment record negated by this entry"
    )
    reversal_reason = models.TextField(blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversed_girvi_payments'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['payment_date', 'id']
        verbose_name = 'Girvi Payment'
        verbose_name_plural = 'Girvi Payments'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'receipt_number'],
                name='unique_tenant_girvi_payment_receipt'
            )
        ]

    def __str__(self):
        reversal_flag = " [REVERSAL]" if self.is_reversal else ""
        return f"{self.receipt_number}{reversal_flag}: ₹{self.total_amount_received} on Loan #{self.loan.loan_number}"


class GirviWaiver(models.Model):
    """
    Explicit, auditable record of an authorized financial waiver or discount.
    Prevents silent erasure of outstanding interest or penalties.
    """
    WAIVER_INTEREST = 'interest'
    WAIVER_CHARGES  = 'charges'
    WAIVER_PENALTY  = 'penalty'

    WAIVER_CHOICES = [
        (WAIVER_INTEREST, 'Interest Waiver'),
        (WAIVER_CHARGES,  'Processing Charges Waiver'),
        (WAIVER_PENALTY,  'Penalty / Overdue Waiver'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='girvi_waivers'
    )
    branch = models.ForeignKey(
        'team.Branch',
        on_delete=models.PROTECT,
        related_name='girvi_waivers'
    )
    loan = models.ForeignKey(
        GirviLoan,
        on_delete=models.CASCADE,
        related_name='waivers'
    )
    waiver_type = models.CharField(
        max_length=20,
        choices=WAIVER_CHOICES,
        default=WAIVER_INTEREST
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Amount waived in INR (₹)"
    )
    reason = models.TextField(
        help_text="Mandatory business reason for approving this waiver"
    )
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='authorized_girvi_waivers',
        help_text="Administrator or manager who authorized this discount/waiver"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Girvi Waiver'
        verbose_name_plural = 'Girvi Waivers'

    def __str__(self):
        return f"{self.get_waiver_type_display()}: ₹{self.amount} for Loan #{self.loan.loan_number} (by {self.authorized_by})"


class GirviAuditLog(models.Model):
    """
    Append-only audit trail capturing key lifecycle events on Girvi loans.
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='girvi_audit_logs'
    )
    loan = models.ForeignKey(
        GirviLoan,
        on_delete=models.CASCADE,
        related_name='audit_logs'
    )
    action = models.CharField(
        max_length=40,
        db_index=True,
        help_text="e.g. LOAN_CREATED, PAYMENT_RECEIVED, PAYMENT_REVERSED, WAIVER_APPLIED, JEWELLERY_RELEASED"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Girvi Audit Log'
        verbose_name_plural = 'Girvi Audit Logs'

    def __str__(self):
        return f"{self.action} on Loan #{self.loan.loan_number} at {self.created_at:%Y-%m-%d %H:%M}"

