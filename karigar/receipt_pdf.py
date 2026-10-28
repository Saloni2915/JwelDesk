"""
karigar/receipt_pdf.py
----------------------
Official Karigar Payment Voucher / Labour Receipt PDF generation using ReportLab.
Produces a professional, high-resolution A4 printable payment voucher for artisan records.
"""

import io
from decimal import Decimal

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Paragraph

from accounts.models import CompanySettings
from sales.invoice_utils import amount_to_words_inr


BRAND_DARK = colors.HexColor('#0F172A')      # Slate 900
BRAND_GOLD = colors.HexColor('#B45309')      # Amber 700 / Jewellery Gold
BRAND_GOLD_LIGHT = colors.HexColor('#D97706')# Amber 600
BRAND_GOLD_BG = colors.HexColor('#FEF3C7')   # Amber 100
BRAND_MUTED = colors.HexColor('#64748B')     # Slate 500
BRAND_LIGHT_BG = colors.HexColor('#F8FAFC')  # Slate 50
BORDER_COLOR = colors.HexColor('#CBD5E1')    # Slate 300
SUCCESS_COLOR = colors.HexColor('#047857')   # Emerald 700
SUCCESS_BG = colors.HexColor('#ECFDF5')      # Emerald 50
DANGER_COLOR = colors.HexColor('#B91C1C')    # Red 700
DANGER_BG = colors.HexColor('#FEF2F2')       # Red 50


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
    remaining = int_part[:-3]
    chunks = []
    while len(remaining) > 2:
        chunks.insert(0, remaining[-2:])
        remaining = remaining[:-2]
    if remaining:
        chunks.insert(0, remaining)
    return sign + ','.join(chunks) + ',' + last_three + dec_part


