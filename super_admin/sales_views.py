"""
super_admin/sales_views.py
--------------------------
Enterprise Sales CRM views for JewelDesk Super Admin / Platform Portal.
Provides dedicated pipeline stage views, Sales Dashboard, Kanban board,
negotiation history, multi-channel activity tracking, and safe tenant conversion.
"""

from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Sum, Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Tenant
from .decorators import super_admin_required
from .models import (
    PlatformDemoLead,
    PlatformLeadNote,
    PlatformLeadStageHistory,
    PlatformLeadNegotiation,
    PlatformLeadActivity,
    PlatformProposal,
    PlatformAuditLog,
    TenantSubscription,
)

User = get_user_model()


def get_sales_crm_stage_counts():
    """Calculate exact real database counts for all dedicated Sales CRM tabs."""
    now = timezone.now()
    thirty_days_dt = now + timedelta(days=30)

    try:
        leads_cnt = PlatformDemoLead.objects.filter(stage__in=[PlatformDemoLead.STAGE_NEW, PlatformDemoLead.STAGE_CONTACTED]).count()
        interested_cnt = PlatformDemoLead.objects.filter(stage=PlatformDemoLead.STAGE_INTERESTED).count()
        meetings_cnt = PlatformDemoLead.objects.filter(stage=PlatformDemoLead.STAGE_MEETINGS).count()
        
        # Trial stores
        trial_cnt = TenantSubscription.objects.filter(plan_name='trial', status__in=['active', 'trial']).count()
        trial_leads_cnt = PlatformDemoLead.objects.filter(stage=PlatformDemoLead.STAGE_TRIAL).count()
        trial_total = max(trial_cnt, trial_leads_cnt)

        # Proposals
        proposals_cnt = PlatformProposal.objects.filter(is_latest=True, status__in=[
            PlatformProposal.STATUS_DRAFT, PlatformProposal.STATUS_SENT, PlatformProposal.STATUS_VIEWED
        ]).count()
        proposal_leads_cnt = PlatformDemoLead.objects.filter(stage=PlatformDemoLead.STAGE_PROPOSAL).count()
        proposals_total = max(proposals_cnt, proposal_leads_cnt)

        orders_cnt = PlatformDemoLead.objects.filter(stage=PlatformDemoLead.STAGE_ORDERS).count()
        customers_cnt = Tenant.objects.filter(is_active=True).count()
        subscribers_cnt = TenantSubscription.objects.filter(status='active').exclude(plan_name='trial').count()
        
        renewals_cnt = TenantSubscription.objects.filter(
            status='active',
            expires_at__gte=now,
            expires_at__lte=thirty_days_dt
        ).exclude(plan_name='trial').count()

        lost_cnt = PlatformDemoLead.objects.filter(stage=PlatformDemoLead.STAGE_LOST).count()

        return {
            'leads': leads_cnt,
            'interested': interested_cnt,
            'meetings': meetings_cnt,
            'trial': trial_total,
            'proposals': proposals_total,
            'orders': orders_cnt,
            'customers': customers_cnt,
            'subscribers': subscribers_cnt,
            'renewals': renewals_cnt,
            'lost': lost_cnt,
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Error calculating sales crm counts: %s", e)
        try:
            leads_fallback = PlatformDemoLead.objects.filter(status__in=['new', 'contacted', 'pending']).count()
        except Exception:
            leads_fallback = 0
        try:
            customers_fallback = Tenant.objects.filter(is_active=True).count()
        except Exception:
            customers_fallback = 0
        try:
            subscribers_fallback = TenantSubscription.objects.filter(status='active').exclude(plan_name='trial').count()
        except Exception:
            subscribers_fallback = 0
        return {
            'leads': leads_fallback,
            'interested': 0,
            'meetings': 0,
            'trial': 0,
            'proposals': 0,
            'orders': 0,
            'customers': customers_fallback,
            'subscribers': subscribers_fallback,
            'renewals': 0,
            'lost': 0
        }


# ============================================================================
# 1. SALES DASHBOARD
# ============================================================================

@super_admin_required
def sales_dashboard_view(request):
    """
    Comprehensive Sales CRM Dashboard with 12 real database KPIs,
    conversion funnel, monthly metrics, source performance, and sales rep leaderboard.
    """
    today = timezone.localdate()
    now = timezone.now()
    stage_counts = get_sales_crm_stage_counts()

    # 12 Core KPI Metrics
    try:
        total_leads = PlatformDemoLead.objects.count()
        new_leads = PlatformDemoLead.objects.filter(stage=PlatformDemoLead.STAGE_NEW).count()
    except Exception:
        total_leads = PlatformDemoLead.objects.count()
        new_leads = PlatformDemoLead.objects.filter(status='pending').count()

    interested_leads = stage_counts.get('interested', 0)
    meetings_count = stage_counts.get('meetings', 0)
    trial_count = stage_counts.get('trial', 0)
    proposals_count = stage_counts.get('proposals', 0)
    orders_count = stage_counts.get('orders', 0)
    won_count = stage_counts.get('customers', 0)
    lost_count = stage_counts.get('lost', 0)

    # Revenue metrics
    try:
        active_deal_stages = [
            PlatformDemoLead.STAGE_NEW,
            PlatformDemoLead.STAGE_CONTACTED,
            PlatformDemoLead.STAGE_INTERESTED,
            PlatformDemoLead.STAGE_MEETINGS,
            PlatformDemoLead.STAGE_TRIAL,
            PlatformDemoLead.STAGE_PROPOSAL,
            PlatformDemoLead.STAGE_ORDERS,
        ]
        expected_revenue = PlatformDemoLead.objects.filter(stage__in=active_deal_stages).aggregate(
            total=Sum('deal_value')
        )['total'] or Decimal('0.00')
    except Exception:
        expected_revenue = Decimal('0.00')

    try:
        converted_revenue = TenantSubscription.objects.filter(status='active').aggregate(
            total=Sum('price')
        )['total'] or Decimal('0.00')
    except Exception:
        converted_revenue = Decimal('0.00')

    # Follow-ups due today and overdue
    try:
        followups_today = PlatformLeadActivity.objects.filter(
            scheduled_at__date=today,
            is_completed=False
        ).count()
        overdue_followups = PlatformLeadActivity.objects.filter(
            scheduled_at__date__lt=today,
            is_completed=False
        ).count()
    except Exception:
        followups_today = 0
        overdue_followups = 0

    # Funnel stages breakdown
    try:
        funnel = [
            {'name': 'Total Leads', 'count': total_leads, 'pct': 100, 'color': '#38bdf8'},
            {'name': 'Contacted', 'count': PlatformDemoLead.objects.filter(stage__in=[PlatformDemoLead.STAGE_CONTACTED, PlatformDemoLead.STAGE_INTERESTED, PlatformDemoLead.STAGE_MEETINGS, PlatformDemoLead.STAGE_TRIAL, PlatformDemoLead.STAGE_PROPOSAL, PlatformDemoLead.STAGE_ORDERS, PlatformDemoLead.STAGE_CUSTOMERS]).count(), 'color': '#0ea5e9'},
            {'name': 'Interested', 'count': PlatformDemoLead.objects.filter(stage__in=[PlatformDemoLead.STAGE_INTERESTED, PlatformDemoLead.STAGE_MEETINGS, PlatformDemoLead.STAGE_TRIAL, PlatformDemoLead.STAGE_PROPOSAL, PlatformDemoLead.STAGE_ORDERS, PlatformDemoLead.STAGE_CUSTOMERS]).count(), 'color': '#eab308'},
            {'name': 'Demos / Trial', 'count': PlatformDemoLead.objects.filter(stage__in=[PlatformDemoLead.STAGE_MEETINGS, PlatformDemoLead.STAGE_TRIAL, PlatformDemoLead.STAGE_PROPOSAL, PlatformDemoLead.STAGE_ORDERS, PlatformDemoLead.STAGE_CUSTOMERS]).count(), 'color': '#a855f7'},
            {'name': 'Proposals & Closing', 'count': PlatformDemoLead.objects.filter(stage__in=[PlatformDemoLead.STAGE_PROPOSAL, PlatformDemoLead.STAGE_ORDERS, PlatformDemoLead.STAGE_CUSTOMERS]).count(), 'color': '#f97316'},
            {'name': 'Won (Customers)', 'count': won_count, 'color': '#10b981'},
        ]
        for step in funnel:
            step['pct'] = round((step['count'] / total_leads * 100), 1) if total_leads > 0 else 0
    except Exception:
        funnel = []

    # Lead source performance
    try:
        source_stats = PlatformDemoLead.objects.values('source').annotate(
            total=Count('id'),
            won=Count('id', filter=Q(stage=PlatformDemoLead.STAGE_CUSTOMERS) | Q(converted_tenant__isnull=False))
        ).order_by('-total')
    except Exception:
        try:
            source_stats = PlatformDemoLead.objects.values('source').annotate(
                total=Count('id'),
                won=Count('id', filter=Q(converted_tenant__isnull=False))
            ).order_by('-total')
        except Exception:
            source_stats = []

    # Sales rep performance leaderboard
    try:
        staff_leaderboard = User.objects.filter(
            is_staff=True
        ).annotate(
            assigned_leads=Count('assigned_demo_leads', distinct=True),
            won_deals=Count('assigned_demo_leads', filter=Q(assigned_demo_leads__stage=PlatformDemoLead.STAGE_CUSTOMERS) | Q(assigned_demo_leads__converted_tenant__isnull=False), distinct=True),
            open_followups=Count('assigned_crm_activities', filter=Q(assigned_crm_activities__is_completed=False), distinct=True)
        ).order_by('-won_deals', '-assigned_leads')[:8]
    except Exception:
        try:
            staff_leaderboard = User.objects.filter(
                is_staff=True
            ).annotate(
                assigned_leads=Count('assigned_demo_leads', distinct=True),
                won_deals=Count('assigned_demo_leads', filter=Q(assigned_demo_leads__converted_tenant__isnull=False), distinct=True)
            ).order_by('-won_deals', '-assigned_leads')[:8]
        except Exception:
            staff_leaderboard = []

    # Recent activities & upcoming follow-ups
    try:
        recent_activities = PlatformLeadActivity.objects.select_related('lead', 'assigned_to').order_by('-created_at')[:6]
        upcoming_followups = PlatformLeadActivity.objects.filter(
            is_completed=False,
            scheduled_at__gte=now
        ).select_related('lead', 'assigned_to').order_by('scheduled_at')[:6]
    except Exception:
        recent_activities = []
        upcoming_followups = []

    context = {
        'page_title': 'Sales CRM Dashboard',
        'current_sales_stage': 'dashboard',
        'sales_crm_counts': stage_counts,
        'kpis': {
            'total_leads': total_leads,
            'new_leads': new_leads,
            'interested_leads': interested_leads,
            'meetings_count': meetings_count,
            'trial_count': trial_count,
            'proposals_count': proposals_count,
            'orders_count': orders_count,
            'won_count': won_count,
            'lost_count': lost_count,
            'expected_revenue': expected_revenue,
            'converted_revenue': converted_revenue,
            'followups_today': followups_today,
            'overdue_followups': overdue_followups,
        },
        'funnel': funnel,
        'source_stats': source_stats,
        'staff_leaderboard': staff_leaderboard,
        'recent_activities': recent_activities,
        'upcoming_followups': upcoming_followups,
    }
    return render(request, 'super_admin/sales/dashboard.html', context)


# ============================================================================
# 2. DEDICATED SALES STAGE VIEWS (Leads, Interested, Meetings, Trial, etc.)
# ============================================================================

@super_admin_required
def sales_stage_view(request, stage_key):
    """
    Dedicated view for each specific sales stage.
    Ensures leads are not lumped into a single page, but cleanly segregated.
    """
    stage_key = stage_key.lower().strip()
    valid_stages = ['leads', 'interested', 'meetings', 'trial', 'proposals', 'orders', 'customers', 'subscribers', 'renewals', 'lost']
    if stage_key not in valid_stages:
        messages.warning(request, f"Unknown stage '{stage_key}'. Showing Leads.")
        return redirect('super_admin:sales_stage_view', stage_key='leads')

    stage_counts = get_sales_crm_stage_counts()
    today = timezone.localdate()
    view_mode = request.GET.get('view', 'table').lower()

    # Base Queryset
    qs = PlatformDemoLead.objects.select_related('assigned_staff', 'converted_tenant').prefetch_related('activities', 'proposals').order_by('-created_at')

    # Filter by specific stage logic
    if stage_key == 'leads':
        qs = qs.filter(stage__in=[PlatformDemoLead.STAGE_NEW, PlatformDemoLead.STAGE_CONTACTED])
        stage_title = "Leads (New & Inbound)"
        stage_desc = "New prospect enquiries requiring qualification and initial outreach"
    elif stage_key == 'interested':
        qs = qs.filter(stage=PlatformDemoLead.STAGE_INTERESTED)
        stage_title = "Interested Prospects"
        stage_desc = "Verified jewellery stores with confirmed interest and module requirements"
    elif stage_key == 'meetings':
        qs = qs.filter(stage=PlatformDemoLead.STAGE_MEETINGS)
        stage_title = "Meetings & Demos"
        stage_desc = "Product demonstrations and scheduled showroom meetings"
    elif stage_key == 'trial':
        qs = qs.filter(Q(stage=PlatformDemoLead.STAGE_TRIAL) | Q(converted_tenant__subscription__plan_name='trial', converted_tenant__subscription__status__in=['active', 'trial'])).distinct()
        stage_title = "Active 15-Day Free Trials"
        stage_desc = "Stores currently evaluating JwelDesk on active trial licenses"
    elif stage_key == 'proposals':
        qs = qs.filter(Q(stage=PlatformDemoLead.STAGE_PROPOSAL) | Q(proposals__is_latest=True)).distinct()
        stage_title = "Proposal & Closing"
        stage_desc = "Issued commercial proposals, discount terms, and closing negotiations"
    elif stage_key == 'orders':
        qs = qs.filter(stage=PlatformDemoLead.STAGE_ORDERS)
        stage_title = "Sales Orders"
        stage_desc = "Agreed commercial deals pending payment, paperwork, or onboarding"
    elif stage_key == 'customers':
        qs = qs.filter(Q(stage=PlatformDemoLead.STAGE_CUSTOMERS) | Q(converted_tenant__isnull=False)).distinct()
        stage_title = "Converted Customers"
        stage_desc = "Jewellery showroom accounts successfully converted to active JwelDesk clients"
    elif stage_key == 'subscribers':
        qs = qs.filter(converted_tenant__subscription__status='active').exclude(converted_tenant__subscription__plan_name='trial').distinct()
        stage_title = "Active Paid Subscribers"
        stage_desc = "Showrooms on recurring active Core, Pro, and Enterprise subscriptions"
    elif stage_key == 'renewals':
        now_dt = timezone.now()
        thirty_days_dt = now_dt + timedelta(days=30)
        qs = qs.filter(
            converted_tenant__subscription__status='active',
            converted_tenant__subscription__expires_at__gte=now_dt,
            converted_tenant__subscription__expires_at__lte=thirty_days_dt
        ).exclude(converted_tenant__subscription__plan_name='trial').distinct()
        stage_title = "Upcoming Subscription Renewals"
        stage_desc = "Client accounts expiring or requiring contract renewal within 30 days"
    elif stage_key == 'lost':
        qs = qs.filter(stage=PlatformDemoLead.STAGE_LOST)
        stage_title = "Lost / Closed Deals"
        stage_desc = "Closed opportunities with documented lost reasons for win-back analysis"

    # Search query
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(lead_name__icontains=q) |
            Q(contact_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(email__icontains=q) |
            Q(city__icontains=q) |
            Q(lead_id__icontains=q)
        )

    # Assigned staff filter
    staff_id = request.GET.get('staff')
    if staff_id and staff_id.isdigit():
        qs = qs.filter(assigned_staff_id=int(staff_id))

    # Business type filter
    b_type = request.GET.get('business_type')
    if b_type:
        qs = qs.filter(business_type=b_type)

    # Source filter
    src = request.GET.get('source')
    if src:
        qs = qs.filter(source=src)

    # Pagination
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    sales_staff = User.objects.filter(is_staff=True).order_by('first_name', 'username')

    context = {
        'page_title': f"Sales CRM — {stage_title}",
        'stage_key': stage_key,
        'current_sales_stage': stage_key,
        'stage_title': stage_title,
        'stage_desc': stage_desc,
        'sales_crm_counts': stage_counts,
        'page_obj': page_obj,
        'leads': page_obj,
        'total_in_stage': qs.count(),
        'sales_staff': sales_staff,
        'selected_q': q,
        'selected_staff': staff_id,
        'selected_type': b_type,
        'selected_source': src,
        'view_mode': view_mode,
        'today': today,
    }
    return render(request, 'super_admin/sales/stage_view.html', context)


# ============================================================================
# 3. KANBAN PIPELINE VIEW
# ============================================================================

@super_admin_required
def sales_pipeline_kanban_view(request):
    """
    Interactive Kanban Board visualising leads across all active sales pipeline stages.
    """
    stage_counts = get_sales_crm_stage_counts()
    leads = PlatformDemoLead.objects.select_related('assigned_staff', 'converted_tenant').order_by('-created_at')

    # Group leads by stage
    columns = [
        {'key': 'new', 'name': 'New Leads', 'badge': '#38bdf8', 'leads': []},
        {'key': 'contacted', 'name': 'Contacted', 'badge': '#0ea5e9', 'leads': []},
        {'key': 'interested', 'name': 'Interested', 'badge': '#eab308', 'leads': []},
        {'key': 'meetings', 'name': 'Meetings / Demos', 'badge': '#a855f7', 'leads': []},
        {'key': 'trial', 'name': 'Trial Active', 'badge': '#6366f1', 'leads': []},
        {'key': 'proposal', 'name': 'Proposal & Closing', 'badge': '#f97316', 'leads': []},
        {'key': 'orders', 'name': 'Sales Orders', 'badge': '#14b8a6', 'leads': []},
        {'key': 'customers', 'name': 'Won (Customers)', 'badge': '#10b981', 'leads': []},
        {'key': 'lost', 'name': 'Lost', 'badge': '#ef4444', 'leads': []},
    ]

    col_dict = {col['key']: col for col in columns}

    for lead in leads[:150]:
        st = lead.stage
        if st in col_dict:
            col_dict[st]['leads'].append(lead)
        else:
            col_dict['new']['leads'].append(lead)

    context = {
        'page_title': 'Sales Pipeline Kanban Board',
        'current_sales_stage': 'pipeline',
        'sales_crm_counts': stage_counts,
        'columns': columns,
        'all_staff': User.objects.filter(is_staff=True).order_by('first_name', 'username'),
    }
    return render(request, 'super_admin/sales/pipeline_kanban.html', context)


# ============================================================================
# 4. STAGE TRANSITION ACTION
# ============================================================================

@super_admin_required
@require_POST
def sales_stage_transition_view(request, lead_id):
    """
    Moves a lead from one pipeline stage to another,
    enforcing reason logging, audit tracking, and optional lost reason capture.
    """
    lead = get_object_or_404(PlatformDemoLead, id=lead_id)
    to_stage = request.POST.get('to_stage', '').strip().lower()
    reason = request.POST.get('reason', '').strip()
    deal_value = request.POST.get('deal_value', '').strip()

    valid_stages = dict(PlatformDemoLead.STAGE_CHOICES).keys()
    if to_stage not in valid_stages:
        messages.error(request, f"Invalid stage '{to_stage}'.")
        return redirect('super_admin:lead_detail', lead_id=lead.id)

    from_stage = lead.stage

    with transaction.atomic():
        lead.stage = to_stage
        if deal_value:
            try:
                lead.deal_value = Decimal(deal_value)
            except Exception:
                pass

        # Handle Lost stage requirements
        if to_stage == PlatformDemoLead.STAGE_LOST:
            lead.lost_reason = request.POST.get('lost_reason', PlatformDemoLead.LOST_OTHER)
            lead.lost_notes = request.POST.get('lost_notes', '')

        lead.save()

        # Record stage history
        PlatformLeadStageHistory.objects.create(
            lead=lead,
            from_stage=from_stage,
            to_stage=to_stage,
            changed_by=request.user,
            reason=reason or f"Moved from {from_stage} to {to_stage}"
        )

        # Audit log
        PlatformAuditLog.objects.create(
            actor=request.user,
            action='LEAD_STAGE_CHANGE',
            target_tenant=lead.converted_tenant,
            reason=f"Sales CRM: Moved {lead.lead_name} from {from_stage} to {to_stage}. {reason}",
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'lead_id': lead.id,
            'from_stage': from_stage,
            'to_stage': to_stage,
            'stage_display': lead.get_stage_display()
        })

    messages.success(request, f"Lead successfully moved to '{lead.get_stage_display()}'.")
    return redirect('super_admin:lead_detail', lead_id=lead.id)


