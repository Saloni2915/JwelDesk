import os
from decimal import Decimal, ROUND_HALF_UP
from django import forms
from .models import JewelleryItem, Category, StockMovement


class SanitizedDecimalField(forms.DecimalField):
    """
    DecimalField that automatically rounds/quantizes input with extra decimal
    places (e.g. 0.50000 -> 0.50, 0.002 -> 0.00) instead of failing validation.
    Also supports default_zero=True to return Decimal('0.00') / Decimal('0.000')
    when the field is left blank.
    """
    def __init__(self, *args, default_zero=False, **kwargs):
        self.default_zero = default_zero
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        val = super().to_python(value)
        if val is None and self.default_zero and not self.required:
            if self.decimal_places == 3:
                val = Decimal('0.000')
            else:
                val = Decimal('0.00')
        if val is not None and self.decimal_places is not None:
            val = val.quantize(Decimal(10) ** -self.decimal_places, rounding=ROUND_HALF_UP)
        return val


class PurityChoiceField(forms.CharField):
    """
    Form field for Purity that renders as a <select> dropdown with standard
    jewellery purities while accepting custom / legacy strings gracefully.
    Exposes a .choices property that delegates to self.widget.choices.
    """
    def __init__(self, *args, **kwargs):
        choices = kwargs.pop('choices', JewelleryItem.PURITY_CHOICES)
        widget_attrs = kwargs.pop('widget_attrs', None) or {'class': 'form-select', 'id': 'id_purity'}
        kwargs.setdefault('widget', forms.Select(attrs=widget_attrs, choices=choices))
        kwargs.setdefault('initial', '22K')
        super().__init__(*args, **kwargs)
        self._choices = list(choices)

    @property
    def choices(self):
        if hasattr(self, 'widget') and hasattr(self.widget, 'choices'):
            return self.widget.choices
        return self._choices

    @choices.setter
    def choices(self, value):
        self._choices = list(value)
        if hasattr(self, 'widget') and hasattr(self.widget, 'choices'):
            self.widget.choices = self._choices

    def clean(self, value):
        val = super().clean(value)
        if val:
            val_str = str(val).strip()
            mapping = {
                '24k': '24K',
                '22k': '22K',
                '20k': '20K',
                '18k': '18K',
                '14k': '14K',
                '10k': '10K',
                '9k': '9K',
            }
            return mapping.get(val_str.lower(), val_str)
        return val


