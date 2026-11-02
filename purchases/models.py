import logging
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger('purchases.models')


# ==============================================================================
# SEQUENCE GENERATOR FOR PURCHASES
# ==============================================================================

class PurchaseSequence(models.Model):
    """
    Atomic thread-safe sequence generator for Purchase Invoices, Supplier Codes,
    Payments, and Purchase Returns.
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='purchase_sequences',
        help_text="Tenant owning this sequence counter"
    )
    sequence_type = models.CharField(
        max_length=50,
        help_text="e.g. purchase, supplier, payment, return"
    )
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Purchase Sequence'
        verbose_name_plural = 'Purchase Sequences'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'sequence_type'],
                name='unique_tenant_purchase_sequence',
            ),
        ]

    def __str__(self):
        return f"{self.sequence_type}: {self.last_number} (Tenant: {self.tenant_id})"

    @classmethod
    def get_next_number(cls, tenant, sequence_type, prefix='PUR', digits=5):
        """Thread-safe sequential reference generation using row locking."""
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(
                tenant=tenant,
                sequence_type=sequence_type,
                defaults={'last_number': 0}
            )
            seq.last_number += 1
            seq.save(update_fields=['last_number'])
            clean_prefix = (prefix or '').strip().rstrip('-')
            if clean_prefix:
                return f"{clean_prefix}-{seq.last_number:0{digits}d}"
            return f"{seq.last_number:0{digits}d}"


# ==============================================================================
# PURCHASE SETTINGS
# ==============================================================================

class PurchaseSetting(models.Model):
    """
    Tenant-specific configuration parameters for the Purchase Management Module.
    """
    TAX_TYPE_CHOICES = (
        ('CGST_SGST', 'Intra-State (CGST + SGST)'),
        ('IGST', 'Inter-State (IGST)'),
        ('EXEMPT', 'Tax Exempted'),
    )

    tenant = models.OneToOneField(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='purchase_setting'
    )
    purchase_prefix = models.CharField(max_length=15, default='PUR', help_text="Prefix for Purchase Invoices")
    payment_prefix = models.CharField(max_length=15, default='PPAY', help_text="Prefix for Supplier Payment Vouchers")
    return_prefix = models.CharField(max_length=15, default='PRET', help_text="Prefix for Purchase Debit Notes / Returns")
    supplier_prefix = models.CharField(max_length=15, default='SUP', help_text="Prefix for Supplier Codes")
    default_payment_terms_days = models.PositiveIntegerField(default=30, help_text="Default due days for invoices")
    default_tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('3.00'), help_text="Default GST % (configurable)")
    default_tax_type = models.CharField(max_length=20, choices=TAX_TYPE_CHOICES, default='CGST_SGST')
    auto_create_inventory_for_ready_made = models.BooleanField(
        default=True,
        help_text="Automatically create inventory items in JewelleryStock when ready-made jewellery purchases are confirmed"
    )
    auto_create_inventory_for_bullion = models.BooleanField(
        default=True,
        help_text="Automatically track bullion/bar purchases in stock when confirmed"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Purchase Settings - {self.tenant}"

    @classmethod
    def load(cls, tenant):
        """Get or create singleton configuration record per tenant."""
        obj, _ = cls.objects.get_or_create(tenant=tenant)
        return obj


# ==============================================================================
# SUPPLIER / PARTY MANAGEMENT
# ==============================================================================

class Supplier(models.Model):
    """
    Supplier / Party master catalogue representing bullion dealers, manufacturers,
    karigar workshops, diamond merchants, and stone vendors.
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='suppliers'
    )
    branch = models.ForeignKey(
        'team.Branch',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='suppliers',
        help_text="Default originating branch or null for global tenant party"
    )
    supplier_code = models.CharField(max_length=30, db_index=True)
    name = models.CharField(max_length=200, help_text="Supplier / Party / Business Name")
    contact_person = models.CharField(max_length=150, blank=True)
    mobile = models.CharField(max_length=20, db_index=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    state_code = models.CharField(max_length=10, blank=True, help_text="2-digit GST state code")
    pincode = models.CharField(max_length=10, blank=True)
    gstin = models.CharField(max_length=20, blank=True, help_text="15-character GSTIN")
    pan_number = models.CharField(max_length=20, blank=True)

    # Bank Settlement Details
    bank_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    ifsc_code = models.CharField(max_length=25, blank=True)
    upi_id = models.CharField(max_length=100, blank=True)

    # Balances
    # Positive = Store owes Supplier (Accounts Payable); Negative = Advance given to Supplier
    opening_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Positive = Shop owes Supplier; Negative = Advance with Supplier"
    )
    current_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00')
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Supplier'
        verbose_name_plural = 'Suppliers'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'supplier_code'],
                name='unique_tenant_supplier_code'
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.supplier_code})"

    @property
    def abs_current_balance(self):
        """Absolute value of current balance for presentation."""
        return abs(self.current_balance or Decimal('0.00'))

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.supplier_code and self.tenant_id:
            settings_obj = PurchaseSetting.load(tenant=self.tenant)
            prefix = settings_obj.supplier_prefix or 'SUP'
            self.supplier_code = PurchaseSequence.get_next_number(self.tenant, 'supplier', prefix=prefix)
        if is_new and self.current_balance == Decimal('0.00'):
            self.current_balance = self.opening_balance
        super().save(*args, **kwargs)

        if is_new and self.opening_balance != Decimal('0.00'):
            # Create opening balance ledger entry
            SupplierLedgerEntry.objects.create(
                tenant=self.tenant,
                branch=self.branch,
                supplier=self,
                entry_type='OPENING_BALANCE',
                entry_date=timezone.localdate(),
                reference_number=self.supplier_code,
                debit_amount=Decimal('0.00') if self.opening_balance > 0 else abs(self.opening_balance),
                credit_amount=self.opening_balance if self.opening_balance > 0 else Decimal('0.00'),
                balance_after=self.opening_balance,
                description='Opening Balance recorded on party creation'
            )

    def recalculate_balance(self):
        """
        Recalculate balance strictly from opening balance + credits (invoices) - debits (payments, returns).
        """
        entries = self.ledger_entries.order_by('entry_date', 'id')
        balance = Decimal('0.00')
        for entry in entries:
            balance += (entry.credit_amount - entry.debit_amount)
            if entry.balance_after != balance:
                entry.balance_after = balance
                entry.save(update_fields=['balance_after'])
        self.current_balance = balance
        self.save(update_fields=['current_balance'])
        return self.current_balance


