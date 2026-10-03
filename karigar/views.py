import csv
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from custom_orders.models import CustomOrder
from inventory.models import JewelleryItem, StockMovement
from inventory.stock import apply_stock_change
from team.models import EmployeePermission
from team.permissions import require_permission

from .forms import (
    KarigarCancelSettlementForm,
    KarigarForm,
    KarigarReceiveWorkForm,
    KarigarSettlementForm,
    KarigarWorkAssignmentForm,
)
from .models import Karigar, KarigarSettlement, KarigarWorkAssignment

PAGE_SIZE = 15


# ==============================================================================
# 1. KARIGAR DASHBOARD
# ==============================================================================

@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'view')
def dashboard(request):
    """Manufacturing & Karigar operational command center."""
    today = timezone.localdate()

    # Metrics
    total_active_karigars = Karigar.objects.filter(status=Karigar.STATUS_ACTIVE).count()
    total_karigars = Karigar.objects.count()

    active_assignments = KarigarWorkAssignment.objects.exclude(
        status__in=[KarigarWorkAssignment.STATUS_RECEIVED, KarigarWorkAssignment.STATUS_CANCELLED]
    )

    work_assigned = active_assignments.filter(status=KarigarWorkAssignment.STATUS_ASSIGNED).count()
    work_in_progress = active_assignments.filter(status=KarigarWorkAssignment.STATUS_IN_PROGRESS).count()
    work_completed = active_assignments.filter(status=KarigarWorkAssignment.STATUS_COMPLETED).count()

    overdue_assignments = active_assignments.filter(
        expected_completion_date__lt=today
    )
    overdue_count = overdue_assignments.count()

    # Metal holdings currently in artisan custody
    gold_held = active_assignments.filter(metal_type='Gold').aggregate(
        total=Sum('net_weight_issued')
    )['total'] or Decimal('0.000')

    silver_held = active_assignments.filter(metal_type='Silver').aggregate(
        total=Sum('net_weight_issued')
    )['total'] or Decimal('0.000')

    # Total labour dues
    all_valid_works = KarigarWorkAssignment.objects.exclude(status=KarigarWorkAssignment.STATUS_CANCELLED)
    total_charges = all_valid_works.aggregate(total=Sum('total_charge'))['total'] or Decimal('0.00')
    total_paid = KarigarSettlement.objects.filter(status='Completed').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    pending_dues = max(Decimal('0.00'), total_charges - total_paid)

    # Recent lists
    recent_assignments = KarigarWorkAssignment.objects.select_related('karigar', 'customer').order_by('-id')[:8]
    recent_settlements = KarigarSettlement.objects.select_related('karigar', 'processed_by').order_by('-id')[:6]
    overdue_list = overdue_assignments.select_related('karigar', 'customer').order_by('expected_completion_date')[:6]

    # Top artisans by active assignments
    top_karigars = Karigar.objects.filter(status=Karigar.STATUS_ACTIVE).annotate(
        active_count=Count(
            'assignments',
            filter=Q(assignments__status__in=[
                KarigarWorkAssignment.STATUS_ASSIGNED,
                KarigarWorkAssignment.STATUS_IN_PROGRESS,
                KarigarWorkAssignment.STATUS_COMPLETED,
            ])
        )
    ).order_by('-active_count')[:5]

    context = {
        'page_title': 'Karigar & Manufacturing Dashboard',
        'total_active_karigars': total_active_karigars,
        'total_karigars': total_karigars,
        'work_assigned': work_assigned,
        'work_in_progress': work_in_progress,
        'work_completed': work_completed,
        'overdue_count': overdue_count,
        'gold_held': gold_held,
        'silver_held': silver_held,
        'pending_dues': pending_dues,
        'total_charges': total_charges,
        'total_paid': total_paid,
        'recent_assignments': recent_assignments,
        'recent_settlements': recent_settlements,
        'overdue_list': overdue_list,
        'top_karigars': top_karigars,
    }
    return render(request, 'karigar/dashboard.html', context)


# ==============================================================================
# 2. KARIGAR MASTER VIEWS
# ==============================================================================

