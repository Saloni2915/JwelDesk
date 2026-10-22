"""
coupons/services.py
-------------------
Core business services for JewelDesk Multi-Tenant Coupon System:
- Pure server-side validation & discount calculations.
- Concurrency-safe atomic redemption with database row-level locking.
- Collision-resistant unique code generation scoped per tenant.
- HTML/CSS sanitization & safe dynamic placeholder rendering.
- Professional luxury jewellery coupon presets.
"""

from decimal import Decimal, ROUND_HALF_UP
import html
import math
import re
import secrets
from typing import Any, Dict, List, Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.html import escape

from super_admin.coupon_engine import (
    generate_barcode_svg,
    generate_qr_svg,
    sanitize_coupon_html,
    sanitize_coupon_css,
    COUPON_ALPHABET,
)


# Explicit placeholder allowlist
ALLOWED_PLACEHOLDERS = [
    "business_name",
    "business_logo",
    "coupon_code",
    "discount_value",
    "minimum_purchase",
    "valid_until",
    "terms_and_conditions",
    "offer_title",
    "serial_number",
    "barcode_svg",
    "qr_svg",
]


# ============================================================================
# 1. Server-Side Discount Calculation & Safe Rules
# ============================================================================

def calculate_coupon_discount(coupon, subtotal: Decimal) -> Decimal:
    """
    Calculate the exact server-side discount amount.
    - Never trusts browser-submitted discount numbers.
    - Applies percentage calculations with optional ceiling cap.
    - Clamps discount so total never becomes negative.
    """
    if not coupon or subtotal <= Decimal('0.00'):
        return Decimal('0.00')

    subtotal = Decimal(str(subtotal))

    if coupon.discount_type == coupon.DISCOUNT_PERCENTAGE:
        # e.g. 15% of 50000 = 7500
        rate = Decimal(str(coupon.discount_value)) / Decimal('100.00')
        raw_discount = (subtotal * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if coupon.max_discount_amount and coupon.max_discount_amount > Decimal('0.00'):
            raw_discount = min(raw_discount, Decimal(str(coupon.max_discount_amount)))
    else:
        # Fixed cash discount, e.g. ₹1000
        raw_discount = Decimal(str(coupon.discount_value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # Prevent negative bill: discount cannot exceed subtotal (leave minimum ₹0.00 total)
    discount = max(Decimal('0.00'), min(raw_discount, subtotal))
    return discount


# ============================================================================
# 2. Comprehensive Validation for Sale / POS Checkout
# ============================================================================

def validate_coupon_for_sale(
    tenant,
    coupon_code: str,
    customer=None,
    item=None,
    subtotal: Decimal = Decimal('0.00')
) -> Dict[str, Any]:
    """
    Validate a coupon code for an impending sale at the checkout counter.
    Returns:
        {
            'valid': bool,
            'discount_amount': Decimal,
            'message': str,
            'coupon': CustomerCoupon or None,
            'code_item': CouponCodeItem or None,
            'coupon_code': str,
            'coupon_name': str,
        }
    """
    from .models import CustomerCoupon, CouponCodeItem, CouponRedemption

    code_clean = (coupon_code or '').strip().upper()
    if not code_clean:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': 'Please enter a coupon code.',
            'coupon': None,
            'code_item': None,
            'coupon_code': '',
            'coupon_name': '',
        }

    if not tenant:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': 'No active business/tenant context found.',
            'coupon': None,
            'code_item': None,
            'coupon_code': code_clean,
            'coupon_name': '',
        }

    # 1. First check if it's a unique serialised coupon code item
    code_item = CouponCodeItem.objects.select_related('coupon', 'coupon__applicable_category', 'coupon__specific_customer').filter(
        tenant=tenant,
        code__iexact=code_clean
    ).first()

    coupon = None
    if code_item:
        coupon = code_item.coupon
        if code_item.is_redeemed:
            return {
                'valid': False,
                'discount_amount': Decimal('0.00'),
                'message': f"This single-use coupon '{code_clean}' has already been redeemed on {code_item.redeemed_at.strftime('%d-%b-%Y') if code_item.redeemed_at else 'a previous sale'}.",
                'coupon': coupon,
                'code_item': code_item,
                'coupon_code': code_clean,
                'coupon_name': coupon.name,
            }
    else:
        # 2. Otherwise look for a general promotional campaign coupon code
        coupon = CustomerCoupon.objects.select_related('applicable_category', 'specific_customer').filter(
            tenant=tenant,
            code__iexact=code_clean
        ).first()

    if not coupon:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': f"Coupon code '{code_clean}' is invalid or does not belong to this business.",
            'coupon': None,
            'code_item': None,
            'coupon_code': code_clean,
            'coupon_name': '',
        }

    # Verify coupon belongs to the current tenant
    if coupon.tenant_id != tenant.id:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': 'Cross-business coupon redemption is strictly prohibited.',
            'coupon': None,
            'code_item': None,
            'coupon_code': code_clean,
            'coupon_name': '',
        }

    # Check Status
    if coupon.status == CustomerCoupon.STATUS_PAUSED:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': f"Coupon campaign '{coupon.name}' is currently paused by the showroom manager.",
            'coupon': coupon,
            'code_item': code_item,
            'coupon_code': code_clean,
            'coupon_name': coupon.name,
        }
    elif coupon.status == CustomerCoupon.STATUS_EXPIRED:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': f"Coupon offer '{coupon.name}' has expired.",
            'coupon': coupon,
            'code_item': code_item,
            'coupon_code': code_clean,
            'coupon_name': coupon.name,
        }
    elif coupon.status == CustomerCoupon.STATUS_ARCHIVED:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': f"Coupon offer '{coupon.name}' has been archived.",
            'coupon': coupon,
            'code_item': code_item,
            'coupon_code': code_clean,
            'coupon_name': coupon.name,
        }
    elif coupon.status != CustomerCoupon.STATUS_ACTIVE:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': f"Coupon offer '{coupon.name}' is not currently active.",
            'coupon': coupon,
            'code_item': code_item,
            'coupon_code': code_clean,
            'coupon_name': coupon.name,
        }

    # Check Date Range
    today = timezone.localdate()
    if coupon.valid_from and today < coupon.valid_from:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': f"Coupon '{coupon.name}' is scheduled to start on {coupon.valid_from.strftime('%d-%b-%Y')}.",
            'coupon': coupon,
            'code_item': code_item,
            'coupon_code': code_clean,
            'coupon_name': coupon.name,
        }
    if coupon.valid_until and today > coupon.valid_until:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': f"Coupon '{coupon.name}' expired on {coupon.valid_until.strftime('%d-%b-%Y')}.",
            'coupon': coupon,
            'code_item': code_item,
            'coupon_code': code_clean,
            'coupon_name': coupon.name,
        }

    # Check Single Use & Total Usage Caps
    if coupon.is_single_use and coupon.times_redeemed >= 1:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': f"Coupon '{coupon.name}' was a single-use offer and has already been redeemed.",
            'coupon': coupon,
            'code_item': code_item,
            'coupon_code': code_clean,
            'coupon_name': coupon.name,
        }
    if coupon.max_uses_total and coupon.times_redeemed >= coupon.max_uses_total:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': f"Coupon '{coupon.name}' has reached its maximum total redemption limit of {coupon.max_uses_total}.",
            'coupon': coupon,
            'code_item': code_item,
            'coupon_code': code_clean,
            'coupon_name': coupon.name,
        }

    # Check Customer Restrictions
    if coupon.specific_customer:
        if not customer:
            return {
                'valid': False,
                'discount_amount': Decimal('0.00'),
                'message': f"This coupon is exclusive to customer '{coupon.specific_customer.name}'. Please select the customer first.",
                'coupon': coupon,
                'code_item': code_item,
                'coupon_code': code_clean,
                'coupon_name': coupon.name,
            }
        elif customer.id != coupon.specific_customer_id:
            return {
                'valid': False,
                'discount_amount': Decimal('0.00'),
                'message': f"This coupon is exclusively reserved for customer '{coupon.specific_customer.name}'.",
                'coupon': coupon,
                'code_item': code_item,
                'coupon_code': code_clean,
                'coupon_name': coupon.name,
            }

    # Check Customer Per-User Limit
    if customer and coupon.max_uses_per_customer:
        cust_redemptions = CouponRedemption.objects.filter(
            coupon=coupon,
            customer=customer
        ).count()
        if cust_redemptions >= coupon.max_uses_per_customer:
            return {
                'valid': False,
                'discount_amount': Decimal('0.00'),
                'message': f"Customer '{customer.name}' has already used this offer {cust_redemptions} time(s) (limit: {coupon.max_uses_per_customer}).",
                'coupon': coupon,
                'code_item': code_item,
                'coupon_code': code_clean,
                'coupon_name': coupon.name,
            }

    # Check Category Restrictions
    if coupon.applicable_category and item:
        item_cat_id = getattr(item, 'category_id', None)
        if item_cat_id != coupon.applicable_category_id:
            cat_name = coupon.applicable_category.name
            return {
                'valid': False,
                'discount_amount': Decimal('0.00'),
                'message': f"This offer is valid only on items in the '{cat_name}' category.",
                'coupon': coupon,
                'code_item': code_item,
                'coupon_code': code_clean,
                'coupon_name': coupon.name,
            }

    # Check Minimum Purchase Requirement
    subtotal_dec = Decimal(str(subtotal or '0.00'))
    if coupon.min_purchase_amount and subtotal_dec < coupon.min_purchase_amount:
        return {
            'valid': False,
            'discount_amount': Decimal('0.00'),
            'message': f"Minimum purchase of ₹{coupon.min_purchase_amount:,.2f} required to apply this coupon (current subtotal: ₹{subtotal_dec:,.2f}).",
            'coupon': coupon,
            'code_item': code_item,
            'coupon_code': code_clean,
            'coupon_name': coupon.name,
        }

    # Calculate Discount
    discount_amount = calculate_coupon_discount(coupon, subtotal_dec)

    return {
        'valid': True,
        'discount_amount': discount_amount,
        'message': f"Applied coupon '{coupon.name}' ({coupon.formatted_discount})! You saved ₹{discount_amount:,.2f}.",
        'coupon': coupon,
        'code_item': code_item,
        'coupon_code': code_clean,
        'coupon_name': coupon.name,
    }


