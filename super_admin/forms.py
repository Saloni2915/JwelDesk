"""
super_admin/forms.py
---------------------
Form definitions for the JewelDesk Super Admin Platform.
Includes Lead & Demo management, Public Demo Request validation with honeypot,
and Platform Support Ticket management.
"""

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import PlatformDemoLead, PlatformSupportTicket, TenantSubscription

User = get_user_model()


class PlatformDemoLeadForm(forms.ModelForm):
    """Admin form for creating and updating prospective showroom demo leads."""

    class Meta:
        model = PlatformDemoLead
        fields = [
            'lead_name',
            'contact_name',
            'email',
            'phone',
            'city',
            'business_type',
            'business_size',
            'source',
            'requested_datetime',
            'meeting_mode',
            'meeting_link',
            'assigned_staff',
            'status',
            'follow_up_date',
            'next_action',
            'notes',
        ]
        widgets = {
            'lead_name': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Mahalaxmi Jewellers'}),
            'contact_name': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Ramesh Soni'}),
            'email': forms.EmailInput(attrs={'class': 'form-control sa-input', 'placeholder': 'owner@jewellers.com'}),
            'phone': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': '+91 98765 43210'}),
            'city': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Mumbai, Jaipur, Rajkot'}),
            'business_type': forms.Select(attrs={'class': 'form-select sa-input'}),
            'business_size': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. 2 Counters, 5 Staff'}),
            'source': forms.Select(attrs={'class': 'form-select sa-input'}),
            'requested_datetime': forms.DateTimeInput(attrs={'class': 'form-control sa-input', 'type': 'datetime-local'}),
            'meeting_mode': forms.Select(attrs={'class': 'form-select sa-input'}),
            'meeting_link': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'https://meet.google.com/xyz or showroom address'}),
            'assigned_staff': forms.Select(attrs={'class': 'form-select sa-input'}),
            'status': forms.Select(attrs={'class': 'form-select sa-input'}),
            'follow_up_date': forms.DateInput(attrs={'class': 'form-control sa-input', 'type': 'date'}),
            'next_action': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': 'e.g. Send Core Plan Proposal'}),
            'notes': forms.Textarea(attrs={'class': 'form-control sa-input', 'rows': 4, 'placeholder': 'Discussion summary, specific showroom requirements, timeline...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate assigned staff with superusers and platform staff
        self.fields['assigned_staff'].queryset = User.objects.filter(is_superuser=True) | User.objects.filter(is_staff=True)
        self.fields['assigned_staff'].required = False
        self.fields['email'].required = False


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
            'contact_phone': forms.TextInput(attrs={'class': 'form-control sa-input', 'placeholder': '+91 98765 43210'}),
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
