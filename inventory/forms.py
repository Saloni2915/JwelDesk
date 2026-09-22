from django import forms
from .models import JewelleryItem, Category


class JewelleryItemForm(forms.ModelForm):
    class Meta:
        model = JewelleryItem
        fields = [
            'item_code', 'design_code', 'name', 'category', 'metal_type', 'purity',
            'gross_weight', 'net_weight', 'making_charge', 'selling_price', 'status'
        ]
        widgets = {
            'item_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Unique Piece ID, e.g. GLD-RN-001-A'}),
            'design_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Design / Model Code, e.g. DSN-RN-001'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 22K Gold Solitaire Ring'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'metal_type': forms.Select(attrs={'class': 'form-select'}),
            'purity': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 22K (916), 18K, 925'}),
            'gross_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000'}),
            'net_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000'}),
            'making_charge': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'selling_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        gross = cleaned_data.get('gross_weight')
        net = cleaned_data.get('net_weight')

        if gross is not None and net is not None:
            if net > gross:
                self.add_error('net_weight', 'Net weight cannot be greater than gross weight.')
        return cleaned_data


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Rings'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional description...'}),
        }
