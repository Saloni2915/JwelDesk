import datetime
from datetime import timedelta
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.http import JsonResponse
from django.utils import timezone
from .models import Sale, Payment, Enquiry, OldGoldTransaction, generate_old_gold_number
from .forms import (
    PaymentForm, SaleForm, EnquiryForm,
    OldGoldExchangeForm, OldGoldBuybackForm, OldGoldCancelForm
)
from .whatsapp import get_whatsapp_context_for_sale
from inventory.models import JewelleryItem
from inventory import stock, pricing
from team.permissions import require_permission, has_module_perm
from accounts.models import CompanySettings


# ==============================================================================
# SALES VIEWS
# ==============================================================================

@login_required
def sale_list(request):
    """List all sales records with search and payment method filters."""
    sales = (
        Sale.objects.select_related('customer', 'jewellery_item')
        .prefetch_related('payments')
        .order_by('-sale_date')
    )

    # Search (Customer name or item name/code/tag/design/HUID)
    q = request.GET.get('q', '').strip()
    if q:
        sales = sales.filter(
            Q(customer__name__icontains=q) |
            Q(jewellery_item__name__icontains=q) |
            Q(jewellery_item__tag_number__icontains=q) |
            Q(jewellery_item__item_code__icontains=q) |
            Q(jewellery_item__design_code__icontains=q) |
            Q(jewellery_item__huid__icontains=q)
        )

    # Payment method filter
    payment = request.GET.get('payment', '').strip()
    if payment:
        sales = sales.filter(payment_method=payment)

    # Pagination
    paginator = Paginator(sales, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'sales': page_obj,
        'page_obj': page_obj,
        'payment_choices': Sale.PAYMENT_METHODS,
        'selected_q': q,
        'selected_payment': payment,
    }
    return render(request, 'sales/sale_list.html', context)


@login_required
def sale_add(request):
    """Create a new sale with transaction safety and automatic status update."""
    initial_data = {}
    # Pre-select customer or item if passed in GET params
    if 'customer' in request.GET:
        initial_data['customer'] = request.GET.get('customer')
    if 'item' in request.GET:
        initial_data['jewellery_item'] = request.GET.get('item')
        try:
            item_obj = JewelleryItem.objects.get(pk=request.GET.get('item'))
            initial_data['sale_price'] = request.GET.get('price') or item_obj.selling_price
        except JewelleryItem.DoesNotExist:
            pass

    if request.method == 'POST':
        form = SaleForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                sale = form.save(commit=False)
                item = sale.jewellery_item

                # Business rule validation: the item must still be in stock.
                # Re-fetch with select_for_update to prevent race conditions
                locked_item = JewelleryItem.objects.select_for_update().get(pk=item.pk)
                if locked_item.status == 'Sold' or locked_item.quantity <= 0:
                    messages.error(request, f"Cannot complete sale: '{locked_item.name}' ({locked_item.item_code}) is already SOLD.")
                    return render(request, 'sales/sale_form.html', {'form': form, 'page_title': 'Create Sale'})

                # Save sale
                sale.save()

                # Reduce inventory: status/quantity and the stock movement are
                # handled by the inventory stock service (single source of
                # truth), so the stock can never be reduced twice for one sale.
                movement = stock.record_sale(locked_item, sale, user=request.user)

                if movement.stock_after == 0:
                    messages.success(request, f"Sale #{sale.id} completed successfully! Item '{locked_item.name}' marked as Sold.")
                else:
                    messages.success(
                        request,
                        f"Sale #{sale.id} completed successfully! '{locked_item.name}' stock "
                        f"reduced to {movement.stock_after}.")
                return redirect('sale_detail', pk=sale.pk)
    else:
        form = SaleForm(initial=initial_data)

    context = {
        'form': form,
        'page_title': 'Create Sale',
    }
    return render(request, 'sales/sale_form.html', context)