@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'view')
def karigar_list(request):
    """Artisan directory with search, specialization filters, and status toggle."""
    queryset = Karigar.objects.annotate(
        active_work_count=Count(
            'assignments',
            filter=Q(assignments__status__in=[
                KarigarWorkAssignment.STATUS_ASSIGNED,
                KarigarWorkAssignment.STATUS_IN_PROGRESS,
            ])
        )
    ).order_by('name')

    q = request.GET.get('q', '').strip()
    if q:
        queryset = queryset.filter(
            Q(name__icontains=q)
            | Q(karigar_code__icontains=q)
            | Q(mobile__icontains=q)
            | Q(email__icontains=q)
            | Q(specialization__icontains=q)
        )

    status = request.GET.get('status', '').strip()
    if status:
        queryset = queryset.filter(status=status)

    specialization = request.GET.get('specialization', '').strip()
    if specialization:
        queryset = queryset.filter(specialization=specialization)

    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_title': 'Karigars / Artisans Directory',
        'karigars': page_obj,
        'page_obj': page_obj,
        'q': q,
        'selected_status': status,
        'selected_specialization': specialization,
        'specialization_choices': Karigar.SPECIALIZATION_CHOICES,
        'status_choices': Karigar.STATUS_CHOICES,
        'total_count': queryset.count(),
    }
    return render(request, 'karigar/karigar_list.html', context)


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'add')
def karigar_create(request):
    """Add a new Karigar master record."""
    if request.method == 'POST':
        form = KarigarForm(request.POST)
        if form.is_valid():
            karigar = form.save()
            messages.success(request, f"Karigar '{karigar.name}' ({karigar.karigar_code}) created successfully.")
            return redirect('karigar:karigar_detail', pk=karigar.pk)
    else:
        form = KarigarForm()

    return render(request, 'karigar/karigar_form.html', {
        'page_title': 'Add New Karigar',
        'form': form,
        'is_edit': False,
    })


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'view')
def karigar_detail(request, pk):
    """Detailed profile of a Karigar with active work, history, and accountability."""
    karigar = get_object_or_404(Karigar, pk=pk)

    # Active assignments
    active_works = karigar.assignments.filter(
        status__in=[
            KarigarWorkAssignment.STATUS_ASSIGNED,
            KarigarWorkAssignment.STATUS_IN_PROGRESS,
            KarigarWorkAssignment.STATUS_COMPLETED,
        ]
    ).select_related('customer', 'custom_order')

    # Completed history with pagination
    history_qs = karigar.assignments.filter(
        status__in=[
            KarigarWorkAssignment.STATUS_RECEIVED,
            KarigarWorkAssignment.STATUS_CANCELLED,
        ]
    ).select_related('customer').order_by('-received_date', '-id')

    paginator = Paginator(history_qs, 10)
    history_page = paginator.get_page(request.GET.get('history_page'))

    # Recent settlements
    settlements = karigar.settlements.order_by('-payment_date', '-id')[:8]

    # Material statistics across all completed jobs
    received_jobs = karigar.assignments.filter(status=KarigarWorkAssignment.STATUS_RECEIVED)
    metal_stats = received_jobs.aggregate(
        total_issued=Sum('net_weight_issued'),
        total_received=Sum('net_weight_received'),
        total_scrap=Sum('scrap_weight_returned'),
        total_actual_loss=Sum('actual_wastage_weight'),
        total_allowed_loss=Sum('wastage_weight_allowed'),
        total_diff=Sum('weight_difference'),
    )

    context = {
        'page_title': f"Karigar: {karigar.name} ({karigar.karigar_code})",
        'karigar': karigar,
        'active_works': active_works,
        'history_page': history_page,
        'settlements': settlements,
        'metal_stats': metal_stats,
    }
    return render(request, 'karigar/karigar_detail.html', context)


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'edit')
def karigar_edit(request, pk):
    """Edit Karigar details."""
    karigar = get_object_or_404(Karigar, pk=pk)
    if request.method == 'POST':
        form = KarigarForm(request.POST, instance=karigar)
        if form.is_valid():
            karigar = form.save()
            messages.success(request, f"Karigar '{karigar.name}' updated successfully.")
            return redirect('karigar:karigar_detail', pk=karigar.pk)
    else:
        form = KarigarForm(instance=karigar)

    return render(request, 'karigar/karigar_form.html', {
        'page_title': f"Edit Karigar: {karigar.name}",
        'form': form,
        'karigar': karigar,
        'is_edit': True,
    })


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'edit')
def karigar_toggle_status(request, pk):
    """Activate or deactivate a Karigar profile."""
    karigar = get_object_or_404(Karigar, pk=pk)
    if request.method == 'POST':
        if karigar.status == Karigar.STATUS_ACTIVE:
            karigar.status = Karigar.STATUS_INACTIVE
            msg = f"Karigar '{karigar.name}' has been deactivated."
        else:
            karigar.status = Karigar.STATUS_ACTIVE
            msg = f"Karigar '{karigar.name}' is now active."
        karigar.save(update_fields=['status'])
        messages.info(request, msg)
    return redirect('karigar:karigar_detail', pk=karigar.pk)


