from django import forms
from django.core.validators import FileExtensionValidator
from .models import CustomOrder


class CustomOrderForm(forms.ModelForm):
    class Meta:
        model = CustomOrder
        fields = [
            'customer', 'category', 'design_description', 'reference_image',
            'metal_type', 'purity', 'approx_gross_weight', 'approx_net_weight',
            'making_charge', 'estimated_price', 'customer_budget', 'advance_amount',
            'expected_delivery_date', 'actual_delivery_date', 'notes',
        ]
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'design_description': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4,
                'placeholder': 'Describe the design the customer wants made...'}),
            'reference_image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'metal_type': forms.Select(attrs={'class': 'form-select'}),
            'purity': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 22K, 18K, 925 Silver'}),
            'approx_gross_weight': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.001', 'min': '0', 'placeholder': '0.000'}),
            'approx_net_weight': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.001', 'min': '0', 'placeholder': '0.000'}),
            'making_charge': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '0.00'}),
            'estimated_price': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0.01', 'placeholder': '0.00'}),
            'customer_budget': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': 'Optional'}),
            'advance_amount': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'min': '0', 'placeholder': '0.00'}),
            'expected_delivery_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'actual_delivery_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3, 'placeholder': 'Internal notes (optional)...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reference_image'].validators.append(
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif', 'pdf']))
        self.fields['reference_image'].help_text = (
            'Reference photo/design brought by the customer (JPG, PNG, GIF or PDF).')


class CustomOrderStatusForm(forms.Form):
    """Status-only transition form used on the order detail page."""
    status = forms.ChoiceField(
        choices=CustomOrder.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )