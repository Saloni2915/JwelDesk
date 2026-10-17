"""
super_admin/decorators.py
-------------------------
Security decorators for the JewelDesk Super Admin Portal.
Strictly restricts access to verified Django superusers on the server side.
"""

from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def super_admin_required(view_func):
    """Ensure the user is an authenticated Django superuser.

    Rules:
    1. Unauthenticated requests are redirected to login.
    2. Impersonated sessions are explicitly blocked from accessing platform admin (HTTP 403).
    3. Normal authenticated tenant users, showroom owners, and staff are blocked with HTTP 403 Forbidden.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        user = getattr(request, 'user', None)

        if not user or not user.is_authenticated:
            login_url = reverse('accounts:login')
            return redirect(f"{login_url}?next={request.path}")

        # Block impersonated sessions from accessing super admin portal
        if request.session.get('impersonator_id') or getattr(request, 'is_impersonated', False):
            raise PermissionDenied(
                "Platform admin access is forbidden while impersonating a showroom user. "
                "Please exit impersonation before accessing the Super Admin portal."
            )

        # Enforce superuser privilege
        if not user.is_superuser:
            raise PermissionDenied(
                "Access denied. Platform Administrator privileges are required to view this resource."
            )

        return view_func(request, *args, **kwargs)

    return _wrapped_view
