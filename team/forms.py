"""
team/forms.py
-------------
Forms for the Team / Employee Management module.
"""

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import (
    Branch,
    Employee,
    EmployeeDocument,
    EmployeePermission,
    Role,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Branch form
# ---------------------------------------------------------------------------

class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
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
# Employee creation form
# ---------------------------------------------------------------------------

class EmployeeCreateForm(forms.ModelForm):
    """Creates an Employee and optionally a linked Django User account."""

    ACCOUNT_CREATE_NEW = 'create_new'
    ACCOUNT_LINK_EXISTING = 'link_existing'
    ACCOUNT_NONE = 'no_account'

    ACCOUNT_MODE_CHOICES = [
        (ACCOUNT_CREATE_NEW, 'Create login account (Default)'),
        (ACCOUNT_LINK_EXISTING, 'Link to existing Django user'),
        (ACCOUNT_NONE, 'No login access (Employee record only)'),
    ]

    account_mode = forms.ChoiceField(
        choices=ACCOUNT_MODE_CHOICES,
        initial=ACCOUNT_CREATE_NEW,
        required=False,
        widget=forms.RadioSelect(),
        help_text='Determine how this employee accesses the JewelDesk system.'
    )

    # New User fields (used when account_mode == 'create_new')
    username = forms.CharField(
        max_length=150,
        required=False,
        help_text='Leave empty to use email as login username.',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. john.sales or email', 'autocomplete': 'off'}),
    )
    password1 = forms.CharField(
        label='Password',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
        help_text='Minimum 8 characters.',
    )
    password2 = forms.CharField(
        label='Confirm password',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )

    # Existing User field (used when account_mode == 'link_existing')
    existing_user = forms.ModelChoiceField(
        queryset=User.objects.filter(employee_profile__isnull=True).order_by('username'),
        required=False,
        empty_label='-- Select unlinked user account --',
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Select a Django user account not currently assigned to an employee.'
    )

    class Meta:
        model = Employee
        fields = (
            'full_name', 'email', 'mobile', 'designation',
            'department', 'role',
            'joining_date', 'status', 'branches', 'photo',
        )
        widgets = {
            'designation': forms.TextInput(attrs={'placeholder': 'e.g. Senior Gemologist, Store Manager'}),
            'joining_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'branches': forms.CheckboxSelectMultiple(),
            'photo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in ('branches', 'password1', 'password2', 'username', 'account_mode', 'existing_user', 'photo'):
                widget = field.widget
                if not isinstance(widget, (forms.CheckboxSelectMultiple, forms.CheckboxInput)):
                    if isinstance(widget, forms.Select):
                        widget.attrs.setdefault('class', 'form-select')
                    else:
                        widget.attrs.setdefault('class', 'form-control')
        self.fields['branches'].queryset = Branch.objects.filter(is_active=True)
        self.fields['joining_date'].required = False
        self.fields['joining_date'].initial = timezone.localdate

    # ---- Validation --------------------------------------------------------

    def clean_joining_date(self):
        val = self.cleaned_data.get('joining_date')
        return val or timezone.localdate()

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if Employee.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An employee with this email already exists.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        mode = cleaned_data.get('account_mode') or self.ACCOUNT_CREATE_NEW
        email = cleaned_data.get('email')

        if mode == self.ACCOUNT_CREATE_NEW:
            raw_username = (cleaned_data.get('username') or '').strip()
            # If username is omitted, default to email or email local-part
            username = raw_username if raw_username else email
            cleaned_data['username'] = username

            if not username:
                self.add_error('username', 'Username or email is required for login account.')
            elif User.objects.filter(username__iexact=username).exists():
                self.add_error('username', f'A user with username "{username}" already exists.')

            if email and User.objects.filter(email__iexact=email).exists():
                self.add_error('email', 'A user account with this email already exists.')

            p1 = cleaned_data.get('password1', '')
            p2 = cleaned_data.get('password2', '')
            if not p1:
                self.add_error('password1', 'Password is required when creating a login account.')
            elif len(p1) < 8:
                self.add_error('password1', 'Password must be at least 8 characters.')
            if p1 and p2 and p1 != p2:
                self.add_error('password2', 'Passwords do not match.')

        elif mode == self.ACCOUNT_LINK_EXISTING:
            existing_user = cleaned_data.get('existing_user')
            if not existing_user:
                self.add_error('existing_user', 'Please select an existing user account to link.')
            elif hasattr(existing_user, 'employee_profile') and existing_user.employee_profile:
                self.add_error('existing_user', 'This user is already linked to another employee.')

        return cleaned_data

    # ---- Save (transactional) ----------------------------------------------

    def save(self, commit=True, created_by=None):
        """Create Employee (and optionally User) atomically; apply role defaults."""
        from django.db import transaction

        mode = self.cleaned_data.get('account_mode') or self.ACCOUNT_CREATE_NEW
        status = self.cleaned_data.get('status') or Employee.STATUS_ACTIVE
        is_active = (status == Employee.STATUS_ACTIVE)
        full_name = (self.cleaned_data.get('full_name') or '').strip()
        email = (self.cleaned_data.get('email') or '').strip().lower()

        name_parts = full_name.split()
        first_name = name_parts[0] if name_parts else ''
        last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''

        with transaction.atomic():
            user = None
            if mode == self.ACCOUNT_CREATE_NEW:
                username = self.cleaned_data['username'].strip()
                raw_password = self.cleaned_data['password1']
                user = User.objects.create_user(
                    username=username,
                    password=raw_password,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                )
                user.is_active = is_active
                user.is_staff = True  # JewelDesk back-office access
                user.save(update_fields=['is_active', 'is_staff', 'first_name', 'last_name'])

            elif mode == self.ACCOUNT_LINK_EXISTING:
                user = self.cleaned_data['existing_user']
                user.is_active = is_active
                user.is_staff = True
                user.save(update_fields=['is_active', 'is_staff'])

            employee = super().save(commit=False)
            employee.user = user
            employee.email = email
            employee.full_name = full_name
            employee.status = status
            if created_by:
                employee.created_by = created_by
            employee.save()
            self.save_m2m()  # branches

            # Apply default permissions for the chosen role
            employee.apply_default_permissions()

        return employee


# ---------------------------------------------------------------------------
# Employee edit form
# ---------------------------------------------------------------------------

class EmployeeEditForm(forms.ModelForm):

    class Meta:
        model = Employee
        fields = (
            'full_name', 'email', 'mobile', 'designation',
            'department', 'role',
            'joining_date', 'status', 'branches', 'photo',
        )
        widgets = {
            'designation': forms.TextInput(attrs={'placeholder': 'e.g. Senior Gemologist, Store Manager'}),
            'joining_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'branches': forms.CheckboxSelectMultiple(),
            'photo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in ('branches', 'photo'):
                widget = field.widget
                if not isinstance(widget, (forms.CheckboxSelectMultiple, forms.CheckboxInput)):
                    if isinstance(widget, forms.Select):
                        widget.attrs.setdefault('class', 'form-select')
                    else:
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
            raise forms.ValidationError('Another employee already uses this email.')

        # Also check User model if linked
        if self.instance.pk and hasattr(self.instance, 'user') and self.instance.user:
            qs2 = User.objects.filter(email__iexact=email).exclude(pk=self.instance.user.pk)
            if qs2.exists():
                raise forms.ValidationError('A user account with this email already exists.')
        return email

    def save(self, commit=True):
        employee = super().save(commit=False)
        if commit:
            employee.save()
            self.save_m2m()
            # Sync user email, is_active, and name
            if hasattr(employee, 'user') and employee.user:
                employee.user.email = employee.email.strip().lower()
                employee.user.is_active = (employee.status == Employee.STATUS_ACTIVE)
                parts = (employee.full_name or '').strip().split()
                if parts:
                    employee.user.first_name = parts[0]
                    employee.user.last_name = ' '.join(parts[1:])
                employee.user.save(update_fields=['email', 'is_active', 'first_name', 'last_name'])
        return employee


# ---------------------------------------------------------------------------
# Employee Password Reset / Set Form
# ---------------------------------------------------------------------------

class EmployeePasswordResetForm(forms.Form):
    """Admin / Manager form to set or reset an employee's account password."""

    new_password1 = forms.CharField(
        label='New password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
        help_text='Minimum 8 characters.',
    )
    new_password2 = forms.CharField(
        label='Confirm new password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )

    def __init__(self, employee, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee

    def clean_new_password2(self):
        p1 = self.cleaned_data.get('new_password1', '')
        p2 = self.cleaned_data.get('new_password2', '')
        if len(p1) < 8:
            raise forms.ValidationError('Password must be at least 8 characters long.')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError('Passwords do not match.')
        return p2

    def save(self):
        if not self.employee.user:
            raise ValueError('Employee does not have an associated User account.')
        password = self.cleaned_data['new_password1']
        self.employee.user.set_password(password)
        self.employee.user.save(update_fields=['password'])
        return self.employee.user


# ---------------------------------------------------------------------------
# Employee Link Account Form
# ---------------------------------------------------------------------------

class EmployeeLinkAccountForm(forms.Form):
    """Allows creating or linking a Django User for an existing employee without one."""

    MODE_CREATE = 'create'
    MODE_LINK = 'link'

    mode = forms.ChoiceField(
        choices=[(MODE_CREATE, 'Create new login user'), (MODE_LINK, 'Link existing Django user')],
        initial=MODE_CREATE,
        widget=forms.RadioSelect(),
    )
    username = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional: leave blank for email'}),
    )
    password1 = forms.CharField(
        required=False,
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )
    password2 = forms.CharField(
        required=False,
        label='Confirm password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )
    existing_user = forms.ModelChoiceField(
        queryset=User.objects.filter(employee_profile__isnull=True).order_by('username'),
        required=False,
        empty_label='-- Select unlinked user account --',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, employee, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee

    def clean(self):
        cleaned_data = super().clean()
        mode = cleaned_data.get('mode')
        if mode == self.MODE_CREATE:
            username = (cleaned_data.get('username') or self.employee.email).strip()
            cleaned_data['username'] = username
            if User.objects.filter(username__iexact=username).exists():
                self.add_error('username', f'A user with username "{username}" already exists.')
            p1 = cleaned_data.get('password1', '')
            p2 = cleaned_data.get('password2', '')
            if not p1 or len(p1) < 8:
                self.add_error('password1', 'Password must be at least 8 characters.')
            if p1 and p2 and p1 != p2:
                self.add_error('password2', 'Passwords do not match.')
        elif mode == self.MODE_LINK:
            existing_user = cleaned_data.get('existing_user')
            if not existing_user:
                self.add_error('existing_user', 'Please select an existing user to link.')
        return cleaned_data

    def save(self):
        from django.db import transaction
        mode = self.cleaned_data['mode']
        is_active = (self.employee.status == Employee.STATUS_ACTIVE)

        with transaction.atomic():
            if mode == self.MODE_CREATE:
                username = self.cleaned_data['username']
                password = self.cleaned_data['password1']
                parts = self.employee.full_name.split()
                user = User.objects.create_user(
                    username=username,
                    password=password,
                    email=self.employee.email,
                    first_name=parts[0] if parts else '',
                    last_name=' '.join(parts[1:]) if len(parts) > 1 else '',
                )
                user.is_staff = True
                user.is_active = is_active
                user.save(update_fields=['is_staff', 'is_active'])
            else:
                user = self.cleaned_data['existing_user']
                user.is_staff = True
                user.is_active = is_active
                user.save(update_fields=['is_staff', 'is_active'])

            self.employee.user = user
            self.employee.save(update_fields=['user'])
        return self.employee


# ---------------------------------------------------------------------------
# Role form (Admin management of roles)
# ---------------------------------------------------------------------------

class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ('name', 'description')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Store Manager'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Describe the role and responsibilities'}),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        qs = Role.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
            if self.instance.is_builtin and self.instance.name != name:
                raise forms.ValidationError('Built-in role names cannot be renamed.')
        if qs.exists():
            raise forms.ValidationError(f'A role named "{name}" already exists.')
        return name


# ---------------------------------------------------------------------------
# HR Foundation: Employee Document Form
# ---------------------------------------------------------------------------

class EmployeeDocumentForm(forms.ModelForm):
    class Meta:
        model = EmployeeDocument
        fields = ('document_type', 'title', 'file', 'notes')
        widgets = {
            'document_type': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Government ID / Passport'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional notes or verification details'}),
        }


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
                current = getattr(perm, f'can_{action}', False) if perm else False
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
