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

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


# ---------------------------------------------------------------------------
# Branch
# ---------------------------------------------------------------------------

class Branch(models.Model):
    """A physical shop location / branch.

    Employees can be assigned to one or more branches. The Admin always has
    implicit access to all branches.
    """
    name        = models.CharField(max_length=150, unique=True)
    address     = models.TextField(blank=True)
    phone       = models.CharField(max_length=20, blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Branches'
        ordering = ['name']

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------

class Role(models.Model):
    """Job role inside the jewellery business.

    Pre-seeded roles are created via the data migration / management command.
    Admins can add custom roles later through the Team → Roles UI (future).
    """

    ROLE_ADMIN             = 'Admin'
    ROLE_MANAGER           = 'Manager'
    ROLE_SALES_EXECUTIVE   = 'Sales Executive'
    ROLE_INVENTORY_MANAGER = 'Inventory Manager'
    ROLE_ACCOUNTANT        = 'Accountant'
    ROLE_CASHIER           = 'Cashier'

    DEFAULT_ROLES = [
        ROLE_ADMIN,
        ROLE_MANAGER,
        ROLE_SALES_EXECUTIVE,
        ROLE_INVENTORY_MANAGER,
        ROLE_ACCOUNTANT,
        ROLE_CASHIER,
    ]

    name        = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_builtin  = models.BooleanField(
        default=False,
        help_text='Built-in roles cannot be deleted.'
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        if self.is_builtin:
            raise ValidationError('Built-in roles cannot be deleted.')
        super().delete(*args, **kwargs)


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

        if role_name == Role.ROLE_ADMIN:
            for m in cls.MODULES:
                perms[m] = full

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
            }

        elif role_name == Role.ROLE_SALES_EXECUTIVE:
            perms = {
                cls.MODULE_DASHBOARD:     view_only,
                cls.MODULE_CUSTOMERS:     view_add,
                cls.MODULE_INVENTORY:     view_only,
                cls.MODULE_SALES:         view_add,
                cls.MODULE_CUSTOM_ORDERS: view_add,
                cls.MODULE_METAL_PRICES:  view_only,
            }

        elif role_name == Role.ROLE_INVENTORY_MANAGER:
            perms = {
                cls.MODULE_DASHBOARD:  view_only,
                cls.MODULE_INVENTORY:  full,
                cls.MODULE_METAL_PRICES: view_only,
            }

        elif role_name == Role.ROLE_ACCOUNTANT:
            perms = {
                cls.MODULE_DASHBOARD: view_only,
                cls.MODULE_SALES:     view_exp,
                cls.MODULE_REPORTS:   view_exp,
                cls.MODULE_CUSTOMERS: view_only,
            }

        elif role_name == Role.ROLE_CASHIER:
            perms = {
                cls.MODULE_DASHBOARD:     view_only,
                cls.MODULE_CUSTOMERS:     view_only,
                cls.MODULE_INVENTORY:     view_only,
                cls.MODULE_SALES:         view_add,
                cls.MODULE_METAL_PRICES:  view_only,
            }

        # Ensure all modules have an entry (default to no access)
        for m in cls.MODULES:
            perms.setdefault(m, none_flags.copy())

        return perms


# ---------------------------------------------------------------------------
# Employee
# ---------------------------------------------------------------------------

def _next_employee_id():
    """Generate the next EMP-XXXX identifier atomically."""
    with transaction.atomic():
        last = (
            Employee.objects
            .filter(employee_id__startswith='EMP-')
            .order_by('-employee_id')
            .values_list('employee_id', flat=True)
            .first()
        )
        if last:
            try:
                num = int(last.split('-')[-1]) + 1
            except (ValueError, IndexError):
                num = 1
        else:
            num = 1
        candidate = f'EMP-{num:04d}'
        while Employee.objects.filter(employee_id=candidate).exists():
            num += 1
            candidate = f'EMP-{num:04d}'
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
        on_delete=models.PROTECT,
        related_name='employee_profile',
        help_text='Django user account for this employee.'
    )

    # --- Identity -----------------------------------------------------------
    employee_id = models.CharField(
        max_length=20, unique=True,
        help_text='Auto-generated ID like EMP-0001.'
    )
    full_name   = models.CharField(max_length=150)
    email       = models.EmailField(unique=True)
    mobile      = models.CharField(max_length=20, blank=True)

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

    def __str__(self):
        return f"{self.employee_id} – {self.full_name}"

    # ---- Helpers -----------------------------------------------------------

    def save(self, *args, **kwargs):
        if not self.employee_id:
            self.employee_id = _next_employee_id()
        super().save(*args, **kwargs)

    def activate(self):
        """Activate both the employee record and the linked User."""
        self.status = self.STATUS_ACTIVE
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        self.save(update_fields=['status'])

    def deactivate(self):
        """Deactivate both records so the user cannot log in."""
        self.status = self.STATUS_INACTIVE
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.save(update_fields=['status'])

    def has_module_permission(self, module, action='view'):
        """Check if this employee has a specific action on a module.

        Admins (is_staff + Admin role) always return True.
        """
        if self.user.is_staff:
            return True
        try:
            perm = self.permissions.get(module=module)
        except EmployeePermission.DoesNotExist:
            return False
        flag_map = {
            'view':   perm.can_view,
            'add':    perm.can_add,
            'edit':   perm.can_edit,
            'delete': perm.can_delete,
            'export': perm.can_export,
        }
        return flag_map.get(action, False)

    def apply_default_permissions(self):
        """Create/reset EmployeePermission rows to role defaults."""
        defaults = EmployeePermission.default_permissions_for_role(
            self.role.name
        )
        for module, flags in defaults.items():
            EmployeePermission.objects.update_or_create(
                employee=self,
                module=module,
                defaults=flags,
            )
