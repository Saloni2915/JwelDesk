"""
coupons/models.py
-----------------
Multi-tenant customer coupon, promotional campaign, and redemption models for JewelDesk.
Allows each jewellery business to create, manage, print, and redeem coupons
strictly isolated to their own tenant account.
"""

from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone


class CustomerCoupon(models.Model):
    """A promotional offer or customer coupon campaign owned by an individual jewellery business."""

    # Occasions
    OCCASION_DIWALI         = 'diwali'
    OCCASION_DHANTERAS      = 'dhanteras'
    OCCASION_AKSHAYA_TRITIYA = 'akshaya_tritiya'
    OCCASION_WEDDING        = 'wedding'
    OCCASION_ANNIVERSARY    = 'anniversary'
    OCCASION_LOYALTY        = 'loyalty'
    OCCASION_GENERAL        = 'general'

    OCCASION_CHOICES = [
        (OCCASION_DIWALI,          'Festive: Diwali Special'),
        (OCCASION_DHANTERAS,       'Festive: Dhanteras Shubh Muhurat'),
        (OCCASION_AKSHAYA_TRITIYA, 'Festive: Akshaya Tritiya Fortune'),
        (OCCASION_WEDDING,         'Wedding / Bridal Season'),
        (OCCASION_ANNIVERSARY,     'Customer Anniversary / Birthday'),
        (OCCASION_LOYALTY,         'VIP / Customer Loyalty Reward'),
        (OCCASION_GENERAL,         'General Promotional Offer'),
    ]

    # Discount Types
    DISCOUNT_PERCENTAGE = 'percentage'
    DISCOUNT_FIXED      = 'fixed'

    DISCOUNT_CHOICES = [
        (DISCOUNT_PERCENTAGE, 'Percentage Discount (%)'),
        (DISCOUNT_FIXED,      'Fixed Cash Discount (₹)'),
    ]

    # Status
    STATUS_ACTIVE   = 'active'
    STATUS_PAUSED   = 'paused'
    STATUS_EXPIRED  = 'expired'
    STATUS_ARCHIVED = 'archived'

    STATUS_CHOICES = [
        (STATUS_ACTIVE,   'Active'),
        (STATUS_PAUSED,   'Paused'),
        (STATUS_EXPIRED,  'Expired'),
        (STATUS_ARCHIVED, 'Archived'),
    ]

    # Design Source & Built-in Styles
    DESIGN_PRESET = 'preset'
    DESIGN_CUSTOM = 'custom'

    DESIGN_SOURCE_CHOICES = [
        (DESIGN_PRESET, 'Ready-Made Luxury Preset'),
        (DESIGN_CUSTOM, 'Custom HTML / CSS Designer'),
    ]

    STYLE_LUXURY_GOLD      = 'luxury_gold'
    STYLE_FESTIVE_DIWALI   = 'festive_diwali'
    STYLE_PERCENTAGE_PROMO = 'percentage_promo'
    STYLE_CASH_VOUCHER     = 'cash_voucher'
    STYLE_MINIMAL_WHITE    = 'minimal_white'
    STYLE_COMPACT_SHEET    = 'compact_sheet'

    STYLE_CHOICES = [
        (STYLE_LUXURY_GOLD,      'Royal Heritage Gold (Dark Velvet & Gold)'),
        (STYLE_FESTIVE_DIWALI,   'Festive Diwali & Dhanteras (Aura & Deepam)'),
        (STYLE_PERCENTAGE_PROMO, 'Modern Percentage Privilege Voucher'),
        (STYLE_CASH_VOUCHER,     'Fixed Cash Gift Voucher (INR Denomination)'),
        (STYLE_MINIMAL_WHITE,    'Minimalist Boutique White Voucher'),
        (STYLE_COMPACT_SHEET,    'Compact Multi-Coupon Sheet (Perforated)'),
    ]

    # Paper Formats
    PAGE_SIZE_A4     = 'a4'
    PAGE_SIZE_SINGLE = 'single'

    PAGE_SIZE_CHOICES = [
        (PAGE_SIZE_A4,     'A4 Multi-Coupon Sheet'),
        (PAGE_SIZE_SINGLE, 'Single Voucher per Page'),
    ]

    ORIENTATION_PORTRAIT  = 'portrait'
    ORIENTATION_LANDSCAPE = 'landscape'

    ORIENTATION_CHOICES = [
        (ORIENTATION_PORTRAIT,  'Portrait'),
        (ORIENTATION_LANDSCAPE, 'Landscape'),
    ]

    # ---- Core Identification & Tenant Scoping ----
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='customer_coupons',
        help_text="Tenant jewellery business owning this coupon campaign"
    )
    name = models.CharField(
        max_length=150,
        help_text="Campaign name, e.g. 'Diwali 2026 Gold Privilege Voucher'"
    )
    code = models.CharField(
        max_length=50,
        db_index=True,
        help_text="General promo code, e.g. 'DIWALI2026' or 'GOLD500'"
    )
    occasion = models.CharField(
        max_length=40,
        choices=OCCASION_CHOICES,
        default=OCCASION_GENERAL,
        db_index=True
    )
    description = models.TextField(
        blank=True,
        help_text="Internal campaign objectives or customer notes"
    )

    # ---- Discount Rules ----
    discount_type = models.CharField(
        max_length=20,
        choices=DISCOUNT_CHOICES,
        default=DISCOUNT_PERCENTAGE
    )
    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('10.00'),
        help_text="Percentage (e.g. 15.00 for 15%) or Fixed Cash Amount in ₹ (e.g. 1000.00)"
    )
    max_discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional ceiling cap in ₹ for percentage discounts"
    )
    min_purchase_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Minimum invoice amount required before discount can apply"
    )

    # ---- Target Restrictions ----
    applicable_category = models.ForeignKey(
        'inventory.Category',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='applicable_customer_coupons',
        help_text="Optional restriction to a specific jewellery category (e.g. Gold, Diamond)"
    )
    specific_customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='targeted_customer_coupons',
        help_text="Optional restriction to an individual customer (e.g. VIP loyalty offer)"
    )

    # ---- Validity & Usage Limits ----
    valid_from = models.DateField(
        null=True,
        blank=True,
        help_text="Offer start date (inclusive)"
    )
    valid_until = models.DateField(
        null=True,
        blank=True,
        help_text="Offer expiry date (inclusive)"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True
    )
    is_single_use = models.BooleanField(
        default=False,
        help_text="If enabled, can only be redeemed once overall"
    )
    max_uses_total = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum total redemptions permitted across all customers (leave blank for unlimited)"
    )
    max_uses_per_customer = models.PositiveIntegerField(
        default=1,
        help_text="Maximum redemptions allowed per customer (default 1)"
    )
    times_redeemed = models.PositiveIntegerField(
        default=0,
        help_text="Total number of times this offer has been redeemed"
    )
    terms_and_conditions = models.TextField(
        blank=True,
        default=(
            "1. Valid on select jewellery purchases at this showroom.\n"
            "2. Cannot be combined with bullion bar rates or other offers.\n"
            "3. Voucher must be presented or verified during billing.\n"
            "4. Management reserves the right of final redemption decision."
        )
    )

    # ---- Designer & Visual Customization ----
    design_source = models.CharField(
        max_length=20,
        choices=DESIGN_SOURCE_CHOICES,
        default=DESIGN_PRESET
    )
    preset_style = models.CharField(
        max_length=30,
        choices=STYLE_CHOICES,
        default=STYLE_LUXURY_GOLD
    )
    custom_html = models.TextField(
        blank=True,
        help_text="Custom HTML layout with safe placeholders: {{business_name}}, {{coupon_code}}, etc."
    )
    custom_css = models.TextField(
        blank=True,
        help_text="Custom CSS styling for print and preview"
    )
    primary_color = models.CharField(
        max_length=30,
        default='#d4af37',
        help_text="Primary gold/accent color (hex)"
    )
    background_color = models.CharField(
        max_length=30,
        default='#160f09',
        help_text="Card background color (hex)"
    )
    text_color = models.CharField(
        max_length=30,
        default='#fef9ed',
        help_text="Text color (hex)"
    )

    # ---- Physical Print & Layout Settings ----
    page_size = models.CharField(
        max_length=20,
        choices=PAGE_SIZE_CHOICES,
        default=PAGE_SIZE_A4
    )
    orientation = models.CharField(
        max_length=20,
        choices=ORIENTATION_CHOICES,
        default=ORIENTATION_PORTRAIT
    )
    coupon_width_mm = models.PositiveIntegerField(
        default=180,
        help_text="Coupon voucher width in mm"
    )
    coupon_height_mm = models.PositiveIntegerField(
        default=70,
        help_text="Coupon voucher height in mm"
    )
    grid_columns = models.PositiveIntegerField(
        default=1,
        help_text="Coupons per row on sheet layout"
    )
    grid_rows = models.PositiveIntegerField(
        default=3,
        help_text="Coupons per column on sheet layout"
    )
    margin_mm = models.PositiveIntegerField(
        default=8,
        help_text="Page margin in mm"
    )
    spacing_mm = models.PositiveIntegerField(
        default=6,
        help_text="Spacing between coupons in mm"
    )
    show_barcode = models.BooleanField(
        default=True,
        help_text="Render vector Code 128 barcode"
    )
    show_qr_code = models.BooleanField(
        default=True,
        help_text="Render vector QR code badge"
    )

    # ---- Audit Metadata ----
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_tenant_coupons'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Customer Coupon'
        verbose_name_plural = 'Customer Coupons'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'code'],
                name='unique_tenant_coupon_code'
            )
        ]

    def __str__(self):
        return f"{self.name} [{self.code}] - {self.tenant.name if self.tenant else 'No Tenant'}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.code:
            self.code = self.code.strip().upper()
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValidationError({'valid_until': "Expiration date cannot be earlier than start date."})

    @property
    def formatted_discount(self) -> str:
        if self.discount_type == self.DISCOUNT_PERCENTAGE:
            val = int(self.discount_value) if self.discount_value % 1 == 0 else self.discount_value
            return f"{val}% OFF"
        val = int(self.discount_value) if self.discount_value % 1 == 0 else self.discount_value
        return f"₹{val:,.0f} OFF" if isinstance(val, (int, float, Decimal)) and val % 1 == 0 else f"₹{val} OFF"

    @property
    def is_currently_valid(self) -> bool:
        """Check if coupon is active and within current date window."""
        if self.status != self.STATUS_ACTIVE:
            return False
        today = timezone.localdate()
        if self.valid_from and today < self.valid_from:
            return False
        if self.valid_until and today > self.valid_until:
            return False
        if self.is_single_use and self.times_redeemed >= 1:
            return False
        if self.max_uses_total and self.times_redeemed >= self.max_uses_total:
            return False
        return True

    @property
    def capacity_per_sheet(self) -> int:
        return max(1, self.grid_columns * self.grid_rows)