# ==============================================================================
# PURCHASE INVOICE & LINE ITEMS
# ==============================================================================

class PurchaseInvoice(models.Model):
    """
    Represents an inward procurement invoice from a supplier for jewellery, metals,
    diamonds, gemstones, or manufacturing materials.
    """
    PURCHASE_TYPE_CHOICES = (
        ('GOLD', 'Gold Purchase'),
        ('SILVER', 'Silver Purchase'),
        ('DIAMOND', 'Diamond Purchase'),
        ('GEMSTONE', 'Gemstone Purchase'),
        ('READY_MADE', 'Ready-made Jewellery Purchase'),
        ('BULLION', 'Bullion / Bar Purchase'),
        ('OTHER', 'Other Purchase'),
    )

    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('CONFIRMED', 'Confirmed'),
        ('PARTIALLY_PAID', 'Partially Paid'),
        ('PAID', 'Fully Paid'),
        ('CANCELLED', 'Cancelled'),
    )

    INVENTORY_STATUS_CHOICES = (
        ('PENDING', 'Pending Intake'),
        ('STOCKED', 'Stocked in Inventory'),
        ('PARTIALLY_RETURNED', 'Partially Returned'),
        ('RETURNED', 'Fully Returned'),
        ('NOT_APPLICABLE', 'Not Applicable'),
    )

    TAX_TYPE_CHOICES = (
        ('CGST_SGST', 'Intra-State (CGST + SGST)'),
        ('IGST', 'Inter-State (IGST)'),
        ('EXEMPT', 'Tax Exempted'),
    )

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='purchases'
    )
    branch = models.ForeignKey(
        'team.Branch',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='purchases'
    )
    purchase_number = models.CharField(max_length=50, db_index=True)
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name='purchases'
    )
    purchase_date = models.DateField(default=timezone.localdate)
    supplier_invoice_number = models.CharField(max_length=100, blank=True, help_text="Supplier's original bill/invoice number")
    supplier_invoice_date = models.DateField(null=True, blank=True)
    purchase_type = models.CharField(max_length=30, choices=PURCHASE_TYPE_CHOICES, default='READY_MADE')
    payment_terms_days = models.PositiveIntegerField(default=30)
    due_date = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', db_index=True)
    inventory_status = models.CharField(max_length=25, choices=INVENTORY_STATUS_CHOICES, default='PENDING')

    # Configurable Taxes
    tax_type = models.CharField(max_length=20, choices=TAX_TYPE_CHOICES, default='CGST_SGST')
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('3.00'), help_text="Total GST Rate % (Configurable)")
    cgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.50'))
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    sgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.50'))
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    igst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Quantity & Weights Totals
    total_quantity = models.PositiveIntegerField(default=0)
    total_gross_weight = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'))
    total_stone_weight = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'))
    total_net_weight = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'))
    total_fine_weight = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'))

    # Financial Totals
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_making_charges = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_stone_charges = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_other_charges = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    round_off = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    balance_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_purchases'
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='confirmed_purchases'
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Purchase Invoice'
        verbose_name_plural = 'Purchase Invoices'
        ordering = ['-purchase_date', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'purchase_number'],
                name='unique_tenant_purchase_number'
            ),
        ]

    def __str__(self):
        return f"{self.purchase_number} - {self.supplier.name} (₹{self.grand_total:,.2f})"

    def save(self, *args, **kwargs):
        if not self.purchase_number and self.tenant_id:
            settings_obj = PurchaseSetting.load(tenant=self.tenant)
            prefix = settings_obj.purchase_prefix or 'PUR'
            self.purchase_number = PurchaseSequence.get_next_number(self.tenant, 'purchase', prefix=prefix)
        if not self.due_date and self.purchase_date:
            self.due_date = self.purchase_date + timezone.timedelta(days=self.payment_terms_days or 30)
        super().save(*args, **kwargs)

    def recalculate_totals(self, save=True):
        """
        Accurately aggregates item quantities, weights, subtotal, charges, taxes, and grand total.
        Uses exact Decimal arithmetic.
        """
        items = self.items.all()
        qty = sum(item.quantity for item in items)
        gw = sum(item.gross_weight for item in items)
        sw = sum(item.stone_weight for item in items)
        nw = sum(item.net_weight for item in items)
        fw = sum(item.fine_weight for item in items)

        metal_val = sum(item.metal_value for item in items)
        making = sum(item.making_charge_total for item in items)
        stone = sum(item.stone_charges for item in items)
        other = sum(item.other_charges for item in items)

        raw_subtotal = metal_val + making + stone + other
        taxable = max(Decimal('0.00'), raw_subtotal - (self.discount_amount or Decimal('0.00')))

        # Tax calculations based on tax_type
        if self.tax_type == 'EXEMPT':
            tax_rate = Decimal('0.00')
            cgst_rate = Decimal('0.00')
            sgst_rate = Decimal('0.00')
            igst_rate = Decimal('0.00')
            cgst_amt = Decimal('0.00')
            sgst_amt = Decimal('0.00')
            igst_amt = Decimal('0.00')
            total_tax = Decimal('0.00')
        elif self.tax_type == 'IGST':
            tax_rate = self.tax_rate or Decimal('3.00')
            cgst_rate = Decimal('0.00')
            sgst_rate = Decimal('0.00')
            igst_rate = tax_rate
            cgst_amt = Decimal('0.00')
            sgst_amt = Decimal('0.00')
            igst_amt = (taxable * (igst_rate / Decimal('100.00'))).quantize(Decimal('0.01'))
            total_tax = igst_amt
        else: # CGST_SGST default
            tax_rate = self.tax_rate or Decimal('3.00')
            half_rate = (tax_rate / Decimal('2.00')).quantize(Decimal('0.01'))
            cgst_rate = half_rate
            sgst_rate = tax_rate - half_rate
            igst_rate = Decimal('0.00')
            cgst_amt = (taxable * (cgst_rate / Decimal('100.00'))).quantize(Decimal('0.01'))
            sgst_amt = (taxable * (sgst_rate / Decimal('100.00'))).quantize(Decimal('0.01'))
            igst_amt = Decimal('0.00')
            total_tax = cgst_amt + sgst_amt

        exact_grand_total = taxable + total_tax
        rounded_total = round(exact_grand_total)
        round_off = (Decimal(str(rounded_total)) - exact_grand_total).quantize(Decimal('0.01'))
        final_grand_total = Decimal(str(rounded_total)).quantize(Decimal('0.01'))

        self.total_quantity = qty
        self.total_gross_weight = gw.quantize(Decimal('0.001'))
        self.total_stone_weight = sw.quantize(Decimal('0.001'))
        self.total_net_weight = nw.quantize(Decimal('0.001'))
        self.total_fine_weight = fw.quantize(Decimal('0.001'))

        self.subtotal = raw_subtotal.quantize(Decimal('0.01'))
        self.total_making_charges = making.quantize(Decimal('0.01'))
        self.total_stone_charges = stone.quantize(Decimal('0.01'))
        self.total_other_charges = other.quantize(Decimal('0.01'))

        self.cgst_rate = cgst_rate
        self.cgst_amount = cgst_amt
        self.sgst_rate = sgst_rate
        self.sgst_amount = sgst_amt
        self.igst_rate = igst_rate
        self.igst_amount = igst_amt
        self.total_tax_amount = total_tax
        self.round_off = round_off
        self.grand_total = final_grand_total

        # Balance computation
        paid = self.amount_paid or Decimal('0.00')
        self.balance_amount = max(Decimal('0.00'), final_grand_total - paid)

        if save:
            self.save(update_fields=[
                'total_quantity', 'total_gross_weight', 'total_stone_weight',
                'total_net_weight', 'total_fine_weight', 'subtotal',
                'total_making_charges', 'total_stone_charges', 'total_other_charges',
                'cgst_rate', 'cgst_amount', 'sgst_rate', 'sgst_amount',
                'igst_rate', 'igst_amount', 'total_tax_amount', 'round_off',
                'grand_total', 'balance_amount'
            ])


