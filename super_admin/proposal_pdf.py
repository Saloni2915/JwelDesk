"""
super_admin/proposal_pdf.py
----------------------------
High-resolution, luxury PDF proposal and quotation generation for JewelDesk.
Built with ReportLab Platypus. Produces authentic, print-ready B2B SaaS
commercial proposals for jewellery showroom owners.
"""

import io
from decimal import Decimal
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether,
)

# Brand Color Palette
PRIMARY_GOLD   = colors.HexColor('#B48516')  # Warm luxury gold
DARK_SLATE     = colors.HexColor('#0F172A')  # Slate 900
DARK_CHARCOAL  = colors.HexColor('#1E293B')  # Slate 800
LIGHT_BG       = colors.HexColor('#F8FAFC')  # Slate 50
GOLD_SUBTLE_BG = colors.HexColor('#FEF9C3')  # Yellow 100
BORDER_COLOR   = colors.HexColor('#CBD5E1')  # Slate 300
BORDER_LIGHT   = colors.HexColor('#E2E8F0')  # Slate 200
TEXT_MUTED     = colors.HexColor('#64748B')  # Slate 500
ACCENT_GREEN   = colors.HexColor('#059669')  # Emerald 600


def _format_date(dt):
    """Format datetime or date into readable Indian business format."""
    if not dt:
        return '—'
    if hasattr(dt, 'strftime'):
        return dt.strftime('%d-%b-%Y')
    return str(dt)


def _draw_page_decorations(canvas, doc):
    """Running header accent strip and footer for each page."""
    canvas.saveState()
    page_w, page_h = A4

    # Top gold accent line
    canvas.setStrokeColor(PRIMARY_GOLD)
    canvas.setLineWidth(3)
    canvas.line(0, page_h - 1.5, page_w, page_h - 1.5)

    # Bottom footer line
    canvas.setStrokeColor(BORDER_LIGHT)
    canvas.setLineWidth(0.8)
    canvas.line(15 * mm, 14 * mm, page_w - 15 * mm, 14 * mm)

    # Footer Text Left
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawString(15 * mm, 9 * mm, "JewelDesk Cloud Suite • Confidential Commercial Quotation • https://jeweldesk.in")

    # Footer Text Right (Page Number)
    canvas.drawRightString(page_w - 15 * mm, 9 * mm, f"Page {doc.page} • Generated: {timezone.now().strftime('%d-%b-%Y')}")
    canvas.restoreState()


