import re
from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError

from accounts.models import validate_gstin, clean_10_digit_phone, validate_proper_email
from inventory.models import JewelleryItem, Category
from .models import (
    RetailerParty,
    WholesaleOrder,
    WholesaleOrderItem,
    WholesaleDispatch,
    WholesaleInvoice,
    RetailerPayment,
    WholesaleReturn,
    WholesaleReturnItem,
    WholesalePricingRule,
)


class RetailerPartyForm(forms.ModelForm):
    class Meta:
        model = RetailerParty
        fields = [
            'name', 'branch', 'contact_person', 'phone', 'email',
            'billing_address', 'shipping_address',
            'gstin', 'pan_number', 'credit_limit',
            'payment_terms_days', 'opening_balance', 'is_active', 'notes',
        ]
        widgets = {
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'billing_address': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'shipping_address': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Royal Gems & Jewellers'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contact Person Name'}),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '10-digit mobile / phone number',
                'maxlength': '10',
                'inputmode': 'numeric',
                'pattern': '[0-9]{10}',
            }),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'retailer@email.com'}),
            'gstin': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '15-digit GSTIN (optional)'}),
            'pan_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'PAN Number (optional)'}),
            'credit_limit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'payment_terms_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, tenant=None, branch=None, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)
        if 'branch' in self.fields:
            self.fields['branch'].required = False
            self.fields['branch'].empty_label = "Select Branch (Main Showroom / Depo)"
            if self.tenant:
                from team.models import Branch
                self.fields['branch'].queryset = Branch.objects.filter(tenant=self.tenant, is_active=True).order_by('-is_default', 'name')
            if not self.instance.pk:
                if branch:
                    self.initial['branch'] = branch
                elif self.tenant:
                    from team.models import Branch
                    default_b = Branch.objects.filter(tenant=self.tenant, is_default=True, is_active=True).first()
                    if default_b:
                        self.initial['branch'] = default_b

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise ValidationError("Retailer / Party name is required.")
        if self.tenant:
            qs = RetailerParty.objects.filter(tenant=self.tenant, name__iexact=name)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError("A retailer party with this business name already exists in your account.")
        return name

    def clean_gstin(self):
        gstin = (self.cleaned_data.get('gstin') or '').strip().upper()
        if gstin:
            validate_gstin(gstin)
        return gstin

    def clean_phone(self):
        phone = (self.cleaned_data.get('phone') or '').strip()
        return clean_10_digit_phone(phone, field_label='Phone / Mobile number', required=True)

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            return ''
        return validate_proper_email(email, field_label='Email address', required=False)


class WholesaleOrderForm(forms.ModelForm):
    class Meta:
        model = WholesaleOrder
        fields = ['party', 'order_date', 'expected_delivery_date', 'notes', 'internal_remarks']
        widgets = {
            'party': forms.Select(attrs={'class': 'form-select select2-enable'}),
            'order_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'expected_delivery_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Notes visible to buyer'}),
            'internal_remarks': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Internal notes'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields['party'].queryset = RetailerParty.objects.filter(tenant=tenant, is_active=True)


class WholesaleOrderItemForm(forms.ModelForm):
    class Meta:
        model = WholesaleOrderItem
        fields = ['item', 'quantity', 'unit_price', 'discount_percent', 'tax_rate']
        widgets = {
            'item': forms.Select(attrs={'class': 'form-select select2-enable item-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control qty-input', 'min': '1'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control price-input', 'step': '0.01'}),
            'discount_percent': forms.NumberInput(attrs={'class': 'form-control discount-input', 'step': '0.01'}),
            'tax_rate': forms.NumberInput(attrs={'class': 'form-control tax-input', 'step': '0.01'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields['item'].queryset = JewelleryItem.objects.filter(tenant=tenant, status='Available', quantity__gt=0)


class RetailerPaymentForm(forms.ModelForm):
    class Meta:
        model = RetailerPayment
        fields = ['party', 'amount', 'payment_date', 'payment_method', 'reference', 'notes']
        widgets = {
            'party': forms.Select(attrs={'class': 'form-select select2-enable'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'reference': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cheque / UTR / Reference ID'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields['party'].queryset = RetailerParty.objects.filter(tenant=tenant, is_active=True)

    def clean_amount(self):
        amt = self.cleaned_data.get('amount')
        if amt is None or amt <= 0:
            raise ValidationError("Payment amount must be greater than zero.")
        return amt


class WholesaleReturnForm(forms.ModelForm):
    class Meta:
        model = WholesaleReturn
        fields = ['party', 'invoice', 'return_date', 'reason', 'inspection_notes']
        widgets = {
            'party': forms.Select(attrs={'class': 'form-select select2-enable'}),
            'invoice': forms.Select(attrs={'class': 'form-select'}),
            'return_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'reason': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Reason for return'}),
            'inspection_notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields['party'].queryset = RetailerParty.objects.filter(tenant=tenant)
            self.fields['invoice'].queryset = WholesaleInvoice.objects.filter(tenant=tenant).exclude(status=WholesaleInvoice.STATUS_CANCELLED)


class WholesalePricingRuleForm(forms.ModelForm):
    class Meta:
        model = WholesalePricingRule
        fields = ['party', 'category', 'item', 'discount_percent', 'making_charge_discount_percent', 'fixed_price_override', 'minimum_order_quantity', 'is_active']
        widgets = {
            'party': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'item': forms.Select(attrs={'class': 'form-select'}),
            'discount_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'making_charge_discount_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'fixed_price_override': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'minimum_order_quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields['party'].queryset = RetailerParty.objects.filter(tenant=tenant, is_active=True)
            self.fields['category'].queryset = Category.objects.filter(tenant=tenant)
            self.fields['item'].queryset = JewelleryItem.objects.filter(tenant=tenant)
