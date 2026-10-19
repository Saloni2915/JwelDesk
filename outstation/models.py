"""
outstation/models.py
--------------------
Data models for JewelDesk Outstation Jewellery Sales & Stock Tracking.
Provides multi-tenant trip management, tagged jewellery stock issuance,
B2B & B2C sales tracking, return reconciliation, and discrepancy audit trails.
"""

from decimal import Decimal
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger('outstation.models')


def generate_trip_number(tenant=None):
    """
    Generate an atomic, sequential trip reference number scoped to the tenant.
    Format: TRIP-YYYY-0001 (e.g. TRIP-2026-0001)
    """
    now = timezone.now()
    year_str = str(now.year)
    prefix = f"TRIP-{year_str}-"

    qs = OutstationTrip.objects.filter(trip_number__startswith=prefix)
    if tenant:
        qs = qs.filter(tenant=tenant)

    latest = qs.order_by('-trip_number').first()
    next_num = 1
    if latest and latest.trip_number:
        try:
            suffix = latest.trip_number.split('-')[-1]
            next_num = int(suffix) + 1
        except (ValueError, IndexError):
            next_num = qs.count() + 1

    candidate = f"{prefix}{next_num:04d}"
    collision_qs = OutstationTrip.objects.filter(trip_number=candidate)
    if tenant:
        collision_qs = collision_qs.filter(tenant=tenant)

    while collision_qs.exists():
        next_num += 1
        candidate = f"{prefix}{next_num:04d}"
        collision_qs = OutstationTrip.objects.filter(trip_number=candidate)
        if tenant:
            collision_qs = collision_qs.filter(tenant=tenant)

    return candidate


class OutstationTrip(models.Model):
    """
    Represents an outstation jewellery sales trip / exhibition (e.g. to Gurgaon, Delhi).
    Maintains complete custody lifecycle: Draft -> Stock Issued -> In Progress -> Reconciling -> Closed.
    """

    STATUS_DRAFT = 'Draft'
    STATUS_ISSUED = 'Stock Issued'
    STATUS_IN_PROGRESS = 'In Progress'
    STATUS_RECONCILING = 'Reconciling'
    STATUS_CLOSED = 'Closed'
    STATUS_CANCELLED = 'Cancelled'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft (Staging)'),
        (STATUS_ISSUED, 'Stock Issued (In Transit)'),
        (STATUS_IN_PROGRESS, 'In Progress (Active Sales)'),
        (STATUS_RECONCILING, 'Reconciling (Returns & Auditing)'),
        (STATUS_CLOSED, 'Closed & Fully Reconciled'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='outstation_trips',
        help_text="Tenant showroom owning this trip"
    )
    trip_number = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Unique trip reference (e.g. TRIP-2026-0001)"
    )
    destination_city = models.CharField(
        max_length=120,
        help_text="Destination city (e.g. Gurgaon, Delhi, Jaipur)"
    )
    destination_location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Market / Venue / Exhibition address (e.g. Gold Souk Mall, Karol Bagh)"
    )
    departure_date = models.DateField(
        help_text="Date the jewellery departs the showroom"
    )
    expected_return_date = models.DateField(
        help_text="Scheduled return date to showroom"
    )
    actual_return_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date jewellery and team returned to showroom"
    )
    responsible_employee = models.ForeignKey(
        'team.Employee',
        on_delete=models.PROTECT,
        related_name='responsible_outstation_trips',
        help_text="Primary employee/sales officer holding custody of the jewellery"
    )
    accompanying_staff = models.ManyToManyField(
        'team.Employee',
        blank=True,
        related_name='accompanying_outstation_trips',
        help_text="Additional showroom staff accompanying this trip"
    )
    purpose = models.CharField(
        max_length=200,
        default='B2B Wholesaler & Retail Sales Exhibition',
        help_text="Trip purpose or event title"
    )
    notes = models.TextField(
        blank=True,
        help_text="Travel details, client meeting notes, hotel or vehicle details"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_outstation_trips'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-departure_date', '-created_at']
        verbose_name = 'Outstation Trip'
        verbose_name_plural = 'Outstation Trips'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'trip_number'],
                name='unique_tenant_trip_number',
            ),
        ]

    def __str__(self):
        return f"{self.trip_number} — {self.destination_city} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        if self.departure_date and self.expected_return_date:
            if self.expected_return_date < self.departure_date:
                raise ValidationError({
                    'expected_return_date': 'Expected return date cannot precede the departure date.'
                })
        if self.actual_return_date and self.departure_date:
            if self.actual_return_date < self.departure_date:
                raise ValidationError({
                    'actual_return_date': 'Actual return date cannot precede the departure date.'
                })
        if self.responsible_employee_id and self.tenant_id:
            if self.responsible_employee.tenant_id != self.tenant_id:
                raise ValidationError({
                    'responsible_employee': 'The responsible employee must belong to the same showroom.'
                })

    def save(self, *args, **kwargs):
        if not self.trip_number:
            self.trip_number = generate_trip_number(tenant=self.tenant)
        self.full_clean()
        super().save(*args, **kwargs)

    # ---- Aggregate Stock & Custody Metrics ----
    @property
    def total_issued_items_count(self):
        return self.issued_items.count()

    @property
    def total_issued_value(self):
        val = self.issued_items.aggregate(total=models.Sum('issue_price'))['total']
        return val or Decimal('0.00')

    @property
    def total_issued_gross_weight(self):
        wt = self.issued_items.aggregate(total=models.Sum('issue_gross_weight'))['total']
        return wt or Decimal('0.000')

    @property
    def total_issued_net_weight(self):
        wt = self.issued_items.aggregate(total=models.Sum('issue_net_weight'))['total']
        return wt or Decimal('0.000')

    @property
    def sold_items_count(self):
        return self.issued_items.filter(status=OutstationTripItem.STATUS_SOLD).count()

    @property
    def returned_items_count(self):
        return self.issued_items.filter(status=OutstationTripItem.STATUS_RETURNED).count()

    @property
    def outstanding_items_count(self):
        return self.issued_items.filter(status=OutstationTripItem.STATUS_ISSUED).count()

    @property
    def discrepancy_items_count(self):
        return self.issued_items.filter(
            status__in=[OutstationTripItem.STATUS_DAMAGED, OutstationTripItem.STATUS_MISSING]
        ).count()

    @property
    def unresolved_discrepancies_count(self):
        return self.issued_items.filter(
            status__in=[OutstationTripItem.STATUS_DAMAGED, OutstationTripItem.STATUS_MISSING],
            discrepancy_resolved=False
        ).count()

    # ---- Financial Metrics (Reusing existing Sale & Payment) ----
    @property
    def total_sales_amount(self):
        total = self.trip_sales.aggregate(total=models.Sum('sale__sale_price'))['total']
        return total or Decimal('0.00')

    @property
    def total_payments_received(self):
        from sales.models import Payment
        sale_ids = self.trip_sales.values_list('sale_id', flat=True)
        if not sale_ids:
            return Decimal('0.00')
        total = Payment.objects.filter(sale_id__in=sale_ids).aggregate(total=models.Sum('amount'))['total']
        return total or Decimal('0.00')

    @property
    def total_outstanding_amount(self):
        due = self.total_sales_amount - self.total_payments_received
        return max(Decimal('0.00'), due)

    # Property aliases for template and test convenience
    @property
    def total_items_count(self):
        return self.total_issued_items_count

    @property
    def in_transit_items_count(self):
        return self.outstanding_items_count

    @property
    def total_collected_amount(self):
        return self.total_payments_received

    @property
    def outstanding_balance(self):
        return self.total_outstanding_amount

    @property
    def damaged_missing_count(self):
        return self.discrepancy_items_count

    @property
    def is_overdue(self):
        if self.status != self.STATUS_CLOSED and self.expected_return_date:
            return timezone.now().date() > self.expected_return_date
        return False

    @property
    def is_fully_reconciled(self):
        """All items must be Sold or Returned, or have any Damaged/Missing discrepancy authorized."""
        if self.issued_items.filter(status=OutstationTripItem.STATUS_ISSUED).exists():
            return False
        if self.unresolved_discrepancies_count > 0:
            return False
        return True