class CouponCodeItem(models.Model):
    """An individual unique serialised coupon code generated under a campaign batch."""

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='coupon_code_items',
        help_text="Tenant jewellery business owning this code"
    )
    coupon = models.ForeignKey(
        CustomerCoupon,
        on_delete=models.CASCADE,
        related_name='code_items'
    )
    code = models.CharField(
        max_length=60,
        db_index=True,
        help_text="Unique collision-free voucher code (e.g. JD-9A7B3X2F)"
    )
    serial_number = models.PositiveIntegerField(
        help_text="Sequential serial number (e.g. 1, 2, 3...)"
    )
    is_redeemed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if this specific unique code has been redeemed"
    )
    redeemed_at = models.DateTimeField(
        null=True,
        blank=True
    )
    redeemed_by_customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='redeemed_coupon_code_items'
    )
    redeemed_in_sale = models.ForeignKey(
        'sales.Sale',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='redeemed_coupon_items'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['coupon', 'serial_number']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'code'],
                name='unique_tenant_coupon_code_item'
            ),
            models.UniqueConstraint(
                fields=['coupon', 'serial_number'],
                name='unique_coupon_item_serial'
            )
        ]

    def __str__(self):
        return f"#{self.serial_number:04d} [{self.code}] - {self.coupon.name}"


