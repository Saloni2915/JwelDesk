"""
super_admin/forms_support.py
----------------------------
Forms for JewelDesk Customer Support, AI Chatbot ticket creation,
and ticket message replies.
"""

import os
from django import forms
from django.core.exceptions import ValidationError
from .models import PlatformSupportTicket, PlatformTicketMessage

ALLOWED_ATTACHMENT_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.pdf', '.txt', '.csv'}
MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def validate_support_attachment(file_obj):
    """Ensure attached file is an acceptable format and does not exceed size limits."""
    if not file_obj:
        return
    if file_obj.size > MAX_ATTACHMENT_SIZE_BYTES:
        raise ValidationError("Attachment exceeds the maximum allowed size of 10 MB.")
    ext = os.path.splitext(file_obj.name)[1].lower()
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '{ext}'. Allowed types: JPG, PNG, WEBP, PDF, TXT, CSV."
        )


class CustomerSupportTicketForm(forms.ModelForm):
    """Ticket creation form used by authenticated showroom business users."""

    attachment = forms.FileField(
        required=False,
        validators=[validate_support_attachment],
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.jpg,.jpeg,.png,.webp,.pdf,.txt,.csv'})
    )

    class Meta:
        model = PlatformSupportTicket
        fields = ['subject', 'category', 'priority', 'description', 'attachment']
        widgets = {
            'subject': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Sales invoice printing issue or GST rounding question',
                'maxlength': '200'
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Please describe what happened, steps you took, or any error messages shown...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit customer choices to user-friendly priorities
        self.fields['priority'].choices = [
            (PlatformSupportTicket.PRIORITY_LOW, 'Low - General inquiry or minor suggestion'),
            (PlatformSupportTicket.PRIORITY_MEDIUM, 'Medium - Standard business question or issue'),
            (PlatformSupportTicket.PRIORITY_HIGH, 'High - Affecting daily billing, stock, or operations'),
        ]
        self.fields['priority'].initial = PlatformSupportTicket.PRIORITY_MEDIUM


class CustomerTicketReplyForm(forms.ModelForm):
    """Form for customer to reply to an ongoing ticket."""

    attachment = forms.FileField(
        required=False,
        validators=[validate_support_attachment],
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.jpg,.jpeg,.png,.webp,.pdf,.txt,.csv'})
    )

    class Meta:
        model = PlatformTicketMessage
        fields = ['message', 'attachment']
        widgets = {
            'message': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Type your reply or additional information for the support team...'
            }),
        }


class StaffTicketReplyForm(forms.ModelForm):
    """Form for Super Admin / Staff to reply to customer or add private internal notes."""

    attachment = forms.FileField(
        required=False,
        validators=[validate_support_attachment],
        widget=forms.FileInput(attrs={'class': 'form-control sa-input', 'accept': '.jpg,.jpeg,.png,.webp,.pdf,.txt,.csv'})
    )

    class Meta:
        model = PlatformTicketMessage
        fields = ['message', 'is_internal', 'attachment']
        widgets = {
            'message': forms.Textarea(attrs={
                'class': 'form-control sa-input',
                'rows': 3,
                'placeholder': 'Type your message to customer, or check "Internal note" to keep private to staff...'
            }),
            'is_internal': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