class OutstationTripItem(models.Model):
    """
    An individual tagged jewellery piece issued to an OutstationTrip.
    Maintains exact item state: Issued -> Sold / Returned / Damaged / Missing.
    """

    STATUS_ISSUED = 'Issued'
    STATUS_SOLD = 'Sold'
    STATUS_RETURNED = 'Returned'
    STATUS_DAMAGED = 'Damaged'
    STATUS_MISSING = 'Missing'

    STATUS_CHOICES = [
        (STATUS_ISSUED, 'Issued / In Transit'),
        (STATUS_SOLD, 'Sold on Trip'),
        (STATUS_RETURNED, 'Returned to Showroom'),
        (STATUS_DAMAGED, 'Damaged Piece'),
        (STATUS_MISSING, 'Missing / Discrepancy'),
    ]

    trip = models.ForeignKey(
        OutstationTrip,
        on_delete=models.CASCADE,
        related_name='issued_items'
    )
    item = models.ForeignKey(
        'inventory.JewelleryItem',
        on_delete=models.PROTECT,
        related_name='outstation_issuances'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ISSUED,
        db_index=True
    )
    issue_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Price snapshot at time of issuance (INR)"
    )
    issue_gross_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Gross weight snapshot at issuance"
    )
    issue_net_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Net weight snapshot at issuance"
    )
    issued_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_outstation_items'
    )

    # Reconciliation & Discrepancy Tracking
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reconciled_outstation_items'
    )
    reconciliation_notes = models.TextField(blank=True)
    discrepancy_reason = models.TextField(
        blank=True,
        help_text="Reason for damage or missing piece"
    )
    discrepancy_resolved = models.BooleanField(
        default=False,
        help_text="Whether this discrepancy has been officially reviewed and resolved"
    )
    discrepancy_resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_outstation_discrepancies'
    )
    discrepancy_resolution_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-issued_at', 'id']
        verbose_name = 'Outstation Trip Item'
        verbose_name_plural = 'Outstation Trip Items'
        constraints = [
            models.UniqueConstraint(
                fields=['trip', 'item'],
                name='unique_trip_jewellery_item',
            ),
        ]

    def __str__(self):
        return f"{self.item.tag_number or self.item.item_code} on {self.trip.trip_number} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        # Verify cross-tenant isolation
        if self.item_id and self.trip_id:
            if self.item.tenant_id != self.trip.tenant_id:
                raise ValidationError({
                    'item': 'Cross-tenant violation: Item does not belong to the trip showroom.'
                })


