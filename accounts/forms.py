from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)
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


class JewelDeskSignUpForm(UserCreationForm):
    """User registration form styled for JewelDesk auth panels."""

    first_name = forms.CharField(
        label='Full Name',
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'jd-auth__control',
            'placeholder': 'Enter your full name',
            'autocomplete': 'name',
            'autofocus': True,
        }),
    )
    email = forms.EmailField(
        label='Email Address',
        max_length=254,
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'jd-auth__control',
            'placeholder': 'name@jewelleryshop.com',
            'autocomplete': 'email',
        }),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('first_name', 'username', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'username' in self.fields:
            self.fields['username'].label = 'Username'
            self.fields['username'].widget.attrs.update({
                'class': 'jd-auth__control',
                'placeholder': 'Choose a username',
                'autocomplete': 'username',
                'autocapitalize': 'none',
                'autocorrect': 'off',
                'spellcheck': 'false',
            })
            self.fields['username'].help_text = (
                'Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.'
            )
        if 'password1' in self.fields:
            self.fields['password1'].label = 'Password'
            self.fields['password1'].widget.attrs.update({
                'class': 'jd-auth__control jd-auth__control--password',
                'placeholder': 'Create a secure password',
                'autocomplete': 'new-password',
            })
        if 'password2' in self.fields:
            self.fields['password2'].label = 'Confirm Password'
            self.fields['password2'].widget.attrs.update({
                'class': 'jd-auth__control jd-auth__control--password',
                'placeholder': 'Confirm your password',
                'autocomplete': 'new-password',
            })

    def clean_first_name(self):
        name = (self.cleaned_data.get('first_name') or '').strip()
        if not name:
            raise forms.ValidationError('Full name is required.')
        return name

    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if not username:
            raise forms.ValidationError('Username is required.')
        User = get_user_model()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('A user with that username already exists.')
        if User.objects.filter(email__iexact=username).exists():
            raise forms.ValidationError('This username is already registered as an email address.')
        return username

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            raise forms.ValidationError('Email address is required.')
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                'An account with this email address already exists. Please sign in or reset your password.'
            )
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError(
                'An account with this identifier already exists. Please sign in or reset your password.'
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = (self.cleaned_data.get('first_name') or '').strip()
        user.email = (self.cleaned_data.get('email') or '').strip().lower()
        user.is_active = True
        if commit:
            user.save()
        return user



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
