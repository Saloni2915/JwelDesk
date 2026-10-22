"""
sales/invoice_utils.py
----------------------
Standard Indian Jewellery Tax Invoice calculations, state derivations,
and currency-to-words formatting for JewelDesk.

Complies with:
- Section 31 of the CGST Act 2017 (Tax Invoice rules).
- HSN 7113 (Articles of jewellery of precious metal).
- 3% GST structure on precious jewellery (1.5% CGST + 1.5% SGST).
- Optional Non-GST Cash Memo / Retail Invoice mode.
- Exact Indian currency denomination in words (Rupees & Paise).
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Tuple


# Standard 2-digit Indian GST State Codes
GST_STATE_MAP = {
    '01': 'Jammu & Kashmir', '02': 'Himachal Pradesh', '03': 'Punjab', '04': 'Chandigarh',
    '05': 'Uttarakhand', '06': 'Haryana', '07': 'Delhi', '08': 'Rajasthan',
    '09': 'Uttar Pradesh', '10': 'Bihar', '11': 'Sikkim', '12': 'Arunachal Pradesh',
    '13': 'Nagaland', '14': 'Manipur', '15': 'Mizoram', '16': 'Tripura',
    '17': 'Meghalaya', '18': 'Assam', '19': 'West Bengal', '20': 'Jharkhand',
    '21': 'Odisha', '22': 'Chhattisgarh', '23': 'Madhya Pradesh', '24': 'Gujarat',
    '26': 'Dadra & Nagar Haveli', '27': 'Maharashtra', '28': 'Andhra Pradesh',
    '29': 'Karnataka', '30': 'Goa', '31': 'Lakshadweep', '32': 'Kerala',
    '33': 'Tamil Nadu', '34': 'Puducherry', '35': 'Andaman & Nicobar',
    '36': 'Telangana', '37': 'Andhra Pradesh', '38': 'Ladakh'
}


def get_state_from_gstin(gstin: str, default_state: str = 'Maharashtra', default_code: str = '27') -> Tuple[str, str]:
    """Extract State Name and 2-digit State Code from a 15-character GSTIN."""
    if gstin and len(str(gstin).strip()) >= 2:
        code = str(gstin).strip()[:2]
        if code in GST_STATE_MAP:
            return GST_STATE_MAP[code], code
    return default_state, default_code


def num_to_words_indian(n: int) -> str:
    """Convert an integer up to 99,99,99,999 into Indian numbering words."""
    units = [
        '', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
        'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
        'Seventeen', 'Eighteen', 'Nineteen'
    ]
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    if n == 0:
        return 'Zero'

    def two_digits(num: int) -> str:
        if num < 20:
            return units[num]
        return (tens[num // 10] + (' ' + units[num % 10] if num % 10 != 0 else '')).strip()

    def three_digits(num: int) -> str:
        h = num // 100
        rem = num % 100
        res = ''
        if h > 0:
            res += units[h] + ' Hundred'
        if rem > 0:
            res += (' ' if res else '') + two_digits(rem)
        return res.strip()

    crores = n // 10000000
    n %= 10000000
    lakhs = n // 100000
    n %= 100000
    thousands = n // 1000
    n %= 1000
    hundreds = n

    parts = []
    if crores > 0:
        parts.append(num_to_words_indian(crores) + ' Crore')
    if lakhs > 0:
        parts.append(two_digits(lakhs) + ' Lakh')
    if thousands > 0:
        parts.append(two_digits(thousands) + ' Thousand')
    if hundreds > 0:
        parts.append(three_digits(hundreds))

    return ' '.join(parts).strip()


def amount_to_words_inr(amount) -> str:
    """
    Format numeric currency amount into formal Indian Currency Words.
    e.g. 54250.00 -> "Rupees Fifty-Four Thousand Two Hundred Fifty Only"
    """
    try:
        amt = Decimal(str(amount))
    except Exception:
        return ''

    rupees = int(amt)
    paise = int(round((amt - Decimal(rupees)) * 100))

    r_words = num_to_words_indian(rupees)
    if paise > 0:
        p_words = num_to_words_indian(paise)
        return f"Rupees {r_words} and {p_words} Paise Only"
    return f"Rupees {r_words} Only"


def calculate_invoice_breakdown(sale, include_gst: bool = True) -> Dict[str, Any]:
    """
    Compute authentic Indian jewellery invoice breakdown for a given Sale.
    All calculations guarantee that (Taxable + CGST + SGST + RoundOff) == sale.sale_price.
    """
    item = getattr(sale, 'jewellery_item', None)
    sale_price = Decimal(str(sale.sale_price or '0.00'))

    # Extract weights
    gross_weight = Decimal('0.000')
    stone_weight = Decimal('0.000')
    net_weight = Decimal('0.000')

    if item:
        if getattr(item, 'gross_weight', None) is not None:
            gross_weight = Decimal(str(item.gross_weight)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
        if getattr(item, 'stone_weight', None) is not None:
            stone_weight = Decimal(str(item.stone_weight)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
        if getattr(item, 'net_weight', None) is not None:
            net_weight = Decimal(str(item.net_weight)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
        else:
            net_weight = max(Decimal('0.000'), gross_weight - stone_weight)

    # Making charges & other charges if stored on item
    making_charge_rate = Decimal('0.00')
    making_charges = Decimal('0.00')
    making_charge_type = 'Fixed Amount'
    if item and getattr(item, 'making_charge', None):
        making_charge_rate = Decimal(str(item.making_charge))
        making_charge_type = getattr(item, 'making_charge_type', 'Fixed Amount')
        if making_charge_type == 'Per Gram':
            making_charges = (making_charge_rate * gross_weight).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        elif making_charge_type == 'Fixed Amount':
            making_charges = making_charge_rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # Tax & Subtotals
    if include_gst:
        taxable_value = (sale_price / Decimal('1.03')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        cgst_rate = Decimal('1.5')
        sgst_rate = Decimal('1.5')
        cgst_amount = (taxable_value * Decimal('0.015')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        sgst_amount = (taxable_value * Decimal('0.015')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_tax = cgst_amount + sgst_amount
        round_off = (sale_price - (taxable_value + total_tax)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    else:
        taxable_value = sale_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        cgst_rate = Decimal('0.0')
        sgst_rate = Decimal('0.0')
        cgst_amount = Decimal('0.00')
        sgst_amount = Decimal('0.00')
        total_tax = Decimal('0.00')
        round_off = Decimal('0.00')

    # Effective precious metal rate per gram (INR/g)
    if net_weight > 0:
        metal_amount = taxable_value - making_charges if taxable_value > making_charges else taxable_value
        rate_per_gram = (metal_amount / net_weight).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    else:
        rate_per_gram = Decimal('0.00')

    # Old gold exchange adjustment if linked
    old_gold_value = Decimal('0.00')
    og = getattr(sale, 'old_gold_exchange', None)
    if og and getattr(og, 'status', None) == 'Completed':
        old_gold_value = Decimal(str(og.final_value or '0.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # Coupon discount if applied
    coupon_discount = getattr(sale, 'coupon_discount', Decimal('0.00')) or Decimal('0.00')
    applied_coupon_code = getattr(sale, 'applied_coupon_code', '') or ''
    original_price = getattr(sale, 'original_price', None) or (sale_price + coupon_discount)

    return {
        'include_gst': include_gst,
        'title': 'TAX INVOICE' if include_gst else 'RETAIL INVOICE / CASH MEMO',
        'subtitle': 'Issued under Section 31 of CGST Act, 2017' if include_gst else 'Non-GST Retail Supply / Cash Memo',
        'hsn_code': '7113',  # Standard gold and silver jewellery HSN
        'gross_weight': gross_weight,
        'stone_weight': stone_weight,
        'net_weight': net_weight,
        'making_charge_type': making_charge_type,
        'making_charge_rate': making_charge_rate,
        'making_charges': making_charges,
        'rate_per_gram': rate_per_gram,
        'taxable_value': taxable_value,
        'cgst_rate': cgst_rate,
        'sgst_rate': sgst_rate,
        'cgst_amount': cgst_amount,
        'sgst_amount': sgst_amount,
        'total_tax': total_tax,
        'round_off': round_off,
        'grand_total': sale_price,
        'original_price': original_price,
        'coupon_discount': coupon_discount,
        'applied_coupon_code': applied_coupon_code,
        'old_gold_value': old_gold_value,
        'amount_in_words': amount_to_words_inr(sale_price),
    }
