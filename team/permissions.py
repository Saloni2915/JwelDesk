"""
team/permissions.py
-------------------
Backend authorization and permission enforcement for JewelDesk.
"""

from functools import wraps
from django.core.exceptions import PermissionDenied
from django.contrib.auth.views import redirect_to_login
from .models import Employee, EmployeePermission, Role


ADMIN_ROLE_NAMES = ('Admin', 'Tenant Administrator')


def has_module_perm(user, module, action='view', tenant=None):
    """Check if the given User has permission for an action on a module within a tenant.

    Rules:
      1. Anonymous or inactive user -> False.
      2. Superuser -> True.
      3. If tenant is specified:
         - Tenant owner (active tenant) -> True.
         - Active employee belonging to that tenant:
           * Admin / Tenant Administrator role -> True.
           * Otherwise -> checks granular EmployeePermission row.
         - User does not belong to this tenant -> False.
      4. If tenant is not specified:
         - User owns at least one active tenant -> True.
         - User is an active employee:
           * Admin / Tenant Administrator role -> True.
           * Otherwise -> checks EmployeePermission row.
      5. Any other case (including non-tenant staff or unassigned users) -> False.
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False

    if user.is_superuser:
        return True

    # Check tenant-specific context
    if tenant is not None:
        if module == 'wholesale' and not getattr(tenant, 'is_wholesale', True):
            return False
        if module in ('sales', 'customers', 'custom_orders') and not getattr(tenant, 'is_retail', True):
            return False

        if tenant.owner_id == user.id and tenant.is_active:
            return True

        emp = getattr(user, '_cached_employee_profile', None)
        if emp is None and not getattr(user, '_checked_employee_profile', False):
            try:
                emp = user.employee_profile
            except Exception:
                emp = None
            user._cached_employee_profile = emp
            user._checked_employee_profile = True

        if emp and emp.tenant_id == tenant.id:
            if emp.status != Employee.STATUS_ACTIVE:
                return False
            if emp.role and emp.role.name in (Role.ROLE_ADMIN, getattr(Role, 'ROLE_TENANT_ADMIN', 'Tenant Administrator'), *ADMIN_ROLE_NAMES):
                return True
            return emp.has_module_permission(module, action)

        return False

    # No tenant provided in context: check if user is an active tenant owner
    try:
        if user.owned_tenants.filter(is_active=True).exists():
            return True
    except Exception:
        pass

    emp = getattr(user, '_cached_employee_profile', None)
    if emp is None and not getattr(user, '_checked_employee_profile', False):
        try:
            emp = user.employee_profile
        except Exception:
            emp = None
        user._cached_employee_profile = emp
        user._checked_employee_profile = True

    if emp:
        if emp.status != Employee.STATUS_ACTIVE:
            return False
        if emp.tenant and not emp.tenant.is_active:
            return False
        if emp.role and emp.role.name in (Role.ROLE_ADMIN, getattr(Role, 'ROLE_TENANT_ADMIN', 'Tenant Administrator'), *ADMIN_ROLE_NAMES):
            return True
        return emp.has_module_permission(module, action)

    return False


def is_admin_user(user, tenant=None):
    """Check if the user is a superuser, tenant owner, or has the Admin role for the tenant."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True

    if tenant is not None:
        if tenant.owner_id == user.id and tenant.is_active:
            return True
        emp = getattr(user, '_cached_employee_profile', None)
        if emp is None and not getattr(user, '_checked_employee_profile', False):
            try:
                emp = user.employee_profile
            except Exception:
                emp = None
            user._cached_employee_profile = emp
            user._checked_employee_profile = True

        if emp and emp.tenant_id == tenant.id:
            return (
                emp.status == Employee.STATUS_ACTIVE
                and emp.role is not None
                and emp.role.name in (Role.ROLE_ADMIN, getattr(Role, 'ROLE_TENANT_ADMIN', 'Tenant Administrator'), *ADMIN_ROLE_NAMES)
            )
        return False

    try:
        if user.owned_tenants.filter(is_active=True).exists():
            return True
    except Exception:
        pass

    emp = getattr(user, '_cached_employee_profile', None)
    if emp is None and not getattr(user, '_checked_employee_profile', False):
        try:
            emp = user.employee_profile
        except Exception:
            emp = None
        user._cached_employee_profile = emp
        user._checked_employee_profile = True

    if emp:
        return (
            emp.status == Employee.STATUS_ACTIVE
            and (emp.tenant is None or emp.tenant.is_active)
            and emp.role is not None
            and emp.role.name in (Role.ROLE_ADMIN, getattr(Role, 'ROLE_TENANT_ADMIN', 'Tenant Administrator'), *ADMIN_ROLE_NAMES)
        )
    return False


def require_permission(module, action='view'):
    """View decorator to enforce backend permission checks scoped to request.tenant.

    Raises PermissionDenied (HTTP 403) if the user lacks the required permission.
    Redirects to login if user is unauthenticated.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            tenant = getattr(request, 'tenant', None)
            if not has_module_perm(request.user, module, action, tenant=tenant):
                raise PermissionDenied(
                    f"You do not have permission to {action} {module}."
                )
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def require_admin():
    """View decorator strictly requiring Admin role, tenant owner, or superuser."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            tenant = getattr(request, 'tenant', None)
            if not is_admin_user(request.user, tenant=tenant):
                raise PermissionDenied(
                    "This action is restricted to administrators."
                )
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def check_branch_access(request, obj):
    """
    Ensure the requesting user has authorization to access an object based on branch assignment.
    Superusers, tenant owners, and users with can_view_all_branches can access all branches in tenant.
    Restricted employees can only access records belonging to their allowed branches or records with no branch.
    """
    if not request.user or not request.user.is_authenticated:
        return False
    if request.user.is_superuser:
        return True
    tenant = getattr(request, 'tenant', None)
    if tenant and getattr(obj, 'tenant_id', None) and obj.tenant_id != tenant.id:
        return False
    branch = getattr(obj, 'branch', None)
    if branch is None:
        return True
    if getattr(request, 'can_view_all_branches', False):
        return True
    allowed_qs = getattr(request, 'allowed_branches', None)
    if allowed_qs is not None:
        return allowed_qs.filter(id=branch.id).exists()
    return True

