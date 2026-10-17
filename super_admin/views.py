"""
super_admin/views.py
--------------------
HTTP handlers for the JewelDesk Super Admin Portal.
Provides platform analytics, customer/tenant management, append-only audit logging,
and secure, reversible support impersonation.
"""

from datetime import timedelta
import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Tenant
from .decorators import super_admin_required
from .models import PlatformAuditLog

User = get_user_model()
logger = logging.getLogger('super_admin')


def get_client_ip(request):
    """Safely extract remote client IP address respecting reverse proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


# ============================================================================
# 1. Dashboard Overview
# ============================================================================

@super_admin_required
def dashboard_view(request):
    """Main platform overview dashboard displaying database-backed metrics."""
    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    # Core tenant counts
    total_tenants = Tenant.objects.count()
    active_tenants = Tenant.objects.filter(is_active=True).count()
    inactive_tenants = Tenant.objects.filter(is_active=False).count()

    # User & Employee aggregates across tenants
    total_users = User.objects.count()
    total_owners = User.objects.filter(owned_tenants__isnull=False).distinct().count()

    from team.models import Employee
    total_employees = Employee.objects.count()

    # Registration growth metrics
    new_tenants_7d = Tenant.objects.filter(created_at__gte=seven_days_ago).count()
    new_tenants_30d = Tenant.objects.filter(created_at__gte=thirty_days_ago).count()

    # Recent tenant registrations
    recent_tenants = (
        Tenant.objects
        .select_related('owner')
        .annotate(employee_count=Count('employees'))
        .order_by('-created_at')[:8]
    )

    # Recent platform audit logs (resilient if table not yet migrated)
    try:
        recent_activity = list(
            PlatformAuditLog.objects
            .select_related('actor', 'target_tenant', 'target_user')
            .order_by('-created_at')[:10]
        )
    except Exception as e:
        logger.warning("Audit log table query deferred: %s", e)
        recent_activity = []

    context = {
        'total_tenants': total_tenants,
        'active_tenants': active_tenants,
        'inactive_tenants': inactive_tenants,
        'total_users': total_users,
        'total_owners': total_owners,
        'total_employees': total_employees,
        'new_tenants_7d': new_tenants_7d,
        'new_tenants_30d': new_tenants_30d,
        'recent_tenants': recent_tenants,
        'recent_activity': recent_activity,
        # Explicit distinction of unavailable metrics
        'billing_configured': False,
        'billing_status_label': 'Not Configured (No billing module installed)',
    }
    return render(request, 'super_admin/dashboard.html', context)


# ============================================================================
# 2. Showroom / Tenant Management
# ============================================================================

@super_admin_required
def showroom_list_view(request):
    """Searchable, filterable, and paginated list of all showroom tenants."""
    qs = (
        Tenant.objects
        .select_related('owner', 'company_settings')
        .annotate(employee_count=Count('employees'))
        .order_by('-created_at')
    )

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(slug__icontains=q) |
            Q(owner__username__icontains=q) |
            Q(owner__email__icontains=q) |
            Q(owner__first_name__icontains=q) |
            Q(owner__last_name__icontains=q) |
            Q(company_settings__company_name__icontains=q)
        )

    # Status filter
    status = request.GET.get('status', 'all').strip().lower()
    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'inactive':
        qs = qs.filter(is_active=False)

    # Sorting
    sort = request.GET.get('sort', '-created_at')
    valid_sorts = {
        'name': 'name',
        '-name': '-name',
        'created_at': 'created_at',
        '-created_at': '-created_at',
        'employees': 'employee_count',
        '-employees': '-employee_count',
    }
    order_field = valid_sorts.get(sort, '-created_at')
    qs = qs.order_by(order_field)

    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'q': q,
        'status': status,
        'sort': sort,
        'total_filtered': paginator.count,
    }
    return render(request, 'super_admin/showroom_list.html', context)


@super_admin_required
def showroom_detail_view(request, tenant_id):
    """Detailed view of a single showroom tenant, its owner, staff, and records."""
    tenant = get_object_or_404(
        Tenant.objects.select_related('owner', 'company_settings'),
        pk=tenant_id
    )

    employees = (
        tenant.employees
        .select_related('role', 'user')
        .order_by('employee_id')
    )

    # Safe inventory & activity stats
    try:
        from inventory.models import JewelleryItem
        inventory_count = JewelleryItem.objects.filter(tenant=tenant).count()
    except Exception:
        inventory_count = 0

    try:
        from sales.models import Sale
        sales_count = Sale.objects.filter(tenant=tenant).count()
    except Exception:
        sales_count = 0

    try:
        from customers.models import Customer
        customers_count = Customer.objects.filter(tenant=tenant).count()
    except Exception:
        customers_count = 0

    try:
        from karigar.models import Karigar
        karigar_count = Karigar.objects.filter(tenant=tenant).count()
    except Exception:
        karigar_count = 0

    # Tenant-specific audit logs (resilient if table not yet migrated)
    try:
        audit_logs = list(
            PlatformAuditLog.objects
            .filter(target_tenant=tenant)
            .select_related('actor', 'target_user')
            .order_by('-created_at')[:20]
        )
    except Exception as e:
        logger.warning("Showroom audit log query deferred: %s", e)
        audit_logs = []

    context = {
        'tenant': tenant,
        'employees': employees,
        'inventory_count': inventory_count,
        'sales_count': sales_count,
        'customers_count': customers_count,
        'karigar_count': karigar_count,
        'audit_logs': audit_logs,
        'billing_configured': False,
        'subscription_status_label': 'Core Plan (Standard Tier)',
    }
    return render(request, 'super_admin/showroom_detail.html', context)


@require_POST
@super_admin_required
def toggle_tenant_status_view(request, tenant_id):
    """Activate or deactivate a showroom tenant with audit logging."""
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    reason = request.POST.get('reason', '').strip()

    if not reason:
        messages.error(request, 'A justification or reason is required to change tenant status.')
        return redirect('super_admin:showroom_detail', tenant_id=tenant.id)

    new_status = not tenant.is_active
    tenant.is_active = new_status
    tenant.save(update_fields=['is_active', 'updated_at'])

    action = (
        PlatformAuditLog.ACTION_TENANT_ACTIVATE
        if new_status else
        PlatformAuditLog.ACTION_TENANT_DEACTIVATE
    )

    PlatformAuditLog.objects.create(
        actor=request.user,
        action=action,
        target_tenant=tenant,
        target_user=tenant.owner,
        reason=reason,
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
    )

    status_word = "activated" if new_status else "deactivated (suspended)"
    messages.success(request, f"Showroom '{tenant.name}' has been successfully {status_word}.")
    return redirect('super_admin:showroom_detail', tenant_id=tenant.id)


# ============================================================================
# 3. Secure Customer Impersonation
# ============================================================================

@require_POST
@super_admin_required
def impersonate_start_view(request, tenant_id):
    """Initiate a support impersonation session for a showroom customer.

    Security guards:
    1. Validates that current user is an authenticated superuser.
    2. Prohibits nested impersonation.
    3. Requires target tenant to be active.
    4. Prohibits impersonating any superuser or platform administrator.
    5. Requires support reason / ticket reference.
    6. Creates an immutable audit log entry.
    7. Stores reversible admin credentials in the server-side session.
    """
    tenant = get_object_or_404(Tenant.objects.select_related('owner'), pk=tenant_id)

    if not tenant.is_active:
        messages.error(request, "Cannot impersonate a deactivated showroom. Please reactivate the showroom first.")
        return redirect('super_admin:showroom_detail', tenant_id=tenant.id)

    if request.session.get('impersonator_id'):
        raise PermissionDenied("Nested customer impersonation is prohibited.")

    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, "A reason or support ticket reference is required to begin customer impersonation.")
        return redirect('super_admin:showroom_detail', tenant_id=tenant.id)

    # Determine target user: optional user_id parameter, defaults to tenant owner
    target_user_id = request.POST.get('user_id')
    if target_user_id:
        target_user = get_object_or_404(User, pk=target_user_id)
    else:
        target_user = tenant.owner

    if not target_user or not target_user.is_active:
        messages.error(request, "The target user account is inactive or missing.")
        return redirect('super_admin:showroom_detail', tenant_id=tenant.id)

    # Strict security barrier: never allow impersonating a superuser or staff admin
    if target_user.is_superuser or target_user.is_staff:
        logger.warning(
            "Blocked attempt by %s to impersonate privileged user %s",
            request.user.username, target_user.username
        )
        raise PermissionDenied("Impersonating a Super Admin or platform staff account is prohibited.")

    # Record impersonation start in immutable audit log
    audit_entry = PlatformAuditLog.objects.create(
        actor=request.user,
        action=PlatformAuditLog.ACTION_IMPERSONATION_START,
        target_tenant=tenant,
        target_user=target_user,
        reason=reason,
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
    )

    admin_pk = request.user.pk
    admin_username = request.user.username

    # Switch authentication session to the customer user
    auth_login(request, target_user, backend='django.contrib.auth.backends.ModelBackend')

    # Immediately populate impersonation session keys after login cycles the session
    request.session['impersonator_id'] = admin_pk
    request.session['impersonator_username'] = admin_username
    request.session['impersonated_tenant_id'] = tenant.pk
    request.session['impersonated_tenant_name'] = tenant.name
    request.session['impersonated_user_id'] = target_user.pk
    request.session['impersonation_audit_id'] = audit_entry.pk
    request.session['impersonation_started_at'] = timezone.now().strftime('%d %b %Y, %H:%M UTC')

    messages.warning(
        request,
        f"Impersonation Mode Active: You are now viewing showroom '{tenant.name}' "
        f"as {target_user.username}. All actions will be logged."
    )
    return redirect('dashboard')


@require_POST
def impersonate_exit_view(request):
    """Safely terminate support impersonation and restore the original Super Admin session."""
    impersonator_id = request.session.get('impersonator_id')

    if not impersonator_id:
        messages.info(request, "No active customer impersonation session was found.")
        return redirect('dashboard')

    admin_user = User.objects.filter(pk=impersonator_id, is_superuser=True, is_active=True).first()
    if not admin_user:
        logger.error("Impersonation exit failed: admin user ID %s not found or inactive", impersonator_id)
        from django.contrib.auth import logout as auth_logout
        auth_logout(request)
        messages.error(request, "Original administrator session could not be restored. Please log in again.")
        return redirect('accounts:login')

    target_tenant_id = request.session.get('impersonated_tenant_id')
    target_user_id = request.session.get('impersonated_user_id')

    target_tenant = Tenant.objects.filter(pk=target_tenant_id).first() if target_tenant_id else None
    target_user = User.objects.filter(pk=target_user_id).first() if target_user_id else None

    # Record impersonation end in audit log
    PlatformAuditLog.objects.create(
        actor=admin_user,
        action=PlatformAuditLog.ACTION_IMPERSONATION_END,
        target_tenant=target_tenant,
        target_user=target_user,
        reason="Impersonation session cleanly ended by administrator",
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
    )

    # Clean up all impersonation markers
    for key in (
        'impersonator_id',
        'impersonator_username',
        'impersonated_tenant_id',
        'impersonated_tenant_name',
        'impersonated_user_id',
        'impersonation_audit_id',
        'impersonation_started_at',
    ):
        request.session.pop(key, None)

    # Restore admin session
    auth_login(request, admin_user, backend='django.contrib.auth.backends.ModelBackend')

    messages.success(request, f"Customer impersonation ended. Restored Super Admin session for {admin_user.username}.")

    if target_tenant:
        return redirect('super_admin:showroom_detail', tenant_id=target_tenant.id)
    return redirect('super_admin:showroom_list')


# ============================================================================
# 4. Audit & Activity Logs
# ============================================================================

@super_admin_required
def audit_log_view(request):
    """Searchable, filterable audit log of all platform administrative operations."""
    qs = (
        PlatformAuditLog.objects
        .select_related('actor', 'target_tenant', 'target_user')
        .order_by('-created_at')
    )

    action_filter = request.GET.get('action', '').strip()
    if action_filter:
        qs = qs.filter(action=action_filter)

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(actor__username__icontains=q) |
            Q(target_tenant__name__icontains=q) |
            Q(target_user__username__icontains=q) |
            Q(reason__icontains=q) |
            Q(ip_address__icontains=q)
        )

    try:
        paginator = Paginator(qs, 25)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        total_logs = paginator.count
    except Exception as e:
        logger.warning("Audit log table query deferred: %s", e)
        page_obj = []
        total_logs = 0

    context = {
        'page_obj': page_obj,
        'action_filter': action_filter,
        'action_choices': PlatformAuditLog.ACTION_CHOICES,
        'q': q,
        'total_logs': total_logs,
    }
    return render(request, 'super_admin/audit_logs.html', context)


# ============================================================================
# 5. Subscriptions (Status View)
# ============================================================================

@super_admin_required
def subscriptions_view(request):
    """Subscription & billing module status view.

    Clearly informs the Super Admin that no third-party billing gateway
    or subscription tier schema is installed in the current database.
    """
    total_tenants = Tenant.objects.count()
    active_tenants = Tenant.objects.filter(is_active=True).count()

    context = {
        'total_tenants': total_tenants,
        'active_tenants': active_tenants,
        'billing_configured': False,
    }
    return render(request, 'super_admin/subscriptions.html', context)


# ============================================================================
# 6. Platform Settings
# ============================================================================

@super_admin_required
def settings_view(request):
    """Platform technical configuration and security status overview."""
    import sys
    import django
    from django.conf import settings as dj_settings

    db_engine = dj_settings.DATABASES['default'].get('ENGINE', '')
    db_host = dj_settings.DATABASES['default'].get('HOST', 'localhost')
    masked_db = db_host[:4] + "..." + db_host[-10:] if len(db_host) > 15 else db_host

    context = {
        'python_version': sys.version.split()[0],
        'django_version': django.get_version(),
        'db_engine': db_engine.split('.')[-1],
        'db_host_masked': masked_db,
        'debug_mode': dj_settings.DEBUG,
        'time_zone': dj_settings.TIME_ZONE,
        'media_storage': getattr(dj_settings, 'DEFAULT_FILE_STORAGE', 'default_storage'),
    }
    return render(request, 'super_admin/settings.html', context)
