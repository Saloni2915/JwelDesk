"""
purchases/views.py
------------------
Controller handlers for the JwelDesk Purchase Management Module.
Includes multi-tenant scoping, branch isolation, dynamic item entry,
supplier ledger statements, payment vouchers, returns, and reports.
"""
import csv
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, Count, Q, F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from accounts.models import CompanySettings
from inventory.models import Category, MetalRate, JewelleryItem
from team.models import Branch
from .models import (
    Supplier,
    PurchaseSetting,
    PurchaseInvoice,
    PurchaseItem,
    SupplierPayment,
    SupplierLedgerEntry,
    PurchaseReturn,
    PurchaseReturnItem,
)
from .forms import (
    SupplierForm,
    PurchaseInvoiceForm,
    PurchaseItemForm,
    SupplierPaymentForm,
    PurchaseSettingForm,
)
from .services import (
    confirm_purchase_invoice,
    cancel_purchase_invoice,
    record_supplier_payment,
    cancel_supplier_payment,
    process_purchase_return,
)

logger = logging.getLogger('purchases.views')


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_tenant_branches(request):
    """Return branches accessible to the current user."""
    if hasattr(request, 'allowed_branches') and request.allowed_branches:
        return request.allowed_branches
    if request.tenant:
        return Branch.objects.filter(tenant=request.tenant, is_active=True)
    return Branch.objects.none()


def apply_branch_filter(qs, request, branch_field='branch'):
    """Filter queryset by user's branch permissions and active branch filter."""
    selected_branch_id = request.GET.get('branch')
    if selected_branch_id:
        try:
            return qs.filter(**{f"{branch_field}_id": int(selected_branch_id)})
        except (ValueError, TypeError):
            pass

    if getattr(request, 'is_all_branches', False) or getattr(request, 'can_view_all_branches', False):
        return qs

    if hasattr(request, 'branch') and request.branch:
        return qs.filter(Q(**{f"{branch_field}": request.branch}) | Q(**{f"{branch_field}__isnull": True}))

    return qs


# ==============================================================================
# 1. PURCHASE DASHBOARD -- DELEGATES TO CENTRALIZED DASHBOARD
# ==============================================================================

@login_required
def dashboard_view(request):
    """
    Purchase Dashboard entrypoint -- unified into Central Dashboard.
    """
    from inventory.dashboard_service import get_central_dashboard_context
    context = get_central_dashboard_context(request)
    return render(request, 'inventory/dashboard.html', context)


# ==============================================================================
# 2. PURCHASE INVOICE VIEWS (CREATE, EDIT, DETAIL, CONFIRM, CANCEL)
# ==============================================================================