class OutstationTripSale(models.Model):
    """
    Links a standard Sale record directly to an OutstationTrip.
    Captures B2B vs B2C trade context without duplicating customer or invoice engines.
    """

    BUYER_B2B = 'B2B'
    BUYER_B2C = 'B2C'
    BUYER_CHOICES = [
        (BUYER_B2B, 'B2B (Jewellery Showroom / Trader / Wholesaler)'),
        (BUYER_B2C, 'B2C (Direct Retail Buyer)'),
    ]

    trip = models.ForeignKey(
        OutstationTrip,
        on_delete=models.CASCADE,
        related_name='trip_sales'
    )
    sale = models.OneToOneField(
        'sales.Sale',
        on_delete=models.CASCADE,
        related_name='outstation_trip_link'
    )
    trip_item = models.ForeignKey(
        OutstationTripItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sale_records'
    )
    buyer_type = models.CharField(
        max_length=10,
        choices=BUYER_CHOICES,
        default=BUYER_B2C,
        db_index=True
    )
    business_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Jewellery business / firm name for B2B buyers"
    )
    business_gstin = models.CharField(
        max_length=15,
        blank=True,
        help_text="GSTIN of the purchasing jewellery business (B2B)"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Outstation Trip Sale'
        verbose_name_plural = 'Outstation Trip Sales'

    def __str__(self):
        return f"Trip {self.trip.trip_number} Sale #{self.sale_id} ({self.buyer_type})"

    def clean(self):
        super().clean()
        if self.sale_id and self.trip_id:
            if self.sale.tenant_id != self.trip.tenant_id:
                raise ValidationError({
                    'sale': 'Cross-tenant violation: Sale does not belong to the same showroom as the trip.'
                })


class OutstationTripAuditLog(models.Model):
    """
    Immutable audit log tracking every action on an OutstationTrip:
    stock issuance, sales, returns, discrepancies, and trip closure.
    """

    ACTION_TRIP_CREATED        = 'TRIP_CREATED'
    ACTION_STATUS_CHANGED      = 'STATUS_CHANGED'
    ACTION_STOCK_ISSUED        = 'STOCK_ISSUED'
    ACTION_SALE_RECORDED       = 'SALE_RECORDED'
    ACTION_STOCK_RETURNED      = 'STOCK_RETURNED'
    ACTION_DISCREPANCY_LOGGED  = 'DISCREPANCY_LOGGED'
    ACTION_DISCREPANCY_RESOLVE = 'DISCREPANCY_RESOLVE'
    ACTION_TRIP_CLOSED         = 'TRIP_CLOSED'

    ACTION_CHOICES = [
        (ACTION_TRIP_CREATED,        'Trip Created'),
        (ACTION_STATUS_CHANGED,      'Status Changed'),
        (ACTION_STOCK_ISSUED,        'Stock Issued'),
        (ACTION_SALE_RECORDED,       'Sale Recorded'),
        (ACTION_STOCK_RETURNED,      'Stock Returned'),
        (ACTION_DISCREPANCY_LOGGED,  'Discrepancy Logged'),
        (ACTION_DISCREPANCY_RESOLVE, 'Discrepancy Resolved'),
        (ACTION_TRIP_CLOSED,         'Trip Closed'),
    ]

    trip = models.ForeignKey(
        OutstationTrip,
        on_delete=models.CASCADE,
        related_name='audit_logs'
    )
    action = models.CharField(
        max_length=50,
        choices=ACTION_CHOICES,
        db_index=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    details = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp', '-id']
        verbose_name = 'Outstation Trip Audit Log'
        verbose_name_plural = 'Outstation Trip Audit Logs'

    def __str__(self):
        username = self.user.username if self.user else 'System'
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {username} - {self.action} on {self.trip.trip_number}"


# ==============================================================================
# EXHIBITION MANAGEMENT MODELS
# ==============================================================================

def generate_exhibition_number(tenant=None):
    """
    Generate sequential exhibition reference formatted as EXH-YYYY-NNNN.
    Scoped per tenant.
    """
    now = timezone.now()
    year_str = str(now.year)
    prefix = f"EXH-{year_str}-"

    qs = Exhibition.objects.filter(exhibition_number__startswith=prefix)
    if tenant:
        qs = qs.filter(tenant=tenant)

    latest = qs.order_by('-exhibition_number').first()
    next_num = 1
    if latest and latest.exhibition_number:
        try:
            suffix = latest.exhibition_number.split('-')[-1]
            next_num = int(suffix) + 1
        except (ValueError, IndexError):
            next_num = qs.count() + 1

    candidate = f"{prefix}{next_num:04d}"
    collision_qs = Exhibition.objects.filter(exhibition_number=candidate)
    if tenant:
        collision_qs = collision_qs.filter(tenant=tenant)

    while collision_qs.exists():
        next_num += 1
        candidate = f"{prefix}{next_num:04d}"
        collision_qs = Exhibition.objects.filter(exhibition_number=candidate)
        if tenant:
            collision_qs = collision_qs.filter(tenant=tenant)

    return candidate


class Exhibition(models.Model):
    """
    Exhibition / Trade Fair management for jewellery exhibitions and expos
    (e.g. IIJS Mumbai, Jewels of India, Dubai Jewellery Show).
    Distinct from ordinary travel trips; manages stall rent, booth staff,
    daily timings, exhibition expenses, and day-wise revenue.
    """

    STATUS_DRAFT        = 'Draft'
    STATUS_ISSUED       = 'Stock Issued'
    STATUS_IN_PROGRESS  = 'In Progress'
    STATUS_RECONCILING  = 'Reconciling'
    STATUS_CLOSED       = 'Closed'
    STATUS_CANCELLED    = 'Cancelled'

    STATUS_CHOICES = [
        (STATUS_DRAFT,        'Draft (Booth Setup)'),
        (STATUS_ISSUED,       'Stock Issued (In Transit to Venue)'),
        (STATUS_IN_PROGRESS,  'In Progress (Exhibition Live)'),
        (STATUS_RECONCILING,  'Reconciling (Post-Expo Returns)'),
        (STATUS_CLOSED,       'Closed & Reconciled'),
        (STATUS_CANCELLED,    'Cancelled'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='exhibitions',
        help_text="Tenant showroom participating in this exhibition"
    )
    exhibition_number = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Unique exhibition code (e.g. EXH-2026-0001)"
    )
    name = models.CharField(
        max_length=200,
        help_text="Exhibition / Expo Title (e.g. IIJS Premiere 2026, Sparkle Surat)"
    )
    venue = models.CharField(
        max_length=250,
        help_text="Exhibition centre / grounds (e.g. Jio World Convention Centre, Hall 1)"
    )
    city = models.CharField(
        max_length=120,
        help_text="Host city (e.g. Mumbai, New Delhi, Bengaluru)"
    )
    organiser = models.CharField(
        max_length=200,
        blank=True,
        help_text="Organising council / agency (e.g. GJEPC, United Exhibitions)"
    )
    stall_number = models.CharField(
        max_length=100,
        help_text="Stall / Booth Identifier (e.g. Hall 1, Booth 1A-24)"
    )
    start_date = models.DateField(help_text="Exhibition inaugural date")
    end_date = models.DateField(help_text="Exhibition conclusion date")
    daily_opening_time = models.TimeField(
        default='10:00:00',
        help_text="Daily expo hall opening time"
    )
    daily_closing_time = models.TimeField(
        default='19:00:00',
        help_text="Daily expo hall closing time"
    )
    responsible_employee = models.ForeignKey(
        'team.Employee',
        on_delete=models.PROTECT,
        related_name='responsible_exhibitions',
        help_text="Lead booth custodian responsible for stock custody"
    )
    booth_staff = models.ManyToManyField(
        'team.Employee',
        blank=True,
        related_name='staffing_exhibitions',
        help_text="Sales officers and attendants stationed at this booth"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True
    )
    notes = models.TextField(
        blank=True,
        help_text="Booth setup notes, security passes, badge details, and instructions"
    )
    actual_return_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date jewellery returned safely to showroom"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_exhibitions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date', '-created_at']
        verbose_name = 'Exhibition'
        verbose_name_plural = 'Exhibitions'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'exhibition_number'],
                name='unique_tenant_exhibition_number'
            ),
        ]

    def __str__(self):
        return f"{self.exhibition_number} — {self.name} ({self.city})"

    def clean(self):
        super().clean()
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValidationError({
                    'end_date': 'Exhibition end date cannot precede start date.'
                })
        if self.responsible_employee_id and self.tenant_id:
            if self.responsible_employee.tenant_id != self.tenant_id:
                raise ValidationError({
                    'responsible_employee': 'Responsible employee must belong to the same showroom.'
                })

    def save(self, *args, **kwargs):
        if not self.exhibition_number:
            self.exhibition_number = generate_exhibition_number(tenant=self.tenant)
        self.full_clean()
        super().save(*args, **kwargs)

    # ---- Aggregate Stock & Custody Metrics ----
    @property
    def total_issued_items_count(self):
        return self.issued_items.count()

    @property
    def total_items_count(self):
        return self.total_issued_items_count

    @property
    def total_issued_value(self):
        val = self.issued_items.aggregate(total=models.Sum('issue_price'))['total']
        return val or Decimal('0.00')

    @property
    def total_issued_gross_weight(self):
        wt = self.issued_items.aggregate(total=models.Sum('issue_gross_weight'))['total']
        return wt or Decimal('0.000')

    @property
    def total_issued_net_weight(self):
        wt = self.issued_items.aggregate(total=models.Sum('issue_net_weight'))['total']
        return wt or Decimal('0.000')

    @property
    def sold_items_count(self):
        return self.issued_items.filter(status=ExhibitionItem.STATUS_SOLD).count()

    @property
    def returned_items_count(self):
        return self.issued_items.filter(status=ExhibitionItem.STATUS_RETURNED).count()

    @property
    def outstanding_items_count(self):
        return self.issued_items.filter(status=ExhibitionItem.STATUS_ISSUED).count()

    @property
    def in_transit_items_count(self):
        return self.outstanding_items_count

    @property
    def discrepancy_items_count(self):
        return self.issued_items.filter(
            status__in=[ExhibitionItem.STATUS_DAMAGED, ExhibitionItem.STATUS_MISSING]
        ).count()

    @property
    def damaged_missing_count(self):
        return self.discrepancy_items_count

    @property
    def unresolved_discrepancies_count(self):
        return self.issued_items.filter(
            status__in=[ExhibitionItem.STATUS_DAMAGED, ExhibitionItem.STATUS_MISSING],
            discrepancy_resolved=False
        ).count()

    # ---- Financial Metrics (Sales, Collections, Expenses) ----
    @property
    def total_sales_amount(self):
        total = self.exhibition_sales.aggregate(total=models.Sum('sale__sale_price'))['total']
        return total or Decimal('0.00')

    @property
    def total_payments_received(self):
        from sales.models import Payment
        sale_ids = self.exhibition_sales.values_list('sale_id', flat=True)
        if not sale_ids:
            return Decimal('0.00')
        total = Payment.objects.filter(sale_id__in=sale_ids).aggregate(total=models.Sum('amount'))['total']
        return total or Decimal('0.00')

    @property
    def total_collected_amount(self):
        return self.total_payments_received

    @property
    def total_outstanding_amount(self):
        due = self.total_sales_amount - self.total_payments_received
        return max(Decimal('0.00'), due)

    @property
    def outstanding_balance(self):
        return self.total_outstanding_amount

    @property
    def total_expenses_amount(self):
        total = self.expenses.aggregate(total=models.Sum('amount'))['total']
        return total or Decimal('0.00')

    @property
    def operating_surplus(self):
        """
        Exhibition Operating Surplus = Sales Revenue - Direct Exhibition Expenses.
        Note: Catalog gross profit is omitted because raw product cost is not stored on JewelleryItem.
        """
        return self.total_sales_amount - self.total_expenses_amount

    @property
    def is_fully_reconciled(self):
        if self.issued_items.filter(status=ExhibitionItem.STATUS_ISSUED).exists():
            return False
        if self.unresolved_discrepancies_count > 0:
            return False
        return True


