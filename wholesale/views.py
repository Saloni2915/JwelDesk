import csv
from decimal import Decimal
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import CompanySettings
from inventory.models import Category, JewelleryItem
from inventory.stock import get_low_stock_threshold
from team.permissions import has_module_perm, is_admin_user

from .forms import (
    RetailerPartyForm,
    RetailerPaymentForm,
    WholesaleOrderForm,
    WholesalePricingRuleForm,
    WholesaleReturnForm,
)
from .invoice_service import (
    create_invoice_for_order,
    issue_wholesale_credit_note,
    record_retailer_payment,
)
from .models import (
    RetailerLedgerEntry,
    RetailerParty,
    RetailerPayment,
    RetailerPaymentAllocation,
    WholesaleDispatch,
    WholesaleDispatchItem,
    WholesaleInvoice,
    WholesaleInvoiceItem,
    WholesaleOrder,
    WholesaleOrderItem,
    WholesalePricingRule,
    WholesaleReturn,
    WholesaleReturnItem,
    WholesaleSequence,
)
from .pdf import generate_wholesale_invoice_pdf
from .pricing_service import get_wholesale_item_price
from .stock_service import (
    confirm_wholesale_order,
    execute_wholesale_dispatch,
    restock_wholesale_return_item,
    validate_order_stock_availability,
)

logger = logging.getLogger('wholesale.views')


# ==============================================================================
# AUTHORIZATION HELPER
# ==============================================================================

def check_wholesale_access(request, action='view'):
    """
    Ensure the request is authenticated, has an active tenant,
    and has authorization for the wholesale module.
    """
    if not request.user.is_authenticated:
        return False, None
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return False, None
    if request.user.is_superuser:
        return True, tenant
    if not getattr(tenant, 'is_wholesale', True):
        return False, tenant
    if tenant.owner_id == request.user.id and tenant.is_active:
        return True, tenant
    if is_admin_user(request.user, tenant=tenant):
        return True, tenant
    if has_module_perm(request.user, 'wholesale', action=action, tenant=tenant):
        return True, tenant
    return False, tenant


# ==============================================================================
# 1. WHOLESALE DASHBOARD
# ==============================================================================

@login_required
def dashboard(request):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Access restricted. You do not have permission to view Wholesale.")
        return redirect('dashboard')

    # Date range filters
    range_filter = request.GET.get('range', '30d')
    today = timezone.localdate()
    if range_filter == 'today':
        start_date = today
    elif range_filter == '7d':
        start_date = today - timezone.timedelta(days=7)
    elif range_filter == 'month':
        start_date = today.replace(day=1)
    elif range_filter == 'year':
        start_date = today.replace(month=1, day=1)
    else:  # default '30d'
        start_date = today - timezone.timedelta(days=30)

    # 1. Orders metrics
    orders_qs = WholesaleOrder.objects.filter(tenant=tenant)
    period_orders = orders_qs.filter(order_date__gte=start_date)

    total_wholesale_sales = period_orders.exclude(status=WholesaleOrder.STATUS_CANCELLED).aggregate(
        total=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=DecimalField())
    )['total']

    order_count = period_orders.exclude(status=WholesaleOrder.STATUS_CANCELLED).count()
    awaiting_confirmation = orders_qs.filter(status=WholesaleOrder.STATUS_DRAFT).count()
    ready_for_dispatch = orders_qs.filter(status=WholesaleOrder.STATUS_READY_FOR_DISPATCH).count()
    dispatched_orders = orders_qs.filter(status__in=[WholesaleOrder.STATUS_DISPATCHED, WholesaleOrder.STATUS_COMPLETED]).count()

    # 2. Payments & Receivables
    payments_qs = RetailerPayment.objects.filter(tenant=tenant)
    period_payments = payments_qs.filter(payment_date__gte=start_date).aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'), output_field=DecimalField())
    )['total']

    # Outstanding retailer balances (sum of all active retailer balances)
    parties = RetailerParty.objects.filter(tenant=tenant, is_active=True)
    total_outstanding = sum((p.current_balance for p in parties), Decimal('0.00'))

    # 3. Returns awaiting inspection
    returns_pending = WholesaleReturn.objects.filter(tenant=tenant, status=WholesaleReturn.STATUS_REQUESTED).count()

    # 4. Low stock products in tenant inventory
    threshold = get_low_stock_threshold()
    low_stock_items = JewelleryItem.objects.filter(
        tenant=tenant,
        status='Available',
        quantity__lte=threshold
    ).order_by('quantity')[:5]

    # 5. Recent activity
    recent_orders = orders_qs.select_related('party').order_by('-created_at')[:6]
    recent_payments = payments_qs.select_related('party').order_by('-payment_date', '-id')[:6]

    context = {
        'tenant': tenant,
        'range_filter': range_filter,
        'start_date': start_date,
        'total_wholesale_sales': total_wholesale_sales,
        'order_count': order_count,
        'awaiting_confirmation': awaiting_confirmation,
        'ready_for_dispatch': ready_for_dispatch,
        'dispatched_orders': dispatched_orders,
        'period_payments': period_payments,
        'total_outstanding': total_outstanding,
        'returns_pending': returns_pending,
        'low_stock_items': low_stock_items,
        'recent_orders': recent_orders,
        'recent_payments': recent_payments,
    }
    return render(request, 'wholesale/dashboard.html', context)