class PurchaseItem(models.Model):
    """
    Individual jewellery or bullion item line within a Purchase Invoice.
    """
    RATE_TYPE_CHOICES = (
        ('PER_GRAM', 'Per Gram'),
        ('PER_PIECE', 'Per Piece'),
        ('FLAT', 'Flat Rate'),
    )

    MAKING_CHARGE_TYPE_CHOICES = (
        ('Per Gram', 'Per Gram (₹/g)'),
        ('Fixed', 'Fixed Amount (₹)'),
        ('Percentage', 'Percentage of Metal Value (%)'),
    )

    purchase = models.ForeignKey(
        PurchaseInvoice,
        on_delete=models.CASCADE,
        related_name='items'
    )
    item_name = models.CharField(max_length=200)
    category = models.ForeignKey(
        'inventory.Category',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='purchase_items'
    )
    metal_type = models.CharField(max_length=20, default='Gold')
    purity = models.CharField(max_length=50, default='22K')
    purity_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('91.60'))
    quantity = models.PositiveIntegerField(default=1)

    gross_weight = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('0.000'))
    stone_weight = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('0.000'))
    net_weight = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('0.000'))
    fine_weight = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('0.000'))

    purchase_rate = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    rate_type = models.CharField(max_length=20, choices=RATE_TYPE_CHOICES, default='PER_GRAM')
    metal_value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))

    making_charge_type = models.CharField(max_length=20, choices=MAKING_CHARGE_TYPE_CHOICES, default='Per Gram')
    making_charge_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    making_charge_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    stone_charges = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    other_charges = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('3.00'))
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))

    huid = models.CharField(max_length=20, blank=True, help_text="6-character alphanumeric BIS HUID")
    hallmark_details = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)

    # Link to inventory item created upon confirmation
    inventory_item = models.ForeignKey(
        'inventory.JewelleryItem',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='purchase_intakes'
    )
    returned_quantity = models.PositiveIntegerField(default=0)
    returned_weight = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('0.000'))

    class Meta:
        verbose_name = 'Purchase Item'
        verbose_name_plural = 'Purchase Items'

    def __str__(self):
        return f"{self.item_name} ({self.quantity} pcs, {self.net_weight}g) - ₹{self.line_total:,.2f}"

    def calculate_line_total(self):
        """
        Calculates net weight, fine weight, metal value, making charges, and line total.
        """
        # Net weight = Gross - Stone
        if self.gross_weight is not None:
            sw = self.stone_weight or Decimal('0.000')
            self.net_weight = max(Decimal('0.000'), self.gross_weight - sw)

        # Fine weight = Net Weight * (Purity / 100)
        purity_factor = (self.purity_percentage or Decimal('91.60')) / Decimal('100.00')
        self.fine_weight = (self.net_weight * purity_factor).quantize(Decimal('0.001'))

        # Metal Value
        if self.rate_type == 'PER_PIECE':
            self.metal_value = (Decimal(self.quantity or 1) * (self.purchase_rate or Decimal('0.00'))).quantize(Decimal('0.01'))
        elif self.rate_type == 'FLAT':
            self.metal_value = (self.purchase_rate or Decimal('0.00')).quantize(Decimal('0.01'))
        else: # PER_GRAM
            self.metal_value = ((self.net_weight or Decimal('0.000')) * (self.purchase_rate or Decimal('0.00'))).quantize(Decimal('0.01'))

        # Making Charges
        if self.making_charge_type == 'Fixed':
            self.making_charge_total = (self.making_charge_rate or Decimal('0.00')).quantize(Decimal('0.01'))
        elif self.making_charge_type == 'Percentage':
            self.making_charge_total = (self.metal_value * ((self.making_charge_rate or Decimal('0.00')) / Decimal('100.00'))).quantize(Decimal('0.01'))
        else: # Per Gram
            self.making_charge_total = ((self.net_weight or Decimal('0.000')) * (self.making_charge_rate or Decimal('0.00'))).quantize(Decimal('0.01'))

        subtotal = self.metal_value + self.making_charge_total + (self.stone_charges or Decimal('0.00')) + (self.other_charges or Decimal('0.00'))
        tax_pct = (self.tax_rate or Decimal('3.00')) / Decimal('100.00')
        self.tax_amount = (subtotal * tax_pct).quantize(Decimal('0.01'))
        self.line_total = (subtotal + self.tax_amount).quantize(Decimal('0.01'))

    def save(self, *args, **kwargs):
        self.calculate_line_total()
        super().save(*args, **kwargs)


