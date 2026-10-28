from decimal import Decimal
from django import forms
from django.core.validators import FileExtensionValidator
from django.utils import timezone

from accounts.models import clean_10_digit_phone
from customers.models import Customer
from custom_orders.models import CustomOrder
from inventory.models import JewelleryItem
from inventory.forms import PurityChoiceField
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
            'bank_name',
            'account_holder_name',
            'account_number',
            'ifsc_code',
            'branch_name',
            'upi_id',
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
                'maxlength': '10',
                'inputmode': 'numeric',
                'pattern': '[0-9]{10}',
            }),
            'alternate_contact': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '10-digit alternate contact (optional)',
                'maxlength': '10',
                'inputmode': 'numeric',
                'pattern': '[0-9]{10}',
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
            'bank_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. State Bank of India, HDFC Bank',
            }),
            'account_holder_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Name as per bank account',
            }),
            'account_number': forms.TextInput(attrs={
                'class': 'form-control font-monospace',
                'placeholder': 'Bank account number (e.g. 123456789012)',
                'maxlength': '35',
            }),
            'ifsc_code': forms.TextInput(attrs={
                'class': 'form-control font-monospace text-uppercase',
                'placeholder': '11-digit IFSC code (e.g. SBIN0001234)',
                'maxlength': '11',
            }),
            'branch_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Branch location / city (e.g. Zaveri Bazaar)',
            }),
            'upi_id': forms.TextInput(attrs={
                'class': 'form-control font-monospace',
                'placeholder': 'e.g. artisan@upi or 9876543210@paytm',
            }),
            'bank_details': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Additional banking remarks or legacy details...',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Special terms, skill notes, references...',
            }),
        }

    def __init__(self, *args, **kwargs):
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        self.fields['karigar_code'].required = False
        if not self.instance.pk:
            self.fields['joining_date'].initial = timezone.localdate()

    def clean_mobile(self):
        mobile = self.cleaned_data.get('mobile', '').strip()
        return clean_10_digit_phone(mobile, field_label='Mobile number', required=True)

    def clean_alternate_contact(self):
        alt = self.cleaned_data.get('alternate_contact', '').strip()
        return clean_10_digit_phone(alt, field_label='Alternate contact', required=False)

    def clean_ifsc_code(self):
        ifsc = (self.cleaned_data.get('ifsc_code') or '').strip().upper()
        if ifsc and len(ifsc) > 11:
            raise forms.ValidationError("IFSC code should be 11 characters (e.g. SBIN0001234).")
        return ifsc

    def clean_account_number(self):
        acct = (self.cleaned_data.get('account_number') or '').strip()
        return acct

    def clean_upi_id(self):
        upi = (self.cleaned_data.get('upi_id') or '').strip()
        return upi

    def clean_karigar_code(self):
        code = self.cleaned_data.get('karigar_code', '').strip()
        if code:
            existing = Karigar.objects.filter(karigar_code__iexact=code)
            if self.tenant:
                existing = existing.filter(tenant=self.tenant)
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise forms.ValidationError(f"Karigar code '{code}' is already in use.")
        return code

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.tenant and not instance.tenant_id:
            instance.tenant = self.tenant
        if commit:
            instance.save()
        return instance


