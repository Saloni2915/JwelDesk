"""
team/models.py
--------------
Team & Employee Management models for JewelDesk.

Design decisions:
  - Uses Django's built-in User model (AUTH_USER_MODEL) via OneToOne link.
  - No custom User model needed; employee-specific fields live on Employee.
  - Role → predefined + extensible; permissions scoped per JewelDesk module.
  - Branch → simple name-based lookup; employees may access 0…N branches.
  - Employee ID auto-generated as EMP-0001, EMP-0002, ...
"""

import os
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from accounts.models import validate_proper_email, clean_10_digit_phone


ALLOWED_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif')


def validate_image_extension(value):
    """Validate allowed image extensions for employee photos."""
    if not value:
        return
    ext = os.path.splitext(value.name or '')[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(
            'Unsupported image format. Allowed: ' + ', '.join(ALLOWED_IMAGE_EXTENSIONS)
        )



# ---------------------------------------------------------------------------
# Branch
# ---------------------------------------------------------------------------

class Branch(models.Model):
    """A physical shop location / branch.

    Employees can be assigned to one or more branches. The Admin always has
    implicit access to all branches.
    """
    tenant      = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='branches',
        null=True,
        blank=True,
        help_text="Tenant shop owning this branch"
    )
    name        = models.CharField(max_length=150)
    code        = models.CharField(
        max_length=20,
        blank=True,
        help_text="Short branch identifier, e.g. MAIN, BR-01"
    )
    address     = models.TextField(blank=True)
    phone       = models.CharField(max_length=20, blank=True)
    is_default  = models.BooleanField(
        default=False,
        help_text="Primary / default branch for this showroom tenant"
    )
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Branches'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'name'],
                name='unique_tenant_branch_name',
            ),
        ]

    def __str__(self):
        if self.code:
            return f"{self.name} ({self.code})"
        return self.name

    @classmethod
    def ensure_default_branch(cls, tenant):
        """Return default branch for tenant, creating one if none exists."""
        if not tenant:
            return None
        branch = cls.objects.filter(tenant=tenant, is_default=True).first()
        if not branch:
            branch = cls.objects.filter(tenant=tenant).first()
        if not branch:
            branch = cls.objects.create(
                tenant=tenant,
                name='Main Showroom',
                code='MAIN',
                is_default=True,
                is_active=True,
            )
        elif not branch.is_default and not cls.objects.filter(tenant=tenant, is_default=True).exists():
            branch.is_default = True
            branch.save(update_fields=['is_default'])
        return branch


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------

