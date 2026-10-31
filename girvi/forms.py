"""
girvi/forms.py
--------------
Form definitions for the Girvi (Jewellery Pledge & Loan Management) module.
Handles validation, multi-tenancy filtering, and inline collateral itemsets.
"""

from decimal import Decimal
from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from customers.models import Customer
from team.models import Branch
from inventory.models import Category, JewelleryItem
from .models import (
    GirviSetting,
    GirviLoan,
    GirviItem,
    GirviPayment,
    GirviWaiver,
)


class GirviLoanForm(forms.ModelForm):
    """Form to create or edit a Girvi Loan."""

    class Meta:
        model = GirviLoan
        fields = [
            'customer',
            'branch',
            'loan_date',
            'principal_amount',
            'interest_rate_percent',
            'interest_period',
            'interest_calculation_type',
            'loan_duration_months',
            'maturity_date',
            'grace_period_days',
            'processing_charges',
            'custody_location',
            'terms_conditions',
            'notes',
        ]
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select', 'id': 'id_customer'}),
            'branch': forms.Select(attrs={'class': 'form-select', 'id': 'id_branch'}),
            'loan_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'principal_amount': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '1', 'placeholder': '0.00', 'id': 'id_principal_amount'
            }),
            'interest_rate_percent': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '2.00', 'id': 'id_interest_rate_percent'
            }),
            'interest_period': forms.Select(attrs={'class': 'form-select'}),
            'interest_calculation_type': forms.Select(attrs={'class': 'form-select'}),
            'loan_duration_months': forms.NumberInput(attrs={
                'class': 'form-control', 'min': '1', 'max': '120', 'placeholder': '12', 'id': 'id_loan_duration_months'
            }),
            'maturity_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'id': 'id_maturity_date'}),
            'grace_period_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'placeholder': '7'}),
            'processing_charges': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '0.00'
            }),
            'custody_location': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'e.g. Vault Safe A, Box #12'
            }),
            'terms_conditions': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3, 'placeholder': 'Pledge agreement terms & conditions...'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2, 'placeholder': 'Internal notes or special instructions...'
            }),
        }

    def __init__(self, *args, tenant=None, branch=None, available_branches=None, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)

        # Tenant-scoped customers
        if self.tenant:
            self.fields['customer'].queryset = Customer.objects.filter(
                tenant=self.tenant
            ).order_by('name')
        else:
            self.fields['customer'].queryset = Customer.objects.none()

        # Branch filtering
        if available_branches is not None:
            if hasattr(available_branches, 'all'):
                self.fields['branch'].queryset = available_branches
            else:
                branch_ids = [b.id for b in available_branches]
                self.fields['branch'].queryset = Branch.objects.filter(id__in=branch_ids)
        elif self.tenant:
            self.fields['branch'].queryset = Branch.objects.filter(
                tenant=self.tenant, is_active=True
            ).order_by('-is_default', 'name')
        else:
            self.fields['branch'].queryset = Branch.objects.none()

        # Set default branch if creating new
        if not self.instance.pk:
            if branch:
                self.initial['branch'] = branch
            elif self.tenant:
                default_b = Branch.objects.filter(tenant=self.tenant, is_default=True).first()
                if default_b:
                    self.initial['branch'] = default_b

            # Default loan_date to today
            if not self.initial.get('loan_date'):
                self.initial['loan_date'] = timezone.localdate()

    def clean(self):
        cleaned_data = super().clean()
        principal = cleaned_data.get('principal_amount')
        rate = cleaned_data.get('interest_rate_percent')
        loan_date = cleaned_data.get('loan_date')
        duration = cleaned_data.get('loan_duration_months')
        maturity_date = cleaned_data.get('maturity_date')

        if principal is not None and principal <= Decimal('0.00'):
            self.add_error('principal_amount', "Loan principal must be greater than zero.")

        if rate is not None and rate < Decimal('0.00'):
            self.add_error('interest_rate_percent', "Interest rate cannot be negative.")

        # Auto-compute maturity date if missing
        if loan_date and duration and not maturity_date:
            import datetime
            # Approximation: duration * 30 days or calendar month shift
            # Using 30 days per month or relative date
            from dateutil.relativedelta import relativedelta
            try:
                cleaned_data['maturity_date'] = loan_date + relativedelta(months=duration)
            except Exception:
                cleaned_data['maturity_date'] = loan_date + datetime.timedelta(days=duration * 30)

        return cleaned_data