# ==============================================================================
# 3. WORK ASSIGNMENT VIEWS
# ==============================================================================

@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'view')
def assignment_list(request):
    """List work assignments with multi-factor search and filtering."""
    queryset = KarigarWorkAssignment.objects.select_related(
        'karigar', 'customer', 'custom_order', 'inventory_item'
    ).order_by('-issue_date', '-id')

    q = request.GET.get('q', '').strip()
    if q:
        queryset = queryset.filter(
            Q(assignment_number__icontains=q)
            | Q(karigar__name__icontains=q)
            | Q(customer__name__icontains=q)
            | Q(customer__mobile__icontains=q)
            | Q(description__icontains=q)
        )

    status = request.GET.get('status', '').strip()
    if status:
        queryset = queryset.filter(status=status)

    karigar_id = request.GET.get('karigar', '').strip()
    if karigar_id:
        queryset = queryset.filter(karigar_id=karigar_id)

    work_type = request.GET.get('work_type', '').strip()
    if work_type:
        queryset = queryset.filter(work_type=work_type)

    priority = request.GET.get('priority', '').strip()
    if priority:
        queryset = queryset.filter(priority=priority)

    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_title': 'Work Assignments',
        'assignments': page_obj,
        'page_obj': page_obj,
        'q': q,
        'selected_status': status,
        'selected_karigar': karigar_id,
        'selected_work_type': work_type,
        'selected_priority': priority,
        'status_choices': KarigarWorkAssignment.STATUS_CHOICES,
        'work_type_choices': KarigarWorkAssignment.WORK_TYPE_CHOICES,
        'priority_choices': KarigarWorkAssignment.PRIORITY_CHOICES,
        'karigars': Karigar.objects.order_by('name'),
        'total_count': queryset.count(),
    }
    return render(request, 'karigar/assignment_list.html', context)


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'view')
def pending_assignments(request):
    """Dedicated dashboard view for pending and overdue jobs."""
    today = timezone.localdate()

    overdue_qs = KarigarWorkAssignment.objects.filter(
        expected_completion_date__lt=today,
        status__in=[KarigarWorkAssignment.STATUS_ASSIGNED, KarigarWorkAssignment.STATUS_IN_PROGRESS]
    ).select_related('karigar', 'customer').order_by('expected_completion_date')

    pending_qs = KarigarWorkAssignment.objects.filter(
        status__in=[KarigarWorkAssignment.STATUS_ASSIGNED, KarigarWorkAssignment.STATUS_IN_PROGRESS, KarigarWorkAssignment.STATUS_COMPLETED]
    ).select_related('karigar', 'customer').order_by('priority', 'expected_completion_date')

    context = {
        'page_title': 'Pending & Overdue Work Assignments',
        'overdue_list': overdue_qs,
        'pending_list': pending_qs,
        'today': today,
    }
    return render(request, 'karigar/pending_assignments.html', context)


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'add')
def assignment_create(request):
    """Issue a new work order to a Karigar with inventory and stock integration."""
    initial_data = {}

    karigar_id = request.GET.get('karigar')
    if karigar_id:
        initial_data['karigar'] = karigar_id

    customer_id = request.GET.get('customer')
    if customer_id:
        initial_data['customer'] = customer_id

    custom_order_id = request.GET.get('custom_order')
    if custom_order_id:
        try:
            co = CustomOrder.objects.get(pk=custom_order_id)
            initial_data['custom_order'] = co
            initial_data['customer'] = co.customer
            initial_data['metal_type'] = co.metal_type
            initial_data['purity'] = co.purity
            initial_data['gross_weight_issued'] = co.approx_gross_weight
            initial_data['description'] = f"Custom Order #{co.order_number}: {co.design_description}"
        except CustomOrder.DoesNotExist:
            pass

    item_id = request.GET.get('item')
    if item_id:
        try:
            item = JewelleryItem.objects.get(pk=item_id)
            initial_data['inventory_item'] = item
            initial_data['metal_type'] = item.metal_type
            initial_data['purity'] = item.purity
            initial_data['gross_weight_issued'] = item.gross_weight
            initial_data['stone_weight_issued'] = item.stone_weight
            initial_data['description'] = f"Showroom item {item.item_code} - {item.name}"
        except JewelleryItem.DoesNotExist:
            pass

    if request.method == 'POST':
        form = KarigarWorkAssignmentForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                assignment = form.save(commit=False)
                assignment.assigned_by = request.user

                # Inventory Integration: If an existing item is selected and user opted to deduct from stock
                issue_stock = form.cleaned_data.get('issue_stock_item', False)
                item = assignment.inventory_item

                if issue_stock and item:
                    if item.quantity <= 0 or item.status != 'Available':
                        form.add_error('inventory_item', f"Item '{item.item_code}' is not currently available in stock.")
                        return render(request, 'karigar/assignment_form.html', {
                            'page_title': 'Issue Work Assignment',
                            'form': form,
                            'is_edit': False,
                        })

                    # Apply audited stock reduction
                    movement = apply_stock_change(
                        item=item,
                        change=-1,
                        movement_type=StockMovement.REDUCTION,
                        reason='Manual Adjustment',
                        notes=f"Issued to Karigar ({assignment.karigar.name}) for {assignment.work_type} - {assignment.gross_weight_issued}g",
                        user=request.user,
                    )
                    assignment.stock_movement_issued = movement

                assignment.save()

                # If tied to a custom order that was 'Confirmed', update it to 'In Making'
                if assignment.custom_order and assignment.custom_order.status == CustomOrder.STATUS_CONFIRMED:
                    assignment.custom_order.status = CustomOrder.STATUS_IN_MAKING
                    assignment.custom_order.save(update_fields=['status'])

            messages.success(request, f"Work assignment '{assignment.assignment_number}' issued successfully to {assignment.karigar.name}.")
            return redirect('karigar:assignment_detail', pk=assignment.pk)
    else:
        form = KarigarWorkAssignmentForm(initial=initial_data)

    return render(request, 'karigar/assignment_form.html', {
        'page_title': 'Issue Work Assignment',
        'form': form,
        'is_edit': False,
    })


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'view')
def assignment_detail(request, pk):
    """Detailed job card with accountability breakdown, labour charges, and audit log."""
    assignment = get_object_or_404(
        KarigarWorkAssignment.objects.select_related(
            'karigar', 'customer', 'custom_order', 'inventory_item',
            'assigned_by', 'received_by', 'stock_movement_issued', 'stock_movement_received'
        ),
        pk=pk
    )

    settlements = assignment.settlements.all().order_by('-payment_date')

    context = {
        'page_title': f"Work Assignment: {assignment.assignment_number}",
        'assignment': assignment,
        'settlements': settlements,
    }
    return render(request, 'karigar/assignment_detail.html', context)


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'edit')
def assignment_edit(request, pk):
    """Edit work assignment instructions / parameters before completion."""
    assignment = get_object_or_404(KarigarWorkAssignment, pk=pk)

    if assignment.status in [KarigarWorkAssignment.STATUS_RECEIVED, KarigarWorkAssignment.STATUS_CANCELLED]:
        messages.error(request, f"Cannot edit an assignment with status '{assignment.status}'.")
        return redirect('karigar:assignment_detail', pk=assignment.pk)

    if request.method == 'POST':
        form = KarigarWorkAssignmentForm(request.POST, request.FILES, instance=assignment)
        if form.is_valid():
            assignment = form.save()
            messages.success(request, f"Work assignment '{assignment.assignment_number}' updated successfully.")
            return redirect('karigar:assignment_detail', pk=assignment.pk)
    else:
        form = KarigarWorkAssignmentForm(instance=assignment)

    return render(request, 'karigar/assignment_form.html', {
        'page_title': f"Edit Work Assignment: {assignment.assignment_number}",
        'form': form,
        'assignment': assignment,
        'is_edit': True,
    })


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'edit')
def assignment_status_update(request, pk):
    """Move assignment status (e.g. In Progress, Completed, Cancelled)."""
    assignment = get_object_or_404(KarigarWorkAssignment, pk=pk)

    if request.method == 'POST':
        target_status = request.POST.get('status')
        if target_status not in dict(KarigarWorkAssignment.STATUS_CHOICES):
            messages.error(request, "Invalid status specified.")
            return redirect('karigar:assignment_detail', pk=assignment.pk)

        if assignment.status == KarigarWorkAssignment.STATUS_RECEIVED:
            messages.error(request, "Received assignments cannot change status directly.")
            return redirect('karigar:assignment_detail', pk=assignment.pk)

        if assignment.status == KarigarWorkAssignment.STATUS_CANCELLED:
            messages.error(request, "Cancelled assignments cannot be reopened.")
            return redirect('karigar:assignment_detail', pk=assignment.pk)

        if target_status == KarigarWorkAssignment.STATUS_CANCELLED:
            # Revert stock movement if stock was deducted
            with transaction.atomic():
                if assignment.stock_movement_issued and assignment.inventory_item:
                    apply_stock_change(
                        item=assignment.inventory_item,
                        change=1,
                        movement_type=StockMovement.ADDITION,
                        reason='Manual Adjustment',
                        notes=f"Returned to stock: cancelled assignment {assignment.assignment_number}",
                        user=request.user,
                    )
                assignment.status = KarigarWorkAssignment.STATUS_CANCELLED
                assignment.save(update_fields=['status'])
            messages.warning(request, f"Assignment '{assignment.assignment_number}' has been cancelled.")
            return redirect('karigar:assignment_detail', pk=assignment.pk)

        assignment.status = target_status
        if target_status == KarigarWorkAssignment.STATUS_COMPLETED and not assignment.actual_completion_date:
            assignment.actual_completion_date = timezone.localdate()
        assignment.save()
        messages.success(request, f"Status updated to '{target_status}'.")

    return redirect('karigar:assignment_detail', pk=assignment.pk)


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'edit')
def assignment_receive(request, pk):
    """Receive completed work from Karigar, perform weight accountability & finalize charges."""
    assignment = get_object_or_404(KarigarWorkAssignment, pk=pk)

    if assignment.status == KarigarWorkAssignment.STATUS_RECEIVED:
        messages.info(request, "This assignment has already been received.")
        return redirect('karigar:assignment_detail', pk=assignment.pk)

    if assignment.status == KarigarWorkAssignment.STATUS_CANCELLED:
        messages.error(request, "Cannot receive a cancelled assignment.")
        return redirect('karigar:assignment_detail', pk=assignment.pk)

    if request.method == 'POST':
        form = KarigarReceiveWorkForm(request.POST, instance=assignment)
        if form.is_valid():
            with transaction.atomic():
                assignment = form.save(commit=False)
                assignment.status = KarigarWorkAssignment.STATUS_RECEIVED
                assignment.received_by = request.user
                assignment.received_date = timezone.localdate()
                if not assignment.actual_completion_date:
                    assignment.actual_completion_date = timezone.localdate()

                # Calculate accountability
                assignment.calculate_weights()
                assignment.calculate_charges()

                # Inventory Integration: If an item was issued and user wants to return it to showroom stock
                return_stock = form.cleaned_data.get('return_to_inventory', False)
                item = assignment.inventory_item

                if return_stock and item and assignment.stock_movement_issued:
                    movement = apply_stock_change(
                        item=item,
                        change=1,
                        movement_type=StockMovement.ADDITION,
                        reason='Manual Adjustment',
                        notes=f"Received from Karigar ({assignment.karigar.name}) - Finished piece {assignment.assignment_number}",
                        user=request.user,
                    )
                    assignment.stock_movement_received = movement

                assignment.save()

                # If linked to a custom order, notify or progress custom order if Ready
                if assignment.custom_order and assignment.custom_order.status == CustomOrder.STATUS_IN_MAKING:
                    assignment.custom_order.status = CustomOrder.STATUS_READY
                    if not assignment.custom_order.actual_delivery_date:
                        assignment.custom_order.actual_delivery_date = timezone.localdate()
                    assignment.custom_order.save(update_fields=['status', 'actual_delivery_date'])

            messages.success(
                request,
                f"Work assignment '{assignment.assignment_number}' successfully received and accountability verified! "
                f"Total charge: ₹{assignment.total_charge:,.2f}"
            )
            return redirect('karigar:assignment_detail', pk=assignment.pk)
    else:
        # Pre-fill received weight with issued weight as baseline convenience
        if assignment.gross_weight_received == 0:
            assignment.gross_weight_received = assignment.gross_weight_issued
        if assignment.stone_weight_received == 0:
            assignment.stone_weight_received = assignment.stone_weight_issued
        form = KarigarReceiveWorkForm(instance=assignment)

    return render(request, 'karigar/assignment_receive_form.html', {
        'page_title': f"Receive Work: {assignment.assignment_number}",
        'assignment': assignment,
        'form': form,
    })