# ==============================================================================
# SUPPLIER PAYMENT & LEDGER
# ==============================================================================

class SupplierPayment(models.Model):
    """
    Outward payment made to a supplier settling invoices or giving on-account advances.
    """
    PAYMENT_METHOD_CHOICES = (
        ('Cash', 'Cash'),
        ('UPI', 'UPI / QR'),
        ('Bank Transfer', 'Bank Transfer / NEFT / RTGS'),
        ('Cheque', 'Cheque'),
        ('Other', 'Other Settlement'),
    )

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='supplier_payments'
    )
    branch = models.ForeignKey(
        'team.Branch',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='supplier_payments'
    )
    payment_number = models.CharField(max_length=50, db_index=True)
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name='payments'
    )
    purchase_invoice = models.ForeignKey(
        PurchaseInvoice,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='payments'
    )
    payment_date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHOD_CHOICES, default='Bank Transfer')
    reference = models.CharField(max_length=100, blank=True, help_text="Cheque # / UTR / Reference ID")
    bank_name = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_supplier_payments'
    )
    is_cancelled = models.BooleanField(default=False)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='cancelled_supplier_payments'
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Supplier Payment'
        verbose_name_plural = 'Supplier Payments'
        ordering = ['-payment_date', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'payment_number'],
                name='unique_tenant_supplier_payment_number'
            ),
        ]

    def __str__(self):
        return f"{self.payment_number} - {self.supplier.name} (₹{self.amount:,.2f})"

    def save(self, *args, **kwargs):
        if not self.payment_number and self.tenant_id:
            settings_obj = PurchaseSetting.load(tenant=self.tenant)
            prefix = settings_obj.payment_prefix or 'PPAY'
            self.payment_number = PurchaseSequence.get_next_number(self.tenant, 'payment', prefix=prefix)
        super().save(*args, **kwargs)