class ExhibitionExpense(models.Model):
    """
    Exhibition-specific expenses (Stall rent, travel, accommodation, marketing, security).
    """

    CAT_STALL_RENT    = 'Stall Rent'
    CAT_TRAVEL        = 'Travel & Airfare'
    CAT_ACCOMMODATION = 'Hotel & Accommodation'
    CAT_SECURITY      = 'Security & Insurance'
    CAT_LOGISTICS     = 'Logistics & Freight'
    CAT_MARKETING     = 'Marketing & Branding'
    CAT_FOOD          = 'Food & Refreshments'
    CAT_MISC          = 'Miscellaneous'

    CATEGORY_CHOICES = [
        (CAT_STALL_RENT,    'Stall / Booth Space Rent'),
        (CAT_TRAVEL,        'Travel & Flights'),
        (CAT_ACCOMMODATION, 'Hotel / Accommodation'),
        (CAT_SECURITY,      'Security & Vault Transit Insurance'),
        (CAT_LOGISTICS,     'Logistics, Props & Freight'),
        (CAT_MARKETING,     'Marketing, Catalogues & Branding'),
        (CAT_FOOD,          'Food & Refreshments'),
        (CAT_MISC,          'Miscellaneous Expenses'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='exhibition_expenses'
    )
    exhibition = models.ForeignKey(
        Exhibition,
        on_delete=models.CASCADE,
        related_name='expenses'
    )
    category = models.CharField(
        max_length=40,
        choices=CATEGORY_CHOICES,
        default=CAT_MISC
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Expense amount in INR"
    )
    expense_date = models.DateField(default=timezone.now)
    payee = models.CharField(
        max_length=200,
        help_text="Paid to (e.g. GJEPC, Vistara Airlines, Hotel Taj)"
    )
    payment_method = models.CharField(
        max_length=50,
        default='Bank Transfer',
        help_text="Payment method used (e.g. Bank Transfer, UPI, Company Card, Cash)"
    )
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Invoice / Receipt / UTR reference number"
    )
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-expense_date', '-id']
        verbose_name = 'Exhibition Expense'
        verbose_name_plural = 'Exhibition Expenses'

    def __str__(self):
        return f"{self.category}: ₹{self.amount} ({self.exhibition.exhibition_number})"

    def clean(self):
        super().clean()
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({'amount': 'Expense amount must be greater than zero.'})
        if self.exhibition_id and self.tenant_id:
            if self.exhibition.tenant_id != self.tenant_id:
                raise ValidationError({'exhibition': 'Cross-tenant violation: Exhibition does not belong to this showroom.'})


