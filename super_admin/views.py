"""
super_admin/views.py
--------------------
HTTP handlers for the JewelDesk Super Admin Portal.
Provides platform analytics, customer/tenant management, append-only audit logging,
and secure, reversible support impersonation.
"""
import csv
from datetime import timedelta
from decimal import Decimal
import logging
import urllib.parse

from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Tenant
from .decorators import super_admin_required
from .proposal_pdf import build_proposal_pdf
from .models import (
    PlatformAuditLog,
    TenantSubscription,
    SubscriptionPayment,
    PlatformProposal,
    PlatformDemoLead,
    PlatformSupportTicket,
    PlatformTicketMessage,
    CouponDesignTemplate,
    CouponPrintBatch,
    CouponBatchItem,
)
from .forms import (
    PlatformDemoLeadForm,
    DemoMeetingScheduleForm,
    PublicDemoRequestForm,
    PlatformSupportTicketForm,
    CouponDesignTemplateForm,
    CouponPrintBatchForm,
)
from .forms_support import StaffTicketReplyForm
from .ai_assistant import ai_summarize_ticket, ai_categorize_ticket
from .coupon_engine import (
    ALLOWED_PLACEHOLDERS,
    generate_unique_batch_codes,
    get_builtin_template_markup,
    render_single_coupon_html,
    sanitize_coupon_css,
    sanitize_coupon_html,
)

User = get_user_model()
logger = logging.getLogger('super_admin')