# ============================================================================
# 5. NEGOTIATIONS & REQUIREMENTS
# ============================================================================

@super_admin_required
@require_POST
def sales_add_negotiation_view(request, lead_id):
    """Logs customer requirements, required modules, budget, and discussion summary."""
    lead = get_object_or_404(PlatformDemoLead, id=lead_id)

    target_plan = request.POST.get('target_plan', TenantSubscription.PLAN_PRO)
    modules = request.POST.getlist('modules')
    branches = int(request.POST.get('branches_count', 1))
    users = int(request.POST.get('users_count', 3))
    budget_raw = request.POST.get('budget', '0.00').strip()
    competitor = request.POST.get('competitor_info', '').strip()
    summary = request.POST.get('discussion_summary', '').strip()
    exp_date = request.POST.get('expected_purchase_date') or None

    try:
        budget = Decimal(budget_raw)
    except Exception:
        budget = Decimal('0.00')

    with transaction.atomic():
        PlatformLeadNegotiation.objects.create(
            lead=lead,
            target_plan=target_plan,
            required_modules=modules,
            branches_count=branches,
            users_count=users,
            budget=budget,
            expected_purchase_date=exp_date,
            competitor_info=competitor,
            discussion_summary=summary,
            conducted_by=request.user
        )

        if budget > 0:
            lead.deal_value = budget
            lead.save(update_fields=['deal_value'])

    messages.success(request, "Negotiation details & requirements logged successfully.")
    return redirect('super_admin:lead_detail', lead_id=lead.id)


