"""
super_admin/forms.py
---------------------
Form definitions for the JewelDesk Super Admin Platform.
Includes Lead & Demo management, Public Demo Request validation with honeypot,
and Platform Support Ticket management.
"""

from decimal import Decimal
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import clean_10_digit_phone, validate_proper_email

from .models import (
    CouponBatchItem,
    CouponDesignTemplate,
    CouponPrintBatch,
    PlatformDemoLead,
    PlatformLeadNote,
    PlatformSupportTicket,
    TenantSubscription,
)
from .coupon_engine import (
    get_builtin_template_markup,
    sanitize_coupon_css,
    sanitize_coupon_html,
)

User = get_user_model()


class PlatformDemoLeadForm(forms.ModelForm):
    """Admin form for creating and updating prospective showroom demo leads."""

    class Meta:
        model = PlatformDemoLead
        fields = [
            'lead_name',
            'contact_name',
            'phone',
            'email',
            'city',
            'address',
            'source',
            'status',
            'notes',
            'follow_up_date',
            'business_type',
            'business_size',
            'assigned_staff',
            'requested_datetime',
            'meeting_mode',
            'meeting_link',
            'next_action',
        ]
        labels = {
            'contact_name': 'Contact Person Name',
            'lead_name': 'Shop / Business Name',
            'phone': 'Phone Number',
            'email': 'Email Address',
            'city': 'City',
            'address': 'Full Address',
            'source': 'Lead Source',
            'status': 'Lead Status',
            'notes': 'Notes / Requirements',
            'follow_up_date': 'Follow-up Date',
            'assigned_staff': 'Assigned Person',
            'business_type': 'Business Type',
            'business_size': 'Showroom Size / Counters',
        }
        widgets = {
            'contact_name': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Ramesh Soni'}),
            'lead_name': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Mahalaxmi Jewellers'}),
            'phone': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. 9876543210'}),
            'email': forms.EmailInput(attrs={'class': 'form-control sa-input', 'placeholder': 'owner@jewellers.com'}),
            'city': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Mumbai, Jaipur, Rajkot'}),
            'address': forms.Textarea(attrs={'class': 'form-control sa-input', 'rows': 2, 'placeholder': 'Showroom street address / market...'}),
            'source': forms.Select(attrs={'class': 'form-select sa-input'}),
            'status': forms.Select(attrs={'class': 'form-select sa-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control sa-input', 'rows': 3, 'placeholder': 'Specific showroom requirements, software needs, timeline...'}),
            'follow_up_date': forms.DateInput(attrs={'class': 'form-control sa-input', 'type': 'date'}),
            'business_type': forms.Select(attrs={'class': 'form-select sa-input'}),
            'business_size': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. 2 Counters, 5 Staff'}),
            'assigned_staff': forms.Select(attrs={'class': 'form-select sa-input'}),
            'requested_datetime': forms.DateTimeInput(attrs={'class': 'form-control sa-input', 'type': 'datetime-local'}),
            'meeting_mode': forms.Select(attrs={'class': 'form-select sa-input'}),
            'meeting_link': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'https://meet.google.com/xyz or showroom address'}),
            'next_action': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Call regarding inventory module demo'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate assigned staff with superusers and platform staff
        self.fields['assigned_staff'].queryset = User.objects.filter(is_superuser=True) | User.objects.filter(is_staff=True)
        self.fields['assigned_staff'].required = False
        self.fields['email'].required = False
        self.fields['contact_name'].required = True
        self.fields['lead_name'].required = True
        self.fields['meeting_mode'].required = False
        if not self.initial.get('meeting_mode'):
            self.fields['meeting_mode'].initial = PlatformDemoLead.MODE_ONLINE

    def clean_meeting_mode(self):
        mode = self.cleaned_data.get('meeting_mode')
        return mode or PlatformDemoLead.MODE_ONLINE

    def clean_phone(self):
        phone = (self.cleaned_data.get('phone') or '').strip()
        return clean_10_digit_phone(phone, field_label='Phone number', required=True)

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email:
            return validate_proper_email(email, field_label='Email address', required=False)
        return ''