@login_required
def purchase_list_view(request):
    """Filterable, paginated register of all purchase invoices."""
    tenant = request.tenant
    invoices = PurchaseInvoice.objects.filter(tenant=tenant).select_related('supplier', 'branch').order_by('-purchase_date', '-id')

    invoices = apply_branch_filter(invoices, request)

    # Search query
    q = (request.GET.get('q') or '').strip()
    if q:
        invoices = invoices.filter(
            Q(purchase_number__icontains=q) |
            Q(supplier_invoice_number__icontains=q) |
            Q(supplier__name__icontains=q) |
            Q(supplier__mobile__icontains=q)
        )

    # Status filter
    status = request.GET.get('status')
    if status:
        invoices = invoices.filter(status=status)

    # Purchase type filter
    ptype = request.GET.get('type')
    if ptype:
        invoices = invoices.filter(purchase_type=ptype)

    # Supplier filter
    supplier_id = request.GET.get('supplier')
    if supplier_id:
        invoices = invoices.filter(supplier_id=supplier_id)

    # Date range filters
    date_from = request.GET.get('from')
    date_to = request.GET.get('to')
    if date_from:
        invoices = invoices.filter(purchase_date__gte=date_from)
    if date_to:
        invoices = invoices.filter(purchase_date__lte=date_to)

    paginator = Paginator(invoices, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    suppliers = Supplier.objects.filter(tenant=tenant, is_active=True).order_by('name')
    branches = get_tenant_branches(request)

    context = {
        'page_obj': page_obj,
        'suppliers': suppliers,
        'branches': branches,
        'selected_status': status,
        'selected_type': ptype,
        'selected_supplier': supplier_id,
        'selected_branch': request.GET.get('branch', ''),
        'search_query': q,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'purchases/purchase_list.html', context)


@login_required
def purchase_create_view(request):
    """
    New Purchase Invoice creation view supporting multiple jewellery items,
    live calculations, and optional immediate confirmation.
    """
    tenant = request.tenant
    settings_obj = PurchaseSetting.load(tenant=tenant)

    if request.method == 'POST':
        form = PurchaseInvoiceForm(request.POST, tenant=tenant)
        if form.is_valid():
            with transaction.atomic():
                invoice = form.save(commit=False)
                invoice.tenant = tenant
                if not invoice.branch:
                    invoice.branch = getattr(request, 'branch', None)
                invoice.created_by = request.user
                invoice.save()

                # Process multi-item rows submitted via POST
                item_names = request.POST.getlist('item_name[]')
                categories = request.POST.getlist('category[]')
                metals = request.POST.getlist('metal_type[]')
                purities = request.POST.getlist('purity[]')
                purity_pcts = request.POST.getlist('purity_percentage[]')
                quantities = request.POST.getlist('quantity[]')
                gross_weights = request.POST.getlist('gross_weight[]')
                stone_weights = request.POST.getlist('stone_weight[]')
                rates = request.POST.getlist('purchase_rate[]')
                rate_types = request.POST.getlist('rate_type[]')
                mc_types = request.POST.getlist('making_charge_type[]')
                mc_rates = request.POST.getlist('making_charge_rate[]')
                stone_charges_list = request.POST.getlist('stone_charges[]')
                other_charges_list = request.POST.getlist('other_charges[]')
                tax_rates = request.POST.getlist('tax_rate[]')
                huids = request.POST.getlist('huid[]')
                hallmarks = request.POST.getlist('hallmark_details[]')
                descriptions = request.POST.getlist('description[]')

                for i in range(len(item_names)):
                    name = (item_names[i] or '').strip()
                    if not name:
                        continue

                    cat_id = categories[i] if i < len(categories) and categories[i] else None
                    cat = Category.objects.filter(pk=cat_id, tenant=tenant).first() if cat_id else None

                    metal = metals[i] if i < len(metals) and metals[i] else 'Gold'
                    purity = purities[i] if i < len(purities) and purities[i] else '22K'

                    try:
                        purity_pct = Decimal(str(purity_pcts[i])) if i < len(purity_pcts) and purity_pcts[i] else Decimal('91.60')
                    except (InvalidOperation, TypeError):
                        purity_pct = Decimal('91.60')

                    try:
                        qty = int(quantities[i]) if i < len(quantities) and quantities[i] else 1
                    except (ValueError, TypeError):
                        qty = 1

                    try:
                        gw = Decimal(str(gross_weights[i])) if i < len(gross_weights) and gross_weights[i] else Decimal('0.000')
                    except (InvalidOperation, TypeError):
                        gw = Decimal('0.000')

                    try:
                        sw = Decimal(str(stone_weights[i])) if i < len(stone_weights) and stone_weights[i] else Decimal('0.000')
                    except (InvalidOperation, TypeError):
                        sw = Decimal('0.000')

                    try:
                        rate = Decimal(str(rates[i])) if i < len(rates) and rates[i] else Decimal('0.00')
                    except (InvalidOperation, TypeError):
                        rate = Decimal('0.00')

                    rate_type = rate_types[i] if i < len(rate_types) and rate_types[i] else 'PER_GRAM'
                    mc_type = mc_types[i] if i < len(mc_types) and mc_types[i] else 'Per Gram'

                    try:
                        mc_rate = Decimal(str(mc_rates[i])) if i < len(mc_rates) and mc_rates[i] else Decimal('0.00')
                    except (InvalidOperation, TypeError):
                        mc_rate = Decimal('0.00')

                    try:
                        stn_chg = Decimal(str(stone_charges_list[i])) if i < len(stone_charges_list) and stone_charges_list[i] else Decimal('0.00')
                    except (InvalidOperation, TypeError):
                        stn_chg = Decimal('0.00')

                    try:
                        oth_chg = Decimal(str(other_charges_list[i])) if i < len(other_charges_list) and other_charges_list[i] else Decimal('0.00')
                    except (InvalidOperation, TypeError):
                        oth_chg = Decimal('0.00')

                    try:
                        item_tax = Decimal(str(tax_rates[i])) if i < len(tax_rates) and tax_rates[i] else invoice.tax_rate
                    except (InvalidOperation, TypeError):
                        item_tax = invoice.tax_rate

                    huid = (huids[i] or '').strip().upper() if i < len(huids) else ''
                    hallmark = (hallmarks[i] or '').strip() if i < len(hallmarks) else ''
                    desc = (descriptions[i] or '').strip() if i < len(descriptions) else ''

                    item = PurchaseItem(
                        purchase=invoice,
                        item_name=name,
                        category=cat,
                        metal_type=metal,
                        purity=purity,
                        purity_percentage=purity_pct,
                        quantity=max(1, qty),
                        gross_weight=gw,
                        stone_weight=sw,
                        purchase_rate=rate,
                        rate_type=rate_type,
                        making_charge_type=mc_type,
                        making_charge_rate=mc_rate,
                        stone_charges=stn_chg,
                        other_charges=oth_chg,
                        tax_rate=item_tax,
                        huid=huid,
                        hallmark_details=hallmark,
                        description=desc
                    )
                    item.save()

                invoice.recalculate_totals(save=True)

                # Check if user requested immediate confirmation
                action = request.POST.get('action')
                if action == 'confirm':
                    try:
                        confirm_purchase_invoice(invoice.pk, user=request.user)
                        messages.success(request, f"Purchase Invoice #{invoice.purchase_number} saved and confirmed successfully! Inventory updated.")
                    except ValidationError as e:
                        messages.warning(request, f"Purchase saved as Draft, but confirmation encountered an error: {e}")
                else:
                    messages.success(request, f"Purchase Invoice #{invoice.purchase_number} created as Draft.")

                return redirect('purchases:purchase_detail', pk=invoice.pk)
    else:
        initial = {
            'purchase_date': timezone.localdate(),
            'tax_rate': settings_obj.default_tax_rate,
            'tax_type': settings_obj.default_tax_type,
            'payment_terms_days': settings_obj.default_payment_terms_days,
            'branch': getattr(request, 'branch', None),
        }
        form = PurchaseInvoiceForm(tenant=tenant, initial=initial)

    categories = Category.objects.filter(tenant=tenant).order_by('name')
    suppliers = Supplier.objects.filter(tenant=tenant, is_active=True).order_by('name')
    branches = get_tenant_branches(request)

    context = {
        'form': form,
        'categories': categories,
        'suppliers': suppliers,
        'branches': branches,
        'settings_obj': settings_obj,
    }
    return render(request, 'purchases/purchase_form.html', context)


@login_required
def purchase_detail_view(request, pk):
    """Detailed inspection view for a purchase invoice."""
    tenant = request.tenant
    invoice = get_object_or_404(
        PurchaseInvoice.objects.select_related('supplier', 'branch', 'created_by', 'confirmed_by'),
        pk=pk,
        tenant=tenant
    )
    items = invoice.items.select_related('category', 'inventory_item').all()
    payments = invoice.payments.select_related('created_by').order_by('-payment_date')
    returns = invoice.returns.select_related('created_by').order_by('-return_date')

    context = {
        'invoice': invoice,
        'items': items,
        'payments': payments,
        'returns': returns,
    }
    return render(request, 'purchases/purchase_detail.html', context)


@login_required
def purchase_edit_view(request, pk):
    """Edit draft purchase invoice before confirmation."""
    tenant = request.tenant
    invoice = get_object_or_404(PurchaseInvoice, pk=pk, tenant=tenant)

    if invoice.status != 'DRAFT':
        messages.error(request, f"Invoice #{invoice.purchase_number} is '{invoice.get_status_display()}' and cannot be edited. Completed invoices cannot be silently altered.")
        return redirect('purchases:purchase_detail', pk=invoice.pk)

    if request.method == 'POST':
        form = PurchaseInvoiceForm(request.POST, instance=invoice, tenant=tenant)
        if form.is_valid():
            with transaction.atomic():
                invoice = form.save()
                # Clear and re-populate items from POST formset
                invoice.items.all().delete()

                item_names = request.POST.getlist('item_name[]')
                categories = request.POST.getlist('category[]')
                metals = request.POST.getlist('metal_type[]')
                purities = request.POST.getlist('purity[]')
                purity_pcts = request.POST.getlist('purity_percentage[]')
                quantities = request.POST.getlist('quantity[]')
                gross_weights = request.POST.getlist('gross_weight[]')
                stone_weights = request.POST.getlist('stone_weight[]')
                rates = request.POST.getlist('purchase_rate[]')
                rate_types = request.POST.getlist('rate_type[]')
                mc_types = request.POST.getlist('making_charge_type[]')
                mc_rates = request.POST.getlist('making_charge_rate[]')
                stone_charges_list = request.POST.getlist('stone_charges[]')
                other_charges_list = request.POST.getlist('other_charges[]')
                tax_rates = request.POST.getlist('tax_rate[]')
                huids = request.POST.getlist('huid[]')
                hallmarks = request.POST.getlist('hallmark_details[]')
                descriptions = request.POST.getlist('description[]')

                for i in range(len(item_names)):
                    name = (item_names[i] or '').strip()
                    if not name:
                        continue

                    cat_id = categories[i] if i < len(categories) and categories[i] else None
                    cat = Category.objects.filter(pk=cat_id, tenant=tenant).first() if cat_id else None
                    metal = metals[i] if i < len(metals) and metals[i] else 'Gold'
                    purity = purities[i] if i < len(purities) and purities[i] else '22K'

                    try:
                        purity_pct = Decimal(str(purity_pcts[i])) if i < len(purity_pcts) and purity_pcts[i] else Decimal('91.60')
                    except (InvalidOperation, TypeError):
                        purity_pct = Decimal('91.60')

                    try:
                        qty = int(quantities[i]) if i < len(quantities) and quantities[i] else 1
                    except (ValueError, TypeError):
                        qty = 1

                    try:
                        gw = Decimal(str(gross_weights[i])) if i < len(gross_weights) and gross_weights[i] else Decimal('0.000')
                    except (InvalidOperation, TypeError):
                        gw = Decimal('0.000')

                    try:
                        sw = Decimal(str(stone_weights[i])) if i < len(stone_weights) and stone_weights[i] else Decimal('0.000')
                    except (InvalidOperation, TypeError):
                        sw = Decimal('0.000')

                    try:
                        rate = Decimal(str(rates[i])) if i < len(rates) and rates[i] else Decimal('0.00')
                    except (InvalidOperation, TypeError):
                        rate = Decimal('0.00')

                    rate_type = rate_types[i] if i < len(rate_types) and rate_types[i] else 'PER_GRAM'
                    mc_type = mc_types[i] if i < len(mc_types) and mc_types[i] else 'Per Gram'

                    try:
                        mc_rate = Decimal(str(mc_rates[i])) if i < len(mc_rates) and mc_rates[i] else Decimal('0.00')
                    except (InvalidOperation, TypeError):
                        mc_rate = Decimal('0.00')

                    try:
                        stn_chg = Decimal(str(stone_charges_list[i])) if i < len(stone_charges_list) and stone_charges_list[i] else Decimal('0.00')
                    except (InvalidOperation, TypeError):
                        stn_chg = Decimal('0.00')

                    try:
                        oth_chg = Decimal(str(other_charges_list[i])) if i < len(other_charges_list) and other_charges_list[i] else Decimal('0.00')
                    except (InvalidOperation, TypeError):
                        oth_chg = Decimal('0.00')

                    try:
                        item_tax = Decimal(str(tax_rates[i])) if i < len(tax_rates) and tax_rates[i] else invoice.tax_rate
                    except (InvalidOperation, TypeError):
                        item_tax = invoice.tax_rate

                    huid = (huids[i] or '').strip().upper() if i < len(huids) else ''
                    hallmark = (hallmarks[i] or '').strip() if i < len(hallmarks) else ''
                    desc = (descriptions[i] or '').strip() if i < len(descriptions) else ''

                    item = PurchaseItem(
                        purchase=invoice,
                        item_name=name,
                        category=cat,
                        metal_type=metal,
                        purity=purity,
                        purity_percentage=purity_pct,
                        quantity=max(1, qty),
                        gross_weight=gw,
                        stone_weight=sw,
                        purchase_rate=rate,
                        rate_type=rate_type,
                        making_charge_type=mc_type,
                        making_charge_rate=mc_rate,
                        stone_charges=stn_chg,
                        other_charges=oth_chg,
                        tax_rate=item_tax,
                        huid=huid,
                        hallmark_details=hallmark,
                        description=desc
                    )
                    item.save()

                invoice.recalculate_totals(save=True)
                messages.success(request, f"Purchase Invoice #{invoice.purchase_number} updated.")
                return redirect('purchases:purchase_detail', pk=invoice.pk)
    else:
        form = PurchaseInvoiceForm(instance=invoice, tenant=tenant)

    existing_items = invoice.items.all()
    categories = Category.objects.filter(tenant=tenant).order_by('name')
    suppliers = Supplier.objects.filter(tenant=tenant, is_active=True).order_by('name')
    branches = get_tenant_branches(request)

    context = {
        'form': form,
        'invoice': invoice,
        'existing_items': existing_items,
        'categories': categories,
        'suppliers': suppliers,
        'branches': branches,
    }
    return render(request, 'purchases/purchase_form.html', context)


@login_required
@require_POST
def purchase_confirm_view(request, pk):
    """Confirm a draft purchase invoice and trigger inventory synchronization."""
    tenant = request.tenant
    invoice = get_object_or_404(PurchaseInvoice, pk=pk, tenant=tenant)
    try:
        confirm_purchase_invoice(invoice.pk, user=request.user)
        messages.success(request, f"Purchase Invoice #{invoice.purchase_number} confirmed! Stock created and supplier balance updated.")
    except ValidationError as e:
        messages.error(request, f"Confirmation failed: {e}")
    return redirect('purchases:purchase_detail', pk=invoice.pk)


@login_required
@require_POST
def purchase_cancel_view(request, pk):
    """Cancel a purchase invoice with audit note."""
    tenant = request.tenant
    invoice = get_object_or_404(PurchaseInvoice, pk=pk, tenant=tenant)
    reason = request.POST.get('reason', 'Cancelled by user').strip()
    try:
        cancel_purchase_invoice(invoice.pk, user=request.user, reason=reason)
        messages.success(request, f"Purchase Invoice #{invoice.purchase_number} has been cancelled.")
    except ValidationError as e:
        messages.error(request, f"Cancellation failed: {e}")
    return redirect('purchases:purchase_detail', pk=invoice.pk)


@login_required
def purchase_voucher_view(request, pk):
    """Printable Purchase Voucher / Inward Receipt."""
    tenant = request.tenant
    invoice = get_object_or_404(PurchaseInvoice.objects.select_related('supplier', 'branch', 'created_by'), pk=pk, tenant=tenant)
    items = invoice.items.select_related('category').all()
    company = CompanySettings.load(tenant=tenant)

    context = {
        'invoice': invoice,
        'items': items,
        'company': company,
    }
    return render(request, 'purchases/purchase_voucher.html', context)


# ==============================================================================
# 3. SUPPLIER / PARTY MANAGEMENT
# ==============================================================================

@login_required
def supplier_list_view(request):
    """Supplier master directory with balance summary and search."""
    tenant = request.tenant
    suppliers = Supplier.objects.filter(tenant=tenant).order_by('name')

    q = (request.GET.get('q') or '').strip()
    if q:
        suppliers = suppliers.filter(
            Q(name__icontains=q) |
            Q(supplier_code__icontains=q) |
            Q(mobile__icontains=q) |
            Q(gstin__icontains=q) |
            Q(contact_person__icontains=q)
        )

    status_filter = request.GET.get('status')
    if status_filter == 'active':
        suppliers = suppliers.filter(is_active=True)
    elif status_filter == 'inactive':
        suppliers = suppliers.filter(is_active=False)

    balance_filter = request.GET.get('balance')
    if balance_filter == 'payable':
        suppliers = suppliers.filter(current_balance__gt=0)
    elif balance_filter == 'advance':
        suppliers = suppliers.filter(current_balance__lt=0)
    elif balance_filter == 'zero':
        suppliers = suppliers.filter(current_balance=0)

    paginator = Paginator(suppliers, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    total_payable = Supplier.objects.filter(tenant=tenant, current_balance__gt=0).aggregate(t=Sum('current_balance'))['t'] or Decimal('0.00')
    total_advance = Supplier.objects.filter(tenant=tenant, current_balance__lt=0).aggregate(t=Sum('current_balance'))['t'] or Decimal('0.00')

    context = {
        'page_obj': page_obj,
        'total_payable': total_payable,
        'total_advance': abs(total_advance),
        'search_query': q,
        'balance_filter': balance_filter,
    }
    return render(request, 'purchases/supplier_list.html', context)


@login_required
def supplier_create_view(request):
    """Register a new supplier / party."""
    tenant = request.tenant
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            supplier = form.save(commit=False)
            supplier.tenant = tenant
            supplier.save()
            messages.success(request, f"Supplier '{supplier.name}' ({supplier.supplier_code}) registered successfully.")
            return redirect('purchases:supplier_detail', pk=supplier.pk)
    else:
        form = SupplierForm()

    return render(request, 'purchases/supplier_form.html', {'form': form, 'title': 'Register New Supplier'})


@login_required
def supplier_edit_view(request, pk):
    """Edit supplier details."""
    tenant = request.tenant
    supplier = get_object_or_404(Supplier, pk=pk, tenant=tenant)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            supplier = form.save()
            messages.success(request, f"Supplier '{supplier.name}' updated successfully.")
            return redirect('purchases:supplier_detail', pk=supplier.pk)
    else:
        form = SupplierForm(instance=supplier)

    return render(request, 'purchases/supplier_form.html', {'form': form, 'supplier': supplier, 'title': f"Edit Supplier: {supplier.name}"})


@login_required
def supplier_detail_view(request, pk):
    """Comprehensive supplier profile, outstanding summary, and recent activity."""
    tenant = request.tenant
    supplier = get_object_or_404(Supplier, pk=pk, tenant=tenant)

    recent_invoices = supplier.purchases.order_by('-purchase_date')[:6]
    recent_payments = supplier.payments.order_by('-payment_date')[:6]
    recent_ledger = supplier.ledger_entries.order_by('-entry_date', '-id')[:10]

    context = {
        'supplier': supplier,
        'recent_invoices': recent_invoices,
        'recent_payments': recent_payments,
        'recent_ledger': recent_ledger,
    }
    return render(request, 'purchases/supplier_detail.html', context)


@login_required
def supplier_ledger_view(request, pk):
    """Full statement of account / party ledger for a supplier."""
    tenant = request.tenant
    supplier = get_object_or_404(Supplier, pk=pk, tenant=tenant)

    entries = supplier.ledger_entries.order_by('entry_date', 'id')

    date_from = request.GET.get('from')
    date_to = request.GET.get('to')
    if date_from:
        entries = entries.filter(entry_date__gte=date_from)
    if date_to:
        entries = entries.filter(entry_date__lte=date_to)

    total_credits = entries.aggregate(t=Sum('credit_amount'))['t'] or Decimal('0.00')
    total_debits = entries.aggregate(t=Sum('debit_amount'))['t'] or Decimal('0.00')

    company = CompanySettings.load(tenant=tenant)

    context = {
        'supplier': supplier,
        'entries': entries,
        'total_credits': total_credits,
        'total_debits': total_debits,
        'date_from': date_from,
        'date_to': date_to,
        'company': company,
    }
    return render(request, 'purchases/supplier_ledger.html', context)


# ==============================================================================
# 4. SUPPLIER PAYMENTS
# ==============================================================================

@login_required
def payment_list_view(request):
    """Register of outward supplier payments."""
    tenant = request.tenant
    payments = SupplierPayment.objects.filter(tenant=tenant).select_related('supplier', 'purchase_invoice', 'created_by').order_by('-payment_date', '-id')
    payments = apply_branch_filter(payments, request)

    q = (request.GET.get('q') or '').strip()
    if q:
        payments = payments.filter(
            Q(payment_number__icontains=q) |
            Q(supplier__name__icontains=q) |
            Q(reference__icontains=q)
        )

    supplier_id = request.GET.get('supplier')
    if supplier_id:
        payments = payments.filter(supplier_id=supplier_id)

    paginator = Paginator(payments, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    suppliers = Supplier.objects.filter(tenant=tenant, is_active=True).order_by('name')

    context = {
        'page_obj': page_obj,
        'suppliers': suppliers,
        'selected_supplier': supplier_id,
        'search_query': q,
    }
    return render(request, 'purchases/payment_list.html', context)


@login_required
def payment_create_view(request):
    """Record an outward payment voucher to a supplier."""
    tenant = request.tenant
    supplier_id = request.GET.get('supplier')
    invoice_id = request.GET.get('invoice')

    initial = {
        'payment_date': timezone.localdate(),
    }
    if supplier_id:
        initial['supplier'] = supplier_id
    if invoice_id:
        inv = PurchaseInvoice.objects.filter(pk=invoice_id, tenant=tenant).first()
        if inv:
            initial['supplier'] = inv.supplier_id
            initial['purchase_invoice'] = inv.pk
            initial['amount'] = inv.balance_amount

    if request.method == 'POST':
        form = SupplierPaymentForm(request.POST, tenant=tenant, supplier_id=supplier_id)
        if form.is_valid():
            try:
                payment = record_supplier_payment(
                    tenant=tenant,
                    supplier=form.cleaned_data['supplier'],
                    amount=form.cleaned_data['amount'],
                    payment_method=form.cleaned_data['payment_method'],
                    purchase_invoice=form.cleaned_data['purchase_invoice'],
                    branch=getattr(request, 'branch', None),
                    user=request.user,
                    reference=form.cleaned_data.get('reference', ''),
                    bank_name=form.cleaned_data.get('bank_name', ''),
                    notes=form.cleaned_data.get('notes', ''),
                    payment_date=form.cleaned_data.get('payment_date')
                )
                messages.success(request, f"Payment #{payment.payment_number} of ₹{payment.amount:,.2f} recorded successfully.")
                return redirect('purchases:payment_receipt', pk=payment.pk)
            except ValidationError as e:
                form.add_error(None, e)
    else:
        form = SupplierPaymentForm(tenant=tenant, supplier_id=supplier_id, initial=initial)

    return render(request, 'purchases/payment_form.html', {'form': form})


@login_required
def payment_receipt_view(request, pk):
    """Printable Payment Voucher."""
    tenant = request.tenant
    payment = get_object_or_404(SupplierPayment.objects.select_related('supplier', 'purchase_invoice', 'created_by'), pk=pk, tenant=tenant)
    company = CompanySettings.load(tenant=tenant)

    context = {
        'payment': payment,
        'company': company,
    }
    return render(request, 'purchases/payment_receipt.html', context)


@login_required
@require_POST
def payment_cancel_view(request, pk):
    """Auditable payment cancellation."""
    tenant = request.tenant
    payment = get_object_or_404(SupplierPayment, pk=pk, tenant=tenant)
    reason = request.POST.get('reason', 'Payment cancelled').strip()
    try:
        cancel_supplier_payment(payment.pk, user=request.user, reason=reason)
        messages.success(request, f"Payment #{payment.payment_number} cancelled and reversed.")
    except ValidationError as e:
        messages.error(request, f"Cancellation failed: {e}")
    return redirect('purchases:payment_list')


# ==============================================================================
# 5. PURCHASE RETURNS & DEBIT NOTES
# ==============================================================================

@login_required
def return_list_view(request):
    """Register of all purchase returns / debit notes."""
    tenant = request.tenant
    returns = PurchaseReturn.objects.filter(tenant=tenant).select_related('supplier', 'original_invoice', 'created_by').order_by('-return_date', '-id')
    returns = apply_branch_filter(returns, request)

    q = (request.GET.get('q') or '').strip()
    if q:
        returns = returns.filter(
            Q(return_number__icontains=q) |
            Q(original_invoice__purchase_number__icontains=q) |
            Q(supplier__name__icontains=q)
        )

    paginator = Paginator(returns, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'search_query': q,
    }
    return render(request, 'purchases/return_list.html', context)


@login_required
def return_create_view(request, invoice_id):
    """Form to return specific items from a confirmed purchase invoice."""
    tenant = request.tenant
    invoice = get_object_or_404(PurchaseInvoice, pk=invoice_id, tenant=tenant)

    if invoice.status not in ['CONFIRMED', 'PARTIALLY_PAID', 'PAID']:
        messages.error(request, "Returns can only be created against confirmed purchase invoices.")
        return redirect('purchases:purchase_detail', pk=invoice.pk)

    eligible_items = invoice.items.filter(returned_quantity__lt=F('quantity')).select_related('inventory_item')
    if not eligible_items.exists():
        messages.warning(request, f"All items on Invoice #{invoice.purchase_number} have already been fully returned.")
        return redirect('purchases:purchase_detail', pk=invoice.pk)

    if request.method == 'POST':
        item_ids = request.POST.getlist('item_id[]')
        return_quantities = request.POST.getlist('return_quantity[]')
        return_weights = request.POST.getlist('return_weight[]')
        item_reasons = request.POST.getlist('item_reason[]')
        main_reason = request.POST.get('main_reason', 'Defective / Purity Issue')
        adj_mode = request.POST.get('adjustment_mode', 'REDUCE_INVOICE_BALANCE')
        notes = request.POST.get('notes', '')

        return_items_data = []
        for i in range(len(item_ids)):
            try:
                qty = int(return_quantities[i])
            except (ValueError, TypeError):
                qty = 0

            if qty > 0:
                wt = return_weights[i] if i < len(return_weights) else 0
                r = item_reasons[i] if i < len(item_reasons) else main_reason
                return_items_data.append({
                    'item_id': item_ids[i],
                    'quantity': qty,
                    'weight': wt,
                    'reason': r
                })

        try:
            purchase_return = process_purchase_return(
                invoice_id=invoice.pk,
                return_items_data=return_items_data,
                reason=main_reason,
                adjustment_mode=adj_mode,
                user=request.user,
                notes=notes
            )
            messages.success(request, f"Debit Note #{purchase_return.return_number} generated successfully! Stock and accounts updated.")
            return redirect('purchases:return_detail', pk=purchase_return.pk)
        except ValidationError as e:
            messages.error(request, f"Unable to process return: {e}")

    context = {
        'invoice': invoice,
        'eligible_items': eligible_items,
    }
    return render(request, 'purchases/return_form.html', context)


@login_required
def return_detail_view(request, pk):
    """Printable Purchase Return / Debit Note voucher."""
    tenant = request.tenant
    purchase_return = get_object_or_404(
        PurchaseReturn.objects.select_related('supplier', 'original_invoice', 'created_by'),
        pk=pk,
        tenant=tenant
    )
    items = purchase_return.return_items.select_related('purchase_item').all()
    company = CompanySettings.load(tenant=tenant)

    context = {
        'purchase_return': purchase_return,
        'items': items,
        'company': company,
    }
    return render(request, 'purchases/return_detail.html', context)


# ==============================================================================
# 6. REPORTS & EXPORTS
# ==============================================================================

@login_required
def reports_view(request):
    """
    Comprehensive reporting center for the Purchase Management Module.
    Supports 8 report types:
    1. register: Purchase Inward Register
    2. supplier: Supplier-wise Procurement
    3. item: Category & Item-wise Breakdown
    4. metal: Metal & Purity Breakdown
    5. branch: Branch-wise Comparison
    6. outstanding: Accounts Payable Outstanding Aging
    7. payments: Outward Payments Register
    8. tax: GST Input Credit Breakdown (CGST, SGST, IGST)
    """
    tenant = request.tenant
    report_type = request.GET.get('report', 'register')
    date_from = request.GET.get('from', '')
    date_to = request.GET.get('to', '')

    today = timezone.localdate()
    if not date_from:
        date_from = str(today.replace(day=1))
    if not date_to:
        date_to = str(today)

    invoices = PurchaseInvoice.objects.filter(tenant=tenant).exclude(status='CANCELLED')
    invoices = apply_branch_filter(invoices, request)

    if date_from:
        invoices = invoices.filter(purchase_date__gte=date_from)
    if date_to:
        invoices = invoices.filter(purchase_date__lte=date_to)

    report_data = {}

    if report_type == 'register':
        report_data['rows'] = invoices.select_related('supplier', 'branch').order_by('purchase_date')
        report_data['summary'] = invoices.aggregate(
            total_qty=Sum('total_quantity'),
            total_gw=Sum('total_gross_weight'),
            total_nw=Sum('total_net_weight'),
            total_fw=Sum('total_fine_weight'),
            total_subtotal=Sum('subtotal'),
            total_tax=Sum('total_tax_amount'),
            total_grand=Sum('grand_total'),
            total_paid=Sum('amount_paid'),
            total_balance=Sum('balance_amount'),
        )

    elif report_type == 'supplier':
        report_data['rows'] = Supplier.objects.filter(tenant=tenant).annotate(
            bills_count=Count('purchases', filter=Q(purchases__purchase_date__gte=date_from, purchases__purchase_date__lte=date_to, purchases__status__in=['CONFIRMED', 'PARTIALLY_PAID', 'PAID'])),
            procurement_total=Sum('purchases__grand_total', filter=Q(purchases__purchase_date__gte=date_from, purchases__purchase_date__lte=date_to, purchases__status__in=['CONFIRMED', 'PARTIALLY_PAID', 'PAID'])),
            paid_total=Sum('purchases__amount_paid', filter=Q(purchases__purchase_date__gte=date_from, purchases__purchase_date__lte=date_to, purchases__status__in=['CONFIRMED', 'PARTIALLY_PAID', 'PAID'])),
        ).filter(procurement_total__gt=0).order_by('-procurement_total')

    elif report_type == 'metal':
        items = PurchaseItem.objects.filter(purchase__in=invoices)
        report_data['rows'] = items.values('metal_type', 'purity').annotate(
            total_pcs=Sum('quantity'),
            total_gross=Sum('gross_weight'),
            total_net=Sum('net_weight'),
            total_fine=Sum('fine_weight'),
            total_value=Sum('line_total')
        ).order_by('metal_type', 'purity')

    elif report_type == 'outstanding':
        report_data['rows'] = Supplier.objects.filter(tenant=tenant, current_balance__gt=0).order_by('-current_balance')
        report_data['total_outstanding'] = report_data['rows'].aggregate(t=Sum('current_balance'))['t'] or Decimal('0.00')

    elif report_type == 'payments':
        payments = SupplierPayment.objects.filter(tenant=tenant, is_cancelled=False)
        payments = apply_branch_filter(payments, request)
        if date_from:
            payments = payments.filter(payment_date__gte=date_from)
        if date_to:
            payments = payments.filter(payment_date__lte=date_to)
        report_data['rows'] = payments.select_related('supplier', 'purchase_invoice').order_by('payment_date')
        report_data['total_amount'] = payments.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    elif report_type == 'tax':
        report_data['rows'] = invoices.select_related('supplier').order_by('purchase_date')
        report_data['summary'] = invoices.aggregate(
            taxable=Sum('subtotal'),
            cgst=Sum('cgst_amount'),
            sgst=Sum('sgst_amount'),
            igst=Sum('igst_amount'),
            total_tax=Sum('total_tax_amount'),
            grand=Sum('grand_total')
        )

    branches = get_tenant_branches(request)

    context = {
        'report_type': report_type,
        'report_data': report_data,
        'date_from': date_from,
        'date_to': date_to,
        'branches': branches,
        'selected_branch': request.GET.get('branch', ''),
    }
    return render(request, 'purchases/reports.html', context)


@login_required
def reports_export_csv_view(request):
    """Export selected purchase report as CSV attachment."""
    tenant = request.tenant
    report_type = request.GET.get('report', 'register')
    date_from = request.GET.get('from', '')
    date_to = request.GET.get('to', '')

    invoices = PurchaseInvoice.objects.filter(tenant=tenant).exclude(status='CANCELLED')
    invoices = apply_branch_filter(invoices, request)
    if date_from:
        invoices = invoices.filter(purchase_date__gte=date_from)
    if date_to:
        invoices = invoices.filter(purchase_date__lte=date_to)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="Purchase_Report_{report_type}_{timezone.localdate()}.csv"'

    writer = csv.writer(response)

    if report_type == 'register':
        writer.writerow(['Purchase #', 'Date', 'Supplier', 'Invoice #', 'Type', 'Gross Wt (g)', 'Net Wt (g)', 'Subtotal', 'GST', 'Grand Total', 'Paid', 'Balance', 'Status'])
        for inv in invoices.select_related('supplier'):
            writer.writerow([
                inv.purchase_number,
                inv.purchase_date,
                inv.supplier.name,
                inv.supplier_invoice_number or 'N/A',
                inv.get_purchase_type_display(),
                inv.total_gross_weight,
                inv.total_net_weight,
                inv.subtotal,
                inv.total_tax_amount,
                inv.grand_total,
                inv.amount_paid,
                inv.balance_amount,
                inv.get_status_display()
            ])

    elif report_type == 'tax':
        writer.writerow(['Purchase #', 'Date', 'Supplier', 'GSTIN', 'Taxable Amt', 'CGST Amt', 'SGST Amt', 'IGST Amt', 'Total GST', 'Grand Total'])
        for inv in invoices.select_related('supplier'):
            writer.writerow([
                inv.purchase_number,
                inv.purchase_date,
                inv.supplier.name,
                inv.supplier.gstin or 'Unregistered',
                inv.subtotal,
                inv.cgst_amount,
                inv.sgst_amount,
                inv.igst_amount,
                inv.total_tax_amount,
                inv.grand_total
            ])

    elif report_type == 'outstanding':
        writer.writerow(['Supplier Code', 'Supplier Name', 'Mobile', 'GSTIN', 'Current Outstanding Payable (₹)'])
        for sup in Supplier.objects.filter(tenant=tenant, current_balance__gt=0).order_by('-current_balance'):
            writer.writerow([
                sup.supplier_code,
                sup.name,
                sup.mobile,
                sup.gstin or '',
                sup.current_balance
            ])

    return response


# ==============================================================================
# 7. PURCHASE SETTINGS
# ==============================================================================

@login_required
def settings_view(request):
    """Store-level configuration parameters for the purchase module."""
    tenant = request.tenant
    setting_obj = PurchaseSetting.load(tenant=tenant)

    if request.method == 'POST':
        form = PurchaseSettingForm(request.POST, instance=setting_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Purchase Module settings saved successfully.")
            return redirect('purchases:settings')
    else:
        form = PurchaseSettingForm(instance=setting_obj)

    return render(request, 'purchases/settings.html', {'form': form})


# ==============================================================================
# 8. AJAX ENDPOINTS
# ==============================================================================

@login_required
@require_GET
def api_supplier_details(request, pk):
    """Return JSON details of a supplier for dynamic form updates."""
    tenant = request.tenant
    supplier = get_object_or_404(Supplier, pk=pk, tenant=tenant)
    pending_invoices = list(supplier.purchases.filter(
        status__in=['CONFIRMED', 'PARTIALLY_PAID'],
        balance_amount__gt=0
    ).values('id', 'purchase_number', 'purchase_date', 'grand_total', 'balance_amount'))

    data = {
        'id': supplier.id,
        'name': supplier.name,
        'supplier_code': supplier.supplier_code,
        'mobile': supplier.mobile,
        'gstin': supplier.gstin,
        'state': supplier.state,
        'state_code': supplier.state_code,
        'current_balance': float(supplier.current_balance),
        'pending_invoices': pending_invoices,
    }
    return JsonResponse(data)


@login_required
@require_GET
def api_current_metal_rates(request):
    """Return today's gold and silver rates for auto-filling item rates."""
    tenant = request.tenant
    today = timezone.localdate()
    rates = MetalRate.objects.filter(tenant=tenant, date=today)
    data = {}
    for r in rates:
        data[f"{r.metal_type}_{r.purity}"] = float(r.rate_per_gram)
    return JsonResponse(data)
