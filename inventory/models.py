import logging
import os
import re
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, OperationalError, ProgrammingError, models, transaction
from django.utils import timezone

logger = logging.getLogger('inventory.models')


class Category(models.Model):
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='categories',
        null=True,
        blank=True,
        help_text="Tenant shop owning this category"
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'name'],
                name='unique_tenant_category_name',
            ),
        ]

    def __str__(self):
        return self.name


class ItemSequence(models.Model):
    """
    Atomic monotonic sequence tracker for jewellery tag numbers (e.g. JWL-000001).
    Used to prevent duplicates under concurrent item creation without gaps or collisions.
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='item_sequences',
        null=True,
        blank=True,
        help_text="Tenant shop owning this sequence"
    )
    name = models.CharField(max_length=50, default='jewellery_tag')
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Item Sequence'
        verbose_name_plural = 'Item Sequences'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'name'],
                name='unique_tenant_sequence_name',
            ),
        ]

    def __str__(self):
        return f"{self.name}: {self.last_number}"


class StockImportBatch(models.Model):
    STATUS_CHOICES = [
        ('Success', 'Success'),
        ('Partial', 'Partial'),
        ('Failed', 'Failed'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='stock_import_batches',
        null=True,
        blank=True,
        help_text="Tenant showroom owning this import batch"
    )
    file_name = models.CharField(max_length=255, help_text="Original uploaded spreadsheet file name")
    file_size = models.PositiveIntegerField(default=0, help_text="File size in bytes")
    total_rows = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Success')
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_import_batches',
        help_text="User who initiated and confirmed the bulk import"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    items_summary = models.JSONField(
        default=list,
        blank=True,
        help_text="Snapshot of imported items metadata"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Stock Import Batch'
        verbose_name_plural = 'Stock Import Batches'

    def __str__(self):
        return f"Import '{self.file_name}' ({self.imported_count} items) on {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    @property
    def file_size_display(self):
        if not self.file_size:
            return "0 B"
        bytes_val = float(self.file_size)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f} {unit}" if unit != 'B' else f"{int(bytes_val)} B"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f} TB"

    @property
    def total_gross_weight(self):
        total = Decimal('0.000')
        for it in (self.items_summary or []):
            try:
                total += Decimal(str(it.get('gross_weight', 0)))
            except Exception:
                pass
        return total

    @property
    def total_value(self):
        total = Decimal('0.00')
        for it in (self.items_summary or []):
            try:
                total += Decimal(str(it.get('selling_price', 0)))
            except Exception:
                pass
        return total


class JewelleryItem(models.Model):
    METAL_CHOICES = [
        ('Gold', 'Gold'),
        ('Silver', 'Silver'),
        ('Diamond', 'Diamond'),
        ('Platinum', 'Platinum'),
        ('Other', 'Other'),
    ]

    PURITY_CHOICES = [
        ('24K', '24K (99.9% Pure Gold)'),
        ('22K', '22K / 916 (91.6% Hallmark Gold)'),
        ('20K', '20K (83.3% Gold)'),
        ('18K', '18K / 750 (75.0% Gold)'),
        ('14K', '14K / 585 (58.5% Gold)'),
        ('10K', '10K (41.7% Gold)'),
        ('9K', '9K (37.5% Gold)'),
        ('999', '999 Fine Silver'),
        ('925', '925 Sterling Silver'),
        ('800', '800 Silver'),
        ('Pt 950', 'Pt 950 Platinum'),
        ('Pt 900', 'Pt 900 Platinum'),
        ('Other', 'Other / Custom Purity'),
        # Backwards-compatible legacy values
        ('24K (999)', '24K (999)'),
        ('22K (916)', '22K (916)'),
        ('18K (750)', '18K (750)'),
        ('14K (585)', '14K (585)'),
        ('925 Silver', '925 Silver'),
        ('925 Sterling Silver', '925 Sterling Silver'),
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

    # Tenant ownership
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='jewellery_items',
        null=True,
        blank=True,
        help_text="Tenant shop owning this jewellery piece"
    )

    import_batch = models.ForeignKey(
        StockImportBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='items',
        help_text="Bulk import batch that created this physical piece"
    )

    # Physical piece identity
    tag_number = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        help_text="Physical jewellery piece tag number (e.g. JWL-000001)"
    )
    item_code = models.CharField(max_length=50, help_text="Piece ID / Tag / Barcode")
    design_code = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        help_text="Design / Model Code (e.g. DSN-GLD-001). Multiple physical pieces can share the same design code."
    )
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='items')
    metal_type = models.CharField(max_length=20, choices=METAL_CHOICES)
    purity = models.CharField(
        max_length=50,
        default='22K',
        help_text="Standard jewellery purity grade (e.g. 22K, 18K, 925)"
    )

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
            models.UniqueConstraint(
                fields=['tenant', 'tag_number'],
                name='unique_tenant_item_tag_number',
            ),
            models.UniqueConstraint(
                fields=['tenant', 'item_code'],
                name='unique_tenant_item_code',
            ),
            # HUID must be unique per tenant when provided; blank ('') values are allowed
            # to repeat so non-hallmarked pieces stay importable/searchable.
            models.UniqueConstraint(
                fields=['tenant', 'huid'],
                condition=~models.Q(huid=''),
                name='unique_tenant_nonblank_huid',
            ),
        ]

    def clean(self):
        super().clean()
        if self.making_charge is None:
            self.making_charge = Decimal('0.00')
        if self.wastage_percent is None:
            self.wastage_percent = Decimal('0.00')
        if self.stone_charges is None:
            self.stone_charges = Decimal('0.00')
        if self.other_charges is None:
            self.other_charges = Decimal('0.00')
        if self.stone_weight is None:
            self.stone_weight = Decimal('0.000')
        if self.tag_number:
            self.tag_number = self.tag_number.strip()
            tag_qs = type(self).objects.filter(tenant=self.tenant, tag_number=self.tag_number)
            if self.pk:
                tag_qs = tag_qs.exclude(pk=self.pk)
            if tag_qs.exists():
                raise ValidationError({'tag_number': 'This tag number is already assigned to another item in your showroom.'})

        # Normalise HUID to uppercase if present
        if self.huid:
            self.huid = self.huid.strip().upper()
            if len(self.huid) != 6 or not self.huid.isalnum():
                raise ValidationError({'huid': 'HUID must be a 6-character alphanumeric code.'})
            # Prevent duplicate HUID values within the same tenant (blank/empty values are always allowed)
            huid_qs = type(self).objects.filter(tenant=self.tenant, huid=self.huid)
            if self.pk:
                huid_qs = huid_qs.exclude(pk=self.pk)
            if huid_qs.exists():
                raise ValidationError({'huid': 'This HUID is already assigned to another item in your showroom.'})

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
    def generate_next_tag_number(cls, tenant=None):
        """
        Thread-safe tag number generator producing unique tags formatted as JWL-000001.
        Uses database row-locking on ItemSequence scoped to the shop tenant.
        """
        from django.db import transaction
        with transaction.atomic():
            seq, _ = ItemSequence.objects.select_for_update().get_or_create(
                tenant=tenant,
                name='jewellery_tag',
                defaults={'last_number': 0}
            )
            # Ensure the sequence counter is at least the highest existing tag number
            if seq.last_number == 0:
                highest = 0
                qs = cls.objects.filter(tag_number__startswith='JWL-')
                if tenant:
                    qs = qs.filter(tenant=tenant)
                for tag in qs.values_list('tag_number', flat=True):
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

            # Safety check against existing record collision in this tenant
            collision_qs = cls.objects.filter(tag_number=tag_candidate)
            if tenant:
                collision_qs = collision_qs.filter(tenant=tenant)
            while collision_qs.exists():
                seq.last_number += 1
                seq.save(update_fields=['last_number'])
                tag_candidate = f"JWL-{seq.last_number:06d}"
                collision_qs = cls.objects.filter(tag_number=tag_candidate)
                if tenant:
                    collision_qs = collision_qs.filter(tenant=tenant)

            return tag_candidate

    def save(self, *args, **kwargs):
        if self.tag_number:
            self.tag_number = self.tag_number.strip()
        if not self.tag_number:
            self.tag_number = self.generate_next_tag_number(tenant=self.tenant)
        if not self.design_code:
            self.design_code = self.item_code
        if self.huid:
            self.huid = self.huid.strip().upper()
        else:
            self.huid = ''
        if self.making_charge is None:
            self.making_charge = Decimal('0.00')
        if self.wastage_percent is None:
            self.wastage_percent = Decimal('0.00')
        if self.stone_charges is None:
            self.stone_charges = Decimal('0.00')
        if self.other_charges is None:
            self.other_charges = Decimal('0.00')
        if self.stone_weight is None:
            self.stone_weight = Decimal('0.000')
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

    @property
    def primary_image(self):
        """Return the primary catalogue image for this piece if available."""
        try:
            if hasattr(self, '_prefetched_objects_cache') and 'images' in self._prefetched_objects_cache:
                for img in self._prefetched_objects_cache['images']:
                    if img.is_primary:
                        return img
                return self._prefetched_objects_cache['images'][0] if self._prefetched_objects_cache['images'] else None
            return self.images.filter(is_primary=True).first() or self.images.first()
        except (OperationalError, ProgrammingError, DatabaseError):
            return None

    @property
    def primary_image_url(self):
        """Safely return the URL of the primary image, or None if unavailable."""
        try:
            img = self.primary_image
            if not img or not getattr(img, 'image', None):
                return None
            return img.image.url
        except (ValueError, DatabaseError, OperationalError, ProgrammingError):
            return None
        except Exception as storage_err:
            # Safe warning logging: log exception type without exposing signed URLs or credentials
            logger.warning("Failed resolving primary image URL for item ID %s: %s", self.pk, storage_err)
            return None

    @property
    def image_url(self):
        """Convenience alias for primary_image_url."""
        return self.primary_image_url

    @property
    def safe_images(self):
        """Safely return all attached images for this piece, or an empty list if query fails."""
        try:
            return list(self.images.all())
        except (OperationalError, ProgrammingError, DatabaseError):
            return []

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
        ('Wholesale Dispatch', 'Wholesale Dispatch'),
        ('Wholesale Return', 'Wholesale Return'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='stock_movements',
        null=True,
        blank=True,
        help_text="Tenant shop owning this stock movement"
    )
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

    def save(self, *args, **kwargs):
        if not self.tenant_id and self.item_id and getattr(self.item, 'tenant_id', None):
            self.tenant_id = self.item.tenant_id
        super().save(*args, **kwargs)

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

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='metal_rates',
        null=True,
        blank=True,
        help_text="Tenant shop owning this metal rate"
    )
    metal_type = models.CharField(max_length=20, choices=METAL_CHOICES)
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
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'metal_type'],
                name='unique_tenant_metal_rate',
            ),
        ]

    def __str__(self):
        return f"{self.metal_type}: ₹{self.rate_per_gram}/g"

    @classmethod
    def get_rate(cls, metal_type, tenant=None):
        qs = cls.objects.filter(metal_type=metal_type)
        if tenant:
            rate_obj = qs.filter(tenant=tenant).first()
            if rate_obj:
                return rate_obj.rate_per_gram
        rate_obj = qs.first()
        return rate_obj.rate_per_gram if rate_obj else None


# =============================================================================
# Jewellery Item Images & Media
# =============================================================================

ALLOWED_JEWELLERY_IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')


def validate_jewellery_image_extension(value):
    """Ensure uploaded jewellery image is in an allowed web image format."""
    if not value:
        return
    ext = os.path.splitext(getattr(value, 'name', '') or '')[1].lower()
    if ext not in ALLOWED_JEWELLERY_IMAGE_EXTENSIONS:
        raise ValidationError(
            f"Unsupported image format '{ext}'. Allowed: "
            + ', '.join(ALLOWED_JEWELLERY_IMAGE_EXTENSIONS)
        )


def item_image_upload_path(instance, filename):
    """Generate a clean, tenant-isolated upload path for jewellery item photographs.

    Path pattern: inventory/items/tenant_<id>/<year>/<month>/<uuid>_<clean_filename>
    """
    now = timezone.now()
    tenant_part = f"tenant_{instance.tenant_id}" if getattr(instance, 'tenant_id', None) else "shared"
    name, ext = os.path.splitext(filename or '')
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '', name)[:30] or "photo"
    unique_prefix = uuid.uuid4().hex[:12]
    clean_filename = f"{unique_prefix}_{safe_name}{ext.lower()}"
    return f"inventory/items/{tenant_part}/{now.year:04d}/{now.month:02d}/{clean_filename}"


class JewelleryItemImage(models.Model):
    """High-resolution photograph or AI studio render linked to a JewelleryItem.

    Enforces strict tenant isolation, primary image tracking, and supports
    multi-angle photography (front, model wear, hallmark macro) for catalogue.
    """

    SOURCE_UPLOAD = 'UPLOAD'
    SOURCE_AI_STUDIO = 'AI_STUDIO'
    SOURCE_CAMERA = 'CAMERA'
    SOURCE_CHOICES = [
        (SOURCE_UPLOAD, 'Direct Upload'),
        (SOURCE_AI_STUDIO, 'AI Photo Studio'),
        (SOURCE_CAMERA, 'Live Camera Capture'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='jewellery_images',
        null=True,
        blank=True,
        help_text="Tenant shop owning this jewellery photograph",
    )
    item = models.ForeignKey(
        JewelleryItem,
        on_delete=models.CASCADE,
        related_name='images',
        help_text="Jewellery piece this image showcases",
    )
    image = models.FileField(
        upload_to=item_image_upload_path,
        validators=[validate_jewellery_image_extension],
        help_text="Jewellery piece photograph or render (JPEG, PNG, WEBP).",
    )
    is_primary = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Primary showcase photo for this jewellery piece in listings and catalogue.",
    )
    caption = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional view angle or caption (e.g. Front View, Model Wearing, Macro Hallmark).",
    )
    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_UPLOAD,
        help_text="How this image was acquired (Direct Upload, AI Photo Studio, Camera).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_jewellery_images',
    )

    class Meta:
        ordering = ['-is_primary', '-created_at']
        verbose_name = 'Jewellery Item Image'
        verbose_name_plural = 'Jewellery Item Images'

    def clean(self):
        super().clean()
        # Tenant integrity validation: prohibit cross-tenant item attachment
        if self.item_id and getattr(self.item, 'tenant_id', None):
            if self.tenant_id and self.tenant_id != self.item.tenant_id:
                raise ValidationError({
                    'item': 'Cross-tenant violation: The chosen jewellery item belongs to a different showroom.'
                })
            if not self.tenant_id:
                self.tenant = self.item.tenant

    def save(self, *args, **kwargs):
        # Auto-inherit tenant from item if not explicitly supplied
        if not self.tenant_id and self.item_id and getattr(self.item, 'tenant_id', None):
            self.tenant = self.item.tenant
        self.full_clean()

        # If designated as the primary image, ensure all other images for this item are demoted
        if self.is_primary and self.item_id:
            with transaction.atomic():
                type(self).objects.filter(
                    item_id=self.item_id, is_primary=True
                ).exclude(pk=self.pk).update(is_primary=False)
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    def __str__(self):
        item_tag = getattr(self.item, 'tag_number', '') or getattr(self.item, 'item_code', '') or f"Item #{self.item_id}"
        primary_badge = " [Primary]" if self.is_primary else ""
        caption_part = f" ({self.caption})" if self.caption else ""
        return f"Image for {item_tag}{caption_part}{primary_badge}"


