"""
team/permissions.py
-------------------
Backend authorization and permission enforcement for JewelDesk.
"""

from functools import wraps
from django.core.exceptions import PermissionDenied
from django.contrib.auth.views import redirect_to_login
from .models import Employee, EmployeePermission, Role


def has_module_perm(user, module, action='view'):
    """Check if the given User has permission for an action on a module.

    Rules:
      1. Anonymous or inactive user -> False.
      2. Superuser -> True.
      3. User has employee profile:
         - Inactive employee -> False.
         - Admin role -> True.
         - Otherwise, check EmployeePermission row.
      4. User is staff without employee profile (e.g. Django default admin) -> True.
      5. Otherwise -> False.
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False

    if user.is_superuser:
        return True

    emp = None
    try:
        emp = user.employee_profile
    except Exception:
        emp = None

    if emp:
        if emp.status != Employee.STATUS_ACTIVE:
            return False
        return emp.has_module_permission(module, action)

    if user.is_staff:
        return True

    return False


def is_admin_user(user):
    """Check if the user is a superuser or has the Admin role."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True

    emp = None
    try:
        emp = user.employee_profile
    except Exception:
        emp = None

    if emp:
        return (
            emp.status == Employee.STATUS_ACTIVE
            and emp.role.name == Role.ROLE_ADMIN
        )
    return user.is_staff


def require_permission(module, action='view'):
    """View decorator to enforce backend permission checks.

    Raises PermissionDenied (HTTP 403) if the user lacks the required permission.
    Redirects to login if user is unauthenticated.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not has_module_perm(request.user, module, action):
                raise PermissionDenied(
                    f"You do not have permission to {action} {module}."
                )
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def require_admin():
    """View decorator strictly requiring Admin role or superuser."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not is_admin_user(request.user):
                raise PermissionDenied(
                    "This action is restricted to administrators."
                )
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
