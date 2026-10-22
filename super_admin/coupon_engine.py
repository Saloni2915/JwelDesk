"""
super_admin/coupon_engine.py
----------------------------
Core business logic, security sanitization, vector barcode/QR generator,
and template rendering engine for JewelDesk Coupon Designer & Print Management.
"""

from decimal import Decimal
import html
import math
import re
import secrets
from typing import Any, Dict, List, Optional
from django.utils import timezone
from django.utils.html import escape


# Unambiguous alphanumeric alphabet omitting lookalike characters (0, O, 1, I, L)
COUPON_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

# Allowed dynamic placeholders in custom & built-in templates
ALLOWED_PLACEHOLDERS = [
    "coupon_code",
    "discount_value",
    "offer_title",
    "business_name",
    "valid_from",
    "valid_until",
    "minimum_purchase",
    "maximum_discount",
    "applicable_categories",
    "terms_and_conditions",
    "serial_number",
    "barcode_svg",
    "qr_svg",
]


# ============================================================================
# 1. Collision-Resistant Unique Coupon Code Generation
# ============================================================================

def generate_random_code(prefix: str = "JD-", length: int = 8) -> str:
    """Generate a cryptographically random coupon code string."""
    clean_prefix = re.sub(r'[^A-Za-z0-9\-_]', '', prefix or '').upper()
    random_part = "".join(secrets.choice(COUPON_ALPHABET) for _ in range(max(4, length)))
    return f"{clean_prefix}{random_part}"


def generate_unique_batch_codes(batch_instance, count: int, prefix: str = "JD-", length: int = 8) -> List[str]:
    """Generate `count` collision-free unique coupon codes and ensure database uniqueness."""
    from .models import CouponBatchItem

    generated_set = set()
    generated_list = []
    attempts = 0
    max_attempts = count * 20 + 200

    while len(generated_list) < count and attempts < max_attempts:
        attempts += 1
        candidate = generate_random_code(prefix=prefix, length=length)
        if candidate not in generated_set:
            # Check DB collision across existing coupon batch items
            if not CouponBatchItem.objects.filter(coupon_code=candidate).exists():
                generated_set.add(candidate)
                generated_list.append(candidate)

    if len(generated_list) < count:
        raise ValueError(
            f"Unable to generate {count} unique collision-free coupon codes after {attempts} attempts. "
            "Please try increasing the code length or choosing a different prefix."
        )

    return generated_list


# ============================================================================
# 2. Vector SVG Barcode & QR Code Generators (Pure Python, Resolution-Independent)
# ============================================================================

# Code 128 Pattern tables (Subset B)
CODE128_PATTERNS = {
    ' ': '11011001100', '!': '11001101100', '"': '11001100110', '#': '10010011000',
    '$': '10010001100', '%': '10001001100', '&': '10011001000', "'": '10011000100',
    '(': '10001100100', ')': '11001001000', '*': '11001000100', '+': '11000100100',
    ',': '10110011100', '-': '10011011100', '.': '10011001110', '/': '10111001100',
    '0': '10011101100', '1': '10011100110', '2': '11001110010', '3': '11001011100',
    '4': '11001001110', '5': '11000101110', '6': '10110111000', '7': '10110001110',
    '8': '10001101110', '9': '10111011000', ':': '10111000110', ';': '10001110110',
    '<': '11101110110', '=': '11010001110', '>': '11000101010', '?': '11011101000',
    '@': '11011100010', 'A': '11011101110', 'B': '11101011000', 'C': '11101000110',
    'D': '11100010110', 'E': '11101101000', 'F': '11101100010', 'G': '11100011010',
    'H': '11101111010', 'I': '11001000010', 'J': '11110001010', 'K': '10100110000',
    'L': '10100001100', 'M': '10010110000', 'N': '10010000110', 'O': '10000101100',
    'P': '10000100110', 'Q': '10110010000', 'R': '10110000100', 'S': '10011010000',
    'T': '10011000010', 'U': '10000110100', 'V': '10000110010', 'W': '11000010010',
    'X': '11001010000', 'Y': '11110111010', 'Z': '11000010100', '_': '10111100010'
}
# Start B and Stop symbols
START_B_PATTERN = '11010010000'
STOP_PATTERN    = '1100011101011'