def get_client_ip(request):
    """Safely extract remote client IP address respecting reverse proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def ensure_all_tenant_subscriptions():
    """Ensure every existing showroom tenant has a corresponding TenantSubscription object."""
    now = timezone.now()
    try:
        tenants_without_sub = Tenant.objects.filter(subscription__isnull=True)
        for t in tenants_without_sub:
            TenantSubscription.objects.create(
                tenant=t,
                plan_name=TenantSubscription.PLAN_CORE,
                status=TenantSubscription.STATUS_ACTIVE if t.is_active else TenantSubscription.STATUS_TRIAL,
                billing_cycle=TenantSubscription.CYCLE_YEARLY,
                price=Decimal('24999.00'),
                discount=Decimal('0.00'),
                payment_status=TenantSubscription.PAYMENT_PAID if t.is_active else TenantSubscription.PAYMENT_PENDING,
                started_at=t.created_at or now,
                expires_at=(t.created_at or now) + timedelta(days=365),
                notes="Auto-provisioned showroom subscription profile."
            )
    except Exception as e:
        logger.warning("Auto-provision subscriptions deferred: %s", e)


# ============================================================================
# 1. Dashboard Overview
# ============================================================================

@super_admin_required
def dashboard_view(request):
    """Main platform overview dashboard displaying database-backed metrics with date filtering."""
    now = timezone.now()
    today = timezone.localdate()

    # 1. Date Range Filter
    period = request.GET.get('period', '30d')
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')

    if start_date_str and end_date_str:
        try:
            from django.utils.dateparse import parse_date
            import datetime
            s_date = parse_date(start_date_str)
            e_date = parse_date(end_date_str)
            if s_date and e_date:
                period_start = timezone.make_aware(datetime.datetime.combine(s_date, datetime.time.min))
                period_end = timezone.make_aware(datetime.datetime.combine(e_date, datetime.time.max))
            else:
                period_start = now - timedelta(days=30)
                period_end = now
        except Exception:
            period_start = now - timedelta(days=30)
            period_end = now
    elif period == '7d':
        period_start = now - timedelta(days=7)
        period_end = now
    elif period == '90d':
        period_start = now - timedelta(days=90)
        period_end = now
    elif period == '1y':
        period_start = now - timedelta(days=365)
        period_end = now
    elif period == 'all':
        period_start = now - timedelta(days=3650)
        period_end = now
    else:
        period = '30d'
        period_start = now - timedelta(days=30)
        period_end = now

    # 2. Core Tenant Counts & Business Types
    total_tenants = Tenant.objects.count()
    active_tenants = Tenant.objects.filter(is_active=True).count()
    inactive_tenants = Tenant.objects.filter(is_active=False).count()
    new_tenants_period = Tenant.objects.filter(created_at__range=(period_start, period_end)).count()

    retail_tenants = Tenant.objects.filter(business_type=Tenant.TYPE_RETAIL).count()
    wholesale_tenants = Tenant.objects.filter(business_type=Tenant.TYPE_WHOLESALE).count()
    hybrid_tenants = Tenant.objects.filter(business_type=Tenant.TYPE_BOTH).count()

    # 3. User & Employee Aggregates
    total_users = User.objects.count()
    total_owners = User.objects.filter(owned_tenants__isnull=False).distinct().count()
    from team.models import Employee
    total_employees = Employee.objects.count()

    # 4. Recent Tenant Registrations
    recent_tenants = (
        Tenant.objects
        .select_related('owner')
        .annotate(employee_count=Count('employees'))
        .order_by('-created_at')[:8]
    )

    # 5. Leads & Demo Meetings Metrics
    try:
        total_leads = PlatformDemoLead.objects.count()
        period_leads = PlatformDemoLead.objects.filter(created_at__range=(period_start, period_end)).count()
        new_leads_count = PlatformDemoLead.objects.filter(status=PlatformDemoLead.STATUS_NEW).count()
        scheduled_demos_count = PlatformDemoLead.objects.filter(status=PlatformDemoLead.STATUS_SCHEDULED).count()
        completed_demos_count = PlatformDemoLead.objects.filter(status=PlatformDemoLead.STATUS_COMPLETED).count()
        converted_leads_count = PlatformDemoLead.objects.filter(converted_tenant__isnull=False).count()
        conversion_rate = round((converted_leads_count / total_leads * 100), 1) if total_leads > 0 else 0

        upcoming_meetings = list(
            PlatformDemoLead.objects
            .filter(status=PlatformDemoLead.STATUS_SCHEDULED, requested_datetime__gte=now)
            .select_related('assigned_staff')
            .order_by('requested_datetime')[:5]
        )
        overdue_followups = list(
            PlatformDemoLead.objects
            .filter(follow_up_date__lt=today)
            .exclude(status__in=[PlatformDemoLead.STATUS_COMPLETED, PlatformDemoLead.STATUS_CANCELLED, PlatformDemoLead.STATUS_NOT_INTERESTED])
            .select_related('assigned_staff')
            .order_by('follow_up_date')[:5]
        )
    except Exception as e:
        logger.warning("Demo lead query deferred: %s", e)
        total_leads = 0
        period_leads = 0
        new_leads_count = 0
        scheduled_demos_count = 0
        completed_demos_count = 0
        converted_leads_count = 0
        conversion_rate = 0
        upcoming_meetings = []
        overdue_followups = []

    # 6. Support Tickets
    try:
        open_tickets_count = PlatformSupportTicket.objects.filter(
            status__in=[PlatformSupportTicket.STATUS_OPEN, PlatformSupportTicket.STATUS_IN_PROGRESS]
        ).count()
        urgent_tickets_count = PlatformSupportTicket.objects.filter(
            priority=PlatformSupportTicket.PRIORITY_URGENT,
            status__in=[PlatformSupportTicket.STATUS_OPEN, PlatformSupportTicket.STATUS_IN_PROGRESS]
        ).count()
    except Exception as e:
        logger.warning("Support ticket query deferred: %s", e)
        open_tickets_count = 0
        urgent_tickets_count = 0

    # 7. Recent Platform Audit Logs
    try:
        recent_activity = list(
            PlatformAuditLog.objects
            .select_related('actor', 'target_tenant', 'target_user')
            .order_by('-created_at')[:10]
        )
    except Exception as e:
        logger.warning("Audit log table query deferred: %s", e)
        recent_activity = []

    # 8. Subscriptions & Verified Revenue
    try:
        ensure_all_tenant_subscriptions()
        total_subscribers = TenantSubscription.objects.count()
        active_subscribers = TenantSubscription.objects.filter(status=TenantSubscription.STATUS_ACTIVE).count()
        trial_subscribers = TenantSubscription.objects.filter(status=TenantSubscription.STATUS_TRIAL).count()
        overdue_subscribers = TenantSubscription.objects.filter(
            status__in=[TenantSubscription.STATUS_OVERDUE, TenantSubscription.STATUS_GRACE_PERIOD]
        ).count()
        suspended_subscribers = TenantSubscription.objects.filter(status=TenantSubscription.STATUS_SUSPENDED).count()

        period_revenue = (
            SubscriptionPayment.objects.filter(created_at__range=(period_start, period_end))
            .aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        )
        total_revenue = SubscriptionPayment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        proposals_count = PlatformProposal.objects.count()
        billing_configured = True
        billing_status_label = f"₹{total_revenue:,.0f} Collected ({active_subscribers} Active)"
    except Exception as e:
        logger.warning("Subscription query deferred: %s", e)
        total_subscribers = 0
        active_subscribers = 0
        trial_subscribers = 0
        overdue_subscribers = 0
        suspended_subscribers = 0
        period_revenue = Decimal('0.00')
        total_revenue = Decimal('0.00')
        proposals_count = 0
        billing_configured = False
        billing_status_label = 'Not Configured'

    context = {
        'period': period,
        'period_start': period_start,
        'period_end': period_end,
        'start_date_str': start_date_str,
        'end_date_str': end_date_str,
        'total_tenants': total_tenants,
        'active_tenants': active_tenants,
        'inactive_tenants': inactive_tenants,
        'new_tenants_period': new_tenants_period,
        'retail_tenants': retail_tenants,
        'wholesale_tenants': wholesale_tenants,
        'hybrid_tenants': hybrid_tenants,
        'total_users': total_users,
        'total_owners': total_owners,
        'total_employees': total_employees,
        'recent_tenants': recent_tenants,
        'recent_activity': recent_activity,
        'total_leads': total_leads,
        'period_leads': period_leads,
        'new_leads_count': new_leads_count,
        'scheduled_demos_count': scheduled_demos_count,
        'completed_demos_count': completed_demos_count,
        'converted_leads_count': converted_leads_count,
        'conversion_rate': conversion_rate,
        'upcoming_meetings': upcoming_meetings,
        'overdue_followups': overdue_followups,
        'open_tickets_count': open_tickets_count,
        'urgent_tickets_count': urgent_tickets_count,
        'billing_configured': billing_configured,
        'billing_status_label': billing_status_label,
        'total_subscribers': total_subscribers,
        'active_subscribers': active_subscribers,
        'trial_subscribers': trial_subscribers,
        'overdue_subscribers': overdue_subscribers,
        'suspended_subscribers': suspended_subscribers,
        'period_revenue': period_revenue,
        'total_revenue': total_revenue,
        'proposals_count': proposals_count,
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

    # Business type filter
    business_type = request.GET.get('business_type', 'all').strip().upper()
    if business_type in (Tenant.TYPE_RETAIL, Tenant.TYPE_WHOLESALE, Tenant.TYPE_BOTH):
        qs = qs.filter(business_type=business_type)

    # Subscription plan filter
    plan = request.GET.get('plan', 'all').strip().lower()
    if plan in ('core', 'pro', 'enterprise', 'trial'):
        qs = qs.filter(subscription__plan_name=plan)

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
        'business_type': business_type,
        'plan': plan,
        'sort': sort,
        'total_filtered': paginator.count,
    }
    return render(request, 'super_admin/showroom_list.html', context)


@super_admin_required
def showroom_detail_view(request, tenant_id):
    """Detailed view of a single showroom tenant, its owner, staff, and SaaS subscription."""
    tenant = get_object_or_404(
        Tenant.objects.select_related('owner', 'company_settings'),
        pk=tenant_id
    )

    employees = (
        tenant.employees
        .select_related('role', 'user')
        .order_by('employee_id')
    )
    employee_count = employees.count()

    # Subscription info
    ensure_all_tenant_subscriptions()
    try:
        subscription = tenant.subscription
    except Exception:
        subscription = None

    # Account tenure
    account_age_days = (timezone.now() - tenant.created_at).days if tenant.created_at else 0

    # Linked demo leads
    try:
        linked_demos = list(tenant.originating_demo_leads.order_by('-created_at')[:5])
    except Exception:
        linked_demos = []

    # Linked support tickets
    try:
        linked_tickets = list(tenant.support_tickets.order_by('-created_at')[:5])
    except Exception:
        linked_tickets = []

    # Tenant-specific audit logs
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
        'employee_count': employee_count,
        'account_age_days': account_age_days,
        'subscription': subscription,
        'linked_demos': linked_demos,
        'linked_tickets': linked_tickets,
        'audit_logs': audit_logs,
        'billing_configured': True if subscription else False,
        'subscription_status_label': subscription.get_plan_name_display() if subscription else 'No Plan Assigned',
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

    # Strict security barrier: never allow impersonating a platform superuser
    if target_user.is_superuser:
        logger.warning(
            "Blocked attempt by %s to impersonate privileged superuser %s",
            request.user.username, target_user.username
        )
        raise PermissionDenied("Impersonating a Super Admin account is prohibited.")

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
# 5. SaaS Subscriptions & Revenue Tracking
# ============================================================================

@super_admin_required
def subscriptions_view(request):
    """SaaS Subscription & Revenue Management Dashboard.

    Displays:
    - How many showrooms are on active plans vs trial vs overdue.
    - Total revenue collected (₹) and payment transactions.
    - Actionable plan upgrades and payment recording modals.
    """
    ensure_all_tenant_subscriptions()

    # Base query for subscriptions
    qs = (
        TenantSubscription.objects
        .select_related('tenant', 'tenant__owner')
        .order_by('-started_at')
    )

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(tenant__name__icontains=q) |
            Q(tenant__slug__icontains=q) |
            Q(tenant__owner__username__icontains=q) |
            Q(tenant__owner__email__icontains=q)
        )

    # Status filter
    status = request.GET.get('status', 'all').strip().lower()
    if status != 'all' and status:
        qs = qs.filter(status=status)

    # Plan filter
    plan = request.GET.get('plan', 'all').strip().lower()
    if plan != 'all' and plan:
        qs = qs.filter(plan_name=plan)

    # Aggregate revenue & count metrics
    total_tenants = Tenant.objects.count()
    active_count = TenantSubscription.objects.filter(status=TenantSubscription.STATUS_ACTIVE).count()
    trial_count = TenantSubscription.objects.filter(status=TenantSubscription.STATUS_TRIAL).count()
    overdue_count = TenantSubscription.objects.filter(
        status__in=[TenantSubscription.STATUS_OVERDUE, TenantSubscription.STATUS_GRACE_PERIOD]
    ).count()

    total_revenue_collected = (
        SubscriptionPayment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    )

    # Estimated Annual Contract Value (ACV) of active accounts
    acv_total = (
        TenantSubscription.objects.filter(status=TenantSubscription.STATUS_ACTIVE)
        .aggregate(total=Sum('price'))['total'] or Decimal('0.00')
    )

    # Recent payment transactions ledger
    recent_payments = (
        SubscriptionPayment.objects
        .select_related('tenant', 'recorded_by')
        .order_by('-payment_date', '-created_at')[:20]
    )

    # Pagination for subscriptions table
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'q': q,
        'status_filter': status,
        'plan_filter': plan,
        'total_tenants': total_tenants,
        'active_count': active_count,
        'trial_count': trial_count,
        'overdue_count': overdue_count,
        'total_revenue_collected': total_revenue_collected,
        'acv_total': acv_total,
        'recent_payments': recent_payments,
        'plan_choices': TenantSubscription.PLAN_CHOICES,
        'status_choices': TenantSubscription.STATUS_CHOICES,
        'cycle_choices': TenantSubscription.CYCLE_CHOICES,
        'payment_status_choices': TenantSubscription.PAYMENT_STATUS_CHOICES,
        'payment_method_choices': SubscriptionPayment.METHOD_CHOICES,
    }
    return render(request, 'super_admin/subscriptions.html', context)


@super_admin_required
@require_POST
def subscription_update_view(request, tenant_id):
    """Update subscription plan, pricing, and status for a showroom tenant."""
    sub = get_object_or_404(TenantSubscription, tenant_id=tenant_id)

    plan_name = request.POST.get('plan_name', sub.plan_name)
    status = request.POST.get('status', sub.status)
    billing_cycle = request.POST.get('billing_cycle', sub.billing_cycle)
    price_raw = request.POST.get('price', str(sub.price))
    discount_raw = request.POST.get('discount', str(sub.discount))
    payment_status = request.POST.get('payment_status', sub.payment_status)
    notes = request.POST.get('notes', sub.notes)

    try:
        sub.price = Decimal(price_raw)
    except Exception:
        pass

    try:
        sub.discount = Decimal(discount_raw)
    except Exception:
        pass

    sub.plan_name = plan_name
    sub.status = status
    sub.billing_cycle = billing_cycle
    sub.payment_status = payment_status
    sub.notes = notes

    expires_at_raw = request.POST.get('expires_at', '').strip()
    if expires_at_raw:
        try:
            from django.utils.dateparse import parse_date
            import datetime
            d = parse_date(expires_at_raw)
            if d:
                sub.expires_at = timezone.make_aware(datetime.datetime.combine(d, datetime.time(23, 59, 59)))
        except Exception as e:
            logger.warning("Error parsing expires_at: %s", e)

    sub.save()

    PlatformAuditLog.objects.create(
        actor=request.user,
        action='SUBSCRIPTION_UPDATE',
        target_tenant=sub.tenant,
        reason=f"Updated subscription to {sub.get_plan_name_display()} ({sub.get_status_display()}) at ₹{sub.price}",
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
    )

    messages.success(request, f"Updated subscription plan for {sub.tenant.name} successfully.")
    return redirect('super_admin:subscriptions')


@super_admin_required
@require_POST
def subscription_record_payment_view(request, tenant_id):
    """Record an incoming payment transaction against a showroom tenant."""
    sub = get_object_or_404(TenantSubscription, tenant_id=tenant_id)

    amount_raw = request.POST.get('amount', '0.00').strip()
    try:
        amount = Decimal(amount_raw)
    except Exception:
        messages.error(request, "Invalid payment amount provided.")
        return redirect('super_admin:subscriptions')

    payment_date_raw = request.POST.get('payment_date', '').strip()
    payment_date = timezone.now().date()
    if payment_date_raw:
        from django.utils.dateparse import parse_date
        parsed = parse_date(payment_date_raw)
        if parsed:
            payment_date = parsed

    payment_method = request.POST.get('payment_method', SubscriptionPayment.METHOD_UPI)
    reference_id = request.POST.get('reference_id', '').strip()
    invoice_number = request.POST.get('invoice_number', '').strip()
    notes = request.POST.get('notes', '').strip()

    payment = SubscriptionPayment.objects.create(
        subscription=sub,
        tenant=sub.tenant,
        amount=amount,
        payment_date=payment_date,
        payment_method=payment_method,
        reference_id=reference_id,
        invoice_number=invoice_number,
        recorded_by=request.user,
        notes=notes
    )

    # Automatically mark subscription as paid and activate if previously overdue
    sub.payment_status = TenantSubscription.PAYMENT_PAID
    if sub.status in [TenantSubscription.STATUS_OVERDUE, TenantSubscription.STATUS_GRACE_PERIOD]:
        sub.status = TenantSubscription.STATUS_ACTIVE
    sub.save(update_fields=['payment_status', 'status', 'updated_at'])

    PlatformAuditLog.objects.create(
        actor=request.user,
        action='PAYMENT_RECORDED',
        target_tenant=sub.tenant,
        reason=f"Recorded ₹{payment.amount} via {payment.get_payment_method_display()} (Ref: {payment.reference_id or 'N/A'})",
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
    )

    messages.success(request, f"Payment of ₹{payment.amount:,.2f} recorded for {sub.tenant.name}.")
    return redirect('super_admin:subscriptions')


# ============================================================================
# 6. Customer Proposals & Quotations
# ============================================================================

@super_admin_required
def proposal_list_view(request):
    """Listing and pipeline overview of all sales proposals sent to prospects."""
    qs = PlatformProposal.objects.select_related('created_by').order_by('-created_at')

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(proposal_number__icontains=q) |
            Q(client_name__icontains=q) |
            Q(client_showroom_name__icontains=q) |
            Q(client_city__icontains=q) |
            Q(client_phone__icontains=q) |
            Q(client_email__icontains=q)
        )

    # Status filter
    status = request.GET.get('status', 'all').strip().lower()
    if status != 'all' and status:
        qs = qs.filter(status=status)

    # Pipeline summary metrics
    total_proposals = PlatformProposal.objects.count()
    accepted_count = PlatformProposal.objects.filter(status=PlatformProposal.STATUS_ACCEPTED).count()
    accepted_value = (
        PlatformProposal.objects.filter(status=PlatformProposal.STATUS_ACCEPTED)
        .aggregate(total=Sum('final_amount'))['total'] or Decimal('0.00')
    )
    pipeline_count = PlatformProposal.objects.filter(
        status__in=[PlatformProposal.STATUS_DRAFT, PlatformProposal.STATUS_SENT, PlatformProposal.STATUS_VIEWED]
    ).count()
    pipeline_value = (
        PlatformProposal.objects.filter(
            status__in=[PlatformProposal.STATUS_DRAFT, PlatformProposal.STATUS_SENT, PlatformProposal.STATUS_VIEWED]
        ).aggregate(total=Sum('final_amount'))['total'] or Decimal('0.00')
    )

    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'q': q,
        'status_filter': status,
        'total_proposals': total_proposals,
        'accepted_count': accepted_count,
        'accepted_value': accepted_value,
        'pipeline_count': pipeline_count,
        'pipeline_value': pipeline_value,
        'status_choices': PlatformProposal.STATUS_CHOICES,
    }
    return render(request, 'super_admin/proposal_list.html', context)


@super_admin_required
def proposal_create_view(request):
    """Create a new proposal / quote for a prospective jewellery showroom."""
    if request.method == 'POST':
        import random
        from django.utils.dateparse import parse_date

        client_name = request.POST.get('client_name', '').strip()
        client_showroom_name = request.POST.get('client_showroom_name', '').strip()
        client_email = request.POST.get('client_email', '').strip()
        client_phone = request.POST.get('client_phone', '').strip()
        client_city = request.POST.get('client_city', '').strip()
        target_plan = request.POST.get('target_plan', TenantSubscription.PLAN_CORE)
        billing_cycle = request.POST.get('billing_cycle', TenantSubscription.CYCLE_YEARLY)

        quoted_amount_raw = request.POST.get('quoted_amount', '29999.00').strip()
        discount_amount_raw = request.POST.get('discount_amount', '0.00').strip()

        try:
            quoted_amount = Decimal(quoted_amount_raw)
        except Exception:
            quoted_amount = Decimal('29999.00')

        try:
            discount_amount = Decimal(discount_amount_raw)
        except Exception:
            discount_amount = Decimal('0.00')

        final_amount = max(Decimal('0.00'), quoted_amount - discount_amount)

        valid_until = None
        valid_until_raw = request.POST.get('valid_until', '').strip()
        if valid_until_raw:
            valid_until = parse_date(valid_until_raw)
        if not valid_until:
            valid_until = (timezone.now() + timedelta(days=15)).date()

        features_summary = request.POST.get('features_summary', '').strip()
        if not features_summary:
            features_summary = (
                "• Complete Jewellery POS & Custom Quotation Generation\n"
                "• BIS Hallmarking & HUID Tag Registry Tracking\n"
                "• Karigar Issue, Receive & Loss/Wastage Ledger\n"
                "• Real-Time Gold & Silver Board Rate Sync\n"
                "• Instant WhatsApp Digital Invoice Delivery\n"
                "• Multi-Device Support (Mobile, Tablet, Desktop POS)\n"
                "• Daily Day-End Cash & Bank Tally Reports\n"
                "• Dedicated Onboarding & 99.9% Uptime Cloud Infrastructure"
            )

        terms_notes = request.POST.get('terms_notes', '').strip()
        if not terms_notes:
            terms_notes = (
                "1. Pricing is inclusive of all standard cloud hosting and daily backups.\n"
                "2. 1-on-1 staff training and showroom data onboarding included at zero extra cost.\n"
                "3. Validity: This commercial proposal is valid for 15 days from issue.\n"
                "4. Payment Terms: 100% advance on activation via UPI, NEFT, or Bank Transfer."
            )

        # Generate unique proposal number
        date_str = timezone.now().strftime('%Y%m')
        rand_num = random.randint(100, 999)
        proposal_number = f"JD-{date_str}-{rand_num}"
        while PlatformProposal.objects.filter(proposal_number=proposal_number).exists():
            rand_num = random.randint(100, 999)
            proposal_number = f"JD-{date_str}-{rand_num}"

        proposal = PlatformProposal.objects.create(
            proposal_number=proposal_number,
            client_name=client_name,
            client_showroom_name=client_showroom_name,
            client_email=client_email,
            client_phone=client_phone,
            client_city=client_city,
            target_plan=target_plan,
            billing_cycle=billing_cycle,
            quoted_amount=quoted_amount,
            discount_amount=discount_amount,
            final_amount=final_amount,
            valid_until=valid_until,
            features_summary=features_summary,
            terms_notes=terms_notes,
            status=PlatformProposal.STATUS_DRAFT,
            created_by=request.user
        )

        PlatformAuditLog.objects.create(
            actor=request.user,
            action='PROPOSAL_CREATED',
            reason=f"Created proposal {proposal.proposal_number} for {proposal.client_showroom_name} (₹{proposal.final_amount})",
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
        )

        messages.success(request, f"Proposal {proposal.proposal_number} created successfully!")
        return redirect('super_admin:proposal_detail', proposal_id=proposal.id)

    # GET request: default initial form data
    default_valid_until = (timezone.now() + timedelta(days=15)).strftime('%Y-%m-%d')
    default_features = (
        "• Complete Jewellery POS & Custom Quotation Generation\n"
        "• BIS Hallmarking & HUID Tag Registry Tracking\n"
        "• Karigar Issue, Receive & Loss/Wastage Ledger\n"
        "• Real-Time Gold & Silver Board Rate Sync\n"
        "• Instant WhatsApp Digital Invoice Delivery\n"
        "• Multi-Device Support (Mobile, Tablet, Desktop POS)\n"
        "• Daily Day-End Cash & Bank Tally Reports\n"
        "• Dedicated Onboarding & 99.9% Uptime Cloud Infrastructure"
    )
    default_terms = (
        "1. Pricing is inclusive of all standard cloud hosting and daily backups.\n"
        "2. 1-on-1 staff training and showroom data onboarding included at zero extra cost.\n"
        "3. Validity: This commercial proposal is valid for 15 days from issue.\n"
        "4. Payment Terms: 100% advance on activation via UPI, NEFT, or Bank Transfer."
    )

    context = {
        'default_valid_until': default_valid_until,
        'default_features': default_features,
        'default_terms': default_terms,
        'plan_choices': TenantSubscription.PLAN_CHOICES,
        'cycle_choices': TenantSubscription.CYCLE_CHOICES,
    }
    return render(request, 'super_admin/proposal_create.html', context)


@super_admin_required
def proposal_detail_view(request, proposal_id):
    """View proposal details, copy share link, update status, and send via WhatsApp."""
    proposal = get_object_or_404(PlatformProposal.objects.select_related('created_by'), id=proposal_id)

    # Generate public client share URL
    share_path = reverse('super_admin:proposal_client_view', kwargs={'token': proposal.share_token})
    client_share_url = request.build_absolute_uri(share_path)

    # Format phone for WhatsApp
    clean_phone = ''.join(c for c in proposal.client_phone if c.isdigit())
    if len(clean_phone) == 10:
        clean_phone = '91' + clean_phone

    # Compose pre-filled WhatsApp pitch message
    wa_msg = (
        f"Namaste {proposal.client_name} ji,\n\n"
        f"Here is your official proposal for the JewelDesk Jewellery Management Suite for {proposal.client_showroom_name}.\n\n"
        f"📋 Plan: {proposal.get_target_plan_display()} ({proposal.get_billing_cycle_display()})\n"
        f"💰 Investment: ₹{proposal.final_amount:,.0f}\n"
        f"⏳ Valid until: {proposal.valid_until.strftime('%d %b %Y') if proposal.valid_until else 'N/A'}\n\n"
        f"You can review your customized proposal, feature inclusions, and onboarding roadmap here:\n"
        f"{client_share_url}\n\n"
        f"Warm regards,\n"
        f"JewelDesk SaaS Platform Team"
    )
    encoded_wa = urllib.parse.quote(wa_msg)
    wa_link = f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded_wa}" if clean_phone else f"https://api.whatsapp.com/send?text={encoded_wa}"

    features_list = [f.strip() for f in proposal.features_summary.split('\n') if f.strip()]
    terms_list = [t.strip() for t in proposal.terms_notes.split('\n') if t.strip()]

    context = {
        'proposal': proposal,
        'client_share_url': client_share_url,
        'wa_link': wa_link,
        'features_list': features_list,
        'terms_list': terms_list,
        'status_choices': PlatformProposal.STATUS_CHOICES,
    }
    return render(request, 'super_admin/proposal_detail.html', context)


@super_admin_required
@require_POST
def proposal_status_update_view(request, proposal_id):
    """Change proposal status (e.g. mark as sent, accepted, declined)."""
    proposal = get_object_or_404(PlatformProposal, id=proposal_id)
    new_status = request.POST.get('status', proposal.status)

    if new_status in dict(PlatformProposal.STATUS_CHOICES):
        proposal.status = new_status
        proposal.save(update_fields=['status', 'updated_at'])

        PlatformAuditLog.objects.create(
            actor=request.user,
            action='PROPOSAL_STATUS_UPDATE',
            reason=f"Updated proposal {proposal.proposal_number} status to {proposal.get_status_display()}",
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
        )
        messages.success(request, f"Proposal status updated to '{proposal.get_status_display()}'.")

    return redirect('super_admin:proposal_detail', proposal_id=proposal.id)


@super_admin_required
def proposal_download_pdf_view(request, proposal_id):
    """Download official B2B Proposal / Quotation as a branded PDF document."""
    proposal = get_object_or_404(PlatformProposal, id=proposal_id)
    pdf_bytes = build_proposal_pdf(proposal)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f"Proposal-{proposal.proposal_number}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    try:
        PlatformAuditLog.objects.create(
            actor=request.user,
            action='PROPOSAL_DOWNLOAD',
            reason=f"Downloaded PDF for proposal {proposal.proposal_number} ({proposal.client_showroom_name})",
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
        )
    except Exception as e:
        logger.warning("Audit log for proposal download deferred: %s", e)

    return response


def proposal_client_view(request, token):
    """Public, customer-facing proposal presentation page.

    Accessible by prospective clients via unique shareable token.
    Automatically marks proposal as 'viewed' on first open.
    Allows prospective client to accept the proposal with a single click.
    """
    proposal = get_object_or_404(PlatformProposal, share_token=token)

    # Track client view
    if proposal.status == PlatformProposal.STATUS_SENT:
        proposal.status = PlatformProposal.STATUS_VIEWED
        proposal.save(update_fields=['status', 'updated_at'])

    # Client acceptance action
    if request.method == 'POST' and request.POST.get('action') == 'accept':
        if proposal.status in [PlatformProposal.STATUS_SENT, PlatformProposal.STATUS_VIEWED, PlatformProposal.STATUS_DRAFT]:
            proposal.status = PlatformProposal.STATUS_ACCEPTED
            proposal.save(update_fields=['status', 'updated_at'])
            messages.success(request, "Congratulations! You have accepted the proposal. Our executive team will reach out immediately.")
            return redirect('super_admin:proposal_client_view', token=token)

    features_list = [f.strip() for f in proposal.features_summary.split('\n') if f.strip()]
    terms_list = [t.strip() for t in proposal.terms_notes.split('\n') if t.strip()]

    context = {
        'proposal': proposal,
        'features_list': features_list,
        'terms_list': terms_list,
    }
    return render(request, 'super_admin/proposal_client_view.html', context)


def proposal_client_download_pdf_view(request, token):
    """Allow prospective customer to download their official proposal PDF directly."""
    proposal = get_object_or_404(PlatformProposal, share_token=token)
    pdf_bytes = build_proposal_pdf(proposal)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f"Proposal-{proposal.proposal_number}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ============================================================================
# 7. Platform Settings
# ============================================================================

@super_admin_required
def settings_view(request):
    """Platform configuration, SaaS subscription defaults, and technical runtime status."""
    import sys
    import django
    from django.conf import settings as dj_settings
    from .models import CouponDesignTemplate

    db_engine = dj_settings.DATABASES['default'].get('ENGINE', '')
    db_host = dj_settings.DATABASES['default'].get('HOST', 'localhost')
    masked_db = db_host[:4] + "..." + db_host[-10:] if len(db_host) > 15 else db_host

    total_templates = CouponDesignTemplate.objects.count()
    active_templates = CouponDesignTemplate.objects.filter(is_archived=False).count()

    context = {
        'python_version': sys.version.split()[0],
        'django_version': django.get_version(),
        'db_engine': db_engine.split('.')[-1],
        'db_host_masked': masked_db,
        'debug_mode': dj_settings.DEBUG,
        'time_zone': dj_settings.TIME_ZONE,
        'media_storage': getattr(dj_settings, 'DEFAULT_FILE_STORAGE', 'default_storage'),
        'platform_name': 'JewelDesk SaaS Platform',
        'platform_company': 'JewelDesk Technologies Pvt Ltd',
        'support_email': 'support@jeweldesk.in',
        'support_phone': '+91 98765 43210',
        'platform_website': 'https://jeweldesk.in',
        'default_trial_days': 14,
        'default_plan': 'Core Showroom Standard Tier',
        'grace_period_days': 7,
        'platform_currency': 'INR (₹)',
        'global_coupon_templates_count': total_templates,
        'global_active_templates_count': active_templates,
    }
    return render(request, 'super_admin/settings.html', context)


# ============================================================================
# 8. Demo Meetings & Lead Management
# ============================================================================

@super_admin_required
def demo_list_view(request):
    """Searchable, filterable list of prospective showroom demo leads."""
    qs = PlatformDemoLead.objects.select_related('assigned_staff', 'converted_tenant').order_by('-created_at')

    # Tab filters
    tab = request.GET.get('tab', 'all').strip().lower()
    now = timezone.now()
    today = timezone.localdate()

    if tab == 'upcoming':
        qs = qs.filter(status=PlatformDemoLead.STATUS_SCHEDULED, requested_datetime__gte=now).order_by('requested_datetime')
    elif tab == 'followup':
        qs = qs.filter(follow_up_date__lt=today).exclude(
            status__in=[PlatformDemoLead.STATUS_COMPLETED, PlatformDemoLead.STATUS_CANCELLED, PlatformDemoLead.STATUS_NOT_INTERESTED]
        ).order_by('follow_up_date')
    elif tab == 'scheduled':
        qs = qs.filter(status=PlatformDemoLead.STATUS_SCHEDULED)
    elif tab == 'completed':
        qs = qs.filter(status=PlatformDemoLead.STATUS_COMPLETED)
    elif tab == 'converted':
        qs = qs.filter(converted_tenant__isnull=False)
    elif tab == 'lost':
        qs = qs.filter(status=PlatformDemoLead.STATUS_NOT_INTERESTED)
    elif tab == 'new':
        qs = qs.filter(status=PlatformDemoLead.STATUS_NEW)

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(lead_name__icontains=q) |
            Q(contact_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(email__icontains=q) |
            Q(city__icontains=q)
        )

    # Status filter
    status = request.GET.get('status', 'all').strip()
    if status != 'all' and status:
        qs = qs.filter(status=status)

    # Business type filter
    business_type = request.GET.get('business_type', 'all').strip().upper()
    if business_type != 'ALL' and business_type:
        qs = qs.filter(business_type=business_type)

    # Source filter
    source = request.GET.get('source', 'all').strip()
    if source != 'all' and source:
        qs = qs.filter(source=source)

    # Counts for tabs
    all_count = PlatformDemoLead.objects.count()
    upcoming_count = PlatformDemoLead.objects.filter(status=PlatformDemoLead.STATUS_SCHEDULED, requested_datetime__gte=now).count()
    followup_count = PlatformDemoLead.objects.filter(follow_up_date__lt=today).exclude(
        status__in=[PlatformDemoLead.STATUS_COMPLETED, PlatformDemoLead.STATUS_CANCELLED, PlatformDemoLead.STATUS_NOT_INTERESTED]
    ).count()
    completed_count = PlatformDemoLead.objects.filter(status=PlatformDemoLead.STATUS_COMPLETED).count()
    converted_count = PlatformDemoLead.objects.filter(converted_tenant__isnull=False).count()

    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'tab': tab,
        'q': q,
        'status_filter': status,
        'business_type_filter': business_type,
        'source_filter': source,
        'total_filtered': paginator.count,
        'all_count': all_count,
        'upcoming_count': upcoming_count,
        'followup_count': followup_count,
        'completed_count': completed_count,
        'converted_count': converted_count,
        'status_choices': PlatformDemoLead.STATUS_CHOICES,
        'mode_choices': PlatformDemoLead.MODE_CHOICES,
        'source_choices': PlatformDemoLead.SOURCE_CHOICES,
        'business_type_choices': [
            ('RETAIL', 'Retail Showroom'),
            ('WHOLESALE', 'Wholesaler / Supplier'),
            ('BOTH', 'Retail & Wholesale'),
            ('OTHER', 'Other'),
        ],
    }
    return render(request, 'super_admin/demo_list.html', context)


@super_admin_required
def demo_create_view(request):
    """Create a new demo lead record manually."""
    if request.method == 'POST':
        form = PlatformDemoLeadForm(request.POST)
        if form.is_valid():
            lead = form.save()
            PlatformAuditLog.objects.create(
                actor=request.user,
                action='DEMO_CREATE',
                reason=f"Created demo lead for '{lead.lead_name}' ({lead.contact_name})",
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
            )
            messages.success(request, f"Demo lead for '{lead.lead_name}' recorded successfully.")
            return redirect('super_admin:demo_detail', lead_id=lead.id)
    else:
        form = PlatformDemoLeadForm(initial={'meeting_mode': 'online', 'status': 'new'})

    context = {
        'form': form,
        'page_title': 'Add New Demo Lead / Meeting',
    }
    return render(request, 'super_admin/demo_form.html', context)


@super_admin_required
def demo_detail_view(request, lead_id):
    """View details of a single demo lead, meetings, and interaction timeline."""
    lead = get_object_or_404(
        PlatformDemoLead.objects.select_related('assigned_staff', 'converted_tenant'),
        pk=lead_id
    )
    schedule_form = DemoMeetingScheduleForm(initial={
        'action_type': 'schedule' if lead.status == PlatformDemoLead.STATUS_NEW else 'reschedule',
        'meeting_datetime': lead.requested_datetime,
        'meeting_mode': lead.meeting_mode,
        'meeting_link': lead.meeting_link,
        'assigned_staff': lead.assigned_staff,
        'follow_up_date': lead.follow_up_date,
        'next_action': lead.next_action,
    })

    # Available tenants for manual conversion linkage
    tenants = Tenant.objects.filter(is_active=True).order_by('name')[:100]

    context = {
        'lead': lead,
        'schedule_form': schedule_form,
        'tenants': tenants,
    }
    return render(request, 'super_admin/demo_detail.html', context)


@super_admin_required
def demo_edit_view(request, lead_id):
    """Edit lead details and contact information."""
    lead = get_object_or_404(PlatformDemoLead, pk=lead_id)
    if request.method == 'POST':
        form = PlatformDemoLeadForm(request.POST, instance=lead)
        if form.is_valid():
            form.save()
            PlatformAuditLog.objects.create(
                actor=request.user,
                action='DEMO_UPDATE',
                reason=f"Updated demo lead #{lead.id} ({lead.lead_name})",
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
            )
            messages.success(request, f"Lead '{lead.lead_name}' updated successfully.")
            return redirect('super_admin:demo_detail', lead_id=lead.id)
    else:
        form = PlatformDemoLeadForm(instance=lead)

    context = {
        'form': form,
        'lead': lead,
        'page_title': f"Edit Lead — {lead.lead_name}",
    }
    return render(request, 'super_admin/demo_form.html', context)


@super_admin_required
@require_POST
def demo_action_view(request, lead_id):
    """Handle scheduling, rescheduling, completing, or cancelling a demo meeting."""
    lead = get_object_or_404(PlatformDemoLead, pk=lead_id)
    form = DemoMeetingScheduleForm(request.POST)

    if form.is_valid():
        action_type = form.cleaned_data['action_type']
        notes_input = form.cleaned_data.get('notes', '').strip()
        follow_up = form.cleaned_data.get('follow_up_date')
        next_action = form.cleaned_data.get('next_action', '').strip()

        now_str = timezone.now().strftime('%Y-%m-%d %H:%M')
        notes_entry = f"[{now_str} - {request.user.username}]: {notes_input}" if notes_input else ""

        if action_type in (DemoMeetingScheduleForm.ACTION_SCHEDULE, DemoMeetingScheduleForm.ACTION_RESCHEDULE):
            lead.requested_datetime = form.cleaned_data.get('meeting_datetime')
            lead.meeting_mode = form.cleaned_data.get('meeting_mode') or lead.meeting_mode
            lead.meeting_link = form.cleaned_data.get('meeting_link', '') or lead.meeting_link
            lead.assigned_staff = form.cleaned_data.get('assigned_staff')
            lead.status = PlatformDemoLead.STATUS_SCHEDULED if action_type == 'schedule' else PlatformDemoLead.STATUS_RESCHEDULED
            msg = f"Meeting scheduled for {lead.requested_datetime} ({lead.get_meeting_mode_display()})."
            audit_action = 'DEMO_UPDATE'

        elif action_type == DemoMeetingScheduleForm.ACTION_COMPLETE:
            lead.status = PlatformDemoLead.STATUS_COMPLETED
            msg = f"Demo marked as completed for {lead.lead_name}."
            audit_action = 'DEMO_COMPLETE'

        elif action_type == DemoMeetingScheduleForm.ACTION_CANCEL:
            lead.status = PlatformDemoLead.STATUS_CANCELLED
            msg = f"Meeting cancelled for {lead.lead_name}."
            audit_action = 'DEMO_UPDATE'

        if follow_up:
            lead.follow_up_date = follow_up
        if next_action:
            lead.next_action = next_action
        if notes_entry:
            lead.notes = (notes_entry + "\n\n" + (lead.notes or "")).strip()

        lead.save()

        PlatformAuditLog.objects.create(
            actor=request.user,
            action=audit_action,
            reason=f"{msg} Follow-up: {lead.follow_up_date or 'N/A'}",
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
        )
        messages.success(request, msg)
    else:
        messages.error(request, "Invalid meeting update data. Please check the form fields.")

    return redirect('super_admin:demo_detail', lead_id=lead.id)


@super_admin_required
@require_POST
def demo_convert_view(request, lead_id):
    """Link a demo lead to a newly created or existing tenant showroom account."""
    lead = get_object_or_404(PlatformDemoLead, pk=lead_id)
    tenant_id = request.POST.get('tenant_id')

    if not tenant_id:
        messages.error(request, "Please select a showroom account to link.")
        return redirect('super_admin:demo_detail', lead_id=lead.id)

    tenant = get_object_or_404(Tenant, pk=tenant_id)
    lead.converted_tenant = tenant
    lead.conversion_date = timezone.now()
    lead.status = PlatformDemoLead.STATUS_COMPLETED
    lead.save(update_fields=['converted_tenant', 'conversion_date', 'status', 'updated_at'])

    PlatformAuditLog.objects.create(
        actor=request.user,
        action='DEMO_CONVERT',
        target_tenant=tenant,
        reason=f"Converted lead '{lead.lead_name}' to Showroom '{tenant.name}'",
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
    )
    messages.success(request, f"Lead successfully converted and linked to '{tenant.name}'!")
    return redirect('super_admin:demo_detail', lead_id=lead.id)


# ============================================================================
# 9. Public Demo & Feedback Request API
# ============================================================================

def public_demo_request_view(request):
    """
    Public endpoint for prospects on landing page requesting a software demo or submitting feedback.
    Validates submission, enforces honeypot anti-spam, and creates a PlatformDemoLead.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    form = PublicDemoRequestForm(request.POST)
    if form.is_valid():
        cd = form.cleaned_data
        msg = cd.get('message', '').strip()
        lead = PlatformDemoLead.objects.create(
            lead_name=cd['showroom_name'],
            contact_name=cd['contact_person'],
            phone=cd['phone'],
            email=cd.get('email', ''),
            city=cd.get('city', ''),
            business_type=cd.get('business_type', 'RETAIL'),
            source=PlatformDemoLead.SOURCE_WEBSITE,
            status=PlatformDemoLead.STATUS_NEW,
            notes=f"Inquiry message from landing page:\n{msg}" if msg else "Submitted via website demo request form."
        )

        try:
            PlatformAuditLog.objects.create(
                action='DEMO_CREATE',
                reason=f"Public demo enquiry received from {lead.contact_name} ({lead.lead_name})",
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
            )
        except Exception:
            pass

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({
                'success': True,
                'message': 'Thank you! Your demo request has been received. Our jewellery software specialist will contact you shortly.'
            })

        messages.success(request, "Thank you! Your demo request has been received. Our team will contact you shortly.")
        return redirect('/#contact')

    errors = {field: [str(e) for e in err_list] for field, err_list in form.errors.items()}
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    for field, errs in form.errors.items():
        messages.error(request, f"{field.replace('_', ' ').capitalize()}: {errs[0]}")
    return redirect('/#contact')