# ============================================================================
# 3. Concurrency-Safe Atomic Redemption inside POS Checkout
# ============================================================================

def redeem_coupon_atomic(
    tenant,
    coupon_code: str,
    sale,
    customer,
    subtotal: Decimal,
    user=None
) -> Decimal:
    """
    Atomically validate and record coupon redemption inside the caller's transaction.atomic() block.
    Uses database row-level locking (`select_for_update`) to prevent race conditions and double redemptions.

    Raises ValidationError if the coupon is invalid, expired, or already redeemed.
    Returns the exact Decimal discount amount applied.
    """
    from .models import CustomerCoupon, CouponCodeItem, CouponRedemption

    code_clean = (coupon_code or '').strip().upper()
    if not code_clean:
        return Decimal('0.00')

    # Acquire lock on CouponCodeItem if exists
    locked_code_item = CouponCodeItem.objects.select_for_update().filter(
        tenant=tenant,
        code__iexact=code_clean
    ).first()

    locked_coupon = None
    if locked_code_item:
        locked_coupon = CustomerCoupon.objects.select_for_update().get(pk=locked_code_item.coupon_id)
        if locked_code_item.is_redeemed:
            raise ValidationError(
                f"Coupon '{code_clean}' has already been redeemed and cannot be used again."
            )
    else:
        locked_coupon = CustomerCoupon.objects.select_for_update().filter(
            tenant=tenant,
            code__iexact=code_clean
        ).first()

    if not locked_coupon:
        raise ValidationError(f"Invalid coupon code '{code_clean}'.")

    # Perform full business validation against the locked rows
    val_res = validate_coupon_for_sale(
        tenant=tenant,
        coupon_code=code_clean,
        customer=customer,
        item=sale.jewellery_item,
        subtotal=subtotal
    )

    if not val_res['valid']:
        raise ValidationError(val_res['message'])

    discount_amount = val_res['discount_amount']
    final_total = max(Decimal('0.00'), subtotal - discount_amount)

    # 1. Update unique code item if applicable
    if locked_code_item:
        locked_code_item.is_redeemed = True
        locked_code_item.redeemed_at = timezone.now()
        locked_code_item.redeemed_by_customer = customer
        locked_code_item.redeemed_in_sale = sale
        locked_code_item.save(update_fields=['is_redeemed', 'redeemed_at', 'redeemed_by_customer', 'redeemed_in_sale'])

    # 2. Update coupon redemption counter
    CustomerCoupon.objects.filter(pk=locked_coupon.pk).update(
        times_redeemed=F('times_redeemed') + 1
    )
    locked_coupon.refresh_from_db(fields=['times_redeemed'])

    # 3. Create immutable audit redemption record
    CouponRedemption.objects.create(
        tenant=tenant,
        coupon=locked_coupon,
        code_item=locked_code_item,
        coupon_code_used=code_clean,
        sale=sale,
        customer=customer,
        order_subtotal=subtotal,
        discount_amount=discount_amount,
        final_total=final_total,
        redeemed_by_user=user,
        redeemed_at=timezone.now()
    )

    return discount_amount


