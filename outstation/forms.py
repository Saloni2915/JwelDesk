"""
outstation/forms.py
-------------------
Django Forms for Outstation Jewellery Sales & Stock Tracking.
Provides strict tenant filtering and validation for trips, stock issuance,
sales, returns, and discrepancy resolutions.
"""

from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import clean_10_digit_phone
from team.models import Employee
from customers.models import Customer
from inventory.models import JewelleryItem
from sales.models import Sale
from .models import (
    OutstationTrip,
    OutstationTripItem,
    OutstationTripSale,
    Exhibition,
    ExhibitionExpense,
    ExhibitionItem,
    ExhibitionSale,
)


class OutstationTripForm(forms.ModelForm):
    """Form to create and update an OutstationTrip."""

    departure_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    expected_return_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )

    class Meta:
        model = OutstationTrip
        fields = [
            'destination_city',
            'destination_location',
            'departure_date',
            'expected_return_date',
            'responsible_employee',
            'accompanying_staff',
            'purpose',
            'notes',
        ]
        widgets = {
            'destination_city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Gurgaon, Delhi, Jaipur'}),
            'destination_location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Gold Souk Mall, Karol Bagh'}),
            'responsible_employee': forms.Select(attrs={'class': 'form-select'}),
            'accompanying_staff': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
            'purpose': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. B2B Wholesaler Meet & Private Exhibition'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional travel notes, vehicle, hotel or appointment details...'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        self.tenant = tenant or (kwargs.get('instance').tenant if kwargs.get('instance') else None)
        super().__init__(*args, **kwargs)
        if self.tenant:
            emp_qs = Employee.objects.filter(tenant=self.tenant, status='Active').order_by('full_name')
            self.fields['responsible_employee'].queryset = emp_qs
            self.fields['accompanying_staff'].queryset = emp_qs

        # Defaults for new trips
        if not self.instance.pk:
            self.fields['departure_date'].initial = timezone.now().date()
            self.fields['expected_return_date'].initial = (timezone.now() + timezone.timedelta(days=3)).date()

    def clean(self):
        cleaned_data = super().clean()
        dep = cleaned_data.get('departure_date')
        ret = cleaned_data.get('expected_return_date')
        resp_emp = cleaned_data.get('responsible_employee')

        if dep and ret and ret < dep:
            self.add_error('expected_return_date', 'Expected return date cannot be earlier than departure date.')

        if self.tenant and resp_emp and resp_emp.tenant_id != self.tenant.id:
            self.add_error('responsible_employee', 'Responsible employee must belong to this showroom.')

        return cleaned_data


class OutstationSaleForm(forms.Form):
    """
    Form to record a sale against an OutstationTrip for B2B or B2C buyers.
    """

    buyer_type = forms.ChoiceField(
        choices=OutstationTripSale.BUYER_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'buyerTypeSelect'}),
        initial=OutstationTripSale.BUYER_B2C
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'customerSelect'}),
        help_text="Select existing customer or register a new buyer below"
    )
    # Quick Inline Customer Registration fields if buyer is new
    new_customer_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Client full name or business owner'})
    )
    new_customer_mobile = forms.CharField(
        max_length=10,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '10-digit mobile number',
            'maxlength': '10',
            'inputmode': 'numeric',
            'pattern': '[0-9]{10}',
        })
    )
    new_customer_city = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City (e.g. Gurgaon)'})
    )
    # B2B Trade Details
    business_name = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Jewellery Firm / Store Name (for B2B)'})
    )
    business_gstin = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '15-digit GSTIN (optional)'})
    )
    # Sale Financials
    sale_price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    payment_method = forms.ChoiceField(
        choices=Sale.PAYMENT_METHODS,
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='Cash'
    )
    paid_amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        help_text="Amount received now. Leave equal to sale price for full payment, or less for partial."
    )
    payment_ref = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'UPI Ref / UTR / Cheque No.'})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional notes or exhibition bill remarks...'})
    )

    def __init__(self, *args, trip=None, **kwargs):
        self.trip = trip
        self.tenant = trip.tenant if trip else None
        super().__init__(*args, **kwargs)
        if self.tenant:
            self.fields['customer'].queryset = Customer.objects.filter(tenant=self.tenant).order_by('name')
            self.fields['customer'].required = False  # May register new customer inline

    def clean(self):
        cleaned_data = super().clean()
        customer = cleaned_data.get('customer')
        new_name = cleaned_data.get('new_customer_name', '').strip()
        new_mob = cleaned_data.get('new_customer_mobile', '').strip()

        if not customer and not new_name:
            self.add_error('customer', 'Please select an existing buyer or enter a name for the new buyer.')

        if not customer and new_name and not new_mob:
            self.add_error('new_customer_mobile', 'Mobile number is required when registering a new buyer.')
        elif new_mob:
            try:
                cleaned_data['new_customer_mobile'] = clean_10_digit_phone(new_mob, field_label='Mobile number', required=True)
            except ValidationError as err:
                self.add_error('new_customer_mobile', err.message if hasattr(err, 'message') else str(err))

        sale_price = cleaned_data.get('sale_price')
        paid_amount = cleaned_data.get('paid_amount')

        if sale_price is not None and sale_price <= Decimal('0.00'):
            self.add_error('sale_price', 'Sale price must be greater than zero.')

        if paid_amount is not None:
            if paid_amount < Decimal('0.00'):
                self.add_error('paid_amount', 'Paid amount cannot be negative.')
            if sale_price is not None and paid_amount > sale_price:
                self.add_error('paid_amount', 'Paid amount cannot exceed the total sale price.')

        return cleaned_data