# ==============================================================================
# 2. RETAILER / PARTY MANAGEMENT
# ==============================================================================

@login_required
def party_list(request):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    qs = RetailerParty.objects.filter(tenant=tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(contact_person__icontains=q) | Q(gstin__icontains=q))

    status_filter = request.GET.get('status', 'active')
    if status_filter == 'active':
        qs = qs.filter(is_active=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'q': q,
        'status_filter': status_filter,
        'total_count': paginator.count,
    }
    return render(request, 'wholesale/party_list.html', context)


@login_required
def party_create(request):
    allowed, tenant = check_wholesale_access(request, 'add')
    if not allowed or not tenant:
        messages.error(request, "Permission denied to add retailer parties.")
        return redirect('wholesale:party_list')

    if request.method == 'POST':
        form = RetailerPartyForm(request.POST, tenant=tenant)
        if form.is_valid():
            party = form.save(commit=False)
            party.tenant = tenant
            party.save()

            # If opening balance provided, log opening balance ledger entry
            if party.opening_balance and party.opening_balance != 0:
                RetailerLedgerEntry.record_entry(
                    tenant=tenant,
                    party=party,
                    entry_type=RetailerLedgerEntry.TYPE_OPENING_BALANCE,
                    reference_number='OPENING-BAL',
                    debit_amount=party.opening_balance if party.opening_balance > 0 else Decimal('0.00'),
                    credit_amount=abs(party.opening_balance) if party.opening_balance < 0 else Decimal('0.00'),
                    description="Opening Balance recorded on party registration"
                )

            messages.success(request, f"Retailer party '{party.name}' created successfully.")
            return redirect('wholesale:party_detail', pk=party.pk)
    else:
        form = RetailerPartyForm(tenant=tenant)

    return render(request, 'wholesale/party_form.html', {'form': form, 'title': 'Add New Retailer Party'})


@login_required
def party_detail(request, pk):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    party = get_object_or_404(RetailerParty, pk=pk, tenant=tenant)
    orders = party.orders.order_by('-order_date', '-id')[:15]
    invoices = party.invoices.order_by('-invoice_date', '-id')[:15]
    payments = party.payments.order_by('-payment_date', '-id')[:15]
    ledger_entries = party.ledger_entries.order_by('-entry_date', '-id')[:30]
    returns = party.returns.order_by('-return_date', '-id')[:10]

    context = {
        'party': party,
        'orders': orders,
        'invoices': invoices,
        'payments': payments,
        'ledger_entries': ledger_entries,
        'returns': returns,
    }
    return render(request, 'wholesale/party_detail.html', context)


@login_required
def party_edit(request, pk):
    allowed, tenant = check_wholesale_access(request, 'edit')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('wholesale:party_list')

    party = get_object_or_404(RetailerParty, pk=pk, tenant=tenant)
    if request.method == 'POST':
        form = RetailerPartyForm(request.POST, instance=party, tenant=tenant)
        if form.is_valid():
            form.save()
            messages.success(request, f"Retailer party '{party.name}' updated successfully.")
            return redirect('wholesale:party_detail', pk=party.pk)
    else:
        form = RetailerPartyForm(instance=party, tenant=tenant)

    return render(request, 'wholesale/party_form.html', {'form': form, 'title': f'Edit Retailer - {party.name}', 'party': party})


