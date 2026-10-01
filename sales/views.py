import datetime
from datetime import timedelta
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from .models import Sale, Enquiry
from .forms import PaymentForm, SaleForm, EnquiryForm
from .whatsapp import get_whatsapp_context_for_sale
from inventory.models import JewelleryItem
from inventory import stock


# ==============================================================================
# SALES VIEWS
# ==============================================================================

@login_required
def sale_list(request):
    """List all sales records with search and payment method filters."""
    sales = Sale.objects.select_related('customer', 'jewellery_item').order_by('-sale_date')

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
    }
    return render(request, 'sales/sales_report.html', context)


@login_required
def payment_add(request, pk):
    """Record a payment against a sale and redirect back to its detail page.

    The Add Payment form lives on the sale detail page and posts here.
    GET simply returns to the sale; POST validates through PaymentForm
    (amount > 0 and <= remaining due) before saving.
    """
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    from .forms import PaymentForm
    from .models import Sale

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

