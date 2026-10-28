from django import forms
from accounts.models import clean_10_digit_phone
from .models import Customer


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'mobile', 'email', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Customer full name'}),
            'mobile': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '10-digit mobile number',
                'maxlength': '10',
                'inputmode': 'numeric',
                'pattern': '[0-9]{10}',
            }),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'customer@example.com (optional)'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Customer address (optional)'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        self.tenant = tenant or (kwargs.get('instance').tenant if kwargs.get('instance') else None)
        super().__init__(*args, **kwargs)

    def clean_mobile(self):
        mobile = self.cleaned_data.get('mobile', '').strip()
        return clean_10_digit_phone(mobile, field_label='Mobile number', required=True)