# ==============================================================================
# 3. WHOLESALE ORDER WORKFLOW
# ==============================================================================

@login_required
def order_list(request):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    qs = WholesaleOrder.objects.filter(tenant=tenant).select_related('party')
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        qs = qs.filter(status=status_filter)

    party_id = request.GET.get('party', '').strip()
    if party_id:
        qs = qs.filter(party_id=party_id)

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(order_number__icontains=q) | Q(party__name__icontains=q))

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    parties = RetailerParty.objects.filter(tenant=tenant, is_active=True)

    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'party_id': party_id,
        'parties': parties,
        'q': q,
        'status_choices': WholesaleOrder.STATUS_CHOICES,
    }
    return render(request, 'wholesale/order_list.html', context)


@login_required
def order_create(request):
    allowed, tenant = check_wholesale_access(request, 'add')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('wholesale:order_list')

    parties = RetailerParty.objects.filter(tenant=tenant, is_active=True)
    items = JewelleryItem.objects.filter(tenant=tenant, status='Available', quantity__gt=0).select_related('category')

    if request.method == 'POST':
        party_id = request.POST.get('party')
        order_date = request.POST.get('order_date') or timezone.localdate()
        expected_delivery = request.POST.get('expected_delivery_date') or None
        notes = request.POST.get('notes', '')
        internal_remarks = request.POST.get('internal_remarks', '')

        party = get_object_or_404(RetailerParty, pk=party_id, tenant=tenant)

        # Parse selected line items from form arrays
        item_ids = request.POST.getlist('item_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        discount_percents = request.POST.getlist('discount_percent[]')

        if not item_ids:
            messages.error(request, "Please add at least one jewellery product to the order.")
            return render(request, 'wholesale/order_form.html', {'parties': parties, 'items': items})

        try:
            with transaction.atomic():
                order_num = WholesaleSequence.get_next_number(tenant, 'order', prefix='WORD')
                order = WholesaleOrder.objects.create(
                    tenant=tenant,
                    order_number=order_num,
                    party=party,
                    order_date=order_date,
                    expected_delivery_date=expected_delivery,
                    notes=notes,
                    internal_remarks=internal_remarks,
                    created_by=request.user,
                    status=WholesaleOrder.STATUS_DRAFT
                )

                for it_id, q_val, p_val, d_val in zip(item_ids, quantities, unit_prices, discount_percents):
                    if not it_id:
                        continue
                    jwl_item = JewelleryItem.objects.select_for_update().get(pk=it_id, tenant=tenant)
                    qty = max(1, int(q_val or 1))
                    price = Decimal(str(p_val or jwl_item.selling_price))
                    disc = Decimal(str(d_val or '0.00'))
                    tax_rate = Decimal('3.00')

                    line_sub = (Decimal(str(qty)) * price * (Decimal('100.00') - disc) / Decimal('100.00')).quantize(Decimal('0.01'))
                    line_tax = (line_sub * (tax_rate / Decimal('100.00'))).quantize(Decimal('0.01'))

                    WholesaleOrderItem.objects.create(
                        order=order,
                        item=jwl_item,
                        quantity=qty,
                        unit_price=price,
                        discount_percent=disc,
                        tax_rate=tax_rate,
                        tax_amount=line_tax,
                        total_price=line_sub + line_tax,
                    )

                order.calculate_totals(save=True)

            messages.success(request, f"Wholesale Order #{order.order_number} created successfully as Draft.")
            return redirect('wholesale:order_detail', pk=order.pk)
        except Exception as e:
            logger.exception("Error creating wholesale order: %s", e)
            messages.error(request, f"Unable to create order: {e}")

    return render(request, 'wholesale/order_form.html', {'parties': parties, 'items': items})


@login_required
def order_detail(request, pk):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    order = get_object_or_404(WholesaleOrder.objects.select_related('party', 'created_by'), pk=pk, tenant=tenant)
    items = order.items.select_related('item', 'item__category').all()
    dispatches = order.dispatches.order_by('-dispatch_date', '-id')
    invoices = order.invoices.order_by('-invoice_date', '-id')

    context = {
        'order': order,
        'items': items,
        'dispatches': dispatches,
        'invoices': invoices,
    }
    return render(request, 'wholesale/order_detail.html', context)


@login_required
def order_status_update(request, pk):
    """Transition wholesale order state with validation and atomic execution."""
    allowed, tenant = check_wholesale_access(request, 'edit')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('wholesale:order_list')

    order = get_object_or_404(WholesaleOrder, pk=pk, tenant=tenant)
    if request.method == 'POST':
        target_status = request.POST.get('target_status')

        if not order.can_transition_to(target_status):
            messages.error(request, f"Invalid status transition from '{order.status}' to '{target_status}'.")
            return redirect('wholesale:order_detail', pk=order.pk)

        try:
            if target_status == WholesaleOrder.STATUS_CONFIRMED:
                confirm_wholesale_order(order, user=request.user)
                messages.success(request, f"Order #{order.order_number} has been confirmed and stock verified.")
            else:
                with transaction.atomic():
                    order.status = target_status
                    order.save(update_fields=['status', 'updated_at'])
                messages.success(request, f"Order status updated to '{target_status}'.")
        except ValidationError as ve:
            messages.error(request, str(ve))
        except Exception as ex:
            logger.exception("Error updating order status: %s", ex)
            messages.error(request, f"Status update failed: {ex}")

    return redirect('wholesale:order_detail', pk=order.pk)


# ==============================================================================
# 4. DISPATCH WORKFLOW
# ==============================================================================

@login_required
def dispatch_list(request):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    qs = WholesaleDispatch.objects.filter(tenant=tenant).select_related('order', 'party')
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'wholesale/dispatch_list.html', {'page_obj': page_obj})


