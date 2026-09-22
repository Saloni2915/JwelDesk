from decimal import InvalidOperation

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q, Sum, Count, ProtectedError
from django.http import HttpResponse
from django.utils import timezone
from .models import JewelleryItem, Category
from .forms import JewelleryItemForm, CategoryForm
from .import_utils import (
    generate_sample_csv,
    get_duplicate_rows,
    import_valid_rows,
    parse_csv_file,
    parse_excel_file,
    validate_import_rows,
)
from . import metal_prices


@login_required
def dashboard(request):
    """Main dashboard view with dynamic statistics and recent activity."""
    today = timezone.localdate()

    total_items = JewelleryItem.objects.count()
    available_items = JewelleryItem.objects.filter(status='Available').count()
    sold_items = JewelleryItem.objects.filter(status='Sold').count()

    # Import sales & enquiries models dynamically to prevent circular imports if any
    from sales.models import Sale, Enquiry

    # Today's sales aggregation
    today_sales_data = Sale.objects.filter(sale_date__date=today).aggregate(
        total_amount=Sum('sale_price'),
        count=Count('id')
    )
    today_sales_amount = today_sales_data['total_amount'] or 0

    # Recent sales (latest 5)
    recent_sales = Sale.objects.select_related('customer', 'jewellery_item').order_by('-sale_date')[:5]

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
        'total_items': total_items,
        'available_items': available_items,
        'sold_items': sold_items,
        'today_sales_amount': today_sales_amount,
        'recent_sales': recent_sales,
        'recent_enquiries': recent_enquiries,
        'upcoming_followups': upcoming_followups,
        'metal_prices': metal_price_snapshot,
    }
    return render(request, 'inventory/dashboard.html', context)


@login_required
def inventory_list(request):
    """List all jewellery items with search and filters."""
    items = JewelleryItem.objects.select_related('category').all()
    categories = Category.objects.all()

    # Search filter (item_code, name, or design_code)
    q = request.GET.get('q', '').strip()
    if q:
        items = items.filter(Q(item_code__icontains=q) | Q(name__icontains=q) | Q(design_code__icontains=q))

    # Category filter
    category_id = request.GET.get('category', '').strip()
    if category_id:
        items = items.filter(category_id=category_id)

    # Metal type filter
    metal = request.GET.get('metal', '').strip()
    if metal:
        items = items.filter(metal_type=metal)

    # Status filter
    status = request.GET.get('status', '').strip()
    if status:
        items = items.filter(status=status)

    # Sorting
    sort = request.GET.get('sort', '-created_at')
    valid_sorts = ['selling_price', '-selling_price', 'created_at', '-created_at', 'name', 'item_code', 'design_code']
    if sort in valid_sorts:
        items = items.order_by(sort)

    # Pagination
    paginator = Paginator(items, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'items': page_obj,
        'page_obj': page_obj,
        'categories': categories,
        'metal_choices': JewelleryItem.METAL_CHOICES,
        'status_choices': JewelleryItem.STATUS_CHOICES,
        'selected_q': q,
        'selected_category': category_id,
        'selected_metal': metal,
        'selected_status': status,
        'selected_sort': sort,
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
                'gross_weight': source_item.gross_weight,
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
            item = form.save()
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
    """View details of a jewellery item and other physical pieces of the same design."""
    item = get_object_or_404(JewelleryItem.objects.select_related('category'), pk=pk)
    # Check if item has been sold
    sale = item.sales.select_related('customer').first() if hasattr(item, 'sales') else None

    # Other physical pieces sharing the same design code
    other_pieces = JewelleryItem.objects.filter(
        design_code=item.design_code
    ).exclude(pk=item.pk).order_by('-status', '-created_at') if item.design_code else []

    context = {
        'item': item,
        'sale': sale,
        'other_pieces': other_pieces,
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
        imported_count = import_valid_rows(valid_rows)
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
    else:
        messages.error(request, f'Price update failed: {result["message"]}')
        if result['snapshot'] and result['snapshot'].get('available'):
            messages.info(request, 'Showing the last available prices.')
    return redirect('dashboard')


