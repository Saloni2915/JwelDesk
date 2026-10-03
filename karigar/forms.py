from decimal import Decimal
from django import forms
from django.core.validators import FileExtensionValidator
from django.utils import timezone

from customers.models import Customer
from custom_orders.models import CustomOrder
from inventory.models import JewelleryItem
from .models import Karigar, KarigarWorkAssignment, KarigarSettlement


class KarigarForm(forms.ModelForm):
    """Form to create or update a Karigar (Artisan) profile."""

    class Meta:
        model = Karigar
        fields = [
            'karigar_code',
            'name',
            'mobile',
            'alternate_contact',
            'email',
            'address',
            'specialization',
            'status',
            'joining_date',
            'pan_or_id',
            'bank_details',
            'notes',
        ]
        widgets = {
            'karigar_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Auto-generated if blank (e.g. KRG-0001)',
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Artisan / Workshop Name',
            }),
            'mobile': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '10-digit mobile number',
            }),
            'alternate_contact': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Alternate phone or workshop contact',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'artisan@example.com (optional)',
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Workshop address or locality...',
            }),
            'specialization': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'joining_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'pan_or_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'PAN, Aadhaar, or Workshop Reg. (optional)',
            }),
            'bank_details': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Bank A/C, IFSC, UPI ID for payments...',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Special terms, skill notes, references...',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['karigar_code'].required = False
        if not self.instance.pk:
            self.fields['joining_date'].initial = timezone.localdate()

    def clean_mobile(self):
        mobile = self.cleaned_data.get('mobile', '').strip()
        if not mobile:
            raise forms.ValidationError('Mobile number is required.')
        clean_digits = ''.join(c for c in mobile if c.isdigit())
        if len(clean_digits) < 7:
            raise forms.ValidationError('Please enter a valid mobile number (minimum 7 digits).')
        return mobile

    def clean_karigar_code(self):
        code = self.cleaned_data.get('karigar_code', '').strip()
        if code:
            existing = Karigar.objects.filter(karigar_code__iexact=code)
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise forms.ValidationError(f"Karigar code '{code}' is already in use.")
        return code


class KarigarWorkAssignmentForm(forms.ModelForm):
    """Form to issue work to a Karigar with initial metal weight & specifications."""

    issue_stock_item = forms.BooleanField(
        required=False,
        initial=True,
        label="Deduct inventory piece from stock during assignment",
        help_text="If checked and an inventory piece is selected, 1 piece will be removed from available showroom stock into manufacturing."
    )

    class Meta:
        model = KarigarWorkAssignment
        fields = [
            'karigar',
            'customer',
            'custom_order',
            'inventory_item',
            'work_type',
            'priority',
            'description',
            'reference_image',
            'issue_date',
            'expected_completion_date',
            'metal_type',
            'purity',
            'gross_weight_issued',
            'stone_weight_issued',
            'wastage_allowed_percent',
            'making_charge_type',
            'making_charge_rate',
            'stone_charges',
            'other_charges',
            'other_charges_description',
            'notes',
        ]
        widgets = {
            'karigar': forms.Select(attrs={'class': 'form-select'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'custom_order': forms.Select(attrs={'class': 'form-select'}),
            'inventory_item': forms.Select(attrs={'class': 'form-select'}),
            'work_type': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Detailed instructions: design specs, size, target weight, findings...',
            }),
            'reference_image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'issue_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'expected_completion_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'metal_type': forms.Select(attrs={'class': 'form-select'}),
            'purity': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 22K (916), 18K (750), 925 Silver',
            }),
            'gross_weight_issued': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'placeholder': '0.000',
            }),
            'stone_weight_issued': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'placeholder': '0.000',
            }),
            'wastage_allowed_percent': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '1.50',
            }),
            'making_charge_type': forms.Select(attrs={'class': 'form-select'}),
            'making_charge_rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': 'Rate in ₹',
            }),
            'stone_charges': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00',
            }),
            'other_charges': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00',
            }),
            'other_charges_description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Rhodium, Enamel / Meena, Hallmark',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Internal notes or Karigar remarks...',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only active karigars for new assignments
        self.fields['karigar'].queryset = Karigar.objects.filter(status=Karigar.STATUS_ACTIVE)
        # Clean select options
        self.fields['customer'].queryset = Customer.objects.order_by('name')
        self.fields['customer'].required = False
        self.fields['custom_order'].queryset = CustomOrder.objects.exclude(
            status__in=[CustomOrder.STATUS_DELIVERED, CustomOrder.STATUS_CANCELLED]
        ).order_by('-id')
        self.fields['custom_order'].required = False
        self.fields['inventory_item'].queryset = JewelleryItem.objects.filter(
            status='Available'
        ).order_by('name')
        self.fields['inventory_item'].required = False

        if 'purity' in self.fields:
            self.fields['purity'].required = False

        if not self.instance.pk:
            self.fields['issue_date'].initial = timezone.localdate()
            self.fields['expected_completion_date'].initial = timezone.localdate() + timezone.timedelta(days=7)

        if self.instance.pk and self.instance.stock_movement_issued:
            # If stock was already deducted, don't show checkbox
            self.fields.pop('issue_stock_item', None)

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('purity'):
            cleaned_data['purity'] = '22K'
        issue_date = cleaned_data.get('issue_date')
        expected_date = cleaned_data.get('expected_completion_date')
        gross_issued = cleaned_data.get('gross_weight_issued') or Decimal('0.000')
        stone_issued = cleaned_data.get('stone_weight_issued') or Decimal('0.000')

        if expected_date and issue_date and expected_date < issue_date:
            self.add_error('expected_completion_date', 'Expected completion date cannot be before issue date.')

        if gross_issued < 0:
            self.add_error('gross_weight_issued', 'Gross weight issued cannot be negative.')

        if stone_issued < 0:
            self.add_error('stone_weight_issued', 'Stone weight issued cannot be negative.')

        if stone_issued > gross_issued:
            self.add_error('stone_weight_issued', 'Stone weight cannot exceed gross weight issued.')

        return cleaned_data