@login_required
def dispatch_create(request, order_pk):
    allowed, tenant = check_wholesale_access(request, 'add')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('wholesale:order_list')

    order = get_object_or_404(WholesaleOrder, pk=order_pk, tenant=tenant)
    if order.status in (WholesaleOrder.STATUS_DRAFT, WholesaleOrder.STATUS_CANCELLED, WholesaleOrder.STATUS_COMPLETED):
        messages.error(request, f"Cannot create dispatch for order in '{order.status}' status.")
        return redirect('wholesale:order_detail', pk=order.pk)

    order_items = order.items.select_related('item').all()

    if request.method == 'POST':
        courier_name = request.POST.get('courier_name', '')
        tracking_number = request.POST.get('tracking_number', '')
        notes = request.POST.get('notes', '')

        dispatch_items_data = []
        for line in order_items:
            qty_input = request.POST.get(f"qty_{line.id}", '0')
            tag_input = request.POST.get(f"tag_{line.id}", '')
            try:
                qty = int(qty_input)
                if qty > 0:
                    dispatch_items_data.append({
                        'order_item_id': line.id,
                        'quantity': qty,
                        'tag_number': tag_input or line.item.tag_number,
                    })
            except ValueError:
                pass

        if not dispatch_items_data:
            messages.error(request, "Please enter a valid quantity of at least 1 piece to dispatch.")
            return render(request, 'wholesale/dispatch_form.html', {'order': order, 'order_items': order_items})

        try:
            dispatch = execute_wholesale_dispatch(
                order=order,
                dispatch_items_data=dispatch_items_data,
                courier_name=courier_name,
                tracking_number=tracking_number,
                notes=notes,
                user=request.user
            )

            # Auto-generate wholesale invoice if requested
            if request.POST.get('create_invoice') == '1':
                create_invoice_for_order(order=order, dispatch=dispatch, user=request.user)

            messages.success(request, f"Dispatch #{dispatch.dispatch_number} recorded successfully. Physical stock deducted.")
            return redirect('wholesale:dispatch_detail', pk=dispatch.pk)
        except ValidationError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            logger.exception("Error executing dispatch: %s", e)
            messages.error(request, f"Dispatch failed: {e}")

    return render(request, 'wholesale/dispatch_form.html', {'order': order, 'order_items': order_items})


@login_required
def dispatch_detail(request, pk):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    dispatch = get_object_or_404(WholesaleDispatch.objects.select_related('order', 'party', 'created_by'), pk=pk, tenant=tenant)
    items = dispatch.items.select_related('item', 'order_item').all()

    return render(request, 'wholesale/dispatch_detail.html', {'dispatch': dispatch, 'items': items})


# ==============================================================================
# 5. WHOLESALE INVOICES & BILLING
# ==============================================================================

