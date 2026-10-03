from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from customers.models import Customer
from inventory.models import JewelleryItem, Category
from inventory import pricing


class Sale(models.Model):
    PAYMENT_METHODS = [
        ('Cash', 'Cash'),
        ('UPI', 'UPI'),
        ('Card', 'Card'),
        ('Bank Transfer', 'Bank Transfer'),
        ('Exchange', 'Exchange / Old Gold'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='sales')
    jewellery_item = models.ForeignKey(JewelleryItem, on_delete=models.PROTECT, related_name='sales')
    sale_price = models.DecimalField(max_digits=12, decimal_places=2)
    sale_date = models.DateTimeField(default=timezone.now)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='Cash')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-sale_date']

    def __str__(self):
        return f"Sale #{self.id} - {self.jewellery_item.name} to {self.customer.name}"

    # ---- Payment summary (always calculated from Payment rows) ------
    @property
    def paid_amount(self):
        """Total received against this sale (never stored)."""
        from django.db.models import Sum
        total = Payment.objects.filter(sale=self).aggregate(total=Sum('amount'))['total']
        return total or Decimal('0')

    @property
    def due_amount(self):
        """Remaining due, floored at zero."""
        due = self.sale_price - self.paid_amount
        return due if due > 0 else Decimal('0')

    @property
    def payment_status(self):
        """Unpaid / Partially Paid / Paid based on actual payments."""
        paid = self.paid_amount
        if paid <= 0:
            return 'Unpaid'
        if paid >= self.sale_price:
            return 'Paid'
        return 'Partially Paid'


class Payment(models.Model):
    """A single money received against a Sale (installment / full / partial)."""

    PAYMENT_METHODS = [
        ('Cash', 'Cash'),
        ('UPI', 'UPI'),
        ('Card', 'Card'),
        ('Bank Transfer', 'Bank Transfer'),
        ('Cheque', 'Cheque'),
        ('Exchange', 'Exchange / Old Gold'),
    ]

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='Cash')
    payment_date = models.DateTimeField(default=timezone.now)
    reference = models.CharField(
        max_length=100, blank=True,
        help_text='UPI ref / cheque no. / transaction id')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payment_date', '-id']

    def __str__(self):
        return f"Payment of Rs. {self.amount} on Sale #{self.sale_id}"

    def clean(self):
        """Reject non-positive amounts and payments above remaining due."""
        from django.db.models import Sum
        super().clean()
        errors = {}
        if self.amount is not None:
            if self.amount <= 0:
                errors['amount'] = 'Payment amount must be greater than zero.'
            elif self.sale_id:
                paid = (Payment.objects.filter(sale_id=self.sale_id)
                        .exclude(pk=self.pk)
                        .aggregate(total=Sum('amount'))['total'] or Decimal('0'))
                remaining = self.sale.sale_price - paid
                if self.amount > remaining:
                    errors['amount'] = (
                        'Payment exceeds the remaining due amount of '
                        f'Rs. {remaining:,.2f}.')
        if errors:
            raise ValidationError(errors)


class Enquiry(models.Model):
    STATUS_CHOICES = [
        ('New', 'New'),
        ('Contacted', 'Contacted'),
        ('Interested', 'Interested'),
        ('Purchased', 'Purchased'),
        ('Closed', 'Closed'),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='enquiries')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='enquiries')
    interested_item = models.CharField(
        max_length=200,
        help_text="e.g. Gold Necklace 22K, Solitaire Ring, etc."
    )
    budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='New')
    next_followup_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Enquiries'
        ordering = ['-created_at']

    def __str__(self):
        return f"Enquiry #{self.id} - {self.customer.name} ({self.interested_item})"


def generate_old_gold_number(transaction_type='Exchange'):
    """
    Generate unique sequential reference for old gold transactions:
    OGX-00001 for Exchange, OGB-00001 for Buyback.
    """
    prefix = 'OGX' if transaction_type == 'Exchange' else 'OGB' if transaction_type == 'Buyback' else 'OG'
    latest = OldGoldTransaction.objects.filter(transaction_number__startswith=prefix).order_by('-id').first()
    next_num = 1
    if latest and latest.transaction_number:
        try:
            num = int(latest.transaction_number.split('-')[-1])
            next_num = num + 1
        except (ValueError, IndexError):
            next_num = OldGoldTransaction.objects.count() + 1
    return f"{prefix}-{next_num:05d}"


