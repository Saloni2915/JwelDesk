"""
wholesale/pricing_service.py
----------------------------
Pricing service for wholesale orders, integrating pricing rules, bulk discounts,
making charge discounts, and GST calculation.
"""

from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Q
from inventory import pricing
from .models import WholesalePricingRule


def get_wholesale_item_price(item, party=None, quantity=1):
    """
    Determine the wholesale price for an item based on the best applicable
    WholesalePricingRule for the given party, category, or individual piece.

    Returns dict:
      {
         'unit_price': Decimal,
         'base_price': Decimal,
         'discount_percent': Decimal,
         'rule_applied': WholesalePricingRule or None,
         'making_charge': Decimal,
         'wastage_percent': Decimal,
         'tax_rate': Decimal,
      }
    """
    tenant = item.tenant
    base_price = item.selling_price or Decimal('0.00')
    tax_rate = pricing.DEFAULT_GST_RATE

    rules_qs = WholesalePricingRule.objects.filter(
        tenant=tenant,
        is_active=True,
        minimum_order_quantity__lte=quantity
    ).filter(
        Q(party=party) | Q(party__isnull=True)
    ).filter(
        Q(item=item) | Q(category=item.category) | (Q(item__isnull=True) & Q(category__isnull=True))
    )

    # Prioritize specific rules: Item > Category > Global, Party-specific > General
    # Sort order: item is not null (0 vs 1), category is not null (0 vs 1), party is not null (0 vs 1)
    best_rule = None
    for rule in rules_qs:
        if rule.item_id == item.id and rule.party_id == getattr(party, 'id', None):
            best_rule = rule
            break
    if not best_rule:
        for rule in rules_qs:
            if rule.item_id == item.id:
                best_rule = rule
                break
    if not best_rule:
        for rule in rules_qs:
            if rule.category_id == item.category_id and rule.party_id == getattr(party, 'id', None):
                best_rule = rule
                break
    if not best_rule:
        for rule in rules_qs:
            if rule.category_id == item.category_id:
                best_rule = rule
                break
    if not best_rule:
        best_rule = rules_qs.first()

    discount_pct = Decimal('0.00')
    making_charge = item.making_charge or Decimal('0.00')
    wastage_percent = item.wastage_percent or Decimal('0.00')

    if best_rule:
        if best_rule.fixed_price_override is not None and best_rule.fixed_price_override > 0:
            unit_price = best_rule.fixed_price_override
            return {
                'unit_price': unit_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
                'base_price': base_price,
                'discount_percent': Decimal('0.00'),
                'rule_applied': best_rule,
                'making_charge': making_charge,
                'wastage_percent': wastage_percent,
                'tax_rate': tax_rate,
            }
        discount_pct = best_rule.discount_percent or Decimal('0.00')
        if best_rule.making_charge_discount_percent:
            mc_disc = best_rule.making_charge_discount_percent / Decimal('100.00')
            making_charge = (making_charge * (Decimal('1.00') - mc_disc)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # Calculate final unit price
    factor = (Decimal('100.00') - discount_pct) / Decimal('100.00')
    unit_price = (base_price * factor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return {
        'unit_price': unit_price,
        'base_price': base_price,
        'discount_percent': discount_pct,
        'rule_applied': best_rule,
        'making_charge': making_charge,
        'wastage_percent': wastage_percent,
        'tax_rate': tax_rate,
    }