@login_required
def invoice_list(request):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    qs = WholesaleInvoice.objects.filter(tenant=tenant).select_related('party', 'order')
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        qs = qs.filter(status=status_filter)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'wholesale/invoice_list.html', {'page_obj': page_obj, 'status_filter': status_filter})


@login_required
def invoice_create_from_order(request, order_pk):
    allowed, tenant = check_wholesale_access(request, 'add')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('wholesale:invoice_list')

    order = get_object_or_404(WholesaleOrder, pk=order_pk, tenant=tenant)
    try:
        invoice = create_invoice_for_order(order=order, user=request.user)
        messages.success(request, f"Tax Invoice #{invoice.invoice_number} created successfully and debited to party ledger.")
        return redirect('wholesale:invoice_detail', pk=invoice.pk)
    except Exception as e:
        logger.exception("Error creating invoice: %s", e)
        messages.error(request, f"Failed to generate invoice: {e}")
        return redirect('wholesale:order_detail', pk=order.pk)


@login_required
def invoice_detail(request, pk):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    invoice = get_object_or_404(WholesaleInvoice.objects.select_related('party', 'order', 'tenant'), pk=pk, tenant=tenant)
    items = invoice.items.select_related('item').all()
    allocations = invoice.payment_allocations.select_related('payment').all()

    return render(request, 'wholesale/invoice_detail.html', {'invoice': invoice, 'items': items, 'allocations': allocations})


@login_required
def invoice_pdf_view(request, pk):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        return HttpResponseForbidden("Access Denied")

    invoice = get_object_or_404(WholesaleInvoice, pk=pk, tenant=tenant)
    pdf_bytes = generate_wholesale_invoice_pdf(invoice)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f"Wholesale_Invoice_{invoice.invoice_number}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


# ==============================================================================
# 6. PAYMENTS & PARTY LEDGER
# ==============================================================================

@login_required
def payment_list(request):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    qs = RetailerPayment.objects.filter(tenant=tenant).select_related('party')
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'wholesale/payment_list.html', {'page_obj': page_obj})


@login_required
def payment_create(request):
    allowed, tenant = check_wholesale_access(request, 'add')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('wholesale:payment_list')

    parties = RetailerParty.objects.filter(tenant=tenant, is_active=True)

    if request.method == 'POST':
        form = RetailerPaymentForm(request.POST, tenant=tenant)
        if form.is_valid():
            try:
                payment = record_retailer_payment(
                    party=form.cleaned_data['party'],
                    amount=form.cleaned_data['amount'],
                    payment_method=form.cleaned_data['payment_method'],
                    reference=form.cleaned_data['reference'],
                    notes=form.cleaned_data['notes'],
                    user=request.user
                )
                messages.success(request, f"Payment #{payment.payment_number} recorded successfully and credited to ledger.")
                return redirect('wholesale:party_detail', pk=payment.party.pk)
            except Exception as e:
                logger.exception("Error recording payment: %s", e)
                messages.error(request, f"Payment recording failed: {e}")
    else:
        initial_party = request.GET.get('party')
        form = RetailerPaymentForm(tenant=tenant, initial={'party': initial_party} if initial_party else None)

    return render(request, 'wholesale/payment_form.html', {'form': form, 'parties': parties})


@login_required
def ledger_view(request):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    qs = RetailerLedgerEntry.objects.filter(tenant=tenant).select_related('party', 'invoice', 'payment', 'return_ref')
    party_id = request.GET.get('party', '').strip()
    if party_id:
        qs = qs.filter(party_id=party_id)

    parties = RetailerParty.objects.filter(tenant=tenant)
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'wholesale/ledger_view.html', {'page_obj': page_obj, 'parties': parties, 'selected_party': party_id})


# ==============================================================================
# 7. RETURNS & CREDIT NOTES
# ==============================================================================

@login_required
def return_list(request):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    qs = WholesaleReturn.objects.filter(tenant=tenant).select_related('party')
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'wholesale/return_list.html', {'page_obj': page_obj})


