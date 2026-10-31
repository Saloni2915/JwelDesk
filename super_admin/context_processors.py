"""
super_admin/context_processors.py
---------------------------------
Template context processor for Super Admin impersonation banner and platform links.
"""

from accounts.models import Tenant


def super_admin_context(request):
    """Expose impersonation state and platform admin indicators to templates."""
    is_impersonating = getattr(request, 'is_impersonated', False)
    impersonator_username = getattr(request, 'impersonator_username', None)
    impersonated_tenant = None

    if is_impersonating:
        tenant_id = getattr(request, 'impersonated_tenant_id', None)
        if tenant_id:
            try:
                impersonated_tenant = Tenant.objects.filter(pk=tenant_id).first()
            except Exception:
                impersonated_tenant = None

    user = getattr(request, 'user', None)
    is_platform_admin = (
        bool(user and user.is_authenticated and user.is_superuser)
        and not is_impersonating
    )

    sales_crm_counts = {}
    if is_platform_admin or (user and user.is_authenticated and user.is_staff):
        try:
            from .sales_views import get_sales_crm_stage_counts
            sales_crm_counts = get_sales_crm_stage_counts()
        except Exception:
            sales_crm_counts = {}

    return {
        'is_impersonating': is_impersonating,
        'impersonator_username': impersonator_username,
        'impersonated_tenant': impersonated_tenant,
        'impersonation_started_at': request.session.get('impersonation_started_at') if is_impersonating else None,
        'is_platform_admin': is_platform_admin,
        'sales_crm_counts': sales_crm_counts,
    }