class SupplierLedgerEntry(models.Model):
    """
    Immutable double-entry party ledger for accounts payable.
    Credit = Increases shop's liability to supplier (e.g. Inward Invoices)
    Debit  = Decreases shop's liability to supplier (e.g. Payments, Returns)
    """
    ENTRY_TYPE_CHOICES = (
        ('OPENING_BALANCE', 'Opening Balance'),
        ('PURCHASE_INVOICE', 'Purchase Invoice'),
        ('PAYMENT', 'Payment to Supplier'),
        ('PURCHASE_RETURN', 'Purchase Return / Debit Note'),
        ('ADJUSTMENT', 'Manual Adjustment'),
    )

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='supplier_ledger_entries'
    )
    branch = models.ForeignKey(
        'team.Branch',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='supplier_ledger_entries'
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name='ledger_entries'
    )
    entry_type = models.CharField(max_length=30, choices=ENTRY_TYPE_CHOICES)
    entry_date = models.DateField(default=timezone.localdate)
    reference_number = models.CharField(max_length=50)
    debit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    credit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    balance_after = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))

    purchase_invoice = models.ForeignKey(
        PurchaseInvoice,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ledger_entries'
    )
    payment = models.ForeignKey(
        SupplierPayment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ledger_entries'
    )
    purchase_return = models.ForeignKey(
        'PurchaseReturn',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='ledger_entries'
    )
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Supplier Ledger Entry'
        verbose_name_plural = 'Supplier Ledger Entries'
        ordering = ['entry_date', 'id']

    def __str__(self):
        return f"{self.supplier.name} - {self.entry_type} ({self.reference_number}): Cr:₹{self.credit_amount} Dr:₹{self.debit_amount} Bal:₹{self.balance_after}"