class ExhibitionItem(models.Model):
    """
    Jewellery piece issued to an exhibition booth.
    """

    STATUS_ISSUED    = 'Issued'
    STATUS_SOLD      = 'Sold'
    STATUS_RETURNED  = 'Returned'
    STATUS_DAMAGED   = 'Damaged'
    STATUS_MISSING   = 'Missing'

    STATUS_CHOICES = [
        (STATUS_ISSUED,    'Issued / At Exhibition'),
        (STATUS_SOLD,      'Sold at Exhibition'),
        (STATUS_RETURNED,  'Returned to Showroom'),
        (STATUS_DAMAGED,   'Damaged Piece'),
        (STATUS_MISSING,   'Missing / Discrepancy'),
    ]

    exhibition = models.ForeignKey(
        Exhibition,
        on_delete=models.CASCADE,
        related_name='issued_items'
    )
    item = models.ForeignKey(
        'inventory.JewelleryItem',
        on_delete=models.PROTECT,
        related_name='exhibition_issuances'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ISSUED,
        db_index=True
    )
    issue_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Tag price snapshot at issuance (INR)"
    )
    issue_gross_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True
    )
    issue_net_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True
    )
    issued_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_exhibition_items'
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reconciled_exhibition_items'
    )
    reconciliation_notes = models.TextField(blank=True)
    discrepancy_reason = models.TextField(blank=True)
    discrepancy_resolved = models.BooleanField(default=False)
    discrepancy_resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_exhibition_discrepancies'
    )
    discrepancy_resolution_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-issued_at', 'id']
        verbose_name = 'Exhibition Item'
        verbose_name_plural = 'Exhibition Items'
        constraints = [
            models.UniqueConstraint(
                fields=['exhibition', 'item'],
                name='unique_exhibition_jewellery_item'
            ),
        ]

    def __str__(self):
        return f"{self.item.tag_number or self.item.item_code} on {self.exhibition.exhibition_number} ({self.status})"


