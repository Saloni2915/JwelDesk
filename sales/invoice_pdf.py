"""
PDF invoice generation for sales, built with ReportLab.

Renders authentic Indian Jewellery Showroom Tax Invoices (and Non-GST Retail Cash Memos)
compliant with:
- Section 31 of CGST Act 2017.
- HSN Code 7113 (Gold/Silver Jewellery).
- BIS Hallmarking & HUID identification.
- Accurate right-aligned numerical weights and currency amounts formatted with Indian comma grouping.
"""
import io
from decimal import Decimal

from django.core.files.storage import default_storage
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Image as RLImage, Paragraph
from reportlab.lib.units import mm

from accounts.models import CompanySettings
from .invoice_utils import calculate_invoice_breakdown, get_state_from_gstin


BRAND_DARK = colors.HexColor('#1E293B')      # Slate 800
BRAND_GOLD = colors.HexColor('#B45309')      # Amber 700 / Jewellery Gold
BRAND_GOLD_BG = colors.HexColor('#FEF3C7')   # Amber 100 subtle
BRAND_MUTED = colors.HexColor('#64748B')     # Slate 500
BRAND_LIGHT_BG = colors.HexColor('#F8FAFC')  # Slate 50
BORDER_COLOR = colors.HexColor('#CBD5E1')    # Slate 300


def _format_inr(val, decimals=2) -> str:
    """Format numeric currency value into authentic Indian numbering notation: 485436.89 -> 4,85,436.89"""
    if val is None:
        return '0.00' if decimals else '0'
    try:
        d = Decimal(str(val))
    except Exception:
        return str(val)
    sign = '-' if d < 0 else ''
    d = abs(d)
    s = f"{d:.{decimals}f}" if decimals else f"{d:.0f}"
    parts = s.split('.')
    int_part = parts[0]
    dec_part = '.' + parts[1] if len(parts) > 1 else ''
    if len(int_part) <= 3:
        return sign + int_part + dec_part
    last_three = int_part[-3:]
    rest = int_part[:-3]
    groups = []
    while len(rest) > 2:
        groups.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.append(rest)
    groups.reverse()
    return sign + ','.join(groups) + ',' + last_three + dec_part


def _split_purity(purity_str):
    """
    Intelligently splits long jewellery purity strings into two balanced lines
    to avoid horizontal collision with adjacent table columns.
    e.g. '22K (916 Hallmarked)' -> ('22K (916)', 'Hallmarked')
         '18K (750) / VVS-1 GH' -> ('18K (750)', 'VVS-1 GH')
         '925 Sterling Silver'   -> ('925 Silver', 'Sterling')
         '22K (916)'             -> ('22K (916)', '')
         '22K'                   -> ('22K', '')
    """
    if not purity_str:
        return '22K', ''
    import re
    p = str(purity_str).strip()
    if 'Hallmark' in p or 'hallmark' in p:
        p_clean = re.sub(r'\b[Hh]allmarked?\b', '', p)
        p_clean = re.sub(r'\s*\)', ')', p_clean)
        p_clean = re.sub(r'\(\s*', '(', p_clean)
        p_clean = re.sub(r'\(\s*\)', '', p_clean)
        p_clean = re.sub(r'\s+', ' ', p_clean).strip()
        p_clean = p_clean.rstrip(' -/')
        return p_clean or '22K (916)', 'Hallmarked'
    if '/' in p:
        parts = p.split('/', 1)
        return parts[0].strip(), parts[1].strip()
    if 'Sterling' in p:
        clean = re.sub(r'\s+', ' ', p.replace('Sterling', '')).strip()
        return clean or '925 Silver', 'Sterling'
    if len(p) > 10 and ' ' in p:
        parts = p.split(' ', 1)
        return parts[0].strip(), parts[1].strip()
    return p, ''


def _local_date_str(dt):
    if not dt:
        return ''
    loc = timezone.localtime(dt)
    return loc.strftime('%d-%b-%Y')