class Role(models.Model):
    """Job role inside the jewellery business.

    Pre-seeded roles are created via the data migration / management command.
    Admins can add custom roles later through the Team → Roles UI (future).
    """

    ROLE_TENANT_ADMIN      = 'Tenant Administrator'
    ROLE_ADMIN             = 'Admin'
    ROLE_HR                = 'HR'
    ROLE_MANAGER           = 'Manager'
    ROLE_SALES             = 'Sales'
    ROLE_SALES_EXECUTIVE   = 'Sales Executive'
    ROLE_INVENTORY         = 'Inventory'
    ROLE_INVENTORY_MANAGER = 'Inventory Manager'
    ROLE_ACCOUNTANT        = 'Accountant'
    ROLE_SUPPORT           = 'Support'
    ROLE_CASHIER           = 'Cashier'

    ADMIN_ROLES = (ROLE_ADMIN, ROLE_TENANT_ADMIN)

    DEFAULT_ROLES = [
        ROLE_TENANT_ADMIN,
        ROLE_ADMIN,
        ROLE_HR,
        ROLE_MANAGER,
        ROLE_SALES,
        ROLE_SALES_EXECUTIVE,
        ROLE_INVENTORY,
        ROLE_INVENTORY_MANAGER,
        ROLE_ACCOUNTANT,
        ROLE_SUPPORT,
        ROLE_CASHIER,
    ]

    tenant      = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='roles',
        null=True,
        blank=True,
        help_text="Tenant shop owning this custom role (null for system built-in roles)"
    )
    name        = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_builtin  = models.BooleanField(
        default=False,
        help_text='Built-in roles cannot be deleted.'
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'name'],
                name='unique_tenant_role_name',
            ),
        ]

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        if self.is_builtin:
            raise ValidationError('Built-in roles cannot be deleted.')
        super().delete(*args, **kwargs)

    @classmethod
    def ensure_builtin_roles(cls):
        """Seed or ensure all standard built-in roles exist in the database."""
        roles_data = [
            (cls.ROLE_TENANT_ADMIN, 'Full administrative access across all modules as Tenant Administrator.'),
            (cls.ROLE_ADMIN, 'Full administrative access across all modules.'),
            (cls.ROLE_MANAGER, 'Store manager with inventory and sales management access.'),
            (cls.ROLE_SALES, 'Handle sales counters and customer interactions.'),
            (cls.ROLE_SALES_EXECUTIVE, 'Handle customer interactions and advanced sales.'),
            (cls.ROLE_INVENTORY, 'Manage jewellery stock and inventory tracking.'),
            (cls.ROLE_INVENTORY_MANAGER, 'Manage jewellery inventory and stock in full.'),
            (cls.ROLE_ACCOUNTANT, 'Financial and accounting access.'),
            (cls.ROLE_HR, 'Human resources, team management, and employee records.'),
            (cls.ROLE_SUPPORT, 'Customer support, order tracking, and enquiry management.'),
            (cls.ROLE_CASHIER, 'Process sales at the counter.'),
        ]
        created = 0
        for name, desc in roles_data:
            role = cls.objects.filter(name=name, tenant__isnull=True).first() or cls.objects.filter(name=name).first()
            if not role:
                cls.objects.create(
                    name=name,
                    tenant=None,
                    description=desc,
                    is_builtin=True,
                )
                created += 1
        return created

    def get_permissions(self, tenant=None):
        """
        Return a dict of {module: {can_view: bool, can_add: bool, can_edit: bool, can_delete: bool, can_export: bool}}
        for this role, checking tenant-specific customization first, then global RolePermission,
        and finally falling back to standard default permissions.
        """
        perms_dict = {}
        target_tenant = tenant or self.tenant
        if target_tenant:
            custom_perms = self.role_permissions.filter(tenant=target_tenant)
            if custom_perms.exists():
                for p in custom_perms:
                    perms_dict[p.module] = {
                        'can_view': p.can_view,
                        'can_add': p.can_add,
                        'can_edit': p.can_edit,
                        'can_delete': p.can_delete,
                        'can_export': p.can_export,
                    }

        if not perms_dict:
            base_perms = self.role_permissions.filter(tenant__isnull=True)
            if base_perms.exists():
                for p in base_perms:
                    perms_dict[p.module] = {
                        'can_view': p.can_view,
                        'can_add': p.can_add,
                        'can_edit': p.can_edit,
                        'can_delete': p.can_delete,
                        'can_export': p.can_export,
                    }

        if not perms_dict:
            perms_dict = EmployeePermission.default_permissions_for_role(self.name)

        none_flags = dict(can_view=False, can_add=False, can_edit=False, can_delete=False, can_export=False)
        for m in EmployeePermission.MODULES:
            if m not in perms_dict:
                perms_dict[m] = none_flags.copy()

        return perms_dict

    def set_permissions(self, permissions_data, tenant=None, sync_employees=False):
        """
        Save permissions_data: dict of {module: {can_view: bool, can_add: bool, can_edit: bool, can_delete: bool, can_export: bool}}
        for this role and tenant.
        If sync_employees is True, updates EmployeePermission for all employees belonging to this tenant and role.
        """
        target_tenant = tenant or self.tenant
        for module, flags in permissions_data.items():
            RolePermission.objects.update_or_create(
                role=self,
                tenant=target_tenant,
                module=module,
                defaults={
                    'can_view': bool(flags.get('can_view', False)),
                    'can_add': bool(flags.get('can_add', False)),
                    'can_edit': bool(flags.get('can_edit', False)),
                    'can_delete': bool(flags.get('can_delete', False)),
                    'can_export': bool(flags.get('can_export', False)),
                }
            )

        if sync_employees:
            employees = self.employees.filter(tenant=target_tenant) if target_tenant else self.employees.all()
            for emp in employees:
                for module, flags in permissions_data.items():
                    EmployeePermission.objects.update_or_create(
                        employee=emp,
                        module=module,
                        defaults={
                            'can_view': bool(flags.get('can_view', False)),
                            'can_add': bool(flags.get('can_add', False)),
                            'can_edit': bool(flags.get('can_edit', False)),
                            'can_delete': bool(flags.get('can_delete', False)),
                            'can_export': bool(flags.get('can_export', False)),
                        }
                    )


