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
                emp = getattr(user, '_cached_employee_profile', None)
                if emp is None and not getattr(user, '_checked_employee_profile', False):
                    try:
                        emp = user.employee_profile
                    except Exception:
                        emp = None
                    user._cached_employee_profile = emp
                    user._checked_employee_profile = True

                if emp and getattr(emp, 'tenant_id', None) and emp.status == 'Active' and getattr(emp.tenant, 'is_active', False):
                    request.tenant = emp.tenant
                else:
                    # 2. Owned tenant
                    owned = getattr(user, '_cached_owned_tenant', None)
                    if owned is None:
                        owned = user.owned_tenants.filter(is_active=True).first()
                        user._cached_owned_tenant = owned

                    if owned:
                        request.tenant = owned
                        # Only run ensure_tenant_admin once per session / 24h to avoid 15+ redundant DB queries on every click
                        if hasattr(request, 'session') and not request.session.get('tenant_admin_ensured'):
                            from django.core.cache import cache
                            cache_key = f'tenant_admin_ensured:{owned.id}:{user.id}'
                            if not cache.get(cache_key):
                                try:
                                    from team.models import Employee
                                    Employee.ensure_tenant_admin(owned, user)
                                    cache.set(cache_key, True, timeout=86400)
                                except Exception:
                                    pass
                            request.session['tenant_admin_ensured'] = True
                    elif user.is_superuser:
                        # Superuser resolution: bind tenant ONLY if actively in an authorized impersonation session
                        impersonated_id = None
                        if hasattr(request, 'session'):
                            impersonated_id = request.session.get('impersonated_tenant_id')
                        if impersonated_id:
                            request.tenant = Tenant.objects.filter(pk=impersonated_id, is_active=True).first()
                        else:
                            # If superuser explicitly owns a test showroom, use that; otherwise None (platform operator)
                            request.tenant = user.owned_tenants.filter(is_active=True).first()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("TenantMiddleware resolution notice: %s", e)
                request.tenant = None

        # Enforce business category routing protection
        if user and user.is_authenticated and request.tenant and not user.is_superuser:
            path = getattr(request, 'path_info', '')
            # Retail routes accessed by pure wholesale business
            if not request.tenant.is_retail:
                RETAIL_PREFIXES = ('/sales/', '/customers/', '/custom-orders/', '/enquiries/', '/old-gold/')
                if any(path.startswith(prefix) for prefix in RETAIL_PREFIXES):
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or '/api/' in path:
                        from django.http import JsonResponse
                        return JsonResponse({'error': 'Module not available for wholesale accounts.'}, status=403)
                    try:
                        from django.contrib import messages
                        messages.warning(request, "Retail showroom features are not enabled for wholesale accounts.")
                    except Exception:
                        pass
                    from django.shortcuts import redirect
                    return redirect('wholesale:dashboard')

            # Wholesale routes accessed by pure retail business
            if not request.tenant.is_wholesale:
                if path.startswith('/wholesale/'):
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or '/api/' in path:
                        from django.http import JsonResponse
                        return JsonResponse({'error': 'Module not available for retail accounts.'}, status=403)
                    try:
                        from django.contrib import messages
                        messages.warning(request, "Wholesale B2B features are not enabled for retail accounts.")
                    except Exception:
                        pass
                    from django.shortcuts import redirect
                    return redirect('dashboard')

        return self.get_response(request)
