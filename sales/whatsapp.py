"""
WhatsApp click-to-chat helpers (Phase 1 - manual send only).

Builds a wa.me URL with a pre-filled thank-you message so the shop user can
open WhatsApp and send it themselves. Nothing is ever sent automatically.
"""
import re
from urllib.parse import quote


SHOP_NAME = "JewelDesk"

# Anything that is not a digit (spaces, +, -, brackets, etc.).
_NON_DIGIT_RE = re.compile(r'\D')

# WhatsApp click-to-chat endpoint.
WA_ME_BASE_URL = "https://wa.me/"


def normalize_phone(raw_number):
    """
    Normalize a phone number for the wa.me click-to-chat URL.

    - Strips every non-digit character (spaces, +, -, brackets...).
    - Indian 10-digit numbers (starting 6-9) get the 91 country code.
    - Numbers already carrying a country code are left untouched.

    Returns the digits-only string, or None when no usable number exists.
    """
    if not raw_number:
        return None

    digits = _NON_DIGIT_RE.sub('', str(raw_number))
    if not digits:
        return None

    # A single leading trunk-prefix 0 (e.g. "098765 43210") is dropped so the
    # number becomes a normal 10-digit Indian mobile.
    if len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]

    if len(digits) == 10 and digits[0] in '6789':
        return '91' + digits

    # Already international (e.g. 919876543210) or otherwise long enough to
    # carry a country code: pass through unchanged.
    if len(digits) >= 11 and digits[0] != '0':
        return digits

    # Too short / otherwise unusable.
    return None


def build_thank_you_message(customer_name, item_name, invoice_reference):
    """Professional, friendly pre-filled WhatsApp thank-you message."""
    return (
        f"Namaste {customer_name}! \n\n"
        f"Thank you for your purchase from {SHOP_NAME}! \n\n"
        f"Your order details:\n"
        f"- Item: {item_name}\n"
        f"- Invoice: {invoice_reference}\n\n"
        f"We hope you cherish your jewellery for years to come. "
        f"For any queries, just reply to this message.\n\n"
        f"Warm regards,\nTeam {SHOP_NAME}"
    )


def build_whatsapp_url(raw_number, message):
    """
    Build a wa.me click-to-chat URL, or None when the number is unusable.
    The message is percent-encoded for safe inclusion in the URL.
    """
    phone = normalize_phone(raw_number)
    if not phone:
        return None
    return f"{WA_ME_BASE_URL}{phone}?text={quote(message)}"


def get_whatsapp_context_for_sale(sale):
    """
    Template context for the sale detail page's WhatsApp button.

    Returns {'whatsapp_url': ..., 'whatsapp_customer_name': ...} when the
    customer has a usable number, otherwise {'whatsapp_unavailable': True}
    so the page can show a clear "number not available" message instead of
    a broken link.
    """
    raw_number = sale.customer.mobile
    phone = normalize_phone(raw_number)
    if not phone:
        return {'whatsapp_unavailable': True}

    invoice_reference = f"INV-{sale.id:05d}"
    message = build_thank_you_message(
        customer_name=sale.customer.name,
        item_name=sale.jewellery_item.name,
        invoice_reference=invoice_reference,
    )
    return {
        'whatsapp_url': build_whatsapp_url(raw_number, message),
        'whatsapp_customer_name': sale.customer.name,
    }