def generate_karigar_receipt_pdf(settlement) -> bytes:
    """
    Generate and return PDF bytes for a Karigar Payment Voucher / Settlement Receipt.
    """
    tenant = settlement.tenant
    company = CompanySettings.load(tenant=tenant) if tenant else None
    company_name = (company.company_name if company and company.company_name else (tenant.name if tenant else 'JewelDesk Atelier'))
    company_address = company.address if company and company.address else ''
    company_phone = company.phone if company and company.phone else ''
    company_email = company.email if company and company.email else ''
    company_gstin = company.gstin.strip().upper() if company and company.gstin else ''

    karigar = settlement.karigar
    assignments = list(settlement.assignments.all()[:12])  # display up to 12 linked assignments

    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=A4, pageCompression=0)
    page_w, page_h = A4
    styles = getSampleStyleSheet()

    def draw_p(text, x, y, width, font_name='Helvetica', font_size=8, leading=10, color=BRAND_DARK, align=0):
        if not text:
            return y
        s = ParagraphStyle(
            'item_p',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=font_size,
            leading=leading,
            textColor=color,
            alignment=align
        )
        para = Paragraph(str(text), s)
        w, h = para.wrap(width, 300)
        para.drawOn(c, x, y - h)
        return y - h

    # Outer border & margins
    margin = 12 * mm
    content_w = page_w - 2 * margin
    c.setStrokeColor(BORDER_COLOR)
    c.setLineWidth(0.8)
    c.rect(margin, margin, content_w, page_h - 2 * margin)

    # 1. Top Header Banner
    top_y = page_h - margin
    banner_h = 24 * mm
    c.setFillColor(BRAND_DARK)
    c.rect(margin, top_y - banner_h, content_w, banner_h, fill=True, stroke=False)

    # Gold accent line below banner
    c.setFillColor(BRAND_GOLD)
    c.rect(margin, top_y - banner_h - 1.2 * mm, content_w, 1.2 * mm, fill=True, stroke=False)

    # Company name and subtitle
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 15)
    c.drawString(margin + 6 * mm, top_y - 9 * mm, company_name.upper())

    c.setFont('Helvetica', 8.5)
    c.setFillColor(colors.HexColor('#E2E8F0'))
    comp_sub = []
    if company_address:
        comp_sub.append(company_address.replace('\n', ', '))
    if company_phone:
        comp_sub.append(f"Phone: {company_phone}")
    if company_gstin:
        comp_sub.append(f"GSTIN: {company_gstin}")
    c.drawString(margin + 6 * mm, top_y - 15 * mm, " • ".join(comp_sub[:2]))
    if len(comp_sub) > 2:
        c.drawString(margin + 6 * mm, top_y - 19.5 * mm, " • ".join(comp_sub[2:]))

    # Right header: Document Type
    c.setFillColor(colors.HexColor('#FCD34D'))  # Amber 300
    c.setFont('Helvetica-Bold', 11)
    c.drawRightString(page_w - margin - 6 * mm, top_y - 9 * mm, "KARIGAR PAYMENT VOUCHER")

    c.setFillColor(colors.white)
    c.setFont('Helvetica', 8)
    c.drawRightString(page_w - margin - 6 * mm, top_y - 14 * mm, "Artisan Labour Settlement Receipt")

    c.setFont('Helvetica-Bold', 9)
    c.drawRightString(page_w - margin - 6 * mm, top_y - 19 * mm, f"VOUCHER #: {settlement.settlement_number}")

    # 2. Key Metadata Strip
    strip_y = top_y - banner_h - 1.2 * mm - 13 * mm
    c.setFillColor(BRAND_LIGHT_BG)
    c.rect(margin + 0.8, strip_y, content_w - 1.6, 13 * mm, fill=True, stroke=False)
    c.setStrokeColor(BORDER_COLOR)
    c.line(margin, strip_y, page_w - margin, strip_y)

    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(BRAND_MUTED)
    c.drawString(margin + 6 * mm, strip_y + 8.5 * mm, "PAYMENT DATE")
    c.drawString(margin + 48 * mm, strip_y + 8.5 * mm, "PAYMENT METHOD")
    c.drawString(margin + 98 * mm, strip_y + 8.5 * mm, "TRANSACTION / REF #")
    c.drawString(margin + 148 * mm, strip_y + 8.5 * mm, "VOUCHER STATUS")

    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(BRAND_DARK)
    c.drawString(margin + 6 * mm, strip_y + 3.5 * mm, settlement.payment_date.strftime("%d %b %Y"))
    c.drawString(margin + 48 * mm, strip_y + 3.5 * mm, settlement.payment_method)
    c.drawString(margin + 98 * mm, strip_y + 3.5 * mm, settlement.payment_reference or 'N/A')

    # Status Pill
    if settlement.status == 'Completed':
        c.setFillColor(SUCCESS_BG)
        c.roundRect(margin + 148 * mm, strip_y + 2.5 * mm, 24 * mm, 5.5 * mm, 2 * mm, fill=True, stroke=False)
        c.setFillColor(SUCCESS_COLOR)
        c.setFont('Helvetica-Bold', 8)
        c.drawString(margin + 151 * mm, strip_y + 4.2 * mm, "PAID / SETTLED")
    else:
        c.setFillColor(DANGER_BG)
        c.roundRect(margin + 148 * mm, strip_y + 2.5 * mm, 22 * mm, 5.5 * mm, 2 * mm, fill=True, stroke=False)
        c.setFillColor(DANGER_COLOR)
        c.setFont('Helvetica-Bold', 8)
        c.drawString(margin + 151 * mm, strip_y + 4.2 * mm, "CANCELLED")

    # 3. Two-Column Details: Karigar on Left, Amount Summary on Right
    section_y = strip_y - 6 * mm
    col_w = (content_w - 6 * mm) / 2
    left_x = margin + 3 * mm
    right_x = margin + col_w + 3 * mm

    # Left Box: Artisan Info
    artisan_box_h = 36 * mm
    c.setFillColor(BRAND_LIGHT_BG)
    c.roundRect(left_x, section_y - artisan_box_h, col_w, artisan_box_h, 3 * mm, fill=True, stroke=True)

    c.setFillColor(BRAND_GOLD)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(left_x + 4 * mm, section_y - 6 * mm, "ARTISAN / KARIGAR DETAILS")

    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(left_x + 4 * mm, section_y - 12 * mm, karigar.name.upper())

    c.setFont('Helvetica', 8)
    c.setFillColor(BRAND_MUTED)
    c.drawString(left_x + 4 * mm, section_y - 16.5 * mm, f"Artisan Code: {karigar.karigar_code}   •   Phone: {karigar.mobile}")

    sub_y = section_y - 21 * mm
    if karigar.specialization:
        c.drawString(left_x + 4 * mm, sub_y, f"Specialization: {karigar.specialization}")
        sub_y -= 4 * mm

    # Bank / Payout details
    bank_info = []
    if karigar.bank_name:
        bank_info.append(f"Bank: {karigar.bank_name}")
    if karigar.account_number:
        bank_info.append(f"A/C: {karigar.account_number}")
    if karigar.ifsc_code:
        bank_info.append(f"IFSC: {karigar.ifsc_code}")
    if karigar.upi_id:
        bank_info.append(f"UPI: {karigar.upi_id}")

    if bank_info:
        c.setFont('Helvetica-Bold', 7.5)
        c.setFillColor(BRAND_DARK)
        c.drawString(left_x + 4 * mm, sub_y, " • ".join(bank_info[:2]))
        if len(bank_info) > 2:
            c.drawString(left_x + 4 * mm, sub_y - 3.8 * mm, " • ".join(bank_info[2:]))
    elif karigar.address:
        draw_p(f"Address: {karigar.address}", left_x + 4 * mm, sub_y, col_w - 8 * mm, font_size=7.5, leading=9)

    # Right Box: Payment Summary (Prominent Amount)
    c.setFillColor(BRAND_GOLD_BG)
    c.setStrokeColor(BRAND_GOLD)
    c.roundRect(right_x, section_y - artisan_box_h, col_w, artisan_box_h, 3 * mm, fill=True, stroke=True)

    c.setFillColor(BRAND_GOLD)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(right_x + 5 * mm, section_y - 6 * mm, "TOTAL AMOUNT PAID (LABOUR CHARGES)")

    # Large Amount
    c.setFont('Helvetica-Bold', 20)
    c.setFillColor(BRAND_DARK)
    amt_str = f"INR {_format_inr(settlement.amount)}"
    c.drawString(right_x + 5 * mm, section_y - 15 * mm, amt_str)

    # Amount in Words
    words = amount_to_words_inr(settlement.amount)
    c.setFont('Helvetica-Bold', 7.5)
    c.setFillColor(BRAND_GOLD)
    c.drawString(right_x + 5 * mm, section_y - 20 * mm, "AMOUNT IN WORDS:")
    draw_p(words, right_x + 5 * mm, section_y - 23 * mm, col_w - 10 * mm, font_name='Helvetica-Oblique', font_size=8, leading=10, color=BRAND_DARK)

    # Processed By
    proc_name = settlement.processed_by.get_full_name() if settlement.processed_by and settlement.processed_by.get_full_name() else (settlement.processed_by.username if settlement.processed_by else 'Store Authorized Executive')
    c.setFont('Helvetica', 7.5)
    c.setFillColor(BRAND_MUTED)
    c.drawString(right_x + 5 * mm, section_y - 32 * mm, f"Disbursed By: {proc_name}  •  {settlement.created_at.strftime('%d %b %Y, %H:%M')}")

    # 4. Linked Job Assignments Table
    tbl_top_y = section_y - artisan_box_h - 7 * mm

    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 10)
    c.drawString(margin + 3 * mm, tbl_top_y, "LINKED WORK ASSIGNMENTS / JOB CARDS")

    tbl_y = tbl_top_y - 3 * mm
    tbl_h = 7 * mm

    # Table Header
    c.setFillColor(BRAND_DARK)
    c.rect(margin + 3 * mm, tbl_y - tbl_h, content_w - 6 * mm, tbl_h, fill=True, stroke=False)

    col_widths = [26 * mm, 38 * mm, 24 * mm, 26 * mm, 26 * mm, 24 * mm]
    col_x = [
        margin + 5 * mm,
        margin + 33 * mm,
        margin + 73 * mm,
        margin + 99 * mm,
        margin + 127 * mm,
        margin + 155 * mm,
    ]

    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 7.5)
    c.drawString(col_x[0], tbl_y - 4.8 * mm, "JOB CARD #")
    c.drawString(col_x[1], tbl_y - 4.8 * mm, "WORK DESCRIPTION")
    c.drawString(col_x[2], tbl_y - 4.8 * mm, "METAL ISSUED")
    c.drawString(col_x[3], tbl_y - 4.8 * mm, "TOTAL CHARGES")
    c.drawString(col_x[4], tbl_y - 4.8 * mm, "PAID IN VOUCHER")
    c.drawString(col_x[5], tbl_y - 4.8 * mm, "JOB STATUS")

    row_y = tbl_y - tbl_h

    if assignments:
        for i, asg in enumerate(assignments):
            row_h = 7 * mm
            bg_color = BRAND_LIGHT_BG if i % 2 == 1 else colors.white
            c.setFillColor(bg_color)
            c.rect(margin + 3 * mm, row_y - row_h, content_w - 6 * mm, row_h, fill=True, stroke=False)
            c.setStrokeColor(BORDER_COLOR)
            c.line(margin + 3 * mm, row_y - row_h, page_w - margin - 3 * mm, row_y - row_h)

            c.setFillColor(BRAND_GOLD)
            c.setFont('Helvetica-Bold', 7.5)
            c.drawString(col_x[0], row_y - 5 * mm, asg.assignment_number)

            c.setFillColor(BRAND_DARK)
            c.setFont('Helvetica', 7.5)
            desc = asg.work_type
            if asg.metal_type and asg.purity:
                desc += f" ({asg.metal_type} {asg.purity})"
            c.drawString(col_x[1], row_y - 5 * mm, desc[:26])

            c.drawString(col_x[2], row_y - 5 * mm, f"{asg.net_weight_issued:.3f} g")
            c.drawString(col_x[3], row_y - 5 * mm, f"INR {_format_inr(asg.total_charge)}")

            c.setFont('Helvetica-Bold', 7.5)
            c.setFillColor(SUCCESS_COLOR)
            c.drawString(col_x[4], row_y - 5 * mm, f"INR {_format_inr(asg.paid_amount)}")

            c.setFont('Helvetica', 7.5)
            c.setFillColor(BRAND_MUTED)
            c.drawString(col_x[5], row_y - 5 * mm, asg.payment_status or asg.status)

            row_y -= row_h
    else:
        # No specific linked assignments - general settlement
        row_h = 10 * mm
        c.setFillColor(BRAND_LIGHT_BG)
        c.rect(margin + 3 * mm, row_y - row_h, content_w - 6 * mm, row_h, fill=True, stroke=False)
        c.setStrokeColor(BORDER_COLOR)
        c.line(margin + 3 * mm, row_y - row_h, page_w - margin - 3 * mm, row_y - row_h)
        c.setFillColor(BRAND_MUTED)
        c.setFont('Helvetica-Oblique', 8)
        c.drawString(margin + 8 * mm, row_y - 6.5 * mm, "General labour payment / Advance on running craftsmanship ledger (No single job attached).")
        row_y -= row_h

    # 5. Notes / Terms Section
    notes_y = row_y - 5 * mm
    if settlement.notes:
        c.setFillColor(BRAND_LIGHT_BG)
        c.setStrokeColor(BORDER_COLOR)
        c.roundRect(margin + 3 * mm, notes_y - 14 * mm, content_w - 6 * mm, 14 * mm, 2 * mm, fill=True, stroke=True)
        c.setFillColor(BRAND_GOLD)
        c.setFont('Helvetica-Bold', 7.5)
        c.drawString(margin + 6 * mm, notes_y - 4.5 * mm, "PAYMENT REMARKS / AUDIT NOTES:")
        draw_p(settlement.notes, margin + 6 * mm, notes_y - 7 * mm, content_w - 14 * mm, font_size=7.5, leading=9, color=BRAND_DARK)
        notes_y -= 16 * mm

    # Statutory Declaration
    c.setFillColor(BRAND_MUTED)
    c.setFont('Helvetica', 6.8)
    legal_text = (
        "Declaration: This official voucher certifies that the aforementioned payment has been fully settled and disbursed to the artisan. "
        "Material accountability and workmanship specifications are reconciled in accordance with workshop standards. "
        "Computer generated receipt — valid without additional stamp."
    )
    draw_p(legal_text, margin + 3 * mm, notes_y - 2 * mm, content_w - 6 * mm, font_size=6.8, leading=8.5, color=BRAND_MUTED)

    # 6. Dual Signature Blocks at bottom
    sig_y = margin + 14 * mm
    c.setStrokeColor(BORDER_COLOR)
    c.setLineWidth(0.6)

    # Authorized Store Signatory
    c.line(margin + 12 * mm, sig_y + 12 * mm, margin + 70 * mm, sig_y + 12 * mm)
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(BRAND_DARK)
    c.drawCentredString(margin + 41 * mm, sig_y + 8 * mm, "FOR " + company_name.upper())
    c.setFont('Helvetica', 7)
    c.setFillColor(BRAND_MUTED)
    c.drawCentredString(margin + 41 * mm, sig_y + 4 * mm, "Authorized Signatory (Workshop Mgr / Cashier)")

    # Artisan / Karigar Signature
    c.line(page_w - margin - 70 * mm, sig_y + 12 * mm, page_w - margin - 12 * mm, sig_y + 12 * mm)
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(BRAND_DARK)
    c.drawCentredString(page_w - margin - 41 * mm, sig_y + 8 * mm, karigar.name.upper())
    c.setFont('Helvetica', 7)
    c.setFillColor(BRAND_MUTED)
    c.drawCentredString(page_w - margin - 41 * mm, sig_y + 4 * mm, "Artisan Signature (Payment Received Acknowledgment)")

    # Bottom Footer Line
    c.setFont('Helvetica', 6.5)
    c.setFillColor(BRAND_MUTED)
    footer_text = f"JewelDesk Atelier Suite  •  Voucher #{settlement.settlement_number}  •  Generated on {timezone.now().strftime('%d %b %Y, %H:%M')}"
    c.drawCentredString(page_w / 2.0, margin + 2.5 * mm, footer_text)

    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