@login_required
def sale_detail(request, pk):
    """View details / receipt for a sale."""
    sale = get_object_or_404(Sale.objects.select_related('customer', 'jewellery_item', 'jewellery_item__category'), pk=pk)
    context = {
        'sale': sale,
        'payments': sale.payments.all(),          # newest first (Payment.Meta)
        'payment_form': PaymentForm(sale=sale),   # renders the Add Payment modal
    }
    context.update(get_whatsapp_context_for_sale(sale))
    return render(request, 'sales/sale_detail.html', context)


@login_required
def sale_invoice_pdf(request, pk):
    """Download the sale's invoice as a PDF (generated from stored data)."""
    from django.http import HttpResponse

    from .invoice_pdf import build_invoice_pdf

    sale = get_object_or_404(
        Sale.objects.select_related('customer', 'jewellery_item'), pk=pk)
    pdf_bytes = build_invoice_pdf(sale)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f'INV-{sale.pk:05d}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ==============================================================================
# ENQUIRY VIEWS
# ==============================================================================

@login_required
def enquiry_list(request):
    """List enquiries with search, status and date filters."""
    enquiries = Enquiry.objects.select_related('customer', 'category').order_by('-created_at')

    # Search (Customer name or interested item)
    q = request.GET.get('q', '').strip()
    if q:
        enquiries = enquiries.filter(
            Q(customer__name__icontains=q) |
            Q(interested_item__icontains=q)
        )

    # Status filter
    status = request.GET.get('status', '').strip()
    if status:
        enquiries = enquiries.filter(status=status)

    # Follow-up date filter (e.g. today, overdue, upcoming)
    followup = request.GET.get('followup', '').strip()
    from django.utils import timezone
    today = timezone.localdate()

    if followup == 'today':
        enquiries = enquiries.filter(next_followup_date=today)
    elif followup == 'upcoming':
        enquiries = enquiries.filter(next_followup_date__gt=today)
    elif followup == 'overdue':
        enquiries = enquiries.filter(next_followup_date__lt=today).exclude(status__in=['Purchased', 'Closed'])

    # Pagination
    paginator = Paginator(enquiries, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'enquiries': page_obj,
        'page_obj': page_obj,
        'status_choices': Enquiry.STATUS_CHOICES,
        'selected_q': q,
        'selected_status': status,
        'selected_followup': followup,
    }
    return render(request, 'sales/enquiry_list.html', context)


@login_required
def enquiry_add(request):
    """Add a new enquiry."""
    initial_data = {}
    if 'customer' in request.GET:
        initial_data['customer'] = request.GET.get('customer')

    if request.method == 'POST':
        form = EnquiryForm(request.POST)
        if form.is_valid():
            enquiry = form.save()
            messages.success(request, f"Enquiry for '{enquiry.customer.name}' recorded successfully.")
            return redirect('enquiry_detail', pk=enquiry.pk)
    else:
        form = EnquiryForm(initial=initial_data)

    context = {
        'form': form,
        'page_title': 'Add Enquiry',
        'is_edit': False,
    }
    return render(request, 'sales/enquiry_form.html', context)


@login_required
def enquiry_detail(request, pk):
    """View enquiry details."""
    enquiry = get_object_or_404(Enquiry.objects.select_related('customer', 'category'), pk=pk)
    context = {
        'enquiry': enquiry,
    }
    return render(request, 'sales/enquiry_detail.html', context)


@login_required
def enquiry_edit(request, pk):
    """Edit an enquiry."""
    enquiry = get_object_or_404(Enquiry, pk=pk)
    if request.method == 'POST':
        form = EnquiryForm(request.POST, instance=enquiry)
        if form.is_valid():
            enquiry = form.save()
            messages.success(request, f"Enquiry updated successfully.")
            return redirect('enquiry_detail', pk=enquiry.pk)
    else:
        form = EnquiryForm(instance=enquiry)

    context = {
        'form': form,
        'enquiry': enquiry,
        'page_title': f"Edit Enquiry #{enquiry.id}",
        'is_edit': True,
    }
    return render(request, 'sales/enquiry_form.html', context)


@login_required
def enquiry_delete(request, pk):
    """Delete an enquiry."""
    enquiry = get_object_or_404(Enquiry, pk=pk)
    if request.method == 'POST':
        enquiry.delete()
        messages.success(request, "Enquiry deleted successfully.")
        return redirect('enquiry_list')

    context = {
        'enquiry': enquiry,
    }
    return render(request, 'sales/enquiry_confirm_delete.html', context)


# ==============================================================================
# REPORTS VIEWS
# ==============================================================================

SALES_REPORT_PER_PAGE = 15
REPORT_PERIOD_CHOICES = ('today', 'week', 'month', 'custom')


def parse_report_date(value):
    """Return a `datetime.date` parsed from a YYYY-MM-DD string, or None."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value.strip())
    except (ValueError, AttributeError, TypeError):
        return None


def get_sales_report_range(period, start_raw, end_raw, today):
    """
    Resolve a report preset (or a validated custom range) into
    (start_date, end_date) date bounds. Returns (None, None) on invalid input.
    """
    if period == 'today':
        return today, today

    if period == 'week':
        # This week: Monday of the current week through today.
        return today - timedelta(days=today.weekday()), today

    if period in ('month',):
        # This month: the first of the month through today.
        return today.replace(day=1), today

    if period == 'custom':
        start_date = parse_report_date(start_raw)
        end_date = parse_report_date(end_raw)
        if start_date is None or end_date is None:
            return None, None
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        return start_date, end_date

    return None, None


@login_required
def sales_report(request):
    """Sales report with date presets (today/week/month/custom) and range totals."""
    today = timezone.localdate()
    period = request.GET.get('period', 'today').strip().lower()
    if period not in REPORT_PERIOD_CHOICES:
        period = 'today'

    start_raw = request.GET.get('start_date', '')
    end_raw = request.GET.get('end_date', '')
    start_date, end_date = get_sales_report_range(period, start_raw, end_raw, today)

    if start_date is None or end_date is None:
        messages.error(
            request,
            "Please enter a valid custom date range (YYYY-MM-DD) to view the sales report."
        )
        return redirect('sales_report')

    sales = (
        Sale.objects
        .select_related('customer', 'jewellery_item')
        .prefetch_related('payments')
        .filter(sale_date__date__gte=start_date, sale_date__date__lte=end_date)
        .order_by('-sale_date')
    )

    # Totals for the selected range, aggregated in the database.
    totals = sales.aggregate(
        total_amount=Sum('sale_price'),
        sales_count=Count('id'),
        items_sold=Count('jewellery_item'),
        average_sale_value=Avg('sale_price'),
    )
    total_amount = totals['total_amount'] or Decimal('0.00')
    sales_count = totals['sales_count'] or 0
    items_sold = totals['items_sold'] or 0
    average_sale_value = totals['average_sale_value'] or Decimal('0.00')

    # Old gold transactions in date range (combined in 1 single aggregate query)
    old_gold_aggr = OldGoldTransaction.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
        status=OldGoldTransaction.STATUS_COMPLETED
    ).aggregate(
        exchange_count=Count('id', filter=Q(transaction_type=OldGoldTransaction.TYPE_EXCHANGE)),
        exchange_val=Sum('final_value', filter=Q(transaction_type=OldGoldTransaction.TYPE_EXCHANGE)),
        exchange_net_wt=Sum('net_weight', filter=Q(transaction_type=OldGoldTransaction.TYPE_EXCHANGE)),
        buyback_count=Count('id', filter=Q(transaction_type=OldGoldTransaction.TYPE_BUYBACK)),
        buyback_val=Sum('final_value', filter=Q(transaction_type=OldGoldTransaction.TYPE_BUYBACK)),
        buyback_net_wt=Sum('net_weight', filter=Q(transaction_type=OldGoldTransaction.TYPE_BUYBACK)),
    )
    exchange_count = old_gold_aggr['exchange_count'] or 0
    exchange_value = old_gold_aggr['exchange_val'] or Decimal('0.00')
    exchange_net_wt = old_gold_aggr['exchange_net_wt'] or Decimal('0.000')
    buyback_count = old_gold_aggr['buyback_count'] or 0
    buyback_payout = old_gold_aggr['buyback_val'] or Decimal('0.00')
    buyback_net_wt = old_gold_aggr['buyback_net_wt'] or Decimal('0.000')
    total_old_gold_weight = exchange_net_wt + buyback_net_wt

    # Pagination (keeps the selected range on every page link).
    paginator = Paginator(sales, SALES_REPORT_PER_PAGE)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Sales Report',
        'report_start': start_date,
        'report_end': end_date,
        'selected_period': period,
        'selected_start_date': start_date.isoformat(),
        'selected_end_date': end_date.isoformat(),
        'sales': page_obj,
        'page_obj': page_obj,
        'total_amount': total_amount,
        'sales_count': sales_count,
        'items_sold': items_sold,
        'average_sale_value': average_sale_value,
        'exchange_count': exchange_count,
        'exchange_value': exchange_value,
        'buyback_count': buyback_count,
        'buyback_payout': buyback_payout,
        'total_old_gold_weight': total_old_gold_weight,
    }
    return render(request, 'sales/sales_report.html', context)


@login_required
def payment_add(request, pk):
    """Record a payment against a sale and redirect back to its detail page.

    The Add Payment form lives on the sale detail page and posts here.
    GET simply returns to the sale; POST validates through PaymentForm
    (amount > 0 and <= remaining due) before saving.
    """
    sale = get_object_or_404(Sale, pk=pk)
    if request.method != 'POST':
        return redirect('sale_detail', pk=sale.pk)

    form = PaymentForm(request.POST, sale=sale)
    if form.is_valid():
        payment = form.save(commit=False)
        payment.sale = sale
        payment.save()
        messages.success(
            request,
            f'Payment of Rs. {payment.amount:,.2f} recorded. '
            f'Due: Rs. {sale.due_amount:,.2f} ({sale.payment_status}).')
        return redirect('sale_detail', pk=sale.pk)

    errors = '; '.join(
        ' '.join(errs) if field == '__all__' else f'{field}: {" ".join(errs)}'
        for field, errs in form.errors.items())
    messages.error(request, f'Payment not recorded — {errors}')
    return redirect('sale_detail', pk=sale.pk)


# ==============================================================================
# OLD GOLD EXCHANGE & BUYBACK VIEWS
# ==============================================================================

@login_required
@require_permission('sales', 'view')
def old_gold_list(request):
    """
    Transaction history for Old Gold Exchanges and Buybacks.
    Provides searching, type filtering, status filtering, and aggregate summaries.
    """
    transactions = OldGoldTransaction.objects.select_related(
        'customer', 'new_sale', 'new_sale__jewellery_item', 'processed_by'
    ).order_by('-created_at', '-id')

    # Search (Customer name, mobile, item description, voucher number)
    q = request.GET.get('q', '').strip()
    if q:
        transactions = transactions.filter(
            Q(customer__name__icontains=q) |
            Q(customer__mobile__icontains=q) |
            Q(transaction_number__icontains=q) |
            Q(item_description__icontains=q) |
            Q(new_sale__jewellery_item__name__icontains=q) |
            Q(new_sale__jewellery_item__tag_number__icontains=q)
        )

    # Transaction type filter (Exchange vs Buyback)
    tx_type = request.GET.get('type', '').strip()
    if tx_type in [OldGoldTransaction.TYPE_EXCHANGE, OldGoldTransaction.TYPE_BUYBACK]:
        transactions = transactions.filter(transaction_type=tx_type)

    # Status filter
    status = request.GET.get('status', '').strip()
    if status in [OldGoldTransaction.STATUS_COMPLETED, OldGoldTransaction.STATUS_CANCELLED]:
        transactions = transactions.filter(status=status)

    # Totals across all completed transactions
    completed_txs = OldGoldTransaction.objects.filter(status=OldGoldTransaction.STATUS_COMPLETED)
    total_val_all = completed_txs.aggregate(total=Sum('final_value'))['total'] or Decimal('0.00')
    total_net_wt_all = completed_txs.aggregate(total=Sum('net_weight'))['total'] or Decimal('0.000')
    exchange_count_all = completed_txs.filter(transaction_type=OldGoldTransaction.TYPE_EXCHANGE).count()
    buyback_count_all = completed_txs.filter(transaction_type=OldGoldTransaction.TYPE_BUYBACK).count()

    paginator = Paginator(transactions, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Old Gold Transactions',
        'transactions': page_obj,
        'page_obj': page_obj,
        'selected_q': q,
        'selected_type': tx_type,
        'selected_status': status,
        'total_val_all': total_val_all,
        'total_net_wt_all': total_net_wt_all,
        'exchange_count_all': exchange_count_all,
        'buyback_count_all': buyback_count_all,
        'type_choices': OldGoldTransaction.TYPE_CHOICES,
        'status_choices': OldGoldTransaction.STATUS_CHOICES,
    }
    return render(request, 'sales/old_gold_list.html', context)


@login_required
@require_permission('sales', 'add')
def old_gold_exchange_create(request):
    """
    Create an Old Gold Exchange transaction:
    - Calculates Old Gold Valuation using jewellery pricing engine conventions.
    - Sells new jewellery piece from showroom inventory.
    - Atomically reduces inventory, creates Sale, logs Exchange Payment credit, and records OldGoldTransaction.
    """
    initial_data = {}
    if 'customer' in request.GET:
        initial_data['customer'] = request.GET.get('customer')
    if 'item' in request.GET:
        initial_data['new_jewellery_item'] = request.GET.get('item')
        try:
            it = JewelleryItem.objects.get(pk=request.GET.get('item'))
            initial_data['new_sale_price'] = it.selling_price
        except JewelleryItem.DoesNotExist:
            pass

    if request.method == 'POST':
        form = OldGoldExchangeForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                # Re-fetch item with select_for_update
                new_item = form.cleaned_data['new_jewellery_item']
                locked_item = JewelleryItem.objects.select_for_update().get(pk=new_item.pk)
                if locked_item.status == 'Sold' or locked_item.quantity <= 0:
                    messages.error(request, f"Cannot exchange: '{locked_item.name}' ({locked_item.item_code}) is already SOLD.")
                    return render(request, 'sales/old_gold_exchange_form.html', {'form': form, 'page_title': 'Old Gold Exchange'})

                # Server-side calculation verification using Pricing Engine conventions
                raw_data = form.cleaned_data
                val = OldGoldTransaction.compute_valuation(
                    gross_weight=raw_data['gross_weight'],
                    stone_weight=raw_data.get('stone_weight') or Decimal('0.000'),
                    metal_type=raw_data.get('metal_type', 'Gold'),
                    purity=raw_data.get('purity', '22K'),
                    custom_purity_percent=raw_data.get('custom_purity_percent'),
                    applicable_rate=raw_data.get('applicable_rate'),
                    deduction_percent=raw_data.get('deduction_percent') or Decimal('0.00'),
                )

                new_price = raw_data['new_sale_price']
                diff_amount = new_price - val['final_value']
                tx_number = generate_old_gold_number(OldGoldTransaction.TYPE_EXCHANGE)

                # 1. Create Sale for new jewellery piece
                sale = Sale.objects.create(
                    customer=raw_data['customer'],
                    jewellery_item=locked_item,
                    sale_price=new_price,
                    sale_date=timezone.now(),
                    payment_method='Exchange',
                    notes=f"Exchange against Old Gold Voucher {tx_number}"
                )

                # 2. Safely deduct inventory piece using existing stock management
                stock.record_sale(locked_item, sale, user=request.user)

                # 3. Apply Old Gold Credit as Payment against Sale
                old_gold_credit = min(sale.sale_price, val['final_value'])
                Payment.objects.create(
                    sale=sale,
                    amount=old_gold_credit,
                    payment_method='Exchange',
                    reference=tx_number,
                    notes='Old Gold Exchange Credit'
                )

                # 4. If customer owes difference and paid at counter
                settlement_method = raw_data.get('settlement_payment_method')
                settlement_ref = raw_data.get('settlement_payment_reference') or ''
                if diff_amount > 0 and settlement_method:
                    Payment.objects.create(
                        sale=sale,
                        amount=diff_amount,
                        payment_method=settlement_method,
                        reference=settlement_ref,
                        notes='Settlement payment for exchange difference'
                    )

                # 5. Create OldGoldTransaction record
                og_tx = form.save(commit=False)
                og_tx.transaction_number = tx_number
                og_tx.transaction_type = OldGoldTransaction.TYPE_EXCHANGE
                og_tx.net_weight = val['net_weight']
                og_tx.purity_factor = val['purity_factor']
                og_tx.pure_weight = val['pure_weight']
                og_tx.effective_rate = val['effective_rate']
                og_tx.gross_valuation = val['gross_valuation']
                og_tx.deduction_amount = val['deduction_amount']
                og_tx.final_value = val['final_value']
                og_tx.inventory_status = 'Vault Stock'
                og_tx.new_sale = sale
                og_tx.new_item_price = new_price
                og_tx.difference_amount = diff_amount
                og_tx.payment_method = 'Adjusted in Sale'
                og_tx.payment_status = 'Paid' if (diff_amount <= 0 or settlement_method) else 'Pending'
                og_tx.status = OldGoldTransaction.STATUS_COMPLETED
                og_tx.processed_by = request.user
                og_tx.save()

                messages.success(
                    request,
                    f"Exchange {tx_number} completed successfully! "
                    f"New piece '{locked_item.name}' sold to {raw_data['customer'].name}. "
                    f"Old Gold Credit: Rs. {val['final_value']:,.2f}."
                )
                return redirect('old_gold_detail', pk=og_tx.pk)
    else:
        form = OldGoldExchangeForm(initial=initial_data)

    context = {
        'form': form,
        'page_title': 'Old Gold Exchange with New Jewellery',
    }
    return render(request, 'sales/old_gold_exchange_form.html', context)


@login_required
@require_permission('sales', 'add')
def old_gold_buyback_create(request):
    """
    Create an Outright Old Gold Buyback transaction (Cash/Bank payout to customer).
    - Calculates scrap valuation.
    - Records payout method and reference without performing real financial calls.
    - Stores scrap item in Vault Stock.
    """
    initial_data = {}
    if 'customer' in request.GET:
        initial_data['customer'] = request.GET.get('customer')

    if request.method == 'POST':
        form = OldGoldBuybackForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                raw_data = form.cleaned_data
                val = OldGoldTransaction.compute_valuation(
                    gross_weight=raw_data['gross_weight'],
                    stone_weight=raw_data.get('stone_weight') or Decimal('0.000'),
                    metal_type=raw_data.get('metal_type', 'Gold'),
                    purity=raw_data.get('purity', '22K'),
                    custom_purity_percent=raw_data.get('custom_purity_percent'),
                    applicable_rate=raw_data.get('applicable_rate'),
                    deduction_percent=raw_data.get('deduction_percent') or Decimal('0.00'),
                )
                tx_number = generate_old_gold_number(OldGoldTransaction.TYPE_BUYBACK)

                og_tx = form.save(commit=False)
                og_tx.transaction_number = tx_number
                og_tx.transaction_type = OldGoldTransaction.TYPE_BUYBACK
                og_tx.net_weight = val['net_weight']
                og_tx.purity_factor = val['purity_factor']
                og_tx.pure_weight = val['pure_weight']
                og_tx.effective_rate = val['effective_rate']
                og_tx.gross_valuation = val['gross_valuation']
                og_tx.deduction_amount = val['deduction_amount']
                og_tx.final_value = val['final_value']
                og_tx.inventory_status = 'Vault Stock'
                og_tx.difference_amount = -val['final_value']  # Outflow to customer
                og_tx.status = OldGoldTransaction.STATUS_COMPLETED
                og_tx.processed_by = request.user
                og_tx.save()

                messages.success(
                    request,
                    f"Buyback {tx_number} recorded successfully! "
                    f"Payout of Rs. {val['final_value']:,.2f} via {og_tx.payment_method} "
                    f"to {og_tx.customer.name}."
                )
                return redirect('old_gold_detail', pk=og_tx.pk)
    else:
        form = OldGoldBuybackForm(initial=initial_data)

    context = {
        'form': form,
        'page_title': 'Old Gold Outright Buyback',
    }
    return render(request, 'sales/old_gold_buyback_form.html', context)


@login_required
@require_permission('sales', 'view')
def old_gold_detail(request, pk):
    """
    Detailed view and printable valuation/exchange voucher for an Old Gold transaction.
    """
    transaction_obj = get_object_or_404(
        OldGoldTransaction.objects.select_related(
            'customer', 'new_sale', 'new_sale__jewellery_item',
            'processed_by', 'cancelled_by'
        ),
        pk=pk
    )
    company = CompanySettings.objects.first()
    cancel_form = OldGoldCancelForm()

    context = {
        'page_title': f"{transaction_obj.transaction_number} - {transaction_obj.get_transaction_type_display()}",
        'tx': transaction_obj,
        'company': company,
        'cancel_form': cancel_form,
    }
    return render(request, 'sales/old_gold_detail.html', context)


@login_required
@require_permission('sales', 'edit')
def old_gold_cancel(request, pk):
    """
    Safely cancel an Old Gold transaction with mandatory reason and audit logging.
    """
    transaction_obj = get_object_or_404(OldGoldTransaction, pk=pk)
    if request.method != 'POST':
        return redirect('old_gold_detail', pk=transaction_obj.pk)

    if transaction_obj.status == OldGoldTransaction.STATUS_CANCELLED:
        messages.error(request, f"Transaction {transaction_obj.transaction_number} is already cancelled.")
        return redirect('old_gold_detail', pk=transaction_obj.pk)

    form = OldGoldCancelForm(request.POST)
    if form.is_valid():
        reason = form.cleaned_data['cancellation_reason']
        with transaction.atomic():
            transaction_obj.cancel(user=request.user, reason=reason)
            if transaction_obj.new_sale:
                sale = transaction_obj.new_sale
                sale.notes += f"\n[CANCELLED] Linked Old Gold Exchange {transaction_obj.transaction_number} was cancelled by {request.user.username} on {timezone.now().strftime('%Y-%m-%d %H:%M')}: {reason}"
                sale.save(update_fields=['notes'])
        messages.warning(request, f"Transaction {transaction_obj.transaction_number} has been cancelled successfully.")
        return redirect('old_gold_detail', pk=transaction_obj.pk)

    messages.error(request, "Failed to cancel transaction: cancellation reason is required.")
    return redirect('old_gold_detail', pk=transaction_obj.pk)


@login_required
def old_gold_rate_api(request):
    """
    Helper API returning base rate and effective rate for metal type and purity.
    Used for seamless dynamic calculation on Old Gold forms.
    """
    metal_type = request.GET.get('metal_type', 'Gold').strip()
    purity = request.GET.get('purity', '22K').strip()
    custom_purity = request.GET.get('custom_purity', '').strip()

    base_rate = pricing.get_current_metal_rate(metal_type)
    if purity == 'Other' and custom_purity:
        p_factor = pricing.to_decimal(custom_purity) / Decimal('100.00')
    else:
        p_factor = pricing.parse_purity_factor(metal_type, purity)

    effective_rate = pricing.round_curr(base_rate * p_factor)
    return JsonResponse({
        'metal_type': metal_type,
        'purity': purity,
        'base_rate': float(base_rate),
        'purity_factor': float(p_factor),
        'effective_rate': float(effective_rate),
    })