# ============================================================================
# 6. MULTI-CHANNEL ACTIVITIES & FOLLOW-UP HUB
# ============================================================================

@super_admin_required
def sales_followups_view(request):
    """
    Centralized follow-up hub organizing activities by Today, Overdue, Upcoming, and Completed.
    """
    today = timezone.localdate()
    stage_counts = get_sales_crm_stage_counts()

    tab = request.GET.get('tab', 'today').lower()
    base_qs = PlatformLeadActivity.objects.select_related('lead', 'assigned_to', 'created_by')

    if tab == 'overdue':
        activities = base_qs.filter(is_completed=False, scheduled_at__date__lt=today).order_by('scheduled_at')
    elif tab == 'upcoming':
        activities = base_qs.filter(is_completed=False, scheduled_at__date__gt=today).order_by('scheduled_at')
    elif tab == 'completed':
        activities = base_qs.filter(is_completed=True).order_by('-completed_at')
    else:  # today
        activities = base_qs.filter(is_completed=False, scheduled_at__date=today).order_by('scheduled_at')

    # Filter by assigned rep
    staff_id = request.GET.get('staff')
    if staff_id and staff_id.isdigit():
        activities = activities.filter(assigned_to_id=int(staff_id))

    context = {
        'page_title': 'Sales Follow-up Hub',
        'current_sales_stage': 'followups',
        'sales_crm_counts': stage_counts,
        'activities': activities,
        'current_tab': tab,
        'counts': {
            'today': base_qs.filter(is_completed=False, scheduled_at__date=today).count(),
            'overdue': base_qs.filter(is_completed=False, scheduled_at__date__lt=today).count(),
            'upcoming': base_qs.filter(is_completed=False, scheduled_at__date__gt=today).count(),
            'completed': base_qs.filter(is_completed=True).count(),
        },
        'sales_staff': User.objects.filter(is_staff=True).order_by('first_name', 'username'),
        'today': today,
    }
    return render(request, 'super_admin/sales/followups.html', context)


