from django import forms
from django.core.validators import FileExtensionValidator
from inventory.models import JewelleryItem
from inventory.forms import PurityChoiceField
from .models import CustomOrder


class CustomOrderForm(forms.ModelForm):
    purity = PurityChoiceField(initial='22K')


    class Meta:
        model = CustomOrder
        fields = [
            'customer', 'category', 'branch', 'design_description', 'reference_image',
            'metal_type', 'purity', 'approx_gross_weight', 'approx_net_weight',
            'making_charge', 'estimated_price', 'customer_budget', 'advance_amount',
            'expected_delivery_date', 'actual_delivery_date', 'notes',
        ]
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'design_description': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4,
                'placeholder': 'Describe the design the customer wants made...'}),
            'reference_image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'metal_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_metal_type'}),
            'purity': forms.Select(attrs={'class': 'form-select', 'id': 'id_purity'}),
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

    def __init__(self, *args, branch=None, **kwargs):
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        if 'branch' in self.fields:
            self.fields['branch'].required = False
            self.fields['branch'].empty_label = "Select Branch (Showroom / Head Office)"
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
        if 'purity' in self.fields:
            purity_field = self.fields['purity']
            choices = getattr(purity_field, 'choices', None)
            if choices is None and hasattr(purity_field, 'widget'):
                choices = getattr(purity_field.widget, 'choices', None)
            if choices:
                try:
                    choice_keys = [c[0] for c in choices]
                    curr_purity = getattr(self.instance, 'purity', None) if self.instance else None
                    if curr_purity and curr_purity not in choice_keys:
                        new_choices = list(choices) + [(curr_purity, curr_purity)]
                        if hasattr(purity_field, 'choices'):
                            purity_field.choices = new_choices
                        if hasattr(purity_field, 'widget') and hasattr(purity_field.widget, 'choices'):
                            purity_field.widget.choices = new_choices
                except Exception:
                    pass
        self.fields['reference_image'].validators.append(
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif', 'pdf']))
        self.fields['reference_image'].help_text = (
            'Reference photo/design brought by the customer (JPG, PNG, GIF or PDF).')
        if self.tenant:
            from customers.models import Customer
            from inventory.models import Category
            self.fields['customer'].queryset = Customer.objects.filter(tenant=self.tenant)
            self.fields['category'].queryset = Category.objects.filter(tenant=self.tenant)

    def clean_purity(self):
        val = (self.cleaned_data.get('purity') or '').strip()
        if val.lower() == '22k':
            return '22K'
        if val.lower() == '24k':
            return '24K'
        if val.lower() == '18k':
            return '18K'
        if val.lower() == '14k':
            return '14K'
        return val or '22K'

    def clean_customer(self):
        customer = self.cleaned_data.get('customer')
        if customer and self.tenant and customer.tenant_id != self.tenant.id:
            raise forms.ValidationError("Invalid customer for this store.")
        return customer

    def clean_category(self):
        category = self.cleaned_data.get('category')
        if category and self.tenant and category.tenant_id != self.tenant.id:
            raise forms.ValidationError("Invalid category for this store.")
        return category

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.tenant and not instance.tenant_id:
            instance.tenant = self.tenant
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class CustomOrderStatusForm(forms.Form):
    """Status-only transition form used on the order detail page."""
    status = forms.ChoiceField(
        choices=CustomOrder.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )