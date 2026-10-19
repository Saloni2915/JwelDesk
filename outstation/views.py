"""
outstation/views.py
-------------------
Views for Outstation Jewellery Sales & Stock Tracking.
Provides complete trip lifecycle management: creation, stock issuance,
B2B/B2C sales recording, return reconciliation, printable stock sheets, and CSV exports.
Enforces strict multi-tenant isolation on every endpoint.
"""

import csv
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import CompanySettings
from customers.models import Customer
from inventory.models import JewelleryItem, Category
from sales.models import Sale, Payment
from team.models import Employee

from .models import (
    OutstationTrip,
    OutstationTripItem,
    OutstationTripSale,
    OutstationTripAuditLog,
    Exhibition,
    ExhibitionExpense,
    ExhibitionItem,
    ExhibitionSale,
    ExhibitionAuditLog,
)
from .forms import (
    OutstationTripForm,
    OutstationSaleForm,
    OutstationReconciliationForm,
    OutstationDiscrepancyResolveForm,
    OutstationTripCloseForm,
    ExhibitionForm,
    ExhibitionExpenseForm,
    ExhibitionSaleForm,
    ExhibitionCloseForm,
)
from . import services


# ==============================================================================
# 1. Trips Dashboard & Listing
# ==============================================================================

@login_required
def trip_list(request):
    """
    Dashboard and searchable list of all outstation jewellery trips for the tenant.
    """
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active showroom / tenant found.")
        return redirect('dashboard')

    qs = (
        OutstationTrip.objects
        .filter(tenant=tenant)
        .select_related('responsible_employee', 'created_by')
        .prefetch_related('issued_items', 'trip_sales')
        .order_by('-departure_date', '-created_at')
    )

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(trip_number__icontains=q) |
            Q(destination_city__icontains=q) |
            Q(destination_location__icontains=q) |
            Q(purpose__icontains=q) |
            Q(responsible_employee__full_name__icontains=q) |
            Q(notes__icontains=q)
        )

    # Status filter
    status = request.GET.get('status', 'all').strip()
    if status and status != 'all':
        qs = qs.filter(status=status)

    # City filter
    city = request.GET.get('city', 'all').strip()
    if city and city != 'all':
        qs = qs.filter(destination_city__iexact=city)

    # Employee filter
    emp_id = request.GET.get('employee', 'all').strip()
    if emp_id and emp_id != 'all':
        qs = qs.filter(responsible_employee_id=emp_id)

    # Date range filters
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    if date_from:
        qs = qs.filter(departure_date__gte=date_from)
    if date_to:
        qs = qs.filter(departure_date__lte=date_to)

    # Summary KPI aggregations across all trips of this showroom
    all_trips = OutstationTrip.objects.filter(tenant=tenant)
    total_trips_count = all_trips.count()
    active_trips_count = all_trips.filter(
        status__in=[
            OutstationTrip.STATUS_ISSUED,
            OutstationTrip.STATUS_IN_PROGRESS,
            OutstationTrip.STATUS_RECONCILING,
        ]
    ).count()

    total_items_in_transit = OutstationTripItem.objects.filter(
        trip__tenant=tenant,
        status=OutstationTripItem.STATUS_ISSUED
    ).count()

    total_outstation_sales = OutstationTripSale.objects.filter(
        trip__tenant=tenant
    ).aggregate(total=Sum('sale__sale_price'))['total'] or Decimal('0.00')

    sale_ids = OutstationTripSale.objects.filter(trip__tenant=tenant).values_list('sale_id', flat=True)
    total_payments_received = (
        Payment.objects.filter(sale_id__in=sale_ids).aggregate(total=Sum('amount'))['total']
        if sale_ids else Decimal('0.00')
    ) or Decimal('0.00')
    total_outstanding_amount = max(Decimal('0.00'), total_outstation_sales - total_payments_received)

    total_unresolved_discrepancies = OutstationTripItem.objects.filter(
        trip__tenant=tenant,
        status__in=[OutstationTripItem.STATUS_DAMAGED, OutstationTripItem.STATUS_MISSING],
        discrepancy_resolved=False
    ).count()

    # Dropdown options
    cities = (
        all_trips.exclude(destination_city='')
        .values_list('destination_city', flat=True)
        .distinct()
        .order_by('destination_city')
    )
    employees = Employee.objects.filter(tenant=tenant, status='Active').order_by('full_name')

    # Pagination
    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'q': q,
        'status_filter': status,
        'city_filter': city,
        'employee_filter': emp_id,
        'date_from': date_from,
        'date_to': date_to,
        'cities': cities,
        'employees': employees,
        'status_choices': OutstationTrip.STATUS_CHOICES,
        'total_trips_count': total_trips_count,
        'active_trips_count': active_trips_count,
        'total_items_in_transit': total_items_in_transit,
        'total_outstation_sales': total_outstation_sales,
        'total_payments_received': total_payments_received,
        'total_outstanding_amount': total_outstanding_amount,
        'total_unresolved_discrepancies': total_unresolved_discrepancies,
    }
    return render(request, 'outstation/trip_list.html', context)


# ==============================================================================
# 2. Trip Creation & Editing
# ==============================================================================

@login_required
def trip_create(request):
    """Create a new outstation jewellery trip."""
    tenant = request.tenant
    if not tenant:
        messages.error(request, "Tenant context required.")
        return redirect('dashboard')

    if request.method == 'POST':
        form = OutstationTripForm(request.POST, tenant=tenant)
        if form.is_valid():
            with transaction.atomic():
                trip = form.save(commit=False)
                trip.tenant = tenant
                trip.created_by = request.user
                trip.status = OutstationTrip.STATUS_DRAFT
                trip.save()
                form.save_m2m()

                OutstationTripAuditLog.objects.create(
                    trip=trip,
                    action=OutstationTripAuditLog.ACTION_TRIP_CREATED,
                    user=request.user,
                    details=f"Created outstation trip to {trip.destination_city} under custody of {trip.responsible_employee.full_name}."
                )

            messages.success(request, f"Trip {trip.trip_number} ({trip.destination_city}) created successfully! Next, issue jewellery stock.")
            return redirect('outstation:trip_detail', pk=trip.pk)
    else:
        form = OutstationTripForm(tenant=tenant)

    context = {
        'form': form,
        'page_title': 'Schedule New Outstation Jewellery Trip',
    }
    return render(request, 'outstation/trip_form.html', context)


@login_required
def trip_edit(request, pk):
    """Edit trip travel details (only if not closed)."""
    tenant = request.tenant
    trip = get_object_or_404(OutstationTrip, pk=pk, tenant=tenant)

    if trip.status == OutstationTrip.STATUS_CLOSED:
        messages.error(request, "Closed trips cannot be edited.")
        return redirect('outstation:trip_detail', pk=trip.pk)

    if request.method == 'POST':
        form = OutstationTripForm(request.POST, instance=trip, tenant=tenant)
        if form.is_valid():
            trip = form.save()
            messages.success(request, f"Trip {trip.trip_number} details updated successfully.")
            return redirect('outstation:trip_detail', pk=trip.pk)
    else:
        form = OutstationTripForm(instance=trip, tenant=tenant)

    context = {
        'form': form,
        'trip': trip,
        'page_title': f"Edit Trip {trip.trip_number} — {trip.destination_city}",
    }
    return render(request, 'outstation/trip_form.html', context)


# ==============================================================================
# 3. Trip Detail & Workflows (Issued Stock, Sales, Returns, Closure)
# ==============================================================================

@login_required
def trip_detail(request, pk):
    """
    Comprehensive single-screen command center for an outstation trip.
    Shows tabs for:
    1. Overview & Statistics
    2. Issued Stock items & Custody
    3. Trip Sales & Invoices
    4. Payments & Customer balances
    5. Returns & Discrepancies
    6. Complete Audit Trail
    """
    tenant = request.tenant
    trip = get_object_or_404(
        OutstationTrip.objects
        .select_related('responsible_employee', 'created_by')
        .prefetch_related('accompanying_staff'),
        pk=pk,
        tenant=tenant
    )

    issued_items = (
        trip.issued_items
        .select_related('item', 'item__category', 'issued_by', 'reconciled_by', 'discrepancy_resolved_by')
        .order_by('status', '-issued_at')
    )

    trip_sales = (
        trip.trip_sales
        .select_related('sale', 'sale__customer', 'sale__jewellery_item', 'trip_item')
        .order_by('-created_at')
    )

    # Collect all payments linked to these sales
    sale_ids = [ts.sale_id for ts in trip_sales]
    payments = (
        Payment.objects.filter(sale_id__in=sale_ids)
        .select_related('sale', 'sale__customer')
        .order_by('-payment_date', '-created_at')
    ) if sale_ids else []

    audit_logs = trip.audit_logs.select_related('user').order_by('-timestamp')[:50]

    # Quick reconciliation form
    reconciliation_form = OutstationReconciliationForm()
    discrepancy_resolve_form = OutstationDiscrepancyResolveForm()
    close_form = OutstationTripCloseForm(trip=trip)

    context = {
        'trip': trip,
        'issued_items': issued_items,
        'trip_sales': trip_sales,
        'payments': payments,
        'audit_logs': audit_logs,
        'reconciliation_form': reconciliation_form,
        'discrepancy_resolve_form': discrepancy_resolve_form,
        'close_form': close_form,
        'active_tab': request.GET.get('tab', 'overview'),
    }
    return render(request, 'outstation/trip_detail.html', context)


# ==============================================================================
# 4. Stock Issuance to Trip
# ==============================================================================

@login_required
def trip_issue_stock(request, pk):
    """
    Select and issue available showroom jewellery items by tag number to a trip.
    """
    tenant = request.tenant
    trip = get_object_or_404(OutstationTrip, pk=pk, tenant=tenant)

    if trip.status in [OutstationTrip.STATUS_CLOSED, OutstationTrip.STATUS_CANCELLED]:
        messages.error(request, f"Cannot issue stock to a {trip.get_status_display()} trip.")
        return redirect('outstation:trip_detail', pk=trip.pk)

    # Base queryset: only items available in showroom stock belonging to this tenant
    available_qs = (
        JewelleryItem.objects
        .filter(tenant=tenant, status='Available', quantity__gt=0)
        .select_related('category')
        .order_by('category__name', 'name')
    )

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        available_qs = available_qs.filter(
            Q(tag_number__icontains=q) |
            Q(item_code__icontains=q) |
            Q(design_code__icontains=q) |
            Q(name__icontains=q) |
            Q(huid__icontains=q)
        )

    # Category filter
    cat_id = request.GET.get('category', 'all').strip()
    if cat_id and cat_id != 'all':
        available_qs = available_qs.filter(category_id=cat_id)

    # Metal filter
    metal = request.GET.get('metal', 'all').strip()
    if metal and metal != 'all':
        available_qs = available_qs.filter(metal_type=metal)

    if request.method == 'POST':
        selected_ids = request.POST.getlist('selected_items')
        if not selected_ids:
            messages.error(request, "Please select at least one jewellery piece to issue.")
            return redirect('outstation:trip_issue_stock', pk=trip.pk)

        try:
            item_ids = [int(i) for i in selected_ids]
            count = services.issue_items_to_trip(trip, item_ids, user=request.user)
            messages.success(request, f"Successfully issued {count} jewellery piece(s) to Trip {trip.trip_number}!")
            return redirect(f"{reverse('outstation:trip_detail', kwargs={'pk': trip.pk})}?tab=stock")
        except Exception as e:
            messages.error(request, f"Stock Issuance Error: {e}")
            return redirect('outstation:trip_issue_stock', pk=trip.pk)

    categories = Category.objects.filter(tenant=tenant).order_by('name')

    context = {
        'trip': trip,
        'available_items': available_qs,
        'categories': categories,
        'q': q,
        'selected_category': cat_id,
        'selected_metal': metal,
        'metal_choices': JewelleryItem.METAL_CHOICES,
    }
    return render(request, 'outstation/trip_issue_stock.html', context)


# ==============================================================================
# 5. Record Sales During Trip (B2B & B2C)
# ==============================================================================

@login_required
def trip_record_sale(request, pk, item_id):
    """
    Record an on-trip sale for an issued jewellery item to a B2B or B2C buyer.
    """
    tenant = request.tenant
    trip = get_object_or_404(OutstationTrip, pk=pk, tenant=tenant)
    trip_item = get_object_or_404(OutstationTripItem, trip=trip, item_id=item_id, status=OutstationTripItem.STATUS_ISSUED)
    item = trip_item.item

    if trip.status in [OutstationTrip.STATUS_CLOSED, OutstationTrip.STATUS_CANCELLED]:
        messages.error(request, f"Cannot record sales on a {trip.get_status_display()} trip.")
        return redirect('outstation:trip_detail', pk=trip.pk)

    if request.method == 'POST':
        form = OutstationSaleForm(request.POST, trip=trip)
        if form.is_valid():
            customer = form.cleaned_data.get('customer')
            # Handle inline buyer creation if requested
            if not customer:
                name = form.cleaned_data['new_customer_name']
                mobile = form.cleaned_data['new_customer_mobile']
                city = form.cleaned_data.get('new_customer_city', '')
                customer = Customer.objects.create(
                    tenant=tenant,
                    name=name,
                    mobile=mobile,
                    address=f"City: {city}" if city else ""
                )

            buyer_type = form.cleaned_data['buyer_type']
            business_name = form.cleaned_data.get('business_name', '')
            business_gstin = form.cleaned_data.get('business_gstin', '')
            sale_price = form.cleaned_data['sale_price']
            payment_method = form.cleaned_data['payment_method']
            paid_amount = form.cleaned_data.get('paid_amount')
            payment_ref = form.cleaned_data.get('payment_ref', '')
            notes = form.cleaned_data.get('notes', '')

            try:
                sale = services.record_outstation_sale(
                    trip=trip,
                    item_id=item.id,
                    customer=customer,
                    sale_price=sale_price,
                    payment_method=payment_method,
                    buyer_type=buyer_type,
                    business_name=business_name,
                    business_gstin=business_gstin,
                    notes=notes,
                    user=request.user,
                    paid_amount=paid_amount,
                    payment_ref=payment_ref
                )
                messages.success(request, f"Sale #{sale.id} recorded successfully! Sold {item.name} for ₹{sale.sale_price:,.2f}.")
                return redirect(f"{reverse('outstation:trip_detail', kwargs={'pk': trip.pk})}?tab=sales")
            except Exception as e:
                messages.error(request, f"Sale Error: {e}")
    else:
        initial = {
            'sale_price': item.selling_price or Decimal('0.00'),
            'paid_amount': item.selling_price or Decimal('0.00'),
            'buyer_type': 'B2C',
        }
        form = OutstationSaleForm(initial=initial, trip=trip)

    context = {
        'trip': trip,
        'trip_item': trip_item,
        'item': item,
        'form': form,
    }
    return render(request, 'outstation/trip_record_sale.html', context)


# ==============================================================================
# 6. Reconcile Returns & Discrepancies
# ==============================================================================

@login_required
@require_POST
def trip_reconcile_item(request, pk, item_id):
    """
    Reconcile an issued piece: mark as Returned to showroom, Damaged, or Missing.
    """
    tenant = request.tenant
    trip = get_object_or_404(OutstationTrip, pk=pk, tenant=tenant)
    trip_item = get_object_or_404(OutstationTripItem, trip=trip, item_id=item_id)

    outcome = request.POST.get('outcome', '').strip()
    reason = request.POST.get('discrepancy_reason', '').strip()
    notes = request.POST.get('notes', '').strip()

    try:
        services.reconcile_trip_item(
            trip_item=trip_item,
            outcome=outcome,
            discrepancy_reason=reason,
            notes=notes,
            user=request.user
        )
        if outcome == 'Returned':
            messages.success(request, f"Item {trip_item.item.tag_number or trip_item.item.item_code} returned safely to showroom inventory.")
        else:
            messages.warning(request, f"Item {trip_item.item.tag_number or trip_item.item.item_code} logged as {outcome.upper()}. Manager resolution required.")
    except Exception as e:
        messages.error(request, f"Reconciliation Error: {e}")

    return redirect(f"{reverse('outstation:trip_detail', kwargs={'pk': trip.pk})}?tab=stock")


@login_required
@require_POST
def trip_resolve_discrepancy(request, pk, item_id):
    """
    Manager / Admin authorization to resolve a damaged or missing piece discrepancy.
    """
    tenant = request.tenant
    trip = get_object_or_404(OutstationTrip, pk=pk, tenant=tenant)
    trip_item = get_object_or_404(OutstationTripItem, trip=trip, item_id=item_id)

    resolution_notes = request.POST.get('resolution_notes', '').strip()
    write_off = request.POST.get('write_off_stock') in ['1', 'true', 'on', 'yes']

    try:
        services.resolve_item_discrepancy(
            trip_item=trip_item,
            resolution_notes=resolution_notes,
            write_off_stock=write_off,
            user=request.user
        )
        messages.success(request, f"Discrepancy for item {trip_item.item.tag_number} successfully authorized and resolved.")
    except Exception as e:
        messages.error(request, f"Resolution Error: {e}")

    return redirect(f"{reverse('outstation:trip_detail', kwargs={'pk': trip.pk})}?tab=reconciliation")


# ==============================================================================
# 7. Trip Closure
# ==============================================================================

@login_required
@require_POST
def trip_close(request, pk):
    """
    Conclude and close an outstation trip.
    Validates that all items are accounted for and no discrepancies remain unresolved.
    """
    tenant = request.tenant
    trip = get_object_or_404(OutstationTrip, pk=pk, tenant=tenant)

    from django.utils.dateparse import parse_date
    actual_date_raw = request.POST.get('actual_return_date', '').strip()
    actual_date = parse_date(actual_date_raw) if actual_date_raw else timezone.now().date()
    closure_notes = request.POST.get('closure_notes', '').strip()

    try:
        services.close_outstation_trip(
            trip=trip,
            user=request.user,
            actual_return_date=actual_date,
            notes=closure_notes
        )
        messages.success(request, f"Trip {trip.trip_number} has been fully reconciled and closed!")
    except Exception as e:
        messages.error(request, f"Trip Closure Error: {e}")

    return redirect('outstation:trip_detail', pk=trip.pk)


# ==============================================================================
# 8. Printable Stock Sheet & CSV Export
# ==============================================================================

@login_required
def trip_stock_sheet(request, pk):
    """
    Printable formal jewellery custody dispatch sheet.
    Includes item tags, HUIDs, gross & net weights, retail valuation, and signature blocks.
    """
    tenant = request.tenant
    trip = get_object_or_404(
        OutstationTrip.objects.select_related('responsible_employee'),
        pk=pk,
        tenant=tenant
    )
    company = CompanySettings.load(tenant=tenant)
    issued_items = (
        trip.issued_items
        .select_related('item', 'item__category')
        .order_by('item__category__name', 'item__name')
    )

    context = {
        'trip': trip,
        'company': company,
        'issued_items': issued_items,
        'now': timezone.now(),
    }
    return render(request, 'outstation/trip_stock_sheet.html', context)


@login_required
def trip_export_csv(request, pk):
    """
    Download a comprehensive CSV export of the trip manifest, sales, and reconciliation status.
    """
    tenant = request.tenant
    trip = get_object_or_404(OutstationTrip, pk=pk, tenant=tenant)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="outstation_manifest_{trip.trip_number}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Tag Number', 'Item Code', 'Item Name', 'Category', 'Metal', 'Purity',
        'Gross Weight (g)', 'Net Weight (g)', 'HUID', 'Issue Price (INR)',
        'Trip Status', 'Reconciliation Notes', 'Discrepancy Reason'
    ])

    for ti in trip.issued_items.select_related('item', 'item__category').order_by('id'):
        it = ti.item
        writer.writerow([
            it.tag_number or '',
            it.item_code or '',
            it.name or '',
            it.category.name if it.category else '',
            it.metal_type or '',
            it.purity or '',
            ti.issue_gross_weight or it.gross_weight or 0,
            ti.issue_net_weight or it.net_weight or 0,
            it.huid or '',
            ti.issue_price or 0,
            ti.get_status_display(),
            ti.reconciliation_notes or '',
            ti.discrepancy_reason or '',
        ])

    return response


# ==============================================================================
# 9. Exhibition Dashboard & Listing
# ==============================================================================

@login_required
def exhibition_list(request):
    """
    Dashboard and searchable listing of all jewellery exhibitions & trade fairs.
    """
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active showroom / tenant found.")
        return redirect('dashboard')

    qs = (
        Exhibition.objects
        .filter(tenant=tenant)
        .select_related('responsible_employee', 'created_by')
        .prefetch_related('issued_items', 'exhibition_sales', 'expenses')
        .order_by('-start_date', '-created_at')
    )

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(exhibition_number__icontains=q) |
            Q(name__icontains=q) |
            Q(venue__icontains=q) |
            Q(city__icontains=q) |
            Q(organiser__icontains=q) |
            Q(stall_number__icontains=q) |
            Q(responsible_employee__full_name__icontains=q)
        )

    status = request.GET.get('status', 'all').strip()
    if status and status != 'all':
        qs = qs.filter(status=status)

    city = request.GET.get('city', 'all').strip()
    if city and city != 'all':
        qs = qs.filter(city__iexact=city)

    emp_id = request.GET.get('employee', 'all').strip()
    if emp_id and emp_id != 'all':
        qs = qs.filter(responsible_employee_id=emp_id)

    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    if date_from:
        qs = qs.filter(start_date__gte=date_from)
    if date_to:
        qs = qs.filter(start_date__lte=date_to)

    # Aggregated KPI cards across all exhibitions
    all_exhibitions = Exhibition.objects.filter(tenant=tenant)
    total_exhibitions_count = all_exhibitions.count()
    active_exhibitions_count = all_exhibitions.filter(
        status__in=[
            Exhibition.STATUS_ISSUED,
            Exhibition.STATUS_IN_PROGRESS,
            Exhibition.STATUS_RECONCILING,
        ]
    ).count()

    total_pieces_at_booths = ExhibitionItem.objects.filter(
        exhibition__tenant=tenant,
        status=ExhibitionItem.STATUS_ISSUED
    ).count()

    total_exhibition_sales = ExhibitionSale.objects.filter(
        exhibition__tenant=tenant
    ).aggregate(total=Sum('sale__sale_price'))['total'] or Decimal('0.00')

    sale_ids = ExhibitionSale.objects.filter(exhibition__tenant=tenant).values_list('sale_id', flat=True)
    total_collections_received = (
        Payment.objects.filter(sale_id__in=sale_ids).aggregate(total=Sum('amount'))['total']
        if sale_ids else Decimal('0.00')
    ) or Decimal('0.00')

    total_exhibition_expenses = ExhibitionExpense.objects.filter(
        tenant=tenant
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    net_operating_surplus = total_exhibition_sales - total_exhibition_expenses

    cities = (
        all_exhibitions.exclude(city='')
        .values_list('city', flat=True)
        .distinct()
        .order_by('city')
    )
    employees = Employee.objects.filter(tenant=tenant, status='Active').order_by('full_name')

    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'q': q,
        'status_filter': status,
        'city_filter': city,
        'employee_filter': emp_id,
        'date_from': date_from,
        'date_to': date_to,
        'cities': cities,
        'employees': employees,
        'status_choices': Exhibition.STATUS_CHOICES,
        'total_exhibitions_count': total_exhibitions_count,
        'active_exhibitions_count': active_exhibitions_count,
        'total_pieces_at_booths': total_pieces_at_booths,
        'total_exhibition_sales': total_exhibition_sales,
        'total_collections_received': total_collections_received,
        'total_exhibition_expenses': total_exhibition_expenses,
        'net_operating_surplus': net_operating_surplus,
    }
    return render(request, 'outstation/exhibition_list.html', context)


# ==============================================================================
# 10. Exhibition Creation & Editing
# ==============================================================================

@login_required
def exhibition_create(request):
    """Register a new trade fair or jewellery exhibition."""
    tenant = request.tenant
    if not tenant:
        messages.error(request, "Tenant context required.")
        return redirect('dashboard')

    if request.method == 'POST':
        form = ExhibitionForm(request.POST, tenant=tenant)
        if form.is_valid():
            with transaction.atomic():
                exhibition = form.save(commit=False)
                exhibition.tenant = tenant
                exhibition.created_by = request.user
                exhibition.status = Exhibition.STATUS_DRAFT
                exhibition.save()
                form.save_m2m()

                ExhibitionAuditLog.objects.create(
                    exhibition=exhibition,
                    action=ExhibitionAuditLog.ACTION_EXHIBITION_CREATED,
                    user=request.user,
                    details=f"Registered exhibition {exhibition.name} ({exhibition.venue}, {exhibition.city})."
                )

            messages.success(request, f"Exhibition {exhibition.exhibition_number} registered! You can now allocate jewellery stock.")
            return redirect('outstation:exhibition_detail', pk=exhibition.pk)
    else:
        form = ExhibitionForm(tenant=tenant)

    context = {
        'form': form,
        'page_title': 'Register New Jewellery Exhibition / Trade Fair',
    }
    return render(request, 'outstation/exhibition_form.html', context)


@login_required
def exhibition_edit(request, pk):
    """Edit exhibition venue, dates, booth numbers, or timings."""
    tenant = request.tenant
    exhibition = get_object_or_404(Exhibition, pk=pk, tenant=tenant)

    if exhibition.status == Exhibition.STATUS_CLOSED:
        messages.error(request, "Closed exhibitions cannot be edited.")
        return redirect('outstation:exhibition_detail', pk=exhibition.pk)

    if request.method == 'POST':
        form = ExhibitionForm(request.POST, instance=exhibition, tenant=tenant)
        if form.is_valid():
            exhibition = form.save()
            messages.success(request, f"Exhibition {exhibition.exhibition_number} details updated.")
            return redirect('outstation:exhibition_detail', pk=exhibition.pk)
    else:
        form = ExhibitionForm(instance=exhibition, tenant=tenant)

    context = {
        'form': form,
        'exhibition': exhibition,
        'page_title': f"Edit Exhibition {exhibition.exhibition_number} — {exhibition.name}",
    }
    return render(request, 'outstation/exhibition_form.html', context)


# ==============================================================================
# 11. Exhibition Detail Command Center
# ==============================================================================

@login_required
def exhibition_detail(request, pk):
    """
    Comprehensive command center for an exhibition.
    Tabs:
    - Overview
    - Issued Stock
    - Sales & Invoices
    - Expenses (Stall Rent, Flights, Hotel, etc.)
    - Payments
    - Reconciliation
    - Day-wise Breakdown Report
    - Audit Trail
    """
    from datetime import timedelta
    tenant = request.tenant
    exhibition = get_object_or_404(
        Exhibition.objects
        .select_related('responsible_employee', 'created_by')
        .prefetch_related('booth_staff'),
        pk=pk,
        tenant=tenant
    )

    issued_items = (
        exhibition.issued_items
        .select_related('item', 'item__category', 'issued_by', 'reconciled_by', 'discrepancy_resolved_by')
        .order_by('status', '-issued_at')
    )

    exhibition_sales = (
        exhibition.exhibition_sales
        .select_related('sale', 'sale__customer', 'sale__jewellery_item', 'exhibition_item')
        .order_by('-sale_datetime')
    )

    expenses = exhibition.expenses.select_related('recorded_by').order_by('-expense_date', '-id')

    sale_ids = [es.sale_id for es in exhibition_sales]
    payments = (
        Payment.objects.filter(sale_id__in=sale_ids)
        .select_related('sale', 'sale__customer')
        .order_by('-payment_date', '-created_at')
    ) if sale_ids else []

    audit_logs = exhibition.audit_logs.select_related('user').order_by('-timestamp')[:50]

    # Day-wise report generation across exhibition start_date to end_date
    daywise_data = []
    if exhibition.start_date and exhibition.end_date:
        cur = exhibition.start_date
        end = exhibition.end_date
        day_num = 1
        delta = timedelta(days=1)
        while cur <= end:
            day_sales = [s for s in exhibition_sales if s.sale_datetime.date() == cur]
            day_rev = sum((s.sale.sale_price for s in day_sales), Decimal('0.00'))
            day_pcs = len(day_sales)
            day_wt = sum((s.exhibition_item.issue_gross_weight or Decimal('0.000') for s in day_sales if s.exhibition_item), Decimal('0.000'))

            day_exps = [e for e in expenses if e.expense_date == cur]
            day_exp_tot = sum((e.amount for e in day_exps), Decimal('0.00'))

            daywise_data.append({
                'day_num': day_num,
                'date': cur,
                'sales_count': day_pcs,
                'gross_weight': day_wt,
                'revenue': day_rev,
                'expenses': day_exp_tot,
                'surplus': day_rev - day_exp_tot,
            })
            cur += delta
            day_num += 1

    expense_form = ExhibitionExpenseForm()
    close_form = ExhibitionCloseForm(exhibition=exhibition)

    context = {
        'exhibition': exhibition,
        'issued_items': issued_items,
        'exhibition_sales': exhibition_sales,
        'expenses': expenses,
        'payments': payments,
        'audit_logs': audit_logs,
        'daywise_data': daywise_data,
        'expense_form': expense_form,
        'close_form': close_form,
        'active_tab': request.GET.get('tab', 'overview'),
    }
    return render(request, 'outstation/exhibition_detail.html', context)


# ==============================================================================
# 12. Exhibition Stock Issuance
# ==============================================================================

@login_required
def exhibition_issue_stock(request, pk):
    """
    Select and issue available showroom jewellery to an exhibition booth.
    """
    tenant = request.tenant
    exhibition = get_object_or_404(Exhibition, pk=pk, tenant=tenant)

    if exhibition.status in [Exhibition.STATUS_CLOSED, Exhibition.STATUS_CANCELLED]:
        messages.error(request, f"Cannot issue stock to a {exhibition.get_status_display()} exhibition.")
        return redirect('outstation:exhibition_detail', pk=exhibition.pk)

    available_qs = (
        JewelleryItem.objects
        .filter(tenant=tenant, status='Available', quantity__gt=0)
        .select_related('category')
        .order_by('category__name', 'name')
    )

    q = request.GET.get('q', '').strip()
    if q:
        available_qs = available_qs.filter(
            Q(tag_number__icontains=q) |
            Q(item_code__icontains=q) |
            Q(design_code__icontains=q) |
            Q(name__icontains=q) |
            Q(huid__icontains=q)
        )

    cat_id = request.GET.get('category', 'all').strip()
    if cat_id and cat_id != 'all':
        available_qs = available_qs.filter(category_id=cat_id)

    metal = request.GET.get('metal', 'all').strip()
    if metal and metal != 'all':
        available_qs = available_qs.filter(metal_type=metal)

    if request.method == 'POST':
        selected_ids = request.POST.getlist('selected_items')
        if not selected_ids:
            messages.error(request, "Please select at least one jewellery piece to issue.")
            return redirect('outstation:exhibition_issue_stock', pk=exhibition.pk)

        try:
            item_ids = [int(i) for i in selected_ids]
            count = services.issue_items_to_exhibition(exhibition, item_ids, user=request.user)
            messages.success(request, f"Successfully issued {count} piece(s) to {exhibition.name}!")
            return redirect(f"{reverse('outstation:exhibition_detail', kwargs={'pk': exhibition.pk})}?tab=stock")
        except Exception as e:
            messages.error(request, f"Exhibition Stock Error: {e}")
            return redirect('outstation:exhibition_issue_stock', pk=exhibition.pk)

    categories = Category.objects.filter(tenant=tenant).order_by('name')

    context = {
        'exhibition': exhibition,
        'available_items': available_qs,
        'categories': categories,
        'q': q,
        'selected_category': cat_id,
        'selected_metal': metal,
        'metal_choices': JewelleryItem.METAL_CHOICES,
    }
    return render(request, 'outstation/exhibition_issue_stock.html', context)


# ==============================================================================
# 13. Exhibition Sales Recording (B2B & B2C)
# ==============================================================================

@login_required
def exhibition_record_sale(request, pk, item_id):
    """
    Record an on-site sale for an issued piece at the exhibition booth.
    """
    tenant = request.tenant
    exhibition = get_object_or_404(Exhibition, pk=pk, tenant=tenant)
    exh_item = get_object_or_404(ExhibitionItem, exhibition=exhibition, item_id=item_id, status=ExhibitionItem.STATUS_ISSUED)
    item = exh_item.item

    if exhibition.status in [Exhibition.STATUS_CLOSED, Exhibition.STATUS_CANCELLED]:
        messages.error(request, f"Cannot record sales on a {exhibition.get_status_display()} exhibition.")
        return redirect('outstation:exhibition_detail', pk=exhibition.pk)

    if request.method == 'POST':
        form = ExhibitionSaleForm(request.POST, exhibition=exhibition)
        if form.is_valid():
            customer = form.cleaned_data.get('customer')
            if not customer:
                name = form.cleaned_data['new_customer_name']
                mobile = form.cleaned_data['new_customer_mobile']
                city = form.cleaned_data.get('new_customer_city', '')
                customer = Customer.objects.create(
                    tenant=tenant,
                    name=name,
                    mobile=mobile,
                    address=f"City: {city}" if city else ""
                )

            buyer_type = form.cleaned_data['buyer_type']
            business_name = form.cleaned_data.get('business_name', '')
            business_gstin = form.cleaned_data.get('business_gstin', '')
            sale_price = form.cleaned_data['sale_price']
            payment_method = form.cleaned_data['payment_method']
            paid_amount = form.cleaned_data.get('paid_amount')
            payment_ref = form.cleaned_data.get('payment_ref', '')
            notes = form.cleaned_data.get('notes', '')

            try:
                sale = services.record_exhibition_sale(
                    exhibition=exhibition,
                    item_id=item.id,
                    customer=customer,
                    sale_price=sale_price,
                    payment_method=payment_method,
                    buyer_type=buyer_type,
                    business_name=business_name,
                    business_gstin=business_gstin,
                    notes=notes,
                    user=request.user,
                    paid_amount=paid_amount,
                    payment_ref=payment_ref
                )
                messages.success(request, f"Sale #{sale.id} recorded successfully! Sold {item.name} for ₹{sale.sale_price:,.2f}.")
                return redirect(f"{reverse('outstation:exhibition_detail', kwargs={'pk': exhibition.pk})}?tab=sales")
            except Exception as e:
                messages.error(request, f"Exhibition Sale Error: {e}")
    else:
        initial = {
            'sale_price': item.selling_price or Decimal('0.00'),
            'paid_amount': item.selling_price or Decimal('0.00'),
            'buyer_type': 'B2C',
        }
        form = ExhibitionSaleForm(initial=initial, exhibition=exhibition)

    context = {
        'exhibition': exhibition,
        'exh_item': exh_item,
        'item': item,
        'form': form,
    }
    return render(request, 'outstation/exhibition_record_sale.html', context)


# ==============================================================================
# 14. Exhibition Expenses Management
# ==============================================================================

@login_required
@require_POST
def exhibition_record_expense(request, pk):
    """Log an expense entry for stall rent, travel, hotel, marketing, or logistics."""
    tenant = request.tenant
    exhibition = get_object_or_404(Exhibition, pk=pk, tenant=tenant)

    form = ExhibitionExpenseForm(request.POST)
    if form.is_valid():
        try:
            exp = services.record_exhibition_expense(
                exhibition=exhibition,
                category=form.cleaned_data['category'],
                amount=form.cleaned_data['amount'],
                payee=form.cleaned_data['payee'],
                expense_date=form.cleaned_data['expense_date'],
                payment_method=form.cleaned_data['payment_method'],
                reference_number=form.cleaned_data.get('reference_number', ''),
                notes=form.cleaned_data.get('notes', ''),
                user=request.user
            )
            messages.success(request, f"Expense of ₹{exp.amount:,.2f} ({exp.category}) logged successfully.")
        except Exception as e:
            messages.error(request, f"Expense Error: {e}")
    else:
        messages.error(request, "Invalid expense data provided.")

    return redirect(f"{reverse('outstation:exhibition_detail', kwargs={'pk': exhibition.pk})}?tab=expenses")


@login_required
@require_POST
def exhibition_delete_expense(request, pk, expense_id):
    """Delete an expense entry if exhibition is not closed."""
    tenant = request.tenant
    exhibition = get_object_or_404(Exhibition, pk=pk, tenant=tenant)
    if exhibition.status == Exhibition.STATUS_CLOSED:
        messages.error(request, "Cannot modify expenses of a closed exhibition.")
        return redirect('outstation:exhibition_detail', pk=exhibition.pk)

    exp = get_object_or_404(ExhibitionExpense, pk=expense_id, exhibition=exhibition, tenant=tenant)
    amount = exp.amount
    cat = exp.category
    exp.delete()
    messages.success(request, f"Expense of ₹{amount:,.2f} ({cat}) deleted.")
    return redirect(f"{reverse('outstation:exhibition_detail', kwargs={'pk': exhibition.pk})}?tab=expenses")