class OutstationReconciliationForm(forms.Form):
    """Form to reconcile an issued item upon return."""

    OUTCOME_CHOICES = [
        ('Returned', 'Returned to Showroom (Safe & Intact)'),
        ('Damaged', 'Damaged Piece (Needs Repair / Melting)'),
        ('Missing', 'Missing / Unaccounted Piece'),
    ]

    outcome = forms.ChoiceField(
        choices=OUTCOME_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'outcomeSelect'}),
        initial='Returned'
    )
    discrepancy_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Mandatory explanation if piece is damaged or missing...'
        })
    )
    notes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Optional verification notes or inspection remarks'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        outcome = cleaned_data.get('outcome')
        reason = cleaned_data.get('discrepancy_reason', '').strip()

        if outcome in ['Damaged', 'Missing'] and not reason:
            self.add_error('discrepancy_reason', 'Discrepancy explanation reason is mandatory for damaged or missing pieces.')

        return cleaned_data


class OutstationDiscrepancyResolveForm(forms.Form):
    """Form to officially authorize and resolve a stock discrepancy."""

    resolution_notes = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Manager / Admin authorization rationale (e.g. Insurance claim filed, written off, melted in workshop)...'
        })
    )
    write_off_stock = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Permanently deduct piece from showroom inventory ledger as Lost/Damaged."
    )


class OutstationTripCloseForm(forms.Form):
    """Form to record return date and close the trip."""

    actual_return_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    closure_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Final trip summary, total business achieved, travel expenses notes...'
        })
    )

    def __init__(self, *args, trip=None, **kwargs):
        self.trip = trip
        super().__init__(*args, **kwargs)
        self.fields['actual_return_date'].initial = timezone.now().date()

    def clean_actual_return_date(self):
        ret_date = self.cleaned_data.get('actual_return_date')
        if self.trip and ret_date and ret_date < self.trip.departure_date:
            raise forms.ValidationError("Actual return date cannot precede the trip departure date.")
        return ret_date


# ==============================================================================
# EXHIBITION FORMS
# ==============================================================================

class ExhibitionForm(forms.ModelForm):
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    daily_opening_time = forms.TimeField(
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        initial='10:00'
    )
    daily_closing_time = forms.TimeField(
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        initial='19:00'
    )

    class Meta:
        model = Exhibition
        fields = [
            'name',
            'venue',
            'city',
            'organiser',
            'stall_number',
            'start_date',
            'end_date',
            'daily_opening_time',
            'daily_closing_time',
            'responsible_employee',
            'booth_staff',
            'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. IIJS Premiere 2026, Sparkle Surat'}),
            'venue': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Jio World Convention Centre, Hall 1'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Mumbai, New Delhi, Jaipur'}),
            'organiser': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. GJEPC, United Exhibitions'}),
            'stall_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Hall 1, Booth 1A-24'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Booth logistics, passes, badges, and display setup...'}),
            'responsible_employee': forms.Select(attrs={'class': 'form-select'}),
            'booth_staff': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)
        if tenant:
            emp_qs = Employee.objects.filter(tenant=tenant, status='Active').order_by('full_name')
            self.fields['responsible_employee'].queryset = emp_qs
            self.fields['booth_staff'].queryset = emp_qs

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_date')
        end = cleaned_data.get('end_date')
        if start and end and end < start:
            self.add_error('end_date', 'Exhibition end date cannot precede start date.')
        return cleaned_data