# ---------------------------------------------------------------------------
# Module-level permission system
# ---------------------------------------------------------------------------

class EmployeePermission(models.Model):
    """Granular per-employee / per-module permission record.

    One row per (employee, module) pair.  Each flag maps to a UI action.
    """

    # ---- JewelDesk module keys -------------------------------------------
    MODULE_DASHBOARD     = 'dashboard'
    MODULE_TEAM          = 'team'
    MODULE_CUSTOMERS     = 'customers'
    MODULE_INVENTORY     = 'inventory'
    MODULE_SALES         = 'sales'
    MODULE_PURCHASES     = 'purchases'
    MODULE_CUSTOM_ORDERS = 'custom_orders'
    MODULE_REPORTS       = 'reports'
    MODULE_METAL_PRICES  = 'metal_prices'
    MODULE_SETTINGS      = 'settings'
    MODULE_KARIGAR       = 'karigar'
    MODULE_WHOLESALE     = 'wholesale'
    MODULE_GIRVI         = 'girvi'

    MODULE_CHOICES = [
        (MODULE_DASHBOARD,     'Dashboard'),
        (MODULE_TEAM,          'Team'),
        (MODULE_CUSTOMERS,     'Customers'),
        (MODULE_INVENTORY,     'Inventory'),
        (MODULE_SALES,         'Sales'),
        (MODULE_PURCHASES,     'Purchases'),
        (MODULE_CUSTOM_ORDERS, 'Custom Orders'),
        (MODULE_REPORTS,       'Reports'),
        (MODULE_METAL_PRICES,  'Metal Prices'),
        (MODULE_SETTINGS,      'Settings'),
        (MODULE_KARIGAR,       'Karigar / Manufacturing'),
        (MODULE_WHOLESALE,     'Wholesale / Supplier'),
        (MODULE_GIRVI,         'Girvi / Pledge Loans'),
    ]

    MODULES = [c[0] for c in MODULE_CHOICES]

    employee   = models.ForeignKey(
        'Employee', on_delete=models.CASCADE, related_name='permissions'
    )
    module     = models.CharField(max_length=30, choices=MODULE_CHOICES)

    # Per-action flags
    can_view   = models.BooleanField(default=False)
    can_add    = models.BooleanField(default=False)
    can_edit   = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_export = models.BooleanField(default=False)

    class Meta:
        unique_together = ('employee', 'module')
        ordering = ['module']

    def __str__(self):
        flags = [
            a for a, v in (
                ('view',   self.can_view),
                ('add',    self.can_add),
                ('edit',   self.can_edit),
                ('delete', self.can_delete),
                ('export', self.can_export),
            ) if v
        ]
        return f"{self.employee.employee_id} | {self.module}: {', '.join(flags) or 'none'}"

    @classmethod
    def default_permissions_for_role(cls, role_name):
        """Return a list of (module, {flag: bool}) dicts for a given role.

        These are sensible defaults; Admins can customise any employee's
        permissions afterwards.
        """
        full = dict(can_view=True, can_add=True, can_edit=True,
                    can_delete=True, can_export=True)
        view_only  = dict(can_view=True, can_add=False, can_edit=False,
                          can_delete=False, can_export=False)
        view_exp   = dict(can_view=True, can_add=False, can_edit=False,
                          can_delete=False, can_export=True)
        view_add   = dict(can_view=True, can_add=True, can_edit=True,
                          can_delete=False, can_export=False)
        none_flags = dict(can_view=False, can_add=False, can_edit=False,
                          can_delete=False, can_export=False)

        perms = {}  # module → flags dict

        if role_name in (Role.ROLE_ADMIN, getattr(Role, 'ROLE_TENANT_ADMIN', 'Tenant Administrator'), 'Tenant Administrator', 'Admin'):
            for m in cls.MODULES:
                perms[m] = full

        elif role_name == Role.ROLE_HR:
            perms = {
                cls.MODULE_DASHBOARD: view_only,
                cls.MODULE_TEAM:      full,
                cls.MODULE_REPORTS:   view_only,
                cls.MODULE_SETTINGS:  view_only,
            }

        elif role_name == Role.ROLE_MANAGER:
            perms = {
                cls.MODULE_DASHBOARD:     view_only,
                cls.MODULE_TEAM:          view_add,
                cls.MODULE_CUSTOMERS:     full,
                cls.MODULE_INVENTORY:     full,
                cls.MODULE_SALES:         full,
                cls.MODULE_PURCHASES:     full,
                cls.MODULE_CUSTOM_ORDERS: full,
                cls.MODULE_REPORTS:       view_exp,
                cls.MODULE_METAL_PRICES:  view_only,
                cls.MODULE_SETTINGS:      view_only,
                cls.MODULE_KARIGAR:       full,
            }

        elif role_name in (Role.ROLE_SALES, Role.ROLE_SALES_EXECUTIVE):
            perms = {
                cls.MODULE_DASHBOARD:     view_only,
                cls.MODULE_CUSTOMERS:     view_add,
                cls.MODULE_INVENTORY:     view_only,
                cls.MODULE_SALES:         view_add,
                cls.MODULE_CUSTOM_ORDERS: view_add,
                cls.MODULE_METAL_PRICES:  view_only,
                cls.MODULE_KARIGAR:       view_add,
            }

        elif role_name in (Role.ROLE_INVENTORY, Role.ROLE_INVENTORY_MANAGER):
            perms = {
                cls.MODULE_DASHBOARD:    view_only,
                cls.MODULE_INVENTORY:    full,
                cls.MODULE_METAL_PRICES: view_only,
                cls.MODULE_KARIGAR:      full,
            }

        elif role_name == Role.ROLE_ACCOUNTANT:
            perms = {
                cls.MODULE_DASHBOARD: view_only,
                cls.MODULE_SALES:     view_exp,
                cls.MODULE_REPORTS:   view_exp,
                cls.MODULE_CUSTOMERS: view_only,
                cls.MODULE_KARIGAR:   view_exp,
            }

        elif role_name == Role.ROLE_SUPPORT:
            perms = {
                cls.MODULE_DASHBOARD:     view_only,
                cls.MODULE_CUSTOMERS:     view_add,
                cls.MODULE_INVENTORY:     view_only,
                cls.MODULE_CUSTOM_ORDERS: view_only,
                cls.MODULE_SALES:         view_only,
                cls.MODULE_KARIGAR:       view_only,
            }

        elif role_name == Role.ROLE_CASHIER:
            perms = {
                cls.MODULE_DASHBOARD:     view_only,
                cls.MODULE_CUSTOMERS:     view_only,
                cls.MODULE_INVENTORY:     view_only,
                cls.MODULE_SALES:         view_add,
                cls.MODULE_METAL_PRICES:  view_only,
                cls.MODULE_KARIGAR:       view_only,
            }

        # Ensure all modules have an entry (default to no access)
        for m in cls.MODULES:
            perms.setdefault(m, none_flags.copy())

        return perms