@super_admin_required
@require_POST
def sales_add_activity_view(request, lead_id):
    """Schedules or logs an interaction (Call, WhatsApp, Email, Meeting, Demo, Site Visit)."""
    lead = get_object_or_404(PlatformDemoLead, id=lead_id)

    activity_type = request.POST.get('activity_type', PlatformLeadActivity.ACTIVITY_CALL)
    title = request.POST.get('title', '').strip()
    scheduled_at_raw = request.POST.get('scheduled_at') or None
    scheduled_at = None
    if scheduled_at_raw:
        from django.utils.dateparse import parse_datetime
        parsed_dt = parse_datetime(scheduled_at_raw)
        if parsed_dt:
            scheduled_at = timezone.make_aware(parsed_dt) if timezone.is_naive(parsed_dt) else parsed_dt
        else:
            scheduled_at = scheduled_at_raw
    is_completed = request.POST.get('is_completed') == '1'
    outcome_notes = request.POST.get('outcome_notes', '').strip()
    assigned_to_id = request.POST.get('assigned_to')
    next_date = request.POST.get('next_follow_up_date') or None

    assigned_to = User.objects.filter(id=assigned_to_id).first() if assigned_to_id else request.user

    with transaction.atomic():
        act = PlatformLeadActivity.objects.create(
            lead=lead,
            activity_type=activity_type,
            title=title or f"{dict(PlatformLeadActivity.ACTIVITY_CHOICES).get(activity_type, 'Activity')} with {lead.contact_name}",
            scheduled_at=scheduled_at,
            is_completed=is_completed,
            completed_at=timezone.now() if is_completed else None,
            outcome_notes=outcome_notes,
            next_follow_up_date=next_date,
            assigned_to=assigned_to,
            created_by=request.user
        )

        if next_date:
            lead.follow_up_date = next_date
            lead.save(update_fields=['follow_up_date'])

    messages.success(request, "Sales activity logged successfully.")
    return redirect('super_admin:lead_detail', lead_id=lead.id)


