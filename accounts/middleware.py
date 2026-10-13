"""
accounts/middleware.py
----------------------
Tenant isolation middleware for JewelDesk.

Resolves the active tenant for the authenticated user and binds it to `request.tenant`.
"""

from .models import Tenant


class TenantMiddleware:
    """Resolve request.tenant for the current request.

    Resolution strategy:
    1. Unauthenticated requests -> request.tenant is None.
    2. Active employee linked to user -> request.tenant = employee.tenant.
    3. User owns one or more active tenants -> request.tenant = first active owned tenant.
    4. Superuser fallback -> first active tenant in system, or None.
    5. Non-admin regular user with no tenant -> request.tenant is None.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        request.tenant = None

        if user and user.is_authenticated:
            try:
                # 1. Active employee profile with tenant
                emp = getattr(user, 'employee_profile', None)
                if emp and getattr(emp, 'tenant_id', None) and emp.status == 'Active' and getattr(emp.tenant, 'is_active', False):
                    request.tenant = emp.tenant
                else:
                    # 2. Owned tenant
                    owned = user.owned_tenants.filter(is_active=True).first()
                    if owned:
                        request.tenant = owned
                    elif user.is_superuser:
                        # Superuser fallback: default to first active tenant if available
                        request.tenant = Tenant.objects.filter(is_active=True).first()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("TenantMiddleware resolution notice: %s", e)
                request.tenant = None

        return self.get_response(request)