class ExhibitionExpenseForm(forms.ModelForm):
    expense_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )

    class Meta:
        model = ExhibitionExpense
        fields = [
            'category',
            'amount',
            'expense_date',
            'payee',
            'payment_method',
            'reference_number',
            'notes',
        ]
        widgets = {
            'category': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'payee': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Paid to vendor / organiser'}),
            'payment_method': forms.Select(choices=[
                ('Bank Transfer', 'Bank Transfer / NEFT / RTGS'),
                ('UPI', 'UPI / QR Code'),
                ('Company Card', 'Company Credit / Debit Card'),
                ('Cash', 'Cash'),
                ('Cheque', 'Cheque'),
            ], attrs={'class': 'form-select'}),
            'reference_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Invoice # / UTR / Receipt #'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional expense remarks...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['expense_date'].initial = timezone.now().date()


class ExhibitionSaleForm(forms.Form):
    buyer_type = forms.ChoiceField(
        choices=ExhibitionSale.BUYER_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    business_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Surat Diamonds Pvt Ltd'})
    )
    business_gstin = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '15-character GSTIN (Optional)'})
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label="— Select Existing Customer / Trade Buyer —"
    )
    new_customer_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Buyer full name'})
    )
    new_customer_mobile = forms.CharField(
        max_length=10,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '10-digit mobile number',
            'maxlength': '10',
            'inputmode': 'numeric',
            'pattern': '[0-9]{10}',
        })
    )
    new_customer_city = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Buyer City'})
    )
    sale_price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    payment_method = forms.ChoiceField(
        choices=[
            ('Bank Transfer', 'Bank Transfer / NEFT / RTGS'),
            ('UPI', 'UPI / QR Code'),
            ('Card', 'Credit / Debit Card'),
            ('Cash', 'Cash'),
            ('Cheque', 'Cheque'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    paid_amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        help_text="Amount collected now. Leave blank or equal to sale price if fully paid."
    )
    payment_ref = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'UTR / Transaction / Cheque #'})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Sale notes or trade terms...'})
    )

    def __init__(self, *args, exhibition=None, **kwargs):
        self.exhibition = exhibition
        super().__init__(*args, **kwargs)
        if exhibition and exhibition.tenant:
            self.fields['customer'].queryset = Customer.objects.filter(
                tenant=exhibition.tenant
            ).order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        customer = cleaned_data.get('customer')
        new_name = cleaned_data.get('new_customer_name', '').strip()
        new_mobile = cleaned_data.get('new_customer_mobile', '').strip()

        if not customer and not new_name:
            self.add_error('customer', 'Select an existing buyer or enter a new buyer name.')
        if not customer and new_name and not new_mobile:
            self.add_error('new_customer_mobile', 'Mobile number is required for new customer registration.')
        elif new_mobile:
            try:
                cleaned_data['new_customer_mobile'] = clean_10_digit_phone(new_mobile, field_label='Mobile number', required=True)
            except ValidationError as err:
                self.add_error('new_customer_mobile', err.message if hasattr(err, 'message') else str(err))

        buyer_type = cleaned_data.get('buyer_type')
        biz_name = cleaned_data.get('business_name', '').strip()
        if buyer_type == ExhibitionSale.BUYER_B2B and not biz_name and not customer:
            self.add_error('business_name', 'Business firm name is required for B2B wholesale buyers.')

        return cleaned_data


class ExhibitionCloseForm(forms.Form):
    actual_return_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    closure_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Final exhibition summary, business generated, reconciliation sign-off...'
        })
    )

    def __init__(self, *args, exhibition=None, **kwargs):
        self.exhibition = exhibition
        super().__init__(*args, **kwargs)
        self.fields['actual_return_date'].initial = timezone.now().date()

    def clean_actual_return_date(self):
        ret_date = self.cleaned_data.get('actual_return_date')
        if self.exhibition and ret_date and ret_date < self.exhibition.start_date:
            raise forms.ValidationError("Actual return date cannot precede the exhibition start date.")
        return ret_date