# ============================================================================
# 10. Platform Support Tickets
# ============================================================================

@super_admin_required
def ticket_list_view(request):
    """List of all support tickets with status, priority, and category filtering."""
    qs = PlatformSupportTicket.objects.select_related('tenant', 'assigned_to').order_by('-created_at')

    # Status filter
    status = request.GET.get('status', 'all').strip()
    if status != 'all' and status:
        qs = qs.filter(status=status)

    # Priority filter
    priority = request.GET.get('priority', 'all').strip()
    if priority != 'all' and priority:
        qs = qs.filter(priority=priority)

    # Category filter
    category = request.GET.get('category', 'all').strip()
    if category != 'all' and category:
        qs = qs.filter(category=category)

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(ticket_number__icontains=q) |
            Q(subject__icontains=q) |
            Q(contact_name__icontains=q) |
            Q(contact_phone__icontains=q) |
            Q(tenant__name__icontains=q)
        )

    # Counts
    all_count = PlatformSupportTicket.objects.count()
    open_count = PlatformSupportTicket.objects.filter(status=PlatformSupportTicket.STATUS_OPEN).count()
    in_progress_count = PlatformSupportTicket.objects.filter(status=PlatformSupportTicket.STATUS_IN_PROGRESS).count()
    resolved_count = PlatformSupportTicket.objects.filter(status=PlatformSupportTicket.STATUS_RESOLVED).count()

    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'q': q,
        'status_filter': status,
        'priority_filter': priority,
        'category_filter': category,
        'total_filtered': paginator.count,
        'all_count': all_count,
        'open_count': open_count,
        'in_progress_count': in_progress_count,
        'resolved_count': resolved_count,
        'status_choices': PlatformSupportTicket.STATUS_CHOICES,
        'priority_choices': PlatformSupportTicket.PRIORITY_CHOICES,
        'category_choices': PlatformSupportTicket.CATEGORY_CHOICES,
    }
    return render(request, 'super_admin/ticket_list.html', context)


