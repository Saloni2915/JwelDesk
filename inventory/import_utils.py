import csv
import io
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from inventory.models import JewelleryItem, Category
from inventory.stock import record_initial_stock

HEADER_MAPPING = {
    'item_code': ['item_code', 'item code', 'piece_id', 'piece id', 'item_id', 'item id', 'tag', 'tag_number', 'barcode', 'code'],
    'design_code': ['design_code', 'design code', 'model_code', 'model code', 'design', 'model', 'design_id', 'sku'],
    'name': ['name', 'item_name', 'item name', 'product_name', 'product name', 'title', 'description'],
    'category': ['category', 'category_name', 'category name', 'cat'],
    'metal_type': ['metal_type', 'metal type', 'metal', 'metal_name'],
    'purity': ['purity', 'purity_grade', 'purity grade', 'grade', 'karat', 'carat'],
    'gross_weight': ['gross_weight', 'gross weight', 'gross_wt', 'gross wt', 'gross'],
    'stone_weight': ['stone_weight', 'stone weight', 'stone_wt', 'stone wt', 'stone'],
    'net_weight': ['net_weight', 'net weight', 'net_wt', 'net wt', 'net'],
    'making_charge': ['making_charge', 'making charge', 'making_charges', 'making charges', 'mc'],
    'selling_price': ['selling_price', 'selling price', 'price', 'amount', 'rate', 'sale_price'],
    'status': ['status', 'item_status', 'item status'],
}

VALID_METALS = {
    'gold': 'Gold',
    'silver': 'Silver',
    'diamond': 'Diamond',
    'platinum': 'Platinum',
}

VALID_STATUSES = {
    'available': 'Available',
    'sold': 'Sold',
    'reserved': 'Reserved',
}

# Fragments of the error messages produced by `validate_import_rows` when a Piece ID
# is duplicated (either inside the uploaded file or already present in the database).
DUPLICATE_ERROR_MARKERS = (
    'Duplicate Piece ID',
    'already exists in database',
)


def normalize_header(header_name):
    """Normalize header string to standard field name."""
    cleaned = str(header_name).strip().lower().replace('-', '_').replace('  ', ' ')
    for standard_field, aliases in HEADER_MAPPING.items():
        if cleaned in aliases:
            return standard_field
    return cleaned


def parse_csv_file(uploaded_file):
    """Parse uploaded CSV file into a list of row dicts."""
    content = uploaded_file.read()
    # Try multiple decodings (UTF-8 with BOM, standard UTF-8, Latin-1)
    for encoding in ['utf-8-sig', 'utf-8', 'latin-1']:
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = content.decode('utf-8', errors='ignore')

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []

    raw_headers = [h.strip() for h in rows[0]]
    normalized_headers = [normalize_header(h) for h in raw_headers]

    data_rows = []
    for row_idx, row in enumerate(rows[1:], start=2):
        if not any(str(cell).strip() for cell in row):
            continue  # Skip completely empty rows
        row_dict = {}
        for col_idx, col_name in enumerate(normalized_headers):
            val = row[col_idx].strip() if col_idx < len(row) else ''
            row_dict[col_name] = val
        row_dict['_row_num'] = row_idx
        data_rows.append(row_dict)

    return normalized_headers, data_rows


def parse_excel_file(uploaded_file):
    """Parse uploaded Excel (.xlsx) file into a list of row dicts using openpyxl."""
    import openpyxl

    wb = openpyxl.load_workbook(uploaded_file, data_only=True)
    sheet = wb.active

    rows = []
    for row in sheet.iter_rows(values_only=True):
        if any(cell is not None and str(cell).strip() != '' for cell in row):
            rows.append([str(cell).strip() if cell is not None else '' for cell in row])

    if not rows:
        return [], []

    raw_headers = [str(h).strip() for h in rows[0]]
    normalized_headers = [normalize_header(h) for h in raw_headers]

    data_rows = []
    for row_idx, row in enumerate(rows[1:], start=2):
        if not any(str(cell).strip() for cell in row):
            continue  # Skip empty rows
        row_dict = {}
        for col_idx, col_name in enumerate(normalized_headers):
            val = row[col_idx].strip() if col_idx < len(row) else ''
            row_dict[col_name] = val
        row_dict['_row_num'] = row_idx
        data_rows.append(row_dict)

    return normalized_headers, data_rows