# ---------------------------------------------------------------------------
# Role-level permission system
# ---------------------------------------------------------------------------

class RolePermission(models.Model):
    """
    Configurable permissions assigned directly to a Role.
    Tenant-scoped so each showroom business can configure what Accountant, Cashier,
    Sales, Manager, or custom roles can view, add, edit, delete, and export.
    """
    tenant     = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='role_permissions',
        null=True,
        blank=True,
        help_text="Tenant that customized this role's permissions (null for global defaults)"
    )
    role       = models.ForeignKey(
        'Role',
        on_delete=models.CASCADE,
        related_name='role_permissions',
        help_text="Role to which this permission set applies"
    )
    module     = models.CharField(max_length=30, choices=EmployeePermission.MODULE_CHOICES)

    can_view   = models.BooleanField(default=False)
    can_add    = models.BooleanField(default=False)
    can_edit   = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_export = models.BooleanField(default=False)

    class Meta:
        unique_together = ('tenant', 'role', 'module')
        ordering = ['module']

    def __str__(self):
        tenant_str = f"[{self.tenant.name}] " if self.tenant else "[Global] "
        flags = [
            a for a, v in (
                ('view',   self.can_view),
                ('add',    self.can_add),
                ('edit',   self.can_edit),
                ('delete', self.can_delete),
                ('export', self.can_export),
            ) if v
        ]
        return f"{tenant_str}{self.role.name} | {self.module}: {', '.join(flags) or 'none'}"