@login_required
def return_create(request):
    allowed, tenant = check_wholesale_access(request, 'add')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('wholesale:return_list')

    parties = RetailerParty.objects.filter(tenant=tenant, is_active=True)
    items = JewelleryItem.objects.filter(tenant=tenant)

    if request.method == 'POST':
        party_id = request.POST.get('party')
        invoice_id = request.POST.get('invoice') or None
        reason = request.POST.get('reason', 'Stock Return')
        inspection_notes = request.POST.get('inspection_notes', '')

        party = get_object_or_404(RetailerParty, pk=party_id, tenant=tenant)
        invoice = WholesaleInvoice.objects.filter(pk=invoice_id, tenant=tenant).first() if invoice_id else None

        item_ids = request.POST.getlist('item_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        dispositions = request.POST.getlist('disposition[]')

        if not item_ids:
            messages.error(request, "Please add at least one item to the return.")
            return render(request, 'wholesale/return_form.html', {'parties': parties, 'items': items})

        try:
            with transaction.atomic():
                ret_num = WholesaleSequence.get_next_number(tenant, 'return', prefix='WRET')
                wholesale_return = WholesaleReturn.objects.create(
                    tenant=tenant,
                    return_number=ret_num,
                    party=party,
                    invoice=invoice,
                    reason=reason,
                    inspection_notes=inspection_notes,
                    status=WholesaleReturn.STATUS_REQUESTED
                )

                for it_id, q_val, p_val, disp_val in zip(item_ids, quantities, unit_prices, dispositions):
                    if not it_id:
                        continue
                    jwl = JewelleryItem.objects.get(pk=it_id, tenant=tenant)
                    qty = max(1, int(q_val or 1))
                    price = Decimal(str(p_val or jwl.selling_price))
                    WholesaleReturnItem.objects.create(
                        wholesale_return=wholesale_return,
                        item=jwl,
                        quantity=qty,
                        unit_price=price,
                        disposition=disp_val or WholesaleReturnItem.DISP_SELLABLE,
                        restocked=False
                    )

                wholesale_return.calculate_totals(save=True)

            messages.success(request, f"Return Request #{wholesale_return.return_number} logged successfully.")
            return redirect('wholesale:return_detail', pk=wholesale_return.pk)
        except Exception as e:
            logger.exception("Error logging return: %s", e)
            messages.error(request, f"Failed to record return: {e}")

    return render(request, 'wholesale/return_form.html', {'parties': parties, 'items': items})


@login_required
def return_detail(request, pk):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    ret = get_object_or_404(WholesaleReturn.objects.select_related('party', 'invoice'), pk=pk, tenant=tenant)
    items = ret.items.select_related('item').all()

    return render(request, 'wholesale/return_detail.html', {'return': ret, 'items': items})


@login_required
def return_approve(request, pk):
    allowed, tenant = check_wholesale_access(request, 'edit')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('wholesale:return_list')

    ret = get_object_or_404(WholesaleReturn, pk=pk, tenant=tenant)
    if request.method == 'POST':
        ret.status = WholesaleReturn.STATUS_APPROVED
        ret.approved_by = request.user
        ret.approved_at = timezone.now()
        ret.save(update_fields=['status', 'approved_by', 'approved_at'])
        messages.success(request, f"Return #{ret.return_number} approved.")

    return redirect('wholesale:return_detail', pk=ret.pk)


@login_required
def return_restock(request, pk, item_pk):
    allowed, tenant = check_wholesale_access(request, 'edit')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('wholesale:return_list')

    ret = get_object_or_404(WholesaleReturn, pk=pk, tenant=tenant)
    ret_item = get_object_or_404(WholesaleReturnItem, pk=item_pk, wholesale_return=ret)

    try:
        restock_wholesale_return_item(ret_item, user=request.user)
        messages.success(request, f"Item '{ret_item.item.name}' restocked back into showroom stock.")
    except Exception as e:
        messages.error(request, f"Restocking failed: {e}")

    return redirect('wholesale:return_detail', pk=ret.pk)


@login_required
def return_issue_credit(request, pk):
    allowed, tenant = check_wholesale_access(request, 'edit')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('wholesale:return_list')

    ret = get_object_or_404(WholesaleReturn, pk=pk, tenant=tenant)
    try:
        issue_wholesale_credit_note(ret, user=request.user)
        messages.success(request, f"Credit Note #{ret.credit_note_number} issued and credited to party ledger.")
    except Exception as e:
        messages.error(request, f"Failed to issue credit note: {e}")

    return redirect('wholesale:return_detail', pk=ret.pk)


# ==============================================================================
# 8. WHOLESALE PRICING RULES & CATALOGUE
# ==============================================================================

@login_required
def pricing_rule_list(request):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    rules = WholesalePricingRule.objects.filter(tenant=tenant).select_related('party', 'category', 'item')
    return render(request, 'wholesale/pricing_rules.html', {'rules': rules})


@login_required
def pricing_rule_create(request):
    allowed, tenant = check_wholesale_access(request, 'add')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('wholesale:pricing_rules')

    if request.method == 'POST':
        form = WholesalePricingRuleForm(request.POST, tenant=tenant)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.tenant = tenant
            rule.save()
            messages.success(request, "Wholesale pricing rule saved successfully.")
            return redirect('wholesale:pricing_rules')
    else:
        form = WholesalePricingRuleForm(tenant=tenant)

    return render(request, 'wholesale/pricing_rule_form.html', {'form': form})


@login_required
def catalogue_view(request):
    """View products with live stock and wholesale prices."""
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    party_id = request.GET.get('party')
    party = RetailerParty.objects.filter(pk=party_id, tenant=tenant).first() if party_id else None

    items = JewelleryItem.objects.filter(tenant=tenant, status='Available').select_related('category')
    q = request.GET.get('q', '').strip()
    if q:
        items = items.filter(Q(name__icontains=q) | Q(item_code__icontains=q) | Q(design_code__icontains=q))

    # Calculate wholesale price for each item in memory
    catalogue_data = []
    for it in items:
        p_info = get_wholesale_item_price(it, party=party)
        catalogue_data.append({
            'item': it,
            'retail_price': it.selling_price,
            'wholesale_price': p_info['unit_price'],
            'discount': p_info['discount_percent'],
            'stock': it.quantity,
        })

    parties = RetailerParty.objects.filter(tenant=tenant, is_active=True)

    return render(request, 'wholesale/catalogue.html', {
        'catalogue_data': catalogue_data,
        'parties': parties,
        'selected_party': party,
        'q': q,
    })


# ==============================================================================
# 9. WHOLESALE REPORTS
# ==============================================================================

@login_required
def reports_dashboard(request):
    allowed, tenant = check_wholesale_access(request, 'view')
    if not allowed or not tenant:
        messages.error(request, "Permission denied.")
        return redirect('dashboard')

    # Top Retailers by Wholesale Sales
    top_retailers = RetailerParty.objects.filter(tenant=tenant).annotate(
        total_sales=Coalesce(Sum('orders__total_amount', filter=~Q(orders__status=WholesaleOrder.STATUS_CANCELLED)), Decimal('0.00'), output_field=DecimalField()),
        orders_count=Count('orders', filter=~Q(orders__status=WholesaleOrder.STATUS_CANCELLED))
    ).order_by('-total_sales')[:10]

    # Category Sales Breakdown
    category_sales = Category.objects.filter(tenant=tenant).annotate(
        sales_val=Coalesce(Sum('items__wholesale_order_items__total_price', filter=~Q(items__wholesale_order_items__order__status=WholesaleOrder.STATUS_CANCELLED)), Decimal('0.00'), output_field=DecimalField()),
        pieces_sold=Coalesce(Sum('items__wholesale_order_items__quantity', filter=~Q(items__wholesale_order_items__order__status=WholesaleOrder.STATUS_CANCELLED)), 0)
    ).order_by('-sales_val')

    return render(request, 'wholesale/reports_dashboard.html', {
        'top_retailers': top_retailers,
        'category_sales': category_sales,
    })


@login_required
def export_retailer_ledger_csv(request, party_pk):
    allowed, tenant = check_wholesale_access(request, 'export')
    if not allowed or not tenant:
        return HttpResponseForbidden("Access Denied")

    party = get_object_or_404(RetailerParty, pk=party_pk, tenant=tenant)
    entries = party.ledger_entries.order_by('entry_date', 'id')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="Ledger_{party.name.replace(" ", "_")}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Date', 'Reference', 'Type', 'Description', 'Debit (Rs)', 'Credit (Rs)', 'Balance (Rs)'])

    for e in entries:
        writer.writerow([
            e.entry_date.strftime('%Y-%m-%d'),
            e.reference_number,
            e.get_entry_type_display(),
            e.description,
            f"{e.debit_amount:.2f}",
            f"{e.credit_amount:.2f}",
            f"{e.balance_after:.2f}",
        ])

    return response
