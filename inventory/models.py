from django.db import models
from django.core.exceptions import ValidationError


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class JewelleryItem(models.Model):
    METAL_CHOICES = [
        ('Gold', 'Gold'),
        ('Silver', 'Silver'),
        ('Diamond', 'Diamond'),
        ('Platinum', 'Platinum'),
    ]

    STATUS_CHOICES = [
        ('Available', 'Available'),
        ('Sold', 'Sold'),
        ('Reserved', 'Reserved'),
    ]

    item_code = models.CharField(max_length=50, unique=True, help_text="Unique piece ID / Tag / Barcode")
    design_code = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        help_text="Design / Model Code (e.g. DSN-GLD-001). Multiple physical pieces can share the same design code."
    )
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='items')
    metal_type = models.CharField(max_length=20, choices=METAL_CHOICES)
    purity = models.CharField(max_length=50, help_text="e.g. 22K, 18K, 925 Silver, VVS-1")
    gross_weight = models.DecimalField(max_digits=10, decimal_places=3, help_text="Weight in grams")
    net_weight = models.DecimalField(max_digits=10, decimal_places=3, help_text="Weight in grams (excluding stones/wax)")
    making_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        super().clean()
        if self.gross_weight is not None and self.net_weight is not None:
            if self.net_weight > self.gross_weight:
                raise ValidationError({'net_weight': 'Net weight cannot be greater than gross weight.'})

    def save(self, *args, **kwargs):
        if not self.design_code:
            self.design_code = self.item_code
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.design_code and self.design_code != self.item_code:
            return f"{self.item_code} (Design: {self.design_code}) - {self.name} ({self.metal_type})"
        return f"{self.item_code} - {self.name} ({self.metal_type})"