@super_admin_required
def ticket_create_view(request):
    """Create a new platform support ticket."""
    if request.method == 'POST':
        form = PlatformSupportTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save()
            PlatformAuditLog.objects.create(
                actor=request.user,
                action='TICKET_CREATE',
                target_tenant=ticket.tenant,
                reason=f"Created support ticket #{ticket.ticket_number}: {ticket.subject}",
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
            )
            messages.success(request, f"Support ticket #{ticket.ticket_number} created successfully.")
            return redirect('super_admin:ticket_detail', ticket_id=ticket.id)
    else:
        form = PlatformSupportTicketForm(initial={'priority': 'medium', 'status': 'open'})

    context = {
        'form': form,
        'page_title': 'Create Support Ticket',
    }
    return render(request, 'super_admin/ticket_form.html', context)


@super_admin_required
def ticket_detail_view(request, ticket_id):
    """View ticket details, response history, staff conversation thread, and update status."""
    ticket = get_object_or_404(
        PlatformSupportTicket.objects.select_related('tenant', 'assigned_to', 'created_by'),
        pk=ticket_id
    )
    staff_users = User.objects.filter(is_superuser=True) | User.objects.filter(is_staff=True)
    messages_list = ticket.messages.select_related('sender').order_by('created_at')
    reply_form = StaffTicketReplyForm()

    context = {
        'ticket': ticket,
        'staff_users': staff_users,
        'messages_list': messages_list,
        'reply_form': reply_form,
        'status_choices': PlatformSupportTicket.STATUS_CHOICES,
        'priority_choices': PlatformSupportTicket.PRIORITY_CHOICES,
    }
    return render(request, 'super_admin/ticket_detail.html', context)