class KarigarReceiveWorkForm(forms.ModelForm):
    """Form to receive completed work back from artisan with weight & charge accountability."""

    return_to_inventory = forms.BooleanField(
        required=False,
        initial=True,
        label="Return item to available inventory stock",
        help_text="Check to add this piece back to available showroom inventory stock."
    )

    class Meta:
        model = KarigarWorkAssignment
        fields = [
            'actual_completion_date',
            'gross_weight_received',
            'stone_weight_received',
            'scrap_weight_returned',
            'making_charge_type',
            'making_charge_rate',
            'stone_charges',
            'other_charges',
            'other_charges_description',
            'notes',
        ]
        widgets = {
            'actual_completion_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'gross_weight_received': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'placeholder': '0.000',
            }),
            'stone_weight_received': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'placeholder': '0.000',
            }),
            'scrap_weight_returned': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'placeholder': '0.000',
            }),
            'making_charge_type': forms.Select(attrs={'class': 'form-select'}),
            'making_charge_rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': 'Rate in ₹',
            }),
            'stone_charges': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00',
            }),
            'other_charges': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00',
            }),
            'other_charges_description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Rhodium, Enamel / Meena, Hallmark',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Inspection notes, quality verification, or variance explanation...',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.actual_completion_date:
            self.fields['actual_completion_date'].initial = timezone.localdate()
        if not self.instance.inventory_item:
            self.fields.pop('return_to_inventory', None)

    def clean(self):
        cleaned_data = super().clean()
        actual_date = cleaned_data.get('actual_completion_date')
        gross_rec = cleaned_data.get('gross_weight_received') or Decimal('0.000')
        stone_rec = cleaned_data.get('stone_weight_received') or Decimal('0.000')
        scrap_rec = cleaned_data.get('scrap_weight_returned') or Decimal('0.000')

        if actual_date and self.instance.issue_date and actual_date < self.instance.issue_date:
            self.add_error('actual_completion_date', 'Completion date cannot be before issue date.')

        if gross_rec < 0:
            self.add_error('gross_weight_received', 'Gross weight received cannot be negative.')

        if stone_rec < 0:
            self.add_error('stone_weight_received', 'Stone weight received cannot be negative.')

        if stone_rec > gross_rec:
            self.add_error('stone_weight_received', 'Stone weight cannot exceed gross weight received.')

        if scrap_rec < 0:
            self.add_error('scrap_weight_returned', 'Scrap weight cannot be negative.')

        return cleaned_data


class KarigarSettlementForm(forms.ModelForm):
    """Form to process a payment/settlement to a Karigar."""

    class Meta:
        model = KarigarSettlement
        fields = [
            'karigar',
            'payment_date',
            'amount',
            'payment_method',
            'payment_reference',
            'assignments',
            'notes',
        ]
        widgets = {
            'karigar': forms.Select(attrs={'class': 'form-select'}),
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0.01',
                'placeholder': 'Amount in ₹',
            }),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'payment_reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'UTR # / Cheque # / UPI Ref',
            }),
            'assignments': forms.SelectMultiple(attrs={
                'class': 'form-select',
                'size': 6,
                'help_text': 'Hold Ctrl (or Cmd) to select multiple assignments to mark as settled.',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Payment notes or settlement terms...',
            }),
        }

    def __init__(self, *args, **kwargs):
        karigar_id = kwargs.pop('karigar_id', None)
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            self.fields['payment_date'].initial = timezone.localdate()

        if karigar_id:
            try:
                karigar = Karigar.objects.get(pk=karigar_id)
                self.fields['karigar'].initial = karigar
                self.fields['karigar'].queryset = Karigar.objects.filter(pk=karigar_id)
                self.fields['assignments'].queryset = karigar.assignments.exclude(
                    status=KarigarWorkAssignment.STATUS_CANCELLED
                ).exclude(payment_status='Paid')
            except Karigar.DoesNotExist:
                self.fields['assignments'].queryset = KarigarWorkAssignment.objects.none()
        else:
            self.fields['karigar'].queryset = Karigar.objects.filter(status=Karigar.STATUS_ACTIVE)
            self.fields['assignments'].queryset = KarigarWorkAssignment.objects.exclude(
                status=KarigarWorkAssignment.STATUS_CANCELLED
            ).exclude(payment_status='Paid')

        self.fields['assignments'].required = False


class KarigarCancelSettlementForm(forms.Form):
    """Form to safely cancel a settlement voucher with audit reason."""

    cancellation_reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'State the reason for cancelling this settlement voucher...',
        }),
        required=True,
        help_text="Audit requirement: reason will be permanently recorded."
    )