class CouponRedemption(models.Model):
    """Immutable audit log of each coupon redemption at the billing/POS counter."""

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='coupon_redemptions'
    )
    coupon = models.ForeignKey(
        CustomerCoupon,
        on_delete=models.CASCADE,
        related_name='redemptions'
    )
    code_item = models.ForeignKey(
        CouponCodeItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='redemption_record'
    )
    coupon_code_used = models.CharField(
        max_length=60,
        help_text="Exact code submitted and redeemed"
    )
    sale = models.ForeignKey(
        'sales.Sale',
        on_delete=models.CASCADE,
        related_name='coupon_redemption_records'
    )
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='coupon_redemptions'
    )
    order_subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Bill subtotal before coupon discount"
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Exact discount amount deducted"
    )
    final_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Final payable total after coupon discount"
    )
    redeemed_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_coupon_redemptions',
        help_text="Cashier or staff member who processed the sale"
    )
    redeemed_at = models.DateTimeField(
        default=timezone.now,
        db_index=True
    )

    class Meta:
        ordering = ['-redeemed_at']
        verbose_name = 'Coupon Redemption'
        verbose_name_plural = 'Coupon Redemptions'

    def __str__(self):
        return f"Redemption #{self.id}: {self.coupon_code_used} (-₹{self.discount_amount}) on Sale #{self.sale_id}"