class GirviItemForm(forms.ModelForm):
    """Form for an individual pledged collateral item."""

    class Meta:
        model = GirviItem
        fields = [
            'item_name',
            'category',
            'metal_type',
            'purity',
            'quantity',
            'gross_weight',
            'stone_weight',
            'net_weight',
            'estimated_market_rate',
            'market_value',
            'loan_value',
            'huid',
            'description',
            'item_photo',
        ]
        widgets = {
            'item_name': forms.TextInput(attrs={
                'class': 'form-control form-control-sm item-name-input',
                'placeholder': 'e.g. Gold Necklace, Silver Anklet'
            }),
            'category': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'metal_type': forms.Select(attrs={'class': 'form-select form-select-sm metal-type-select'}),
            'purity': forms.Select(attrs={'class': 'form-select form-select-sm purity-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': '1', 'value': '1'}),
            'gross_weight': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm gross-weight-input',
                'step': '0.001', 'min': '0.001', 'placeholder': '0.000'
            }),
            'stone_weight': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm stone-weight-input',
                'step': '0.001', 'min': '0', 'placeholder': '0.000'
            }),
            'net_weight': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm net-weight-input',
                'step': '0.001', 'min': '0.001', 'placeholder': '0.000'
            }),
            'estimated_market_rate': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm market-rate-input',
                'step': '0.01', 'min': '0', 'placeholder': '0.00'
            }),
            'market_value': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm market-val-input',
                'step': '0.01', 'min': '0', 'placeholder': '0.00'
            }),
            'loan_value': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm loan-val-input',
                'step': '0.01', 'min': '0', 'placeholder': '0.00'
            }),
            'huid': forms.TextInput(attrs={
                'class': 'form-control form-control-sm text-uppercase',
                'maxlength': '10', 'placeholder': 'HUID'
            }),
            'description': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'Stones, hallmark, condition...'
            }),
            'item_photo': forms.ClearableFileInput(attrs={'class': 'form-control form-control-sm'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['net_weight'].required = False
        self.fields['stone_weight'].required = False
        self.fields['item_name'].required = True
        self.fields['gross_weight'].required = True

    def clean(self):
        cleaned_data = super().clean()
        gross = cleaned_data.get('gross_weight')
        stone = cleaned_data.get('stone_weight') or Decimal('0.000')

        if gross is not None:
            if gross <= Decimal('0.000'):
                self.add_error('gross_weight', "Gross weight must be greater than zero.")
            if stone > gross:
                self.add_error('stone_weight', "Stone weight cannot exceed gross weight.")
            # Auto-calculate net weight
            cleaned_data['net_weight'] = max(Decimal('0.000'), gross - stone)

        return cleaned_data


# Inline Formset for multi-item collateral pledges
GirviItemFormSet = inlineformset_factory(
    GirviLoan,
    GirviItem,
    form=GirviItemForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class GirviPaymentForm(forms.ModelForm):
    """Form to record an incoming payment against a Girvi loan."""

    class Meta:
        model = GirviPayment
        fields = [
            'payment_date',
            'total_amount_received',
            'payment_method',
            'interest_portion',
            'principal_portion',
            'charges_portion',
            'reference_number',
            'notes',
        ]
        widgets = {
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'total_amount_received': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '1', 'placeholder': '0.00', 'id': 'id_total_amount_received'
            }),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'interest_portion': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '0.00', 'id': 'id_interest_portion'
            }),
            'principal_portion': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '0.00', 'id': 'id_principal_portion'
            }),
            'charges_portion': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '0.00', 'id': 'id_charges_portion'
            }),
            'reference_number': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'UPI Ref, Cheque No, Bank UTR...'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2, 'placeholder': 'Payment notes (optional)...'
            }),
        }

    def __init__(self, *args, loan=None, **kwargs):
        self.loan = loan
        super().__init__(*args, **kwargs)
        if not self.initial.get('payment_date'):
            self.initial['payment_date'] = timezone.localdate()

    def clean(self):
        cleaned_data = super().clean()
        total = cleaned_data.get('total_amount_received')
        i_portion = cleaned_data.get('interest_portion') or Decimal('0.00')
        p_portion = cleaned_data.get('principal_portion') or Decimal('0.00')
        c_portion = cleaned_data.get('charges_portion') or Decimal('0.00')

        if total is not None and total <= Decimal('0.00'):
            self.add_error('total_amount_received', "Payment amount must be greater than zero.")

        # If user entered explicit breakdown, ensure they add up
        if total is not None and (i_portion > 0 or p_portion > 0 or c_portion > 0):
            alloc_sum = i_portion + p_portion + c_portion
            if alloc_sum != total:
                self.add_error(
                    'total_amount_received',
                    f"Sum of allocations (Principal: ₹{p_portion} + Interest: ₹{i_portion} + Charges: ₹{c_portion} = ₹{alloc_sum}) "
                    f"must match Total Received amount (₹{total})."
                )

        return cleaned_data


