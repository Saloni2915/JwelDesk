"""
wholesale/stock_service.py
--------------------------
Atomic stock management, allocation, dispatch, and return restocking for Wholesale.
Directly interfaces with `inventory.stock.apply_stock_change` to prevent negative stock,
double deductions, or unrecorded movements.
"""

from decimal import Decimal
import logging
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from inventory.models import JewelleryItem, StockMovement
from inventory.stock import apply_stock_change
from .models import (
    WholesaleOrder,
    WholesaleOrderItem,
    WholesaleDispatch,
    WholesaleDispatchItem,
    WholesaleSequence,
    WholesaleReturn,
    WholesaleReturnItem,
)

logger = logging.getLogger('wholesale.stock_service')


def validate_order_stock_availability(order):
    """
    Check whether all line items in the order have sufficient stock available.
    Returns (is_available, error_messages_list).
    """
    errors = []
    for line in order.items.select_related('item').all():
        item = line.item
        avail = item.in_stock_quantity
        if avail < line.quantity:
            errors.append(
                f"Insufficient stock for '{item.name}' ({item.item_code}): "
                f"Order requires {line.quantity}, but only {avail} currently available."
            )
    return (len(errors) == 0, errors)


def confirm_wholesale_order(order, user=None):
    """
    Transition order from DRAFT to CONFIRMED inside an atomic transaction.
    Verifies stock availability and reserves items if necessary.
    """
    with transaction.atomic():
        order = WholesaleOrder.objects.select_for_update().get(pk=order.pk)
        if order.status != WholesaleOrder.STATUS_DRAFT:
            raise ValidationError(f"Cannot confirm order in '{order.status}' status.")

        is_avail, errors = validate_order_stock_availability(order)
        if not is_avail:
            raise ValidationError("Cannot confirm order due to insufficient stock:\n" + "\n".join(errors))

        order.status = WholesaleOrder.STATUS_CONFIRMED
        order.save(update_fields=['status', 'updated_at'])
        return order


def execute_wholesale_dispatch(order, dispatch_items_data, courier_name='', tracking_number='', notes='', user=None):
    """
    Dispatch stock for an order atomically:
      1. Validates quantities against remaining dispatchable quantities.
      2. Creates WholesaleDispatch and WholesaleDispatchItem records.
      3. Performs atomic physical stock reduction via `apply_stock_change`.
      4. Updates order line item `dispatched_quantity`.
      5. Automatically progresses order status to DISPATCHED or COMPLETED if all items fulfilled.
    
    dispatch_items_data format:
      [ {'order_item_id': 123, 'quantity': 2, 'tag_number': 'JWL-000001'}, ... ]
    """
    tenant = order.tenant
    with transaction.atomic():
        order = WholesaleOrder.objects.select_for_update().get(pk=order.pk)
        if order.status in (WholesaleOrder.STATUS_DRAFT, WholesaleOrder.STATUS_CANCELLED, WholesaleOrder.STATUS_COMPLETED):
            raise ValidationError(f"Cannot dispatch order in '{order.status}' status.")

        if not dispatch_items_data:
            raise ValidationError("At least one item must be included in the dispatch.")

        # Generate unique dispatch number
        dispatch_num = WholesaleSequence.get_next_number(tenant, 'dispatch', prefix='WDSP')

        dispatch = WholesaleDispatch.objects.create(
            tenant=tenant,
            dispatch_number=dispatch_num,
            order=order,
            party=order.party,
            dispatch_date=timezone.now(),
            courier_name=courier_name,
            tracking_number=tracking_number,
            notes=notes,
            created_by=user,
            status=WholesaleDispatch.STATUS_DELIVERED
        )

        for item_data in dispatch_items_data:
            order_item_id = item_data.get('order_item_id')
            qty = int(item_data.get('quantity', 0))
            if qty <= 0:
                continue

            order_item = WholesaleOrderItem.objects.select_for_update().get(pk=order_item_id, order=order)
            remaining = order_item.remaining_dispatch_quantity
            if qty > remaining:
                raise ValidationError(
                    f"Cannot dispatch {qty} units of '{order_item.item.name}': "
                    f"Only {remaining} remaining to be dispatched on this order."
                )

            # Atomically lock the JewelleryItem
            jewellery_item = JewelleryItem.objects.select_for_update().get(pk=order_item.item_id)
            if jewellery_item.tenant_id != tenant.id:
                raise ValidationError("Cross-tenant item access detected!")

            # Deduct physical stock via centralized apply_stock_change
            movement_notes = (
                f"Wholesale Dispatch #{dispatch.dispatch_number} for Order #{order.order_number} "
                f"to Retailer {order.party.name}"
            )
            apply_stock_change(
                item=jewellery_item,
                change=-qty,
                movement_type=StockMovement.REDUCTION,
                reason='Wholesale Dispatch',
                notes=movement_notes,
                user=user,
                lock=False  # Already locked with select_for_update
            )

            # Record dispatch item
            WholesaleDispatchItem.objects.create(
                dispatch=dispatch,
                order_item=order_item,
                item=jewellery_item,
                quantity=qty,
                tag_number=item_data.get('tag_number') or jewellery_item.tag_number or ''
            )

            # Update fulfilled quantity on order item
            order_item.dispatched_quantity += qty
            order_item.save(update_fields=['dispatched_quantity'])

        # Check order fulfillment status
        if order.is_fully_dispatched:
            order.status = WholesaleOrder.STATUS_DISPATCHED
        else:
            order.status = WholesaleOrder.STATUS_PROCESSING
        order.save(update_fields=['status', 'updated_at'])

        return dispatch


def restock_wholesale_return_item(return_item, user=None):
    """
    Restock a single approved return item back into sellable inventory
    if its disposition is 'Sellable'.
    """
    with transaction.atomic():
        return_item = WholesaleReturnItem.objects.select_for_update().get(pk=return_item.pk)
        wholesale_return = return_item.wholesale_return

        if return_item.restocked:
            raise ValidationError("This return line item has already been restocked.")

        if wholesale_return.status not in (WholesaleReturn.STATUS_APPROVED, WholesaleReturn.STATUS_RESTOCKED):
            raise ValidationError(f"Cannot restock items from a return with status '{wholesale_return.status}'.")

        if return_item.disposition != WholesaleReturnItem.DISP_SELLABLE:
            raise ValidationError(f"Only items with 'Sellable' disposition can be restocked into inventory.")

        jewellery_item = JewelleryItem.objects.select_for_update().get(pk=return_item.item_id)
        if jewellery_item.tenant_id != wholesale_return.tenant_id:
            raise ValidationError("Cross-tenant return restock attempted!")

        movement_notes = (
            f"Wholesale Return #{wholesale_return.return_number} from Retailer {wholesale_return.party.name} - "
            f"Restocked into Showroom stock"
        )

        apply_stock_change(
            item=jewellery_item,
            change=return_item.quantity,
            movement_type=StockMovement.ADDITION,
            reason='Wholesale Return',
            notes=movement_notes,
            user=user,
            lock=False
        )

        return_item.restocked = True
        return_item.save(update_fields=['restocked'])

        # If all return items are restocked/processed, update return status
        all_items = list(wholesale_return.items.all())
        all_restocked_or_unsellable = all(
            it.restocked or it.disposition != WholesaleReturnItem.DISP_SELLABLE for it in all_items
        )
        if all_restocked_or_unsellable:
            wholesale_return.status = WholesaleReturn.STATUS_RESTOCKED
            wholesale_return.save(update_fields=['status'])

        return return_item
