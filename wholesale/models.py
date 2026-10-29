import logging
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from accounts.models import validate_gstin, validate_email_address, validate_proper_email
from inventory.models import JewelleryItem, Category

logger = logging.getLogger('wholesale.models')


# ==============================================================================
# SEQUENCE GENERATOR FOR WHOLESALE IDENTIFIERS
# ==============================================================================

class WholesaleSequence(models.Model):
    """
    Atomic sequence generator for Wholesale Orders, Invoices, Dispatches,
    Payments, Returns, and Credit Notes.
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='wholesale_sequences',
        help_text="Tenant owning this sequence counter"
    )
    sequence_type = models.CharField(max_length=50, help_text="e.g. order, dispatch, invoice, payment, return, credit_note")
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Wholesale Sequence'
        verbose_name_plural = 'Wholesale Sequences'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'sequence_type'],
                name='unique_tenant_wholesale_sequence',
            ),
        ]

    def __str__(self):
        return f"{self.sequence_type}: {self.last_number} (Tenant: {self.tenant_id})"

    @classmethod
    def get_next_number(cls, tenant, sequence_type, prefix='WHL'):
        """Thread-safe sequential reference generation using row locking."""
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(
                tenant=tenant,
                sequence_type=sequence_type,
                defaults={'last_number': 0}
            )
            seq.last_number += 1
            seq.save(update_fields=['last_number'])
            return f"{prefix}-{seq.last_number:05d}"


# ==============================================================================
# RETAILER / PARTY MANAGEMENT
# ==============================================================================

class RetailerParty(models.Model):
    """
    Wholesale Buyer / Jewellery Retailer Party that buys stock from the supplier.
    Strictly isolated per tenant.
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='wholesale_parties',
        help_text="Wholesale supplier tenant owning this retailer account"
    )
    branch = models.ForeignKey(
        'team.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='retailer_parties',
        help_text="Branch managing this retailer party"
    )
    name = models.CharField(max_length=200, help_text="Shop / Business Name")
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, help_text="Primary contact phone / mobile")
    email = models.EmailField(blank=True, validators=[validate_email_address])
    billing_address = models.TextField(blank=True)
    shipping_address = models.TextField(blank=True)
    gstin = models.CharField(max_length=15, blank=True, validators=[validate_gstin], help_text="15-character GSTIN")
    pan_number = models.CharField(max_length=20, blank=True, help_text="PAN Number")
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Max credit limit allowed (0 for no limit)")
    payment_terms_days = models.PositiveIntegerField(default=30, help_text="Standard payment terms in days (e.g. 15, 30, 45)")
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Starting receivable balance (+ve for debit / due from retailer)")
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Retailer / Party'
        verbose_name_plural = 'Retailers / Parties'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'name'],
                name='unique_tenant_retailer_name',
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.phone})" if self.phone else self.name

    def clean(self):
        super().clean()
        if self.gstin:
            self.gstin = self.gstin.strip().upper()
        if self.pan_number:
            self.pan_number = self.pan_number.strip().upper()
        if self.phone:
            self.phone = self.phone.strip()
        if self.email:
            self.email = validate_proper_email(self.email, field_label='Email address', required=False)

    # ---- Derived Balance & Ledger Properties --------------------------------
    @property
    def total_orders_count(self):
        return self.orders.exclude(status=WholesaleOrder.STATUS_CANCELLED).count()

    @property
    def total_invoiced_amount(self):
        total = self.invoices.exclude(status=WholesaleInvoice.STATUS_CANCELLED).aggregate(total=models.Sum('total_amount'))['total']
        return total or Decimal('0.00')

    @property
    def total_paid_amount(self):
        total = self.payments.aggregate(total=models.Sum('amount'))['total']
        return total or Decimal('0.00')

    @property
    def total_returns_credit_amount(self):
        total = self.returns.filter(
            status__in=[WholesaleReturn.STATUS_APPROVED, WholesaleReturn.STATUS_RESTOCKED, WholesaleReturn.STATUS_COMPLETED],
            credit_note_issued=True
        ).aggregate(total=models.Sum('total_credit_amount'))['total']
        return total or Decimal('0.00')

    @property
    def current_balance(self):
        """
        Calculated Outstanding Balance (Receivable):
        Opening Balance + Total Invoiced - Total Payments Received - Approved Returns Credit.
        """
        op = self.opening_balance or Decimal('0.00')
        return op + self.total_invoiced_amount - self.total_paid_amount - self.total_returns_credit_amount

    @property
    def available_credit(self):
        if self.credit_limit and self.credit_limit > 0:
            avail = self.credit_limit - self.current_balance
            return max(Decimal('0.00'), avail)
        return Decimal('0.00')

    @property
    def is_over_credit_limit(self):
        if self.credit_limit and self.credit_limit > 0:
            return self.current_balance > self.credit_limit
        return False

    @property
    def overdue_invoices(self):
        today = timezone.localdate()
        return self.invoices.filter(
            status__in=[WholesaleInvoice.STATUS_UNPAID, WholesaleInvoice.STATUS_PARTIALLY_PAID],
            due_date__lt=today
        ).exclude(status=WholesaleInvoice.STATUS_CANCELLED)