class PlatformLeadNoteForm(forms.ModelForm):
    """Form for recording a new follow-up note on a prospective lead."""

    class Meta:
        model = PlatformLeadNote
        fields = ['note', 'status_at_note', 'follow_up_date']
        labels = {
            'note': 'Follow-up Notes / Discussion Details',
            'status_at_note': 'Update Lead Status',
            'follow_up_date': 'Next Follow-up Date',
        }
        widgets = {
            'note': forms.Textarea(attrs={
                'class': 'form-control sa-input',
                'rows': 3,
                'placeholder': 'Enter discussion summary, customer questions, interest level, requirements...',
                'required': True,
            }),
            'status_at_note': forms.Select(attrs={'class': 'form-select sa-input'}),
            'follow_up_date': forms.DateInput(attrs={'class': 'form-control sa-input', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        lead_status = kwargs.pop('lead_status', None)
        super().__init__(*args, **kwargs)
        self.fields['status_at_note'].choices = [('', 'Keep Current Status')] + list(PlatformDemoLead.STATUS_CHOICES)
        if lead_status:
            self.fields['status_at_note'].initial = lead_status
        self.fields['status_at_note'].required = False
        self.fields['follow_up_date'].required = False



class DemoMeetingScheduleForm(forms.Form):
    """Action form to schedule, reschedule, or complete a demo meeting."""

    ACTION_SCHEDULE = 'schedule'
    ACTION_RESCHEDULE = 'reschedule'
    ACTION_COMPLETE = 'complete'
    ACTION_CANCEL = 'cancel'

    ACTION_CHOICES = [
        (ACTION_SCHEDULE, 'Schedule Demo Meeting'),
        (ACTION_RESCHEDULE, 'Reschedule Meeting'),
        (ACTION_COMPLETE, 'Mark Demo as Completed'),
        (ACTION_CANCEL, 'Cancel Meeting'),
    ]

    action_type = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select sa-input'})
    )
    meeting_datetime = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'class': 'form-control sa-input', 'type': 'datetime-local'})
    )
    meeting_mode = forms.ChoiceField(
        choices=PlatformDemoLead.MODE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select sa-input'})
    )
    meeting_link = forms.CharField(
        max_length=300,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'Google Meet link or showroom location'})
    )
    assigned_staff = forms.ModelChoiceField(
        queryset=User.objects.filter(is_superuser=True) | User.objects.filter(is_staff=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select sa-input'})
    )
    follow_up_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control sa-input', 'type': 'date'})
    )
    next_action = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Follow up on Tuesday with quote'})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control sa-input', 'rows': 3, 'placeholder': 'Meeting outcome, client reaction, key questions...'})
    )


class PublicDemoRequestForm(forms.Form):
    """
    Public demo request and enquiry form for prospective customers on the landing page.
    Includes invisible honeypot field to block automated bot submissions.
    """

    showroom_name = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={'class': 'jd-input-text', 'placeholder': 'e.g. Shree Jewellers, Mumbai'})
    )
    contact_person = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'jd-input-text', 'placeholder': 'e.g. Rajesh Soni'})
    )
    phone = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'jd-input-text', 'placeholder': '+91 98765 43210'})
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'jd-input-text', 'placeholder': 'rajesh@jewellers.com'})
    )
    city = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'jd-input-text', 'placeholder': 'e.g. Mumbai'})
    )
    business_type = forms.ChoiceField(
        choices=[
            ('RETAIL', 'Retail Showroom'),
            ('WHOLESALE', 'Wholesaler / Supplier'),
            ('BOTH', 'Retail & Wholesale'),
            ('OTHER', 'Other'),
        ],
        initial='RETAIL',
        required=False,
        widget=forms.Select(attrs={'class': 'jd-input-text'})
    )
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'jd-textarea', 'rows': 3, 'placeholder': 'Tell us about your showroom requirements...'})
    )

    # Honeypot spam trap: must be empty on legitimate submissions
    website_hp = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'style': 'display:none !important;', 'tabindex': '-1', 'autocomplete': 'off'})
    )

    def clean_phone(self):
        phone = (self.cleaned_data.get('phone') or '').strip()
        return clean_10_digit_phone(phone, field_label='Phone number', required=True)

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            return ''
        return validate_proper_email(email, field_label='Email address', required=False)

    def clean(self):
        cleaned_data = super().clean()
        hp = cleaned_data.get('website_hp')
        if hp:
            raise ValidationError("Automated bot submission detected.")
        return cleaned_data