@super_admin_required
@require_POST
def ticket_staff_reply_view(request, ticket_id):
    """Post a staff reply to customer, or add a private internal note."""
    ticket = get_object_or_404(PlatformSupportTicket, pk=ticket_id)
    form = StaffTicketReplyForm(request.POST, request.FILES)
    if form.is_valid():
        msg = form.save(commit=False)
        msg.ticket = ticket
        msg.sender = request.user
        msg.save()

        # If replying publicly to customer, update status to Waiting for Customer or In Progress
        if not msg.is_internal:
            if ticket.status == PlatformSupportTicket.STATUS_OPEN:
                ticket.status = PlatformSupportTicket.STATUS_WAITING_CUSTOMER
            ticket.updated_at = timezone.now()
            ticket.save(update_fields=['status', 'updated_at'])
            messages.success(request, f"Customer reply sent for ticket #{ticket.ticket_number}.")
        else:
            ticket.updated_at = timezone.now()
            ticket.save(update_fields=['updated_at'])
            messages.info(request, f"Internal note recorded (visible to staff only).")

        PlatformAuditLog.objects.create(
            actor=request.user,
            action='TICKET_MESSAGE',
            target_tenant=ticket.tenant,
            reason=f"Added {'internal note' if msg.is_internal else 'reply'} to ticket #{ticket.ticket_number}",
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
        )
    else:
        error_msg = "Please provide a valid message."
        if 'attachment' in form.errors:
            error_msg = form.errors['attachment'][0]
        messages.error(request, error_msg)

    return redirect('super_admin:ticket_detail', ticket_id=ticket.id)


@super_admin_required
@require_POST
def ticket_ai_summary_view(request, ticket_id):
    """Generate or refresh concise AI summary and recommended action plan for staff review."""
    ticket = get_object_or_404(PlatformSupportTicket, pk=ticket_id)
    messages_qs = ticket.messages.select_related('sender').order_by('created_at')
    
    conversation_lines = []
    for m in messages_qs:
        sender_label = "Staff" if (m.sender and (m.sender.is_superuser or m.sender.is_staff)) else "Customer"
        if m.is_internal:
            sender_label += " (Internal Note)"
        conversation_lines.append(f"{sender_label}: {m.message}")

    conversation_text = "\n".join(conversation_lines)
    summary = ai_summarize_ticket(ticket.subject, ticket.description, conversation_text)
    ticket.ai_summary = summary

    # Auto-categorize if not already categorized
    cat_sug, pri_sug = ai_categorize_ticket(ticket.subject, ticket.description)
    if not ticket.ai_suggested_category:
        ticket.ai_suggested_category = cat_sug
    if not ticket.ai_suggested_priority:
        ticket.ai_suggested_priority = pri_sug

    ticket.save(update_fields=['ai_summary', 'ai_suggested_category', 'ai_suggested_priority'])

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        return JsonResponse({
            'success': True,
            'ai_summary': ticket.ai_summary,
            'ai_suggested_category': ticket.ai_suggested_category,
            'ai_suggested_priority': ticket.ai_suggested_priority,
        })

    messages.success(request, f"AI summary generated for ticket #{ticket.ticket_number}.")
    return redirect('super_admin:ticket_detail', ticket_id=ticket.id)


@super_admin_required
@require_POST
def ticket_update_status_view(request, ticket_id):
    """Update ticket resolution notes, status, priority, or assigned specialist."""
    ticket = get_object_or_404(PlatformSupportTicket, pk=ticket_id)
    new_status = request.POST.get('status', ticket.status)
    new_priority = request.POST.get('priority', ticket.priority)
    assigned_to_id = request.POST.get('assigned_to')
    resolution_notes = request.POST.get('resolution_notes', '').strip()

    ticket.status = new_status
    ticket.priority = new_priority
    if assigned_to_id:
        ticket.assigned_to_id = assigned_to_id
    elif assigned_to_id == '':
        ticket.assigned_to = None

    if resolution_notes:
        now_str = timezone.now().strftime('%Y-%m-%d %H:%M')
        ticket.resolution_notes = (f"[{now_str} - {request.user.username}]: {resolution_notes}\n\n" + (ticket.resolution_notes or "")).strip()

    if new_status in (PlatformSupportTicket.STATUS_RESOLVED, PlatformSupportTicket.STATUS_CLOSED) and not ticket.resolved_at:
        ticket.resolved_at = timezone.now()

    ticket.save()

    audit_action = 'TICKET_RESOLVE' if new_status in ('resolved', 'closed') else 'TICKET_UPDATE'
    PlatformAuditLog.objects.create(
        actor=request.user,
        action=audit_action,
        target_tenant=ticket.tenant,
        reason=f"Updated ticket #{ticket.ticket_number} status to {ticket.get_status_display()}",
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
    )
    messages.success(request, f"Ticket #{ticket.ticket_number} updated to '{ticket.get_status_display()}'.")
    return redirect('super_admin:ticket_detail', ticket_id=ticket.id)


# ============================================================================
# 11. Reports & Analytics
# ============================================================================

