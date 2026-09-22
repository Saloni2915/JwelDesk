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