class JewelleryItemForm(forms.ModelForm):
    making_charge = SanitizedDecimalField(
        max_digits=10, decimal_places=2, required=False, default_zero=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}))
    wastage_percent = SanitizedDecimalField(
        max_digits=5, decimal_places=2, required=False, default_zero=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}))
    stone_charges = SanitizedDecimalField(
        max_digits=10, decimal_places=2, required=False, default_zero=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}))
    other_charges = SanitizedDecimalField(
        max_digits=10, decimal_places=2, required=False, default_zero=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}))
    selling_price = SanitizedDecimalField(
        max_digits=12, decimal_places=2, required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}))
    gross_weight = SanitizedDecimalField(
        max_digits=10, decimal_places=3, required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000'}))
    stone_weight = SanitizedDecimalField(
        max_digits=10, decimal_places=3, required=False, default_zero=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': '0.000'}))
    net_weight = SanitizedDecimalField(
        max_digits=10, decimal_places=3, required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001', 'placeholder': 'Auto = Gross - Stone'}))
    quantity = forms.IntegerField(
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1', 'placeholder': '1'}))
    image = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            'id': 'id_jewellery_image',
            'class': 'd-none',
            'accept': 'image/jpeg,image/png,image/webp,image/jpg',
        }),
        help_text="Upload a photograph of the jewellery item (JPEG, PNG, WEBP, max 10MB).",
    )
    purity = PurityChoiceField(initial='22K')

    class Meta:
        model = JewelleryItem
        fields = [
            'tag_number', 'item_code', 'design_code', 'name', 'category', 'metal_type', 'purity',
            'huid', 'huid_status', 'hallmark_status', 'hallmark_details',
            'gross_weight', 'stone_weight', 'net_weight',
            'making_charge_type', 'making_charge', 'wastage_percent', 'stone_charges', 'other_charges',
            'selling_price', 'quantity', 'status'
        ]
        widgets = {
            'tag_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Auto-assigned if left blank (e.g. JWL-000001)'}),
            'item_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Unique Piece ID, e.g. GLD-RN-001-A'}),
            'design_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Design / Model Code, e.g. DSN-RN-001'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 22K Gold Solitaire Ring'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'metal_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_metal_type'}),
            'purity': forms.Select(attrs={'class': 'form-select', 'id': 'id_purity'}),
            'huid': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '6-char alphanumeric, e.g. AB1234', 'maxlength': 6}),
            'huid_status': forms.Select(attrs={'class': 'form-select'}),
            'hallmark_status': forms.Select(attrs={'class': 'form-select'}),
            'hallmark_details': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Center name, assay notes, or certification ID'}),
            'making_charge_type': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '1', 'placeholder': '1'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        self.tenant = tenant or (kwargs.get('instance').tenant if kwargs.get('instance') else None)
        super().__init__(*args, **kwargs)
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
        if self.tenant:
            self.fields['category'].queryset = Category.objects.filter(tenant=self.tenant)
        if self.instance and self.instance.pk:
            if self.instance.quantity is not None:
                self.fields['quantity'].initial = self.instance.quantity
        else:
            self.fields['quantity'].initial = self.initial.get('quantity', 1)
        self.fields['tag_number'].required = False
        self.fields['design_code'].required = False
        self.fields['stone_weight'].required = False
        self.fields['net_weight'].required = False
        self.fields['making_charge_type'].required = False
        self.fields['making_charge'].required = False
        self.fields['wastage_percent'].required = False
        self.fields['stone_charges'].required = False
        self.fields['other_charges'].required = False
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

    def clean_tag_number(self):
        tag = self.cleaned_data.get('tag_number', '')
        if tag:
            tag = tag.strip()
            qs = JewelleryItem.objects.filter(tag_number__iexact=tag)
            if self.tenant:
                qs = qs.filter(tenant=self.tenant)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f"Tag number '{tag}' is already assigned to another item in your showroom. "
                    "Please enter a unique tag or leave blank to auto-generate."
                )
        else:
            tag = ''
        return tag

    def clean_item_code(self):
        code = self.cleaned_data.get('item_code', '')
        if code:
            code = code.strip()
            qs = JewelleryItem.objects.filter(item_code__iexact=code)
            if self.tenant:
                qs = qs.filter(tenant=self.tenant)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f"Piece ID / Item Code '{code}' is already assigned to another piece in your showroom. "
                    "Each physical piece must have a unique Piece ID."
                )
        return code

    def clean_huid(self):
        huid = self.cleaned_data.get('huid', '')
        if huid:
            huid = huid.strip().upper()
            if len(huid) != 6 or not huid.isalnum():
                raise forms.ValidationError("HUID must be exactly 6 alphanumeric characters.")
            qs = JewelleryItem.objects.filter(huid=huid)
            if self.tenant:
                qs = qs.filter(tenant=self.tenant)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("This HUID is already assigned to another item in your showroom.")
        else:
            huid = ''
        return huid

    def clean_making_charge(self):
        mc = self.cleaned_data.get('making_charge')
        if mc is None:
            return Decimal('0.00')
        return mc

    def clean_wastage_percent(self):
        val = self.cleaned_data.get('wastage_percent')
        if val is None:
            return Decimal('0.00')
        return val

    def clean_stone_charges(self):
        val = self.cleaned_data.get('stone_charges')
        if val is None:
            return Decimal('0.00')
        return val

    def clean_other_charges(self):
        val = self.cleaned_data.get('other_charges')
        if val is None:
            return Decimal('0.00')
        return val

    def clean_stone_weight(self):
        val = self.cleaned_data.get('stone_weight')
        if val is None:
            return Decimal('0.000')
        return val

    def clean_quantity(self):
        qty = self.cleaned_data.get('quantity')
        if qty is None:
            if self.instance and self.instance.pk and self.instance.quantity is not None:
                return self.instance.quantity
            return 1
        return max(0, qty)

    def clean_image(self):
        img = self.cleaned_data.get('image')
        if img:
            if hasattr(img, 'size') and img.size > 10 * 1024 * 1024:
                raise forms.ValidationError("Photograph file size must not exceed 10 MB.")
            ext = os.path.splitext(getattr(img, 'name', '') or '')[1].lower()
            if ext and ext not in ('.jpg', '.jpeg', '.png', '.webp'):
                raise forms.ValidationError(f"Unsupported image format '{ext}'. Allowed: JPG, PNG, WEBP.")
        return img

    def clean(self):
        cleaned_data = super().clean()
        gross = cleaned_data.get('gross_weight')
        stone = cleaned_data.get('stone_weight')
        if stone is None:
            stone = Decimal('0.000')
            cleaned_data['stone_weight'] = stone

        for fld in ('making_charge', 'wastage_percent', 'stone_charges', 'other_charges'):
            if cleaned_data.get(fld) is None:
                cleaned_data[fld] = Decimal('0.00')

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

    def __init__(self, *args, tenant=None, **kwargs):
        self.tenant = tenant or (kwargs.get('instance').tenant if kwargs.get('instance') else None)
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        qs = Category.objects.filter(name__iexact=name)
        if self.tenant:
            qs = qs.filter(tenant=self.tenant)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Category '{name}' already exists in your showroom.")
        return name


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


class MetalRateForm(forms.ModelForm):
    """Form to update single metal board rate."""
    class Meta:
        from .models import MetalRate
        model = MetalRate
        fields = ['rate_per_gram', 'source']
        widgets = {
            'rate_per_gram': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01', 'placeholder': '0.00'}),
            'source': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. IBJA / Shop Board Rate'}),
        }


class MetalRatesUpdateForm(forms.Form):
    """Form to update all daily shop rates simultaneously (Gold 24K, Silver 999, Platinum 950)."""
    gold_rate_24k = forms.DecimalField(
        label='24K Pure Gold Rate (₹/g)',
        max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg fw-bold', 'step': '0.01', 'min': '1.00', 'placeholder': '7500.00'})
    )
    silver_rate_999 = forms.DecimalField(
        label='999 Fine Silver Rate (₹/g)',
        max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg fw-bold', 'step': '0.01', 'min': '0.10', 'placeholder': '95.00'})
    )
    platinum_rate = forms.DecimalField(
        label='Platinum Pt950 Rate (₹/g)',
        max_digits=10, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '1.00', 'placeholder': '3200.00'})
    )
    source = forms.CharField(
        label='Rate Source / Reference',
        max_length=50, required=False, initial='Shop Board Rate',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. IBJA, Mumbai Bullion, Shop Opening Rate'})
    )


