"""
coupons/forms.py
----------------
Tenant-scoped forms for Customer Coupon management, design configuration,
and batch code generation.
"""

from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError

from customers.models import Customer
from inventory.models import Category
from super_admin.models import CouponDesignTemplate
from .models import CustomerCoupon
from .services import sanitize_coupon_html, sanitize_coupon_css, get_tenant_preset_markup


class CustomerCouponForm(forms.ModelForm):
    """Create and edit a customer promotional campaign and printable coupon."""

    class Meta:
        model = CustomerCoupon
        fields = [
            'name',
            'code',
            'occasion',
            'description',
            'discount_type',
            'discount_value',
            'max_discount_amount',
            'min_purchase_amount',
            'applicable_category',
            'specific_customer',
            'valid_from',
            'valid_until',
            'status',
            'is_single_use',
            'max_uses_total',
            'max_uses_per_customer',
            'terms_and_conditions',
            'design_source',
            'preset_style',
            'custom_html',
            'custom_css',
            'primary_color',
            'background_color',
            'text_color',
            'page_size',
            'orientation',
            'coupon_width_mm',
            'coupon_height_mm',
            'grid_columns',
            'grid_rows',
            'margin_mm',
            'spacing_mm',
            'show_barcode',
            'show_qr_code',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Diwali Dhamaka 15% Off Gold'}),
            'code': forms.TextInput(attrs={'class': 'form-control text-uppercase font-monospace', 'placeholder': 'e.g. DIWALI2026'}),
            'occasion': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Internal notes or campaign objective...'}),
            'discount_type': forms.Select(attrs={'class': 'form-select'}),
            'discount_value': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'max_discount_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Optional ceiling cap in ₹'}),
            'min_purchase_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'applicable_category': forms.Select(attrs={'class': 'form-select'}),
            'specific_customer': forms.Select(attrs={'class': 'form-select'}),
            'valid_from': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'valid_until': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'is_single_use': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'max_uses_total': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Leave blank for unlimited'}),
            'max_uses_per_customer': forms.NumberInput(attrs={'class': 'form-control', 'value': 1}),
            'terms_and_conditions': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'design_source': forms.Select(attrs={'class': 'form-select'}),
            'preset_style': forms.Select(attrs={'class': 'form-select'}),
            'custom_html': forms.Textarea(attrs={'class': 'form-control font-monospace', 'rows': 8, 'placeholder': 'Custom HTML markup with placeholders like {{coupon_code}}, {{discount_value}}...'}),
            'custom_css': forms.Textarea(attrs={'class': 'form-control font-monospace', 'rows': 8, 'placeholder': 'Print-ready CSS styling...'}),
            'primary_color': forms.TextInput(attrs={'class': 'form-control form-control-color', 'type': 'color'}),
            'background_color': forms.TextInput(attrs={'class': 'form-control form-control-color', 'type': 'color'}),
            'text_color': forms.TextInput(attrs={'class': 'form-control form-control-color', 'type': 'color'}),
            'page_size': forms.Select(attrs={'class': 'form-select'}),
            'orientation': forms.Select(attrs={'class': 'form-select'}),
            'coupon_width_mm': forms.NumberInput(attrs={'class': 'form-control'}),
            'coupon_height_mm': forms.NumberInput(attrs={'class': 'form-control'}),
            'grid_columns': forms.NumberInput(attrs={'class': 'form-control'}),
            'grid_rows': forms.NumberInput(attrs={'class': 'form-control'}),
            'margin_mm': forms.NumberInput(attrs={'class': 'form-control'}),
            'spacing_mm': forms.NumberInput(attrs={'class': 'form-control'}),
            'show_barcode': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_qr_code': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)

        # Restrict Category and Customer choices strictly to current tenant
        if self.tenant:
            self.fields['applicable_category'].queryset = Category.objects.filter(tenant=self.tenant)
            self.fields['specific_customer'].queryset = Customer.objects.filter(tenant=self.tenant)

        # Ensure color fields are optional so saving templates never raises validation errors
        if 'primary_color' in self.fields:
            self.fields['primary_color'].required = False
        if 'background_color' in self.fields:
            self.fields['background_color'].required = False
        if 'text_color' in self.fields:
            self.fields['text_color'].required = False
        if 'max_uses_per_customer' in self.fields:
            self.fields['max_uses_per_customer'].required = False

        # Custom voucher HTML and CSS should remain blank by default for a clean slate


    def clean_code(self):
        code = self.cleaned_data.get('code', '').strip().upper()
        if not code:
            raise ValidationError("Please specify a coupon promo code.")

        # Ensure uniqueness per tenant
        qs = CustomerCoupon.objects.filter(code__iexact=code)
        if self.tenant:
            qs = qs.filter(tenant=self.tenant)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise ValidationError(f"A coupon with code '{code}' already exists in your showroom.")
        return code

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get('valid_from')
        valid_until = cleaned_data.get('valid_until')

        if valid_from and valid_until and valid_from > valid_until:
            self.add_error('valid_until', "Expiry date cannot be prior to the start date.")

        discount_type = cleaned_data.get('discount_type')
        discount_value = cleaned_data.get('discount_value')
        if discount_type == CustomerCoupon.DISCOUNT_PERCENTAGE and discount_value:
            if discount_value <= 0 or discount_value > 100:
                self.add_error('discount_value', "Percentage discount must be between 0.01% and 100%.")
        elif discount_type == CustomerCoupon.DISCOUNT_FIXED and discount_value:
            if discount_value <= 0:
                self.add_error('discount_value', "Cash discount amount must be greater than ₹0.")

        # Robust color defaults fallback if omitted or left blank
        if not cleaned_data.get('primary_color'):
            cleaned_data['primary_color'] = (
                self.instance.primary_color if (self.instance and self.instance.pk and self.instance.primary_color)
                else '#d4af37'
            )
        if not cleaned_data.get('background_color'):
            cleaned_data['background_color'] = (
                self.instance.background_color if (self.instance and self.instance.pk and self.instance.background_color)
                else '#160f09'
            )
        if not cleaned_data.get('text_color'):
            cleaned_data['text_color'] = (
                self.instance.text_color if (self.instance and self.instance.pk and self.instance.text_color)
                else '#fef9ed'
            )
        if not cleaned_data.get('max_uses_per_customer'):
            cleaned_data['max_uses_per_customer'] = (
                self.instance.max_uses_per_customer if (self.instance and self.instance.pk and self.instance.max_uses_per_customer)
                else 1
            )

        # Sanitize HTML and CSS
        custom_html = cleaned_data.get('custom_html', '')
        custom_css = cleaned_data.get('custom_css', '')
        if custom_html:
            cleaned_data['custom_html'] = sanitize_coupon_html(custom_html)
        if custom_css:
            cleaned_data['custom_css'] = sanitize_coupon_css(custom_css)

        return cleaned_data