# ==============================================================================
# WHOLESALE PRICING RULES & OVERRIDES
# ==============================================================================

class WholesalePricingRule(models.Model):
    """
    Tiered or party-specific wholesale pricing rules, volume discounts,
    and minimum order quantity rules.
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='wholesale_pricing_rules'
    )
    party = models.ForeignKey(
        RetailerParty,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='pricing_rules',
        help_text="Applies exclusively to this retailer if set, or all retailers if blank"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='wholesale_pricing_rules',
        help_text="Applies to all products in this category if set"
    )
    item = models.ForeignKey(
        JewelleryItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='wholesale_pricing_rules',
        help_text="Applies to this specific jewellery design/piece if set"
    )
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Overall discount % off retail selling price"
    )
    making_charge_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Discount % applied to making charges for wholesale"
    )
    fixed_price_override = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fixed per-piece wholesale price override"
    )
    minimum_order_quantity = models.PositiveIntegerField(
        default=1,
        help_text="Minimum pieces required to qualify for this rule"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        target = self.item.name if self.item else (self.category.name if self.category else 'All Catalogue')
        scope = f" for {self.party.name}" if self.party else " (Global Wholesale)"
        return f"Rule: {target}{scope} - {self.discount_percent}% off"


# ==============================================================================
# WHOLESALE ORDER & ORDER ITEMS
# ==============================================================================

class WholesaleOrder(models.Model):
    """
    Wholesale Order placed by or created for a Retailer Party.
    Lifecycle:
      DRAFT -> CONFIRMED -> PROCESSING -> READY_FOR_DISPATCH -> DISPATCHED -> COMPLETED
      (CANCELLED is permitted from pre-completion states with audit log).
    """
    STATUS_DRAFT = 'Draft'
    STATUS_CONFIRMED = 'Confirmed'
    STATUS_PROCESSING = 'Processing'
    STATUS_READY_FOR_DISPATCH = 'Ready for Dispatch'
    STATUS_DISPATCHED = 'Dispatched'
    STATUS_COMPLETED = 'Completed'
    STATUS_CANCELLED = 'Cancelled'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_READY_FOR_DISPATCH, 'Ready for Dispatch'),
        (STATUS_DISPATCHED, 'Dispatched'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    VALID_TRANSITIONS = {
        STATUS_DRAFT: [STATUS_CONFIRMED, STATUS_CANCELLED],
        STATUS_CONFIRMED: [STATUS_PROCESSING, STATUS_READY_FOR_DISPATCH, STATUS_CANCELLED],
        STATUS_PROCESSING: [STATUS_READY_FOR_DISPATCH, STATUS_CANCELLED],
        STATUS_READY_FOR_DISPATCH: [STATUS_DISPATCHED, STATUS_CANCELLED],
        STATUS_DISPATCHED: [STATUS_COMPLETED],
        STATUS_COMPLETED: [],
        STATUS_CANCELLED: [],
    }

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='wholesale_orders'
    )
    order_number = models.CharField(max_length=50, help_text="Unique sequential order number e.g. WORD-00001")
    party = models.ForeignKey(RetailerParty, on_delete=models.PROTECT, related_name='orders')
    order_date = models.DateField(default=timezone.now)
    expected_delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True, help_text="Order notes visible to retailer")
    internal_remarks = models.TextField(blank=True, help_text="Internal workshop/supplier remarks")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='wholesale_orders')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'order_number'],
                name='unique_tenant_wholesale_order_number',
            ),
        ]

    def __str__(self):
        return f"{self.order_number} - {self.party.name} ({self.status})"

    def can_transition_to(self, new_status):
        return new_status in self.VALID_TRANSITIONS.get(self.status, [])

    def calculate_totals(self, save=True):
        """Recalculate subtotal, tax and total amount from items."""
        items = list(self.items.all())
        subtotal = sum((it.total_price for it in items), Decimal('0.00'))
        tax_total = sum((it.tax_amount for it in items), Decimal('0.00'))
        self.subtotal = subtotal
        self.tax_amount = tax_total
        self.total_amount = subtotal + tax_total - (self.discount_amount or Decimal('0.00'))
        if save and self.pk:
            self.save(update_fields=['subtotal', 'tax_amount', 'total_amount', 'updated_at'])
        return self.total_amount

    @property
    def total_quantity(self):
        return sum((it.quantity for it in self.items.all()), 0)

    @property
    def dispatched_quantity(self):
        return sum((it.dispatched_quantity for it in self.items.all()), 0)

    @property
    def is_fully_dispatched(self):
        t_qty = self.total_quantity
        return t_qty > 0 and self.dispatched_quantity >= t_qty


class WholesaleOrderItem(models.Model):
    """A line item inside a Wholesale Order with preserved historical pricing."""
    order = models.ForeignKey(WholesaleOrder, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(JewelleryItem, on_delete=models.PROTECT, related_name='wholesale_order_items')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Historical locked wholesale unit price")
    making_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    wastage_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('3.00'), help_text="GST % (e.g. 3.00%)")
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Taxable line subtotal (quantity * unit_price - discount)")
    dispatched_quantity = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.quantity}x {self.item.name} @ Rs. {self.unit_price} (Order #{self.order.order_number})"

    @property
    def remaining_dispatch_quantity(self):
        return max(0, self.quantity - self.dispatched_quantity)


# ==============================================================================
# STOCK DISPATCH WORKFLOW
# ==============================================================================

class WholesaleDispatch(models.Model):
    """
    Physical shipment / dispatch of goods for a confirmed wholesale order.
    Deducts stock atomically using inventory.stock.apply_stock_change.
    """
    STATUS_PENDING = 'Pending'
    STATUS_IN_TRANSIT = 'In Transit'
    STATUS_DELIVERED = 'Delivered'
    STATUS_CANCELLED = 'Cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_IN_TRANSIT, 'In Transit'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='wholesale_dispatches'
    )
    dispatch_number = models.CharField(max_length=50, help_text="Unique dispatch code e.g. WDSP-00001")
    order = models.ForeignKey(WholesaleOrder, on_delete=models.CASCADE, related_name='dispatches')
    party = models.ForeignKey(RetailerParty, on_delete=models.CASCADE, related_name='dispatches')
    dispatch_date = models.DateTimeField(default=timezone.now)
    courier_name = models.CharField(max_length=150, blank=True, help_text="Logistics carrier / courier name")
    tracking_number = models.CharField(max_length=150, blank=True, help_text="Airway bill / LR / Tracking ID")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DELIVERED)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='wholesale_dispatches')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-dispatch_date', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'dispatch_number'],
                name='unique_tenant_wholesale_dispatch_number',
            ),
        ]

    def __str__(self):
        return f"{self.dispatch_number} for {self.order.order_number} to {self.party.name}"

    @property
    def total_quantity(self):
        return sum((it.quantity for it in self.items.all()), 0)


class WholesaleDispatchItem(models.Model):
    """Line item within a dispatch."""
    dispatch = models.ForeignKey(WholesaleDispatch, on_delete=models.CASCADE, related_name='items')
    order_item = models.ForeignKey(WholesaleOrderItem, on_delete=models.CASCADE, related_name='dispatch_items')
    item = models.ForeignKey(JewelleryItem, on_delete=models.PROTECT, related_name='wholesale_dispatch_items')
    quantity = models.PositiveIntegerField(default=1)
    tag_number = models.CharField(max_length=50, blank=True, help_text="Specific tag number if individual piece dispatched")

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.quantity}x {self.item.name} on {self.dispatch.dispatch_number}"


# ==============================================================================
# WHOLESALE INVOICING & BILLING
# ==============================================================================

class WholesaleInvoice(models.Model):
    """
    Wholesale Tax Invoice generated against fulfilled/dispatched wholesale orders.
    Complies with HSN 7113, GST regulations, and multi-tenancy.
    """
    STATUS_UNPAID = 'Unpaid'
    STATUS_PARTIALLY_PAID = 'Partially Paid'
    STATUS_PAID = 'Paid'
    STATUS_CANCELLED = 'Cancelled'

    STATUS_CHOICES = [
        (STATUS_UNPAID, 'Unpaid'),
        (STATUS_PARTIALLY_PAID, 'Partially Paid'),
        (STATUS_PAID, 'Paid'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='wholesale_invoices'
    )
    invoice_number = models.CharField(max_length=50, help_text="Unique invoice reference e.g. WINV-00001")
    order = models.ForeignKey(WholesaleOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    dispatch = models.ForeignKey(WholesaleDispatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    party = models.ForeignKey(RetailerParty, on_delete=models.PROTECT, related_name='invoices')
    invoice_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_UNPAID)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='wholesale_invoices')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-invoice_date', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'invoice_number'],
                name='unique_tenant_wholesale_invoice_number',
            ),
        ]

    def __str__(self):
        return f"{self.invoice_number} - {self.party.name} (Rs. {self.total_amount})"

    @property
    def paid_amount(self):
        """Sum of payment allocations against this invoice."""
        total = self.payment_allocations.aggregate(total=models.Sum('allocated_amount'))['total']
        return total or Decimal('0.00')

    @property
    def outstanding_amount(self):
        due = self.total_amount - self.paid_amount
        return max(Decimal('0.00'), due)

    @property
    def is_overdue(self):
        if self.status in (self.STATUS_PAID, self.STATUS_CANCELLED):
            return False
        if not self.due_date:
            return False
        return self.due_date < timezone.localdate()

    def update_payment_status(self, save=True):
        if self.status == self.STATUS_CANCELLED:
            return self.status
        paid = self.paid_amount
        if paid <= 0:
            self.status = self.STATUS_UNPAID
        elif paid >= self.total_amount:
            self.status = self.STATUS_PAID
        else:
            self.status = self.STATUS_PARTIALLY_PAID
        if save and self.pk:
            self.save(update_fields=['status'])
        return self.status


class WholesaleInvoiceItem(models.Model):
    """Line item in a Wholesale Invoice."""
    invoice = models.ForeignKey(WholesaleInvoice, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(JewelleryItem, on_delete=models.PROTECT, related_name='wholesale_invoice_items')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('3.00'))
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.quantity}x {self.item.name} on {self.invoice.invoice_number}"


# ==============================================================================
# PAYMENTS & PAYMENT ALLOCATIONS
# ==============================================================================

class RetailerPayment(models.Model):
    """Money received from a wholesale retailer."""
    PAYMENT_METHODS = [
        ('Bank Transfer', 'Bank Transfer (NEFT/RTGS/IMPS)'),
        ('Cheque', 'Cheque / Draft'),
        ('UPI', 'UPI / QR'),
        ('Cash', 'Cash'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='retailer_payments'
    )
    payment_number = models.CharField(max_length=50, help_text="e.g. WREC-00001")
    party = models.ForeignKey(RetailerParty, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField(default=timezone.now)
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHODS, default='Bank Transfer')
    reference = models.CharField(max_length=100, blank=True, help_text="Cheque / UTR / Transaction reference number")
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='retailer_payments')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'payment_number'],
                name='unique_tenant_retailer_payment_number',
            ),
        ]

    def __str__(self):
        return f"{self.payment_number} - Rs. {self.amount} from {self.party.name}"

    @property
    def allocated_amount(self):
        total = self.allocations.aggregate(total=models.Sum('allocated_amount'))['total']
        return total or Decimal('0.00')

    @property
    def unallocated_amount(self):
        unalloc = self.amount - self.allocated_amount
        return max(Decimal('0.00'), unalloc)


class RetailerPaymentAllocation(models.Model):
    """Maps a payment portion to a specific wholesale invoice."""
    payment = models.ForeignKey(RetailerPayment, on_delete=models.CASCADE, related_name='allocations')
    invoice = models.ForeignKey(WholesaleInvoice, on_delete=models.CASCADE, related_name='payment_allocations')
    allocated_amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"Rs. {self.allocated_amount} on {self.invoice.invoice_number} from {self.payment.payment_number}"


# ==============================================================================
# RETURNS, RESTOCKING & CREDIT NOTES
# ==============================================================================

class WholesaleReturn(models.Model):
    """
    Wholesale Return (RMA) record for stock returned by a retailer party.
    Workflow:
      REQUESTED -> APPROVED / REJECTED -> RESTOCKED (optional) -> COMPLETED
    """
    STATUS_REQUESTED = 'Requested'
    STATUS_APPROVED = 'Approved'
    STATUS_REJECTED = 'Rejected'
    STATUS_RESTOCKED = 'Restocked'
    STATUS_COMPLETED = 'Completed'

    STATUS_CHOICES = [
        (STATUS_REQUESTED, 'Requested'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_RESTOCKED, 'Restocked'),
        (STATUS_COMPLETED, 'Completed'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='wholesale_returns'
    )
    return_number = models.CharField(max_length=50, help_text="e.g. WRET-00001")
    party = models.ForeignKey(RetailerParty, on_delete=models.CASCADE, related_name='returns')
    invoice = models.ForeignKey(WholesaleInvoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='returns')
    order = models.ForeignKey(WholesaleOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='returns')
    return_date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    total_credit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    reason = models.CharField(max_length=150, help_text="Reason for return (Defective, Design mismatch, Unsold, etc.)")
    inspection_notes = models.TextField(blank=True, help_text="Physical inspection notes from vault/karigar")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_returns')
    approved_at = models.DateTimeField(null=True, blank=True)
    credit_note_issued = models.BooleanField(default=False)
    credit_note_number = models.CharField(max_length=50, blank=True, help_text="e.g. WCN-00001")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-return_date', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'return_number'],
                name='unique_tenant_wholesale_return_number',
            ),
        ]

    def __str__(self):
        return f"{self.return_number} - {self.party.name} ({self.status})"

    def calculate_totals(self, save=True):
        total = sum((it.quantity * it.unit_price for it in self.items.all()), Decimal('0.00'))
        self.total_credit_amount = total
        if save and self.pk:
            self.save(update_fields=['total_credit_amount'])
        return total


class WholesaleReturnItem(models.Model):
    """Line item within a wholesale return."""
    DISP_SELLABLE = 'Sellable'
    DISP_DAMAGED = 'Damaged'
    DISP_REPAIR = 'Repair Required'
    DISP_MELT = 'Melt Down'

    DISPOSITION_CHOICES = [
        (DISP_SELLABLE, 'Sellable (Restock to Showroom)'),
        (DISP_DAMAGED, 'Damaged (Vault / Scrap)'),
        (DISP_REPAIR, 'Repair Required (Send to Karigar)'),
        (DISP_MELT, 'Melt Down (Gold Refinery)'),
    ]

    wholesale_return = models.ForeignKey(WholesaleReturn, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(JewelleryItem, on_delete=models.PROTECT, related_name='wholesale_return_items')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    disposition = models.CharField(max_length=30, choices=DISPOSITION_CHOICES, default=DISP_SELLABLE)
    restocked = models.BooleanField(default=False, help_text="True once physical stock is restored to inventory")

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.quantity}x {self.item.name} on Return #{self.wholesale_return.return_number}"


# ==============================================================================
# AUDITABLE RETAILER ACCOUNT LEDGER
# ==============================================================================

class RetailerLedgerEntry(models.Model):
    """
    Immutable double-entry party ledger for wholesale retailer accounts.
    Provides complete auditability of debits, credits, and running balance.
    """
    TYPE_OPENING_BALANCE = 'OPENING_BALANCE'
    TYPE_INVOICE = 'INVOICE'
    TYPE_PAYMENT = 'PAYMENT'
    TYPE_CREDIT_NOTE = 'CREDIT_NOTE'
    TYPE_ADJUSTMENT = 'ADJUSTMENT'

    ENTRY_TYPES = [
        (TYPE_OPENING_BALANCE, 'Opening Balance'),
        (TYPE_INVOICE, 'Invoice Debit'),
        (TYPE_PAYMENT, 'Payment Received'),
        (TYPE_CREDIT_NOTE, 'Credit Note'),
        (TYPE_ADJUSTMENT, 'Adjustment'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='retailer_ledger_entries'
    )
    party = models.ForeignKey(RetailerParty, on_delete=models.CASCADE, related_name='ledger_entries')
    entry_type = models.CharField(max_length=30, choices=ENTRY_TYPES)
    entry_date = models.DateField(default=timezone.now)
    reference_number = models.CharField(max_length=50)
    debit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Amount owed increases (e.g. Invoice)")
    credit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Amount owed decreases (e.g. Payment/Return)")
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Running balance after this entry")
    invoice = models.ForeignKey(WholesaleInvoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='ledger_entries')
    payment = models.ForeignKey(RetailerPayment, on_delete=models.SET_NULL, null=True, blank=True, related_name='ledger_entries')
    return_ref = models.ForeignKey(WholesaleReturn, on_delete=models.SET_NULL, null=True, blank=True, related_name='ledger_entries')
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['entry_date', 'id']

    def __str__(self):
        return f"{self.party.name} | {self.entry_type} | {self.reference_number} | Dr: {self.debit_amount} Cr: {self.credit_amount} Bal: {self.balance_after}"

    @classmethod
    def record_entry(cls, tenant, party, entry_type, reference_number, debit_amount=Decimal('0.00'), credit_amount=Decimal('0.00'), description='', invoice=None, payment=None, return_ref=None, entry_date=None):
        """Append an immutable ledger entry and calculate running balance."""
        with transaction.atomic():
            last_entry = cls.objects.filter(party=party).order_by('-id').first()
            prev_balance = last_entry.balance_after if last_entry else (party.opening_balance or Decimal('0.00'))
            new_balance = prev_balance + Decimal(str(debit_amount or '0.00')) - Decimal(str(credit_amount or '0.00'))
            entry = cls.objects.create(
                tenant=tenant,
                party=party,
                entry_type=entry_type,
                entry_date=entry_date or timezone.localdate(),
                reference_number=reference_number,
                debit_amount=debit_amount,
                credit_amount=credit_amount,
                balance_after=new_balance,
                invoice=invoice,
                payment=payment,
                return_ref=return_ref,
                description=description
            )
            return entry