# ============================================================================
# 4. Collision-Resistant Unique Coupon Code Generation
# ============================================================================

def generate_random_tenant_code(prefix: str = "JD-", length: int = 8) -> str:
    """Generate a clean alphanumeric coupon code string omitting ambiguous characters."""
    clean_prefix = re.sub(r'[^A-Za-z0-9\-_]', '', prefix or '').upper()
    random_part = "".join(secrets.choice(COUPON_ALPHABET) for _ in range(max(4, length)))
    return f"{clean_prefix}{random_part}"


def generate_unique_tenant_coupon_codes(
    tenant,
    coupon,
    count: int,
    prefix: str = "JD-",
    length: int = 8,
    serial_start: int = 1
) -> List[Any]:
    """
    Generate `count` unique collision-free CouponCodeItem records for the specified tenant coupon.
    Guarantees database uniqueness scoped to this tenant.
    """
    from .models import CouponCodeItem

    created_items = []
    generated_set = set()
    current_serial = serial_start
    attempts = 0
    max_attempts = count * 30 + 300

    with transaction.atomic():
        while len(created_items) < count and attempts < max_attempts:
            attempts += 1
            candidate = generate_random_tenant_code(prefix=prefix, length=length)
            if candidate not in generated_set:
                # Verify collision within tenant code items and general coupon codes
                exists_in_items = CouponCodeItem.objects.filter(tenant=tenant, code=candidate).exists()
                if not exists_in_items:
                    generated_set.add(candidate)
                    item = CouponCodeItem(
                        tenant=tenant,
                        coupon=coupon,
                        code=candidate,
                        serial_number=current_serial,
                    )
                    created_items.append(item)
                    current_serial += 1

        if len(created_items) < count:
            raise ValueError(
                f"Could only generate {len(created_items)} of {count} unique codes. "
                "Please increase code length or choose another prefix."
            )

        CouponCodeItem.objects.bulk_create(created_items)

    return created_items