# ==============================================================================
# 4. SETTLEMENT / PAYMENT VIEWS
# ==============================================================================

@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'view')
def settlement_list(request):
    """List labour payment settlements with filter and pagination."""
    queryset = KarigarSettlement.objects.select_related('karigar', 'processed_by').order_by('-payment_date', '-id')

    q = request.GET.get('q', '').strip()
    if q:
        queryset = queryset.filter(
            Q(settlement_number__icontains=q)
            | Q(karigar__name__icontains=q)
            | Q(payment_reference__icontains=q)
        )

    karigar_id = request.GET.get('karigar', '').strip()
    if karigar_id:
        queryset = queryset.filter(karigar_id=karigar_id)

    status = request.GET.get('status', '').strip()
    if status:
        queryset = queryset.filter(status=status)

    method = request.GET.get('method', '').strip()
    if method:
        queryset = queryset.filter(payment_method=method)

    total_amount = queryset.filter(status='Completed').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_title': 'Karigar Settlements & Payments',
        'settlements': page_obj,
        'page_obj': page_obj,
        'q': q,
        'selected_karigar': karigar_id,
        'selected_status': status,
        'selected_method': method,
        'karigars': Karigar.objects.order_by('name'),
        'payment_methods': KarigarSettlement.PAYMENT_METHODS,
        'status_choices': KarigarSettlement.STATUS_CHOICES,
        'total_amount': total_amount,
    }
    return render(request, 'karigar/settlement_list.html', context)


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'add')
def settlement_create(request):
    """Record a settlement payment to a Karigar and allocate against assignments."""
    karigar_id = request.GET.get('karigar')
    assignment_id = request.GET.get('assignment')

    if request.method == 'POST':
        form = KarigarSettlementForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                settlement = form.save(commit=False)
                settlement.processed_by = request.user
                settlement.save()
                form.save_m2m()

                # Allocate settlement to selected assignments (FIFO - oldest jobs first)
                selected_assignments = settlement.assignments.order_by('issue_date', 'id')
                if selected_assignments.exists():
                    # Evenly or sequentially allocate
                    remaining = settlement.amount
                    for asg in selected_assignments:
                        due = asg.due_charge_amount
                        alloc = min(due, remaining)
                        asg.paid_amount += alloc
                        remaining -= alloc
                        asg.calculate_charges()
                        asg.save(update_fields=['paid_amount', 'payment_status'])
                        if remaining <= 0:
                            break

            messages.success(
                request,
                f"Settlement voucher '{settlement.settlement_number}' of ₹{settlement.amount:,.2f} recorded for {settlement.karigar.name}."
            )
            return redirect('karigar:settlement_detail', pk=settlement.pk)
    else:
        form = KarigarSettlementForm(karigar_id=karigar_id)
        if assignment_id:
            try:
                asg = KarigarWorkAssignment.objects.get(pk=assignment_id)
                form.fields['assignments'].initial = [asg]
                form.fields['amount'].initial = asg.due_charge_amount
            except KarigarWorkAssignment.DoesNotExist:
                pass

    return render(request, 'karigar/settlement_form.html', {
        'page_title': 'Record Karigar Payment Settlement',
        'form': form,
    })


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'view')
def settlement_detail(request, pk):
    """Settlement voucher display and printable payment receipt."""
    settlement = get_object_or_404(
        KarigarSettlement.objects.select_related('karigar', 'processed_by', 'cancelled_by'),
        pk=pk
    )
    assignments = settlement.assignments.all()

    context = {
        'page_title': f"Settlement Voucher: {settlement.settlement_number}",
        'settlement': settlement,
        'assignments': assignments,
    }
    return render(request, 'karigar/settlement_detail.html', context)