def validate_import_rows(data_rows):
    """
    Validate imported rows against schema, business rules, and database constraints.
    Returns:
        valid_rows: list of clean dicts ready for insertion
        invalid_rows: list of row dicts containing error details
        summary: summary stats dict
    """
    valid_rows = []
    invalid_rows = []
    seen_file_codes = set()
    existing_db_codes = set(
        JewelleryItem.objects.values_list('item_code', flat=True)
    )

    for row in data_rows:
        row_num = row.get('_row_num', 0)
        errors = []

        # 1. Piece ID / item_code
        item_code = row.get('item_code', '').strip()
        if not item_code:
            errors.append("Piece ID / Item Code is required.")
        else:
            if item_code in seen_file_codes:
                errors.append(f"Duplicate Piece ID '{item_code}' found within uploaded file.")
            elif item_code in existing_db_codes:
                errors.append(f"Piece ID '{item_code}' already exists in database.")
            else:
                seen_file_codes.add(item_code)

        # 2. Design Code (optional, defaults to item_code)
        design_code = row.get('design_code', '').strip()
        if not design_code and item_code:
            design_code = item_code

        # 3. Name
        name = row.get('name', '').strip()
        if not name:
            errors.append("Item name is required.")

        # 4. Category
        category_name = row.get('category', '').strip()
        if not category_name:
            errors.append("Category is required.")

        # 5. Metal Type
        raw_metal = row.get('metal_type', '').strip().lower()
        if not raw_metal:
            errors.append("Metal type is required (Gold, Silver, Diamond, Platinum).")
            metal_type = ''
        elif raw_metal not in VALID_METALS:
            errors.append(f"Invalid metal type '{row.get('metal_type')}'. Must be Gold, Silver, Diamond, or Platinum.")
            metal_type = ''
        else:
            metal_type = VALID_METALS[raw_metal]

        # 6. Purity
        purity = row.get('purity', '').strip()
        if not purity:
            errors.append("Purity / Grade is required (e.g. 22K (916), 18K, 925).")

        # 7. Weights
        gross_weight = None
        raw_gross = str(row.get('gross_weight', '')).replace(',', '').strip()
        if not raw_gross:
            errors.append("Gross weight is required.")
        else:
            try:
                gross_weight = Decimal(raw_gross)
                if gross_weight <= 0:
                    errors.append("Gross weight must be greater than 0.")
            except (InvalidOperation, ValueError):
                errors.append(f"Invalid gross weight number: '{raw_gross}'.")

        stone_weight = Decimal('0.000')
        raw_stone = str(row.get('stone_weight', '')).replace(',', '').strip()
        if raw_stone:
            try:
                stone_weight = Decimal(raw_stone)
                if stone_weight < 0:
                    errors.append("Stone weight cannot be negative.")
            except (InvalidOperation, ValueError):
                errors.append(f"Invalid stone weight number: '{raw_stone}'.")

        net_weight = None
        raw_net = str(row.get('net_weight', '')).replace(',', '').strip()
        if raw_net:
            try:
                net_weight = Decimal(raw_net)
                if net_weight <= 0:
                    errors.append("Net weight must be greater than 0.")
            except (InvalidOperation, ValueError):
                errors.append(f"Invalid net weight number: '{raw_net}'.")
        elif gross_weight is not None and stone_weight < gross_weight:
            # Net weight is optional: it is the precious metal weight left after the
            # stones are removed, exactly like `JewelleryItem.clean` computes it.
            net_weight = gross_weight - stone_weight
        else:
            errors.append("Net weight is required.")

        # Only report the single most specific weight problem for the row.
        if gross_weight is not None and net_weight is not None and net_weight > gross_weight:
            errors.append(f"Net weight ({net_weight}g) cannot exceed gross weight ({gross_weight}g).")
        elif gross_weight is not None and stone_weight > gross_weight:
            errors.append(f"Stone weight ({stone_weight}g) cannot exceed gross weight ({gross_weight}g).")
        elif (gross_weight is not None and net_weight is not None
                and net_weight + stone_weight > gross_weight):
            errors.append(
                f"Net weight ({net_weight}g) plus stone weight ({stone_weight}g) exceeds "
                f"gross weight ({gross_weight}g)."
            )

        # 8. Making charge
        making_charge = Decimal('0.00')
        raw_mc = str(row.get('making_charge', '')).replace(',', '').strip()
        if raw_mc:
            try:
                making_charge = Decimal(raw_mc)
                if making_charge < 0:
                    errors.append("Making charge cannot be negative.")
            except (InvalidOperation, ValueError):
                errors.append(f"Invalid making charge amount: '{raw_mc}'.")

        # 9. Selling Price
        selling_price = None
        raw_price = str(row.get('selling_price', '')).replace(',', '').strip()
        if not raw_price:
            errors.append("Selling price is required.")
        else:
            try:
                selling_price = Decimal(raw_price)
                if selling_price <= 0:
                    errors.append("Selling price must be greater than 0.")
            except (InvalidOperation, ValueError):
                errors.append(f"Invalid selling price amount: '{raw_price}'.")

        # 10. Status
        raw_status = row.get('status', '').strip().lower()
        if not raw_status:
            status = 'Available'
        elif raw_status in VALID_STATUSES:
            status = VALID_STATUSES[raw_status]
        else:
            errors.append(f"Invalid status '{row.get('status')}'. Must be Available, Sold, or Reserved.")
            status = 'Available'

        processed_row = {
            'row_num': row_num,
            'item_code': item_code,
            'design_code': design_code,
            'name': name,
            'category_name': category_name,
            'metal_type': metal_type,
            'purity': purity,
            'gross_weight': str(gross_weight) if gross_weight is not None else raw_gross,
            'stone_weight': str(stone_weight),
            'has_stone_weight': stone_weight != 0,
            'net_weight': str(net_weight) if net_weight is not None else raw_net,
            'making_charge': str(making_charge),
            'selling_price': str(selling_price) if selling_price is not None else raw_price,
            'status': status,
            'errors': errors,
            'is_valid': len(errors) == 0,
        }

        if len(errors) == 0:
            valid_rows.append(processed_row)
        else:
            invalid_rows.append(processed_row)

    summary = {
        'total_rows': len(data_rows),
        'valid_count': len(valid_rows),
        'invalid_count': len(invalid_rows),
    }

    return valid_rows, invalid_rows, summary