# ==============================================================================
# 15. Exhibition Reconciliation & Closure
# ==============================================================================

@login_required
@require_POST
def exhibition_reconcile_item(request, pk, item_id):
    """Reconcile piece upon return: Returned to Showroom, Damaged, or Missing."""
    tenant = request.tenant
    exhibition = get_object_or_404(Exhibition, pk=pk, tenant=tenant)
    exh_item = get_object_or_404(ExhibitionItem, exhibition=exhibition, item_id=item_id)

    outcome = request.POST.get('outcome', '').strip()
    reason = request.POST.get('discrepancy_reason', '').strip()
    notes = request.POST.get('notes', '').strip()

    try:
        services.reconcile_exhibition_item(
            exhibition_item=exh_item,
            outcome=outcome,
            discrepancy_reason=reason,
            notes=notes,
            user=request.user
        )
        if outcome == 'Returned':
            messages.success(request, f"Item {exh_item.item.tag_number or exh_item.item.item_code} safely returned to showroom stock.")
        else:
            messages.warning(request, f"Item {exh_item.item.tag_number or exh_item.item.item_code} logged as {outcome.upper()}. Manager resolution required.")
    except Exception as e:
        messages.error(request, f"Reconciliation Error: {e}")

    return redirect(f"{reverse('outstation:exhibition_detail', kwargs={'pk': exhibition.pk})}?tab=stock")


@login_required
@require_POST
def exhibition_resolve_discrepancy(request, pk, item_id):
    """Manager authorization to resolve damaged/missing item discrepancy."""
    tenant = request.tenant
    exhibition = get_object_or_404(Exhibition, pk=pk, tenant=tenant)
    exh_item = get_object_or_404(ExhibitionItem, exhibition=exhibition, item_id=item_id)

    resolution_notes = request.POST.get('resolution_notes', '').strip()
    write_off = request.POST.get('write_off_stock') in ['1', 'true', 'on', 'yes']

    try:
        services.resolve_exhibition_discrepancy(
            exhibition_item=exh_item,
            resolution_notes=resolution_notes,
            write_off_stock=write_off,
            user=request.user
        )
        messages.success(request, f"Discrepancy for item {exh_item.item.tag_number} successfully resolved.")
    except Exception as e:
        messages.error(request, f"Resolution Error: {e}")

    return redirect(f"{reverse('outstation:exhibition_detail', kwargs={'pk': exhibition.pk})}?tab=reconciliation")


@login_required
@require_POST
def exhibition_close(request, pk):
    """Conclude and close an exhibition with full validation checks."""
    tenant = request.tenant
    exhibition = get_object_or_404(Exhibition, pk=pk, tenant=tenant)

    from django.utils.dateparse import parse_date
    actual_date_raw = request.POST.get('actual_return_date', '').strip()
    actual_date = parse_date(actual_date_raw) if actual_date_raw else timezone.now().date()
    closure_notes = request.POST.get('closure_notes', '').strip()

    try:
        services.close_exhibition(
            exhibition=exhibition,
            user=request.user,
            actual_return_date=actual_date,
            notes=closure_notes
        )
        messages.success(request, f"Exhibition {exhibition.exhibition_number} ({exhibition.name}) has been successfully closed and reconciled!")
    except Exception as e:
        messages.error(request, f"Exhibition Closure Error: {e}")

    return redirect('outstation:exhibition_detail', pk=exhibition.pk)


# ==============================================================================
# 16. Exhibition Printable Stock Sheet & CSV Export
# ==============================================================================

@login_required
def exhibition_stock_sheet(request, pk):
    """Printable formal exhibition booth jewellery dispatch sheet."""
    tenant = request.tenant
    exhibition = get_object_or_404(
        Exhibition.objects.select_related('responsible_employee'),
        pk=pk,
        tenant=tenant
    )
    company = CompanySettings.load(tenant=tenant)
    issued_items = (
        exhibition.issued_items
        .select_related('item', 'item__category')
        .order_by('item__category__name', 'item__name')
    )

    context = {
        'exhibition': exhibition,
        'company': company,
        'issued_items': issued_items,
        'now': timezone.now(),
    }
    return render(request, 'outstation/exhibition_stock_sheet.html', context)


@login_required
def exhibition_export_csv(request, pk):
    """CSV export of exhibition items, weights, and sales status."""
    tenant = request.tenant
    exhibition = get_object_or_404(Exhibition, pk=pk, tenant=tenant)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="exhibition_manifest_{exhibition.exhibition_number}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Tag Number', 'Item Code', 'Item Name', 'Category', 'Metal', 'Purity',
        'Gross Weight (g)', 'Net Weight (g)', 'HUID', 'Issue Price (INR)',
        'Status', 'Reconciliation Notes', 'Discrepancy Reason'
    ])

    for ei in exhibition.issued_items.select_related('item', 'item__category').order_by('id'):
        it = ei.item
        writer.writerow([
            it.tag_number or '',
            it.item_code or '',
            it.name or '',
            it.category.name if it.category else '',
            it.metal_type or '',
            it.purity or '',
            ei.issue_gross_weight or it.gross_weight or 0,
            ei.issue_net_weight or it.net_weight or 0,
            it.huid or '',
            ei.issue_price or 0,
            ei.get_status_display(),
            ei.reconciliation_notes or '',
            ei.discrepancy_reason or '',
        ])

    return response

