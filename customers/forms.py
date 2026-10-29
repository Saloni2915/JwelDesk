from django import forms
from accounts.models import clean_10_digit_phone, validate_proper_email
from .models import Customer


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'mobile', 'email', 'address', 'branch']
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
            'branch': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, tenant=None, branch=None, **kwargs):
        self.tenant = tenant or (kwargs.get('instance').tenant if kwargs.get('instance') else None)
        super().__init__(*args, **kwargs)
        if 'branch' in self.fields:
            self.fields['branch'].required = False
            self.fields['branch'].empty_label = "Select Branch (Default / Showroom)"
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

    def clean_mobile(self):
        mobile = self.cleaned_data.get('mobile', '').strip()
        return clean_10_digit_phone(mobile, field_label='Mobile number', required=True)

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            return ''
        return validate_proper_email(email, field_label='Customer email', required=False)

