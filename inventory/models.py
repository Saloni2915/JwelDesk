from decimal import Decimal

from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class ItemSequence(models.Model):
    """
    Atomic monotonic sequence tracker for jewellery tag numbers (e.g. JWL-000001).
    Used to prevent duplicates under concurrent item creation without gaps or collisions.
    """
    name = models.CharField(max_length=50, unique=True, default='jewellery_tag')
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Item Sequence'
        verbose_name_plural = 'Item Sequences'

    def __str__(self):
        return f"{self.name}: {self.last_number}"



class JewelleryItem(models.Model):
    METAL_CHOICES = [
        ('Gold', 'Gold'),
        ('Silver', 'Silver'),
        ('Diamond', 'Diamond'),
        ('Platinum', 'Platinum'),
        ('Other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('Available', 'Available'),
        ('Sold', 'Sold'),
        ('Reserved', 'Reserved'),
    ]

    HUID_STATUS_CHOICES = [
        ('Not Applicable', 'Not Applicable'),
        ('Pending', 'Pending'),
        ('Verified', 'Verified'),
    ]

    HALLMARK_STATUS_CHOICES = [
        ('Not Applicable', 'Not Applicable'),
        ('Pending', 'Pending'),
        ('Hallmarked', 'Hallmarked'),
    ]

    # Physical piece identity
    tag_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        db_index=True,
        help_text="Unique physical jewellery piece tag number (e.g. JWL-000001)"
    )
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

    # Authentication / Hallmark
    huid = models.CharField(
        max_length=6,
        blank=True,
        db_index=True,
        help_text="6-character alphanumeric BIS Hallmarking Unique ID (Indian jewellery inventory)"
    )
    huid_status = models.CharField(
        max_length=20,
        choices=HUID_STATUS_CHOICES,
        default='Not Applicable',
        help_text="HUID authentication status"
    )
    hallmark_status = models.CharField(
        max_length=20,
        choices=HALLMARK_STATUS_CHOICES,
        default='Not Applicable',
        help_text="Hallmark status"
    )
    hallmark_details = models.CharField(
        max_length=150,
        blank=True,
        help_text="Hallmark center / assaying notes or certification details"
    )

    # Weights
    gross_weight = models.DecimalField(max_digits=10, decimal_places=3, help_text="Gross weight in grams")
    stone_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=Decimal('0.000'),
        blank=True,
        help_text="Stone / bead / wax weight in grams"
    )
    net_weight = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        blank=True,
        null=True,
        help_text="Net precious metal weight in grams (gross weight minus stone weight; auto = gross - stone)"
    )
    MAKING_CHARGE_TYPE_CHOICES = [
        ('Fixed Amount', 'Fixed Amount (₹)'),
        ('Per Gram', 'Per Gram (₹/g)'),
        ('Percentage', 'Percentage (%)'),
    ]

    making_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    making_charge_type = models.CharField(
        max_length=20,
        choices=MAKING_CHARGE_TYPE_CHOICES,
        default='Fixed Amount',
        help_text="How making charges are calculated (Fixed ₹, Per gram, or %)"
    )
    wastage_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        blank=True,
        help_text="Manufacturing wastage percentage (e.g. 3.00%)"
    )
    stone_charges = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        blank=True,
        help_text="Stone / diamond / bead charges in ₹"
    )
    other_charges = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        blank=True,
        help_text="Hallmarking, certification or other charges in ₹"
    )
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(
        default=1,
        help_text="Pieces of this item currently held in stock."
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # HUID must be unique when provided; blank ('') values are allowed
            # to repeat so non-hallmarked pieces stay importable/searchable.
            models.UniqueConstraint(
                fields=['huid'],
                condition=~models.Q(huid=''),
                name='unique_nonblank_huid',
            ),
        ]

    def clean(self):
        super().clean()
        if self.tag_number:
            self.tag_number = self.tag_number.strip()

        # Normalise HUID to uppercase if present
        if self.huid:
            self.huid = self.huid.strip().upper()
            if len(self.huid) != 6 or not self.huid.isalnum():
                raise ValidationError({'huid': 'HUID must be a 6-character alphanumeric code.'})
            # Prevent duplicate HUID values (blank/empty values are always allowed)
            huid_qs = type(self).objects.filter(huid=self.huid)
            if self.pk:
                huid_qs = huid_qs.exclude(pk=self.pk)
            if huid_qs.exists():
                raise ValidationError({'huid': 'This HUID is already assigned to another item.'})

        # Normalise HUID whitespace when blank so all empty values stay ''
        # (and share the DB partial-index exemption cleanly).
        if not self.huid:
            self.huid = ''

        if self.gross_weight is not None and self.gross_weight < 0:
            raise ValidationError({'gross_weight': 'Gross weight cannot be negative.'})

        if self.stone_weight is not None and self.stone_weight < 0:
            raise ValidationError({'stone_weight': 'Stone weight cannot be negative.'})

        if self.net_weight is not None and self.net_weight < 0:
            raise ValidationError({'net_weight': 'Net weight cannot be negative.'})

        # Calculate or validate net weight
        if self.gross_weight is not None:
            stone = self.stone_weight or Decimal('0.000')
            if self.net_weight is None:
                calc_net = self.gross_weight - stone
                if calc_net < 0:
                    raise ValidationError({'stone_weight': 'Stone weight cannot exceed gross weight.'})
                self.net_weight = calc_net
            else:
                if self.net_weight > self.gross_weight:
                    raise ValidationError({'net_weight': 'Net weight cannot be greater than gross weight.'})
                if (self.net_weight + stone) > self.gross_weight:
                    raise ValidationError({'stone_weight': 'Combined net and stone weight exceeds gross weight.'})

        if self.quantity is not None and self.quantity < 0:
            raise ValidationError({'quantity': 'Stock quantity cannot be negative.'})

    @classmethod
    def generate_next_tag_number(cls):
        """
        Thread-safe tag number generator producing unique tags formatted as JWL-000001.
        Uses database row-locking on ItemSequence to ensure safe concurrent allocations.
        """
        from django.db import transaction
        with transaction.atomic():
            seq, _ = ItemSequence.objects.select_for_update().get_or_create(
                name='jewellery_tag',
                defaults={'last_number': 0}
            )
            # Ensure the sequence counter is at least the highest existing tag number
            if seq.last_number == 0:
                highest = 0
                for tag in cls.objects.filter(tag_number__startswith='JWL-').values_list('tag_number', flat=True):
                    try:
                        num = int(tag.split('-')[-1])
                        if num > highest:
                            highest = num
                    except (ValueError, IndexError):
                        pass
                if highest > seq.last_number:
                    seq.last_number = highest

            seq.last_number += 1
            seq.save(update_fields=['last_number'])
            tag_candidate = f"JWL-{seq.last_number:06d}"

            # Safety check against existing record collision
            while cls.objects.filter(tag_number=tag_candidate).exists():
                seq.last_number += 1
                seq.save(update_fields=['last_number'])
                tag_candidate = f"JWL-{seq.last_number:06d}"

            return tag_candidate

    def save(self, *args, **kwargs):
        if self.tag_number:
            self.tag_number = self.tag_number.strip()
        if not self.tag_number:
            self.tag_number = self.generate_next_tag_number()
        if not self.design_code:
            self.design_code = self.item_code
        if self.huid:
            self.huid = self.huid.strip().upper()
        else:
            self.huid = ''
        self.full_clean()
        super().save(*args, **kwargs)

    # ---- Stock helpers -------------------------------------------------
    @property
    def in_stock_quantity(self):
        """Pieces that can actually be sold right now (never negative)."""
        if self.status != 'Available' or self.quantity is None:
            return 0
        return self.quantity

    @property
    def estimated_value(self):
        """Stock value = selling price of the pieces currently available."""
        price = self.selling_price or Decimal('0.00')
        return price * self.in_stock_quantity

    @property
    def stock_status(self):
        """Threshold-independent stock status used by listing templates."""
        if self.status == 'Sold' or not self.quantity:
            return 'Out of Stock'
        if self.status == 'Reserved':
            return 'Reserved'
        return 'In Stock'

    @property
    def is_out_of_stock(self):
        return self.stock_status == 'Out of Stock'

    # ---- Live Pricing Helpers ------------------------------------------
    def calculate_live_price(self, base_rate=None, tax_percent=None):
        """Calculate the live market price breakdown using active metal rates."""
        from . import pricing
        kwargs = {}
        if base_rate is not None:
            kwargs['base_rate'] = base_rate
        if tax_percent is not None:
            kwargs['tax_percent'] = tax_percent
        return pricing.calculate_item_price(self, **kwargs)

    @property
    def current_market_price(self):
        """Current calculated retail price based on today's active metal rates."""
        try:
            return self.calculate_live_price().final_price
        except Exception:
            return self.selling_price

    @property
    def live_price_breakdown(self):
        """Full PriceBreakdown object for template rendering."""
        try:
            return self.calculate_live_price()
        except Exception:
            return None

    def __str__(self):
        display_tag = self.tag_number or self.item_code
        if self.design_code and self.design_code != self.item_code:
            return f"[{display_tag}] {self.name} ({self.metal_type}) - Design: {self.design_code}"
        return f"[{display_tag}] {self.name} ({self.metal_type})"