# ---------------------------------------------------------------------------
# Employee
# ---------------------------------------------------------------------------

def _next_employee_id(tenant=None):
    """Generate the next EMP-XXXX identifier atomically for the given tenant."""
    with transaction.atomic():
        qs = Employee.objects.filter(employee_id__startswith='EMP-')
        if tenant:
            qs = qs.filter(tenant=tenant)
        last = qs.order_by('-employee_id').values_list('employee_id', flat=True).first()
        if last:
            try:
                num = int(last.split('-')[-1]) + 1
            except (ValueError, IndexError):
                num = 1
        else:
            num = 1
        candidate = f'EMP-{num:04d}'
        check_qs = Employee.objects.filter(employee_id=candidate)
        if tenant:
            check_qs = check_qs.filter(tenant=tenant)
        while check_qs.exists():
            num += 1
            candidate = f'EMP-{num:04d}'
            check_qs = Employee.objects.filter(employee_id=candidate)
            if tenant:
                check_qs = check_qs.filter(tenant=tenant)
        return candidate


class Employee(models.Model):
    """Business-level employee profile linked to a Django User account.

    The Django User handles authentication (password, is_active, etc.).
    This model stores jewellery-business-specific fields.
    """

    STATUS_ACTIVE   = 'Active'
    STATUS_INACTIVE = 'Inactive'
    STATUS_ON_LEAVE = 'On Leave'

    STATUS_CHOICES = [
        (STATUS_ACTIVE,   'Active'),
        (STATUS_INACTIVE, 'Inactive'),
        (STATUS_ON_LEAVE, 'On Leave'),
    ]

    DEPT_CHOICES = [
        ('Sales',            'Sales'),
        ('Inventory',        'Inventory'),
        ('Accounts',         'Accounts'),
        ('Administration',   'Administration'),
        ('Operations',       'Operations'),
        ('Customer Service', 'Customer Service'),
        ('Other',            'Other'),
    ]

    # --- Account link -------------------------------------------------------
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employee_profile',
        help_text='Django user account for this employee (optional).'
    )

    # --- Tenant ownership ---------------------------------------------------
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='employees',
        null=True,
        blank=True,
        help_text="Tenant shop employing this staff member"
    )

    # --- Identity -----------------------------------------------------------
    employee_id = models.CharField(
        max_length=20,
        help_text='ID like EMP-0001.'
    )
    full_name   = models.CharField(max_length=150)
    email       = models.EmailField(validators=[validate_proper_email])
    mobile      = models.CharField(max_length=20, blank=True)
    designation = models.CharField(
        max_length=100, blank=True,
        help_text='Job title or designation, e.g. Senior Gemologist, Sales Head'
    )
    photo       = models.FileField(
        upload_to='employees/', null=True, blank=True,
        validators=[validate_image_extension],
        help_text='Profile photo (PNG/JPG/WEBP).'
    )

    # --- Organisation -------------------------------------------------------
    department  = models.CharField(
        max_length=50, choices=DEPT_CHOICES, default='Sales'
    )
    role        = models.ForeignKey(
        Role, on_delete=models.PROTECT, related_name='employees'
    )
    joining_date = models.DateField(default=timezone.localdate, blank=True)

    # --- Access -------------------------------------------------------------
    branches    = models.ManyToManyField(
        Branch,
        blank=True,
        related_name='employees',
        help_text='Branches this employee can access. Leave empty for all.'
    )
    status      = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )

    # --- Audit --------------------------------------------------------------
    created_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='employees_created',
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['full_name']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'employee_id'],
                name='unique_tenant_employee_id',
            ),
            models.UniqueConstraint(
                fields=['tenant', 'email'],
                name='unique_tenant_employee_email',
            ),
        ]

    def __str__(self):
        return f"{self.employee_id} – {self.full_name}"

    # ---- Helpers -----------------------------------------------------------

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        if hasattr(self, '_cached_permissions_map'):
            del self._cached_permissions_map
        if hasattr(self, '_cached_role_permissions_map'):
            del self._cached_role_permissions_map

    def clean(self):
        super().clean()
        if self.email:
            self.email = validate_proper_email(self.email, field_label='Email address', required=True)
        if self.mobile:
            try:
                self.mobile = clean_10_digit_phone(self.mobile, field_label='Mobile number', required=False)
            except ValidationError as err:
                raise ValidationError({'mobile': err.message if hasattr(err, 'message') else str(err)})

    def save(self, *args, **kwargs):
        if not self.employee_id:
            self.employee_id = _next_employee_id(tenant=self.tenant)
        super().save(*args, **kwargs)

    def activate(self):
        """Activate both the employee record and the linked User if present."""
        self.status = self.STATUS_ACTIVE
        if self.user:
            self.user.is_active = True
            self.user.save(update_fields=['is_active'])
        self.save(update_fields=['status'])

    def deactivate(self):
        """Deactivate both records so the user cannot log in."""
        self.status = self.STATUS_INACTIVE
        if self.user:
            self.user.is_active = False
            self.user.save(update_fields=['is_active'])
        self.save(update_fields=['status'])

    def has_module_permission(self, module, action='view'):
        """Check if this employee has a specific action on a module.

        Superusers and Admin role always return True.
        """
        if self.status != self.STATUS_ACTIVE:
            return False
        if self.user and self.user.is_superuser:
            return True
        if self.role and self.role.name in (Role.ROLE_ADMIN, getattr(Role, 'ROLE_TENANT_ADMIN', 'Tenant Administrator'), 'Tenant Administrator', 'Admin'):
            return True

        # Memoize all permissions for this employee on first check to prevent 10-15 sequential queries in base.html
        if not hasattr(self, '_cached_permissions_map'):
            self._cached_permissions_map = {
                p.module: {
                    'view':   p.can_view,
                    'add':    p.can_add,
                    'edit':   p.can_edit,
                    'delete': p.can_delete,
                    'export': p.can_export,
                }
                for p in self.permissions.all()
            }

        if module in self._cached_permissions_map:
            return self._cached_permissions_map[module].get(action, False)

        if self.role and hasattr(self.role, 'get_permissions'):
            if not hasattr(self, '_cached_role_permissions_map'):
                self._cached_role_permissions_map = self.role.get_permissions(tenant=self.tenant)
            module_perms = self._cached_role_permissions_map.get(module, {})
            return module_perms.get(f'can_{action}', False)
        return False

    def apply_default_permissions(self):
        """Create/reset EmployeePermission rows to role defaults."""
        defaults = (
            self.role.get_permissions(tenant=self.tenant)
            if hasattr(self.role, 'get_permissions')
            else EmployeePermission.default_permissions_for_role(self.role.name)
        )
        for module, flags in defaults.items():
            EmployeePermission.objects.update_or_create(
                employee=self,
                module=module,
                defaults=flags,
            )

    @classmethod
    def ensure_tenant_admin(cls, tenant, user=None):
        """Ensure the tenant owner has an active Employee profile with the Tenant Administrator role and full permissions."""
        if not tenant:
            return None
        owner = user or getattr(tenant, 'owner', None)
        if not owner:
            return None

        Role.ensure_builtin_roles()
        admin_role = (
            Role.objects.filter(name=Role.ROLE_TENANT_ADMIN, tenant__isnull=True).first()
            or Role.objects.filter(name=Role.ROLE_TENANT_ADMIN, tenant=tenant).first()
            or Role.objects.filter(name=Role.ROLE_TENANT_ADMIN).first()
            or Role.objects.filter(name=Role.ROLE_ADMIN, tenant__isnull=True).first()
            or Role.objects.filter(name=Role.ROLE_ADMIN, tenant=tenant).first()
            or Role.objects.filter(name=Role.ROLE_ADMIN).first()
        )
        if not admin_role:
            admin_role = Role.objects.create(
                name=Role.ROLE_TENANT_ADMIN,
                tenant=tenant,
                description='Full administrative access across all modules as Tenant Administrator.',
                is_builtin=True,
            )

        emp = cls.objects.filter(tenant=tenant, user=owner).first()
        if not emp and owner.email:
            emp = cls.objects.filter(tenant=tenant, email__iexact=owner.email).first()

        if not emp:
            full_name = ''
            if hasattr(owner, 'get_full_name'):
                full_name = owner.get_full_name().strip()
            if not full_name:
                full_name = (owner.first_name or '').strip()
            if not full_name:
                full_name = owner.username

            owner_email = (owner.email or '').strip().lower()
            if not owner_email:
                owner_email = f"{owner.username}@jeweldesk.local"

            emp = cls.objects.create(
                user=owner,
                tenant=tenant,
                full_name=full_name,
                email=owner_email,
                role=admin_role,
                designation='Tenant Administrator',
                department='Administration',
                status=cls.STATUS_ACTIVE,
            )
        else:
            updates = []
            if emp.user_id != owner.id:
                emp.user = owner
                updates.append('user')
            if emp.status != cls.STATUS_ACTIVE:
                emp.status = cls.STATUS_ACTIVE
                updates.append('status')
            if admin_role and emp.role_id != admin_role.id:
                emp.role = admin_role
                updates.append('role')
            if not emp.designation or emp.designation in ('Admin', 'Full Administrator', 'Staff'):
                emp.designation = 'Tenant Administrator'
                updates.append('designation')
            if updates:
                emp.save(update_fields=updates)

        emp.apply_default_permissions()
        return emp