@super_admin_required
def reports_view(request):
    """
    Comprehensive platform reporting suite with date-range filters:
    1. Registrations growth & business type distribution
    2. Demo meeting conversion funnel & lead sources
    3. Subscription plans & active trial distributions
    4. Verified subscription revenue collections
    5. Support ticket response volume
    """
    now = timezone.now()
    period = request.GET.get('period', '30d')
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')

    if start_date_str and end_date_str:
        try:
            from django.utils.dateparse import parse_date
            import datetime
            s_d = parse_date(start_date_str)
            e_d = parse_date(end_date_str)
            if s_d and e_d:
                start_dt = timezone.make_aware(datetime.datetime.combine(s_d, datetime.time.min))
                end_dt = timezone.make_aware(datetime.datetime.combine(e_d, datetime.time.max))
            else:
                start_dt = now - timedelta(days=30)
                end_dt = now
        except Exception:
            start_dt = now - timedelta(days=30)
            end_dt = now
    elif period == '7d':
        start_dt = now - timedelta(days=7)
        end_dt = now
    elif period == '90d':
        start_dt = now - timedelta(days=90)
        end_dt = now
    elif period == '1y':
        start_dt = now - timedelta(days=365)
        end_dt = now
    elif period == 'all':
        start_dt = now - timedelta(days=3650)
        end_dt = now
    else:
        period = '30d'
        start_dt = now - timedelta(days=30)
        end_dt = now

    # 1. Registration Metrics
    new_tenants_period = Tenant.objects.filter(created_at__range=(start_dt, end_dt)).count()
    total_tenants = Tenant.objects.count()
    retail_count = Tenant.objects.filter(business_type=Tenant.TYPE_RETAIL).count()
    wholesale_count = Tenant.objects.filter(business_type=Tenant.TYPE_WHOLESALE).count()
    hybrid_count = Tenant.objects.filter(business_type=Tenant.TYPE_BOTH).count()

    # 2. Demo Funnel Metrics
    leads_period = PlatformDemoLead.objects.filter(created_at__range=(start_dt, end_dt)).count()
    scheduled_period = PlatformDemoLead.objects.filter(created_at__range=(start_dt, end_dt), status=PlatformDemoLead.STATUS_SCHEDULED).count()
    completed_period = PlatformDemoLead.objects.filter(created_at__range=(start_dt, end_dt), status=PlatformDemoLead.STATUS_COMPLETED).count()
    converted_period = PlatformDemoLead.objects.filter(created_at__range=(start_dt, end_dt), converted_tenant__isnull=False).count()
    conversion_rate = round((converted_period / leads_period * 100), 1) if leads_period > 0 else 0

    lead_sources = (
        PlatformDemoLead.objects.filter(created_at__range=(start_dt, end_dt))
        .values('source')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    # 3. Subscriptions Breakdown
    ensure_all_tenant_subscriptions()
    active_subs = TenantSubscription.objects.filter(status=TenantSubscription.STATUS_ACTIVE).count()
    trial_subs = TenantSubscription.objects.filter(status=TenantSubscription.STATUS_TRIAL).count()
    overdue_subs = TenantSubscription.objects.filter(
        status__in=[TenantSubscription.STATUS_OVERDUE, TenantSubscription.STATUS_GRACE_PERIOD]
    ).count()

    plan_distribution = (
        TenantSubscription.objects.values('plan_name')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    # 4. Actual Revenue (SubscriptionPayment)
    period_revenue = (
        SubscriptionPayment.objects.filter(payment_date__range=(start_dt.date(), end_dt.date()))
        .aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    )
    total_revenue = SubscriptionPayment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    payment_methods_breakdown = (
        SubscriptionPayment.objects.filter(payment_date__range=(start_dt.date(), end_dt.date()))
        .values('payment_method')
        .annotate(total=Sum('amount'), count=Count('id'))
        .order_by('-total')
    )

    # 5. Support Tickets
    tickets_period = PlatformSupportTicket.objects.filter(created_at__range=(start_dt, end_dt)).count()
    resolved_period = PlatformSupportTicket.objects.filter(
        created_at__range=(start_dt, end_dt),
        status__in=[PlatformSupportTicket.STATUS_RESOLVED, PlatformSupportTicket.STATUS_CLOSED]
    ).count()

    categories_breakdown = (
        PlatformSupportTicket.objects.filter(created_at__range=(start_dt, end_dt))
        .values('category')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    context = {
        'period': period,
        'start_dt': start_dt,
        'end_dt': end_dt,
        'start_date_str': start_date_str,
        'end_date_str': end_date_str,
        'new_tenants_period': new_tenants_period,
        'total_tenants': total_tenants,
        'retail_count': retail_count,
        'wholesale_count': wholesale_count,
        'hybrid_count': hybrid_count,
        'leads_period': leads_period,
        'scheduled_period': scheduled_period,
        'completed_period': completed_period,
        'converted_period': converted_period,
        'conversion_rate': conversion_rate,
        'lead_sources': lead_sources,
        'active_subs': active_subs,
        'trial_subs': trial_subs,
        'overdue_subs': overdue_subs,
        'plan_distribution': plan_distribution,
        'period_revenue': period_revenue,
        'total_revenue': total_revenue,
        'payment_methods_breakdown': payment_methods_breakdown,
        'tickets_period': tickets_period,
        'resolved_period': resolved_period,
        'categories_breakdown': categories_breakdown,
    }
    return render(request, 'super_admin/reports.html', context)


@super_admin_required
def reports_export_csv_view(request, report_type):
    """Export filtered report tables to CSV format."""
    now = timezone.now()
    response = HttpResponse(content_type='text/csv')
    writer = csv.writer(response)

    if report_type == 'registrations':
        response['Content-Disposition'] = f'attachment; filename="JewelDesk_Registrations_{now.strftime("%Y%m%d")}.csv"'
        writer.writerow(['Showroom ID', 'Showroom Name', 'Slug', 'Business Type', 'Owner Username', 'Owner Email', 'Status', 'Registered Date'])
        for t in Tenant.objects.select_related('owner').order_by('-created_at'):
            writer.writerow([
                t.id,
                t.name,
                t.slug,
                t.get_business_type_display(),
                t.owner.username if t.owner else 'N/A',
                t.owner.email if t.owner else 'N/A',
                'Active' if t.is_active else 'Suspended',
                t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else 'N/A'
            ])

    elif report_type == 'demos':
        response['Content-Disposition'] = f'attachment; filename="JewelDesk_Demo_Leads_{now.strftime("%Y%m%d")}.csv"'
        writer.writerow(['Lead ID', 'Showroom Name', 'Contact Person', 'Phone', 'Email', 'City', 'Business Type', 'Source', 'Status', 'Meeting Date', 'Follow Up', 'Created Date'])
        for d in PlatformDemoLead.objects.order_by('-created_at'):
            writer.writerow([
                d.id,
                d.lead_name,
                d.contact_name,
                d.phone,
                d.email,
                d.city,
                d.get_business_type_display(),
                d.get_source_display(),
                d.get_status_display(),
                d.requested_datetime.strftime('%Y-%m-%d %H:%M') if d.requested_datetime else 'N/A',
                d.follow_up_date.strftime('%Y-%m-%d') if d.follow_up_date else 'N/A',
                d.created_at.strftime('%Y-%m-%d %H:%M') if d.created_at else 'N/A'
            ])

    elif report_type == 'subscriptions':
        response['Content-Disposition'] = f'attachment; filename="JewelDesk_Subscriptions_{now.strftime("%Y%m%d")}.csv"'
        writer.writerow(['Tenant Name', 'Plan', 'Status', 'Billing Cycle', 'Price (INR)', 'Payment Status', 'Started Date', 'Expires Date'])
        ensure_all_tenant_subscriptions()
        for s in TenantSubscription.objects.select_related('tenant').order_by('-started_at'):
            writer.writerow([
                s.tenant.name,
                s.get_plan_name_display(),
                s.get_status_display(),
                s.get_billing_cycle_display(),
                s.price,
                s.get_payment_status_display(),
                s.started_at.strftime('%Y-%m-%d') if s.started_at else 'N/A',
                s.expires_at.strftime('%Y-%m-%d') if s.expires_at else 'N/A'
            ])

    elif report_type == 'revenue':
        response['Content-Disposition'] = f'attachment; filename="JewelDesk_Subscription_Revenue_{now.strftime("%Y%m%d")}.csv"'
        writer.writerow(['Payment ID', 'Showroom Name', 'Amount (INR)', 'Payment Date', 'Payment Method', 'Reference ID', 'Invoice Number'])
        for p in SubscriptionPayment.objects.select_related('tenant').order_by('-payment_date'):
            writer.writerow([
                p.id,
                p.tenant.name,
                p.amount,
                p.payment_date.strftime('%Y-%m-%d') if p.payment_date else 'N/A',
                p.get_payment_method_display(),
                p.reference_id,
                p.invoice_number
            ])

    elif report_type == 'tickets':
        response['Content-Disposition'] = f'attachment; filename="JewelDesk_Support_Tickets_{now.strftime("%Y%m%d")}.csv"'
        writer.writerow(['Ticket Number', 'Showroom', 'Contact Name', 'Category', 'Priority', 'Status', 'Subject', 'Created Date', 'Resolved Date'])
        for tk in PlatformSupportTicket.objects.select_related('tenant').order_by('-created_at'):
            writer.writerow([
                tk.ticket_number,
                tk.tenant.name if tk.tenant else 'N/A',
                tk.contact_name,
                tk.get_category_display(),
                tk.get_priority_display(),
                tk.get_status_display(),
                tk.subject,
                tk.created_at.strftime('%Y-%m-%d %H:%M') if tk.created_at else 'N/A',
                tk.resolved_at.strftime('%Y-%m-%d %H:%M') if tk.resolved_at else 'N/A'
            ])

    else:
        return HttpResponse("Unknown report type", status=400)

    return response


# ============================================================================
# 8. Coupon Designer, Discount Templates & Print Management Views
# ============================================================================

@super_admin_required
def coupon_list_view(request):
    """List coupon templates with search, filtering, and summary statistics."""
    qs = CouponDesignTemplate.objects.all().select_related('created_by')

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(description__icontains=q) |
            Q(offer_title__icontains=q) |
            Q(sample_coupon_code__icontains=q)
        )

    ttype = request.GET.get('type', '').strip()
    if ttype in ['built_in', 'custom']:
        qs = qs.filter(template_type=ttype)

    status = request.GET.get('status', 'active').strip()
    if status == 'archived':
        qs = qs.filter(is_archived=True)
    elif status == 'all':
        pass
    else:
        qs = qs.filter(is_archived=False)

    total_templates = CouponDesignTemplate.objects.count()
    active_templates = CouponDesignTemplate.objects.filter(is_archived=False).count()
    total_batches = CouponPrintBatch.objects.count()
    total_coupons_generated = CouponBatchItem.objects.count()

    recent_batches = CouponPrintBatch.objects.select_related('template').order_by('-created_at')[:6]

    paginator = Paginator(qs, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'q': q,
        'selected_type': ttype,
        'selected_status': status,
        'total_templates': total_templates,
        'active_templates': active_templates,
        'total_batches': total_batches,
        'total_coupons_generated': total_coupons_generated,
        'recent_batches': recent_batches,
    }
    return render(request, 'super_admin/coupon_list.html', context)


@super_admin_required
def coupon_create_view(request):
    """Create a new Coupon Design Template (Built-in preset or Custom HTML/CSS)."""
    initial = {}
    preset_style = request.GET.get('preset', '').strip()
    if preset_style in [s[0] for s in CouponDesignTemplate.STYLE_CHOICES]:
        preset_markup = get_builtin_template_markup(preset_style)
        initial['built_in_style'] = preset_style
        initial['custom_html'] = preset_markup['html']
        initial['custom_css'] = preset_markup['css']

    if request.method == 'POST':
        form = CouponDesignTemplateForm(request.POST)
        if form.is_valid():
            template = form.save(commit=False)
            template.created_by = request.user
            template.save()

            PlatformAuditLog.objects.create(
                actor=request.user,
                action=PlatformAuditLog.ACTION_COUPON_TEMPLATE_CREATE,
                reason=f"Created coupon template: '{template.name}' ({template.get_template_type_display()})",
                ip_address=get_client_ip(request),
            )
            messages.success(request, f"Coupon template '{template.name}' created successfully!")
            action = request.POST.get('submit_action', 'save')
            if action == 'save_and_batch':
                return redirect(f"{reverse('super_admin:coupon_batch_create')}?template_id={template.id}")
            return redirect('super_admin:coupon_list')
        else:
            messages.error(request, "Please correct the errors in the template form below.")
    else:
        form = CouponDesignTemplateForm(initial=initial)

    context = {
        'form': form,
        'is_edit': False,
        'allowed_placeholders': ALLOWED_PLACEHOLDERS,
    }
    return render(request, 'super_admin/coupon_form.html', context)


@super_admin_required
def coupon_edit_view(request, template_id):
    """Edit an existing Coupon Design Template."""
    template = get_object_or_404(CouponDesignTemplate, id=template_id)

    if request.method == 'POST':
        form = CouponDesignTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            PlatformAuditLog.objects.create(
                actor=request.user,
                action=PlatformAuditLog.ACTION_COUPON_TEMPLATE_UPDATE,
                reason=f"Updated coupon template: '{template.name}' (ID: {template.id})",
                ip_address=get_client_ip(request),
            )
            messages.success(request, f"Coupon template '{template.name}' updated successfully.")
            action = request.POST.get('submit_action', 'save')
            if action == 'save_and_batch':
                return redirect(f"{reverse('super_admin:coupon_batch_create')}?template_id={template.id}")
            return redirect('super_admin:coupon_list')
        else:
            messages.error(request, "Please resolve form validation errors before saving.")
    else:
        form = CouponDesignTemplateForm(instance=template)

    context = {
        'form': form,
        'template': template,
        'is_edit': True,
        'allowed_placeholders': ALLOWED_PLACEHOLDERS,
    }
    return render(request, 'super_admin/coupon_form.html', context)


@super_admin_required
@require_POST
def coupon_duplicate_view(request, template_id):
    """Duplicate an existing coupon template for quick customization."""
    template = get_object_or_404(CouponDesignTemplate, id=template_id)

    clone = CouponDesignTemplate.objects.create(
        name=f"{template.name} (Copy)",
        description=template.description,
        template_type=template.template_type,
        built_in_style=template.built_in_style,
        discount_type=template.discount_type,
        discount_value=template.discount_value,
        offer_title=template.offer_title,
        sample_coupon_code=template.sample_coupon_code,
        business_name=template.business_name,
        business_logo_url=template.business_logo_url,
        valid_from=template.valid_from,
        valid_until=template.valid_until,
        minimum_purchase=template.minimum_purchase,
        maximum_discount=template.maximum_discount,
        applicable_categories=template.applicable_categories,
        terms_and_conditions=template.terms_and_conditions,
        show_barcode=template.show_barcode,
        show_qr_code=template.show_qr_code,
        primary_color=template.primary_color,
        background_color=template.background_color,
        text_color=template.text_color,
        page_size=template.page_size,
        orientation=template.orientation,
        coupon_width_mm=template.coupon_width_mm,
        coupon_height_mm=template.coupon_height_mm,
        grid_columns=template.grid_columns,
        grid_rows=template.grid_rows,
        margin_mm=template.margin_mm,
        spacing_mm=template.spacing_mm,
        custom_html=template.custom_html,
        custom_css=template.custom_css,
        is_archived=False,
        created_by=request.user,
    )

    PlatformAuditLog.objects.create(
        actor=request.user,
        action=PlatformAuditLog.ACTION_COUPON_TEMPLATE_CREATE,
        reason=f"Duplicated coupon template from '{template.name}' to '{clone.name}'",
        ip_address=get_client_ip(request),
    )
    messages.success(request, f"Duplicated template '{clone.name}'. You can now edit its design.")
    return redirect('super_admin:coupon_edit', template_id=clone.id)


@super_admin_required
@require_POST
def coupon_archive_view(request, template_id):
    """Toggle the archive status of a coupon template."""
    template = get_object_or_404(CouponDesignTemplate, id=template_id)
    template.is_archived = not template.is_archived
    template.save(update_fields=['is_archived', 'updated_at'])

    state_str = "archived" if template.is_archived else "restored to active"
    PlatformAuditLog.objects.create(
        actor=request.user,
        action=PlatformAuditLog.ACTION_COUPON_TEMPLATE_ARCHIVE,
        reason=f"Template '{template.name}' was {state_str}.",
        ip_address=get_client_ip(request),
    )
    messages.info(request, f"Template '{template.name}' has been {state_str}.")
    return redirect('super_admin:coupon_list')


@super_admin_required
@require_POST
def coupon_delete_view(request, template_id):
    """Delete a template only if no print batches are linked."""
    template = get_object_or_404(CouponDesignTemplate, id=template_id)
    if template.print_batches.exists():
        messages.error(request, f"Cannot delete '{template.name}' because {template.print_batches.count()} print batches are associated with it. Please archive it instead.")
        return redirect('super_admin:coupon_list')

    name = template.name
    template.delete()
    messages.success(request, f"Template '{name}' was permanently deleted.")
    return redirect('super_admin:coupon_list')


@super_admin_required
def coupon_preview_api(request):
    """Live Sandboxed Preview Endpoint.

    Returns an isolated, sanitized HTML document rendered either from a saved template ID
    or directly from real-time POST/GET form fields. Loaded via iframe sandbox for full isolation.
    """
    template_id = request.GET.get('template_id') or request.POST.get('template_id')
    template = None
    if template_id:
        template = CouponDesignTemplate.objects.filter(id=template_id).first()

    ttype = request.POST.get('template_type') or (template.template_type if template else CouponDesignTemplate.TYPE_BUILT_IN)
    bstyle = request.POST.get('built_in_style') or (template.built_in_style if template else CouponDesignTemplate.STYLE_LUXURY_GOLD)
    custom_html = request.POST.get('custom_html') if 'custom_html' in request.POST else (template.custom_html if template else '')
    custom_css = request.POST.get('custom_css') if 'custom_css' in request.POST else (template.custom_css if template else '')

    business_name = request.POST.get('business_name') or (template.business_name if template else 'JewelDesk Fine Atelier')
    offer_title = request.POST.get('offer_title') or (template.offer_title if template else 'Privilege Jewellery Voucher')
    sample_code = request.POST.get('sample_coupon_code') or (template.sample_coupon_code if template else 'SAMPLE-VIP20')
    discount_type = request.POST.get('discount_type') or (template.discount_type if template else CouponDesignTemplate.DISCOUNT_PERCENTAGE)

    raw_val = request.POST.get('discount_value')
    if raw_val is not None and str(raw_val).strip() != '':
        try:
            discount_val = Decimal(str(raw_val))
        except Exception:
            discount_val = template.discount_value if template else Decimal('20.00')
    else:
        discount_val = template.discount_value if template else Decimal('20.00')

    valid_until = request.POST.get('valid_until') or (template.valid_until.strftime('%d %b %Y') if template and template.valid_until else '31 Dec 2026')
    valid_from = request.POST.get('valid_from') or (template.valid_from.strftime('%d %b %Y') if template and template.valid_from else '01 Jan 2026')
    min_purchase = request.POST.get('minimum_purchase') or (str(template.minimum_purchase) if template else '10,000')
    max_discount = request.POST.get('maximum_discount') or (str(template.maximum_discount) if template and template.maximum_discount else '')
    categories = request.POST.get('applicable_categories') or (template.applicable_categories if template else 'Gold & Diamond Ornaments')
    terms = request.POST.get('terms_and_conditions') or (template.terms_and_conditions if template else 'Original coupon must be surrendered at billing counter. Valid on all jewellery.')

    show_barcode = (request.POST.get('show_barcode') in ['true', 'on', '1', True]) if 'show_barcode' in request.POST else (template.show_barcode if template else True)
    show_qr = (request.POST.get('show_qr_code') in ['true', 'on', '1', True]) if 'show_qr_code' in request.POST else (template.show_qr_code if template else True)

    p_color = request.POST.get('primary_color') or (template.primary_color if template else '#d4af37')
    b_color = request.POST.get('background_color') or (template.background_color if template else '#160f09')
    t_color = request.POST.get('text_color') or (template.text_color if template else '#fef9ed')

    try:
        w_mm = int(request.POST.get('coupon_width_mm') or (template.coupon_width_mm if template else 180))
    except Exception:
        w_mm = 180
    try:
        h_mm = int(request.POST.get('coupon_height_mm') or (template.coupon_height_mm if template else 70))
    except Exception:
        h_mm = 70

    html_markup = render_single_coupon_html(
        template_type=ttype,
        built_in_style=bstyle,
        custom_html=custom_html,
        custom_css=custom_css,
        coupon_code=sample_code,
        discount_type=discount_type,
        discount_value=discount_val,
        offer_title=offer_title,
        business_name=business_name,
        valid_from=valid_from,
        valid_until=valid_until,
        minimum_purchase=min_purchase,
        maximum_discount=max_discount,
        applicable_categories=categories,
        terms_and_conditions=terms,
        serial_number=1,
        show_barcode=show_barcode,
        show_qr_code=show_qr,
        primary_color=p_color,
        background_color=b_color,
        text_color=t_color,
        coupon_width_mm=w_mm,
        coupon_height_mm=h_mm,
    )

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'json' in request.GET:
        return JsonResponse({'status': 'ok', 'html': html_markup})

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>JewelDesk Coupon Sandbox Preview</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Montserrat:wght@400;500;600;700&family=Playfair+Display:ital,wght@0,600;0,700;1,400&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 24px;
      background: #110e0c;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      font-family: 'Montserrat', system-ui, sans-serif;
    }}
    .preview-canvas {{
      background: #1e1915;
      padding: 24px;
      border-radius: 12px;
      border: 1px solid rgba(212, 175, 55, 0.25);
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6);
      display: flex;
      flex-direction: column;
      align-items: center;
    }}
    .preview-badge {{
      margin-bottom: 14px;
      padding: 4px 12px;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #d4af37;
      background: rgba(212, 175, 55, 0.12);
      border: 1px solid rgba(212, 175, 55, 0.3);
      border-radius: 999px;
    }}
  </style>