@super_admin_required
@require_POST
def sales_toggle_activity_view(request, activity_id):
    """Marks a scheduled follow-up activity as completed or reopens it."""
    activity = get_object_or_404(PlatformLeadActivity, id=activity_id)
    activity.is_completed = not activity.is_completed
    activity.completed_at = timezone.now() if activity.is_completed else None
    activity.save(update_fields=['is_completed', 'completed_at'])

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'is_completed': activity.is_completed})

    status_str = "completed" if activity.is_completed else "reopened"
    messages.success(request, f"Activity marked as {status_str}.")
    return redirect('super_admin:followup_list')


# ============================================================================
# 7. SALES REPORTS & ANALYTICS
# ============================================================================

@super_admin_required
def sales_reports_view(request):
    """
    Comprehensive Sales Performance Reports:
    Conversion rates, Source analysis, Rep leaderboard, Monthly revenue, Proposal win rates.
    """
    stage_counts = get_sales_crm_stage_counts()
    today = timezone.localdate()

    # Source breakdown
    source_data = PlatformDemoLead.objects.values('source').annotate(
        total=Count('id'),
        won=Count('id', filter=Q(stage=PlatformDemoLead.STAGE_CUSTOMERS) | Q(converted_tenant__isnull=False)),
        lost=Count('id', filter=Q(stage=PlatformDemoLead.STAGE_LOST)),
        total_val=Sum('deal_value')
    ).order_by('-total')

    # Executive performance
    exec_data = User.objects.filter(is_staff=True).annotate(
        leads=Count('assigned_demo_leads', distinct=True),
        won=Count('assigned_demo_leads', filter=Q(assigned_demo_leads__stage=PlatformDemoLead.STAGE_CUSTOMERS) | Q(assigned_demo_leads__converted_tenant__isnull=False), distinct=True),
        lost=Count('assigned_demo_leads', filter=Q(assigned_demo_leads__stage=PlatformDemoLead.STAGE_LOST), distinct=True),
        revenue=Sum('assigned_demo_leads__deal_value')
    ).order_by('-won', '-leads')

    # Lost reasons distribution
    lost_reasons = PlatformDemoLead.objects.filter(stage=PlatformDemoLead.STAGE_LOST).values('lost_reason').annotate(
        count=Count('id')
    ).order_by('-count')

    # Proposal statistics
    total_proposals = PlatformProposal.objects.filter(is_latest=True).count()
    accepted_proposals = PlatformProposal.objects.filter(is_latest=True, status=PlatformProposal.STATUS_ACCEPTED).count()
    proposal_win_rate = round((accepted_proposals / total_proposals * 100), 1) if total_proposals > 0 else 0

    context = {
        'page_title': 'Sales Reports & Analytics',
        'current_sales_stage': 'reports',
        'sales_crm_counts': stage_counts,
        'source_data': source_data,
        'exec_data': exec_data,
        'lost_reasons': lost_reasons,
        'proposal_stats': {
            'total': total_proposals,
            'accepted': accepted_proposals,
            'win_rate': proposal_win_rate,
        },
        'today': today,
    }
    return render(request, 'super_admin/sales/reports.html', context)