def _local_time_str(dt):
    if not dt:
        return ''
    loc = timezone.localtime(dt)
    return loc.strftime('%I:%M %p')


def build_invoice_pdf(sale, include_gst: bool = True) -> bytes:
    """Return the PDF bytes for the given Sale in standard jewellery format."""
    company = CompanySettings.objects.first()
    company_name = (company.company_name if company and company.company_name else 'JewelDesk Showroom')
    gstin = company.gstin.strip().upper() if company and company.gstin else ''
    address = (company.address if company else '') or ''
    phone = company.phone if company else ''
    email = company.email if company else ''
    footer_note = (company.invoice_footer_note if company else '') or ''

    state_name, state_code = get_state_from_gstin(gstin)
    breakdown = calculate_invoice_breakdown(sale, include_gst=include_gst)

    item = sale.jewellery_item
    customer = sale.customer

    buffer = io.BytesIO()
    page_w, page_h = A4
    c = pdf_canvas.Canvas(buffer, pagesize=A4, pageCompression=0)
    base = getSampleStyleSheet()

    def wrapped(text, x, y, width, font_name='Helvetica', font_size=8, leading=10, color=BRAND_DARK):
        """Draw wrapped paragraph top-down and return final y."""
        if not text:
            return y
        para = ParagraphStyle(
            'p_wrap',
            parent=base['Normal'],
            fontName=font_name,
            fontSize=font_size,
            leading=leading,
            textColor=color
        )
        p = Paragraph(str(text), para)
        _w, h = p.wrap(width, page_h)
        p.drawOn(c, x, y - h)
        return y - h

    # Margins: 12mm left/right -> content_w = 186mm
    left_m = 12 * mm
    right_m = page_w - 12 * mm
    content_w = right_m - left_m
    y = page_h - 12 * mm

    # =========================================================================
    # 1. SHOWROOM HEADER
    # =========================================================================
    header_top = y
    logo_drawn = False
    if company and company.logo:
        try:
            if hasattr(company, 'ensure_logo_file'):
                company.ensure_logo_file()
        except Exception:
            pass
        if default_storage.exists(company.logo.name):
            try:
                with company.logo.open('rb') as fh:
                    img = RLImage(fh, width=32 * mm, height=14 * mm, kind='proportional')
                    img.drawOn(c, left_m, header_top - 14 * mm)
                    logo_drawn = True
            except Exception:
                pass

    header_text_x = (left_m + 36 * mm) if logo_drawn else (page_w / 2)
    header_align = 'left' if logo_drawn else 'center'

    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 15)
    if header_align == 'center':
        c.drawCentredString(header_text_x, y, company_name.upper())
    else:
        c.drawString(header_text_x, y, company_name.upper())
    y -= 4.5 * mm

    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(BRAND_GOLD)
    tagline = 'MANUFACTURERS & RETAIL JEWELLERS • GOLD & SILVER ORNAMENTS • BIS HALLMARKED'
    if header_align == 'center':
        c.drawCentredString(header_text_x, y, tagline)
    else:
        c.drawString(header_text_x, y, tagline)
    y -= 4 * mm

    c.setFont('Helvetica', 8)
    c.setFillColor(BRAND_DARK)
    addr_line = address.replace('\n', ', ') if address else 'Showroom Counter, Jewel Market'
    if header_align == 'center':
        c.drawCentredString(header_text_x, y, addr_line[:110])
    else:
        c.drawString(header_text_x, y, addr_line[:90])
    y -= 3.5 * mm

    contact_bits = []
    if phone:
        contact_bits.append(f'Phone: {phone}')
    if email:
        contact_bits.append(f'Email: {email}')
    contact_str = ' | '.join(contact_bits) if contact_bits else 'Customer Support Counter'
    if header_align == 'center':
        c.drawCentredString(header_text_x, y, contact_str)
    else:
        c.drawString(header_text_x, y, contact_str)
    y -= 5 * mm

    # Statutory Band (GSTIN, State, BIS)
    c.setFillColor(BRAND_LIGHT_BG)
    c.setStrokeColor(BORDER_COLOR)
    c.setLineWidth(0.5)
    c.rect(left_m, y - 5 * mm, content_w, 6.5 * mm, stroke=1, fill=1)

    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(BRAND_DARK)
    gstin_display = f'GSTIN: {gstin}' if gstin else 'GSTIN: UNREGISTERED / COMPOSITION'
    c.drawString(left_m + 3 * mm, y - 3.5 * mm, gstin_display)
    c.drawString(left_m + 72 * mm, y - 3.5 * mm, f'STATE: {state_name.upper()} (CODE: {state_code})')
    c.setFillColor(BRAND_GOLD)
    c.drawRightString(right_m - 3 * mm, y - 3.5 * mm, 'BIS 916 & HUID CERTIFIED')
    y -= 9 * mm

    # =========================================================================
    # 2. DOCUMENT TITLE BANNER
    # =========================================================================
    doc_title = 'TAX INVOICE' if include_gst else 'RETAIL INVOICE / CASH MEMO'
    doc_sub = '(Issued under Section 31 of CGST Act, 2017)' if include_gst else '(Non-GST Retail Supply / Cash Memo)'

    c.setFillColor(BRAND_GOLD_BG if include_gst else BRAND_LIGHT_BG)
    c.setStrokeColor(BRAND_GOLD if include_gst else BORDER_COLOR)
    c.setLineWidth(1)
    c.rect(left_m, y - 7 * mm, content_w, 8 * mm, stroke=1, fill=1)

    c.setFillColor(BRAND_GOLD if include_gst else BRAND_DARK)
    c.setFont('Helvetica-Bold', 12)
    c.drawCentredString(page_w / 2, y - 3 * mm, doc_title)
    c.setFont('Helvetica', 7.5)
    c.setFillColor(BRAND_DARK)
    c.drawCentredString(page_w / 2, y - 6 * mm, doc_sub)
    y -= 10 * mm

    # =========================================================================
    # 3. INVOICE META & BUYER DETAILS (2-Column Box)
    # =========================================================================
    box_w = (content_w - 4 * mm) / 2
    box_h = 24 * mm
    top_box_y = y

    # Left Box: Billed To (Buyer)
    c.setFillColor(colors.white)
    c.setStrokeColor(BORDER_COLOR)
    c.setLineWidth(0.5)
    c.rect(left_m, top_box_y - box_h, box_w, box_h, stroke=1, fill=1)

    # Header strip inside left box
    c.setFillColor(BRAND_LIGHT_BG)
    c.rect(left_m, top_box_y - 5 * mm, box_w, 5 * mm, stroke=0, fill=1)
    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(left_m + 2.5 * mm, top_box_y - 3.8 * mm, 'BILLED TO (BUYER DETAILS)')

    c.setFont('Helvetica-Bold', 9)
    c.drawString(left_m + 2.5 * mm, top_box_y - 8.5 * mm, customer.name[:35])
    c.setFont('Helvetica', 8)
    c.setFillColor(BRAND_MUTED)
    c.drawString(left_m + 2.5 * mm, top_box_y - 12.5 * mm, f'Mobile: {customer.mobile}')
    cust_addr = (customer.address or 'Counter Sale / Retail Consumer').replace('\n', ', ')
    c.drawString(left_m + 2.5 * mm, top_box_y - 16.5 * mm, f'Address: {cust_addr[:40]}')
    c.drawString(left_m + 2.5 * mm, top_box_y - 20.5 * mm, 'Buyer GSTIN: Unregistered Consumer')

    # Right Box: Invoice Details
    right_box_x = left_m + box_w + 4 * mm
    c.setFillColor(colors.white)
    c.rect(right_box_x, top_box_y - box_h, box_w, box_h, stroke=1, fill=1)

    c.setFillColor(BRAND_LIGHT_BG)
    c.rect(right_box_x, top_box_y - 5 * mm, box_w, 5 * mm, stroke=0, fill=1)
    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(right_box_x + 2.5 * mm, top_box_y - 3.8 * mm, 'INVOICE & DISPATCH DETAILS')

    c.setFont('Helvetica', 8)
    c.setFillColor(BRAND_DARK)
    c.drawString(right_box_x + 2.5 * mm, top_box_y - 8.5 * mm, 'Invoice No:')
    c.setFont('Helvetica-Bold', 8.5)
    c.drawRightString(right_box_x + box_w - 2.5 * mm, top_box_y - 8.5 * mm, f'INV-{sale.pk:05d}')

    c.setFont('Helvetica', 8)
    c.drawString(right_box_x + 2.5 * mm, top_box_y - 12.5 * mm, 'Date & Time:')
    c.drawRightString(right_box_x + box_w - 2.5 * mm, top_box_y - 12.5 * mm,
                      f'{_local_date_str(sale.sale_date)} {_local_time_str(sale.sale_date)}')

    c.drawString(right_box_x + 2.5 * mm, top_box_y - 16.5 * mm, 'Place of Supply:')
    c.drawRightString(right_box_x + box_w - 2.5 * mm, top_box_y - 16.5 * mm, f'{state_name} ({state_code})')

    c.drawString(right_box_x + 2.5 * mm, top_box_y - 20.5 * mm, 'Payment Method:')
    c.setFont('Helvetica-Bold', 8)
    # Handle split tender payment methods nicely
    pm_display = sale.payment_method
    if getattr(sale, 'second_payment_method', None) and sale.second_payment_method:
        pm_display = f"{sale.payment_method} + {sale.second_payment_method}"
    c.drawRightString(right_box_x + box_w - 2.5 * mm, top_box_y - 20.5 * mm, pm_display[:24])

    y = top_box_y - box_h - 4 * mm

    # =========================================================================
    # 4. JEWELLERY LINE ITEMS TABLE
    # Perfectly rebalanced 10-column grid preventing all text overlap & clipping
    # Total content_w = 186 mm
    # 0. Sr. (center)            width 7mm   x: 12..19
    # 1. Description (left)      width 45mm  x: 19..64
    # 2. HSN (center)            width 12mm  x: 64..76
    # 3. Purity (center)         width 19mm  x: 76..95
    # 4. Gross Wt (right)        width 14mm  x: 95..109
    # 5. Less Wt (right)         width 13mm  x: 109..122
    # 6. Net Wt (right)          width 15mm  x: 122..137
    # 7. Rate / g (right)        width 19mm  x: 137..156
    # 8. Making (right)          width 18mm  x: 156..174
    # 9. Taxable Amt (right)    width 24mm  x: 174..198
    # =========================================================================
    col_bounds = [
        (left_m, left_m + 7 * mm),             # 0: Sr
        (left_m + 7 * mm, left_m + 52 * mm),   # 1: Description
        (left_m + 52 * mm, left_m + 64 * mm),  # 2: HSN
        (left_m + 64 * mm, left_m + 83 * mm),  # 3: Purity
        (left_m + 83 * mm, left_m + 97 * mm),  # 4: Gross Wt
        (left_m + 97 * mm, left_m + 110 * mm), # 5: Less Wt
        (left_m + 110 * mm, left_m + 125 * mm),# 6: Net Wt
        (left_m + 125 * mm, left_m + 144 * mm),# 7: Rate / g
        (left_m + 144 * mm, left_m + 162 * mm),# 8: Making
        (left_m + 162 * mm, right_m),          # 9: Taxable / Amount
    ]

    tbl_header_h = 7 * mm
    c.setFillColor(BRAND_DARK)
    c.rect(left_m, y - tbl_header_h, content_w, tbl_header_h, stroke=0, fill=1)

    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 7.5)
    c.drawCentredString((col_bounds[0][0] + col_bounds[0][1]) / 2, y - 4.5 * mm, 'Sr.')
    c.drawString(col_bounds[1][0] + 2 * mm, y - 4.5 * mm, 'Description of Goods')
    c.drawCentredString((col_bounds[2][0] + col_bounds[2][1]) / 2, y - 4.5 * mm, 'HSN')
    c.drawCentredString((col_bounds[3][0] + col_bounds[3][1]) / 2, y - 4.5 * mm, 'Purity')
    c.drawRightString(col_bounds[4][1] - 1.5 * mm, y - 4.5 * mm, 'Gross Wt')
    c.drawRightString(col_bounds[5][1] - 1.5 * mm, y - 4.5 * mm, 'Less Wt')
    c.drawRightString(col_bounds[6][1] - 1.5 * mm, y - 4.5 * mm, 'Net Wt')
    c.drawRightString(col_bounds[7][1] - 1.5 * mm, y - 4.5 * mm, 'Rate / g')
    c.drawRightString(col_bounds[8][1] - 1.5 * mm, y - 4.5 * mm, 'Making')
    amt_header_label = 'Taxable Amt' if include_gst else 'Amount'
    c.drawRightString(col_bounds[9][1] - 2 * mm, y - 4.5 * mm, amt_header_label)

    y -= tbl_header_h

    # Table Item Data Row (height 18.5mm gives generous breathing room)
    row_h = 18.5 * mm
    c.setFillColor(colors.white)
    c.setStrokeColor(BORDER_COLOR)
    c.setLineWidth(0.5)
    c.rect(left_m, y - row_h, content_w, row_h, stroke=1, fill=1)

    # Vertical column separator lines
    for b in col_bounds[:-1]:
        c.line(b[1], y, b[1], y - row_h)

    # 0. Sr.
    c.setFont('Helvetica', 8)
    c.setFillColor(BRAND_DARK)
    c.drawCentredString((col_bounds[0][0] + col_bounds[0][1]) / 2, y - 6.5 * mm, '1')

    # 1. Description & HUID / Tag
    desc_x = col_bounds[1][0] + 2 * mm
    desc_w = (col_bounds[1][1] - col_bounds[1][0]) - 3 * mm
    item_name = str(item.name or 'Jewellery Item').strip()

    c.setFillColor(BRAND_DARK)
    # Check if item name needs 2 lines or 1 line
    if len(item_name) > 28:
        # Wrap cleanly with Paragraph
        p_name = Paragraph(
            f"<b>{item_name}</b>",
            ParagraphStyle(
                'item_desc_name',
                parent=base['Normal'],
                fontName='Helvetica-Bold',
                fontSize=7.8,
                leading=9.2,
                textColor=BRAND_DARK
            )
        )
        _, h_name = p_name.wrap(desc_w, 10 * mm)
        p_name.drawOn(c, desc_x, y - h_name - 1.2 * mm)
        sub_y = y - h_name - 3.2 * mm
    else:
        c.setFont('Helvetica-Bold', 8)
        c.drawString(desc_x, y - 4.2 * mm, item_name)
        sub_y = y - 7.5 * mm

    c.setFont('Helvetica', 6.8)
    c.setFillColor(BRAND_MUTED)
    cat_name = getattr(getattr(item, 'category', None), 'name', '')
    tag_str = item.tag_number or item.item_code or ''
    huid_str = item.huid or ''

    specs = []
    if cat_name:
        specs.append(cat_name)
    if tag_str:
        specs.append(f'Tag: {tag_str}')
    if huid_str:
        specs.append(f'HUID: {huid_str}')
    specs_line = ' • '.join(specs)
    c.drawString(desc_x, sub_y, specs_line[:40])

    if item.design_code and item.design_code != item.item_code:
        c.drawString(desc_x, sub_y - 3.2 * mm, f'Design: {item.design_code[:22]}')

    # 2. HSN Code
    c.setFont('Helvetica', 7.8)
    c.setFillColor(BRAND_DARK)
    c.drawCentredString((col_bounds[2][0] + col_bounds[2][1]) / 2, y - 6.5 * mm, str(breakdown.get('hsn_code', '7113')))

    # 3. Purity (Smart Two-Line Layout preventing all overlap into HSN & Gross Wt)
    main_purity, sub_purity = _split_purity(item.purity or '22K (916)')
    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 7.6)
    purity_cx = (col_bounds[3][0] + col_bounds[3][1]) / 2

    if sub_purity:
        c.drawCentredString(purity_cx, y - 5.5 * mm, main_purity)
        c.setFont('Helvetica', 6.5)
        c.setFillColor(BRAND_GOLD)
        c.drawCentredString(purity_cx, y - 9.0 * mm, sub_purity)
    else:
        c.drawCentredString(purity_cx, y - 6.5 * mm, main_purity)

    # 4. Gross Wt
    c.setFont('Helvetica', 7.5)
    c.setFillColor(BRAND_DARK)
    c.drawRightString(col_bounds[4][1] - 1.5 * mm, y - 6.5 * mm, f"{breakdown['gross_weight']:,.3f}g")

    # 5. Less Wt
    c.drawRightString(col_bounds[5][1] - 1.5 * mm, y - 6.5 * mm, f"{breakdown['stone_weight']:,.3f}g")

    # 6. Net Wt (Bold)
    c.setFont('Helvetica-Bold', 7.5)
    c.drawRightString(col_bounds[6][1] - 1.5 * mm, y - 6.5 * mm, f"{breakdown['net_weight']:,.3f}g")

    # 7. Rate / g
    c.setFont('Helvetica', 7.5)
    rate_val = f"Rs. {_format_inr(breakdown['rate_per_gram'])}" if breakdown['rate_per_gram'] > 0 else '—'
    c.drawRightString(col_bounds[7][1] - 1.5 * mm, y - 6.5 * mm, rate_val)

    # 8. Making Charges
    mk_val = f"Rs. {_format_inr(breakdown['making_charges'])}" if breakdown['making_charges'] > 0 else 'Included'
    c.drawRightString(col_bounds[8][1] - 1.5 * mm, y - 6.5 * mm, mk_val)

    # 9. Taxable Amt / Amount
    c.setFont('Helvetica-Bold', 8)
    c.drawRightString(col_bounds[9][1] - 2 * mm, y - 6.5 * mm, f"Rs. {_format_inr(breakdown['taxable_value'])}")

    y -= row_h

    # Weight Totals Strip
    strip_h = 5 * mm
    c.setFillColor(BRAND_LIGHT_BG)
    c.setStrokeColor(BORDER_COLOR)
    c.rect(left_m, y - strip_h, content_w, strip_h, stroke=1, fill=1)
    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 7.5)
    c.drawString(left_m + 3 * mm, y - 3.5 * mm, 'WEIGHT TOTALS:')
    c.setFont('Helvetica', 7.5)
    wt_text = (f"Gross Weight: {breakdown['gross_weight']:,.3f} g    |    "
               f"Stone/Less Weight: {breakdown['stone_weight']:,.3f} g    |    "
               f"Net Precious Metal Weight: {breakdown['net_weight']:,.3f} g")
    c.drawString(left_m + 28 * mm, y - 3.5 * mm, wt_text)
    y -= (strip_h + 3.5 * mm)

    # =========================================================================
    # 5. FINANCIAL SETTLEMENT & TAX CALCULATION (2-Column Box)
    # Left: Amount in words, Payment Mode, Terms & Conditions
    # Right: Taxable, CGST, SGST, Round off, Grand Total, Paid, Balance
    # =========================================================================
    summary_left_w = content_w * 0.54
    summary_right_w = content_w - summary_left_w - 4 * mm
    summary_right_x = left_m + summary_left_w + 4 * mm
    summary_h = 60 * mm
    summary_top_y = y

    # LEFT BOX: Words, Notes & Terms
    c.setFillColor(colors.white)
    c.setStrokeColor(BORDER_COLOR)
    c.rect(left_m, summary_top_y - summary_h, summary_left_w, summary_h, stroke=1, fill=1)

    # Words banner inside left box
    c.setFillColor(BRAND_LIGHT_BG)
    c.rect(left_m, summary_top_y - 12 * mm, summary_left_w, 12 * mm, stroke=0, fill=1)
    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 7.5)
    c.drawString(left_m + 2.5 * mm, summary_top_y - 4 * mm, 'AMOUNT IN WORDS (INR):')
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(BRAND_GOLD)
    wrapped(breakdown['amount_in_words'], left_m + 2.5 * mm, summary_top_y - 6 * mm,
            summary_left_w - 5 * mm, font_name='Helvetica-Bold', font_size=7.5, leading=9.5, color=BRAND_GOLD)

    # Payment info
    c.setFont('Helvetica', 7.5)
    c.setFillColor(BRAND_DARK)
    c.drawString(left_m + 2.5 * mm, summary_top_y - 16 * mm,
                 f"Payment Mode: {pm_display}    |    Status: {sale.payment_status}")

    # Notes if any
    notes_y = summary_top_y - 19.5 * mm
    if sale.notes:
        c.setFont('Helvetica-Oblique', 7)
        c.setFillColor(BRAND_MUTED)
        c.drawString(left_m + 2.5 * mm, notes_y, f"Note: {sale.notes[:50]}")
        notes_y -= 4 * mm

    # Declarations / Terms
    c.setStrokeColor(BORDER_COLOR)
    c.line(left_m, notes_y + 1 * mm, left_m + summary_left_w, notes_y + 1 * mm)
    c.setFont('Helvetica-Bold', 7)
    c.setFillColor(BRAND_DARK)
    c.drawString(left_m + 2.5 * mm, notes_y - 2.5 * mm, 'TERMS & CONDITIONS:')
    c.setFont('Helvetica', 6.5)
    c.setFillColor(BRAND_MUTED)
    terms = [
        '1. Goods sold are BIS Hallmarked as per Bureau of Indian Standards (HUID certified).',
        '2. Weight, purity, gemstones & ornament verified by buyer before purchase.',
        '3. Exchange / buyback as per showroom policy against this original invoice only.',
        '4. All disputes subject to showroom local jurisdiction.'
    ]
    term_y = notes_y - 5.5 * mm
    for t in terms:
        c.drawString(left_m + 2.5 * mm, term_y, t)
        term_y -= 3 * mm

    # RIGHT BOX: Calculation Grid
    c.setFillColor(colors.white)
    c.rect(summary_right_x, summary_top_y - summary_h, summary_right_w, summary_h, stroke=1, fill=1)

    calc_y = summary_top_y - 4.5 * mm
    def calc_row(label, val_str, bold=False, font_size=7.8, bg=None, text_color=BRAND_DARK):
        nonlocal calc_y
        if bg:
            c.setFillColor(bg)
            c.rect(summary_right_x, calc_y - 1.8 * mm, summary_right_w, 5.5 * mm, stroke=0, fill=1)
        c.setFillColor(text_color)
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', font_size)
        c.drawString(summary_right_x + 3 * mm, calc_y, label)
        c.drawRightString(summary_right_x + summary_right_w - 3 * mm, calc_y, val_str)
        calc_y -= 4.9 * mm

    taxable_lbl = 'Total Taxable Value' if include_gst else 'Subtotal Amount'
    calc_row(taxable_lbl, f"Rs. {_format_inr(breakdown['taxable_value'])}")

    if include_gst:
        calc_row('CGST @ 1.5%', f"Rs. {_format_inr(breakdown['cgst_amount'])}")
        calc_row('SGST @ 1.5%', f"Rs. {_format_inr(breakdown['sgst_amount'])}")
        calc_row('Total Tax (GST 3%)', f"Rs. {_format_inr(breakdown['total_tax'])}", bold=True, font_size=7.5)
    else:
        calc_row('GST / Tax Rate', 'Non-GST / Nil')
        calc_row('Tax Amount', 'Rs. 0.00')

    og = getattr(sale, 'old_gold_exchange', None)
    if og and getattr(og, 'status', None) == 'Completed':
        calc_row(f'Old Gold Credit (#{og.transaction_number})', f"- Rs. {_format_inr(og.final_value)}", text_color=BRAND_GOLD)

    # Promotional Coupon Discount Line Item
    if getattr(sale, 'coupon_discount', None) and sale.coupon_discount > Decimal('0.00'):
        c_code = getattr(sale, 'applied_coupon_code', '') or 'PROMO'
        calc_row(f"Coupon ({c_code})", f"- Rs. {_format_inr(sale.coupon_discount)}", bold=True, text_color=colors.HexColor('#166534'))

    if breakdown['round_off'] != Decimal('0.00'):
        sign = '+' if breakdown['round_off'] > 0 else ''
        calc_row('Round Off (+/-)', f"{sign}Rs. {abs(breakdown['round_off']):.2f}")

    # Divider line
    c.setStrokeColor(BORDER_COLOR)
    c.line(summary_right_x, calc_y + 1 * mm, summary_right_x + summary_right_w, calc_y + 1 * mm)

    # GRAND TOTAL ROW (Prominent Gold/Dark banner)
    calc_row('GRAND TOTAL', f"Rs. {_format_inr(sale.sale_price)}", bold=True, font_size=9,
             bg=BRAND_GOLD_BG if include_gst else BRAND_LIGHT_BG, text_color=BRAND_GOLD)

    # Paid / Due amounts
    paid_amt = sale.paid_amount
    due_amt = sale.due_amount
    calc_row('Amount Paid', f"Rs. {_format_inr(paid_amt)}", bold=True, text_color=colors.HexColor('#166534'))
    if due_amt > 0:
        calc_row('Balance Due', f"Rs. {_format_inr(due_amt)}", bold=True, text_color=colors.HexColor('#DC2626'))
    else:
        calc_row('Balance Due', 'Rs. 0.00 (Fully Settled)', font_size=7.5, text_color=colors.HexColor('#166534'))

    y = summary_top_y - summary_h - 6 * mm

    # =========================================================================
    # 6. SIGNATURE SECTION
    # =========================================================================
    c.setStrokeColor(BORDER_COLOR)
    c.setLineWidth(0.5)

    # Customer Sign (Left)
    c.line(left_m + 5 * mm, y - 8 * mm, left_m + 55 * mm, y - 8 * mm)
    c.setFont('Helvetica', 7.5)
    c.setFillColor(BRAND_MUTED)
    c.drawCentredString(left_m + 30 * mm, y - 11.5 * mm, "Customer's Signature")

    # Authorised Signatory (Right)
    sig_right_center = right_m - 35 * mm
    c.setFont('Helvetica-Bold', 7.5)
    c.setFillColor(BRAND_DARK)
    c.drawCentredString(sig_right_center, y - 1 * mm, f"For {company_name}")
    c.line(right_m - 60 * mm, y - 8 * mm, right_m - 5 * mm, y - 8 * mm)
    c.setFont('Helvetica', 7.5)
    c.setFillColor(BRAND_MUTED)
    c.drawCentredString(sig_right_center, y - 11.5 * mm, "Authorised Signatory")

    # =========================================================================
    # 7. FOOTER NOTE
    # =========================================================================
    c.setFont('Helvetica', 7.5)
    c.setFillColor(BRAND_MUTED)
    fn_text = footer_note if footer_note else f"Thank you for choosing {company_name}! Visit us again."
    c.drawCentredString(page_w / 2, 8 * mm, fn_text)
    c.drawCentredString(page_w / 2, 4.5 * mm, 'This is a computer-generated tax invoice.')

    c.showPage()
    c.save()
    return buffer.getvalue()
