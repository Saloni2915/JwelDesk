"""
Stock tracking helpers for the inventory app.

This module is the single place where stock quantities, stock movements,
low-stock detection and inventory valuation are calculated, so the inventory
views, the sales flow and the admin all share exactly one implementation.

Model recap: a `JewelleryItem` row is one catalogue entry (a unique physical
piece, or a small batch of identical pieces) and ``quantity`` holds how many
pieces are on hand.  *Available* stock only counts pieces whose status is
``Available`` - reserved pieces are on the premises but not sellable, and sold
pieces have left the shop.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import (
    Case, Count, DecimalField, F, IntegerField, Q, Sum, When,
)
from django.db.models.functions import Coalesce

from .models import JewelleryItem, StockMovement

#: Pieces left in stock at (or below) which a design counts as "low stock".
DEFAULT_LOW_STOCK_THRESHOLD = 1
MAX_LOW_STOCK_THRESHOLD = 1000

MONEY_FIELD = DecimalField(max_digits=20, decimal_places=2)
WEIGHT_FIELD = DecimalField(max_digits=20, decimal_places=3)

STOCK_STATUS_FILTERS = [
    ('available', 'In Stock'),
    ('low_stock', 'Low Stock'),
    ('out_of_stock', 'Out of Stock'),
    ('reserved', 'Reserved'),
]


# ==============================================================================
# LOW STOCK CONFIGURATION
# ==============================================================================

def get_low_stock_threshold(override=None):
    """
    Return the low-stock threshold in pieces.

    The value comes from ``settings.INVENTORY_LOW_STOCK_THRESHOLD`` and can be
    overridden per request (the inventory pages accept ``?threshold=``), so a
    shop can tune the rule without a code change. Invalid input always falls
    back to the configured default.
    """
    value = override
    if value in (None, ''):
        value = getattr(settings, 'INVENTORY_LOW_STOCK_THRESHOLD',
                        DEFAULT_LOW_STOCK_THRESHOLD)
    try:
        threshold = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LOW_STOCK_THRESHOLD
    return max(0, min(threshold, MAX_LOW_STOCK_THRESHOLD))


def _available_quantity():
    """Pieces in stock: the quantity of an `Available` item, else zero."""
    return Case(
        When(status='Available', then=F('quantity')),
        default=0,
        output_field=IntegerField(),
    )


# ==============================================================================
# INVENTORY VALUATION / SUMMARY
# ==============================================================================

def inventory_value(queryset=None):
    """
    Total stock value of the given items (defaults to the whole inventory).

    Value reuses the existing pricing field: ``selling_price`` is the price of
    one piece, so the stock value of an item is ``quantity x selling_price``.
    Only pieces that are actually available are valued - sold and reserved
    pieces are excluded, exactly like they are excluded from available stock.
    """
    queryset = JewelleryItem.objects.all() if queryset is None else queryset
    total = queryset.aggregate(total=Coalesce(
        Sum(Case(
            When(status='Available', then=F('quantity') * F('selling_price')),
            default=0,
            output_field=MONEY_FIELD,
        )),
        Decimal('0.00'),
        output_field=MONEY_FIELD,
    ))['total']
    return (total or Decimal('0.00')).quantize(Decimal('0.01'))


def item_stock_value(item):
    """Stock value of a single item (quantity x selling price when available)."""
    return item.estimated_value.quantize(Decimal('0.01'))


def inventory_summary(threshold=None):
    """
    Return the inventory KPI block used by the inventory pages.

    Every number is derived from existing inventory fields (quantity, status,
    metal_type, net_weight, selling_price) - nothing is invented, and no live
    gold/silver rate is used.
    """
    threshold = get_low_stock_threshold(threshold)
    available = _available_quantity()

    totals = JewelleryItem.objects.aggregate(
        total_items=Count('id'),
        total_designs=Count('design_code', distinct=True),
        available_stock=Coalesce(Sum(available), 0, output_field=IntegerField()),
        reserved_stock=Coalesce(
            Sum(Case(When(status='Reserved', then=F('quantity')), default=0,
                     output_field=IntegerField())),
            0, output_field=IntegerField()),
        out_of_stock_items=Count(
            'id', filter=Q(status='Sold') | Q(quantity__lte=0)),
        inventory_value=Coalesce(
            Sum(Case(When(status='Available',
                          then=F('quantity') * F('selling_price')),
                     default=0, output_field=MONEY_FIELD)),
            Decimal('0.00'), output_field=MONEY_FIELD),
        gold_stock=Coalesce(
            Sum(Case(When(Q(status='Available') & Q(metal_type='Gold'),
                          then=F('quantity')), default=0,
                     output_field=IntegerField())),
            0, output_field=IntegerField()),
        gold_weight=Coalesce(
            Sum(Case(When(Q(status='Available') & Q(metal_type='Gold'),
                          then=F('quantity') * F('net_weight')),
                     default=0, output_field=WEIGHT_FIELD)),
            Decimal('0.000'), output_field=WEIGHT_FIELD),
        silver_stock=Coalesce(
            Sum(Case(When(Q(status='Available') & Q(metal_type='Silver'),
                          then=F('quantity')), default=0,
                     output_field=IntegerField())),
            0, output_field=IntegerField()),
        silver_weight=Coalesce(
            Sum(Case(When(Q(status='Available') & Q(metal_type='Silver'),
                          then=F('quantity') * F('net_weight')),
                     default=0, output_field=WEIGHT_FIELD)),
            Decimal('0.000'), output_field=WEIGHT_FIELD),
    )

    designs = low_stock_designs(threshold)
    totals['inventory_value'] = (totals['inventory_value'] or Decimal('0.00')
                                 ).quantize(Decimal('0.01'))
    totals['gold_weight'] = (totals['gold_weight'] or Decimal('0.000')
                             ).quantize(Decimal('0.001'))
    totals['silver_weight'] = (totals['silver_weight'] or Decimal('0.000')
                               ).quantize(Decimal('0.001'))
    totals['low_stock_threshold'] = threshold
    totals['low_stock_designs'] = designs
    totals['low_stock_design_count'] = len(designs)
    totals['low_stock_items'] = sum(d['item_count'] for d in designs)
    return totals


# ==============================================================================
# LOW STOCK DETECTION
# ==============================================================================

def low_stock_design_codes(threshold=None):
    """
    Return the set of design codes that are running low.

    A design is "low stock" when it still has something available (so it is not
    simply out of stock) but the available pieces are at or below the
    threshold. Working per design code reuses the existing model: several
    physical pieces of the same design are separate rows sharing a code.
    """
    threshold = get_low_stock_threshold(threshold)
    rows = (
        JewelleryItem.objects
        .exclude(design_code='')
        .values('design_code')
        .annotate(available=Sum(_available_quantity()))
        .filter(available__gt=0, available__lte=threshold)
    )
    return {row['design_code'] for row in rows}


def low_stock_items(threshold=None):
    """QuerySet of available items whose design is running low."""
    codes = low_stock_design_codes(threshold)
    if not codes:
        return JewelleryItem.objects.none()
    return (JewelleryItem.objects
            .filter(status='Available', quantity__gt=0, design_code__in=codes)
            .select_related('category'))


def low_stock_designs(threshold=None):
    """
    Design-level low stock report for the UI.

    Returns a list of small dicts (design code, name, category, metal, pieces
    left) ordered from the most urgent to the least urgent.
    """
    threshold = get_low_stock_threshold(threshold)
    items = low_stock_items(threshold).order_by('design_code', '-created_at')
    designs = {}
    for item in items:
        design = designs.setdefault(item.design_code, {
            'design_code': item.design_code,
            'name': item.name,
            'category': item.category.name if item.category_id else '',
            'metal_type': item.metal_type,
            'available': 0,
            'item_count': 0,
        })
        design['available'] += item.quantity
        design['item_count'] += 1
    return sorted(designs.values(),
                  key=lambda d: (d['available'], d['design_code']))


# ==============================================================================
# STOCK MOVEMENTS
# ==============================================================================

def _restock_status(status, new_quantity):
    """Status an item ends up in after a stock change."""
    if new_quantity == 0:
        # Nothing left on the shelf: the piece counts as sold/out of stock.
        return 'Sold'
    if status == 'Sold':
        # Stock came back (return / correction): sellable again.
        return 'Available'
    return status


def apply_stock_change(item, change, movement_type, reason='', notes='',
                       user=None, sale=None, lock=True):
    """
    Apply a signed stock change to `item` and record the `StockMovement`.

    This is the only supported way to change stock, so every change is atomic,
    validated and auditable:

    * the row is locked (when ``lock`` is true) and re-read inside a
      transaction before the new quantity is calculated;
    * a change that would push the stock below zero raises `ValidationError`;
    * the movement stores the stock level before and after the change;
    * ``status`` is kept in sync (0 pieces -> Sold, restocked Sold item ->
      Available).

    Returns the created `StockMovement`.
    """
    change = int(change)
    if change == 0:
        raise ValidationError(
            'No stock change to record: the quantity change must not be zero.')

    if user is not None and not getattr(user, 'is_authenticated', False):
        user = None

    with transaction.atomic():
        if lock and item.pk:
            item = JewelleryItem.objects.select_for_update().get(pk=item.pk)
        elif not item.pk:
            # An unsaved item cannot have stock history.
            raise ValidationError('Stock can only be adjusted for a saved item.')

        before = item.quantity or 0
        after = before + change
        if after < 0:
            raise ValidationError(
                f"Cannot remove {abs(change)} piece(s): '{item.item_code}' only has "
                f"{before} piece(s) in stock. Stock can never become negative.")

        movement = StockMovement(
            item=item,
            movement_type=movement_type,
            quantity_change=change,
            stock_before=before,
            stock_after=after,
            reason=reason or '',
            notes=notes or '',
            sale=sale,
            created_by=user,
        )
        movement.full_clean()

        item.quantity = after
        item.status = _restock_status(item.status, after)
        item.save(update_fields=['quantity', 'status', 'updated_at'])
        movement.save()

    return movement


def record_sale(item, sale, user=None, reason='Sale', notes=''):
    """
    Reduce stock by one piece because `item` was sold on `sale`.

    Reused by the sales flow inside its existing transaction, so a completed
    sale can never reduce the stock twice (the movement is only created for the
    sale that is being saved).
    """
    notes = notes or f'Sale #{sale.pk} to {sale.customer.name}'
    return apply_stock_change(
        item, -1, StockMovement.SALE,
        reason=reason, notes=notes, user=user, sale=sale)


def record_initial_stock(item, user=None, reason='New Stock Received',
                         notes='Initial stock recorded when the item was created.'):
    """
    Record the opening stock of a newly created item.

    The item already carries its opening quantity, so this only writes the
    matching audit entry (0 -> quantity) instead of applying another change.
    """
    if not item.pk or not item.quantity:
        return None

    if user is not None and not getattr(user, 'is_authenticated', False):
        user = None

    movement = StockMovement(
        item=item,
        movement_type=StockMovement.ADDITION,
        quantity_change=item.quantity,
        stock_before=0,
        stock_after=item.quantity,
        reason=reason or '',
        notes=notes or '',
        created_by=user,
    )
    movement.full_clean()
    movement.save()
    return movement