# ============================================================================
# 8. SAFE TENANT CONVERSION WORKFLOW
# ============================================================================

@super_admin_required
@require_POST
def sales_convert_tenant_view(request, lead_id):
    """
    Safely converts a Won lead into an active showroom Tenant account.
    Avoids duplicate accounts, connects subscription tier, and preserves lead history.
    """
    lead = get_object_or_404(PlatformDemoLead, id=lead_id)

    if lead.converted_tenant:
        messages.info(request, f"Lead is already linked to tenant '{lead.converted_tenant.name}'.")
        return redirect('super_admin:showroom_detail', tenant_id=lead.converted_tenant.id)

    link_existing_id = request.POST.get('existing_tenant_id')
    target_plan = request.POST.get('target_plan', TenantSubscription.PLAN_PRO)

    with transaction.atomic():
        if link_existing_id and link_existing_id.isdigit():
            # Link existing tenant
            tenant = get_object_or_404(Tenant, id=int(link_existing_id))
        else:
            # Create a clean new Tenant account
            from django.utils.text import slugify
            base_slug = slugify(lead.lead_name) or f"store-{lead.id}"
            slug = base_slug
            counter = 1
            while Tenant.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            # Business type mapping
            b_map = {'RETAIL': Tenant.TYPE_RETAIL, 'WHOLESALE': Tenant.TYPE_WHOLESALE, 'BOTH': Tenant.TYPE_BOTH}
            b_type = b_map.get(lead.business_type, Tenant.TYPE_RETAIL)

            owner = None
            if lead.email:
                owner = User.objects.filter(email=lead.email).first()
            if not owner and lead.assigned_staff:
                owner = lead.assigned_staff
            if not owner:
                owner = request.user

            tenant = Tenant.objects.create(
                name=lead.lead_name,
                slug=slug,
                owner=owner,
                business_type=b_type,
                is_active=True
            )

        # Connect or update TenantSubscription
        sub = TenantSubscription.objects.filter(tenant=tenant).first()
        if not sub:
            now_dt = timezone.now()
            exp_dt = now_dt + timedelta(days=15 if target_plan == TenantSubscription.PLAN_TRIAL else 365)
            TenantSubscription.objects.create(
                tenant=tenant,
                plan_name=target_plan,
                status=TenantSubscription.STATUS_ACTIVE if target_plan != TenantSubscription.PLAN_TRIAL else TenantSubscription.STATUS_TRIAL,
                billing_cycle=TenantSubscription.CYCLE_YEARLY,
                price=lead.deal_value or Decimal('29999.00'),
                started_at=now_dt,
                expires_at=exp_dt
            )

        # Mark lead as converted
        lead.converted_tenant = tenant
        lead.conversion_date = timezone.now()
        lead.stage = PlatformDemoLead.STAGE_CUSTOMERS
        lead.status = PlatformDemoLead.STATUS_CONVERTED
        lead.save()

        # Audit log
        PlatformAuditLog.objects.create(
            actor=request.user,
            action='DEAL_WON',
            target_tenant=tenant,
            reason=f"Sales CRM: Won deal converted to Tenant '{tenant.name}' (Plan: {target_plan}).",
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )

    messages.success(request, f"Lead successfully converted! Tenant '{tenant.name}' is now active.")
    return redirect('super_admin:showroom_detail', tenant_id=tenant.id)
