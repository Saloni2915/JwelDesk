from django import forms
from django.db.models import Q
from .models import Enquiry, Payment, Sale
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