class CouponBatchGenerateForm(forms.Form):
    """Bulk generate unique serialized coupon codes under a campaign."""

    quantity = forms.IntegerField(
        min_value=1,
        max_value=500,
        initial=20,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 20, 50, 100'}),
        help_text="Number of unique coupon vouchers to generate (max 500 per batch)."
    )
    code_prefix = forms.CharField(
        max_length=15,
        required=False,
        initial='JD-',
        widget=forms.TextInput(attrs={'class': 'form-control text-uppercase font-monospace', 'placeholder': 'e.g. DIWALI-, VIP-'}),
        help_text="Optional prefix for the codes (e.g. 'DIWALI-')"
    )
    code_length = forms.IntegerField(
        min_value=6,
        max_value=14,
        initial=8,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        help_text="Length of random characters in code (6 to 14 characters)."
    )
    serial_start = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        help_text="Starting serial number for this batch."
    )


class ClonePlatformTemplateForm(forms.Form):
    """Clone a platform-level Super Admin template into the tenant's own offer library."""

    platform_template = forms.ModelChoiceField(
        queryset=CouponDesignTemplate.objects.filter(is_archived=False),
        empty_label="-- Select Platform Template to Copy --",
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Changes made will be saved to your private showroom design without altering platform defaults."
    )
    new_coupon_code = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-control text-uppercase font-monospace', 'placeholder': 'e.g. DIWALI2026'}),
        help_text="Unique promo code for your showroom offer."
    )
