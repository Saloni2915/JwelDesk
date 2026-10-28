from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.db.models import Q
import re

from .models import CompanySettings, Tenant


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


def generate_username_from_full_name(full_name, email=None):
    """Generate a clean, valid, and unique Django username from full name."""
    import re
    from django.contrib.auth import get_user_model
    User = get_user_model()

    name = (full_name or '').strip()
    if not name and email:
        name = email.split('@')[0]
    if not name:
        name = 'user'

    # Convert spaces to dots and keep only valid characters (letters, digits, @/./+/-/_)
    cleaned = re.sub(r'\s+', '.', name)
    cleaned = re.sub(r'[^\w.@+-]', '', cleaned)
    if not cleaned:
        cleaned = re.sub(r'[^\w.@+-]', '', (email or '').split('@')[0]) or 'user'

    cleaned = cleaned[:140]
    candidate = cleaned
    suffix = 1
    while User.objects.filter(username__iexact=candidate).exists():
        candidate = f"{cleaned}{suffix}"
        suffix += 1

    return candidate


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
    shop_name = forms.CharField(
        label='Jewellery Shop Name',
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'jd-auth__control',
            'placeholder': 'e.g. Sri Krishna Jewellers',
            'autocomplete': 'organization',
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

    business_type = forms.ChoiceField(
        label='Business Type',
        choices=[
            (Tenant.TYPE_RETAIL, 'Retail Jewellery Store'),
            (Tenant.TYPE_WHOLESALE, 'Wholesaler / Jewellery Supplier'),
            (Tenant.TYPE_BOTH, 'Both (Retail & Wholesale)'),
        ],
        initial=Tenant.TYPE_RETAIL,
        required=False,
        widget=forms.Select(attrs={
            'class': 'jd-auth__control',
        }),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('first_name', 'shop_name', 'business_type', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            raise forms.ValidationError('Email address is required.')
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        email = (cleaned_data.get('email') or '').strip().lower()
        User = get_user_model()
        if email and User.objects.filter(email__iexact=email).exists():
            self.add_error('email', 'An account with this email already exists.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        full_name = (self.cleaned_data.get('first_name') or '').strip()
        user.first_name = full_name
        user.email = (self.cleaned_data.get('email') or '').strip().lower()

        # Set username as full name (or explicit username if submitted by legacy tests/API)
        explicit_username = (self.data.get('username') or '').strip()
        User = get_user_model()
        if explicit_username and not User.objects.filter(username__iexact=explicit_username).exists():
            user.username = explicit_username
        else:
            user.username = generate_username_from_full_name(full_name, user.email)

        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
            raw_shop_name = (self.cleaned_data.get('shop_name') or '').strip()
            shop_name = raw_shop_name or f"{user.first_name or user.username}'s Jewellery"
            b_type = self.cleaned_data.get('business_type') or Tenant.TYPE_RETAIL
            tenant = Tenant.objects.create(name=shop_name, owner=user, business_type=b_type)
            CompanySettings.objects.create(tenant=tenant, company_name=shop_name)

            # Create default Tenant Administrator Employee profile for this store owner in their own shop
            from team.models import Employee
            Employee.ensure_tenant_admin(tenant, user)
        return user



COMPANY_NAME_MAX = 200
COMPANY_GSTIN_RE = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$')


class CompanySettingsForm(forms.ModelForm):
    """Admin form for the singleton company settings record."""

    business_type = forms.ChoiceField(
        choices=Tenant.BUSINESS_TYPE_CHOICES,
        required=False,
        label="Business Model / Operations Type",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = CompanySettings
        fields = ('company_name', 'logo', 'gstin', 'address', 'phone',
                  'email', 'language', 'invoice_footer_note')
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
            'invoice_footer_note': forms.Textarea(attrs={'rows': 2}),
            'language': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and getattr(self.instance, 'tenant', None):
            self.fields['business_type'].initial = self.instance.tenant.business_type
        for name in ('company_name', 'gstin', 'phone', 'email', 'business_type', 'language'):
            if name in self.fields:
                self.fields[name].widget.attrs.setdefault('class', 'form-control')
        self.fields['address'].widget.attrs.setdefault('class', 'form-control')
        self.fields['invoice_footer_note'].widget.attrs.setdefault(
            'class', 'form-control')
        self.fields['logo'].widget.attrs.setdefault('class', 'form-control')

    def save(self, commit=True):
        obj = super().save(commit=commit)
        b_type = self.cleaned_data.get('business_type')
        if b_type and getattr(obj, 'tenant', None) and obj.tenant.business_type != b_type:
            obj.tenant.business_type = b_type
            obj.tenant.save(update_fields=['business_type', 'updated_at'])
        return obj

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if logo and hasattr(logo, 'size') and logo.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Logo file size must be less than 5MB.')
        return logo

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
        if phone:
            from .models import clean_10_digit_phone
            try:
                cleaned['phone'] = clean_10_digit_phone(phone, field_label='Phone number', required=False)
            except forms.ValidationError as err:
                self.add_error('phone', err.message if hasattr(err, 'message') else str(err))
        if gstin and not COMPANY_GSTIN_RE.fullmatch(gstin):
            self.add_error(
                'gstin', 'GSTIN must be 15 characters in the correct pattern '
                '(e.g. 27AAAAA0000A1Z5).')
        for field in ('company_name', 'gstin', 'phone', 'email', 'address',
                       'invoice_footer_note'):
            if len(cleaned.get(field, '') or '') > COMPANY_NAME_MAX:
                self.add_error(field, f'Maximum length is {COMPANY_NAME_MAX} characters.')

        return cleaned