# ==============================================================================
# PURCHASE RETURNS & DEBIT NOTES
# ==============================================================================

class PurchaseReturn(models.Model):
    """
    Voucher recording items returned to a supplier, reducing stock and issuing a debit note.
    """
    ADJUSTMENT_MODE_CHOICES = (
        ('REDUCE_INVOICE_BALANCE', 'Reduce Invoice Balance'),
        ('SUPPLIER_CREDIT_NOTE', 'Credit to Supplier Ledger (Debit Note)'),
        ('CASH_BANK_REFUND', 'Immediate Cash / Bank Refund'),
    )

    STATUS_CHOICES = (
        ('CONFIRMED', 'Confirmed'),
        ('CANCELLED', 'Cancelled'),
    )

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='purchase_returns'
    )
    branch = models.ForeignKey(
        'team.Branch',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='purchase_returns'
    )
    return_number = models.CharField(max_length=50, db_index=True)
    original_invoice = models.ForeignKey(
        PurchaseInvoice,
        on_delete=models.PROTECT,
        related_name='returns'
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name='returns'
    )
    return_date = models.DateField(default=timezone.localdate)
    total_return_quantity = models.PositiveIntegerField(default=0)
    total_return_weight = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'))
    total_return_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    adjustment_mode = models.CharField(max_length=30, choices=ADJUSTMENT_MODE_CHOICES, default='REDUCE_INVOICE_BALANCE')
    reason = models.CharField(max_length=200, default='Defective / Purity Issue')
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CONFIRMED')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_purchase_returns'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Purchase Return'
        verbose_name_plural = 'Purchase Returns'
        ordering = ['-return_date', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'return_number'],
                name='unique_tenant_purchase_return_number'
            ),
        ]

    def __str__(self):
        return f"{self.return_number} - {self.supplier.name} (₹{self.total_return_amount:,.2f})"

    def save(self, *args, **kwargs):
        if not self.return_number and self.tenant_id:
            settings_obj = PurchaseSetting.load(tenant=self.tenant)
            prefix = settings_obj.return_prefix or 'PRET'
            self.return_number = PurchaseSequence.get_next_number(self.tenant, 'return', prefix=prefix)
        super().save(*args, **kwargs)


class PurchaseReturnItem(models.Model):
    """
    Line item for individual pieces or weights being returned in a Purchase Return voucher.
    """
    purchase_return = models.ForeignKey(
        PurchaseReturn,
        on_delete=models.CASCADE,
        related_name='return_items'
    )
    purchase_item = models.ForeignKey(
        PurchaseItem,
        on_delete=models.PROTECT,
        related_name='returned_lines'
    )
    returned_quantity = models.PositiveIntegerField(default=1)
    returned_weight = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('0.000'))
    return_rate = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    return_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = 'Purchase Return Item'
        verbose_name_plural = 'Purchase Return Items'

    def __str__(self):
        return f"Return {self.purchase_item.item_name} ({self.returned_quantity} pcs, {self.returned_weight}g) - ₹{self.return_amount:,.2f}"
