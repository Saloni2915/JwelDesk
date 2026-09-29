from django import forms
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
import re

from .models import CompanySettings


class JewelDeskPasswordResetForm(PasswordResetForm):
    """Custom password reset form styled for JewelDesk auth panels."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update({
            'class': 'jd-auth__control',
            'placeholder': 'Enter your registered email',
            'autocomplete': 'email',
            'autofocus': True,
        })


class JewelDeskSetPasswordForm(SetPasswordForm):
    """Custom password confirmation form styled for JewelDesk auth panels."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ('new_password1', 'new_password2'):
            if field in self.fields:
                self.fields[field].widget.attrs.update({
                    'class': 'jd-auth__control jd-auth__control--password',
                })


COMPANY_NAME_MAX = 200
COMPANY_GSTIN_RE = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$')


class CompanySettingsForm(forms.ModelForm):
    """Admin form for the singleton company settings record."""

    class Meta:
        model = CompanySettings
        fields = ('company_name', 'logo', 'gstin', 'address', 'phone',
                  'email', 'invoice_footer_note')
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
            'invoice_footer_note': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('company_name', 'gstin', 'phone', 'email'):
            self.fields[name].widget.attrs.setdefault('class', 'form-control')
        self.fields['address'].widget.attrs.setdefault('class', 'form-control')
        self.fields['invoice_footer_note'].widget.attrs.setdefault(
            'class', 'form-control')
        self.fields['logo'].widget.attrs.setdefault('class', 'form-control')

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get('company_name') or '').strip()
        gstin = (cleaned.get('gstin') or '').strip()
        phone = (cleaned.get('phone') or '').strip()
        email = (cleaned.get('email') or '').strip()
        cleaned['company_name'] = name
        cleaned['gstin'] = gstin
        cleaned['phone'] = phone
        cleaned['email'] = email

        if self.errors:
            return cleaned

        if email and '@' not in email:
            self.add_error('email', 'Enter a valid email address.')
        if phone and not re.match(r'^[0-9+\-\s()]{5,20}$', phone):
            self.add_error(
                'phone', 'Enter a valid phone number (digits, spaces, + - ( ) only).')
        if gstin and not COMPANY_GSTIN_RE.fullmatch(gstin):
            self.add_error(
                'gstin', 'GSTIN must be 15 characters in the correct pattern '
                '(e.g. 27AAAAA0000A1Z5).')
        for field in ('company_name', 'gstin', 'phone', 'email', 'address',
                       'invoice_footer_note'):
            if len(cleaned.get(field, '') or '') > COMPANY_NAME_MAX:
                self.add_error(field, f'Maximum length is {COMPANY_NAME_MAX} characters.')

        return cleaned