class GirviPaymentReverseForm(forms.Form):
    """Form to reverse an earlier payment with mandatory reason."""
    reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'rows': 3,
            'placeholder': 'Provide a detailed reason for reversing this payment voucher (e.g. Bounced cheque, wrong loan account, entry error)...'
        }),
        required=True,
        help_text="Mandatory audit explanation for reversal."
    )


class GirviWaiverForm(forms.ModelForm):
    """Form to grant an explicit financial waiver/discount."""

    class Meta:
        model = GirviWaiver
        fields = ['waiver_type', 'amount', 'reason']
        widgets = {
            'waiver_type': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0.01', 'placeholder': '0.00'
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3,
                'placeholder': 'Explain why this waiver is approved (e.g. Customer goodwill, full settlement discount authorized by owner)...'
            }),
        }


class GirviReleaseForm(forms.Form):
    """Form to confirm physical jewellery collateral release to the customer."""
    notes = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'rows': 3,
            'placeholder': 'Release remarks: borrower verified, original pledge voucher collected, ID verified...'
        }),
        required=False,
    )
    confirm_handover = forms.BooleanField(
        required=True,
        label="I confirm all pledged jewellery articles have been physically inspected, counted, and handed over to the customer."
    )


class GirviSettingForm(forms.ModelForm):
    """Form to configure showroom default Girvi parameters."""

    class Meta:
        model = GirviSetting
        fields = [
            'loan_number_prefix',
            'payment_number_prefix',
            'default_interest_rate_monthly',
            'default_interest_period',
            'default_calculation_type',
            'default_loan_duration_months',
            'default_grace_period_days',
            'standard_terms_conditions',
        ]
        widgets = {
            'loan_number_prefix': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'GIR-'}),
            'payment_number_prefix': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'PAY-GIR-'}),
            'default_interest_rate_monthly': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '2.00'
            }),
            'default_interest_period': forms.Select(attrs={'class': 'form-select'}),
            'default_calculation_type': forms.Select(attrs={'class': 'form-select'}),
            'default_loan_duration_months': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '120'}),
            'default_grace_period_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'standard_terms_conditions': forms.Textarea(attrs={'class': 'form-control', 'rows': 6}),
        }
