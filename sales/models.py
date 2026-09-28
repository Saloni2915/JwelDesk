from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from customers.models import Customer
from inventory.models import JewelleryItem, Category


class Sale(models.Model):
    PAYMENT_METHODS = [
        ('Cash', 'Cash'),
        ('UPI', 'UPI'),
        ('Card', 'Card'),
        ('Bank Transfer', 'Bank Transfer'),
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

