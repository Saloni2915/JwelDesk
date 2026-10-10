"""
PDF invoice generation for sales, built with ReportLab.

All financial values come from the stored Sale record — nothing is
recalculated or invented here. Company details are read from the
CompanySettings singleton (accounts app) with safe blank fallbacks.
"""
import io

from django.core.files.storage import default_storage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Image as RLImage, Paragraph
from reportlab.lib.units import mm

from accounts.models import CompanySettings

BRAND_GOLD = colors.HexColor('#C9A227')
BRAND_DARK = colors.HexColor('#212529')
BRAND_MUTED = colors.HexColor('#6C757D')


def _local_date(dt):
    from django.utils import timezone
    return timezone.localtime(dt).strftime('%d %b %Y')


def build_invoice_pdf(sale):
    """Return the PDF bytes for the given Sale."""
    company = CompanySettings.objects.first()
    company_name = (company.company_name if company and company.company_name
                    else 'JewelDesk')
    gstin = company.gstin if company else ''
    address = (company.address if company else '') or ''
    phone = company.phone if company else ''
    email = company.email if company else ''
    footer_note = (company.invoice_footer_note if company else '') or ''

    item = sale.jewellery_item
    customer = sale.customer

    buffer = io.BytesIO()
    page_w, page_h = A4
    c = pdf_canvas.Canvas(buffer, pagesize=A4, pageCompression=0)
    base = getSampleStyleSheet()

    def wrapped(text, x, y, width):
        """Draw wrapped text top-down starting at (x, y); return final y."""
        if not text:
            return y
        para = ParagraphStyle('wrap', parent=base['Normal'], leading=13)
        p = Paragraph(str(text), para)
        _w, h = p.wrap(width, page_h)
        p.drawOn(c, x, y - h)
        return y - h

    # ---- Header band -------------------------------------------------
    c.setFillColor(BRAND_DARK)
    c.rect(0, page_h - 30 * mm, page_w, 30 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 20)
    c.drawString(20 * mm, page_h - 16 * mm, company_name)
    c.setFont('Helvetica', 9)
    c.setFillColor(colors.HexColor('#DEE2E6'))
    info_bits = [b for b in (address.replace('\n', ', '), phone, email) if b]
    if info_bits:
        c.drawString(20 * mm, page_h - 22 * mm, ' | '.join(info_bits)[:110])
    if gstin:
        c.setFont('Helvetica-Bold', 9)
        c.setFillColor(BRAND_GOLD)
        c.drawRightString(page_w - 20 * mm, page_h - 16 * mm,
                          f'GSTIN: {gstin.upper()}')

    # Optional logo (drawn over the dark band, right side).
    if company and company.logo:
        try:
            if hasattr(company, 'ensure_logo_file'):
                company.ensure_logo_file()
        except Exception:
            pass
        if default_storage.exists(company.logo.name):
            try:
                with company.logo.open('rb') as fh:
                    img = RLImage(fh, width=32 * mm, height=10 * mm, kind='proportional')
                    img.drawOn(c, page_w - 45 * mm, page_h - 24 * mm)
            except Exception:
                pass  # A broken/unreadable logo must not block the invoice.

    # ---- Invoice meta ------------------------------------------------
    y = page_h - 42 * mm
    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 14)
    c.drawString(20 * mm, y, 'TAX INVOICE')
    c.setFont('Helvetica', 10)
    y -= 8 * mm
    c.drawString(20 * mm, y, f'Invoice No.: INV-{sale.pk:05d}')
    c.drawRightString(page_w - 20 * mm, y, f'Date: {_local_date(sale.sale_date)}')
    y -= 6 * mm
    c.drawString(20 * mm, y, f'Payment Method: {sale.payment_method}')

    # ---- Customer block ----------------------------------------------
    y -= 12 * mm
    c.setFont('Helvetica-Bold', 11)
    c.drawString(20 * mm, y, 'Billed To')
    c.setFont('Helvetica', 10)
    y -= 6 * mm
    c.drawString(20 * mm, y, customer.name)
    y -= 5 * mm
    for label, value in (('Mobile: ', customer.mobile),
                         ('Email: ', customer.email)):
        if value:
            c.drawString(20 * mm, y, f'{label}{value}')
            y -= 5 * mm
    if customer.address:
        y = wrapped(customer.address, 20 * mm, y, 80 * mm) - 2 * mm

    # ---- Line items table ---------------------------------------------
    y -= 4 * mm
    col_x = [20 * mm, 105 * mm, 128 * mm, 145 * mm, 190 * mm]
    headers = ['Item', 'Code', 'Qty', 'Rate', 'Amount']
    c.setFillColor(BRAND_GOLD)
    c.rect(18 * mm, y - 2 * mm, page_w - 38 * mm, 8 * mm, stroke=0, fill=1)
    c.setFillColor(BRAND_DARK)
    c.setFont('Helvetica-Bold', 10)
    for x, h in zip(col_x, headers):
        c.drawString(x, y, h)
    y -= 10 * mm
    c.setFont('Helvetica', 10)
    c.setFillColor(BRAND_DARK)
    c.drawString(col_x[0], y, item.name[:45])
    c.drawString(col_x[1], y, (item.item_code or '')[:18])
    c.drawString(col_x[2], y, '1')
    c.drawString(col_x[3], y, f'{sale.sale_price:,.2f}')
    c.drawRightString(col_x[4], y, f'{sale.sale_price:,.2f}')
    y -= 6 * mm
    extra_details = []
    if item.tag_number and item.tag_number != item.item_code:
        extra_details.append(f'Tag: {item.tag_number}')
    if item.design_code and item.design_code != item.item_code:
        extra_details.append(f'Design: {item.design_code}')
    if item.huid:
        extra_details.append(f'HUID: {item.huid}')
    if extra_details:
        c.setFont('Helvetica', 8)
        c.setFillColor(BRAND_MUTED)
        c.drawString(col_x[0], y, ' | '.join(extra_details))
        c.setFont('Helvetica', 10)
        c.setFillColor(BRAND_DARK)
        y -= 6 * mm

    # ---- Totals --------------------------------------------------------
    c.setStrokeColor(BRAND_MUTED)
    c.setLineWidth(0.5)
    c.line(120 * mm, y, page_w - 20 * mm, y)
    y -= 7 * mm
    c.setFont('Helvetica', 10)
    c.drawString(130 * mm, y, 'Subtotal')
    c.drawRightString(col_x[4], y, f'Rs. {sale.sale_price:,.2f}')
    y -= 6 * mm
    c.drawString(130 * mm, y, 'Making Charges / Taxes')
    c.drawRightString(col_x[4], y, 'Included')
    y -= 8 * mm
    c.setFont('Helvetica-Bold', 12)
    c.drawString(130 * mm, y, 'Grand Total')
    c.drawRightString(col_x[4], y, f'Rs. {sale.sale_price:,.2f}')

    # Old gold exchange credit if linked to an exchange transaction
    og = getattr(sale, 'old_gold_exchange', None)
    if og and og.status == 'Completed':
        y -= 6 * mm
        c.setFont('Helvetica', 10)
        c.setFillColor(BRAND_GOLD)
        c.drawString(130 * mm, y, f'Old Gold ({og.transaction_number})')
        c.drawRightString(col_x[4], y, f'- Rs. {og.final_value:,.2f}')
        c.setFillColor(BRAND_DARK)

    # Paid / Due / Status (calculated from recorded payments)
    paid = sale.paid_amount
    due = sale.due_amount
    status = sale.payment_status
    y -= 6 * mm
    c.setFont('Helvetica', 10)
    c.drawString(130 * mm, y, 'Paid')
    c.drawRightString(col_x[4], y, f'Rs. {paid:,.2f}')
    y -= 6 * mm
    c.drawString(130 * mm, y, 'Due')
    c.drawRightString(col_x[4], y, f'Rs. {due:,.2f}')
    y -= 7 * mm
    c.setFont('Helvetica-Bold', 10)
    c.drawString(130 * mm, y, 'Status')
    c.drawRightString(col_x[4], y, status)
    c.setFont('Helvetica', 10)

    # ---- Payment / footer ----------------------------------------------
    c.setFont('Helvetica', 10)
    c.drawString(20 * mm, y, f'Payment: {sale.payment_method}')
    c.setFont('Helvetica', 8)
    c.setFillColor(BRAND_MUTED)
    if footer_note:
        c.drawCentredString(page_w / 2, 18 * mm, footer_note)
    c.drawCentredString(
        page_w / 2, 12 * mm,
        f'{company_name} - Thank you for your business!')

    c.showPage()
    c.save()
    return buffer.getvalue()