def generate_sample_csv():
    """Generate sample CSV content for download."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'item_code', 'design_code', 'name', 'category', 'metal_type',
        'purity', 'gross_weight', 'stone_weight', 'net_weight', 'making_charge', 'selling_price', 'status'
    ])
    sample_rows = [
        ['GLD-RN-101-A', 'DSN-RN-101', '22K Gold Floral Solitaire Ring (Piece 1)', 'Rings', 'Gold', '22K (916)', '5.500', '0.300', '5.200', '2500.00', '48500.00', 'Available'],
        ['GLD-RN-101-B', 'DSN-RN-101', '22K Gold Floral Solitaire Ring (Piece 2)', 'Rings', 'Gold', '22K (916)', '5.650', '0.300', '5.350', '2500.00', '49800.00', 'Available'],
        ['DIA-ER-201-A', 'DSN-ER-201', '18K Diamond Solitaire Studs (0.5ct)', 'Earrings', 'Diamond', '18K / VVS-1', '4.200', '0.400', '3.800', '4500.00', '68000.00', 'Available'],
        ['GLD-NK-301-A', 'DSN-NK-301', 'Royal Antique Temple Gold Necklace', 'Necklaces', 'Gold', '22K (916)', '45.000', '2.500', '42.500', '22000.00', '345000.00', 'Available'],
        ['GLD-CN-401-A', 'DSN-COIN-10G', '24K Pure Gold Minted Coin (10g)', 'Coins & Bars', 'Gold', '24K (999)', '10.000', '0.000', '10.000', '800.00', '78500.00', 'Available'],
        ['SLV-AK-501-A', 'DSN-AK-501', 'Sterling Silver Handcrafted Payal (Anklet)', 'Anklets', 'Silver', '925 Silver', '48.000', '0.000', '48.000', '1200.00', '5600.00', 'Available'],
    ]
    for row in sample_rows:
        writer.writerow(row)
    return output.getvalue()


# ==============================================================================
# IMPORT COMMIT HELPERS
# ==============================================================================

def get_duplicate_rows(invalid_rows):
    """
    Return the subset of `invalid_rows` that failed because of a duplicate Piece ID.

    `validate_import_rows` rejects a Piece ID both when it repeats inside the uploaded
    file and when it already exists in the database, so duplicate problems are reported
    separately from other validation errors on the import preview screen.
    """
    duplicate_rows = []
    for row in invalid_rows:
        errors = row.get('errors', [])
        if any(marker in error for error in errors for marker in DUPLICATE_ERROR_MARKERS):
            duplicate_rows.append(row)
    return duplicate_rows


def create_jewellery_item_from_row(row, category):
    """
    Create and return one `JewelleryItem` from a row produced by `validate_import_rows`.

    The model's own `save()` / `full_clean()` integrity checks are the final safety net,
    so a row that cannot be stored raises `django.core.exceptions.ValidationError`
    (re-raised here with the spreadsheet row number for an actionable error message).
    """
    try:
        return JewelleryItem.objects.create(
            item_code=row['item_code'],
            design_code=row['design_code'] or row['item_code'],
            name=row['name'],
            category=category,
            metal_type=row['metal_type'],
            purity=row['purity'],
            gross_weight=Decimal(row['gross_weight']),
            stone_weight=Decimal(row.get('stone_weight') or '0.000'),
            net_weight=Decimal(row['net_weight']),
            making_charge=Decimal(row['making_charge']),
            selling_price=Decimal(row['selling_price']),
            status=row['status'],
        )
    except ValidationError as exc:
        raise ValidationError(
            f"Row {row.get('row_num', '?')} ('{row.get('item_code', '')}'): "
            f"{'; '.join(exc.messages)}"
        ) from exc


def import_valid_rows(valid_rows, user=None):
    """
    Insert every row of `valid_rows` inside a single atomic database transaction.

    Categories are matched by name and created automatically when they do not exist yet.
    If any single row fails, the whole transaction is rolled back, so the inventory is
    never left with a partially imported file.

    Each created item also gets its opening stock recorded as a `StockMovement`,
    so the stock history of imported items starts from zero like any other item.

    Returns the number of `JewelleryItem` records created.
    """
    imported_count = 0
    with transaction.atomic():
        category_cache = {}
        for row in valid_rows:
            category_name = row['category_name']
            category = category_cache.get(category_name)
            if category is None:
                category, _ = Category.objects.get_or_create(
                    name=category_name,
                    defaults={'description': 'Created automatically during bulk inventory import.'},
                )
                category_cache[category_name] = category

            item = create_jewellery_item_from_row(row, category)
            record_initial_stock(
                item,
                user=user,
                notes='Opening stock recorded by bulk inventory import.',
            )
            imported_count += 1

    return imported_count