# ---------------------------------------------------------------------------
# HR Foundation: Employee Document
# ---------------------------------------------------------------------------

class EmployeeDocument(models.Model):
    """Foundation for HR documents: ID proofs, contracts, resumes, certificates."""
    DOC_ID_PROOF    = 'id_proof'
    DOC_CONTRACT    = 'contract'
    DOC_RESUME      = 'resume'
    DOC_CERTIFICATE = 'certificate'
    DOC_OTHER       = 'other'

    DOC_TYPE_CHOICES = [
        (DOC_ID_PROOF,    'Identity Proof (Govt ID / Passport / PAN)'),
        (DOC_CONTRACT,    'Employment Contract / Agreement'),
        (DOC_RESUME,      'Resume / CV'),
        (DOC_CERTIFICATE, 'Certificate / Qualification'),
        (DOC_OTHER,       'Other Document'),
    ]

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='employee_documents',
        null=True,
        blank=True,
        help_text="Tenant shop owning this employee document"
    )
    employee    = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='documents'
    )
    document_type = models.CharField(
        max_length=30, choices=DOC_TYPE_CHOICES, default=DOC_OTHER
    )
    title       = models.CharField(max_length=150)
    file        = models.FileField(upload_to='employee_docs/')
    notes       = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='employee_docs_uploaded'
    )

    def save(self, *args, **kwargs):
        if not self.tenant_id and self.employee_id and getattr(self.employee, 'tenant_id', None):
            self.tenant_id = self.employee.tenant_id
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.employee.employee_id} – {self.title}"

