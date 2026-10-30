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


class TenantTrialMiddleware:
    """
    Enforces server-side 15-day Free Trial expiry and subscription validity per Tenant.

    Critical Business Rules:
    1. The trial belongs to the accounts.Tenant, NOT to individual employees, users, or branches.
    2. All employees and branches belonging to the same Tenant share the identical trial status.
    3. Platform superusers (user.is_superuser) and /super-admin/ or /admin/ routes are strictly exempt.
    4. When trial expires:
       - Regular HTML requests -> redirect to accounts:trial_expired.
       - AJAX / API requests -> return JSON 403 Forbidden with trial_expired error payload.
    5. Existing customer accounts (core/paid plans) are protected and continue normally.
    6. Business data is never modified or deleted upon trial expiry; access is simply restricted.
    """

    EXEMPT_URL_PREFIXES = (
        '/super-admin/',
        '/admin/',
        '/accounts/login/',
        '/accounts/logout/',
        '/accounts/signup/',
        '/signup/',
        '/accounts/password-reset/',
        '/accounts/trial-expired/',
        '/accounts/set-language/',
        '/support/',
        '/static/',
        '/media/',
        '/favicon.ico',
        '/manifest.json',
        '/sw.js',
        '/offline/',
        '/api/app-version/',
        '/download-app/',
        '/download-apk/',
        '/download-brochure/',
        '/view-brochure/',
        '/brochure/',
        '/download-report/',
        '/view-report/',
        '/api/system/migrate/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = getattr(request, 'path_info', '') or request.path

        # 1. Bypass exempt routes
        if any(path.startswith(prefix) for prefix in self.EXEMPT_URL_PREFIXES):
            return self.get_response(request)

        user = getattr(request, 'user', None)

        # 2. Unauthenticated requests are handled by login_required / auth views
        if not user or not user.is_authenticated:
            return self.get_response(request)

        # 3. Platform superusers are strictly exempt from trial restrictions
        if user.is_superuser:
            return self.get_response(request)

        # 4. Resolve tenant context
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return self.get_response(request)

        # 5. Check subscription status
        from django.utils import timezone
        sub = getattr(tenant, 'subscription', None)

        # Auto-provision 15-day free trial if tenant has no subscription at all
        if not sub:
            from super_admin.trial_services import create_tenant_trial
            sub = create_tenant_trial(tenant)

        is_blocked = False
        if sub:
            from super_admin.models import TenantSubscription
            if sub.status in (TenantSubscription.STATUS_SUSPENDED, getattr(TenantSubscription, 'STATUS_EXPIRED', 'expired')):
                is_blocked = True
            elif sub.expires_at and timezone.now() > sub.expires_at:
                is_blocked = True
                if sub.status != 'expired':
                    try:
                        sub.status = 'expired'
                        sub.save(update_fields=['status', 'updated_at'])
                    except Exception:
                        pass
        else:
            is_blocked = True

        if is_blocked:
            # Check for API / AJAX requests
            is_ajax = (
                request.headers.get('x-requested-with') == 'XMLHttpRequest'
                or '/api/' in path
                or 'application/json' in request.headers.get('accept', '')
                or getattr(request, 'content_type', '') == 'application/json'
            )
            if is_ajax:
                from django.http import JsonResponse
                return JsonResponse({
                    'error': 'trial_expired',
                    'message': f"Your 15-day free trial for '{tenant.name}' has expired. Please renew your subscription to continue.",
                    'expired_at': sub.expires_at.isoformat() if (sub and sub.expires_at) else None,
                    'tenant_id': tenant.id,
                    'tenant_name': tenant.name,
                    'support_contact': {
                        'phone': '+91 98765 43210',
                        'email': 'support@jweldesk.com',
                        'whatsapp': '+91 98765 43210'
                    }
                }, status=403)

            from django.shortcuts import redirect
            return redirect('accounts:trial_expired')

        # Attach helper attributes for template layer
        request.tenant_subscription = sub

        return self.get_response(request)

