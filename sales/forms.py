from decimal import Decimal
from django import forms
from django.db.models import Q
from .models import Enquiry, Payment, Sale, OldGoldTransaction
from inventory.models import JewelleryItem


class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ['customer', 'jewellery_item', 'sale_price', 'payment_method', 'notes']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'jewellery_item': forms.Select(attrs={'class': 'form-select'}),
            'sale_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional sale notes or bill reference...'}),
        }
        error_messages = {
            'jewellery_item': {
                'invalid_choice': 'This jewellery item is already SOLD or unavailable.',
            }
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show items that are Available
        if self.instance and self.instance.pk:
            # If editing existing sale, include current item as well
            self.fields['jewellery_item'].queryset = JewelleryItem.objects.filter(
                Q(status='Available') | Q(pk=self.instance.jewellery_item_id)
            ).select_related('category')
        else:
            self.fields['jewellery_item'].queryset = JewelleryItem.objects.filter(
                status='Available').select_related('category')
        # Show tag number + design in the dropdown for reliable piece identification.
        self.fields['jewellery_item'].label_from_instance = (
            lambda obj: f"[{obj.tag_number or obj.item_code}] {obj.name} "
                        f"({obj.metal_type} {obj.purity}) - Rs.{obj.selling_price}"
        )


class EnquiryForm(forms.ModelForm):
    class Meta:
        model = Enquiry
        fields = ['customer', 'category', 'interested_item', 'budget', 'notes', 'status', 'next_followup_date']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'interested_item': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Solitaire Diamond Ring 1ct or 22K Gold Chain'}),
            'budget': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Optional budget in ₹'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Customer preferences, design notes, etc.'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'next_followup_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

class PaymentForm(forms.ModelForm):
    """Validates a payment against the sale's remaining due amount."""

    class Meta:
        model = Payment
        fields = ['amount', 'payment_method', 'reference', 'notes']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0.01',
                'placeholder': '0.00'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Transaction / cheque / UPI reference (optional)'}),
            'notes': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'Optional notes...'}),
        }

    def __init__(self, *args, sale=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sale = sale

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount is None or amount <= 0:
            raise forms.ValidationError(
                'Payment amount must be greater than zero.')
        if self.sale is not None:
            remaining = self.sale.due_amount
            if amount > remaining:
                raise forms.ValidationError(
                    'Payment exceeds the remaining due amount of '
                    f'Rs. {remaining:,.2f}.')
        return amount


class OldGoldExchangeForm(forms.ModelForm):
    """
    Form for creating an Old Gold Exchange transaction linked with a new jewellery purchase.
    """
    new_jewellery_item = forms.ModelChoiceField(
        queryset=JewelleryItem.objects.filter(status='Available').select_related('category'),
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_new_jewellery_item'}),
        label='Select New Jewellery Item',
        help_text='Only currently Available items from inventory'
    )
    new_sale_price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'id': 'id_new_sale_price'}),
        label='New Jewellery Sale Price (₹)'
    )
    settlement_payment_method = forms.ChoiceField(
        choices=[
            ('Cash', 'Cash'),
            ('UPI', 'UPI'),
            ('Card', 'Card'),
            ('Bank Transfer', 'Bank Transfer'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_settlement_payment_method'}),
        label='Payment Method for Difference (if customer owes)'
    )
    settlement_payment_reference = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'UPI ID / Card slip / Reference'}),
        label='Payment Reference'
    )

    class Meta:
        model = OldGoldTransaction
        fields = [
            'customer',
            'metal_type',
            'old_gold_type',
            'item_description',
            'gross_weight',
            'stone_weight',
            'purity',
            'custom_purity_percent',
            'applicable_rate',
            'deduction_percent',
            'notes',
        ]
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select', 'id': 'id_customer'}),
            'metal_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_metal_type'}),
            'old_gold_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_old_gold_type'}),
            'item_description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Broken 22K Bangle (2 pcs)', 'id': 'id_item_description'}),
            'gross_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000', 'id': 'id_gross_weight'}),
            'stone_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000', 'id': 'id_stone_weight'}),
            'purity': forms.Select(attrs={'class': 'form-select', 'id': 'id_purity'}),
            'custom_purity_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'e.g. 84.50', 'id': 'id_custom_purity_percent'}),
            'applicable_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'id': 'id_applicable_rate'}),
            'deduction_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00', 'id': 'id_deduction_percent'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional internal notes, melting remarks, testing notes...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_jewellery_item'].label_from_instance = (
            lambda obj: f"[{obj.tag_number or obj.item_code}] {obj.name} "
                        f"({obj.metal_type} {obj.purity}) - ₹{obj.selling_price:,.2f}"
        )
        if not self.initial.get('applicable_rate'):
            from inventory.pricing import get_current_metal_rate
            self.initial['applicable_rate'] = get_current_metal_rate('Gold')

    def clean(self):
        cleaned_data = super().clean()
        gross = cleaned_data.get('gross_weight')
        stone = cleaned_data.get('stone_weight') or Decimal('0.000')
        if gross and stone >= gross:
            self.add_error('stone_weight', 'Stone weight cannot be equal to or greater than gross weight.')

        purity = cleaned_data.get('purity')
        custom_pct = cleaned_data.get('custom_purity_percent')
        if purity == 'Other' and (not custom_pct or custom_pct <= 0 or custom_pct > 100):
            self.add_error('custom_purity_percent', 'Please enter a valid custom purity percentage between 0% and 100%.')

        item = cleaned_data.get('new_jewellery_item')
        if item and (item.status != 'Available' or item.quantity <= 0):
            self.add_error('new_jewellery_item', f"Selected item '{item.name}' is no longer available in stock.")

        return cleaned_data