class OldGoldTransaction(models.Model):
    """
    Old Gold Exchange & Outright Buyback Transaction Record.

    Supports:
      1. Exchange with new jewellery: Old gold valuation credited towards a new Sale.
      2. Outright buyback: Cash/bank payout for customer's old gold without a purchase.
      3. Scrap inventory tracking in the vault without polluting sellable showroom stock.
      4. Complete immutability and cancellation audit trail.
    """

    TYPE_EXCHANGE = 'Exchange'
    TYPE_BUYBACK = 'Buyback'
    TYPE_CHOICES = [
        (TYPE_EXCHANGE, 'Exchange with New Jewellery'),
        (TYPE_BUYBACK, 'Outright Buyback (Cash Payout)'),
    ]

    STATUS_COMPLETED = 'Completed'
    STATUS_CANCELLED = 'Cancelled'
    STATUS_CHOICES = [
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    PURITY_CHOICES = [
        ('24K', '24K (99.9% Pure)'),
        ('22K', '22K / 916 (91.6%)'),
        ('20K', '20K (83.3%)'),
        ('18K', '18K / 750 (75.0%)'),
        ('14K', '14K / 585 (58.5%)'),
        ('10K', '10K (41.7%)'),
        ('925', '925 Sterling Silver'),
        ('Other', 'Other / Custom Purity'),
    ]

    OLD_GOLD_TYPES = [
        ('Old Jewellery', 'Old Jewellery / Ornaments'),
        ('Broken Jewellery', 'Broken Jewellery Pieces'),
        ('Scrap Gold', 'Scrap Gold'),
        ('Coins / Bullion', 'Gold Coins / Bullion Bar'),
        ('Silver Scrap', 'Silver Scrap / Utensils'),
        ('Other', 'Other Scrap Metal'),
    ]

    INVENTORY_STATUS_CHOICES = [
        ('Vault Stock', 'Scrap in Vault (Not for sale)'),
        ('Sent for Refining', 'Sent to Refinery / Melter'),
        ('Melted', 'Melted into Bullion'),
        ('Refined Bar', 'Refined Bullion Bar Received'),
    ]

    transaction_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique voucher reference (e.g. OGX-00001, OGB-00001)"
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_EXCHANGE
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='old_gold_transactions'
    )
    created_at = models.DateTimeField(default=timezone.now)

    # Physical / Metal specifications
    metal_type = models.CharField(
        max_length=20,
        choices=JewelleryItem.METAL_CHOICES,
        default='Gold'
    )
    old_gold_type = models.CharField(
        max_length=50,
        choices=OLD_GOLD_TYPES,
        default='Old Jewellery'
    )
    item_description = models.CharField(
        max_length=255,
        help_text="e.g. Broken 22K Bangle, Mangalsutra chain pieces"
    )
    gross_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        help_text="Total physical weight in grams"
    )
    stone_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Stone, enamel, wax or non-metal weight in grams"
    )
    net_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        help_text="Net precious metal weight in grams (gross - stone)"
    )

    # Purity and Rates
    purity = models.CharField(
        max_length=50,
        choices=PURITY_CHOICES,
        default='22K'
    )
    custom_purity_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Custom purity % if 'Other' selected"
    )
    purity_factor = models.DecimalField(
        max_digits=8,
        decimal_places=6,
        default=Decimal('0.916667'),
        help_text="Purity multiplier (e.g. 0.916667 for 22K)"
    )
    pure_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        help_text="Equivalent 24K pure metal weight in grams"
    )
    applicable_rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Standard 24K rate per gram in INR at time of intake"
    )
    effective_rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Rate per gram for this purity in INR (applicable_rate * purity_factor)"
    )

    # Valuation Breakdown
    gross_valuation = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Gross gold value before deductions (net_weight * effective_rate)"
    )
    deduction_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Melting/testing wastage deduction percentage"
    )
    deduction_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Deduction in INR"
    )
    final_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Final old gold valuation credited or paid (Gross - Deductions)"
    )

    # Stock isolation (Scrap inventory)
    inventory_status = models.CharField(
        max_length=30,
        choices=INVENTORY_STATUS_CHOICES,
        default='Vault Stock',
        help_text="Kept separate from normal showroom stock"
    )

    # Exchange with New Jewellery
    new_sale = models.OneToOneField(
        Sale,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='old_gold_exchange',
        help_text="Linked sale when old gold is used towards new jewellery purchase"
    )
    new_item_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Sale price of the new jewellery piece"
    )
    difference_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="New Item Price - Old Gold Final Value (+ve = Customer owes, -ve = Refund due)"
    )

    # Buyback / Payout details
    payment_method = models.CharField(
        max_length=30,
        blank=True,
        choices=[
            ('Cash', 'Cash'),
            ('UPI', 'UPI'),
            ('Bank Transfer', 'Bank Transfer'),
            ('Cheque', 'Cheque'),
            ('Adjusted in Sale', 'Adjusted in Sale (Exchange)'),
        ],
        default='Cash'
    )
    payment_status = models.CharField(
        max_length=20,
        default='Paid',
        choices=[
            ('Paid', 'Paid'),
            ('Pending', 'Pending'),
            ('N/A', 'N/A'),
        ]
    )
    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Bank / UPI reference or cheque number"
    )

    # Status and Audit
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_COMPLETED
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_old_golds'
    )
    notes = models.TextField(blank=True)

    # Cancellation Audit
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cancelled_old_golds'
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'Old Gold Transaction'
        verbose_name_plural = 'Old Gold Transactions'

    def __str__(self):
        return f"{self.transaction_number} - {self.customer.name} ({self.get_transaction_type_display()} - Rs. {self.final_value:,.2f})"

    @property
    def is_exchange(self):
        return self.transaction_type == self.TYPE_EXCHANGE

    @property
    def is_buyback(self):
        return self.transaction_type == self.TYPE_BUYBACK

    @property
    def customer_payable(self):
        """Amount payable by customer when new item is more expensive than old gold."""
        if self.is_exchange and self.difference_amount > 0:
            return self.difference_amount
        return Decimal('0.00')

    @property
    def customer_refund(self):
        """Refund / credit amount due to customer when old gold exceeds new item price."""
        if self.is_exchange and self.difference_amount < 0:
            return abs(self.difference_amount)
        return Decimal('0.00')

    @classmethod
    def compute_valuation(
        cls,
        gross_weight,
        stone_weight=Decimal('0.000'),
        metal_type='Gold',
        purity='22K',
        custom_purity_percent=None,
        applicable_rate=None,
        deduction_percent=Decimal('0.00'),
    ):
        """
        Pure valuation calculator reusing inventory.pricing logic.
        """
        g_wt = pricing.round_wt(pricing.to_decimal(gross_weight, '0.000'))
        s_wt = pricing.round_wt(pricing.to_decimal(stone_weight, '0.000'))
        n_wt = max(Decimal('0.000'), g_wt - s_wt)

        m_type = (metal_type or 'Gold').strip().title()

        # Parse purity factor
        if purity == 'Other' and custom_purity_percent:
            p_factor = pricing.to_decimal(custom_purity_percent) / Decimal('100.00')
        else:
            p_factor = pricing.parse_purity_factor(m_type, str(purity or ''))

        # Fetch rate
        if applicable_rate is not None and pricing.to_decimal(applicable_rate) > 0:
            base_rate = pricing.to_decimal(applicable_rate)
        else:
            base_rate = pricing.get_current_metal_rate(m_type)

        eff_rate = pricing.round_curr(base_rate * p_factor)
        gross_val = pricing.round_curr(n_wt * eff_rate)

        d_pct = max(Decimal('0.00'), pricing.to_decimal(deduction_percent, '0.00'))
        d_amt = pricing.round_curr(gross_val * (d_pct / Decimal('100.00')))
        final_val = pricing.round_curr(gross_val - d_amt)

        pure_wt = pricing.round_wt(n_wt * p_factor)

        return {
            'gross_weight': g_wt,
            'stone_weight': s_wt,
            'net_weight': n_wt,
            'purity_factor': p_factor,
            'pure_weight': pure_wt,
            'applicable_rate': base_rate,
            'effective_rate': eff_rate,
            'gross_valuation': gross_val,
            'deduction_percent': d_pct,
            'deduction_amount': d_amt,
            'final_value': final_val,
        }

    def clean(self):
        super().clean()
        errors = {}

        if self.gross_weight is None or self.gross_weight <= 0:
            errors['gross_weight'] = 'Gross weight must be greater than zero.'

        if self.stone_weight is not None and self.stone_weight < 0:
            errors['stone_weight'] = 'Stone weight cannot be negative.'

        if self.gross_weight and self.stone_weight is not None:
            if self.stone_weight >= self.gross_weight:
                errors['stone_weight'] = 'Stone weight cannot be equal to or greater than gross weight.'

        if self.applicable_rate is None or self.applicable_rate <= 0:
            errors['applicable_rate'] = 'Applicable rate must be greater than zero.'

        if self.deduction_percent is not None and (self.deduction_percent < 0 or self.deduction_percent > 100):
            errors['deduction_percent'] = 'Deduction percent must be between 0% and 100%.'

        if errors:
            raise ValidationError(errors)

    def cancel(self, user, reason):
        """Safely cancel an old gold transaction with an audit log."""
        if self.status == self.STATUS_CANCELLED:
            raise ValidationError('Transaction is already cancelled.')
        self.status = self.STATUS_CANCELLED
        self.cancelled_by = user
        self.cancelled_at = timezone.now()
        self.cancellation_reason = reason or 'No reason provided.'
        self.save(update_fields=['status', 'cancelled_by', 'cancelled_at', 'cancellation_reason'])