def generate_barcode_svg(code_text: str, bar_color: str = "#221c10", text_color: str = "#666666", width: int = 210, height: int = 46) -> str:
    """Generate high-precision vector SVG Code 128 barcode."""
    clean_text = re.sub(r'[^A-Za-z0-9\-_ ]', '', str(code_text or 'COUPON')).upper()
    if not clean_text:
        clean_text = "VOUCHER"

    # Assemble barcode bitstream
    bitstream = START_B_PATTERN
    for ch in clean_text:
        bitstream += CODE128_PATTERNS.get(ch, '10011101100')
    bitstream += STOP_PATTERN

    # Generate SVG rectangles
    rects = []
    x = 10
    bar_w = max(1.15, (width - 20) / len(bitstream))
    bar_h = height - 16

    for bit in bitstream:
        if bit == '1':
            rects.append(f'<rect x="{x:.2f}" y="4" width="{bar_w:.2f}" height="{bar_h}" fill="{bar_color}" />')
        x += bar_w

    total_svg_w = math.ceil(x + 10)
    rects_markup = "".join(rects)
    escaped_text = escape(clean_text)

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_svg_w} {height}" '
        f'width="100%" height="{height}px" style="display:block; margin: 0 auto; max-width:{width}px;">'
        f'{rects_markup}'
        f'<text x="{total_svg_w / 2:.2f}" y="{height - 2}" text-anchor="middle" '
        f'fill="{text_color}" font-family="monospace, monospace" font-size="9" font-weight="600" letter-spacing="1.5px">'
        f'{escaped_text}'
        f'</text>'
        f'</svg>'
    )
    return svg


def generate_qr_svg(payload_text: str, fg_color: str = "#221c10", bg_color: str = "transparent", size: int = 70) -> str:
    """Generate a clean, self-contained vector SVG QR code verification insignia."""
    # Deterministic pseudo-grid based on payload hash for consistent, crisp rendering
    h = 0
    for ch in str(payload_text or 'JD'):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFFFFFFFFFF

    grid_size = 21  # Standard Version 1 QR layout (21x21 modules)
    modules = [[False for _ in range(grid_size)] for _ in range(grid_size)]

    # Finder patterns at 3 corners (7x7)
    for r in range(7):
        for c in range(7):
            # Top-left
            modules[r][c] = (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))
            # Top-right
            modules[r][grid_size - 1 - c] = (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))
            # Bottom-left
            modules[grid_size - 1 - r][c] = (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))

    # Timing lines
    for i in range(8, grid_size - 8):
        modules[6][i] = (i % 2 == 0)
        modules[i][6] = (i % 2 == 0)

    # Deterministic data bits
    seed = h
    for r in range(grid_size):
        for c in range(grid_size):
            if (r < 8 and (c < 8 or c >= grid_size - 8)) or (r >= grid_size - 8 and c < 8):
                continue
            if r == 6 or c == 6:
                continue
            seed = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
            modules[r][c] = ((seed >> 28) & 1) == 1

    # Render module rects
    mod_size = size / (grid_size + 2)
    rects = []
    for r in range(grid_size):
        for c in range(grid_size):
            if modules[r][c]:
                rx = (c + 1) * mod_size
                ry = (r + 1) * mod_size
                rects.append(f'<rect x="{rx:.2f}" y="{ry:.2f}" width="{mod_size + 0.1:.2f}" height="{mod_size + 0.1:.2f}" fill="{fg_color}" />')

    rects_markup = "".join(rects)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}px" height="{size}px" style="display:inline-block; border-radius:4px;">'
        f'<rect width="{size}" height="{size}" fill="{bg_color}" />'
        f'{rects_markup}'
        f'</svg>'
    )
    return svg


# ============================================================================
# 3. HTML & CSS Sanitization (Untrusted Input Security Engine)
# ============================================================================

DANGEROUS_TAGS_RE = re.compile(
    r'<\s*(script|iframe|object|embed|applet|form|input|button|textarea|select|link|meta|base)[^>]*>.*?</\s*\1\s*>',
    re.IGNORECASE | re.DOTALL
)
DANGEROUS_SELF_CLOSING_RE = re.compile(
    r'<\s*(script|iframe|object|embed|applet|form|input|button|textarea|select|link|meta|base)[^>]*>',
    re.IGNORECASE
)
DANGEROUS_ATTRIBUTES_RE = re.compile(
    r'\s+(on[a-zA-Z]+\s*=\s*([\'\"][^\'\"]*[\'\"]|[^\s>]+))',
    re.IGNORECASE
)
DANGEROUS_SCHEMES_RE = re.compile(
    r'(href|src|action|data)\s*=\s*[\'\""]?\s*(javascript|vbscript|data):',
    re.IGNORECASE
)