class StockMovement(models.Model):
    """
    Immutable audit trail of every stock change for a `JewelleryItem`.

    A movement stores the signed piece change together with the stock level
    before and after it, so the history can always be replayed/verified.
    Movements are only created through `inventory.stock.apply_stock_change`
    (or the sales flow that reuses it) - never edited or deleted.
    """

    ADDITION = 'Addition'
    REDUCTION = 'Reduction'
    ADJUSTMENT = 'Adjustment'
    SALE = 'Sale'

    MOVEMENT_TYPES = [
        (ADDITION, 'Stock Addition'),
        (REDUCTION, 'Stock Reduction'),
        (ADJUSTMENT, 'Stock Adjustment'),
        (SALE, 'Sale'),
    ]

    REASON_CHOICES = [
        ('New Stock Received', 'New Stock Received'),
        ('Returned by Customer', 'Returned by Customer'),
        ('Damaged Item', 'Damaged Item'),
        ('Lost Item', 'Lost Item'),
        ('Stock Correction', 'Stock Correction'),
        ('Manual Adjustment', 'Manual Adjustment'),
        ('Sale', 'Sale'),
    ]

    item = models.ForeignKey(
        JewelleryItem, on_delete=models.CASCADE, related_name='stock_movements')
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity_change = models.IntegerField(
        help_text="Signed piece change: positive adds stock, negative removes it.")
    stock_before = models.PositiveIntegerField()
    stock_after = models.PositiveIntegerField()
    reason = models.CharField(max_length=50, choices=REASON_CHOICES, blank=True)
    notes = models.TextField(blank=True)
    sale = models.ForeignKey(
        'sales.Sale', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_movements')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_movements')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(quantity_change=0),
                name='stock_movement_change_not_zero'),
            models.CheckConstraint(
                condition=models.Q(stock_after__gte=0),
                name='stock_movement_after_not_negative'),
        ]

    def __str__(self):
        return (f"{self.get_movement_type_display()} "
                f"{self.quantity_change:+d} x {self.item.item_code}")

    # ---- Display helpers ------------------------------------------------
    @property
    def quantity(self):
        """Magnitude of the change (always positive, for display)."""
        return abs(self.quantity_change)

    @property
    def is_stock_out(self):
        return self.quantity_change < 0

    def clean(self):
        """Reject movements that do not describe a consistent stock change."""
        super().clean()
        errors = {}

        if not self.quantity_change:
            errors['quantity_change'] = 'Quantity change cannot be zero.'

        if self.quantity_change and self.stock_before is not None and \
                self.stock_after is not None:
            if self.stock_after != self.stock_before + self.quantity_change:
                errors['stock_after'] = (
                    'New stock must equal the previous stock plus the quantity change.')

        if self.stock_after is not None and self.stock_after < 0:
            errors['stock_after'] = 'Stock cannot be negative.'

        if self.movement_type == self.ADDITION and self.quantity_change and \
                self.quantity_change <= 0:
            errors['quantity_change'] = 'A stock addition must increase the stock.'

        if self.movement_type in (self.REDUCTION, self.SALE) and \
                self.quantity_change and self.quantity_change >= 0:
            errors['quantity_change'] = 'A stock reduction must decrease the stock.'

        if errors:
            raise ValidationError(errors)