class KarigarWorkAssignmentForm(forms.ModelForm):
    """Form to issue work to a Karigar with initial metal weight & specifications."""

    issue_stock_item = forms.BooleanField(
        required=False,
        initial=True,
        label="Deduct inventory piece from stock during assignment",
        help_text="If checked and an inventory piece is selected, 1 piece will be removed from available showroom stock into manufacturing."
    )
    purity = PurityChoiceField(required=False, initial='22K')

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
            'metal_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_metal_type'}),
            'purity': forms.Select(attrs={'class': 'form-select', 'id': 'id_purity'}),
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
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        # Only active karigars for new assignments
        if self.tenant:
            self.fields['karigar'].queryset = Karigar.objects.filter(tenant=self.tenant, status=Karigar.STATUS_ACTIVE)
            self.fields['customer'].queryset = Customer.objects.filter(tenant=self.tenant).order_by('name')
            self.fields['custom_order'].queryset = CustomOrder.objects.filter(tenant=self.tenant).exclude(
                status__in=[CustomOrder.STATUS_DELIVERED, CustomOrder.STATUS_CANCELLED]
            ).order_by('-id')
            self.fields['inventory_item'].queryset = JewelleryItem.objects.filter(
                tenant=self.tenant, status='Available'
            ).order_by('name')
        else:
            self.fields['karigar'].queryset = Karigar.objects.filter(status=Karigar.STATUS_ACTIVE)
            self.fields['customer'].queryset = Customer.objects.order_by('name')
            self.fields['custom_order'].queryset = CustomOrder.objects.exclude(
                status__in=[CustomOrder.STATUS_DELIVERED, CustomOrder.STATUS_CANCELLED]
            ).order_by('-id')
            self.fields['inventory_item'].queryset = JewelleryItem.objects.filter(
                status='Available'
            ).order_by('name')
        self.fields['customer'].required = False
        self.fields['custom_order'].required = False
        self.fields['inventory_item'].required = False

        if 'purity' in self.fields:
            self.fields['purity'].required = False
            purity_field = self.fields['purity']
            choices = getattr(purity_field, 'choices', None)
            if choices is None and hasattr(purity_field, 'widget'):
                choices = getattr(purity_field.widget, 'choices', None)
            if choices:
                try:
                    choice_keys = [c[0] for c in choices]
                    curr_purity = getattr(self.instance, 'purity', None) if self.instance else None
                    if curr_purity and curr_purity not in choice_keys:
                        new_choices = list(choices) + [(curr_purity, curr_purity)]
                        if hasattr(purity_field, 'choices'):
                            purity_field.choices = new_choices
                        if hasattr(purity_field, 'widget') and hasattr(purity_field.widget, 'choices'):
                            purity_field.widget.choices = new_choices
                except Exception:
                    pass

        if not self.instance.pk:
            self.fields['issue_date'].initial = timezone.localdate()
            self.fields['expected_completion_date'].initial = timezone.localdate() + timezone.timedelta(days=7)

        if self.instance.pk and self.instance.stock_movement_issued:
            # If stock was already deducted, don't show checkbox
            self.fields.pop('issue_stock_item', None)

    def clean_purity(self):
        val = (self.cleaned_data.get('purity') or '').strip()
        if val.lower() == '22k':
            return '22K'
        if val.lower() == '24k':
            return '24K'
        if val.lower() == '18k':
            return '18K'
        if val.lower() == '14k':
            return '14K'
        return val or '22K'

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

        if self.tenant:
            kg = cleaned_data.get('karigar')
            if kg and kg.tenant_id != self.tenant.id:
                self.add_error('karigar', 'Invalid artisan for this store.')
            cust = cleaned_data.get('customer')
            if cust and cust.tenant_id != self.tenant.id:
                self.add_error('customer', 'Invalid customer for this store.')
            co = cleaned_data.get('custom_order')
            if co and co.tenant_id != self.tenant.id:
                self.add_error('custom_order', 'Invalid custom order for this store.')
            item = cleaned_data.get('inventory_item')
            if item and item.tenant_id != self.tenant.id:
                self.add_error('inventory_item', 'Invalid inventory item for this store.')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.tenant and not instance.tenant_id:
            instance.tenant = self.tenant
        if commit:
            instance.save()
            self.save_m2m()
        return instance


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
        self.tenant = kwargs.pop('tenant', None)
        karigar_id = kwargs.pop('karigar_id', None)
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            self.fields['payment_date'].initial = timezone.localdate()

        if karigar_id:
            try:
                qs = Karigar.objects.filter(pk=karigar_id)
                if self.tenant:
                    qs = qs.filter(tenant=self.tenant)
                karigar = qs.get()
                self.fields['karigar'].initial = karigar
                self.fields['karigar'].queryset = qs
                self.fields['assignments'].queryset = karigar.assignments.exclude(
                    status=KarigarWorkAssignment.STATUS_CANCELLED
                ).exclude(payment_status='Paid')
            except Karigar.DoesNotExist:
                self.fields['assignments'].queryset = KarigarWorkAssignment.objects.none()
        else:
            kg_qs = Karigar.objects.filter(status=Karigar.STATUS_ACTIVE)
            asg_qs = KarigarWorkAssignment.objects.exclude(
                status=KarigarWorkAssignment.STATUS_CANCELLED
            ).exclude(payment_status='Paid')
            if self.tenant:
                kg_qs = kg_qs.filter(tenant=self.tenant)
                asg_qs = asg_qs.filter(tenant=self.tenant)
            self.fields['karigar'].queryset = kg_qs
            self.fields['assignments'].queryset = asg_qs

        self.fields['assignments'].required = False

    def clean_karigar(self):
        karigar = self.cleaned_data.get('karigar')
        if karigar and self.tenant and karigar.tenant_id != self.tenant.id:
            raise forms.ValidationError("Invalid artisan for this store.")
        return karigar

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.tenant and not instance.tenant_id:
            instance.tenant = self.tenant
        if commit:
            instance.save()
            self.save_m2m()
        return instance


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