class ExhibitionSale(models.Model):
    """
    Links a sales.Sale record made at an exhibition to the Exhibition model.
    """

    BUYER_B2B = 'B2B'
    BUYER_B2C = 'B2C'

    BUYER_CHOICES = [
        (BUYER_B2B, 'B2B (Wholesale Jeweller / Trade Buyer)'),
        (BUYER_B2C, 'B2C (Retail Exhibition Visitor)'),
    ]

    exhibition = models.ForeignKey(
        Exhibition,
        on_delete=models.CASCADE,
        related_name='exhibition_sales'
    )
    sale = models.OneToOneField(
        'sales.Sale',
        on_delete=models.CASCADE,
        related_name='exhibition_link'
    )
    exhibition_item = models.ForeignKey(
        ExhibitionItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sale_records'
    )
    buyer_type = models.CharField(
        max_length=10,
        choices=BUYER_CHOICES,
        default=BUYER_B2C,
        db_index=True
    )
    business_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Jewellery business / firm name for B2B buyers"
    )
    business_gstin = models.CharField(
        max_length=15,
        blank=True,
        help_text="GSTIN of trade buyer"
    )
    sale_datetime = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp of sale execution at the exhibition booth"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sale_datetime']
        verbose_name = 'Exhibition Sale'
        verbose_name_plural = 'Exhibition Sales'

    def __str__(self):
        return f"Exhibition {self.exhibition.exhibition_number} Sale #{self.sale_id} ({self.buyer_type})"