class MetalRate(models.Model):
    """
    Shop daily board rates for precious metals in INR per gram.
    Used by the Jewellery Pricing Engine to calculate live prices.
    Can be updated manually by authorized staff or synced from the external metal price API.
    """
    METAL_GOLD = 'Gold'
    METAL_SILVER = 'Silver'
    METAL_PLATINUM = 'Platinum'
    METAL_CHOICES = [
        (METAL_GOLD, 'Gold'),
        (METAL_SILVER, 'Silver'),
        (METAL_PLATINUM, 'Platinum'),
    ]

    metal_type = models.CharField(max_length=20, choices=METAL_CHOICES, unique=True)
    rate_per_gram = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Standard rate per gram in INR (24K for Gold, 999 for Silver, 950 for Platinum)"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_metal_rates'
    )
    source = models.CharField(
        max_length=50,
        default='Manual',
        help_text="Rate source (e.g. Manual, Live API, IBJA)"
    )

    class Meta:
        ordering = ['metal_type']
        verbose_name = 'Metal Rate'
        verbose_name_plural = 'Metal Rates'

    def __str__(self):
        return f"{self.metal_type}: ₹{self.rate_per_gram}/g"

    @classmethod
    def get_rate(cls, metal_type):
        rate_obj = cls.objects.filter(metal_type=metal_type).first()
        return rate_obj.rate_per_gram if rate_obj else None