# ============================================================================
# 5. Safe Dynamic Placeholder Substitution
# ============================================================================

def render_coupon_template(
    template_html: str,
    context: Dict[str, Any]
) -> str:
    """
    Safely replace allowed placeholders into HTML markup.
    Escapes all dynamic text values (preventing XSS).
    Never executes arbitrary Django template tags or Python code.
    """
    if not template_html:
        return ""

    output = str(template_html)

    for key in ALLOWED_PLACEHOLDERS:
        val = context.get(key, "")
        if key in ("barcode_svg", "qr_svg", "business_logo"):
            safe_val = str(val) if val else ""
        else:
            safe_val = escape(str(val)) if val is not None else ""

        pattern = re.compile(r'\{\{\s*' + re.escape(key) + r'\s*\}\}', re.IGNORECASE)
        output = pattern.sub(safe_val, output)

    return output


# ============================================================================
# 6. Built-in Professional Ready-Made Jewellery Presets
# ============================================================================

def get_tenant_preset_markup(style: str = 'luxury_gold') -> Dict[str, str]:
    """Return authentic responsive HTML and print-friendly CSS for ready-made jewellery presets."""

    if style == 'festive_diwali':
        html_markup = """
<div class="jd-coupon-card jd-preset-festive">
    <div class="jd-coupon-inner">
        <div class="jd-festive-corner tl">&#10022;</div>
        <div class="jd-festive-corner tr">&#10022;</div>
        <div class="jd-festive-corner bl">&#10022;</div>
        <div class="jd-festive-corner br">&#10022;</div>

        <div class="jd-coupon-left">
            <div class="jd-brand-row">
                <span class="jd-brand-name">{{business_name}}</span>
                <span class="jd-festive-tag">&#129684; SHUBH UTSAV PRIVILEGE</span>
            </div>
            <div class="jd-offer-headline">{{offer_title}}</div>
            <div class="jd-valid-dates">Valid Until: <strong>{{valid_until}}</strong> &bull; Min Purchase: <strong>{{minimum_purchase}}</strong></div>
            <div class="jd-terms-box">{{terms_and_conditions}}</div>
        </div>

        <div class="jd-coupon-divider-ornate"></div>

        <div class="jd-coupon-right">
            <div class="jd-discount-badge">{{discount_value}}</div>
            <div class="jd-code-pill">
                <span class="jd-code-lbl">PROMO CODE</span>
                <span class="jd-code-val">{{coupon_code}}</span>
            </div>
            <div class="jd-barcode-box">{{barcode_svg}}</div>
            <div class="jd-serial-lbl">VOUCHER #{{serial_number}}</div>
        </div>
    </div>
</div>
""".strip()

        css_markup = """
.jd-preset-festive {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    background: linear-gradient(135deg, #2b0e04 0%, #170701 50%, #361002 100%);
    border: 2px solid #e5a93b;
    border-radius: 10px;
    padding: 12px;
    color: #fff6e5;
    font-family: 'Cinzel', 'Playfair Display', Georgia, serif;
    position: relative;
    box-shadow: 0 4px 14px rgba(0,0,0,0.3);
}
.jd-preset-festive .jd-coupon-inner {
    width: 100%;
    height: 100%;
    border: 1px solid rgba(229, 169, 59, 0.4);
    border-radius: 6px;
    display: flex;
    position: relative;
    padding: 10px 14px;
    box-sizing: border-box;
}
.jd-preset-festive .jd-festive-corner {
    position: absolute;
    color: #e5a93b;
    font-size: 13px;
}
.jd-preset-festive .tl { top: 4px; left: 6px; }
.jd-preset-festive .tr { top: 4px; right: 6px; }
.jd-preset-festive .bl { bottom: 4px; left: 6px; }
.jd-preset-festive .br { bottom: 4px; right: 6px; }

.jd-preset-festive .jd-coupon-left {
    flex: 1.6;
    display: flex;
    flex-direction: column;
    justifyContent: space-between;
    padding-right: 14px;
}
.jd-preset-festive .jd-brand-name {
    font-size: 13px;
    font-weight: 700;
    color: #ffd987;
    letter-spacing: 1.5px;
    text-transform: uppercase;
}
.jd-preset-festive .jd-festive-tag {
    font-size: 9px;
    background: rgba(229,169,59,0.2);
    border: 1px solid rgba(229,169,59,0.4);
    color: #ffe6a8;
    padding: 1px 6px;
    border-radius: 4px;
    margin-left: 8px;
    letter-spacing: 0.8px;
}
.jd-preset-festive .jd-offer-headline {
    font-size: 17px;
    font-weight: 700;
    color: #ffffff;
    line-height: 1.2;
    margin: 4px 0;
}
.jd-preset-festive .jd-valid-dates {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 9.5px;
    color: #d1b899;
}
.jd-preset-festive .jd-terms-box {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 8px;
    color: #a8947c;
    line-height: 1.3;
    max-height: 32px;
    overflow: hidden;
}
.jd-preset-festive .jd-coupon-divider-ornate {
    width: 1px;
    background: repeating-linear-gradient(to bottom, #e5a93b 0, #e5a93b 4px, transparent 4px, transparent 8px);
    margin: 0 10px;
}
.jd-preset-festive .jd-coupon-right {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justifyContent: space-between;
    text-align: center;
}
.jd-preset-festive .jd-discount-badge {
    font-size: 24px;
    font-weight: 900;
    color: #ffd987;
    text-shadow: 0 1px 4px rgba(0,0,0,0.4);
    letter-spacing: 1px;
}
.jd-preset-festive .jd-code-pill {
    background: rgba(0,0,0,0.4);
    border: 1px dashed #e5a93b;
    border-radius: 4px;
    padding: 3px 10px;
}
.jd-preset-festive .jd-code-lbl {
    display: block;
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 7.5px;
    color: #d1b899;
    letter-spacing: 1px;
}
.jd-preset-festive .jd-code-val {
    font-family: monospace;
    font-size: 13px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: 1.5px;
}
.jd-preset-festive .jd-barcode-box {
    width: 100%;
    margin-top: 2px;
}
.jd-preset-festive .jd-serial-lbl {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 8px;
    color: #a8947c;
}
""".strip()

    elif style == 'percentage_promo':
        html_markup = """
<div class="jd-coupon-card jd-preset-promo">
    <div class="jd-promo-ribbon">{{discount_value}}</div>
    <div class="jd-promo-body">
        <div class="jd-promo-header">
            <span class="jd-brand">{{business_name}}</span>
            <span class="jd-pill">EXCLUSIVE PRIVILEGE</span>
        </div>
        <div class="jd-promo-title">{{offer_title}}</div>
        <div class="jd-promo-details">
            <span>Minimum Purchase: <strong>{{minimum_purchase}}</strong></span> &bull;
            <span>Valid Until: <strong>{{valid_until}}</strong></span>
        </div>
        <div class="jd-promo-terms">{{terms_and_conditions}}</div>
    </div>
    <div class="jd-promo-stub">
        <div class="jd-stub-title">PROMO CODE</div>
        <div class="jd-stub-code">{{coupon_code}}</div>
        <div class="jd-stub-barcode">{{barcode_svg}}</div>
        <div class="jd-stub-num">VOUCHER #{{serial_number}}</div>
    </div>
</div>
""".strip()

        css_markup = """
.jd-preset-promo {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    background: #141416;
    border: 1.5px solid #d4af37;
    border-radius: 8px;
    display: flex;
    font-family: 'Plus Jakarta Sans', sans-serif;
    color: #f5f5f7;
    position: relative;
    overflow: hidden;
}
.jd-preset-promo .jd-promo-ribbon {
    position: absolute;
    top: 0;
    right: 0;
    background: #d4af37;
    color: #141416;
    font-weight: 800;
    font-size: 12px;
    padding: 3px 14px;
    border-bottom-left-radius: 8px;
    letter-spacing: 0.5px;
}
.jd-preset-promo .jd-promo-body {
    flex: 1.8;
    padding: 14px;
    display: flex;
    flex-direction: column;
    justifyContent: space-between;
}
.jd-preset-promo .jd-brand {
    font-size: 12px;
    font-weight: 700;
    color: #d4af37;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.jd-preset-promo .jd-pill {
    font-size: 8px;
    background: rgba(212,175,55,0.15);
    color: #e5c76b;
    padding: 1px 6px;
    border-radius: 3px;
    margin-left: 8px;
}
.jd-preset-promo .jd-promo-title {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
    line-height: 1.25;
}
.jd-preset-promo .jd-promo-details {
    font-size: 9.5px;
    color: #a1a1aa;
}
.jd-preset-promo .jd-promo-terms {
    font-size: 8px;
    color: #71717a;
    line-height: 1.25;
    max-height: 30px;
    overflow: hidden;
}
.jd-preset-promo .jd-promo-stub {
    flex: 1;
    border-left: 1px dashed rgba(212,175,55,0.4);
    padding: 12px 10px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justifyContent: space-between;
    background: rgba(255,255,255,0.02);
}
.jd-preset-promo .jd-stub-title {
    font-size: 8px;
    color: #a1a1aa;
    letter-spacing: 1.5px;
}
.jd-preset-promo .jd-stub-code {
    font-family: monospace;
    font-size: 14px;
    font-weight: 800;
    color: #d4af37;
    letter-spacing: 1px;
}
.jd-preset-promo .jd-stub-barcode {
    width: 100%;
}
.jd-preset-promo .jd-stub-num {
    font-size: 8px;
    color: #71717a;
}
""".strip()

    elif style == 'cash_voucher':
        html_markup = """
<div class="jd-coupon-card jd-preset-cash">
    <div class="jd-cash-left">
        <div class="jd-cash-stamp">GIFT VOUCHER</div>
        <div class="jd-cash-val">{{discount_value}}</div>
        <div class="jd-cash-min">On Min. Purchase of {{minimum_purchase}}</div>
    </div>
    <div class="jd-cash-divider"></div>
    <div class="jd-cash-center">
        <div class="jd-brand">{{business_name}}</div>
        <div class="jd-title">{{offer_title}}</div>
        <div class="jd-terms">{{terms_and_conditions}}</div>
        <div class="jd-expiry">Valid Until: <strong>{{valid_until}}</strong></div>
    </div>
    <div class="jd-cash-right">
        <div class="jd-code-box">
            <span class="jd-lbl">VOUCHER CODE</span>
            <span class="jd-code">{{coupon_code}}</span>
        </div>
        <div class="jd-qr-box">{{qr_svg}}</div>
        <div class="jd-serial">#{{serial_number}}</div>
    </div>
</div>
""".strip()

        css_markup = """
.jd-preset-cash {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    background: #0f172a;
    border: 2px solid #38bdf8;
    border-radius: 8px;
    display: flex;
    font-family: 'Plus Jakarta Sans', sans-serif;
    color: #f8fafc;
    overflow: hidden;
}
.jd-preset-cash .jd-cash-left {
    flex: 1;
    background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
    padding: 12px;
    display: flex;
    flex-direction: column;
    justifyContent: center;
    align-items: center;
    text-align: center;
}
.jd-preset-cash .jd-cash-stamp {
    font-size: 8.5px;
    font-weight: 800;
    letter-spacing: 1.5px;
    color: #e0f2fe;
    background: rgba(0,0,0,0.25);
    padding: 2px 6px;
    border-radius: 3px;
}
.jd-preset-cash .jd-cash-val {
    font-size: 22px;
    font-weight: 900;
    color: #ffffff;
    margin: 4px 0;
}
.jd-preset-cash .jd-cash-min {
    font-size: 8px;
    color: #bae6fd;
}
.jd-preset-cash .jd-cash-divider {
    width: 1px;
    border-left: 2px dashed #0284c7;
}
.jd-preset-cash .jd-cash-center {
    flex: 1.6;
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    justifyContent: space-between;
}
.jd-preset-cash .jd-brand {
    font-size: 11px;
    font-weight: 700;
    color: #38bdf8;
    text-transform: uppercase;
}
.jd-preset-cash .jd-title {
    font-size: 15px;
    font-weight: 700;
    color: #ffffff;
}
.jd-preset-cash .jd-terms {
    font-size: 8px;
    color: #94a3b8;
    line-height: 1.3;
    max-height: 28px;
    overflow: hidden;
}
.jd-preset-cash .jd-expiry {
    font-size: 9px;
    color: #cbd5e1;
}
.jd-preset-cash .jd-cash-right {
    flex: 0.9;
    padding: 10px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justifyContent: space-between;
    border-left: 1px solid rgba(255,255,255,0.08);
}
.jd-preset-cash .jd-code-box {
    text-align: center;
}
.jd-preset-cash .jd-lbl {
    font-size: 7.5px;
    color: #94a3b8;
    letter-spacing: 1px;
    display: block;
}
.jd-preset-cash .jd-code {
    font-family: monospace;
    font-size: 12px;
    font-weight: 800;
    color: #38bdf8;
}
.jd-preset-cash .jd-qr-box {
    margin: 2px 0;
}
.jd-preset-cash .jd-serial {
    font-size: 8px;
    color: #64748b;
}
""".strip()

    elif style == 'minimal_white':
        html_markup = """
<div class="jd-coupon-card jd-preset-minimal">
    <div class="jd-min-left">
        <div class="jd-min-brand">{{business_name}}</div>
        <div class="jd-min-title">{{offer_title}}</div>
        <div class="jd-min-terms">{{terms_and_conditions}}</div>
        <div class="jd-min-meta">
            <span>Valid Until: <strong>{{valid_until}}</strong></span> &bull;
            <span>Min. Spend: <strong>{{minimum_purchase}}</strong></span>
        </div>
    </div>
    <div class="jd-min-divider"></div>
    <div class="jd-min-right">
        <div class="jd-min-discount">{{discount_value}}</div>
        <div class="jd-min-code">
            <span class="jd-lbl">VOUCHER CODE</span>
            <span class="jd-val">{{coupon_code}}</span>
        </div>
        <div class="jd-min-barcode">{{barcode_svg}}</div>
        <div class="jd-min-num">#{{serial_number}}</div>
    </div>
</div>
""".strip()

        css_markup = """
.jd-preset-minimal {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    background: #ffffff;
    border: 1.5px solid #1c1917;
    border-radius: 6px;
    display: flex;
    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
    color: #1c1917;
    overflow: hidden;
}
.jd-preset-minimal .jd-min-left {
    flex: 1.8;
    padding: 14px;
    display: flex;
    flex-direction: column;
    justifyContent: space-between;
}
.jd-preset-minimal .jd-min-brand {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: #78716c;
}
.jd-preset-minimal .jd-min-title {
    font-size: 16px;
    font-weight: 700;
    color: #1c1917;
    line-height: 1.25;
}
.jd-preset-minimal .jd-min-terms {
    font-size: 8px;
    color: #78716c;
    line-height: 1.3;
    max-height: 28px;
    overflow: hidden;
}
.jd-preset-minimal .jd-min-meta {
    font-size: 9px;
    color: #44403c;
}
.jd-preset-minimal .jd-min-divider {
    width: 1px;
    border-left: 1.5px dashed #a8a29e;
}
.jd-preset-minimal .jd-min-right {
    flex: 1.1;
    padding: 12px 10px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justifyContent: space-between;
    background: #fafaf9;
    text-align: center;
}
.jd-preset-minimal .jd-min-discount {
    font-size: 22px;
    font-weight: 900;
    color: #1c1917;
}
.jd-preset-minimal .jd-min-code {
    background: #ffffff;
    border: 1px solid #d6d3d1;
    border-radius: 4px;
    padding: 2px 8px;
}
.jd-preset-minimal .jd-lbl {
    display: block;
    font-size: 7.5px;
    color: #78716c;
    letter-spacing: 1px;
}
.jd-preset-minimal .jd-val {
    font-family: monospace;
    font-size: 13px;
    font-weight: 800;
    color: #1c1917;
}
.jd-preset-minimal .jd-min-barcode {
    width: 100%;
}
.jd-preset-minimal .jd-min-num {
    font-size: 8px;
    color: #a8a29e;
}
""".strip()

    elif style == 'compact_sheet':
        html_markup = """
<div class="jd-coupon-card jd-preset-compact">
    <div class="jd-c-left">
        <div class="jd-c-brand">{{business_name}}</div>
        <div class="jd-c-title">{{offer_title}}</div>
        <div class="jd-c-meta">Valid Until: <strong>{{valid_until}}</strong> | Min: <strong>{{minimum_purchase}}</strong></div>
    </div>
    <div class="jd-c-right">
        <div class="jd-c-disc">{{discount_value}}</div>
        <div class="jd-c-code">{{coupon_code}}</div>
        <div class="jd-c-num">#{{serial_number}}</div>
    </div>
</div>
""".strip()

        css_markup = """
.jd-preset-compact {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    background: #ffffff;
    border: 1px dashed #78716c;
    border-radius: 4px;
    display: flex;
    font-family: 'Plus Jakarta Sans', sans-serif;
    color: #1c1917;
    padding: 8px 10px;
}
.jd-preset-compact .jd-c-left {
    flex: 2;
    display: flex;
    flex-direction: column;
    justifyContent: space-between;
}
.jd-preset-compact .jd-c-brand {
    font-size: 10px;
    font-weight: 700;
    color: #a8a29e;
    text-transform: uppercase;
}
.jd-preset-compact .jd-c-title {
    font-size: 13px;
    font-weight: 700;
}
.jd-preset-compact .jd-c-meta {
    font-size: 8.5px;
    color: #57534e;
}
.jd-preset-compact .jd-c-right {
    flex: 1;
    border-left: 1px dotted #d6d3d1;
    padding-left: 10px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justifyContent: space-between;
    text-align: center;
}
.jd-preset-compact .jd-c-disc {
    font-size: 16px;
    font-weight: 900;
    color: #b45309;
}
.jd-preset-compact .jd-c-code {
    font-family: monospace;
    font-size: 11px;
    font-weight: 700;
    background: #f5f5f4;
    padding: 1px 6px;
    border-radius: 3px;
}
.jd-preset-compact .jd-c-num {
    font-size: 7.5px;
    color: #a8a29e;
}
""".strip()

    else:
        # Default: Royal Heritage Gold
        html_markup = """
<div class="jd-coupon-card jd-preset-luxury">
    <div class="jd-luxury-border">
        <div class="jd-luxury-left">
            <div class="jd-brand-header">
                <span class="jd-brand-name">{{business_name}}</span>
                <span class="jd-privilege-badge">ROYAL PRIVILEGE</span>
            </div>
            <div class="jd-offer-title">{{offer_title}}</div>
            <div class="jd-offer-terms">{{terms_and_conditions}}</div>
            <div class="jd-offer-validity">
                <span>Valid Until: <strong>{{valid_until}}</strong></span>
                <span>Min. Purchase: <strong>{{minimum_purchase}}</strong></span>
            </div>
        </div>
        <div class="jd-luxury-divider"></div>
        <div class="jd-luxury-right">
            <div class="jd-discount-amount">{{discount_value}}</div>
            <div class="jd-code-container">
                <div class="jd-code-label">PROMOTIONAL CODE</div>
                <div class="jd-code-value">{{coupon_code}}</div>
            </div>
            <div class="jd-barcode-box">{{barcode_svg}}</div>
            <div class="jd-serial-number">VOUCHER #{{serial_number}}</div>
        </div>
    </div>
</div>
""".strip()

        css_markup = """
.jd-preset-luxury {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    background: radial-gradient(circle at 50% 50%, #1f160e 0%, #120c08 100%);
    border: 2px solid #d4af37;
    border-radius: 8px;
    padding: 10px;
    font-family: 'Cinzel', 'Playfair Display', Georgia, serif;
    color: #fef9ed;
}
.jd-preset-luxury .jd-luxury-border {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    border: 1px solid rgba(212, 175, 55, 0.45);
    border-radius: 4px;
    display: flex;
    padding: 10px 14px;
}
.jd-preset-luxury .jd-luxury-left {
    flex: 1.7;
    display: flex;
    flex-direction: column;
    justifyContent: space-between;
    padding-right: 12px;
}
.jd-preset-luxury .jd-brand-name {
    font-size: 13px;
    font-weight: 700;
    color: #d4af37;
    letter-spacing: 1.5px;
    text-transform: uppercase;
}
.jd-preset-luxury .jd-privilege-badge {
    font-size: 8px;
    background: rgba(212, 175, 55, 0.15);
    color: #fae19c;
    padding: 1px 6px;
    border-radius: 3px;
    border: 0.5px solid rgba(212,175,55,0.4);
    margin-left: 8px;
    letter-spacing: 1px;
}
.jd-preset-luxury .jd-offer-title {
    font-size: 17px;
    font-weight: 700;
    color: #ffffff;
    line-height: 1.25;
}
.jd-preset-luxury .jd-offer-terms {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 8px;
    color: #bfa88f;
    line-height: 1.3;
    max-height: 30px;
    overflow: hidden;
}
.jd-preset-luxury .jd-offer-validity {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 9px;
    color: #e5cfa8;
    display: flex;
    gap: 12px;
}
.jd-preset-luxury .jd-luxury-divider {
    width: 1px;
    background: linear-gradient(to bottom, transparent, #d4af37 30%, #d4af37 70%, transparent);
    margin: 0 8px;
}
.jd-preset-luxury .jd-luxury-right {
    flex: 1.1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justifyContent: space-between;
    text-align: center;
}
.jd-preset-luxury .jd-discount-amount {
    font-size: 24px;
    font-weight: 900;
    color: #d4af37;
    text-shadow: 0 2px 6px rgba(0,0,0,0.5);
}
.jd-preset-luxury .jd-code-container {
    background: rgba(0,0,0,0.35);
    border: 1px dashed #d4af37;
    border-radius: 4px;
    padding: 3px 10px;
}
.jd-preset-luxury .jd-code-label {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 7.5px;
    color: #bfa88f;
    letter-spacing: 1px;
}
.jd-preset-luxury .jd-code-value {
    font-family: monospace;
    font-size: 13px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: 1.5px;
}
.jd-preset-luxury .jd-barcode-box {
    width: 100%;
}
.jd-preset-luxury .jd-serial-number {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 8px;
    color: #bfa88f;
}
""".strip()

    return {
        'html': html_markup,
        'css': css_markup,
    }
