from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from customers.models import Customer
from inventory.models import JewelleryItem, StockMovement
from inventory import pricing


# ==============================================================================
# SEQUENTIAL REFERENCE GENERATORS
# ==============================================================================

def generate_karigar_code():
    """Generate sequential Karigar code: KRG-0001, KRG-0002, etc."""
    latest = Karigar.objects.filter(karigar_code__startswith='KRG-').order_by('-id').first()
    next_num = 1
    if latest and latest.karigar_code:
        try:
            num = int(latest.karigar_code.split('-')[-1])
            next_num = num + 1
        except (ValueError, IndexError):
            next_num = Karigar.objects.count() + 1
    candidate = f"KRG-{next_num:04d}"
    while Karigar.objects.filter(karigar_code=candidate).exists():
        next_num += 1
        candidate = f"KRG-{next_num:04d}"
    return candidate


def generate_assignment_number():
    """Generate sequential assignment number: WA-YYYY-XXXX."""
    year = timezone.now().strftime('%Y')
    prefix = f"WA-{year}-"
    latest = KarigarWorkAssignment.objects.filter(assignment_number__startswith=prefix).order_by('-id').first()
    next_num = 1
    if latest and latest.assignment_number:
        try:
            num = int(latest.assignment_number.split('-')[-1])
            next_num = num + 1
        except (ValueError, IndexError):
            next_num = KarigarWorkAssignment.objects.filter(assignment_number__startswith=prefix).count() + 1
    candidate = f"{prefix}{next_num:04d}"
    while KarigarWorkAssignment.objects.filter(assignment_number=candidate).exists():
        next_num += 1
        candidate = f"{prefix}{next_num:04d}"
    return candidate


def generate_settlement_number():
    """Generate sequential settlement voucher: KST-YYYY-XXXX."""
    year = timezone.now().strftime('%Y')
    prefix = f"KST-{year}-"
    latest = KarigarSettlement.objects.filter(settlement_number__startswith=prefix).order_by('-id').first()
    next_num = 1
    if latest and latest.settlement_number:
        try:
            num = int(latest.settlement_number.split('-')[-1])
            next_num = num + 1
        except (ValueError, IndexError):
            next_num = KarigarSettlement.objects.filter(settlement_number__startswith=prefix).count() + 1
    candidate = f"{prefix}{next_num:04d}"
    while KarigarSettlement.objects.filter(settlement_number=candidate).exists():
        next_num += 1
        candidate = f"{prefix}{next_num:04d}"
    return candidate


# ==============================================================================
# 1. KARIGAR MASTER
# ==============================================================================

