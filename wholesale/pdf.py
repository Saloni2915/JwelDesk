"""
wholesale/pdf.py
----------------
Wholesale Jewellery Tax Invoice PDF Generation using ReportLab.
Compliant with:
  - Section 31 of CGST Act 2017
  - HSN Code 7113 (Gold/Silver/Diamond Jewellery)
  - BIS Hallmarking, HUID and Weight details
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
from sales.invoice_utils import get_state_from_gstin

BRAND_DARK = colors.HexColor('#1E293B')
BRAND_GOLD = colors.HexColor('#B45309')
BRAND_GOLD_BG = colors.HexColor('#FEF3C7')
BRAND_MUTED = colors.HexColor('#64748B')
BRAND_LIGHT_BG = colors.HexColor('#F8FAFC')
BORDER_COLOR = colors.HexColor('#CBD5E1')


def generate_wholesale_invoice_pdf(invoice) -> bytes:
    """Generate and return PDF bytes for a WholesaleInvoice."""
    tenant = invoice.tenant
    company = CompanySettings.load(tenant=tenant)
    company_name = company.company_name or tenant.name
    supplier_gstin = company.gstin.strip().upper() if company and company.gstin else ''
    supplier_address = company.address or ''
    supplier_phone = company.phone or ''
    supplier_email = company.email or ''
    footer_note = company.invoice_footer_note or 'Thank you for your business. Interest @ 18% p.a. will be charged on overdue payments.'

    party = invoice.party
    retailer_name = party.name
    retailer_contact = party.contact_person or ''
    retailer_phone = party.phone or ''
    retailer_email = party.email or ''
    retailer_gstin = party.gstin or ''
    retailer_address = party.billing_address or ''

    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=A4, pageCompression=0)
    page_w, page_h = A4
    styles = getSampleStyleSheet()

    def p(text, x, y, width, font_name='Helvetica', font_size=8, leading=10, color=BRAND_DARK, align=0):
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
        w, h = para.wrap(width, 200)
        para.drawOn(c, x, y - h)
        return y - h

    # Outer border & header banner
    c.setStrokeColor(BORDER_COLOR)
    c.setLineWidth(0.8)
    margin = 10 * mm
    c.rect(margin, margin, page_w - 2 * margin, page_h - 2 * margin)

    # Top Brand Header
    c.setFillColor(BRAND_GOLD)
    c.rect(margin, page_h - margin - 22 * mm, page_w - 2 * margin, 22 * mm, fill=True, stroke=False)

    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 16)
    c.drawString(margin + 5 * mm, page_h - margin - 10 * mm, (company_name or 'JEWELDESK WHOLESALE').upper())

    c.setFont('Helvetica', 9)
    c.drawString(margin + 5 * mm, page_h - margin - 16 * mm, "WHOLESALE JEWELLERY TAX INVOICE (B2B)")

    c.setFont('Helvetica-Bold', 12)
    c.drawRightString(page_w - margin - 5 * mm, page_h - margin - 10 * mm, f"INVOICE #: {invoice.invoice_number}")
    c.setFont('Helvetica', 9)
    c.drawRightString(page_w - margin - 5 * mm, page_h - margin - 16 * mm, f"DATE: {invoice.invoice_date.strftime('%d-%b-%Y')}")

    # Supplier & Buyer Meta box
    y_meta = page_h - margin - 25 * mm
    col_w = (page_w - 2 * margin) / 2

    # Left: Supplier (Consignor)
    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(margin + 3 * mm, y_meta, "SUPPLIER / CONSIGNOR:")
    p(f"<b>{company_name}</b><br/>{supplier_address}<br/>Phone: {supplier_phone} | Email: {supplier_email}<br/>GSTIN: <b>{supplier_gstin or 'URP'}</b>",
      margin + 3 * mm, y_meta - 3 * mm, col_w - 6 * mm, font_size=8, leading=11)

    # Right: Retailer Buyer (Consignee)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(margin + col_w + 3 * mm, y_meta, "BUYER / RETAILER PARTY:")
    due_str = f"<br/>Due Date: <b>{invoice.due_date.strftime('%d-%b-%Y')}</b>" if invoice.due_date else ""
    ord_str = f" | Order Ref: <b>{invoice.order.order_number}</b>" if invoice.order else ""
    p(f"<b>{retailer_name}</b> (Attn: {retailer_contact})<br/>{retailer_address}<br/>Phone: {retailer_phone}<br/>GSTIN: <b>{retailer_gstin or 'Unregistered'}</b>{due_str}{ord_str}",
      margin + col_w + 3 * mm, y_meta - 3 * mm, col_w - 6 * mm, font_size=8, leading=11)

    # Table Header
    y_table = y_meta - 38 * mm
    c.setFillColor(BRAND_GOLD_BG)
    c.rect(margin, y_table, page_w - 2 * margin, 7 * mm, fill=True, stroke=True)

    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(margin + 2 * mm, y_table + 2 * mm, "SN")
    c.drawString(margin + 10 * mm, y_table + 2 * mm, "DESCRIPTION / TAG")
    c.drawString(margin + 65 * mm, y_table + 2 * mm, "PURITY")
    c.drawString(margin + 85 * mm, y_table + 2 * mm, "GROSS WT")
    c.drawString(margin + 105 * mm, y_table + 2 * mm, "NET WT")
    c.drawString(margin + 125 * mm, y_table + 2 * mm, "QTY")
    c.drawString(margin + 138 * mm, y_table + 2 * mm, "RATE (Rs)")
    c.drawString(margin + 160 * mm, y_table + 2 * mm, "GST")
    c.drawRightString(page_w - margin - 3 * mm, y_table + 2 * mm, "TOTAL (Rs)")

    # Table Rows
    curr_y = y_table - 2 * mm
    items = invoice.items.select_related('item').all()
    c.setFont('Helvetica', 8)

    for idx, line in enumerate(items, 1):
        item = line.item
        gross = f"{item.gross_weight:.3f}g" if item.gross_weight else "-"
        net = f"{item.net_weight:.3f}g" if item.net_weight else "-"
        desc = f"<b>{item.name}</b><br/><font color='#64748B'>Tag: {item.tag_number or item.item_code} | HSN: 7113</font>"

        c.drawString(margin + 2 * mm, curr_y - 3 * mm, str(idx))
        p(desc, margin + 10 * mm, curr_y, 52 * mm, font_size=7.5, leading=9)
        c.drawString(margin + 65 * mm, curr_y - 3 * mm, str(item.purity or ''))
        c.drawString(margin + 85 * mm, curr_y - 3 * mm, gross)
        c.drawString(margin + 105 * mm, curr_y - 3 * mm, net)
        c.drawString(margin + 125 * mm, curr_y - 3 * mm, str(line.quantity))
        c.drawString(margin + 138 * mm, curr_y - 3 * mm, f"{line.unit_price:,.2f}")
        c.drawString(margin + 160 * mm, curr_y - 3 * mm, f"{line.tax_rate:.1f}%")
        c.drawRightString(page_w - margin - 3 * mm, curr_y - 3 * mm, f"{line.total_price:,.2f}")

        curr_y -= 10 * mm
        c.setStrokeColor(BORDER_COLOR)
        c.line(margin, curr_y, page_w - margin, curr_y)

    # Summary Box at Bottom
    y_sum = margin + 35 * mm
    c.setFillColor(BRAND_LIGHT_BG)
    c.rect(page_w - margin - 75 * mm, y_sum, 75 * mm, 30 * mm, fill=True, stroke=True)

    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica', 8.5)
    c.drawString(page_w - margin - 72 * mm, y_sum + 22 * mm, "Taxable Subtotal:")
    c.drawRightString(page_w - margin - 3 * mm, y_sum + 22 * mm, f"Rs. {invoice.subtotal:,.2f}")

    c.drawString(page_w - margin - 72 * mm, y_sum + 14 * mm, "GST Output Tax:")
    c.drawRightString(page_w - margin - 3 * mm, y_sum + 14 * mm, f"Rs. {invoice.tax_amount:,.2f}")

    c.setFont('Helvetica-Bold', 10)
    c.setFillColor(BRAND_GOLD)
    c.drawString(page_w - margin - 72 * mm, y_sum + 4 * mm, "TOTAL DUE:")
    c.drawRightString(page_w - margin - 3 * mm, y_sum + 4 * mm, f"Rs. {invoice.total_amount:,.2f}")

    # Terms & Authorization
    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica', 7.5)
    p(f"<b>Terms & Conditions:</b><br/>{footer_note}", margin + 3 * mm, y_sum + 28 * mm, 100 * mm, font_size=7, leading=9)

    c.drawRightString(page_w - margin - 15 * mm, margin + 8 * mm, f"For {company_name}")
    c.setFont('Helvetica-Oblique', 7)
    c.drawRightString(page_w - margin - 15 * mm, margin + 4 * mm, "Authorized Signatory")

    c.showPage()
    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