class ExhibitionAuditLog(models.Model):
    """
    Immutable audit trail for exhibition lifecycle events.
    """

    ACTION_EXHIBITION_CREATED  = 'EXHIBITION_CREATED'
    ACTION_STATUS_CHANGED      = 'STATUS_CHANGED'
    ACTION_STOCK_ISSUED        = 'STOCK_ISSUED'
    ACTION_SALE_RECORDED       = 'SALE_RECORDED'
    ACTION_EXPENSE_LOGGED      = 'EXPENSE_LOGGED'
    ACTION_STOCK_RETURNED      = 'STOCK_RETURNED'
    ACTION_DISCREPANCY_LOGGED  = 'DISCREPANCY_LOGGED'
    ACTION_DISCREPANCY_RESOLVE = 'DISCREPANCY_RESOLVE'
    ACTION_EXHIBITION_CLOSED   = 'EXHIBITION_CLOSED'

    ACTION_CHOICES = [
        (ACTION_EXHIBITION_CREATED,  'Exhibition Created'),
        (ACTION_STATUS_CHANGED,      'Status Changed'),
        (ACTION_STOCK_ISSUED,        'Stock Issued'),
        (ACTION_SALE_RECORDED,       'Sale Recorded'),
        (ACTION_EXPENSE_LOGGED,      'Expense Logged'),
        (ACTION_STOCK_RETURNED,      'Stock Returned'),
        (ACTION_DISCREPANCY_LOGGED,  'Discrepancy Logged'),
        (ACTION_DISCREPANCY_RESOLVE, 'Discrepancy Resolved'),
        (ACTION_EXHIBITION_CLOSED,   'Exhibition Closed'),
    ]

    exhibition = models.ForeignKey(
        Exhibition,
        on_delete=models.CASCADE,
        related_name='audit_logs'
    )
    action = models.CharField(
        max_length=50,
        choices=ACTION_CHOICES,
        db_index=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    details = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp', '-id']
        verbose_name = 'Exhibition Audit Log'
        verbose_name_plural = 'Exhibition Audit Logs'

    def __str__(self):
        username = self.user.username if self.user else 'System'
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {username} - {self.action} on {self.exhibition.exhibition_number}"

