"""
purchases/forms.py
------------------
Django form definitions for the Purchase Management Module.
Includes proper Bootstrap 5 styling, field validation, and dynamic formsets.
"""
from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError

from inventory.models import Category
from .models import (
    Supplier,
    PurchaseSetting,
    PurchaseInvoice,
    PurchaseItem,
    SupplierPayment,
    PurchaseReturn,
)


class SupplierForm(forms.ModelForm):
    """Form for adding and modifying suppliers / vendors."""

    class Meta:
        model = Supplier
        fields = [
            'name', 'contact_person', 'mobile', 'whatsapp_number', 'email',
            'address', 'city', 'state', 'state_code', 'pincode',
            'gstin', 'pan_number',
            'bank_name', 'account_number', 'ifsc_code', 'upi_id',
            'opening_balance', 'is_active', 'notes'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Navkar Bullion / Rajesh Exports', 'required': 'required'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contact Person Name'}),
            'mobile': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Primary 10-digit Mobile', 'required': 'required'}),
            'whatsapp_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'WhatsApp Number'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'supplier@email.com'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Shop / Office Address'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City'}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'State'}),
            'state_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 27 (MH), 24 (GJ)'}),
            'pincode': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '6-digit PIN'}),
            'gstin': forms.TextInput(attrs={'class': 'form-control text-uppercase', 'placeholder': '15-digit GSTIN'}),
            'pan_number': forms.TextInput(attrs={'class': 'form-control text-uppercase', 'placeholder': '10-digit PAN'}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Bank Name'}),
            'account_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Account Number'}),
            'ifsc_code': forms.TextInput(attrs={'class': 'form-control text-uppercase', 'placeholder': 'IFSC Code'}),
            'upi_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'merchant@upi'}),
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Payment terms or supplier notes...'}),
        }

    def clean_gstin(self):
        gstin = (self.cleaned_data.get('gstin') or '').strip().upper()
        if gstin and len(gstin) != 15:
            raise ValidationError("GSTIN must be exactly 15 alphanumeric characters.")
        return gstin

    def clean_pan_number(self):
        pan = (self.cleaned_data.get('pan_number') or '').strip().upper()
        if pan and len(pan) != 10:
            raise ValidationError("PAN Number must be exactly 10 alphanumeric characters.")
        return pan


class PurchaseInvoiceForm(forms.ModelForm):
    """Header form for creating and editing purchase invoices."""

    class Meta:
        model = PurchaseInvoice
        fields = [
            'supplier', 'branch', 'purchase_date',
            'supplier_invoice_number', 'supplier_invoice_date',
            'purchase_type', 'payment_terms_days', 'due_date',
            'tax_type', 'tax_rate', 'discount_amount', 'notes'
        ]
        widgets = {
            'supplier': forms.Select(attrs={'class': 'form-select select2-supplier', 'required': 'required'}),
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'purchase_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'supplier_invoice_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Vendor Bill / Invoice Ref #'}),
            'supplier_invoice_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'purchase_type': forms.Select(attrs={'class': 'form-select'}),
            'payment_terms_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'tax_type': forms.Select(attrs={'class': 'form-select'}),
            'tax_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'discount_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Special delivery notes or terms...'}),
        }

    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields['supplier'].queryset = Supplier.objects.filter(tenant=tenant, is_active=True).order_by('name')
            from team.models import Branch
            self.fields['branch'].queryset = Branch.objects.filter(tenant=tenant, is_active=True).order_by('name')


