"""
girvi/views.py
--------------
Views for the JwelDesk Girvi (Jewellery Pledge & Loan Management) module.
Handles dashboard, loan creation, multi-item collateral tracking, payments,
auditable reversals, waivers, jewellery release, printable vouchers, and settings.
"""

from decimal import Decimal
import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from team.permissions import require_permission, check_branch_access, is_admin_user
from team.models import Branch
from customers.models import Customer
from inventory.models import Category

from .models import (
    GirviSetting,
    GirviLoan,
    GirviItem,
    GirviPayment,
    GirviWaiver,
    GirviAuditLog,
)
from .forms import (
    GirviLoanForm,
    GirviItemFormSet,
    GirviPaymentForm,
    GirviPaymentReverseForm,
    GirviWaiverForm,
    GirviReleaseForm,
    GirviSettingForm,
)
from .services import (
    get_or_create_girvi_settings,
    get_next_sequence_number,
    calculate_loan_financials,
    record_payment,
    reverse_payment,
    record_waiver,
    release_collateral,
)


def get_client_ip(request):
    """Extract client IP address for audit logs."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


@login_required
@require_permission('girvi', 'view')
def girvi_dashboard(request):
    """
    Girvi Management Cockpit & Dashboard.
    Provides real-time KPIs: Active Loans, Outstanding Principal, Accrued Interest,
    Overdue Loans, Loans Expiring Soon, and Collateral Metal Breakdown.
    """
    tenant = request.tenant
    active_b = request.branch if not getattr(request, 'is_all_branches', False) else None

    loans_qs = GirviLoan.objects.filter(tenant=tenant)
    if active_b:
        loans_qs = loans_qs.filter(branch=active_b)

    today = timezone.localdate()
    soon_threshold = today + datetime.timedelta(days=15)

    # Base counts and aggregates
    active_loans = loans_qs.filter(status=GirviLoan.STATUS_ACTIVE)
    overdue_loans = loans_qs.filter(
        Q(status=GirviLoan.STATUS_OVERDUE) |
        (Q(status=GirviLoan.STATUS_ACTIVE) & Q(maturity_date__lt=today))
    )
    due_soon_loans = loans_qs.filter(
        status=GirviLoan.STATUS_ACTIVE,
        maturity_date__gte=today,
        maturity_date__lte=soon_threshold
    ).order_by('maturity_date')

    # Calculate financial aggregates across active & overdue loans
    total_active_count = active_loans.count()
    total_overdue_count = overdue_loans.count()

    total_outstanding_principal = Decimal('0.00')
    total_interest_accrued = Decimal('0.00')
    total_outstanding_balance = Decimal('0.00')

    # Pre-fetch items and payments to optimize calculation
    active_and_overdue = loans_qs.filter(
        status__in=[GirviLoan.STATUS_ACTIVE, GirviLoan.STATUS_OVERDUE]
    ).select_related('customer', 'branch').prefetch_related('payments', 'waivers', 'items')

    for loan in active_and_overdue:
        fin = calculate_loan_financials(loan, as_of_date=today)
        total_outstanding_principal += fin['remaining_principal']
        total_interest_accrued += fin['remaining_interest']
        total_outstanding_balance += fin['outstanding_balance']

    # Collateral metal weights held in vault
    vault_items = GirviItem.objects.filter(
        loan__tenant=tenant,
        custody_status=GirviItem.CUSTODY_IN_VAULT
    )
    if active_b:
        vault_items = vault_items.filter(loan__branch=active_b)

    gold_weight = vault_items.filter(metal_type='Gold').aggregate(
        gross=Sum('gross_weight'), net=Sum('net_weight')
    )
    silver_weight = vault_items.filter(metal_type='Silver').aggregate(
        gross=Sum('gross_weight'), net=Sum('net_weight')
    )

    # Recently created loans
    recent_loans = loans_qs.select_related('customer', 'branch').prefetch_related('items')[:8]

    # Attach live balance to recent loans
    recent_loans_data = []
    for l in recent_loans:
        fin = calculate_loan_financials(l, as_of_date=today)
        recent_loans_data.append({
            'loan': l,
            'financials': fin,
        })

    # Due soon loans data
    due_soon_data = []
    for l in due_soon_loans[:6]:
        fin = calculate_loan_financials(l, as_of_date=today)
        due_soon_data.append({
            'loan': l,
            'financials': fin,
            'days_left': (l.maturity_date - today).days if l.maturity_date else None,
        })

    context = {
        'page_title': 'Girvi Dashboard',
        'active_branch': active_b,
        'total_active_count': total_active_count,
        'total_overdue_count': total_overdue_count,
        'total_outstanding_principal': total_outstanding_principal,
        'total_interest_accrued': total_interest_accrued,
        'total_outstanding_balance': total_outstanding_balance,
        'gold_gross_weight': gold_weight['gross'] or Decimal('0.000'),
        'gold_net_weight': gold_weight['net'] or Decimal('0.000'),
        'silver_gross_weight': silver_weight['gross'] or Decimal('0.000'),
        'silver_net_weight': silver_weight['net'] or Decimal('0.000'),
        'recent_loans': recent_loans_data,
        'due_soon_loans': due_soon_data,
    }
    return render(request, 'girvi/dashboard.html', context)


@login_required
@require_permission('girvi', 'view')
def girvi_loan_list(request):
    """
    Searchable and filterable registry of all Girvi Loans.
    Filters: Branch, Status, Date Range, Customer/Phone search.
    """
    tenant = request.tenant
    active_b = request.branch if not getattr(request, 'is_all_branches', False) else None

    loans_qs = GirviLoan.objects.filter(tenant=tenant).select_related('customer', 'branch').prefetch_related('items', 'payments', 'waivers')

    # Branch filtering
    selected_branch_id = request.GET.get('branch', '')
    if selected_branch_id:
        try:
            loans_qs = loans_qs.filter(branch_id=int(selected_branch_id))
        except ValueError:
            pass
    elif active_b:
        loans_qs = loans_qs.filter(branch=active_b)

    # Status filtering
    status_filter = request.GET.get('status', 'all').strip()
    today = timezone.localdate()
    if status_filter == 'active':
        loans_qs = loans_qs.filter(status=GirviLoan.STATUS_ACTIVE)
    elif status_filter == 'overdue':
        loans_qs = loans_qs.filter(
            Q(status=GirviLoan.STATUS_OVERDUE) |
            (Q(status=GirviLoan.STATUS_ACTIVE) & Q(maturity_date__lt=today))
        )
    elif status_filter == 'settled':
        loans_qs = loans_qs.filter(status=GirviLoan.STATUS_SETTLED)
    elif status_filter == 'released':
        loans_qs = loans_qs.filter(status=GirviLoan.STATUS_RELEASED)

    # Date range filtering
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()
    if start_date:
        try:
            loans_qs = loans_qs.filter(loan_date__gte=start_date)
        except Exception:
            pass
    if end_date:
        try:
            loans_qs = loans_qs.filter(loan_date__lte=end_date)
        except Exception:
            pass

    # Search keyword
    q = request.GET.get('q', '').strip()
    if q:
        loans_qs = loans_qs.filter(
            Q(loan_number__icontains=q) |
            Q(customer__name__icontains=q) |
            Q(customer__mobile__icontains=q) |
            Q(custody_location__icontains=q)
        )

    # Pagination
    paginator = Paginator(loans_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Compute financial snapshots for current page items
    loan_rows = []
    for loan in page_obj:
        fin = calculate_loan_financials(loan, as_of_date=today)
        loan_rows.append({
            'loan': loan,
            'financials': fin,
            'items_count': loan.items.count(),
            'total_net_weight': sum(it.net_weight for it in loan.items.all()),
        })

    # Available branches for filter dropdown
    branches = Branch.objects.filter(tenant=tenant, is_active=True).order_by('name')

    context = {
        'page_title': 'Girvi Loans Directory',
        'page_obj': page_obj,
        'loan_rows': loan_rows,
        'branches': branches,
        'status_filter': status_filter,
        'selected_branch_id': selected_branch_id,
        'start_date': start_date,
        'end_date': end_date,
        'q': q,
        'active_branch': active_b,
    }
    return render(request, 'girvi/loan_list.html', context)


@login_required
@require_permission('girvi', 'add')
def girvi_loan_create(request):
    """
    Create a new Girvi Loan agreement with multiple pledged collateral items.
    Snapshots showroom financial defaults so subsequent setting changes never affect this loan.
    """
    tenant = request.tenant
    active_b = request.branch if not getattr(request, 'is_all_branches', False) else None
    available_branches = getattr(request, 'available_branches', None)
    settings_obj = get_or_create_girvi_settings(tenant)

    if request.method == 'POST':
        form = GirviLoanForm(
            request.POST,
            tenant=tenant,
            branch=active_b,
            available_branches=available_branches
        )
        item_formset = GirviItemFormSet(request.POST, request.FILES)

        if form.is_valid() and item_formset.is_valid():
            with transaction.atomic():
                loan = form.save(commit=False)
                loan.tenant = tenant
                loan.created_by = request.user

                # Verify branch access
                if not check_branch_access(request, loan):
                    raise PermissionDenied("You do not have permission to book loans for this branch.")

                # Generate unique sequential loan number
                loan.loan_number = get_next_sequence_number(tenant, sequence_type='loan')

                # Snapshot standard terms if empty
                if not loan.terms_conditions and settings_obj.standard_terms_conditions:
                    loan.terms_conditions = settings_obj.standard_terms_conditions

                loan.save()

                # Save collateral items
                item_instances = item_formset.save(commit=False)
                valuation_sum = Decimal('0.00')
                for item in item_instances:
                    item.loan = loan
                    item.save()
                    valuation_sum += (item.market_value or Decimal('0.00'))

                # Update total collateral valuation on loan
                loan.valuation_total = valuation_sum
                loan.save(update_fields=['valuation_total'])

                # Log audit trail
                GirviAuditLog.objects.create(
                    tenant=tenant,
                    loan=loan,
                    action='LOAN_CREATED',
                    user=request.user,
                    ip_address=get_client_ip(request),
                    details=(
                        f"Booked new Girvi Loan #{loan.loan_number} for customer {loan.customer.name}. "
                        f"Principal: ₹{loan.principal_amount}, Rate: {loan.interest_rate_percent}% "
                        f"({loan.get_interest_period_display()}), Collateral Pieces: {len(item_instances)}."
                    )
                )

                messages.success(
                    request,
                    f"Girvi Loan #{loan.loan_number} created successfully for {loan.customer.name}!"
                )
                return redirect('girvi:loan_detail', loan_id=loan.id)
        else:
            messages.error(request, "Please correct the errors in the form below.")
    else:
        # Prepopulate with defaults from GirviSetting
        initial_data = {
            'loan_date': timezone.localdate(),
            'interest_rate_percent': settings_obj.default_interest_rate_monthly,
            'interest_period': settings_obj.default_interest_period,
            'interest_calculation_type': settings_obj.default_calculation_type,
            'loan_duration_months': settings_obj.default_loan_duration_months,
            'grace_period_days': settings_obj.default_grace_period_days,
            'terms_conditions': settings_obj.standard_terms_conditions,
        }
        # Pre-calculate initial maturity date
        if settings_obj.default_loan_duration_months:
            initial_data['maturity_date'] = timezone.localdate() + datetime.timedelta(
                days=settings_obj.default_loan_duration_months * 30
            )

        form = GirviLoanForm(
            initial=initial_data,
            tenant=tenant,
            branch=active_b,
            available_branches=available_branches
        )
        item_formset = GirviItemFormSet()

    context = {
        'page_title': 'New Girvi Loan Entry',
        'form': form,
        'item_formset': item_formset,
        'settings': settings_obj,
        'categories': Category.objects.filter(tenant=tenant),
    }
    return render(request, 'girvi/loan_form.html', context)


@login_required
@require_permission('girvi', 'view')
def girvi_loan_detail(request, loan_id):
    """
    Comprehensive Loan Dossier & Details View.
    Displays:
    - Master Agreement & snapshot terms
    - Pledged Jewellery Collateral pieces (photos, weights, purity, custody status)
    - Real-time financial position (accrued interest, payments, waivers, balance)
    - Payment History with reversal controls
    - Waivers Applied
    - Audit Trail
    """
    tenant = request.tenant
    loan = get_object_or_404(
        GirviLoan.objects.select_related('customer', 'branch', 'created_by', 'released_by').prefetch_related(
            'items__category', 'payments__received_by', 'waivers__authorized_by', 'audit_logs__user'
        ),
        id=loan_id,
        tenant=tenant
    )

    if not check_branch_access(request, loan):
        raise PermissionDenied("You do not have permission to view records for this branch.")

    financials = calculate_loan_financials(loan)
    items = loan.items.all()
    payments = loan.payments.all().order_by('-payment_date', '-id')
    waivers = loan.waivers.all().order_by('-created_at')
    audit_logs = loan.audit_logs.all().order_by('-created_at')[:25]

    payment_form = GirviPaymentForm(loan=loan)
    reversal_form = GirviPaymentReverseForm()
    waiver_form = GirviWaiverForm()
    release_form = GirviReleaseForm()

    context = {
        'page_title': f"Girvi Loan #{loan.loan_number} — {loan.customer.name}",
        'loan': loan,
        'financials': financials,
        'items': items,
        'payments': payments,
        'waivers': waivers,
        'audit_logs': audit_logs,
        'payment_form': payment_form,
        'reversal_form': reversal_form,
        'waiver_form': waiver_form,
        'release_form': release_form,
        'is_admin': is_admin_user(request.user, tenant=tenant),
    }
    return render(request, 'girvi/loan_detail.html', context)


@login_required
@require_permission('girvi', 'edit')
def girvi_payment_create(request, loan_id):
    """Record an incoming payment against a Girvi loan."""
    tenant = request.tenant
    loan = get_object_or_404(GirviLoan, id=loan_id, tenant=tenant)

    if not check_branch_access(request, loan):
        raise PermissionDenied("You do not have permission to record payments for this branch.")

    if loan.status == GirviLoan.STATUS_RELEASED:
        messages.error(request, "This loan is already released and closed.")
        return redirect('girvi:loan_detail', loan_id=loan.id)

    if request.method == 'POST':
        form = GirviPaymentForm(request.POST, loan=loan)
        if form.is_valid():
            try:
                payment = record_payment(
                    loan=loan,
                    data=form.cleaned_data,
                    user=request.user,
                    ip_address=get_client_ip(request)
                )
                messages.success(
                    request,
                    f"Payment of ₹{payment.total_amount_received} recorded successfully! Receipt #{payment.receipt_number}."
                )
                return redirect('girvi:payment_receipt_print', payment_id=payment.id)
            except ValidationError as e:
                messages.error(request, str(e.message if hasattr(e, 'message') else e))
        else:
            messages.error(request, "Please fix the errors in the payment form.")

    return redirect('girvi:loan_detail', loan_id=loan.id)


@login_required
@require_permission('girvi', 'edit')
@require_POST
def girvi_payment_reverse(request, payment_id):
    """
    Auditable payment reversal.
    Restores loan balance and creates a negative counter-entry.
    """
    tenant = request.tenant
    payment = get_object_or_404(
        GirviPayment.objects.select_related('loan', 'branch'),
        id=payment_id,
        tenant=tenant
    )

    if not check_branch_access(request, payment.loan):
        raise PermissionDenied("You do not have permission to reverse payments for this branch.")

    form = GirviPaymentReverseForm(request.POST)
    if form.is_valid():
        try:
            reversal = reverse_payment(
                payment=payment,
                reason=form.cleaned_data['reason'],
                user=request.user,
                ip_address=get_client_ip(request)
            )
            messages.success(
                request,
                f"Payment #{payment.receipt_number} has been reversed. Reversal entry #{reversal.receipt_number} created."
            )
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
    else:
        messages.error(request, "A mandatory reason is required to reverse a payment.")

    return redirect('girvi:loan_detail', loan_id=payment.loan_id)


@login_required
@require_permission('girvi', 'edit')
@require_POST
def girvi_waiver_create(request, loan_id):
    """Record an explicit financial waiver/discount."""
    tenant = request.tenant
    loan = get_object_or_404(GirviLoan, id=loan_id, tenant=tenant)

    if not check_branch_access(request, loan):
        raise PermissionDenied("You do not have permission to approve waivers for this branch.")

    form = GirviWaiverForm(request.POST)
    if form.is_valid():
        try:
            waiver = record_waiver(
                loan=loan,
                waiver_type=form.cleaned_data['waiver_type'],
                amount=form.cleaned_data['amount'],
                reason=form.cleaned_data['reason'],
                user=request.user,
                ip_address=get_client_ip(request)
            )
            messages.success(
                request,
                f"Waiver of ₹{waiver.amount} ({waiver.get_waiver_type_display()}) authorized successfully."
            )
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
    else:
        messages.error(request, "Invalid waiver details provided.")

    return redirect('girvi:loan_detail', loan_id=loan.id)


@login_required
@require_permission('girvi', 'edit')
def girvi_collateral_release(request, loan_id):
    """
    Handover and physical release of pledged jewellery collateral to the borrower.
    Requires loan to be fully settled (outstanding balance <= 0).
    """
    tenant = request.tenant
    loan = get_object_or_404(GirviLoan, id=loan_id, tenant=tenant)

    if not check_branch_access(request, loan):
        raise PermissionDenied("You do not have permission to release collateral for this branch.")

    financials = calculate_loan_financials(loan)

    if request.method == 'POST':
        form = GirviReleaseForm(request.POST)
        if form.is_valid():
            try:
                release_collateral(
                    loan=loan,
                    user=request.user,
                    notes=form.cleaned_data.get('notes', ''),
                    ip_address=get_client_ip(request)
                )
                messages.success(
                    request,
                    f"Pledged jewellery for Loan #{loan.loan_number} has been released to {loan.customer.name}! "
                    f"Release Voucher #{loan.release_receipt_number}."
                )
                return redirect('girvi:release_receipt_print', loan_id=loan.id)
            except ValidationError as e:
                messages.error(request, str(e.message if hasattr(e, 'message') else e))
        else:
            messages.error(request, "Please check the confirmation box to proceed with release.")
    else:
        form = GirviReleaseForm()

    context = {
        'page_title': f"Release Jewellery Collateral — Loan #{loan.loan_number}",
        'loan': loan,
        'financials': financials,
        'items': loan.items.all(),
        'form': form,
    }
    return render(request, 'girvi/release_form.html', context)


@login_required
@require_permission('girvi', 'view')
def girvi_loan_print(request, loan_id):
    """Printable Girvi Loan Voucher & Legal Pledge Agreement."""
    tenant = request.tenant
    loan = get_object_or_404(
        GirviLoan.objects.select_related('customer', 'branch', 'created_by').prefetch_related('items'),
        id=loan_id,
        tenant=tenant
    )
    if not check_branch_access(request, loan):
        raise PermissionDenied("Access denied.")

    financials = calculate_loan_financials(loan)
    settings_obj = get_or_create_girvi_settings(tenant)

    context = {
        'loan': loan,
        'financials': financials,
        'items': loan.items.all(),
        'settings': settings_obj,
        'company': getattr(tenant, 'company_settings', None),
        'print_time': timezone.now(),
    }
    return render(request, 'girvi/print_loan_voucher.html', context)


@login_required
@require_permission('girvi', 'view')
def girvi_payment_receipt_print(request, payment_id):
    """Printable Payment Receipt for Girvi loan payments."""
    tenant = request.tenant
    payment = get_object_or_404(
        GirviPayment.objects.select_related('loan__customer', 'loan__branch', 'received_by'),
        id=payment_id,
        tenant=tenant
    )
    if not check_branch_access(request, payment.loan):
        raise PermissionDenied("Access denied.")

    financials = calculate_loan_financials(payment.loan, as_of_date=payment.payment_date)

    context = {
        'payment': payment,
        'loan': payment.loan,
        'financials': financials,
        'company': getattr(tenant, 'company_settings', None),
        'print_time': timezone.now(),
    }
    return render(request, 'girvi/print_payment_receipt.html', context)


@login_required
@require_permission('girvi', 'view')
def girvi_release_receipt_print(request, loan_id):
    """Printable Collateral Handover & Discharge Voucher."""
    tenant = request.tenant
    loan = get_object_or_404(
        GirviLoan.objects.select_related('customer', 'branch', 'released_by').prefetch_related('items'),
        id=loan_id,
        tenant=tenant
    )
    if not check_branch_access(request, loan):
        raise PermissionDenied("Access denied.")

    context = {
        'loan': loan,
        'items': loan.items.all(),
        'company': getattr(tenant, 'company_settings', None),
        'print_time': timezone.now(),
    }
    return render(request, 'girvi/print_release_receipt.html', context)


@login_required
@require_permission('girvi', 'edit')
def girvi_settings(request):
    """Configure showroom-level default Girvi terms and voucher prefixes."""
    tenant = request.tenant
    settings_obj = get_or_create_girvi_settings(tenant)

    if request.method == 'POST':
        form = GirviSettingForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Girvi showroom settings updated successfully. Defaults will apply to future loans.")
            return redirect('girvi:settings')
        else:
            messages.error(request, "Please correct the errors in the settings form.")
    else:
        form = GirviSettingForm(instance=settings_obj)

    context = {
        'page_title': 'Girvi Settings & Defaults',
        'form': form,
        'settings': settings_obj,
    }
    return render(request, 'girvi/settings.html', context)


@login_required
@require_permission('customers', 'add')
@require_POST
def customer_quick_add(request):
    """Quickly create a customer via AJAX modal from Girvi loan creation page."""
    tenant = request.tenant
    name = request.POST.get('name', '').strip()
    phone = request.POST.get('phone', '').strip()
    email = request.POST.get('email', '').strip()
    address = request.POST.get('address', '').strip()
    city = request.POST.get('city', '').strip()
    pan_number = request.POST.get('pan_number', '').strip()
    aadhaar_number = request.POST.get('aadhaar_number', '').strip()

    if not name or not phone:
        return JsonResponse({'success': False, 'error': "Name and phone number are required."}, status=400)

    active_b = request.branch if not getattr(request, 'is_all_branches', False) else None

    customer = Customer.objects.create(
        tenant=tenant,
        branch=active_b,
        name=name,
        mobile=phone,
        email=email or None,
        address=address,
        city=city,
        pan_number=pan_number,
        aadhaar_number=aadhaar_number,
    )

    return JsonResponse({
        'success': True,
        'customer': {
            'id': customer.id,
            'name': customer.name,
            'phone': customer.phone,
            'city': customer.city or '',
        }
    })
