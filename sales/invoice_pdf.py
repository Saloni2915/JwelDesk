"""
PDF invoice generation for sales, built with ReportLab.

Renders authentic Indian Jewellery Showroom Tax Invoices (and Non-GST Retail Cash Memos)
compliant with:
- Section 31 of CGST Act 2017.
- HSN Code 7113 (Gold/Silver Jewellery).
- BIS Hallmarking & HUID identification.
- Accurate right-aligned numerical weights and currency amounts.
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

    # Margins: 12mm left/right
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
    c.drawRightString(right_box_x + box_w - 2.5 * mm, top_box_y - 20.5 * mm, sale.payment_method)

    y = top_box_y - box_h - 4 * mm

    # =========================================================================
    # 4. JEWELLERY LINE ITEMS TABLE
    # Columns:
    # 1. Sr. (center)            width 8mm   x: 12..20
    # 2. Description (left)      width 50mm  x: 20..70
    # 3. HSN (center)            width 13mm  x: 70..83
    # 4. Purity (center)         width 15mm  x: 83..98
    # 5. Gross Wt (right)        width 15mm  x: 98..113
    # 6. Less Wt (right)         width 13mm  x: 113..126
    # 7. Net Wt (right)          width 15mm  x: 126..141
    # 8. Rate / g (right)        width 16mm  x: 141..157
    # 9. Making (right)          width 14mm  x: 157..171
    # 10. Taxable Amt (right)    width 25mm  x: 171..196 (right_m is ~198mm)
    # =========================================================================
    col_bounds = [
        (left_m, left_m + 8 * mm),            # 0: Sr
        (left_m + 8 * mm, left_m + 56 * mm),   # 1: Description
        (left_m + 56 * mm, left_m + 70 * mm),  # 2: HSN
        (left_m + 70 * mm, left_m + 86 * mm),  # 3: Purity
        (left_m + 86 * mm, left_m + 102 * mm), # 4: Gross Wt
        (left_m + 102 * mm, left_m + 116 * mm),# 5: Less Wt
        (left_m + 116 * mm, left_m + 132 * mm),# 6: Net Wt
        (left_m + 132 * mm, left_m + 150 * mm),# 7: Rate/g
        (left_m + 150 * mm, left_m + 165 * mm),# 8: Making
        (left_m + 165 * mm, right_m),          # 9: Taxable / Total
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

    # Table Item Data Row
    row_h = 16 * mm
    c.setFillColor(colors.white)
    c.setStrokeColor(BORDER_COLOR)
    c.setLineWidth(0.5)
    c.rect(left_m, y - row_h, content_w, row_h, stroke=1, fill=1)

    # Vertical separators
    for b in col_bounds[:-1]:
        c.line(b[1], y, b[1], y - row_h)

    # 1. Sr
    c.setFont('Helvetica', 8.5)
    c.setFillColor(BRAND_DARK)
    c.drawCentredString((col_bounds[0][0] + col_bounds[0][1]) / 2, y - 5.5 * mm, '1')

    # 2. Description & HUID / Tag
    desc_x = col_bounds[1][0] + 2 * mm
    c.setFont('Helvetica-Bold', 8.5)
    c.drawString(desc_x, y - 4.5 * mm, item.name[:30])
    c.setFont('Helvetica', 7.5)
    c.setFillColor(BRAND_MUTED)
    cat_name = getattr(getattr(item, 'category', None), 'name', '')
    c.drawString(desc_x, y - 8 * mm, f'Category: {cat_name}' if cat_name else '')
    tag_str = item.tag_number or item.item_code or ''
    huid_str = item.huid or ''
    specs = []
    if tag_str:
        specs.append(f'Tag: {tag_str}')
    if huid_str:
        specs.append(f'HUID: {huid_str}')
    c.drawString(desc_x, y - 11.5 * mm, ' | '.join(specs)[:36])
    if item.design_code and item.design_code != item.item_code:
        c.drawString(desc_x, y - 14.5 * mm, f'Design: {item.design_code[:20]}')

    # 3. HSN
    c.setFont('Helvetica', 8)
    c.setFillColor(BRAND_DARK)
    c.drawCentredString((col_bounds[2][0] + col_bounds[2][1]) / 2, y - 5.5 * mm, breakdown['hsn_code'])

    # 4. Purity
    purity_label = item.purity or '22K'
    c.setFont('Helvetica-Bold', 8)
    c.drawCentredString((col_bounds[3][0] + col_bounds[3][1]) / 2, y - 5.5 * mm, purity_label)

    # 5. Gross Wt
    c.setFont('Helvetica', 8)
    c.drawRightString(col_bounds[4][1] - 1.5 * mm, y - 5.5 * mm, f"{breakdown['gross_weight']:,.3f}g")

    # 6. Less Wt
    c.drawRightString(col_bounds[5][1] - 1.5 * mm, y - 5.5 * mm, f"{breakdown['stone_weight']:,.3f}g")

    # 7. Net Wt (Bold)
    c.setFont('Helvetica-Bold', 8)
    c.drawRightString(col_bounds[6][1] - 1.5 * mm, y - 5.5 * mm, f"{breakdown['net_weight']:,.3f}g")

    # 8. Rate / g
    c.setFont('Helvetica', 8)
    rate_val = f"Rs.{breakdown['rate_per_gram']:,.2f}" if breakdown['rate_per_gram'] > 0 else '—'
    c.drawRightString(col_bounds[7][1] - 1.5 * mm, y - 5.5 * mm, rate_val)

    # 9. Making
    mk_val = f"Rs.{breakdown['making_charges']:,.2f}" if breakdown['making_charges'] > 0 else 'Included'
    c.drawRightString(col_bounds[8][1] - 1.5 * mm, y - 5.5 * mm, mk_val)

    # 10. Taxable Amt
    c.setFont('Helvetica-Bold', 8.5)
    c.drawRightString(col_bounds[9][1] - 2 * mm, y - 5.5 * mm, f"Rs.{breakdown['taxable_value']:,.2f}")

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
    c.drawString(left_m + 30 * mm, y - 3.5 * mm, wt_text)
    y -= (strip_h + 3.5 * mm)

    # =========================================================================
    # 5. FINANCIAL SETTLEMENT & TAX CALCULATION (2-Column Box)
    # Left: Amount in words, Payment Mode, Terms & Conditions
    # Right: Taxable, CGST, SGST, Round off, Grand Total, Paid, Balance
    # =========================================================================
    summary_left_w = content_w * 0.54
    summary_right_w = content_w - summary_left_w - 4 * mm
    summary_right_x = left_m + summary_left_w + 4 * mm
    summary_h = 56 * mm
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
            summary_left_w - 5 * mm, font_name='Helvetica-Bold', font_size=7.5, leading=9, color=BRAND_GOLD)

    # Payment info
    c.setFont('Helvetica', 7.5)
    c.setFillColor(BRAND_DARK)
    c.drawString(left_m + 2.5 * mm, summary_top_y - 16 * mm,
                 f"Payment Mode: {sale.payment_method}    |    Status: {sale.payment_status}")

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

    calc_y = summary_top_y - 5 * mm
    def calc_row(label, val_str, bold=False, font_size=8, bg=None, text_color=BRAND_DARK):
        nonlocal calc_y
        if bg:
            c.setFillColor(bg)
            c.rect(summary_right_x, calc_y - 2 * mm, summary_right_w, 6 * mm, stroke=0, fill=1)
        c.setFillColor(text_color)
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', font_size)
        c.drawString(summary_right_x + 3 * mm, calc_y, label)
        c.drawRightString(summary_right_x + summary_right_w - 3 * mm, calc_y, val_str)
        calc_y -= 5.5 * mm

    taxable_lbl = 'Total Taxable Value' if include_gst else 'Subtotal Amount'
    calc_row(taxable_lbl, f"Rs. {breakdown['taxable_value']:,.2f}")

    if include_gst:
        calc_row('CGST @ 1.5%', f"Rs. {breakdown['cgst_amount']:,.2f}")
        calc_row('SGST @ 1.5%', f"Rs. {breakdown['sgst_amount']:,.2f}")
        calc_row('Total Tax (GST 3%)', f"Rs. {breakdown['total_tax']:,.2f}", bold=True, font_size=7.5)
    else:
        calc_row('GST / Tax Rate', 'Non-GST / Nil')
        calc_row('Tax Amount', 'Rs. 0.00')

    og = getattr(sale, 'old_gold_exchange', None)
    if og and getattr(og, 'status', None) == 'Completed':
        calc_row(f'Old Gold Credit (#{og.transaction_number})', f"- Rs. {og.final_value:,.2f}", text_color=BRAND_GOLD)

    if breakdown['round_off'] != Decimal('0.00'):
        sign = '+' if breakdown['round_off'] > 0 else ''
        calc_row('Round Off (+/-)', f"{sign}Rs. {breakdown['round_off']:,.2f}")

    # Divider line
    c.setStrokeColor(BORDER_COLOR)
    c.line(summary_right_x, calc_y + 1 * mm, summary_right_x + summary_right_w, calc_y + 1 * mm)

    # GRAND TOTAL ROW (Prominent Gold/Dark banner)
    calc_row('GRAND TOTAL', f"Rs. {sale.sale_price:,.2f}", bold=True, font_size=9.5,
             bg=BRAND_GOLD_BG if include_gst else BRAND_LIGHT_BG, text_color=BRAND_GOLD)

    # Paid / Due amounts
    paid_amt = sale.paid_amount
    due_amt = sale.due_amount
    calc_row('Amount Paid', f"Rs. {paid_amt:,.2f}", bold=True, text_color=colors.HexColor('#166534'))
    if due_amt > 0:
        calc_row('Balance Due', f"Rs. {due_amt:,.2f}", bold=True, text_color=colors.HexColor('#DC2626'))
    else:
        calc_row('Balance Due', 'Rs. 0.00 (Fully Settled)', font_size=7.5)

    y = summary_top_y - summary_h - 6 * mm

    # =========================================================================
    # 6. SIGNATURE SECTION
    # =========================================================================
    sig_h = 16 * mm
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