class PurchaseItemForm(forms.ModelForm):
    """Line item form inside purchase invoice."""

    class Meta:
        model = PurchaseItem
        fields = [
            'item_name', 'category', 'metal_type', 'purity', 'purity_percentage',
            'quantity', 'gross_weight', 'stone_weight', 'net_weight',
            'purchase_rate', 'rate_type',
            'making_charge_type', 'making_charge_rate',
            'stone_charges', 'other_charges', 'tax_rate',
            'huid', 'hallmark_details', 'description'
        ]
        widgets = {
            'item_name': forms.TextInput(attrs={'class': 'form-control form-control-sm item-name-input', 'placeholder': 'e.g. 22K Gold Bangle', 'required': 'required'}),
            'category': forms.Select(attrs={'class': 'form-select form-select-sm item-category-select'}),
            'metal_type': forms.Select(
                choices=[('Gold', 'Gold'), ('Silver', 'Silver'), ('Diamond', 'Diamond'), ('Platinum', 'Platinum'), ('Gemstone', 'Gemstone'), ('Other', 'Other')],
                attrs={'class': 'form-select form-select-sm item-metal-select'}
            ),
            'purity': forms.TextInput(attrs={'class': 'form-control form-control-sm item-purity-input', 'placeholder': 'e.g. 22K, 925'}),
            'purity_percentage': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-purity-pct', 'step': '0.01'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-qty-input', 'min': '1', 'value': '1'}),
            'gross_weight': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-gw-input', 'step': '0.001'}),
            'stone_weight': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-sw-input', 'step': '0.001', 'value': '0.000'}),
            'net_weight': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-nw-input', 'step': '0.001', 'readonly': 'readonly'}),
            'purchase_rate': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-rate-input', 'step': '0.01'}),
            'rate_type': forms.Select(attrs={'class': 'form-select form-select-sm item-ratetype-select'}),
            'making_charge_type': forms.Select(attrs={'class': 'form-select form-select-sm item-mc-type-select'}),
            'making_charge_rate': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-mc-rate-input', 'step': '0.01', 'value': '0.00'}),
            'stone_charges': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-stone-charges', 'step': '0.01', 'value': '0.00'}),
            'other_charges': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-other-charges', 'step': '0.01', 'value': '0.00'}),
            'tax_rate': forms.NumberInput(attrs={'class': 'form-control form-control-sm item-tax-rate', 'step': '0.01', 'value': '3.00'}),
            'huid': forms.TextInput(attrs={'class': 'form-control form-control-sm text-uppercase item-huid-input', 'placeholder': '6-char HUID'}),
            'hallmark_details': forms.TextInput(attrs={'class': 'form-control form-control-sm item-hallmark-input', 'placeholder': 'BIS 916 / 750'}),
            'description': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Item notes'}),
        }

    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields['category'].queryset = Category.objects.filter(tenant=tenant).order_by('name')


class SupplierPaymentForm(forms.ModelForm):
    """Payment voucher form for recording outward settlement to suppliers."""

    class Meta:
        model = SupplierPayment
        fields = [
            'supplier', 'purchase_invoice', 'payment_date',
            'amount', 'payment_method', 'reference', 'bank_name', 'notes'
        ]
        widgets = {
            'supplier': forms.Select(attrs={'class': 'form-select', 'required': 'required'}),
            'purchase_invoice': forms.Select(attrs={'class': 'form-select'}),
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control fw-bold fs-5', 'step': '0.01', 'min': '0.01', 'required': 'required'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'reference': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'UTR # / Cheque # / Ref'}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Remitting Bank Name'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Payment reference notes...'}),
        }

    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant', None)
        supplier_id = kwargs.pop('supplier_id', None)
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields['supplier'].queryset = Supplier.objects.filter(tenant=tenant, is_active=True).order_by('name')
            qs = PurchaseInvoice.objects.filter(tenant=tenant, status__in=['CONFIRMED', 'PARTIALLY_PAID'])
            if supplier_id:
                qs = qs.filter(supplier_id=supplier_id)
            self.fields['purchase_invoice'].queryset = qs.order_by('-purchase_date')
            self.fields['purchase_invoice'].required = False


class PurchaseSettingForm(forms.ModelForm):
    """Form to manage purchase module settings per tenant."""

    class Meta:
        model = PurchaseSetting
        fields = [
            'purchase_prefix', 'payment_prefix', 'return_prefix', 'supplier_prefix',
            'default_payment_terms_days', 'default_tax_rate', 'default_tax_type',
            'auto_create_inventory_for_ready_made', 'auto_create_inventory_for_bullion'
        ]
        widgets = {
            'purchase_prefix': forms.TextInput(attrs={'class': 'form-control text-uppercase'}),
            'payment_prefix': forms.TextInput(attrs={'class': 'form-control text-uppercase'}),
            'return_prefix': forms.TextInput(attrs={'class': 'form-control text-uppercase'}),
            'supplier_prefix': forms.TextInput(attrs={'class': 'form-control text-uppercase'}),
            'default_payment_terms_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'default_tax_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'default_tax_type': forms.Select(attrs={'class': 'form-select'}),
            'auto_create_inventory_for_ready_made': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'auto_create_inventory_for_bullion': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

