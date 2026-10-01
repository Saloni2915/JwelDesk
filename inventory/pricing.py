"""
inventory/pricing.py
--------------------
Jewellery Pricing Engine for JewelDesk.

Accurately calculates retail and estimate jewellery prices in Indian Rupees (INR)
according to jewellery industry conventions.

Price Breakdown Formula:
    Metal Value
  + Wastage
  + Making Charges
  + Stone Charges
  + Other Charges
  + GST / Tax
  = Final Selling Price

Handles:
  - Gold, Silver, Platinum and Diamond jewellery
  - Purity parsing (24K, 22K/916, 18K/750, 14K/585, 925 Sterling Silver, etc.)
  - Gross vs Net metal weight fallback
  - Wastage (percentage of metal value or fixed amount)
  - Making charges (Fixed amount, Per gram, or Percentage of metal value)
  - Stone / Diamond charges
  - Other charges (hallmarking, certifications, rhodium)
  - Configurable GST (default 3.0% under Indian GST HSN 7113)
  - Zero/missing optional charges handled safely without throwing exceptions
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from dataclasses import dataclass, asdict
import re
from typing import Optional, Dict, Any


DEFAULT_GST_RATE = Decimal('3.00')

# Fallback default rates in INR per gram if neither database nor API has a value
FALLBACK_GOLD_24K_RATE = Decimal('7500.00')   # 24K Gold (₹7,500/g = ~₹75,000/10g)
FALLBACK_SILVER_999_RATE = Decimal('95.00')   # 999 Fine Silver (₹95/g = ~₹95,000/kg)
FALLBACK_PLATINUM_RATE = Decimal('3200.00')   # Pt 950 Platinum


def to_decimal(val, default='0.00') -> Decimal:
    """Safely convert any numeric/string value to Decimal."""
    if val is None or val == '':
        return Decimal(str(default))
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(str(default))


def round_curr(val: Decimal) -> Decimal:
    """Round to 2 decimal places using standard ROUND_HALF_UP."""
    if not isinstance(val, Decimal):
        val = to_decimal(val)
    return val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def round_wt(val: Decimal) -> Decimal:
    """Round weight to 3 decimal places (milligrams)."""
    if not isinstance(val, Decimal):
        val = to_decimal(val, '0.000')
    return val.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)


# Standard purity conversion factors relative to 24K pure Gold / 999 Silver
GOLD_KARAT_MAP = {
    24: Decimal('1.000000'),      # 24/24 = 1.0 (999 fineness)
    23: Decimal('23') / Decimal('24'),
    22: Decimal('22') / Decimal('24'), # 22/24 = 0.916667 (916 fineness)
    21: Decimal('21') / Decimal('24'),
    20: Decimal('20') / Decimal('24'),
    18: Decimal('18') / Decimal('24'), # 18/24 = 0.750000 (750 fineness)
    14: Decimal('14') / Decimal('24'), # 14/24 = 0.583333 (585 fineness)
    10: Decimal('10') / Decimal('24'), # 10/24 = 0.416667
    9:  Decimal('9')  / Decimal('24'), # 9/24  = 0.375000
}

MILLIS_MAP = {
    999: Decimal('1.000000'),
    958: Decimal('23') / Decimal('24'),
    916: Decimal('22') / Decimal('24'),
    875: Decimal('21') / Decimal('24'),
    833: Decimal('20') / Decimal('24'),
    750: Decimal('18') / Decimal('24'),
    585: Decimal('14') / Decimal('24'),
    417: Decimal('10') / Decimal('24'),
    375: Decimal('9')  / Decimal('24'),
}


def parse_purity_factor(metal_type: str, purity_str: str) -> Decimal:
    """
    Parse a jewellery purity string and return the purity factor (0.0 to 1.0).
    
    Examples:
      - Gold "22K (916)", "22K", "916" -> Decimal('22') / Decimal('24') (~0.916667)
      - Gold "18K (750)", "18K"         -> Decimal('18') / Decimal('24') (0.75)
      - Gold "24K (999)", "24K"         -> Decimal('1.000000')
      - Silver "925 Sterling Silver"     -> Decimal('0.925000')
      - Silver "999", "Fine Silver"     -> Decimal('1.000000')
      - Platinum "Pt 950"               -> Decimal('0.950000')
    """
    m_type = (metal_type or '').strip().title()
    text = (purity_str or '').strip().upper()

    if not text:
        if m_type == 'Silver':
            return Decimal('0.925000') # Standard sterling
        return Decimal('22') / Decimal('24') # Standard 22K gold

    # Gold or Diamond (in diamond jewellery, the setting is usually gold/platinum)
    if m_type in ('Gold', 'Diamond'):
        # 1. Look for Karat: e.g. "24K", "22 K", "18KT"
        k_match = re.search(r'\b(24|23|22|21|20|18|14|10|9)\s*K(?:T)?\b', text)
        if k_match:
            k_val = int(k_match.group(1))
            return GOLD_KARAT_MAP.get(k_val, Decimal(k_val) / Decimal(24))

        # 2. Look for 3-digit millesimal fineness: e.g. "916", "750", "999"
        m_match = re.search(r'\b(999|958|916|875|833|750|585|417|375)\b', text)
        if m_match:
            m_val = int(m_match.group(1))
            return MILLIS_MAP.get(m_val, Decimal(m_val) / Decimal(1000))

        # 3. Look for plain karat number if preceded/followed by gold keywords
        if '24' in text:
            return GOLD_KARAT_MAP[24]
        if '22' in text:
            return GOLD_KARAT_MAP[22]
        if '18' in text:
            return GOLD_KARAT_MAP[18]
        if '14' in text:
            return GOLD_KARAT_MAP[14]

        # Default gold standard in India is 22K
        return GOLD_KARAT_MAP[22]

    elif m_type == 'Silver':
        if '999' in text or 'FINE' in text:
            return Decimal('1.000000')
        if '925' in text or 'STERLING' in text:
            return Decimal('0.925000')
        if '900' in text:
            return Decimal('0.900000')
        if '850' in text:
            return Decimal('0.850000')
        if '800' in text:
            return Decimal('0.800000')
        # Default silver standard is 925 sterling
        return Decimal('0.925000')

    elif m_type == 'Platinum':
        if '950' in text:
            return Decimal('0.950000')
        if '900' in text:
            return Decimal('0.900000')
        return Decimal('0.950000')

    return Decimal('1.000000')


def get_current_metal_rate(metal_type: str = 'Gold') -> Decimal:
    """
    Fetch the active base rate per gram in INR.
    Priority:
      1. MetalRate model row in DB (manually set or cached daily shop rate)
      2. Cached API snapshot from inventory.metal_prices
      3. Fallback default
    """
    m_type = (metal_type or 'Gold').strip().title()
    # Treat Diamond as Gold for base rate calculation
    if m_type == 'Diamond':
        m_type = 'Gold'

    # 1. DB lookup
    try:
        from .models import MetalRate
        rate_obj = MetalRate.objects.filter(metal_type=m_type).first()
        if rate_obj and rate_obj.rate_per_gram > 0:
            return to_decimal(rate_obj.rate_per_gram)
    except Exception:
        pass

    # 2. Cache/API snapshot
    try:
        from . import metal_prices
        snapshot = metal_prices.get_price_snapshot()
        if snapshot and snapshot.get('available'):
            if m_type == 'Gold' and snapshot.get('gold_price_per_gram'):
                return to_decimal(snapshot['gold_price_per_gram'])
            elif m_type == 'Silver' and snapshot.get('silver_price_per_gram'):
                return to_decimal(snapshot['silver_price_per_gram'])
    except Exception:
        pass

    # 3. Fallbacks
    if m_type == 'Silver':
        return FALLBACK_SILVER_999_RATE
    elif m_type == 'Platinum':
        return FALLBACK_PLATINUM_RATE
    return FALLBACK_GOLD_24K_RATE


@dataclass
class PriceBreakdown:
    """Itemized breakdown of a jewellery pricing calculation."""
    metal_type: str
    purity: str
    purity_factor: Decimal

    # Weights in grams
    gross_weight: Decimal
    stone_weight: Decimal
    net_weight: Decimal
    metal_weight: Decimal  # Weight actually used for precious metal value

    # Rates
    base_rate_per_gram: Decimal       # Rate for 24K Gold / 999 Silver
    effective_rate_per_gram: Decimal  # Base rate * purity factor

    # Component Amounts in INR
    metal_value: Decimal
    wastage_percent: Decimal
    wastage_amount: Decimal
    making_charge_type: str
    making_charge_rate: Decimal
    making_charge_amount: Decimal
    stone_charges: Decimal
    other_charges: Decimal
    other_charges_description: str

    # Subtotals & Tax
    subtotal: Decimal          # Taxable value before GST
    tax_percent: Decimal       # GST %
    tax_amount: Decimal        # GST in INR
    final_price: Decimal       # Final selling price (subtotal + tax)

    def to_dict(self) -> Dict[str, Any]:
        """Convert breakdown to a JSON-serializable dictionary."""
        return {
            'metal_type': self.metal_type,
            'purity': self.purity,
            'purity_factor': float(round_curr(self.purity_factor * Decimal('100'))),
            'gross_weight': float(round_wt(self.gross_weight)),
            'stone_weight': float(round_wt(self.stone_weight)),
            'net_weight': float(round_wt(self.net_weight)),
            'metal_weight': float(round_wt(self.metal_weight)),
            'base_rate_per_gram': float(round_curr(self.base_rate_per_gram)),
            'effective_rate_per_gram': float(round_curr(self.effective_rate_per_gram)),
            'metal_value': float(round_curr(self.metal_value)),
            'wastage_percent': float(round_curr(self.wastage_percent)),
            'wastage_amount': float(round_curr(self.wastage_amount)),
            'making_charge_type': self.making_charge_type,
            'making_charge_rate': float(round_curr(self.making_charge_rate)),
            'making_charge_amount': float(round_curr(self.making_charge_amount)),
            'stone_charges': float(round_curr(self.stone_charges)),
            'other_charges': float(round_curr(self.other_charges)),
            'other_charges_description': self.other_charges_description,
            'subtotal': float(round_curr(self.subtotal)),
            'tax_percent': float(round_curr(self.tax_percent)),
            'tax_amount': float(round_curr(self.tax_amount)),
            'final_price': float(round_curr(self.final_price)),
        }


def calculate_jewellery_price(
    metal_type: str = 'Gold',
    purity: str = '22K',
    gross_weight: Decimal = Decimal('0.000'),
    stone_weight: Decimal = Decimal('0.000'),
    net_weight: Optional[Decimal] = None,
    base_metal_rate: Optional[Decimal] = None,
    wastage_percent: Decimal = Decimal('0.00'),
    wastage_amount: Optional[Decimal] = None,
    making_charge: Decimal = Decimal('0.00'),
    making_charge_type: str = 'Fixed Amount',
    stone_charges: Decimal = Decimal('0.00'),
    other_charges: Decimal = Decimal('0.00'),
    other_charges_description: str = '',
    tax_percent: Decimal = DEFAULT_GST_RATE,
) -> PriceBreakdown:
    """
    Perform a complete jewellery price calculation.

    Parameters:
      - metal_type: 'Gold', 'Silver', 'Diamond', 'Platinum'
      - purity: e.g. '22K', '18K', '925'
      - gross_weight: total physical weight of piece in grams
      - stone_weight: non-metal weight (stones, pearls, wax) in grams
      - net_weight: precious metal weight in grams (if not provided, auto-calculated as gross - stone)
      - base_metal_rate: rate per gram of pure metal (24K Gold or 999 Silver). If None, current active rate is used.
      - wastage_percent: wastage as a % of metal value (e.g. 3.0 = 3%)
      - wastage_amount: explicit wastage amount in INR (takes priority over percentage if > 0)
      - making_charge: making charge value
      - making_charge_type: 'Fixed Amount' (Rs.), 'Per Gram' (Rs./g on gross weight), or 'Percentage' (% of metal value)
      - stone_charges: total diamond / gemstone charges in INR
      - other_charges: hallmarking, packaging, rhodium in INR
      - other_charges_description: note describing other charges
      - tax_percent: GST rate percentage (default 3.0%)

    Returns:
      PriceBreakdown dataclass with all computed components and final price.
    """
    # 1. Weights
    g_wt = max(Decimal('0.000'), to_decimal(gross_weight, '0.000'))
    s_wt = max(Decimal('0.000'), to_decimal(stone_weight, '0.000'))

    if net_weight is not None and str(net_weight).strip() != '':
        n_wt = max(Decimal('0.000'), to_decimal(net_weight, '0.000'))
    else:
        n_wt = max(Decimal('0.000'), g_wt - s_wt)

    # In jewellery trade, if net weight > 0, it is used for metal pricing; otherwise gross weight
    metal_wt = n_wt if n_wt > 0 else g_wt

    # 2. Purity & Base Rate
    m_type = (metal_type or 'Gold').strip().title()
    p_factor = parse_purity_factor(m_type, str(purity or ''))

    if base_metal_rate is not None and to_decimal(base_metal_rate) > 0:
        base_rate = to_decimal(base_metal_rate)
    else:
        base_rate = get_current_metal_rate(m_type)

    effective_rate = round_curr(base_rate * p_factor)

    # 3. Metal Value = Metal Weight * Effective Rate
    metal_val = round_curr(metal_wt * effective_rate)

    # 4. Wastage
    w_pct = max(Decimal('0.00'), to_decimal(wastage_percent, '0.00'))
    w_amt_input = to_decimal(wastage_amount, '0.00') if wastage_amount is not None else Decimal('0.00')

    if w_amt_input > 0:
        calc_wastage = round_curr(w_amt_input)
    elif w_pct > 0 and metal_val > 0:
        calc_wastage = round_curr(metal_val * (w_pct / Decimal('100')))
    else:
        calc_wastage = Decimal('0.00')

    # 5. Making Charges
    mc_rate = max(Decimal('0.00'), to_decimal(making_charge, '0.00'))
    mc_type = (making_charge_type or 'Fixed Amount').strip().title()
    if 'Per Gram' in mc_type or 'Per_Gram' in mc_type:
        charge_wt = g_wt if g_wt > 0 else metal_wt
        calc_mc = round_curr(mc_rate * charge_wt)
        normalized_mc_type = 'Per Gram'
    elif 'Percent' in mc_type:
        calc_mc = round_curr(metal_val * (mc_rate / Decimal('100')))
        normalized_mc_type = 'Percentage'
    else:
        calc_mc = round_curr(mc_rate)
        normalized_mc_type = 'Fixed Amount'

    # 6. Stone Charges & Other Charges
    calc_stones = max(Decimal('0.00'), round_curr(to_decimal(stone_charges, '0.00')))
    calc_others = max(Decimal('0.00'), round_curr(to_decimal(other_charges, '0.00')))

    # 7. Subtotal (Taxable Value)
    subtotal = round_curr(metal_val + calc_wastage + calc_mc + calc_stones + calc_others)

    # 8. GST / Tax
    t_pct = max(Decimal('0.00'), to_decimal(tax_percent, '0.00'))
    tax_amt = round_curr(subtotal * (t_pct / Decimal('100')))

    # 9. Final Selling Price
    final_price = round_curr(subtotal + tax_amt)

    return PriceBreakdown(
        metal_type=m_type,
        purity=str(purity or '').strip(),
        purity_factor=p_factor,
        gross_weight=g_wt,
        stone_weight=s_wt,
        net_weight=n_wt,
        metal_weight=metal_wt,
        base_rate_per_gram=base_rate,
        effective_rate_per_gram=effective_rate,
        metal_value=metal_val,
        wastage_percent=w_pct,
        wastage_amount=calc_wastage,
        making_charge_type=normalized_mc_type,
        making_charge_rate=mc_rate,
        making_charge_amount=calc_mc,
        stone_charges=calc_stones,
        other_charges=calc_others,
        other_charges_description=str(other_charges_description or '').strip(),
        subtotal=subtotal,
        tax_percent=t_pct,
        tax_amount=tax_amt,
        final_price=final_price,
    )


def calculate_item_price(item, base_rate=None, tax_percent=DEFAULT_GST_RATE) -> PriceBreakdown:
    """Calculate the live market price breakdown for an existing JewelleryItem."""
    return calculate_jewellery_price(
        metal_type=getattr(item, 'metal_type', 'Gold'),
        purity=getattr(item, 'purity', '22K'),
        gross_weight=getattr(item, 'gross_weight', Decimal('0.000')),
        stone_weight=getattr(item, 'stone_weight', Decimal('0.000')),
        net_weight=getattr(item, 'net_weight', None),
        base_metal_rate=base_rate,
        wastage_percent=getattr(item, 'wastage_percent', Decimal('0.00')),
        making_charge=getattr(item, 'making_charge', Decimal('0.00')),
        making_charge_type=getattr(item, 'making_charge_type', 'Fixed Amount'),
        stone_charges=getattr(item, 'stone_charges', Decimal('0.00')),
        other_charges=getattr(item, 'other_charges', Decimal('0.00')),
        tax_percent=tax_percent,
    )
