from django import forms
from django.db.models import Q
from .models import Sale, Enquiry
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
            )
        else:
            self.fields['jewellery_item'].queryset = JewelleryItem.objects.filter(status='Available')


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