class PlatformSupportTicketForm(forms.ModelForm):
    """Form to record or create a customer support ticket."""

    class Meta:
        model = PlatformSupportTicket
        fields = [
            'tenant',
            'contact_name',
            'contact_email',
            'contact_phone',
            'category',
            'priority',
            'status',
            'subject',
            'description',
            'assigned_to',
            'resolution_notes',
        ]
        widgets = {
            'tenant': forms.Select(attrs={'class': 'form-select sa-input'}),
            'contact_name': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'Contact Name'}),
            'contact_email': forms.EmailInput(attrs={'class': 'form-control sa-input', 'placeholder': 'contact@jewellers.com'}),
            'contact_phone': forms.TextInput(attrs={
                'class': 'form-control sa-input',
                'placeholder': '10-digit contact phone',
                'maxlength': '10',
                'inputmode': 'numeric',
            }),
            'category': forms.Select(attrs={'class': 'form-select sa-input'}),
            'priority': forms.Select(attrs={'class': 'form-select sa-input'}),
            'status': forms.Select(attrs={'class': 'form-select sa-input'}),
            'subject': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'Summary of the issue / requirement'}),
            'description': forms.Textarea(attrs={'class': 'form-control sa-input', 'rows': 4, 'placeholder': 'Full details of the request...'}),
            'assigned_to': forms.Select(attrs={'class': 'form-select sa-input'}),
            'resolution_notes': forms.Textarea(attrs={'class': 'form-control sa-input', 'rows': 3, 'placeholder': 'Actions taken to resolve...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_to'].queryset = User.objects.filter(is_superuser=True) | User.objects.filter(is_staff=True)
        self.fields['tenant'].required = False
        self.fields['assigned_to'].required = False

    def clean_contact_phone(self):
        phone = (self.cleaned_data.get('contact_phone') or '').strip()
        return clean_10_digit_phone(phone, field_label='Contact phone', required=False)

    def clean_contact_email(self):
        email = (self.cleaned_data.get('contact_email') or '').strip().lower()
        if not email:
            return ''
        return validate_proper_email(email, field_label='Contact email', required=False)


# ============================================================================
# Coupon Designer & Print Management Forms
# ============================================================================

class CouponDesignTemplateForm(forms.ModelForm):
    """Form to create and edit ready-made built-in or custom HTML/CSS coupon templates."""

    class Meta:
        model = CouponDesignTemplate
        fields = [
            'name',
            'description',
            'template_type',
            'built_in_style',
            'discount_type',
            'discount_value',
            'offer_title',
            'sample_coupon_code',
            'business_name',
            'business_logo_url',
            'valid_from',
            'valid_until',
            'minimum_purchase',
            'maximum_discount',
            'applicable_categories',
            'terms_and_conditions',
            'show_barcode',
            'show_qr_code',
            'primary_color',
            'background_color',
            'text_color',
            'page_size',
            'orientation',
            'coupon_width_mm',
            'coupon_height_mm',
            'grid_columns',
            'grid_rows',
            'margin_mm',
            'spacing_mm',
            'custom_html',
            'custom_css',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Royal Gold 20% Privilege Voucher'}),
            'description': forms.Textarea(attrs={'class': 'form-control sa-input', 'rows': 2, 'placeholder': 'Campaign context or internal notes'}),
            'template_type': forms.Select(attrs={'class': 'form-select sa-input', 'id': 'id_template_type'}),
            'built_in_style': forms.Select(attrs={'class': 'form-select sa-input', 'id': 'id_built_in_style'}),
            'discount_type': forms.Select(attrs={'class': 'form-select sa-input', 'id': 'id_discount_type'}),
            'discount_value': forms.NumberInput(attrs={'class': 'form-control sa-input', 'step': '0.01', 'id': 'id_discount_value'}),
            'offer_title': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Exclusive Jewellery Privilege Voucher', 'id': 'id_offer_title'}),
            'sample_coupon_code': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. ROYAL-GOLD20', 'id': 'id_sample_coupon_code'}),
            'business_name': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. JewelDesk Fine Atelier', 'id': 'id_business_name'}),
            'business_logo_url': forms.URLInput(attrs={'class': 'form-control sa-input', 'placeholder': 'https://example.com/logo.png'}),
            'valid_from': forms.DateInput(attrs={'class': 'form-control sa-input', 'type': 'date'}),
            'valid_until': forms.DateInput(attrs={'class': 'form-control sa-input', 'type': 'date', 'id': 'id_valid_until'}),
            'minimum_purchase': forms.NumberInput(attrs={'class': 'form-control sa-input', 'step': '0.01', 'placeholder': '10000.00'}),
            'maximum_discount': forms.NumberInput(attrs={'class': 'form-control sa-input', 'step': '0.01', 'placeholder': 'Optional cap'}),
            'applicable_categories': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Gold, Diamond & Polki Jewellery'}),
            'terms_and_conditions': forms.Textarea(attrs={'class': 'form-control sa-input', 'rows': 4, 'id': 'id_terms_and_conditions'}),
            'show_barcode': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_show_barcode'}),
            'show_qr_code': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_show_qr_code'}),
            'primary_color': forms.TextInput(attrs={'class': 'form-control sa-input', 'type': 'color', 'id': 'id_primary_color'}),
            'background_color': forms.TextInput(attrs={'class': 'form-control sa-input', 'type': 'color', 'id': 'id_background_color'}),
            'text_color': forms.TextInput(attrs={'class': 'form-control sa-input', 'type': 'color', 'id': 'id_text_color'}),
            'page_size': forms.Select(attrs={'class': 'form-select sa-input'}),
            'orientation': forms.Select(attrs={'class': 'form-select sa-input'}),
            'coupon_width_mm': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 30, 'max': 300, 'id': 'id_coupon_width_mm'}),
            'coupon_height_mm': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 20, 'max': 300, 'id': 'id_coupon_height_mm'}),
            'grid_columns': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 1, 'max': 6}),
            'grid_rows': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 1, 'max': 10}),
            'margin_mm': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 0, 'max': 50}),
            'spacing_mm': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 0, 'max': 30}),
            'custom_html': forms.Textarea(attrs={'class': 'form-control sa-input font-monospace', 'rows': 14, 'id': 'id_custom_html', 'spellcheck': 'false'}),
            'custom_css': forms.Textarea(attrs={'class': 'form-control sa-input font-monospace', 'rows': 14, 'id': 'id_custom_css', 'spellcheck': 'false'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        ttype = cleaned_data.get('template_type')
        bstyle = cleaned_data.get('built_in_style')
        custom_html = cleaned_data.get('custom_html') or ''
        custom_css = cleaned_data.get('custom_css') or ''
        discount_type = cleaned_data.get('discount_type')
        discount_val = cleaned_data.get('discount_value')

        if discount_val is not None:
            if discount_val < 0:
                self.add_error('discount_value', 'Discount value cannot be negative.')
            if discount_type == CouponDesignTemplate.DISCOUNT_PERCENTAGE and discount_val > 100:
                self.add_error('discount_value', 'Percentage discount cannot exceed 100%.')

        # Custom HTML sanitization and security
        if ttype == CouponDesignTemplate.TYPE_CUSTOM:
            if not custom_html.strip():
                self.add_error('custom_html', 'Custom HTML markup cannot be empty when using Custom Designer.')
            else:
                cleaned_data['custom_html'] = sanitize_coupon_html(custom_html)
                cleaned_data['custom_css'] = sanitize_coupon_css(custom_css)
        elif ttype == CouponDesignTemplate.TYPE_BUILT_IN:
            # If user switches to custom later, pre-seed with built-in markup if currently empty
            if not custom_html.strip() and bstyle:
                preset = get_builtin_template_markup(bstyle)
                cleaned_data['custom_html'] = preset['html']
                cleaned_data['custom_css'] = preset['css']

        # Ensure positive layout dimensions
        width = cleaned_data.get('coupon_width_mm')
        height = cleaned_data.get('coupon_height_mm')
        cols = cleaned_data.get('grid_columns')
        rows = cleaned_data.get('grid_rows')

        if width is not None and width <= 0:
            self.add_error('coupon_width_mm', 'Coupon width must be greater than 0 mm.')
        if height is not None and height <= 0:
            self.add_error('coupon_height_mm', 'Coupon height must be greater than 0 mm.')
        if cols is not None and cols < 1:
            self.add_error('grid_columns', 'Grid columns must be at least 1.')
        if rows is not None and rows < 1:
            self.add_error('grid_rows', 'Grid rows must be at least 1.')

        return cleaned_data


class CouponPrintBatchForm(forms.ModelForm):
    """Form to configure a single coupon or bulk print run from a template."""

    class Meta:
        model = CouponPrintBatch
        fields = [
            'template',
            'name',
            'batch_type',
            'total_quantity',
            'shared_code',
            'code_prefix',
            'code_length',
            'include_serial_numbers',
            'serial_start',
            'offer_title',
            'discount_type',
            'discount_value',
            'valid_from',
            'valid_until',
            'business_name',
            'minimum_purchase',
            'maximum_discount',
            'applicable_categories',
            'terms_and_conditions',
            'grid_columns',
            'grid_rows',
            'margin_mm',
            'spacing_mm',
            'notes',
        ]
        widgets = {
            'template': forms.Select(attrs={'class': 'form-select sa-input', 'id': 'id_batch_template'}),
            'name': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Diwali 2026 VIP Showroom Mailer Batch'}),
            'batch_type': forms.Select(attrs={'class': 'form-select sa-input', 'id': 'id_batch_type'}),
            'total_quantity': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 1, 'max': 500, 'id': 'id_total_quantity'}),
            'shared_code': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. DIWALI-2026', 'id': 'id_shared_code'}),
            'code_prefix': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'JD-', 'id': 'id_code_prefix'}),
            'code_length': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 4, 'max': 16, 'id': 'id_code_length'}),
            'include_serial_numbers': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_include_serial_numbers'}),
            'serial_start': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 1, 'id': 'id_serial_start'}),
            'offer_title': forms.TextInput(attrs={'class': 'form-control sa-input', 'id': 'id_batch_offer_title'}),
            'discount_type': forms.Select(attrs={'class': 'form-select sa-input', 'id': 'id_batch_discount_type'}),
            'discount_value': forms.NumberInput(attrs={'class': 'form-control sa-input', 'step': '0.01', 'id': 'id_batch_discount_value'}),
            'valid_from': forms.DateInput(attrs={'class': 'form-control sa-input', 'type': 'date'}),
            'valid_until': forms.DateInput(attrs={'class': 'form-control sa-input', 'type': 'date'}),
            'business_name': forms.TextInput(attrs={'class': 'form-control sa-input'}),
            'minimum_purchase': forms.NumberInput(attrs={'class': 'form-control sa-input', 'step': '0.01'}),
            'maximum_discount': forms.NumberInput(attrs={'class': 'form-control sa-input', 'step': '0.01'}),
            'applicable_categories': forms.TextInput(attrs={'class': 'form-control sa-input'}),
            'terms_and_conditions': forms.Textarea(attrs={'class': 'form-control sa-input', 'rows': 3}),
            'grid_columns': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 1, 'max': 6}),
            'grid_rows': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 1, 'max': 10}),
            'margin_mm': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 0, 'max': 40}),
            'spacing_mm': forms.NumberInput(attrs={'class': 'form-control sa-input', 'min': 0, 'max': 30}),
            'notes': forms.Textarea(attrs={'class': 'form-control sa-input', 'rows': 2, 'placeholder': 'Internal printing notes (printer paper, tray, counter distribution)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['template'].queryset = CouponDesignTemplate.objects.filter(is_archived=False)
        self.fields['shared_code'].required = False
        self.fields['code_prefix'].required = False
        self.fields['code_length'].required = False
        self.fields['offer_title'].required = False
        self.fields['discount_type'].required = False
        self.fields['discount_value'].required = False
        self.fields['business_name'].required = False
        self.fields['minimum_purchase'].required = False
        self.fields['maximum_discount'].required = False
        self.fields['applicable_categories'].required = False
        self.fields['terms_and_conditions'].required = False
        self.fields['notes'].required = False

    def clean(self):
        cleaned_data = super().clean()
        batch_type = cleaned_data.get('batch_type')
        shared_code = (cleaned_data.get('shared_code') or '').strip()
        template = cleaned_data.get('template')
        qty = cleaned_data.get('total_quantity')

        if not cleaned_data.get('code_length'):
            cleaned_data['code_length'] = 8

        if template:
            if not cleaned_data.get('offer_title'):
                cleaned_data['offer_title'] = template.offer_title
            if not cleaned_data.get('discount_type'):
                cleaned_data['discount_type'] = template.discount_type
            if cleaned_data.get('discount_value') is None:
                cleaned_data['discount_value'] = template.discount_value
            if not cleaned_data.get('business_name'):
                cleaned_data['business_name'] = template.business_name
            if cleaned_data.get('minimum_purchase') is None:
                cleaned_data['minimum_purchase'] = template.minimum_purchase or Decimal('0.00')
            if not cleaned_data.get('applicable_categories'):
                cleaned_data['applicable_categories'] = template.applicable_categories
            if not cleaned_data.get('terms_and_conditions'):
                cleaned_data['terms_and_conditions'] = template.terms_and_conditions
            if cleaned_data.get('grid_columns') is None:
                cleaned_data['grid_columns'] = template.grid_columns
            if cleaned_data.get('grid_rows') is None:
                cleaned_data['grid_rows'] = template.grid_rows
            if cleaned_data.get('margin_mm') is None:
                cleaned_data['margin_mm'] = template.margin_mm
            if cleaned_data.get('spacing_mm') is None:
                cleaned_data['spacing_mm'] = template.spacing_mm

        if qty is not None:
            if qty < 1:
                self.add_error('total_quantity', 'Quantity must be at least 1.')
            elif qty > 500:
                self.add_error('total_quantity', 'Maximum 500 coupons per batch to ensure optimal print performance.')

        if batch_type == CouponPrintBatch.BATCH_IDENTICAL:
            if not shared_code:
                if template and template.sample_coupon_code:
                    cleaned_data['shared_code'] = template.sample_coupon_code
                else:
                    self.add_error('shared_code', 'Please specify the promotional code for identical artwork.')
        elif batch_type == CouponPrintBatch.BATCH_UNIQUE:
            prefix = cleaned_data.get('code_prefix') or ''
            length = cleaned_data.get('code_length') or 8
            if length < 4 or length > 20:
                self.add_error('code_length', 'Code random character length must be between 4 and 20.')

        return cleaned_data