@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'delete')
def settlement_cancel(request, pk):
    """Safely cancel a settlement voucher and roll back assignment paid balances."""
    settlement = get_object_or_404(KarigarSettlement, pk=pk)

    if settlement.status == KarigarSettlement.STATUS_CANCELLED:
        messages.warning(request, "This settlement is already cancelled.")
        return redirect('karigar:settlement_detail', pk=settlement.pk)

    if request.method == 'POST':
        form = KarigarCancelSettlementForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data['cancellation_reason']
            settlement.cancel(user=request.user, reason=reason)
            messages.warning(request, f"Settlement voucher '{settlement.settlement_number}' has been cancelled and balances reverted.")
            return redirect('karigar:settlement_detail', pk=settlement.pk)
    else:
        form = KarigarCancelSettlementForm()

    return render(request, 'karigar/settlement_cancel_form.html', {
        'page_title': f"Cancel Settlement: {settlement.settlement_number}",
        'settlement': settlement,
        'form': form,
    })


# ==============================================================================
# 5. KARIGAR REPORTS
# ==============================================================================

@login_required
@require_permission(EmployeePermission.MODULE_KARIGAR, 'view')
def reports(request):
    """
    Comprehensive Karigar Reporting Hub:
      - Work Assignment Report
      - Material Accountability Report
      - Charges & Payments Report
      - Overdue Report
    Supports CSV exports when ?export=csv is supplied.
    """
    tab = request.GET.get('tab', 'work')
    export = request.GET.get('export', '')

    today = timezone.localdate()
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    karigar_id = request.GET.get('karigar', '')

    # Base assignments
    assignments = KarigarWorkAssignment.objects.select_related('karigar', 'customer').order_by('-issue_date')

    if karigar_id:
        assignments = assignments.filter(karigar_id=karigar_id)

    if start_date:
        assignments = assignments.filter(issue_date__gte=start_date)

    if end_date:
        assignments = assignments.filter(issue_date__lte=end_date)

    # 1. Work Assignment Report
    if tab == 'work':
        if export == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="karigar_work_report_{today}.csv"'
            writer = csv.writer(response)
            writer.writerow([
                'Assignment #', 'Karigar', 'Work Type', 'Issue Date',
                'Expected Date', 'Actual Date', 'Status', 'Total Charge (INR)'
            ])
            for asg in assignments:
                writer.writerow([
                    asg.assignment_number,
                    asg.karigar.name,
                    asg.work_type,
                    asg.issue_date,
                    asg.expected_completion_date or '',
                    asg.actual_completion_date or '',
                    asg.status,
                    f"{asg.total_charge:.2f}",
                ])
            return response

    # 2. Material Accountability Report
    elif tab == 'material':
        material_qs = assignments.exclude(status=KarigarWorkAssignment.STATUS_CANCELLED)
        if export == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="karigar_material_accountability_{today}.csv"'
            writer = csv.writer(response)
            writer.writerow([
                'Assignment #', 'Karigar', 'Metal', 'Net Issued (g)',
                'Net Received (g)', 'Scrap Returned (g)', 'Actual Loss (g)',
                'Allowed Loss (g)', 'Difference (g)', 'Status'
            ])
            for asg in material_qs:
                writer.writerow([
                    asg.assignment_number,
                    asg.karigar.name,
                    f"{asg.metal_type} {asg.purity}",
                    f"{asg.net_weight_issued:.3f}",
                    f"{asg.net_weight_received:.3f}",
                    f"{asg.scrap_weight_returned:.3f}",
                    f"{asg.actual_wastage_weight:.3f}",
                    f"{asg.wastage_weight_allowed:.3f}",
                    f"{asg.weight_difference:.3f}",
                    asg.status,
                ])
            return response

    # 3. Charges & Payments Report
    elif tab == 'charges':
        settlements_qs = KarigarSettlement.objects.filter(status='Completed')
        if karigar_id:
            settlements_qs = settlements_qs.filter(karigar_id=karigar_id)
        if start_date:
            settlements_qs = settlements_qs.filter(payment_date__gte=start_date)
        if end_date:
            settlements_qs = settlements_qs.filter(payment_date__lte=end_date)

        if export == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="karigar_charges_report_{today}.csv"'
            writer = csv.writer(response)
            writer.writerow([
                'Voucher #', 'Karigar', 'Payment Date', 'Payment Method', 'Reference', 'Amount (INR)'
            ])
            for st in settlements_qs:
                writer.writerow([
                    st.settlement_number,
                    st.karigar.name,
                    st.payment_date,
                    st.payment_method,
                    st.payment_reference,
                    f"{st.amount:.2f}",
                ])
            return response

    # 4. Overdue Report
    elif tab == 'overdue':
        overdue_qs = assignments.filter(
            expected_completion_date__lt=today,
            status__in=[KarigarWorkAssignment.STATUS_ASSIGNED, KarigarWorkAssignment.STATUS_IN_PROGRESS]
        )
        if export == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="karigar_overdue_report_{today}.csv"'
            writer = csv.writer(response)
            writer.writerow([
                'Assignment #', 'Karigar', 'Customer', 'Due Date', 'Days Overdue', 'Priority', 'Status'
            ])
            for asg in overdue_qs:
                days = (today - asg.expected_completion_date).days if asg.expected_completion_date else 0
                writer.writerow([
                    asg.assignment_number,
                    asg.karigar.name,
                    asg.customer.name if asg.customer else 'Showroom Stock',
                    asg.expected_completion_date,
                    days,
                    asg.priority,
                    asg.status,
                ])
            return response

    # Web View
    karigars = Karigar.objects.order_by('name')

    # Aggregates for summary cards
    aggregates = {
        'total_issued_wt': assignments.aggregate(s=Sum('net_weight_issued'))['s'] or Decimal('0.000'),
        'total_received_wt': assignments.aggregate(s=Sum('net_weight_received'))['s'] or Decimal('0.000'),
        'total_scrap_wt': assignments.aggregate(s=Sum('scrap_weight_returned'))['s'] or Decimal('0.000'),
        'total_actual_loss': assignments.aggregate(s=Sum('actual_wastage_weight'))['s'] or Decimal('0.000'),
        'total_allowed_loss': assignments.aggregate(s=Sum('wastage_weight_allowed'))['s'] or Decimal('0.000'),
        'total_diff': assignments.aggregate(s=Sum('weight_difference'))['s'] or Decimal('0.000'),
        'total_charges': assignments.exclude(status='Cancelled').aggregate(s=Sum('total_charge'))['s'] or Decimal('0.00'),
        'total_paid': KarigarSettlement.objects.filter(status='Completed').aggregate(s=Sum('amount'))['s'] or Decimal('0.00'),
    }
    aggregates['pending_balance'] = max(Decimal('0.00'), aggregates['total_charges'] - aggregates['total_paid'])

    paginator = Paginator(assignments, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_title': 'Karigar & Manufacturing Reports',
        'tab': tab,
        'karigars': karigars,
        'selected_karigar': karigar_id,
        'start_date': start_date,
        'end_date': end_date,
        'assignments': page_obj,
        'page_obj': page_obj,
        'aggregates': aggregates,
        'today': today,
    }
    return render(request, 'karigar/reports.html', context)