</head>
<body>
  <div class="preview-canvas">
    <div class="preview-badge">Live Print Scaling Preview ({w_mm}mm × {h_mm}mm)</div>
    {html_markup}
  </div>
</body>
</html>"""
    response = HttpResponse(full_html, content_type='text/html; charset=utf-8')
    response['X-Content-Type-Options'] = 'nosniff'
    response['X-Frame-Options'] = 'SAMEORIGIN'
    return response


# ============================================================================
# Coupon Print Batches & Multi-Coupon Layout Views
# ============================================================================

@super_admin_required
def coupon_batch_list_view(request):
    """List of all generated coupon print batches with status and export."""
    qs = CouponPrintBatch.objects.select_related('template', 'created_by').prefetch_related('items')

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(batch_number__icontains=q) |
            Q(name__icontains=q) |
            Q(shared_code__icontains=q) |
            Q(template__name__icontains=q)
        )

    template_id = request.GET.get('template_id')
    if template_id:
        qs = qs.filter(template_id=template_id)

    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    templates = CouponDesignTemplate.objects.filter(is_archived=False)

    context = {
        'page_obj': page_obj,
        'q': q,
        'selected_template_id': template_id,
        'templates': templates,
    }
    return render(request, 'super_admin/coupon_batch_list.html', context)


@super_admin_required
def coupon_batch_create_view(request):
    """Generate a single coupon or bulk print run with unique codes or identical artwork."""
    template_id = request.GET.get('template_id')
    selected_template = None
    if template_id:
        selected_template = CouponDesignTemplate.objects.filter(id=template_id, is_archived=False).first()

    initial = {}
    if selected_template:
        initial = {
            'template': selected_template.id,
            'offer_title': selected_template.offer_title,
            'discount_type': selected_template.discount_type,
            'discount_value': selected_template.discount_value,
            'valid_from': selected_template.valid_from,
            'valid_until': selected_template.valid_until,
            'business_name': selected_template.business_name,
            'minimum_purchase': selected_template.minimum_purchase,
            'maximum_discount': selected_template.maximum_discount,
            'applicable_categories': selected_template.applicable_categories,
            'terms_and_conditions': selected_template.terms_and_conditions,
            'grid_columns': selected_template.grid_columns,
            'grid_rows': selected_template.grid_rows,
            'margin_mm': selected_template.margin_mm,
            'spacing_mm': selected_template.spacing_mm,
            'shared_code': selected_template.sample_coupon_code,
        }

    if request.method == 'POST':
        form = CouponPrintBatchForm(request.POST)
        if form.is_valid():
            batch = form.save(commit=False)
            batch.created_by = request.user

            import random
            year = timezone.localdate().year
            last_batch = CouponPrintBatch.objects.order_by('-id').first()
            next_id = (last_batch.id + 1) if last_batch else random.randint(100, 999)
            batch.batch_number = f"BATCH-{year}-{next_id:04d}"

            tpl = batch.template
            if not batch.offer_title:
                batch.offer_title = tpl.offer_title
            if not batch.discount_type:
                batch.discount_type = tpl.discount_type
            if not batch.discount_value:
                batch.discount_value = tpl.discount_value
            if not batch.business_name:
                batch.business_name = tpl.business_name
            if not batch.terms_and_conditions:
                batch.terms_and_conditions = tpl.terms_and_conditions

            batch.save()

            qty = batch.total_quantity
            items_to_create = []

            if batch.batch_type == CouponPrintBatch.BATCH_UNIQUE:
                codes = generate_unique_batch_codes(
                    batch_instance=batch,
                    count=qty,
                    prefix=batch.code_prefix or 'JD-',
                    length=batch.code_length or 8
                )
                start_num = batch.serial_start if batch.include_serial_numbers else 1
                for idx, code_str in enumerate(codes):
                    items_to_create.append(CouponBatchItem(
                        batch=batch,
                        serial_number=start_num + idx,
                        coupon_code=code_str,
                    ))
            else:
                code_str = batch.shared_code or tpl.sample_coupon_code or 'PROMO'
                start_num = batch.serial_start if batch.include_serial_numbers else 1
                for idx in range(qty):
                    items_to_create.append(CouponBatchItem(
                        batch=batch,
                        serial_number=start_num + idx,
                        coupon_code=code_str,
                    ))

            CouponBatchItem.objects.bulk_create(items_to_create)

            PlatformAuditLog.objects.create(
                actor=request.user,
                action=PlatformAuditLog.ACTION_COUPON_BATCH_GENERATE,
                reason=f"Generated print batch {batch.batch_number} with {qty} coupons ({batch.get_batch_type_display()})",
                ip_address=get_client_ip(request),
            )
            messages.success(request, f"Batch '{batch.batch_number}' ({qty} coupons) generated successfully! Ready for printing.")
            return redirect('super_admin:coupon_batch_detail', batch_id=batch.id)
        else:
            messages.error(request, "Please review the batch settings below.")
    else:
        form = CouponPrintBatchForm(initial=initial)

    context = {
        'form': form,
        'selected_template': selected_template,
        'templates': CouponDesignTemplate.objects.filter(is_archived=False),
    }
    return render(request, 'super_admin/coupon_batch_create.html', context)


@super_admin_required
def coupon_batch_detail_view(request, batch_id):
    """View coupon batch metadata, individual serial items, and export."""
    batch = get_object_or_404(CouponPrintBatch.objects.select_related('template', 'created_by'), id=batch_id)

    # Optional CSV export of batch codes
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        now_str = timezone.now().strftime('%Y%m%d_%H%M')
        response['Content-Disposition'] = f'attachment; filename="JewelDesk_Coupons_{batch.batch_number}_{now_str}.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Batch Number',
            'Serial Number',
            'Coupon Code',
            'Discount Value',
            'Offer Title',
            'Valid Until',
            'Redeemed',
            'Redeemed Date',
            'Redemption Note',
        ])
        for itm in batch.items.all().order_by('serial_number'):
            writer.writerow([
                batch.batch_number,
                f"#{itm.serial_number:04d}",
                itm.coupon_code,
                batch.formatted_discount,
                batch.offer_title,
                batch.valid_until.strftime('%Y-%m-%d') if batch.valid_until else 'N/A',
                'Yes' if itm.is_redeemed else 'No',
                itm.redeemed_at.strftime('%Y-%m-%d %H:%M') if itm.redeemed_at else '',
                itm.redemption_note,
            ])
        return response

    items_qs = batch.items.all().order_by('serial_number')

    q = request.GET.get('q', '').strip()
    if q:
        items_qs = items_qs.filter(coupon_code__icontains=q)

    redemption_filter = request.GET.get('redeemed', '').strip()
    if redemption_filter == 'yes':
        items_qs = items_qs.filter(is_redeemed=True)
    elif redemption_filter == 'no':
        items_qs = items_qs.filter(is_redeemed=False)

    paginator = Paginator(items_qs, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    redeemed_count = batch.items.filter(is_redeemed=True).count()
    unredeemed_count = batch.total_quantity - redeemed_count

    context = {
        'batch': batch,
        'page_obj': page_obj,
        'q': q,
        'redemption_filter': redemption_filter,
        'redeemed_count': redeemed_count,
        'unredeemed_count': unredeemed_count,
    }
    return render(request, 'super_admin/coupon_batch_detail.html', context)


@super_admin_required
@require_POST
def coupon_batch_item_toggle_view(request, item_id):
    """Toggle redemption status for a specific coupon voucher item."""
    item = get_object_or_404(CouponBatchItem, id=item_id)
    item.is_redeemed = not item.is_redeemed
    if item.is_redeemed:
        item.redeemed_at = timezone.now()
        note = request.POST.get('redemption_note', '').strip()
        item.redemption_note = note or f"Marked redeemed by {request.user.username}"
    else:
        item.redeemed_at = None
        item.redemption_note = ''
    item.save(update_fields=['is_redeemed', 'redeemed_at', 'redemption_note'])

    state_str = "Redeemed" if item.is_redeemed else "Unredeemed"
    messages.success(request, f"Coupon #{item.serial_number:04d} [{item.coupon_code}] marked as {state_str}.")
    return redirect('super_admin:coupon_batch_detail', batch_id=item.batch.id)


@super_admin_required
def coupon_batch_print_view(request, batch_id):
    """Dedicated Native Browser Print Layout for a batch of coupons.

    Renders A4 multi-coupon sheets or single voucher pages using @page and @media print.
    Excludes all admin navigation, sidebars, and buttons from print output.
    """
    batch = get_object_or_404(CouponPrintBatch.objects.select_related('template'), id=batch_id)
    template = batch.template

    items = list(batch.items.all().order_by('serial_number'))
    capacity = max(1, batch.grid_columns * batch.grid_rows)

    sheets = []
    for i in range(0, len(items), capacity):
        chunk = items[i:i + capacity]
        rendered_coupons = []
        for item in chunk:
            coupon_html = render_single_coupon_html(
                template_type=template.template_type,
                built_in_style=template.built_in_style,
                custom_html=template.custom_html,
                custom_css=template.custom_css,
                coupon_code=item.coupon_code,
                discount_type=batch.discount_type,
                discount_value=batch.discount_value,
                offer_title=batch.offer_title,
                business_name=batch.business_name,
                valid_from=batch.valid_from.strftime('%d %b %Y') if batch.valid_from else '',
                valid_until=batch.valid_until.strftime('%d %b %Y') if batch.valid_until else '',
                minimum_purchase=f"{batch.minimum_purchase:,.0f}" if batch.minimum_purchase else '0',
                maximum_discount=f"{batch.maximum_discount:,.0f}" if batch.maximum_discount else '',
                applicable_categories=batch.applicable_categories,
                terms_and_conditions=batch.terms_and_conditions,
                serial_number=item.serial_number if batch.include_serial_numbers else None,
                show_barcode=template.show_barcode,
                show_qr_code=template.show_qr_code,
                primary_color=template.primary_color,
                background_color=template.background_color,
                text_color=template.text_color,
                coupon_width_mm=template.coupon_width_mm,
                coupon_height_mm=template.coupon_height_mm,
            )
            rendered_coupons.append({
                'item': item,
                'html': coupon_html,
            })
        sheets.append({
            'sheet_number': len(sheets) + 1,
            'coupons': rendered_coupons,
        })

    context = {
        'batch': batch,
        'template': template,
        'sheets': sheets,
        'total_sheets': len(sheets),
        'total_coupons': len(items),
    }
    return render(request, 'super_admin/coupon_batch_print.html', context)


@super_admin_required
def coupon_single_print_view(request, template_id):
    """Direct single voucher print test preview for a template."""
    template = get_object_or_404(CouponDesignTemplate, id=template_id)

    coupon_html = render_single_coupon_html(
        template_type=template.template_type,
        built_in_style=template.built_in_style,
        custom_html=template.custom_html,
        custom_css=template.custom_css,
        coupon_code=template.sample_coupon_code,
        discount_type=template.discount_type,
        discount_value=template.discount_value,
        offer_title=template.offer_title,
        business_name=template.business_name,
        valid_from=template.valid_from.strftime('%d %b %Y') if template.valid_from else '',
        valid_until=template.valid_until.strftime('%d %b %Y') if template.valid_until else '',
        minimum_purchase=f"{template.minimum_purchase:,.0f}" if template.minimum_purchase else '0',
        maximum_discount=f"{template.maximum_discount:,.0f}" if template.maximum_discount else '',
        applicable_categories=template.applicable_categories,
        terms_and_conditions=template.terms_and_conditions,
        serial_number=1,
        show_barcode=template.show_barcode,
        show_qr_code=template.show_qr_code,
        primary_color=template.primary_color,
        background_color=template.background_color,
        text_color=template.text_color,
        coupon_width_mm=template.coupon_width_mm,
        coupon_height_mm=template.coupon_height_mm,
    )

    sheet = {
        'sheet_number': 1,
        'coupons': [{'item': None, 'html': coupon_html}],
    }

    context = {
        'template': template,
        'sheets': [sheet],
        'total_sheets': 1,
        'total_coupons': 1,
        'is_single_test': True,
    }
    return render(request, 'super_admin/coupon_batch_print.html', context)


