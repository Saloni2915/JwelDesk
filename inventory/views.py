import datetime
from decimal import Decimal, InvalidOperation

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum, Count, ProtectedError
from django.http import HttpResponse
from django.utils import timezone
from .models import JewelleryItem, Category, StockMovement, MetalRate
from .forms import JewelleryItemForm, CategoryForm, StockAdjustmentForm
from . import stock
from .import_utils import (
    generate_sample_csv,
    get_duplicate_rows,
    import_valid_rows,
    parse_csv_file,
    parse_excel_file,
    validate_import_rows,
)
from . import metal_prices


def landing_page(request):
    """Public software landing page for JewelDesk.

    Introduces the JewelDesk retail management platform to unauthenticated visitors.
    If an authenticated user visits '/' without '?view=landing', smoothly redirect
    them to their showroom dashboard cockpit.
    """
    if request.user.is_authenticated and request.GET.get('view') != 'landing':
        return redirect('dashboard')

    from django.conf import settings

    pdf_path = settings.BASE_DIR / 'JewelDesk_Complete_Project_Report.pdf'
    has_pdf = pdf_path.exists()

    context = {
        'has_pdf': has_pdf,
    }
    return render(request, 'landing.html', context)


@login_required
def dashboard(request):
    """Main dashboard view — Jewellery Business Cockpit.

    Every number is derived from existing rows (Sale/Payment/Customer/
    JewelleryItem/CustomOrder/Enquiry). No invented trends or percentages.
    Legacy context keys (total_items, available_items, sold_items,
    today_sales_amount, recent_sales, recent_enquiries, upcoming_followups,
    metal_prices) are preserved for backwards compatibility.
    """
    from django.db.models.functions import TruncDate

    today = timezone.localdate()

    total_items = JewelleryItem.objects.count()
    available_items = JewelleryItem.objects.filter(status='Available').count()
    sold_items = JewelleryItem.objects.filter(status='Sold').count()

    # Import sales & enquiries models dynamically to prevent circular imports if any
    from sales.models import Sale, Enquiry, Payment
    from customers.models import Customer
    from custom_orders.models import CustomOrder

    # ---- Sales aggregates -------------------------------------------------
    today_sales_data = Sale.objects.filter(sale_date__date=today).aggregate(
        total_amount=Sum('sale_price'),
        count=Count('id')
    )
    today_sales_amount = today_sales_data['total_amount'] or 0
    today_sales_count = today_sales_data['count'] or 0

    sales_totals = Sale.objects.aggregate(
        total_amount=Sum('sale_price'),
        count=Count('id'),
    )
    total_sales_amount = sales_totals['total_amount'] or 0
    total_sales_count = sales_totals['count'] or 0

    # Outstanding = total sales - total payments (never stored, always derived)
    payments_total = Payment.objects.aggregate(
        total=Sum('amount'))['total'] or 0
    from decimal import Decimal
    try:
        outstanding_amount = Decimal(total_sales_amount) - Decimal(payments_total)
    except Exception:
        outstanding_amount = 0
    if outstanding_amount < 0:
        outstanding_amount = Decimal('0.00')

    # ---- Inventory / customers -------------------------------------------
    summary = stock.inventory_summary()
    inventory_value = summary.get('inventory_value')
    low_stock_designs = summary.get('low_stock_designs', [])[:5]
    low_stock_design_count = summary.get('low_stock_design_count', 0)
    customer_count = Customer.objects.count()

    # Pending custom orders = everything not Delivered/Cancelled
    pending_orders_qs = (
        CustomOrder.objects.select_related('customer', 'category')
        .exclude(status__in=[CustomOrder.STATUS_DELIVERED,
                             CustomOrder.STATUS_CANCELLED])
        .order_by('-created_at')
    )
    pending_custom_orders_count = pending_orders_qs.count()
    pending_custom_orders = list(pending_orders_qs[:5])

    # ---- Recent sales (latest 5) ------------------------------------------
    recent_sales = Sale.objects.select_related('customer', 'jewellery_item').order_by('-sale_date')[:5]

    # ---- 7-day sales overview (CSS/SVG bars, no JS dependency) ------------
    week_start = today - datetime.timedelta(days=6)
    per_day = (
        Sale.objects.filter(sale_date__date__gte=week_start,
                            sale_date__date__lte=today)
        .annotate(day=TruncDate('sale_date'))
        .values('day')
        .annotate(total=Sum('sale_price'), count=Count('id'))
        .order_by('day')
    )
    by_day = {row['day']: row for row in per_day}
    sales_chart = []
    for i in range(7):
        day = week_start + datetime.timedelta(days=i)
        row = by_day.get(day)
        sales_chart.append({
            'date': day,
            'label': day.strftime('%a'),
            'day_num': day.strftime('%d'),
            'total': row['total'] if row else 0,
            'count': row['count'] if row else 0,
        })
    chart_max = max([float(r['total'] or 0) for r in sales_chart] + [0])
    for row in sales_chart:
        value = float(row['total'] or 0)
        row['pct'] = round((value / chart_max * 100)) if chart_max else 0

    # Recent enquiries (latest 5)
    recent_enquiries = Enquiry.objects.select_related('customer', 'category').order_by('-created_at')[:5]

    # Upcoming follow-ups (today or in future, ordered by followup date)
    upcoming_followups = Enquiry.objects.select_related('customer', 'category').filter(
        next_followup_date__gte=today
    ).exclude(
        status__in=['Purchased', 'Closed']
    ).order_by('next_followup_date')[:5]

    # Metal prices for the dashboard — cache-only read, never an API call.
    # The explicit "Refresh" action (POST metal_price_refresh) fetches new
    # rates, so the API is not hit on every page interaction.
    metal_price_snapshot = metal_prices.get_price_snapshot()

    context = {
        'page_title': 'Dashboard',
        # Legacy keys (kept for existing tests/templates)
        'total_items': total_items,
        'available_items': available_items,
        'sold_items': sold_items,
        'today_sales_amount': today_sales_amount,
        'recent_sales': recent_sales,
        'recent_enquiries': recent_enquiries,
        'upcoming_followups': upcoming_followups,
        'metal_prices': metal_price_snapshot,
        # Cockpit additions (all from existing data)
        'today_sales_count': today_sales_count,
        'total_sales_amount': total_sales_amount,
        'total_sales_count': total_sales_count,
        'outstanding_amount': outstanding_amount,
        'inventory_value': inventory_value,
        'low_stock_designs': low_stock_designs,
        'low_stock_design_count': low_stock_design_count,
        'customer_count': customer_count,
        'pending_custom_orders': pending_custom_orders,
        'pending_custom_orders_count': pending_custom_orders_count,
        'sales_chart': sales_chart,
        'sales_chart_max': chart_max,
        'sales_chart_start': week_start,
        'today': today,
    }
    return render(request, 'inventory/dashboard.html', context)