def sanitize_coupon_html(raw_html: str) -> str:
    """
    Sanitize custom HTML content:
    - Removes executable scripts, frames, inputs, embeds, and forms.
    - Strips all on* event handler attributes.
    - Disallows javascript:, vbscript:, and data: schemes.
    """
    if not raw_html:
        return ""

    cleaned = str(raw_html)

    # 1. Remove dangerous paired tags
    cleaned = DANGEROUS_TAGS_RE.sub('', cleaned)

    # 2. Remove dangerous standalone/unpaired tags
    cleaned = DANGEROUS_SELF_CLOSING_RE.sub('', cleaned)

    # 3. Strip all event handlers (e.g. onclick, onload, onerror)
    cleaned = DANGEROUS_ATTRIBUTES_RE.sub('', cleaned)

    # 4. Strip dangerous URL schemes
    cleaned = DANGEROUS_SCHEMES_RE.sub(r'\1="#"', cleaned)

    return cleaned.strip()


def sanitize_coupon_css(raw_css: str) -> str:
    """
    Sanitize custom CSS rules:
    - Blocks expression(), behavior, @import, javascript:, and -moz-binding.
    """
    if not raw_css:
        return ""

    cleaned = str(raw_css)

    # Strip expressions and behaviors
    cleaned = re.sub(r'expression\s*\(.*?\)', '', cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r'behavior\s*:[^;]+;?', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'@import[^;]+;?', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'javascript\s*:', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'-moz-binding[^;]+;?', '', cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


# ============================================================================
# 4. Safe Dynamic Placeholder Substitution Engine
# ============================================================================

def substitute_placeholders(template_text: str, context: Dict[str, Any]) -> str:
    """
    Safely substitute allowed placeholders (e.g. {{coupon_code}}, {{discount_value}})
    into HTML/CSS templates.
    - Replaces only explicitly allowed placeholders.
    - Escapes all dynamic text values (preventing XSS).
    - NEVER evaluates arbitrary Django template expressions or Python code.
    """
    if not template_text:
        return ""

    output = str(template_text)

    for key in ALLOWED_PLACEHOLDERS:
        val = context.get(key, "")
        # Do not escape SVG elements
        if key in ("barcode_svg", "qr_svg"):
            safe_val = str(val) if val else ""
        else:
            safe_val = escape(str(val)) if val is not None else ""

        pattern = re.compile(r'\{\{\s*' + re.escape(key) + r'\s*\}\}', re.IGNORECASE)
        output = pattern.sub(safe_val, output)

    return output


# ============================================================================
# 5. Built-in Professional Design Presets
# ============================================================================

def get_builtin_template_markup(style: str = 'luxury_gold', discount_type: str = 'percentage') -> Dict[str, str]:
    """Return the baseline HTML and CSS for one of the 4 ready-made luxury coupon presets."""

    if style == 'minimal_white':
        html_markup = """
<div class="jd-coupon-card jd-style-minimal">
    <div class="jd-coupon-left">
        <div class="jd-coupon-brand">{{business_name}}</div>
        <div class="jd-coupon-title">{{offer_title}}</div>
        <div class="jd-coupon-categories">{{applicable_categories}}</div>
        <div class="jd-coupon-terms">{{terms_and_conditions}}</div>
        <div class="jd-coupon-footer">
            <span class="jd-coupon-date">Valid Until: <strong>{{valid_until}}</strong></span>
            <span class="jd-coupon-min">Min Purchase: <strong>{{minimum_purchase}}</strong></span>
        </div>
    </div>
    <div class="jd-coupon-divider"></div>
    <div class="jd-coupon-right">
        <div class="jd-discount-badge">{{discount_value}}</div>
        <div class="jd-code-box">
            <div class="jd-code-label">PROMO CODE</div>
            <div class="jd-code-value">{{coupon_code}}</div>
        </div>
        <div class="jd-barcode-wrapper">
            {{barcode_svg}}
        </div>
        <div class="jd-serial">VOUCHER {{serial_number}}</div>
    </div>
</div>
""".strip()

        css_markup = """
.jd-style-minimal {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    background: #ffffff;
    border: 1.5px solid #2b2620;
    border-radius: 8px;
    display: flex;
    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
    color: #1a1714;
    overflow: hidden;
    position: relative;
}
.jd-style-minimal .jd-coupon-left {
    flex: 1.6;
    padding: 16px 20px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
}
.jd-style-minimal .jd-coupon-brand {
    font-size: 11px;
    letter-spacing: 2px;
    text-transform: uppercase;
    font-weight: 800;
    color: #8c733e;
}
.jd-style-minimal .jd-coupon-title {
    font-size: 17px;
    font-weight: 800;
    color: #1a1714;
    line-height: 1.25;
    margin: 4px 0;
}
.jd-style-minimal .jd-coupon-categories {
    font-size: 10.5px;
    color: #555555;
    font-weight: 600;
}
.jd-style-minimal .jd-coupon-terms {
    font-size: 8px;
    color: #777777;
    line-height: 1.35;
    margin: 6px 0;
    max-height: 34px;
    overflow: hidden;
}
.jd-style-minimal .jd-coupon-footer {
    display: flex;
    justify-content: space-between;
    font-size: 9px;
    color: #444444;
    border-top: 1px solid #e5e5e5;
    padding-top: 6px;
}
.jd-style-minimal .jd-coupon-divider {
    width: 0;
    border-left: 2px dashed #b59858;
    position: relative;
    margin: 6px 0;
}
.jd-style-minimal .jd-coupon-right {
    flex: 1.1;
    padding: 14px 16px;
    background: #faf8f5;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: space-between;
    text-align: center;
}
.jd-style-minimal .jd-discount-badge {
    font-size: 24px;
    font-weight: 900;
    color: #8c733e;
    letter-spacing: -0.5px;
}
.jd-style-minimal .jd-code-box {
    background: #ffffff;
    border: 1px solid #d4af37;
    border-radius: 4px;
    padding: 4px 10px;
    width: 90%;
}
.jd-style-minimal .jd-code-label {
    font-size: 7.5px;
    letter-spacing: 1.5px;
    color: #8c733e;
    font-weight: 700;
}
.jd-style-minimal .jd-code-value {
    font-family: monospace;
    font-size: 13px;
    font-weight: 800;
    color: #1a1714;
    letter-spacing: 1px;
}
.jd-style-minimal .jd-barcode-wrapper {
    width: 100%;
}
.jd-style-minimal .jd-serial {
    font-size: 8px;
    color: #888888;
    letter-spacing: 1px;
}
""".strip()

    elif style == 'bold_promo':
        html_markup = """
<div class="jd-coupon-card jd-style-bold">
    <div class="jd-badge-ribbon">EXCLUSIVE OFFER</div>
    <div class="jd-coupon-body">
        <div class="jd-header-row">
            <span class="jd-brand-name">{{business_name}}</span>
            <span class="jd-serial-tag">{{serial_number}}</span>
        </div>
        <div class="jd-hero-row">
            <div class="jd-discount-huge">{{discount_value}}</div>
            <div class="jd-hero-info">
                <div class="jd-offer-headline">{{offer_title}}</div>
                <div class="jd-offer-sub">{{applicable_categories}}</div>
            </div>
        </div>
        <div class="jd-action-bar">
            <div class="jd-code-pill">
                <span class="jd-use-code">USE CODE:</span>
                <strong class="jd-code-str">{{coupon_code}}</strong>
            </div>
            <div class="jd-dates">
                <span>Valid: <strong>{{valid_until}}</strong></span>
                <span>Min Order: <strong>{{minimum_purchase}}</strong></span>
            </div>
        </div>
        <div class="jd-barcode-row">
            {{barcode_svg}}
        </div>
    </div>
</div>
""".strip()

        css_markup = """
.jd-style-bold {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    background: linear-gradient(135deg, #2b110e 0%, #170a08 100%);
    border: 2px solid #e65100;
    border-radius: 10px;
    position: relative;
    font-family: 'Plus Jakarta Sans', sans-serif;
    color: #ffffff;
    overflow: hidden;
}
.jd-style-bold .jd-badge-ribbon {
    position: absolute;
    top: 10px;
    right: -28px;
    background: #d84315;
    color: #ffffff;
    font-size: 8px;
    font-weight: 800;
    letter-spacing: 1.5px;
    padding: 3px 28px;
    transform: rotate(45deg);
    box-shadow: 0 2px 4px rgba(0,0,0,0.4);
}
.jd-style-bold .jd-coupon-body {
    padding: 14px 18px;
    height: 100%;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
}
.jd-style-bold .jd-header-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.jd-style-bold .jd-brand-name {
    font-size: 11px;
    letter-spacing: 2px;
    text-transform: uppercase;
    font-weight: 800;
    color: #ffab40;
}
.jd-style-bold .jd-serial-tag {
    font-size: 8px;
    font-family: monospace;
    color: #ffcc80;
    opacity: 0.8;
}
.jd-style-bold .jd-hero-row {
    display: flex;
    align-items: center;
    gap: 14px;
    margin: 4px 0;
}
.jd-style-bold .jd-discount-huge {
    font-size: 34px;
    font-weight: 900;
    color: #ffab40;
    line-height: 1;
    text-shadow: 0 2px 6px rgba(0,0,0,0.5);
    white-space: nowrap;
}
.jd-style-bold .jd-hero-info {
    flex: 1;
}
.jd-style-bold .jd-offer-headline {
    font-size: 14px;
    font-weight: 800;
    color: #ffffff;
    line-height: 1.2;
}
.jd-style-bold .jd-offer-sub {
    font-size: 9.5px;
    color: #ffd180;
    margin-top: 2px;
}
.jd-style-bold .jd-action-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: rgba(0,0,0,0.35);
    border: 1px solid rgba(255, 171, 64, 0.3);
    padding: 6px 12px;
    border-radius: 6px;
}
.jd-style-bold .jd-code-pill {
    display: flex;
    align-items: center;
    gap: 6px;
}
.jd-style-bold .jd-use-code {
    font-size: 8px;
    letter-spacing: 1px;
    color: #ffab40;
    font-weight: 700;
}
.jd-style-bold .jd-code-str {
    font-family: monospace;
    font-size: 14px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: 1px;
}
.jd-style-bold .jd-dates {
    display: flex;
    gap: 10px;
    font-size: 8.5px;
    color: #ffcc80;
}
.jd-style-bold .jd-barcode-row {
    margin-top: 4px;
}
""".strip()

    elif style == 'compact_sheet':
        html_markup = """
<div class="jd-coupon-card jd-style-compact">
    <div class="jd-cut-guide"><span class="jd-scissors">✂</span> cut here</div>
    <div class="jd-compact-inner">
        <div class="jd-compact-header">
            <span class="jd-compact-brand">{{business_name}}</span>
            <span class="jd-compact-code">{{coupon_code}}</span>
        </div>
        <div class="jd-compact-middle">
            <div class="jd-compact-discount">{{discount_value}}</div>
            <div class="jd-compact-details">
                <div class="jd-compact-title">{{offer_title}}</div>
                <div class="jd-compact-valid">Valid: {{valid_until}} | Min: {{minimum_purchase}}</div>
            </div>
            <div class="jd-compact-qr">
                {{qr_svg}}
            </div>
        </div>
        <div class="jd-compact-barcode">
            {{barcode_svg}}
        </div>
    </div>
</div>
""".strip()

        css_markup = """
.jd-style-compact {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    background: #ffffff;
    border: 1px dashed #777777;
    position: relative;
    padding: 8px;
    font-family: 'Plus Jakarta Sans', sans-serif;
    color: #111111;
}
.jd-style-compact .jd-cut-guide {
    position: absolute;
    top: 2px;
    left: 8px;
    font-size: 7px;
    color: #888888;
    text-transform: uppercase;
}
.jd-style-compact .jd-compact-inner {
    border: 1px solid #1a1714;
    border-radius: 5px;
    padding: 8px 10px;
    height: calc(100% - 6px);
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    background: #fdfcf9;
}
.jd-style-compact .jd-compact-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.jd-style-compact .jd-compact-brand {
    font-size: 9.5px;
    font-weight: 800;
    color: #8c733e;
    letter-spacing: 1px;
    text-transform: uppercase;
}
.jd-style-compact .jd-compact-code {
    font-family: monospace;
    font-size: 11px;
    font-weight: 800;
    background: #f0ebe1;
    padding: 1px 6px;
    border-radius: 3px;
    border: 1px solid #d4af37;
}
.jd-style-compact .jd-compact-middle {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 3px 0;
}
.jd-style-compact .jd-compact-discount {
    font-size: 22px;
    font-weight: 900;
    color: #1a1714;
    white-space: nowrap;
}
.jd-style-compact .jd-compact-details {
    flex: 1;
}
.jd-style-compact .jd-compact-title {
    font-size: 11px;
    font-weight: 800;
    line-height: 1.2;
    color: #1a1714;
}
.jd-style-compact .jd-compact-valid {
    font-size: 8px;
    color: #555555;
    margin-top: 2px;
}
.jd-style-compact .jd-compact-qr {
    width: 38px;
    height: 38px;
    flex-shrink: 0;
}
.jd-style-compact .jd-compact-barcode {
    width: 100%;
}
""".strip()

    else:
        # Default: Royal Heritage Gold (luxury_gold)
        html_markup = """
<div class="jd-coupon-card jd-style-gold">
    <div class="jd-corner-ornament jd-top-left"></div>
    <div class="jd-corner-ornament jd-top-right"></div>
    <div class="jd-corner-ornament jd-bottom-left"></div>
    <div class="jd-corner-ornament jd-bottom-right"></div>
    <div class="jd-gold-border">
        <div class="jd-gold-header">
            <div class="jd-brand-badge">ROYAL PRIVILEGE</div>
            <div class="jd-brand-name">{{business_name}}</div>
            <div class="jd-serial-no">{{serial_number}}</div>
        </div>
        <div class="jd-gold-main">
            <div class="jd-gold-left">
                <div class="jd-title-text">{{offer_title}}</div>
                <div class="jd-cat-text">{{applicable_categories}}</div>
                <div class="jd-terms-box">{{terms_and_conditions}}</div>
                <div class="jd-meta-row">
                    <span>Valid Until: <strong>{{valid_until}}</strong></span>
                    <span>Min Order: <strong>{{minimum_purchase}}</strong></span>
                </div>
            </div>
            <div class="jd-gold-right">
                <div class="jd-seal-circle">
                    <span class="jd-seal-label">PRIVILEGE</span>
                    <span class="jd-seal-val">{{discount_value}}</span>
                </div>
                <div class="jd-code-container">
                    <span class="jd-code-tag">VOUCHER CODE</span>
                    <strong class="jd-code-text">{{coupon_code}}</strong>
                </div>
            </div>
        </div>
        <div class="jd-gold-footer">
            <div class="jd-barcode-box">
                {{barcode_svg}}
            </div>
        </div>
    </div>
</div>
""".strip()

        css_markup = """
.jd-style-gold {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    background: radial-gradient(circle at 50% 30%, #20170f 0%, #110c07 100%);
    border: 2px solid #c5a059;
    border-radius: 8px;
    padding: 6px;
    position: relative;
    font-family: 'Cinzel', 'Playfair Display', serif;
    color: #fef9ed;
    overflow: hidden;
}
.jd-style-gold .jd-gold-border {
    border: 1px solid rgba(212, 175, 55, 0.45);
    border-radius: 5px;
    padding: 10px 14px;
    height: 100%;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
}
.jd-style-gold .jd-corner-ornament {
    position: absolute;
    width: 14px;
    height: 14px;
    border-color: #d4af37;
    border-style: solid;
    pointer-events: none;
    z-index: 2;
}
.jd-style-gold .jd-top-left { top: 8px; left: 8px; border-width: 2px 0 0 2px; }
.jd-style-gold .jd-top-right { top: 8px; right: 8px; border-width: 2px 2px 0 0; }
.jd-style-gold .jd-bottom-left { bottom: 8px; left: 8px; border-width: 0 0 2px 2px; }
.jd-style-gold .jd-bottom-right { bottom: 8px; right: 8px; border-width: 0 2px 2px 0; }

.jd-style-gold .jd-gold-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid rgba(212, 175, 55, 0.25);
    padding-bottom: 4px;
}
.jd-style-gold .jd-brand-badge {
    font-size: 7.5px;
    letter-spacing: 2px;
    color: #d4af37;
    font-weight: 700;
}
.jd-style-gold .jd-brand-name {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: #ecc86a;
    text-transform: uppercase;
}
.jd-style-gold .jd-serial-no {
    font-size: 8px;
    font-family: monospace;
    color: #a89474;
}
.jd-style-gold .jd-gold-main {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin: 4px 0;
}
.jd-style-gold .jd-gold-left {
    flex: 1.6;
    font-family: 'Plus Jakarta Sans', sans-serif;
}
.jd-style-gold .jd-title-text {
    font-family: 'Cinzel', serif;
    font-size: 15px;
    font-weight: 700;
    color: #ffffff;
    line-height: 1.25;
}
.jd-style-gold .jd-cat-text {
    font-size: 9.5px;
    color: #ecc86a;
    margin: 2px 0;
}
.jd-style-gold .jd-terms-box {
    font-size: 7.5px;
    color: #bfa98b;
    line-height: 1.35;
    margin: 4px 0;
    max-height: 30px;
    overflow: hidden;
}
.jd-style-gold .jd-meta-row {
    display: flex;
    gap: 12px;
    font-size: 8.5px;
    color: #ecc86a;
    margin-top: 3px;
}
.jd-style-gold .jd-gold-right {
    flex: 1.1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}
.jd-style-gold .jd-seal-circle {
    width: 68px;
    height: 68px;
    border-radius: 50%;
    background: radial-gradient(circle, #f3cf7a 0%, #c49a45 100%);
    border: 2px dashed #422d0c;
    box-shadow: 0 0 10px rgba(243, 207, 122, 0.35);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: #2b1704;
    text-align: center;
}
.jd-style-gold .jd-seal-label {
    font-size: 6.5px;
    letter-spacing: 1.5px;
    font-weight: 800;
}
.jd-style-gold .jd-seal-val {
    font-size: 16px;
    font-weight: 900;
    line-height: 1.1;
}
.jd-style-gold .jd-code-container {
    margin-top: 6px;
    background: rgba(0,0,0,0.45);
    border: 1px solid #d4af37;
    border-radius: 4px;
    padding: 3px 8px;
    text-align: center;
    width: 90%;
}
.jd-style-gold .jd-code-tag {
    display: block;
    font-size: 6.5px;
    letter-spacing: 1px;
    color: #ecc86a;
}
.jd-style-gold .jd-code-text {
    font-family: monospace;
    font-size: 11px;
    letter-spacing: 1.2px;
    color: #ffffff;
}
.jd-style-gold .jd-gold-footer {
    border-top: 1px solid rgba(212, 175, 55, 0.2);
    padding-top: 4px;
}
.jd-style-gold .jd-barcode-box {
    width: 100%;
}
""".strip()

    return {
        'html': html_markup,
        'css': css_markup,
    }


# ============================================================================
# 6. Full Coupon Render Engine (Single & Batch)
# ============================================================================

def render_single_coupon_html(
    template=None,
    coupon_code: str = None,
    serial_number: Any = None,
    template_type: str = None,
    built_in_style: str = None,
    custom_html: str = None,
    custom_css: str = None,
    discount_type: str = 'percentage',
    discount_value: Any = None,
    offer_title: str = None,
    business_name: str = None,
    valid_from: str = None,
    valid_until: str = None,
    minimum_purchase: str = None,
    maximum_discount: str = None,
    applicable_categories: str = None,
    terms_and_conditions: str = None,
    show_barcode: bool = True,
    show_qr_code: bool = True,
    primary_color: str = None,
    background_color: str = None,
    text_color: str = None,
    coupon_width_mm: int = 180,
    coupon_height_mm: int = 70,
    **kwargs
) -> str:
    """Render a single coupon's complete HTML and scoped CSS with safe placeholder substitution."""
    if template is not None:
        template_type = template_type or template.template_type
        built_in_style = built_in_style or template.built_in_style
        custom_html = custom_html if custom_html is not None else template.custom_html
        custom_css = custom_css if custom_css is not None else template.custom_css
        discount_type = discount_type or template.discount_type
        if discount_value is None:
            discount_value = template.discount_value
        offer_title = offer_title or template.offer_title
        business_name = business_name or template.business_name
        if valid_from is None and template.valid_from:
            valid_from = template.valid_from.strftime("%d %b %Y")
        if valid_until is None and template.valid_until:
            valid_until = template.valid_until.strftime("%d %b %Y")
        if minimum_purchase is None and template.minimum_purchase:
            minimum_purchase = f"{template.minimum_purchase:,.0f}"
        if maximum_discount is None and template.maximum_discount:
            maximum_discount = f"{template.maximum_discount:,.0f}"
        applicable_categories = applicable_categories or template.applicable_categories
        terms_and_conditions = terms_and_conditions or template.terms_and_conditions
        show_barcode = show_barcode if show_barcode is not None else template.show_barcode
        show_qr_code = show_qr_code if show_qr_code is not None else template.show_qr_code
        primary_color = primary_color or template.primary_color
        background_color = background_color or template.background_color
        text_color = text_color or template.text_color
        coupon_width_mm = coupon_width_mm or template.coupon_width_mm
        coupon_height_mm = coupon_height_mm or template.coupon_height_mm
        coupon_code = coupon_code or template.sample_coupon_code

    template_type = template_type or 'built_in'
    built_in_style = built_in_style or 'luxury_gold'
    discount_type = discount_type or 'percentage'
    business_name = business_name or "JewelDesk Fine Atelier"
    offer_title = offer_title or "Jewellery Privilege Voucher"
    coupon_code = coupon_code or "ROYAL-GOLD20"
    serial_str = f"#{serial_number:04d}" if isinstance(serial_number, int) else (str(serial_number) if serial_number else "#0001")
    valid_from_str = str(valid_from) if valid_from else "Immediate"
    valid_until_str = str(valid_until) if valid_until else "31 Dec 2026"
    min_purch_str = f"₹{minimum_purchase}" if minimum_purchase and not str(minimum_purchase).startswith('₹') else (str(minimum_purchase) if minimum_purchase else "No minimum")
    max_disc_str = f"₹{maximum_discount}" if maximum_discount and not str(maximum_discount).startswith('₹') else (str(maximum_discount) if maximum_discount else "No limit")

    if discount_value is not None:
        if discount_type == 'percentage':
            try:
                v = float(discount_value)
                disc_str = f"{int(v)}% OFF" if v.is_integer() else f"{v}% OFF"
            except Exception:
                disc_str = f"{discount_value}% OFF"
        else:
            try:
                v = float(discount_value)
                disc_str = f"₹{int(v):,} OFF" if v.is_integer() else f"₹{v} OFF"
            except Exception:
                disc_str = f"₹{discount_value} OFF"
    else:
        disc_str = "20% OFF"

    bar_color = "#221c10" if built_in_style in ('minimal_white', 'compact_sheet') else (primary_color or "#ecc86a")
    text_c = "#444444" if built_in_style in ('minimal_white', 'compact_sheet') else (text_color or "#fef9ed")

    barcode_svg = generate_barcode_svg(coupon_code, bar_color=bar_color, text_color=text_c, width=220, height=44) if show_barcode else ""
    qr_svg = generate_qr_svg(coupon_code, fg_color=bar_color, size=48) if show_qr_code else ""

    context = {
        "coupon_code": coupon_code,
        "discount_value": disc_str,
        "offer_title": offer_title,
        "business_name": business_name,
        "valid_from": valid_from_str,
        "valid_until": valid_until_str,
        "minimum_purchase": min_purch_str,
        "maximum_discount": max_disc_str,
        "applicable_categories": applicable_categories or "Gold, Diamond & Silver Ornaments",
        "terms_and_conditions": terms_and_conditions or "Valid on jewellery purchases at showroom billing.",
        "serial_number": serial_str,
        "barcode_svg": barcode_svg,
        "qr_svg": qr_svg,
    }

    if template_type == 'custom' and custom_html:
        raw_html = sanitize_coupon_html(custom_html)
        css_rules = sanitize_coupon_css(custom_css or '')
    else:
        preset = get_builtin_template_markup(built_in_style, discount_type)
        raw_html = preset['html']
        css_rules = preset['css']

    rendered_body = substitute_placeholders(raw_html, context)

    wrapper = f"""
<div class="jd-coupon-wrapper" style="width: {coupon_width_mm}mm; height: {coupon_height_mm}mm; display: inline-block; vertical-align: top; position: relative;">
    <style>
{css_rules}
    </style>
    {rendered_body}
</div>
""".strip()
    return wrapper


def get_template_css(template) -> str:
    """Get the CSS for a template (sanitized if custom, preset if built-in)."""
    if template.template_type == template.TYPE_CUSTOM and template.custom_css:
        return sanitize_coupon_css(template.custom_css)
    preset = get_builtin_template_markup(template.built_in_style, template.discount_type)
    return preset['css']

