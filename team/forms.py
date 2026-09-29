"""
team/forms.py
-------------
Forms for the Team / Employee Management module.
"""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from django.utils import timezone

from .models import Branch, Employee, EmployeePermission, Role

User = get_user_model()


# ---------------------------------------------------------------------------
# Branch form
# ---------------------------------------------------------------------------

class BranchForm(forms.ModelForm):
    class Meta:
        model  = Branch
        fields = ('name', 'address', 'phone', 'is_active')
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != 'is_active':
                field.widget.attrs.setdefault('class', 'form-control')


# ---------------------------------------------------------------------------
# Employee creation form  (Admin only)
# ---------------------------------------------------------------------------

class EmployeeCreateForm(forms.ModelForm):
    """Combined form: creates a Django User + Employee in one step."""

    # User fields
    username   = forms.CharField(
        max_length=150,
        help_text='Required. 150 chars or fewer. Letters, digits and @/./+/-/_ only.',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )
    password1  = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
        help_text='Minimum 8 characters.',
    )
    password2  = forms.CharField(
        label='Confirm password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )

    class Meta:
        model  = Employee
        fields = (
            'full_name', 'email', 'mobile',
            'department', 'role',
            'joining_date', 'status', 'branches',
        )
        widgets = {
            'joining_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'branches':     forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Apply form-control CSS to all text/select fields
        for name, field in self.fields.items():
            if name not in ('branches', 'password1', 'password2', 'username'):
                widget = field.widget
                if not isinstance(widget, (forms.CheckboxSelectMultiple,
                                           forms.CheckboxInput)):
                    widget.attrs.setdefault('class', 'form-control')
        self.fields['branches'].queryset = Branch.objects.filter(is_active=True)
        self.fields['joining_date'].required = False
        self.fields['joining_date'].initial = timezone.localdate

    # ---- Validation --------------------------------------------------------

    def clean_joining_date(self):
        val = self.cleaned_data.get('joining_date')
        return val or timezone.localdate()

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(
                'A user with this username already exists.')
        return username

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                'A user with this email already exists.')
        if Employee.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                'An employee with this email already exists.')
        return email

    def clean_password2(self):
        p1 = self.cleaned_data.get('password1', '')
        p2 = self.cleaned_data.get('password2', '')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError('Passwords do not match.')
        if len(p1) < 8:
            raise forms.ValidationError(
                'Password must be at least 8 characters.')
        return p2

    # ---- Save (transactional) ----------------------------------------------

    def save(self, commit=True, created_by=None):
        """Create User + Employee atomically; apply role defaults."""
        from django.db import transaction

        with transaction.atomic():
            # 1. Create User
            user = User.objects.create_user(
                username=self.cleaned_data['username'],
                password=self.cleaned_data['password1'],
                email=self.cleaned_data['email'],
                first_name=self.cleaned_data.get('full_name', '').split()[0],
            )
            user.is_active = (
                self.cleaned_data.get('status') == Employee.STATUS_ACTIVE
            )
            user.is_staff = True
            user.save(update_fields=['is_active', 'is_staff'])

            # 2. Create Employee
            employee = super().save(commit=False)
            employee.user       = user
            employee.email      = self.cleaned_data['email']
            employee.full_name  = self.cleaned_data['full_name']
            if created_by:
                employee.created_by = created_by
            employee.save()
            self.save_m2m()   # branches

            # 3. Apply default permissions for the chosen role
            employee.apply_default_permissions()

        return employee


# ---------------------------------------------------------------------------
# Employee edit form  (does NOT touch username/password)
# ---------------------------------------------------------------------------

class EmployeeEditForm(forms.ModelForm):

    class Meta:
        model  = Employee
        fields = (
            'full_name', 'email', 'mobile',
            'department', 'role',
            'joining_date', 'status', 'branches',
        )
        widgets = {
            'joining_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'branches':     forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in ('branches',):
                widget = field.widget
                if not isinstance(widget, forms.CheckboxSelectMultiple):
                    widget.attrs.setdefault('class', 'form-control')
        self.fields['branches'].queryset = Branch.objects.filter(is_active=True)
        self.fields['joining_date'].required = False

    def clean_joining_date(self):
        val = self.cleaned_data.get('joining_date')
        return val or (self.instance.joining_date if self.instance and self.instance.pk else timezone.localdate())

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        qs = Employee.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                'Another employee already uses this email.')
        # Also check User model
        qs2 = User.objects.filter(email__iexact=email)
        if self.instance.pk and hasattr(self.instance, 'user'):
            qs2 = qs2.exclude(pk=self.instance.user.pk)
        if qs2.exists():
            raise forms.ValidationError(
                'A user account with this email already exists.')
        return email

    def save(self, commit=True):
        employee = super().save(commit=False)
        if commit:
            employee.save()
            self.save_m2m()
            # Sync email + is_active on linked user
            employee.user.email = employee.email
            employee.user.is_active = (employee.status == Employee.STATUS_ACTIVE)
            employee.user.save(update_fields=['email', 'is_active'])
        return employee


# ---------------------------------------------------------------------------
# Permission management form (inline for all modules)
# ---------------------------------------------------------------------------

class PermissionForm(forms.Form):
    """Dynamically generates checkbox rows for every (module, action) pair."""

    ACTIONS = ['view', 'add', 'edit', 'delete', 'export']

    def __init__(self, employee, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        # Pre-load existing perms
        existing = {
            p.module: p
            for p in employee.permissions.all()
        }
        for module_key, module_label in EmployeePermission.MODULE_CHOICES:
            perm = existing.get(module_key)
            for action in self.ACTIONS:
                field_name = f'{module_key}__{action}'
                current    = getattr(perm, f'can_{action}', False) if perm else False
                self.fields[field_name] = forms.BooleanField(
                    required=False,
                    initial=current,
                    label=f'{module_label} – {action.title()}',
                )

    def save(self):
        """Upsert EmployeePermission rows from cleaned_data."""
        data = self.cleaned_data
        for module_key, _label in EmployeePermission.MODULE_CHOICES:
            flags = {
                f'can_{action}': data.get(f'{module_key}__{action}', False)
                for action in self.ACTIONS
            }
            EmployeePermission.objects.update_or_create(
                employee=self.employee,
                module=module_key,
                defaults=flags,
            )
