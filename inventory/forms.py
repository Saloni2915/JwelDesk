from django import forms
from .models import JewelleryItem, Category, StockMovement


class JewelleryItemForm(forms.ModelForm):
    class Meta:
        model = JewelleryItem
        fields = [
            'tag_number', 'item_code', 'design_code', 'name', 'category', 'metal_type', 'purity',
            'huid', 'huid_status', 'hallmark_status', 'hallmark_details',
            'gross_weight', 'stone_weight', 'net_weight', 'making_charge', 'selling_price', 'status'
        ]
        widgets = {
            'tag_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Auto-assigned if left blank (e.g. JWL-000001)'}),
            'item_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Unique Piece ID, e.g. GLD-RN-001-A'}),
            'design_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Design / Model Code, e.g. DSN-RN-001'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 22K Gold Solitaire Ring'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'metal_type': forms.Select(attrs={'class': 'form-select'}),
            'purity': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 22K (916), 18K, 925'}),
            'huid': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '6-char alphanumeric, e.g. AB1234', 'maxlength': 6}),
            'huid_status': forms.Select(attrs={'class': 'form-select'}),
            'hallmark_status': forms.Select(attrs={'class': 'form-select'}),
            'hallmark_details': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Center name, assay notes, or certification ID'}),
            'gross_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000'}),
            'stone_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000'}),
            'net_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': 'Auto = Gross - Stone'}),
            'making_charge': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'selling_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tag_number'].required = False
        self.fields['design_code'].required = False
        self.fields['stone_weight'].required = False
        self.fields['net_weight'].required = False
        self.fields['making_charge'].required = False
        self.fields['huid'].required = False
        self.fields['hallmark_details'].required = False
        # New Phase-1 dropdowns default to 'Not Applicable' so legacy POSTs
        # (and old tests) without these keys still validate.
        for fname, default in (('huid_status', 'Not Applicable'),
                               ('hallmark_status', 'Not Applicable')):
            field = self.fields.get(fname)
            if field is not None:
                field.required = False
                if self.instance is not None and self.instance.pk:
                    field.initial = getattr(self.instance, fname)
                else:
                    field.initial = self.initial.get(fname, default)
                    if not self.is_bound:
                        self.initial.setdefault(fname, default)

    def clean_tag_number(self):
        tag = self.cleaned_data.get('tag_number', '')
        if tag:
            tag = tag.strip()
            qs = JewelleryItem.objects.filter(tag_number__iexact=tag)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("This tag number is already assigned to another item.")
        else:
            tag = ''
        return tag

    def clean_huid(self):
        huid = self.cleaned_data.get('huid', '')
        if huid:
            huid = huid.strip().upper()
            if len(huid) != 6 or not huid.isalnum():
                raise forms.ValidationError("HUID must be exactly 6 alphanumeric characters.")
            qs = JewelleryItem.objects.filter(huid=huid)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("This HUID is already assigned to another item.")
        else:
            huid = ''
        return huid

    def clean_making_charge(self):
        mc = self.cleaned_data.get('making_charge')
        if mc is None:
            return 0.00
        return mc

    def clean(self):
        cleaned_data = super().clean()
        gross = cleaned_data.get('gross_weight')
        stone = cleaned_data.get('stone_weight')
        if stone is None:
            stone = 0
            cleaned_data['stone_weight'] = stone
        net = cleaned_data.get('net_weight')

        if gross is not None:
            if net is None:
                # Will be automatically calculated on save/clean
                pass
            else:
                if net > gross:
                    self.add_error('net_weight', 'Net weight cannot be greater than gross weight.')
                if (net + stone) > gross:
                    self.add_error('stone_weight', 'Combined net weight and stone weight cannot exceed gross weight.')
        return cleaned_data


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Rings'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional description...'}),
        }


class StockAdjustmentForm(forms.Form):
    """
    Controlled stock adjustment (increase / decrease / physical count).

    The form only collects and validates the user's intent; the actual stock
    change is applied by ``inventory.stock.apply_stock_change`` so that the
    audit trail and the negative-stock guard are always applied.
    """

    INCREASE = 'increase'
    DECREASE = 'decrease'
    SET_EXACT = 'set'

    ADJUSTMENT_TYPES = [
        (INCREASE, 'Stock increase - new stock received / customer return'),
        (DECREASE, 'Stock decrease - damaged, lost or corrected out'),
        (SET_EXACT, 'Set exact stock count - physical stock take'),
    ]

    DEFAULT_REASONS = {
        INCREASE: 'New Stock Received',
        DECREASE: 'Manual Adjustment',
        SET_EXACT: 'Stock Correction',
    }

    adjustment_type = forms.ChoiceField(
        choices=ADJUSTMENT_TYPES,
        initial=INCREASE,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    quantity = forms.IntegerField(
        required=False,
        min_value=1,
        initial=1,
        label='Number of pieces',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'step': 1}),
        help_text='How many pieces to add or remove.',
    )
    new_stock = forms.IntegerField(
        required=False,
        min_value=0,
        label='Counted stock',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': 1}),
        help_text='The number of pieces you physically counted.',
    )
    reason = forms.ChoiceField(
        choices=[('', 'Select a reason...')] + list(StockMovement.REASON_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Shown in the stock movement history.',
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'rows': 3,
            'placeholder': 'Optional details, e.g. supplier invoice no., damage description...',
        }),
    )

    def __init__(self, *args, item=None, **kwargs):
        self.item = item
        super().__init__(*args, **kwargs)
        if item is not None:
            self.fields['new_stock'].initial = item.quantity

    def clean(self):
        cleaned = super().clean()
        adjustment_type = cleaned.get('adjustment_type')

        if adjustment_type in (self.INCREASE, self.DECREASE):
            if cleaned.get('quantity') is None:
                self.add_error('quantity', 'Enter the number of pieces to add or remove.')
        elif adjustment_type == self.SET_EXACT and self.item is not None:
            target = cleaned.get('new_stock')
            if target is None:
                self.add_error('new_stock', 'Enter the counted number of pieces.')
            elif target == self.item.quantity:
                self.add_error(
                    'new_stock',
                    f'Stock is already {target} piece(s) - nothing to adjust.')

        return cleaned

    def stock_change(self):
        """
        Translate the validated form into a `(change, movement_type, reason)`
        triple for `inventory.stock.apply_stock_change`.
        """
        adjustment_type = self.cleaned_data['adjustment_type']
        reason = self.cleaned_data.get('reason') or self.DEFAULT_REASONS[adjustment_type]

        if adjustment_type == self.INCREASE:
            return self.cleaned_data['quantity'], StockMovement.ADDITION, reason
        if adjustment_type == self.DECREASE:
            return -self.cleaned_data['quantity'], StockMovement.REDUCTION, reason
        return (self.cleaned_data['new_stock'] - self.item.quantity,
                StockMovement.ADJUSTMENT, reason)