class Karigar(models.Model):
    """
    Karigar / Artisan profile.
    Maintains artisan identity, contact details, trade specialization,
    and running financial & material accountability balances.
    """

    STATUS_ACTIVE = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    SPECIALIZATION_CHOICES = [
        ('Gold Jewellery', 'Gold Jewellery (Plain / Jadau)'),
        ('Silver Jewellery', 'Silver Jewellery & Utensils'),
        ('Diamond Setting', 'Diamond & Gemstone Setting'),
        ('Casting', 'Casting & Die Work'),
        ('Polishing & Finishing', 'Polishing, Buffing & Rhodium'),
        ('Repair & Restoration', 'Repair & Size Alteration'),
        ('Hand Engraving', 'Hand Engraving / Meenakari'),
        ('Custom Work', 'Custom Designer Pieces'),
        ('General / All Rounder', 'General All-Round Artisan'),
        ('Other', 'Other Work'),
    ]

    karigar_code = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        help_text="Unique artisan ID (e.g. KRG-0001)"
    )
    name = models.CharField(max_length=150, help_text="Artisan / Workshop Name")
    mobile = models.CharField(max_length=20)
    alternate_contact = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True, help_text="Workshop / residential address")
    specialization = models.CharField(
        max_length=50,
        choices=SPECIALIZATION_CHOICES,
        default='Gold Jewellery'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE
    )
    joining_date = models.DateField(default=timezone.localdate)
    pan_or_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="PAN / Aadhaar / Workshop Reg. for compliance"
    )
    bank_details = models.TextField(
        blank=True,
        help_text="Bank Account, IFSC, UPI ID for settlements"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Karigar'
        verbose_name_plural = 'Karigars'

    def __str__(self):
        return f"{self.karigar_code} - {self.name} ({self.specialization})"

    def clean(self):
        super().clean()
        if self.mobile:
            self.mobile = self.mobile.strip()

    def save(self, *args, **kwargs):
        if not self.karigar_code:
            self.karigar_code = generate_karigar_code()
        super().save(*args, **kwargs)

    # ---- Statistics & Balance Properties -------------------------------------
    @property
    def is_active(self):
        return self.status == self.STATUS_ACTIVE

    @property
    def total_assignments_count(self):
        return self.assignments.count()

    @property
    def active_assignments_count(self):
        return self.assignments.filter(
            status__in=[
                KarigarWorkAssignment.STATUS_ASSIGNED,
                KarigarWorkAssignment.STATUS_IN_PROGRESS,
            ]
        ).count()

    @property
    def completed_unreceived_count(self):
        return self.assignments.filter(
            status=KarigarWorkAssignment.STATUS_COMPLETED
        ).count()

    @property
    def overdue_assignments_count(self):
        today = timezone.localdate()
        return self.assignments.filter(
            status__in=[
                KarigarWorkAssignment.STATUS_ASSIGNED,
                KarigarWorkAssignment.STATUS_IN_PROGRESS,
            ],
            expected_completion_date__lt=today
        ).count()

    @property
    def total_charges(self):
        """Total labour/making charges earned by this karigar."""
        total = self.assignments.exclude(
            status=KarigarWorkAssignment.STATUS_CANCELLED
        ).aggregate(total=models.Sum('total_charge'))['total']
        return total or Decimal('0.00')

    @property
    def total_paid(self):
        """Total payments/settlements completed to this karigar."""
        total = self.settlements.filter(
            status='Completed'
        ).aggregate(total=models.Sum('amount'))['total']
        return total or Decimal('0.00')

    @property
    def pending_balance(self):
        """Unsettled labour dues owed to this artisan."""
        bal = self.total_charges - self.total_paid
        return bal if bal > 0 else Decimal('0.00')

    @property
    def current_net_metal_holding(self):
        """
        Total net metal weight currently held by this Karigar
        across active (unreceived) work assignments.
        """
        active_works = self.assignments.filter(
            status__in=[
                KarigarWorkAssignment.STATUS_ASSIGNED,
                KarigarWorkAssignment.STATUS_IN_PROGRESS,
                KarigarWorkAssignment.STATUS_COMPLETED,
            ]
        )
        total_issued = active_works.aggregate(total=models.Sum('net_weight_issued'))['total'] or Decimal('0.000')
        return total_issued


# ==============================================================================
# 2. KARIGAR WORK ASSIGNMENT
# ==============================================================================

class KarigarWorkAssignment(models.Model):
    """
    Work order / Job card assigned to a Karigar.
    Tracks work instructions, deadlines, material accountability,
    and labour charge calculations.
    """

    WORK_TYPE_CHOICES = [
        ('New Making', 'New Piece Making'),
        ('Repair', 'Repair & Restoration'),
        ('Polishing', 'Polishing & Finishing'),
        ('Stone Setting', 'Stone / Diamond Setting'),
        ('Resizing', 'Resizing / Alteration'),
        ('Casting', 'Casting & Moulding'),
        ('Custom Work', 'Custom Work (From Design)'),
        ('Other', 'Other Work'),
    ]

    PRIORITY_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
        ('Urgent', 'Urgent'),
    ]

    STATUS_ASSIGNED = 'Assigned'
    STATUS_IN_PROGRESS = 'In Progress'
    STATUS_COMPLETED = 'Completed'
    STATUS_RECEIVED = 'Received'
    STATUS_CANCELLED = 'Cancelled'

    STATUS_CHOICES = [
        (STATUS_ASSIGNED, 'Assigned (Job Issued)'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_COMPLETED, 'Completed (Ready for Inspection)'),
        (STATUS_RECEIVED, 'Received & Verified in Stock'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    MAKING_CHARGE_TYPE_CHOICES = [
        ('Fixed Amount', 'Fixed Amount (₹)'),
        ('Per Gram', 'Per Gram (₹/g)'),
        ('Percentage', 'Percentage of Metal Value (%)'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('Unpaid', 'Unpaid'),
        ('Partially Paid', 'Partially Paid'),
        ('Paid', 'Paid'),
    ]

    assignment_number = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        help_text="Unique assignment reference (e.g. WA-2026-0001)"
    )
    karigar = models.ForeignKey(
        Karigar,
        on_delete=models.PROTECT,
        related_name='assignments'
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='karigar_assignments',
        help_text="Customer if this work is for a customer repair or bespoke piece"
    )
    custom_order = models.ForeignKey(
        'custom_orders.CustomOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='karigar_assignments',
        help_text="Linked custom order if assigned for order fulfillment"
    )
    inventory_item = models.ForeignKey(
        JewelleryItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='karigar_assignments',
        help_text="Existing inventory piece issued for repair, polishing, or resizing"
    )

    work_type = models.CharField(
        max_length=40,
        choices=WORK_TYPE_CHOICES,
        default='New Making'
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='Medium'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ASSIGNED
    )
    description = models.TextField(
        help_text="Detailed job instructions, dimensions, design requirements"
    )
    reference_image = models.FileField(
        upload_to='karigar/designs/%Y/%m/',
        blank=True,
        null=True,
        help_text="Design sketch, CAD render, or reference photo"
    )

    # Dates
    issue_date = models.DateField(default=timezone.localdate)
    expected_completion_date = models.DateField(null=True, blank=True)
    actual_completion_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)

    # ---- Material / Weight Accountability (Issued) ---------------------------
    metal_type = models.CharField(
        max_length=20,
        choices=JewelleryItem.METAL_CHOICES,
        default='Gold'
    )
    purity = models.CharField(
        max_length=50,
        default='22K',
        blank=True,
        help_text="e.g. 24K, 22K (916), 18K (750), 925 Silver"
    )
    gross_weight_issued = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Gross weight of raw gold/scrap issued in grams"
    )
    stone_weight_issued = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Weight of stones/beads/findings issued"
    )
    net_weight_issued = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Net precious metal issued (Gross - Stones)"
    )

    # ---- Material Received Back (Finished Piece + Scrap) --------------------
    gross_weight_received = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Finished piece gross weight in grams"
    )
    stone_weight_received = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Finished piece stone weight in grams"
    )
    net_weight_received = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Finished piece net precious metal weight in grams"
    )
    scrap_weight_returned = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Cut pieces, filings, or scrap gold returned back by artisan"
    )

    # ---- Wastage & Difference -----------------------------------------------
    wastage_allowed_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Allowed manufacturing wastage % (e.g. 1.50%)"
    )
    wastage_weight_allowed = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Allowed wastage in grams (Net Issued * Wastage %)"
    )
    actual_wastage_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Actual loss = Net Issued - (Net Received + Scrap Returned)"
    )
    weight_difference = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Actual Wastage - Allowed Wastage (+ve = excess loss, -ve = recovery gain)"
    )

    # ---- Making / Labour Charges --------------------------------------------
    making_charge_type = models.CharField(
        max_length=20,
        choices=MAKING_CHARGE_TYPE_CHOICES,
        default='Per Gram'
    )
    making_charge_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Rate in ₹ (e.g. ₹450/g or fixed ₹2,500)"
    )
    labour_charge = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Calculated making charge in ₹"
    )
    stone_charges = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Stone setting / diamond charges in ₹"
    )
    other_charges = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Rhodium, hallmarking, casting or polish charges in ₹"
    )
    other_charges_description = models.CharField(
        max_length=200,
        blank=True,
        help_text="Description of other approved charges"
    )
    total_charge = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total artisan charge (Labour + Stones + Others)"
    )

    # ---- Settlement / Payment Status ----------------------------------------
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='Unpaid'
    )
    paid_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00')
    )

    # ---- Stock Movement Links -----------------------------------------------
    stock_movement_issued = models.ForeignKey(
        StockMovement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='karigar_issue_assignments',
        help_text="Audit record when showroom item was issued to Karigar"
    )
    stock_movement_received = models.ForeignKey(
        StockMovement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='karigar_receipt_assignments',
        help_text="Audit record when finished piece was received into inventory"
    )

    # ---- Audit --------------------------------------------------------------
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='karigar_assignments_issued'
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='karigar_assignments_received'
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-issue_date', '-id']
        verbose_name = 'Work Assignment'
        verbose_name_plural = 'Work Assignments'

    def __str__(self):
        return f"{self.assignment_number} - {self.karigar.name} ({self.work_type})"

    @property
    def is_overdue(self):
        """Check if work is past its due date without completion or receipt."""
        if not self.expected_completion_date:
            return False
        return (
            self.expected_completion_date < timezone.localdate()
            and self.status not in (self.STATUS_COMPLETED, self.STATUS_RECEIVED, self.STATUS_CANCELLED)
        )

    @property
    def due_charge_amount(self):
        due = self.total_charge - self.paid_amount
        return due if due > 0 else Decimal('0.00')

    @property
    def has_excess_wastage(self):
        return self.weight_difference > Decimal('0.000')

    def calculate_weights(self):
        """Recompute weights, wastage, and accountability differences."""
        # 1. Issued net
        g_iss = pricing.round_wt(self.gross_weight_issued or Decimal('0.000'))
        s_iss = pricing.round_wt(self.stone_weight_issued or Decimal('0.000'))
        self.net_weight_issued = max(Decimal('0.000'), g_iss - s_iss)

        # 2. Received net
        g_rec = pricing.round_wt(self.gross_weight_received or Decimal('0.000'))
        s_rec = pricing.round_wt(self.stone_weight_received or Decimal('0.000'))
        self.net_weight_received = max(Decimal('0.000'), g_rec - s_rec)

        scrap = pricing.round_wt(self.scrap_weight_returned or Decimal('0.000'))

        # 3. Allowed wastage
        w_pct = pricing.to_decimal(self.wastage_allowed_percent or Decimal('0.00'))
        if w_pct > 0 and self.net_weight_issued > 0:
            self.wastage_weight_allowed = pricing.round_wt(self.net_weight_issued * (w_pct / Decimal('100.00')))
        else:
            self.wastage_weight_allowed = Decimal('0.000')

        # 4. Actual wastage and accountability difference (calculated when received)
        if self.status in (self.STATUS_COMPLETED, self.STATUS_RECEIVED) or self.net_weight_received > 0:
            total_accounted = self.net_weight_received + scrap
            self.actual_wastage_weight = pricing.round_wt(self.net_weight_issued - total_accounted)
            self.weight_difference = pricing.round_wt(self.actual_wastage_weight - self.wastage_weight_allowed)
        else:
            self.actual_wastage_weight = Decimal('0.000')
            self.weight_difference = Decimal('0.000')

    def calculate_charges(self):
        """Recompute labour and total charges based on configured charge type."""
        c_type = self.making_charge_type or 'Per Gram'
        rate = pricing.to_decimal(self.making_charge_rate or Decimal('0.00'))

        if c_type == 'Fixed Amount':
            self.labour_charge = pricing.round_curr(rate)
        elif c_type == 'Per Gram':
            # Use finished received weight if available, else net weight issued
            wt_basis = self.net_weight_received if self.net_weight_received > 0 else self.net_weight_issued
            self.labour_charge = pricing.round_curr(rate * wt_basis)
        elif c_type == 'Percentage':
            # Percentage on metal base value
            base_rate = pricing.get_current_metal_rate(self.metal_type)
            p_factor = pricing.parse_purity_factor(self.metal_type, self.purity)
            metal_val = (self.net_weight_received or self.net_weight_issued) * (base_rate * p_factor)
            self.labour_charge = pricing.round_curr(metal_val * (rate / Decimal('100.00')))

        stones = pricing.round_curr(self.stone_charges or Decimal('0.00'))
        others = pricing.round_curr(self.other_charges or Decimal('0.00'))
        self.total_charge = pricing.round_curr(self.labour_charge + stones + others)

        # Update payment status
        paid = pricing.round_curr(self.paid_amount or Decimal('0.00'))
        if paid <= 0:
            self.payment_status = 'Unpaid'
        elif paid >= self.total_charge and self.total_charge > 0:
            self.payment_status = 'Paid'
        else:
            self.payment_status = 'Partially Paid'

    def clean(self):
        super().clean()
        errors = {}

        if self.gross_weight_issued < 0:
            errors['gross_weight_issued'] = 'Issued gross weight cannot be negative.'
        if self.stone_weight_issued < 0:
            errors['stone_weight_issued'] = 'Issued stone weight cannot be negative.'
        if self.stone_weight_issued and self.gross_weight_issued:
            if self.stone_weight_issued > self.gross_weight_issued:
                errors['stone_weight_issued'] = 'Issued stone weight cannot exceed gross weight.'

        if self.gross_weight_received < 0:
            errors['gross_weight_received'] = 'Received gross weight cannot be negative.'
        if self.stone_weight_received < 0:
            errors['stone_weight_received'] = 'Received stone weight cannot be negative.'
        if self.stone_weight_received and self.gross_weight_received:
            if self.stone_weight_received > self.gross_weight_received:
                errors['stone_weight_received'] = 'Received stone weight cannot exceed gross weight.'

        if self.scrap_weight_returned < 0:
            errors['scrap_weight_returned'] = 'Scrap weight cannot be negative.'

        if self.making_charge_rate < 0:
            errors['making_charge_rate'] = 'Making charge rate cannot be negative.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.assignment_number:
            self.assignment_number = generate_assignment_number()
        self.calculate_weights()
        self.calculate_charges()
        super().save(*args, **kwargs)


# ==============================================================================
# 3. KARIGAR SETTLEMENT / PAYMENT
# ==============================================================================

class KarigarSettlement(models.Model):
    """
    Financial voucher for labour charge payments made to a Karigar.
    Can be allocated against one or multiple work assignments,
    or recorded as an advance on account.
    """

    PAYMENT_METHODS = [
        ('Cash', 'Cash'),
        ('Bank Transfer', 'Bank Transfer (NEFT/RTGS/IMPS)'),
        ('UPI', 'UPI Payment'),
        ('Cheque', 'Cheque'),
    ]

    STATUS_COMPLETED = 'Completed'
    STATUS_CANCELLED = 'Cancelled'
    STATUS_CHOICES = [
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    settlement_number = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        help_text="Unique settlement reference (e.g. KST-2026-0001)"
    )
    karigar = models.ForeignKey(
        Karigar,
        on_delete=models.PROTECT,
        related_name='settlements'
    )
    payment_date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Payment amount in ₹"
    )
    payment_method = models.CharField(
        max_length=30,
        choices=PAYMENT_METHODS,
        default='Cash'
    )
    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Cheque # / UTR / Transaction reference"
    )
    assignments = models.ManyToManyField(
        KarigarWorkAssignment,
        blank=True,
        related_name='settlements',
        help_text="Work assignments settled by this payment"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_COMPLETED
    )
    notes = models.TextField(blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_karigar_settlements'
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cancelled_karigar_settlements'
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payment_date', '-id']
        verbose_name = 'Karigar Settlement'
        verbose_name_plural = 'Karigar Settlements'

    def __str__(self):
        return f"{self.settlement_number} - {self.karigar.name} (₹{self.amount:,.2f})"

    def clean(self):
        super().clean()
        if self.amount is not None and self.amount <= Decimal('0.00'):
            raise ValidationError({'amount': 'Settlement amount must be greater than zero.'})

    def save(self, *args, **kwargs):
        if not self.settlement_number:
            self.settlement_number = generate_settlement_number()
        super().save(*args, **kwargs)

    def cancel(self, user, reason):
        """Safely cancel settlement and adjust paid balances on linked assignments."""
        if self.status == self.STATUS_CANCELLED:
            raise ValidationError('Settlement is already cancelled.')
        with transaction.atomic():
            self.status = self.STATUS_CANCELLED
            self.cancelled_by = user
            self.cancelled_at = timezone.now()
            self.cancellation_reason = reason or 'Cancelled by user.'
            self.save(update_fields=['status', 'cancelled_by', 'cancelled_at', 'cancellation_reason'])

            # Revert allocations on assignments
            for asg in self.assignments.all():
                # Re-sum completed settlements for this assignment
                other_settlements = asg.settlements.filter(status='Completed')
                new_paid = other_settlements.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
                asg.paid_amount = min(asg.total_charge, new_paid)
                asg.save(update_fields=['paid_amount', 'payment_status'])