@login_required
def inventory_list(request):
    """List all jewellery items with search, filters and stock summary."""
    items = JewelleryItem.objects.select_related('category').all()
    categories = Category.objects.all()

    # Low-stock threshold: configurable per request (?threshold=) otherwise
    # taken from settings.INVENTORY_LOW_STOCK_THRESHOLD.
    threshold = stock.get_low_stock_threshold(request.GET.get('threshold'))

    # Search filter (tag_number, item_code, name, design_code, or huid)
    q = request.GET.get('q', '').strip()
    if q:
        items = items.filter(
            Q(tag_number__icontains=q) |
            Q(item_code__icontains=q) |
            Q(name__icontains=q) |
            Q(design_code__icontains=q) |
            Q(huid__icontains=q)
        )

    # Specific tag filter
    tag = (request.GET.get('tag_number') or request.GET.get('tag', '')).strip()
    if tag:
        items = items.filter(tag_number__icontains=tag)

    # Specific HUID filter
    huid = request.GET.get('huid', '').strip()
    if huid:
        items = items.filter(huid__icontains=huid)

    # Category filter
    category_id = request.GET.get('category', '').strip()
    if category_id:
        items = items.filter(category_id=category_id)

    # Metal type filter
    metal = request.GET.get('metal', '').strip()
    if metal:
        items = items.filter(metal_type=metal)

    # Purity filter (values are whatever the shop already uses, e.g. 22K, 925)
    purity = request.GET.get('purity', '').strip()
    if purity:
        items = items.filter(purity__iexact=purity)

    # HUID status filter
    huid_status = request.GET.get('huid_status', '').strip()
    if huid_status:
        items = items.filter(huid_status=huid_status)

    # Hallmark status filter
    hallmark_status = request.GET.get('hallmark_status', '').strip()
    if hallmark_status:
        items = items.filter(hallmark_status=hallmark_status)

    # Status filter (Available / Sold / Reserved)
    status = request.GET.get('status', '').strip()
    if status:
        items = items.filter(status=status)

    # Stock filter (In Stock / Low Stock / Out of Stock / Reserved)
    low_stock_codes = stock.low_stock_design_codes(threshold)
    stock_filter = request.GET.get('stock', '').strip()
    if stock_filter == 'available':
        items = items.filter(status='Available')
    elif stock_filter == 'low_stock':
        items = (items.filter(status='Available', quantity__gt=0,
                              design_code__in=low_stock_codes)
                 if low_stock_codes else items.none())
    elif stock_filter == 'out_of_stock':
        items = items.filter(Q(status='Sold') | Q(quantity__lte=0))
    elif stock_filter == 'reserved':
        items = items.filter(status='Reserved')
    else:
        stock_filter = ''

    # Sorting
    sort = request.GET.get('sort', '-created_at')
    valid_sorts = ['selling_price', '-selling_price', 'created_at', '-created_at', 'name', 'item_code',
                   'tag_number', '-tag_number', 'design_code', 'quantity', '-quantity', 'net_weight', '-net_weight',
                   'gross_weight', '-gross_weight', 'stone_weight', '-stone_weight', 'huid', '-huid']
    if sort in valid_sorts:
        items = items.order_by(sort)

    # Pagination
    paginator = Paginator(items, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Flag the items on this page that are running low (single query for the
    # whole page - the design codes were already fetched above).
    for item in page_obj.object_list:
        item.is_low_stock = (
            item.status == 'Available' and item.quantity > 0
            and item.design_code in low_stock_codes)

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'categories': categories,
        'metal_choices': JewelleryItem.METAL_CHOICES,
        'status_choices': JewelleryItem.STATUS_CHOICES,
        'huid_status_choices': JewelleryItem.HUID_STATUS_CHOICES,
        'hallmark_status_choices': JewelleryItem.HALLMARK_STATUS_CHOICES,
        'purity_choices': (JewelleryItem.objects.exclude(purity='')
                           .order_by('purity')
                           .values_list('purity', flat=True)
                           .distinct()),
        'stock_filter_choices': stock.STOCK_STATUS_FILTERS,
        'selected_q': q,
        'selected_tag': tag,
        'selected_huid': huid,
        'selected_category': category_id,
        'selected_metal': metal,
        'selected_purity': purity,
        'selected_huid_status': huid_status,
        'selected_hallmark_status': hallmark_status,
        'selected_status': status,
        'selected_stock': stock_filter,
        'selected_sort': sort,
        'low_stock_threshold': threshold,
        'summary': stock.inventory_summary(threshold),
    }
    return render(request, 'inventory/item_list.html', context)


@login_required
def inventory_add(request):
    """Add a new jewellery item, with optional pre-fill for adding another piece of an existing design."""
    initial_data = {}
    if 'design_code' in request.GET:
        initial_data['design_code'] = request.GET.get('design_code')
    if 'duplicate_from' in request.GET:
        try:
            source_item = JewelleryItem.objects.get(pk=request.GET.get('duplicate_from'))
            initial_data.update({
                'design_code': source_item.design_code,
                'name': source_item.name,
                'category': source_item.category_id,
                'metal_type': source_item.metal_type,
                'purity': source_item.purity,
                'huid_status': source_item.huid_status,
                'hallmark_status': source_item.hallmark_status,
                'hallmark_details': source_item.hallmark_details,
                'gross_weight': source_item.gross_weight,
                'stone_weight': source_item.stone_weight,
                'net_weight': source_item.net_weight,
                'making_charge': source_item.making_charge,
                'selling_price': source_item.selling_price,
                'status': 'Available',
            })
        except JewelleryItem.DoesNotExist:
            pass

    if request.method == 'POST':
        form = JewelleryItemForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                item = form.save()
                # Opening stock is written to the movement history too, so the
                # stock ledger starts from zero for every item.
                stock.record_initial_stock(item, user=request.user)
            messages.success(request, f"Jewellery item '{item.name}' ({item.item_code}) added successfully.")
            return redirect('inventory_list')
    else:
        form = JewelleryItemForm(initial=initial_data)

    context = {
        'form': form,
        'page_title': 'Add Jewellery Piece',
        'is_edit': False,
    }
    return render(request, 'inventory/item_form.html', context)


@login_required
def inventory_detail(request, pk):
    """View details of a jewellery item, its stock position and other pieces of the same design."""
    item = get_object_or_404(JewelleryItem.objects.select_related('category'), pk=pk)
    # Check if item has been sold
    sale = item.sales.select_related('customer').first() if hasattr(item, 'sales') else None

    # Other physical pieces sharing the same design code
    other_pieces = JewelleryItem.objects.filter(
        design_code=item.design_code
    ).exclude(pk=item.pk).order_by('-status', '-created_at') if item.design_code else []

    # Recent stock movement history (the full ledger lives on its own page)
    movements = item.stock_movements.select_related('created_by', 'sale')

    threshold = stock.get_low_stock_threshold()
    is_low_stock = (
        item.status == 'Available' and item.quantity > 0
        and item.design_code in stock.low_stock_design_codes(threshold))

    context = {
        'item': item,
        'sale': sale,
        'other_pieces': other_pieces,
        'movements': movements[:10],
        'movement_count': movements.count(),
        'is_low_stock': is_low_stock,
        'low_stock_threshold': threshold,
        'stock_value': stock.item_stock_value(item),
        'stock_weight': item.net_weight * item.quantity,
    }
    return render(request, 'inventory/item_detail.html', context)


@login_required
def inventory_edit(request, pk):
    """Edit an existing jewellery item."""
    item = get_object_or_404(JewelleryItem, pk=pk)
    if request.method == 'POST':
        form = JewelleryItemForm(request.POST, instance=item)
        if form.is_valid():
            item = form.save()
            messages.success(request, f"Jewellery item '{item.name}' ({item.item_code}) updated successfully.")
            return redirect('inventory_detail', pk=item.pk)
    else:
        form = JewelleryItemForm(instance=item)

    context = {
        'form': form,
        'item': item,
        'page_title': f"Edit {item.name}",
        'is_edit': True,
    }
    return render(request, 'inventory/item_form.html', context)


@login_required
def inventory_delete(request, pk):
    """Delete a jewellery item."""
    item = get_object_or_404(JewelleryItem, pk=pk)
    if request.method == 'POST':
        item_name = item.name
        item_code = item.item_code
        item.delete()
        messages.success(request, f"Jewellery item '{item_name}' ({item_code}) deleted successfully.")
        return redirect('inventory_list')

    context = {
        'item': item,
    }
    return render(request, 'inventory/item_confirm_delete.html', context)


# ==============================================================================
# STOCK VIEWS
# ==============================================================================

STOCK_MOVEMENTS_PER_PAGE = 25


def parse_movement_date(value):
    """Return a `datetime.date` parsed from a YYYY-MM-DD string, or None."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None


@login_required
def stock_adjust(request, pk):
    """
    Controlled manual stock adjustment (increase / decrease / stock take).

    All validation, the negative-stock guard and the audit-trail entry are
    handled by `inventory.stock.apply_stock_change`, so this view only wires the
    form to that service.
    """
    item = get_object_or_404(JewelleryItem.objects.select_related('category'), pk=pk)
    threshold = stock.get_low_stock_threshold()

    if request.method == 'POST':
        form = StockAdjustmentForm(request.POST, item=item)
        if form.is_valid():
            change, movement_type, reason = form.stock_change()
            try:
                movement = stock.apply_stock_change(
                    item, change, movement_type,
                    reason=reason,
                    notes=form.cleaned_data.get('notes', ''),
                    user=request.user)
            except ValidationError as exc:
                form.add_error(None, ' '.join(exc.messages))
            else:
                messages.success(
                    request,
                    f"Stock for '{item.item_code}' updated from "
                    f"{movement.stock_before} to {movement.stock_after} piece(s).")
                return redirect('inventory_detail', pk=item.pk)
    else:
        form = StockAdjustmentForm(item=item)

    context = {
        'form': form,
        'item': item,
        'page_title': f'Adjust Stock - {item.item_code}',
        'stock_value': stock.item_stock_value(item),
        'movements': item.stock_movements.select_related('created_by')[:5],
        'movement_count': item.stock_movements.count(),
        'low_stock_threshold': threshold,
        'is_low_stock': (item.status == 'Available' and item.quantity > 0
                         and item.design_code in stock.low_stock_design_codes(threshold)),
    }
    return render(request, 'inventory/stock_adjust.html', context)


@login_required
def stock_movement_list(request):
    """Stock movement history for the whole inventory, with filters."""
    movements = StockMovement.objects.select_related('item', 'created_by', 'sale')

    # Search (tag number, piece ID, item name, design code or notes)
    q = request.GET.get('q', '').strip()
    if q:
        movements = movements.filter(
            Q(item__tag_number__icontains=q) |
            Q(item__item_code__icontains=q) |
            Q(item__name__icontains=q) |
            Q(item__design_code__icontains=q) |
            Q(notes__icontains=q)
        )

    # Single item filter (linked from the item detail page)
    item_id = request.GET.get('item', '').strip()
    if item_id.isdigit():
        movements = movements.filter(item_id=item_id)

    # Movement type filter
    movement_type = request.GET.get('type', '').strip()
    if movement_type:
        movements = movements.filter(movement_type=movement_type)

    # Date range filter
    date_from = parse_movement_date(request.GET.get('from'))
    if date_from:
        movements = movements.filter(created_at__date__gte=date_from)
    date_to = parse_movement_date(request.GET.get('to'))
    if date_to:
        movements = movements.filter(created_at__date__lte=date_to)

    totals = movements.aggregate(
        movement_count=Count('id'),
        stock_in=Sum('quantity_change', filter=Q(quantity_change__gt=0)),
        stock_out=Sum('quantity_change', filter=Q(quantity_change__lt=0)),
    )
    totals['stock_in'] = totals['stock_in'] or 0
    totals['stock_out'] = totals['stock_out'] or 0

    paginator = Paginator(movements, STOCK_MOVEMENTS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_title': 'Stock Movement History',
        'movements': page_obj,
        'page_obj': page_obj,
        'totals': totals,
        'movement_types': StockMovement.MOVEMENT_TYPES,
        'selected_q': q,
        'selected_type': movement_type,
        'selected_item': item_id,
        'selected_from': request.GET.get('from', '').strip(),
        'selected_to': request.GET.get('to', '').strip(),
        'is_item_filter': bool(item_id),
    }
    return render(request, 'inventory/stock_movement_list.html', context)


# ==============================================================================
# CATEGORY VIEWS
# ==============================================================================

@login_required
def category_list(request):
    """List all categories with item count and inline create form."""
    categories = Category.objects.annotate(items_count=Count('items')).all()
    form = CategoryForm()

    context = {
        'categories': categories,
        'form': form,
        'page_title': 'Jewellery Categories',
    }
    return render(request, 'inventory/category_list.html', context)


@login_required
def category_add(request):
    """Add a new jewellery category."""
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            messages.success(request, f"Category '{category.name}' created successfully.")
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('category_list')
        else:
            messages.error(request, "Failed to create category. Please check for errors.")
            categories = Category.objects.annotate(items_count=Count('items')).all()
            return render(request, 'inventory/category_list.html', {
                'categories': categories,
                'form': form,
                'page_title': 'Jewellery Categories',
            })
    return redirect('category_list')


@login_required
def category_edit(request, pk):
    """Edit an existing category."""
    category = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            category = form.save()
            messages.success(request, f"Category '{category.name}' updated successfully.")
            return redirect('category_list')
    else:
        form = CategoryForm(instance=category)

    context = {
        'form': form,
        'category': category,
        'page_title': f"Edit Category: {category.name}",
    }
    return render(request, 'inventory/category_form.html', context)


@login_required
def category_delete(request, pk):
    """Delete a category with protection check."""
    category = get_object_or_404(Category.objects.annotate(items_count=Count('items')), pk=pk)
    if request.method == 'POST':
        try:
            cat_name = category.name
            category.delete()
            messages.success(request, f"Category '{cat_name}' deleted successfully.")
            return redirect('category_list')
        except ProtectedError:
            messages.error(
                request,
                f"Cannot delete category '{category.name}' because {category.items_count} jewellery item(s) are assigned to it."
            )
            return redirect('category_list')

    context = {
        'category': category,
    }
    return render(request, 'inventory/category_confirm_delete.html', context)


# ==============================================================================
# BULK IMPORT VIEWS
# ==============================================================================

# Session key holding the parsed rows of the file waiting for confirmation
IMPORT_SESSION_KEY = 'inventory_import_rows'
ALLOWED_IMPORT_EXTENSIONS = ('.csv', '.xlsx')
MAX_IMPORT_FILE_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_IMPORT_ROWS = 5000
MAX_PREVIEW_INVALID_ROWS = 200
PREVIEW_VALID_ROWS_PER_PAGE = 25


def clear_stored_import(request):
    """Forget any file that was waiting to be imported."""
    request.session.pop(IMPORT_SESSION_KEY, None)


def preview_inventory_import(request):
    """
    Parse and validate an uploaded CSV/Excel file and remember its rows in the session.

    Nothing is written to the inventory here - the rows are kept only so that the
    preview (and the final import) can be validated against the current database.
    """
    uploaded_file = request.FILES.get('import_file')

    if not uploaded_file:
        messages.error(request, "Please choose a CSV or Excel (.xlsx) file to import.")
        return redirect('inventory_import')

    filename = uploaded_file.name
    extension = filename[filename.rfind('.'):].lower() if '.' in filename else ''
    max_size_mb = MAX_IMPORT_FILE_SIZE // (1024 * 1024)

    if extension not in ALLOWED_IMPORT_EXTENSIONS:
        messages.error(request, f"Unsupported file type '{filename}'. Please upload a .csv or .xlsx file.")
        return redirect('inventory_import')

    if uploaded_file.size > MAX_IMPORT_FILE_SIZE:
        messages.error(request, f"'{filename}' is larger than the {max_size_mb} MB limit per import.")
        return redirect('inventory_import')

    try:
        if extension == '.xlsx':
            _, data_rows = parse_excel_file(uploaded_file)
        else:
            _, data_rows = parse_csv_file(uploaded_file)
    except Exception as exc:  # Whatever the parser hits, report it instead of a 500
        clear_stored_import(request)
        messages.error(request, f"Could not read '{filename}': {exc}")
        return redirect('inventory_import')

    if not data_rows:
        clear_stored_import(request)
        messages.warning(
            request,
            f"No data rows were found in '{filename}'. Make sure the first row contains the column headings."
        )
        return redirect('inventory_import')

    if len(data_rows) > MAX_IMPORT_ROWS:
        clear_stored_import(request)
        messages.error(
            request,
            f"'{filename}' contains {len(data_rows)} data rows, which is more than the {MAX_IMPORT_ROWS} rows "
            f"allowed per import. Please split the file and import it in batches."
        )
        return redirect('inventory_import')

    request.session[IMPORT_SESSION_KEY] = {
        'filename': filename,
        'rows': data_rows,
    }

    _, _, summary = validate_import_rows(data_rows)

    if summary['invalid_count']:
        messages.error(
            request,
            f"{summary['invalid_count']} of {summary['total_rows']} row(s) in '{filename}' failed validation. "
            f"Nothing has been imported - review the errors below, fix the file and upload it again."
        )
    else:
        messages.success(
            request,
            f"All {summary['valid_count']} row(s) in '{filename}' passed validation. "
            f"Review the preview below, then confirm the import."
        )

    return redirect('inventory_import')


def confirm_inventory_import(request):
    """
    Re-validate the previewed rows and insert them inside one atomic transaction.

    Rows are validated again so that pieces added to (or edited in) the inventory after
    the preview was rendered can never be imported twice or left partially imported.
    """
    stored_import = request.session.get(IMPORT_SESSION_KEY)

    if not stored_import or not stored_import.get('rows'):
        messages.error(request, "There is no validated file to import. Please upload your file again.")
        return redirect('inventory_import')

    filename = stored_import.get('filename', 'uploaded file')
    valid_rows, invalid_rows, _ = validate_import_rows(stored_import['rows'])

    if invalid_rows:
        messages.error(
            request,
            f"Nothing was imported because {len(invalid_rows)} row(s) in '{filename}' have validation errors. "
            f"Review the errors below and upload a corrected file."
        )
        return redirect('inventory_import')

    if not valid_rows:
        messages.warning(request, f"'{filename}' does not contain any rows that can be imported.")
        return redirect('inventory_import')

    try:
        imported_count = import_valid_rows(valid_rows, user=request.user)
    except (ValidationError, IntegrityError, InvalidOperation) as exc:
        clear_stored_import(request)
        messages.error(
            request,
            f"Bulk import failed and was rolled back - no items were imported. {exc}"
        )
        return redirect('inventory_import')

    clear_stored_import(request)
    messages.success(
        request,
        f"Bulk import complete: {imported_count} jewellery item(s) from '{filename}' were added to the inventory."
    )
    return redirect('inventory_list')


@login_required
def inventory_import(request):
    """
    Bulk import jewellery items from a CSV or Excel (.xlsx) file.

    Step 1 (action=upload) validates the file and shows a preview; step 2
    (action=confirm) writes the valid rows, and action=cancel discards the upload.
    """
    if request.method == 'POST':
        action = request.POST.get('action', 'upload')

        if action == 'cancel':
            clear_stored_import(request)
            messages.info(request, "Bulk import cancelled - no items were imported.")
            return redirect('inventory_import')

        if action == 'confirm':
            return confirm_inventory_import(request)

        return preview_inventory_import(request)

    stored_import = request.session.get(IMPORT_SESSION_KEY)

    context = {
        'page_title': 'Bulk Import Inventory',
        'allowed_extensions': ', '.join(ALLOWED_IMPORT_EXTENSIONS),
        'max_file_size_mb': MAX_IMPORT_FILE_SIZE // (1024 * 1024),
        'max_rows': MAX_IMPORT_ROWS,
    }

    if not stored_import or not stored_import.get('rows'):
        return render(request, 'inventory/import.html', context)

    valid_rows, invalid_rows, summary = validate_import_rows(stored_import['rows'])
    duplicate_rows = get_duplicate_rows(invalid_rows)

    paginator = Paginator(valid_rows, PREVIEW_VALID_ROWS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page'))

    context.update({
        'stored_filename': stored_import.get('filename', 'uploaded file'),
        'summary': summary,
        'page_obj': page_obj,
        'valid_rows': page_obj,
        'invalid_rows': invalid_rows[:MAX_PREVIEW_INVALID_ROWS],
        'shown_invalid_count': min(summary['invalid_count'], MAX_PREVIEW_INVALID_ROWS),
        'duplicate_rows': duplicate_rows,
        'duplicate_count': len(duplicate_rows),
        'duplicate_row_nums': {row['row_num'] for row in duplicate_rows},
        'can_import': summary['invalid_count'] == 0 and summary['valid_count'] > 0,
    })
    return render(request, 'inventory/import_preview.html', context)


@login_required
def inventory_import_sample(request):
    """Download the sample CSV template used by the bulk inventory import."""
    response = HttpResponse(generate_sample_csv(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="jeweldesk_inventory_import_sample.csv"'
    return response


@login_required
def metal_price_refresh(request):
    """
    Explicit refresh action for the dashboard metal prices (POST only).

    Performs a single API call, caches the result and reports the outcome
    with a Django message. The dashboard itself never calls the API, so the
    price service is not hit on ordinary page interactions.
    """
    if request.method != 'POST':
        return redirect('dashboard')
    result = metal_prices.refresh_prices()
    if result['ok']:
        messages.success(request, 'Metal prices updated.')
        # Sync fetched prices into MetalRate model if available
        snapshot = result.get('snapshot') or {}
        if snapshot.get('gold_price_per_gram'):
            MetalRate.objects.update_or_create(
                metal_type='Gold',
                defaults={'rate_per_gram': snapshot['gold_price_per_gram'], 'source': 'Live API'}
            )
        if snapshot.get('silver_price_per_gram'):
            MetalRate.objects.update_or_create(
                metal_type='Silver',
                defaults={'rate_per_gram': snapshot['silver_price_per_gram'], 'source': 'Live API'}
            )
    else:
        messages.error(request, f'Price update failed: {result["message"]}')
        if result['snapshot'] and result['snapshot'].get('available'):
            messages.info(request, 'Showing the last available prices.')
    return redirect('dashboard')


# ==============================================================================
# PRICING ENGINE VIEWS
# ==============================================================================

@login_required
def pricing_calculator(request):
    """
    Interactive Jewellery Pricing Engine and Live Valuation Cockpit.
    Supports real-time price breakdowns, purity conversion, wastage,
    making charges, stones, GST and direct inventory item prefill / price updating.
    """
    from . import pricing
    from team.permissions import has_module_perm, is_admin_user
    from django.core.exceptions import PermissionDenied

    # Check permission (viewing pricing requires inventory:view or metal_prices:view or admin/staff)
    user = request.user
    can_view = (
        user.is_superuser or user.is_staff or
        has_module_perm(user, 'inventory', 'view') or
        has_module_perm(user, 'metal_prices', 'view') or
        not hasattr(user, 'employee_profile')
    )
    if not can_view:
        raise PermissionDenied("You do not have permission to access the Pricing Engine.")

    can_edit_items = (
        user.is_superuser or user.is_staff or
        has_module_perm(user, 'inventory', 'edit') or
        not hasattr(user, 'employee_profile')
    )

    can_edit_rates = (
        user.is_superuser or user.is_staff or
        has_module_perm(user, 'metal_prices', 'edit') or
        not hasattr(user, 'employee_profile')
    )

    # Available items for dropdown selector
    available_items = JewelleryItem.objects.filter(status='Available').select_related('category').order_by('name')

    selected_item = None
    item_id = request.GET.get('item') or request.POST.get('selected_item_id')
    if item_id:
        try:
            selected_item = JewelleryItem.objects.get(pk=item_id)
        except (JewelleryItem.DoesNotExist, ValueError):
            selected_item = None

    # Base rates
    active_gold_rate = pricing.get_current_metal_rate('Gold')
    active_silver_rate = pricing.get_current_metal_rate('Silver')

    # Initial form values
    if request.method == 'POST':
        action = request.POST.get('action', 'calculate')
        metal_type = request.POST.get('metal_type', 'Gold').strip()
        purity = request.POST.get('purity', '22K').strip()
        gross_weight = pricing.to_decimal(request.POST.get('gross_weight'), '10.000')
        stone_weight = pricing.to_decimal(request.POST.get('stone_weight'), '0.000')
        net_weight = pricing.to_decimal(request.POST.get('net_weight'), '') if request.POST.get('net_weight') else None
        base_rate_input = pricing.to_decimal(request.POST.get('base_metal_rate'), '') if request.POST.get('base_metal_rate') else None
        wastage_percent = pricing.to_decimal(request.POST.get('wastage_percent'), '0.00')
        making_charge = pricing.to_decimal(request.POST.get('making_charge'), '0.00')
        making_charge_type = request.POST.get('making_charge_type', 'Fixed Amount').strip()
        stone_charges = pricing.to_decimal(request.POST.get('stone_charges'), '0.00')
        other_charges = pricing.to_decimal(request.POST.get('other_charges'), '0.00')
        other_charges_desc = request.POST.get('other_charges_description', '').strip()
        tax_percent = pricing.to_decimal(request.POST.get('tax_percent'), '3.00')

        # Run calculation
        breakdown = pricing.calculate_jewellery_price(
            metal_type=metal_type,
            purity=purity,
            gross_weight=gross_weight,
            stone_weight=stone_weight,
            net_weight=net_weight,
            base_metal_rate=base_rate_input,
            wastage_percent=wastage_percent,
            making_charge=making_charge,
            making_charge_type=making_charge_type,
            stone_charges=stone_charges,
            other_charges=other_charges,
            other_charges_description=other_charges_desc,
            tax_percent=tax_percent,
        )

        # Action: Apply calculated price to existing inventory piece
        if action == 'save_to_item' and selected_item:
            if not can_edit_items:
                raise PermissionDenied("You do not have permission to update inventory item prices.")
            selected_item.selling_price = breakdown.final_price
            selected_item.making_charge = breakdown.making_charge_rate
            selected_item.making_charge_type = breakdown.making_charge_type
            selected_item.wastage_percent = breakdown.wastage_percent
            selected_item.stone_charges = breakdown.stone_charges
            selected_item.other_charges = breakdown.other_charges
            selected_item.save()
            messages.success(
                request,
                f"Successfully updated selling price of '{selected_item.name}' ({selected_item.item_code}) to ₹{breakdown.final_price:,.2f}."
            )

    else:
        # GET request
        if selected_item:
            metal_type = selected_item.metal_type
            purity = selected_item.purity
            gross_weight = selected_item.gross_weight
            stone_weight = selected_item.stone_weight
            net_weight = selected_item.net_weight
            base_rate_input = None
            wastage_percent = selected_item.wastage_percent
            making_charge = selected_item.making_charge
            making_charge_type = selected_item.making_charge_type
            stone_charges = selected_item.stone_charges
            other_charges = selected_item.other_charges
            other_charges_desc = ''
            tax_percent = pricing.DEFAULT_GST_RATE
        else:
            metal_type = 'Gold'
            purity = '22K (916)'
            gross_weight = Decimal('10.000')
            stone_weight = Decimal('0.000')
            net_weight = Decimal('10.000')
            base_rate_input = active_gold_rate
            wastage_percent = Decimal('3.00')
            making_charge = Decimal('450.00')
            making_charge_type = 'Per Gram'
            stone_charges = Decimal('0.00')
            other_charges = Decimal('0.00')
            other_charges_desc = ''
            tax_percent = pricing.DEFAULT_GST_RATE

        breakdown = pricing.calculate_jewellery_price(
            metal_type=metal_type,
            purity=purity,
            gross_weight=gross_weight,
            stone_weight=stone_weight,
            net_weight=net_weight,
            base_metal_rate=base_rate_input,
            wastage_percent=wastage_percent,
            making_charge=making_charge,
            making_charge_type=making_charge_type,
            stone_charges=stone_charges,
            other_charges=other_charges,
            other_charges_description=other_charges_desc,
            tax_percent=tax_percent,
        )

    # Derived rates for display bar
    rate_24k = active_gold_rate
    rate_22k = pricing.round_curr(active_gold_rate * (Decimal('22') / Decimal('24')))
    rate_18k = pricing.round_curr(active_gold_rate * (Decimal('18') / Decimal('24')))
    rate_silver_999 = active_silver_rate
    rate_silver_925 = pricing.round_curr(active_silver_rate * Decimal('0.925'))

    context = {
        'page_title': 'Jewellery Pricing Engine',
        'breakdown': breakdown,
        'breakdown_json': breakdown.to_dict(),
        'available_items': available_items,
        'selected_item': selected_item,
        'selected_item_id': str(selected_item.pk) if selected_item else '',
        'can_edit_items': can_edit_items,
        'can_edit_rates': can_edit_rates,
        # Board rates
        'rate_24k': rate_24k,
        'rate_22k': rate_22k,
        'rate_18k': rate_18k,
        'rate_silver_999': rate_silver_999,
        'rate_silver_925': rate_silver_925,
        # Current form inputs
        'form_data': {
            'metal_type': metal_type,
            'purity': purity,
            'gross_weight': gross_weight,
            'stone_weight': stone_weight,
            'net_weight': net_weight if net_weight is not None else '',
            'base_metal_rate': base_rate_input if base_rate_input is not None else '',
            'wastage_percent': wastage_percent,
            'making_charge': making_charge,
            'making_charge_type': making_charge_type,
            'stone_charges': stone_charges,
            'other_charges': other_charges,
            'other_charges_description': other_charges_desc,
            'tax_percent': tax_percent,
        }
    }
    return render(request, 'inventory/pricing_calculator.html', context)


@login_required
def api_calculate_price(request):
    """
    JSON API endpoint for real-time frontend calculations.
    Accepts GET or POST with pricing inputs and returns full PriceBreakdown dict.
    """
    from . import pricing
    from django.http import JsonResponse
    import json

    params = {}
    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                params = json.loads(request.body.decode('utf-8'))
            except Exception:
                params = {}
        else:
            params = request.POST.dict()
    else:
        params = request.GET.dict()

    try:
        metal_type = params.get('metal_type', 'Gold')
        purity = params.get('purity', '22K')
        gross_weight = pricing.to_decimal(params.get('gross_weight'), '0.000')
        stone_weight = pricing.to_decimal(params.get('stone_weight'), '0.000')
        net_weight = pricing.to_decimal(params.get('net_weight')) if params.get('net_weight') else None
        base_rate = pricing.to_decimal(params.get('base_metal_rate')) if params.get('base_metal_rate') else None
        wastage_pct = pricing.to_decimal(params.get('wastage_percent'), '0.00')
        wastage_amt = pricing.to_decimal(params.get('wastage_amount'), '0.00') if params.get('wastage_amount') else None
        making_charge = pricing.to_decimal(params.get('making_charge'), '0.00')
        making_charge_type = params.get('making_charge_type', 'Fixed Amount')
        stone_charges = pricing.to_decimal(params.get('stone_charges'), '0.00')
        other_charges = pricing.to_decimal(params.get('other_charges'), '0.00')
        tax_pct = pricing.to_decimal(params.get('tax_percent'), '3.00')

        breakdown = pricing.calculate_jewellery_price(
            metal_type=metal_type,
            purity=purity,
            gross_weight=gross_weight,
            stone_weight=stone_weight,
            net_weight=net_weight,
            base_metal_rate=base_rate,
            wastage_percent=wastage_pct,
            wastage_amount=wastage_amt,
            making_charge=making_charge,
            making_charge_type=making_charge_type,
            stone_charges=stone_charges,
            other_charges=other_charges,
            tax_percent=tax_pct,
        )
        return JsonResponse({'ok': True, 'breakdown': breakdown.to_dict()})
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)


@login_required
def metal_rates_view(request):
    """
    Shop Metal Rates Management view.
    Displays current board rates (24K Gold, 22K Gold, 18K Gold, 999 Silver, 925 Silver).
    Allows authorized staff to update the daily board rates or sync from live market API.
    """
    from . import pricing
    from .forms import MetalRatesUpdateForm
    from team.permissions import has_module_perm, is_admin_user
    from django.core.exceptions import PermissionDenied

    user = request.user
    can_view = (
        user.is_superuser or user.is_staff or
        has_module_perm(user, 'metal_prices', 'view') or
        not hasattr(user, 'employee_profile')
    )
    if not can_view:
        raise PermissionDenied("You do not have permission to view metal prices.")

    can_edit = (
        user.is_superuser or user.is_staff or
        has_module_perm(user, 'metal_prices', 'edit') or
        not hasattr(user, 'employee_profile')
    )

    # Fetch DB records
    gold_rate_obj = MetalRate.objects.filter(metal_type='Gold').first()
    silver_rate_obj = MetalRate.objects.filter(metal_type='Silver').first()
    plat_rate_obj = MetalRate.objects.filter(metal_type='Platinum').first()

    gold_24k = gold_rate_obj.rate_per_gram if gold_rate_obj else pricing.FALLBACK_GOLD_24K_RATE
    silver_999 = silver_rate_obj.rate_per_gram if silver_rate_obj else pricing.FALLBACK_SILVER_999_RATE
    plat_rate = plat_rate_obj.rate_per_gram if plat_rate_obj else pricing.FALLBACK_PLATINUM_RATE

    if request.method == 'POST':
        if not can_edit:
            raise PermissionDenied("You do not have permission to edit metal board rates.")

        action = request.POST.get('action')
        if action == 'sync_api':
            result = metal_prices.refresh_prices()
            if result['ok']:
                snapshot = result.get('snapshot') or {}
                if snapshot.get('gold_price_per_gram'):
                    MetalRate.objects.update_or_create(
                        metal_type='Gold',
                        defaults={'rate_per_gram': snapshot['gold_price_per_gram'], 'source': 'Live API', 'updated_by': user}
                    )
                if snapshot.get('silver_price_per_gram'):
                    MetalRate.objects.update_or_create(
                        metal_type='Silver',
                        defaults={'rate_per_gram': snapshot['silver_price_per_gram'], 'source': 'Live API', 'updated_by': user}
                    )
                messages.success(request, 'Successfully synchronized metal rates from live market API.')
            else:
                messages.error(request, f'Failed to fetch API prices: {result["message"]}')
            return redirect('metal_rates')

        else:
            # Manual update
            form = MetalRatesUpdateForm(request.POST)
            if form.is_valid():
                g_rate = form.cleaned_data['gold_rate_24k']
                s_rate = form.cleaned_data['silver_rate_999']
                p_rate = form.cleaned_data.get('platinum_rate')
                source = form.cleaned_data.get('source') or 'Shop Board Rate'

                MetalRate.objects.update_or_create(
                    metal_type='Gold',
                    defaults={'rate_per_gram': g_rate, 'source': source, 'updated_by': user}
                )
                MetalRate.objects.update_or_create(
                    metal_type='Silver',
                    defaults={'rate_per_gram': s_rate, 'source': source, 'updated_by': user}
                )
                if p_rate:
                    MetalRate.objects.update_or_create(
                        metal_type='Platinum',
                        defaults={'rate_per_gram': p_rate, 'source': source, 'updated_by': user}
                    )
                messages.success(request, 'Daily shop metal rates updated successfully!')
                return redirect('metal_rates')
            else:
                messages.error(request, 'Please check the values entered in the form.')
    else:
        form = MetalRatesUpdateForm(initial={
            'gold_rate_24k': gold_24k,
            'silver_rate_999': silver_999,
            'platinum_rate': plat_rate,
            'source': gold_rate_obj.source if gold_rate_obj else 'Shop Board Rate',
        })

    # Calculations for Karat board
    gold_decimal = pricing.to_decimal(gold_24k)
    silver_decimal = pricing.to_decimal(silver_999)

    karat_rates = {
        '24K': gold_decimal,
        '22K': pricing.round_curr(gold_decimal * (Decimal('22') / Decimal('24'))),
        '20K': pricing.round_curr(gold_decimal * (Decimal('20') / Decimal('24'))),
        '18K': pricing.round_curr(gold_decimal * (Decimal('18') / Decimal('24'))),
        '14K': pricing.round_curr(gold_decimal * (Decimal('14') / Decimal('24'))),
        '10K': pricing.round_curr(gold_decimal * (Decimal('10') / Decimal('24'))),
    }

    silver_rates = {
        '999': silver_decimal,
        '925': pricing.round_curr(silver_decimal * Decimal('0.925')),
        '900': pricing.round_curr(silver_decimal * Decimal('0.900')),
        '800': pricing.round_curr(silver_decimal * Decimal('0.800')),
    }

    context = {
        'page_title': 'Shop Metal Rates Board',
        'form': form,
        'can_edit': can_edit,
        'gold_rate_obj': gold_rate_obj,
        'silver_rate_obj': silver_rate_obj,
        'plat_rate_obj': plat_rate_obj,
        'gold_24k': gold_24k,
        'silver_999': silver_999,
        'karat_rates': karat_rates,
        'silver_rates': silver_rates,
    }
    return render(request, 'inventory/metal_rates.html', context)