def build_proposal_pdf(proposal) -> bytes:
    """Generate and return PDF bytes for the given PlatformProposal instance."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=15 * mm,
        bottomMargin=18 * mm,
    )

    base = getSampleStyleSheet()

    # Custom Typography Styles
    style_brand = ParagraphStyle(
        'DocBrand',
        parent=base['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=22,
        textColor=PRIMARY_GOLD,
    )
    style_tagline = ParagraphStyle(
        'DocTagline',
        parent=base['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=TEXT_MUTED,
    )
    style_doc_title = ParagraphStyle(
        'DocTitle',
        parent=base['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=14,
        alignment=2,  # Right align
        textColor=DARK_SLATE,
    )
    style_doc_meta = ParagraphStyle(
        'DocMeta',
        parent=base['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        alignment=2,  # Right align
        textColor=DARK_CHARCOAL,
    )
    style_section_title = ParagraphStyle(
        'SectionTitle',
        parent=base['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9.5,
        leading=12,
        textColor=PRIMARY_GOLD,
        textTransform='uppercase',
    )
    style_box_label = ParagraphStyle(
        'BoxLabel',
        parent=base['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=10,
        textColor=TEXT_MUTED,
        textTransform='uppercase',
    )
    style_box_val = ParagraphStyle(
        'BoxVal',
        parent=base['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=DARK_SLATE,
    )
    style_feature_item = ParagraphStyle(
        'FeatureItem',
        parent=base['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=DARK_CHARCOAL,
    )
    style_th = ParagraphStyle(
        'TH',
        parent=base['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )
    style_th_right = ParagraphStyle(
        'THRight',
        parent=style_th,
        alignment=2,
    )
    style_td = ParagraphStyle(
        'TD',
        parent=base['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=DARK_SLATE,
    )
    style_td_right = ParagraphStyle(
        'TDRight',
        parent=style_td,
        alignment=2,
    )
    style_term_item = ParagraphStyle(
        'TermItem',
        parent=base['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=10.5,
        textColor=DARK_CHARCOAL,
    )

    story = []

    # =========================================================================
    # 1. HEADER BRANDING & PROPOSAL METADATA
    # =========================================================================
    status_display = proposal.get_status_display()
    valid_until_str = _format_date(proposal.valid_until) if proposal.valid_until else '30 Days from Issue'

    header_left = [
        Paragraph("JEWELDESK", style_brand),
        Paragraph("Jewellery Showroom & Atelier Management Cloud Platform", style_tagline),
        Paragraph("Email: sales@jeweldesk.in &bull; Web: https://jeweldesk.in", style_tagline),
    ]

    header_right = [
        Paragraph("COMMERCIAL PROPOSAL", style_doc_title),
        Spacer(1, 2 * mm),
        Paragraph(f"<b>Proposal Ref:</b> <font color='#B48516'>{proposal.proposal_number}</font>", style_doc_meta),
        Paragraph(f"<b>Date:</b> {_format_date(proposal.created_at)}", style_doc_meta),
        Paragraph(f"<b>Valid Until:</b> <font color='#059669'>{valid_until_str}</font>", style_doc_meta),
        Paragraph(f"<b>Status:</b> {status_display}", style_doc_meta),
    ]

    header_table = Table(
        [[header_left, header_right]],
        colWidths=[105 * mm, 77 * mm]
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY_GOLD, spaceBefore=0, spaceAfter=4 * mm))

    # =========================================================================
    # 2. CLIENT INFORMATION & PROPOSAL SCOPE
    # =========================================================================
    client_box_content = [
        Paragraph("<b>PREPARED FOR:</b>", style_box_label),
        Spacer(1, 1 * mm),
        Paragraph(f"<b>{proposal.client_showroom_name}</b>", ParagraphStyle('SHName', parent=style_box_val, fontName='Helvetica-Bold', fontSize=10, textColor=DARK_SLATE)),
        Paragraph(f"<b>Contact Person:</b> {proposal.client_name}", style_box_val),
        Paragraph(f"<b>Mobile / WhatsApp:</b> {proposal.client_phone or '—'}", style_box_val),
        Paragraph(f"<b>Email Address:</b> {proposal.client_email or '—'}", style_box_val),
        Paragraph(f"<b>City / Location:</b> {proposal.client_city or '—'}", style_box_val),
    ]

    scope_box_content = [
        Paragraph("<b>SUBSCRIPTION PACKAGE SPECIFICATION:</b>", style_box_label),
        Spacer(1, 1 * mm),
        Paragraph(f"<b>Plan Tier:</b> <font color='#B48516'><b>{proposal.get_target_plan_display()}</b></font>", style_box_val),
        Paragraph(f"<b>Billing Frequency:</b> {proposal.get_billing_cycle_display()}", style_box_val),
        Paragraph("<b>Cloud Architecture:</b> Multi-Tenant Isolated Showroom Instance", style_box_val),
        Paragraph("<b>Data Security:</b> 256-Bit SSL Encryption & Automated Daily Backups", style_box_val),
        Paragraph("<b>Support Level:</b> Priority Showroom Support & Dedicated Architect", style_box_val),
    ]

    client_table = Table(
        [[client_box_content, scope_box_content]],
        colWidths=[90 * mm, 92 * mm]
    )
    client_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_LIGHT),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
        ('TOPPADDING', (0, 0), (-1, -1), 3 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 4 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4 * mm),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(client_table)
    story.append(Spacer(1, 4 * mm))

    # =========================================================================
    # 3. INCLUDED FEATURES & MODULES
    # =========================================================================
    story.append(Paragraph("INCLUDED FEATURES & CORE CAPABILITIES", style_section_title))
    story.append(Spacer(1, 1.5 * mm))

    features_raw = [f.strip() for f in proposal.features_summary.split('\n') if f.strip()]
    if not features_raw:
        features_raw = [
            "Complete Jewellery POS & Custom Quotation Generation",
            "BIS Hallmarking & HUID Tag Registry Tracking",
            "Karigar Issue, Receive & Loss/Wastage Ledger",
            "Real-Time Gold & Silver Board Rate Sync",
            "Instant WhatsApp Digital Invoice Delivery",
            "Multi-Device Support (Mobile, Tablet, Desktop POS)",
            "Daily Day-End Cash & Bank Tally Reports",
            "Dedicated Onboarding & 99.9% Uptime Cloud Infrastructure",
        ]

    # Split features into 2 columns
    half = (len(features_raw) + 1) // 2
    col1 = features_raw[:half]
    col2 = features_raw[half:]

    def make_feature_cell(items):
        cell_elements = []
        for item in items:
            cleaned = item.lstrip('•*- ').strip()
            cell_elements.append(Paragraph(f"<font color='#059669'><b>&#10003;</b></font>&nbsp; {cleaned}", style_feature_item))
            cell_elements.append(Spacer(1, 1.2 * mm))
        return cell_elements

    feat_table = Table(
        [[make_feature_cell(col1), make_feature_cell(col2)]],
        colWidths=[91 * mm, 91 * mm]
    )
    feat_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 1 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 1 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1 * mm),
    ]))
    story.append(feat_table)
    story.append(Spacer(1, 4 * mm))

    # =========================================================================
    # 4. COMMERCIAL QUOTATION & PRICING TABLE
    # =========================================================================
    story.append(Paragraph("COMMERCIAL QUOTATION & INVESTMENT SUMMARY", style_section_title))
    story.append(Spacer(1, 1.5 * mm))

    plan_desc = f"<b>JewelDesk Cloud Suite License</b><br/><font color='#64748B' size='7'>{proposal.get_target_plan_display()} &bull; Full Multi-Tenant Showroom Access</font>"
    cycle_desc = proposal.get_billing_cycle_display()
    list_price_str = f"₹{proposal.quoted_amount:,.2f}"
    discount_str = f"-₹{proposal.discount_amount:,.2f}" if proposal.discount_amount > Decimal('0.00') else "—"
    final_amount_str = f"₹{proposal.final_amount:,.2f}"

    quotation_data = [
        [
            Paragraph("Item Description & Scope", style_th),
            Paragraph("Billing Frequency", style_th),
            Paragraph("Standard Price", style_th_right),
            Paragraph("Special Discount", style_th_right),
            Paragraph("Net Amount", style_th_right),
        ],
        [
            Paragraph(plan_desc, style_td),
            Paragraph(cycle_desc, style_td),
            Paragraph(list_price_str, style_td_right),
            Paragraph(f"<font color='#059669'>{discount_str}</font>", style_td_right),
            Paragraph(f"<b>{final_amount_str}</b>", style_td_right),
        ],
        [
            Paragraph("<b>TOTAL COMMERCIAL INVESTMENT (NET PAYABLE)</b>", ParagraphStyle('TotLbl', parent=style_td, fontName='Helvetica-Bold', fontSize=8.5, textColor=DARK_SLATE)),
            "",
            "",
            "",
            Paragraph(f"<b><font size='10' color='#B48516'>{final_amount_str}</font></b>", style_td_right),
        ]
    ]

    quote_table = Table(
        quotation_data,
        colWidths=[70 * mm, 38 * mm, 26 * mm, 24 * mm, 24 * mm]
    )
    quote_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), DARK_SLATE),
        ('ALIGN', (0, 0), (1, -1), 'LEFT'),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -2), 0.5, BORDER_LIGHT),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2.5 * mm),
        # Total Row Styling
        ('SPAN', (0, 2), (3, 2)),
        ('BACKGROUND', (0, 2), (-1, 2), GOLD_SUBTLE_BG),
        ('LINEABOVE', (0, 2), (-1, 2), 1.5, PRIMARY_GOLD),
    ]))
    story.append(quote_table)
    story.append(Spacer(1, 4 * mm))

    # =========================================================================
    # 5. ONBOARDING ROADMAP & TERMS OF ENGAGEMENT
    # =========================================================================
    terms_raw = [t.strip() for t in proposal.terms_notes.split('\n') if t.strip()]
    if not terms_raw:
        terms_raw = [
            "1. Pricing is inclusive of dedicated cloud deployment, daily backups, and security patching.",
            "2. 1-on-1 staff onboarding and opening inventory balance setup included at zero additional cost.",
            "3. Cloud instance ready within 24-48 business hours of proposal confirmation.",
            "4. Payment Terms: 100% advance upon confirmation via UPI, NEFT, IMPS or Cheque.",
        ]

    terms_elements = []
    for t_item in terms_raw:
        terms_elements.append(Paragraph(t_item, style_term_item))
        terms_elements.append(Spacer(1, 0.8 * mm))

    terms_box = Table(
        [[
            [
                Paragraph("<b>TERMS OF SERVICE & IMPLEMENTATION SCHEDULE:</b>", style_box_label),
                Spacer(1, 1 * mm),
                *terms_elements
            ]
        ]],
        colWidths=[182 * mm]
    )
    terms_box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_LIGHT),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 3.5 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3.5 * mm),
    ]))
    story.append(terms_box)
    story.append(Spacer(1, 4 * mm))

    # =========================================================================
    # 6. SIGNATURE & ACCEPTANCE BLOCK
    # =========================================================================
    sig_left = [
        Paragraph("<b>CLIENT ACCEPTANCE</b>", style_box_label),
        Spacer(1, 10 * mm),
        Paragraph("Authorized Signature: ____________________________", style_box_val),
        Spacer(1, 1 * mm),
        Paragraph("Name & Title: _________________________________", style_box_val),
        Spacer(1, 1 * mm),
        Paragraph(f"For: <b>{proposal.client_showroom_name}</b>", style_box_val),
    ]

    sig_right = [
        Paragraph("<b>FOR JEWELDESK PLATFORM</b>", style_box_label),
        Spacer(1, 10 * mm),
        Paragraph("Commercial Operations Desk", ParagraphStyle('SignRight', parent=style_box_val, fontName='Helvetica-Bold')),
        Spacer(1, 1 * mm),
        Paragraph("JewelDesk Atelier & Retail Management Cloud", style_box_val),
        Spacer(1, 1 * mm),
        Paragraph(f"Ref Token: <font color='#64748B'>{proposal.share_token[:16]}...</font>", style_box_val),
    ]

    sig_table = Table(
        [[sig_left, sig_right]],
        colWidths=[91 * mm, 91 * mm]
    )
    sig_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2 * mm),
        ('TOPPADDING', (0, 0), (-1, -1), 2 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2 * mm),
    ]))

    story.append(KeepTogether([sig_table]))

    # Build PDF
    doc.build(
        story,
        onFirstPage=_draw_page_decorations,
        onLaterPages=_draw_page_decorations,
    )

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