class OldGoldBuybackForm(forms.ModelForm):
    """
    Form for creating an Outright Old Gold Buyback transaction (Cash/Bank payout).
    """
    class Meta:
        model = OldGoldTransaction
        fields = [
            'customer',
            'metal_type',
            'old_gold_type',
            'item_description',
            'gross_weight',
            'stone_weight',
            'purity',
            'custom_purity_percent',
            'applicable_rate',
            'deduction_percent',
            'payment_method',
            'payment_status',
            'payment_reference',
            'notes',
        ]
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select', 'id': 'id_customer'}),
            'metal_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_metal_type'}),
            'old_gold_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_old_gold_type'}),
            'item_description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Broken 22K Bangle (2 pcs)', 'id': 'id_item_description'}),
            'gross_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000', 'id': 'id_gross_weight'}),
            'stone_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000', 'id': 'id_stone_weight'}),
            'purity': forms.Select(attrs={'class': 'form-select', 'id': 'id_purity'}),
            'custom_purity_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'e.g. 84.50', 'id': 'id_custom_purity_percent'}),
            'applicable_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'id': 'id_applicable_rate'}),
            'deduction_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00', 'id': 'id_deduction_percent'}),
            'payment_method': forms.Select(attrs={'class': 'form-select', 'id': 'id_payment_method'}),
            'payment_status': forms.Select(attrs={'class': 'form-select', 'id': 'id_payment_status'}),
            'payment_reference': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cash voucher # / UPI UTR / Cheque #'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Testing remarks, customer ID verification notes, purity check...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get('applicable_rate'):
            from inventory.pricing import get_current_metal_rate
            self.initial['applicable_rate'] = get_current_metal_rate('Gold')

    def clean(self):
        cleaned_data = super().clean()
        gross = cleaned_data.get('gross_weight')
        stone = cleaned_data.get('stone_weight') or Decimal('0.000')
        if gross and stone >= gross:
            self.add_error('stone_weight', 'Stone weight cannot be equal to or greater than gross weight.')

        purity = cleaned_data.get('purity')
        custom_pct = cleaned_data.get('custom_purity_percent')
        if purity == 'Other' and (not custom_pct or custom_pct <= 0 or custom_pct > 100):
            self.add_error('custom_purity_percent', 'Please enter a valid custom purity percentage between 0% and 100%.')

        return cleaned_data


class OldGoldCancelForm(forms.Form):
    cancellation_reason = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Please specify the reason for cancelling this transaction...'}),
        required=True,
        label='Cancellation Reason'
    )


