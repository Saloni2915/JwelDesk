#!/usr/bin/env python3
"""
tools/generate_project_pdf_report.py
------------------------------------
Generates a comprehensive, professional, publication-quality PDF report
documenting all features, architecture, workflows, and operational guides
of the JewelDesk Jewellery Retail Management System.
"""

import os
import sys
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable, Image
)
from reportlab.pdfgen import canvas

# ----------------------------------------------------------------------
# Custom Numbered Canvas for Running Headers and Footers
# ----------------------------------------------------------------------
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_decorations(self, page_count):
        # Suppress headers & footers on the cover page
        if self._pageNumber == 1:
            return

        self.saveState()
        self.setFont('Helvetica', 8)
        self.setFillColor(colors.HexColor('#64748b'))
        self.setStrokeColor(colors.HexColor('#cbd5e1'))
        self.setLineWidth(0.6)

        # Running Top Header
        self.line(15 * mm, 282 * mm, 195 * mm, 282 * mm)
        self.drawString(15 * mm, 284 * mm, "JewelDesk — Comprehensive Project Architecture & Feature Report")
        self.drawRightString(195 * mm, 284 * mm, "Production Release v2.0")

        # Running Bottom Footer
        self.line(15 * mm, 14 * mm, 195 * mm, 14 * mm)
        self.drawString(15 * mm, 9.5 * mm, "Confidential • JewelDesk Jewellery Retail Management System • All Rights Reserved")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(195 * mm, 9.5 * mm, page_str)

        self.restoreState()


# ----------------------------------------------------------------------
# PDF Generation Function
# ----------------------------------------------------------------------
def generate_pdf_report(output_filename):
    print(f"Generating JewelDesk PDF report at: {output_filename}")
    
    doc = SimpleDocTemplate(
        output_filename,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm
    )

    # Base Styles
    styles = getSampleStyleSheet()

    # Brand Colors
    c_gold = colors.HexColor('#c59b27')
    c_gold_light = colors.HexColor('#fef9c3')
    c_navy = colors.HexColor('#121824')
    c_navy_light = colors.HexColor('#1a2232')
    c_text = colors.HexColor('#1e293b')
    c_text_muted = colors.HexColor('#64748b')
    c_border = colors.HexColor('#cbd5e1')
    c_bg_alt = colors.HexColor('#f8fafc')
    c_green = colors.HexColor('#15803d')
    c_blue = colors.HexColor('#1d4ed8')

    # Custom Typography Styles
    title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=28,
        leading=34,
        textColor=c_navy,
        alignment=0
    )

    subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=13,
        leading=18,
        textColor=c_gold,
        alignment=0
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=c_navy,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=c_gold,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13.5,
        textColor=c_text,
        spaceAfter=5
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        parent=body_style,
        leftIndent=14,
        firstLineIndent=-10,
        spaceAfter=3
    )

    callout_style = ParagraphStyle(
        'Callout_Text',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12.5,
        textColor=c_text
    )

    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
        alignment=1
    )

    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10.5,
        textColor=c_text
    )

    table_cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=table_cell_style,
        fontName='Helvetica-Bold'
    )

    story = []

    # ==================================================================
    # 1. COVER PAGE
    # ==================================================================
    story.append(Spacer(1, 15 * mm))

    # App Logo
    logo_path = os.path.join('static', 'icons', 'icon-512x512.png')
    if os.path.exists(logo_path):
        story.append(Image(logo_path, width=65, height=65))
        story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("JewelDesk", title_style))
    story.append(Paragraph("Jewellery Retail Management & ERP System", subtitle_style))
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width="100%", thickness=2.5, color=c_gold, spaceBefore=4, spaceAfter=12))

    story.append(Paragraph("<b>Complete Project Architecture, Feature Specifications & Operational Manual</b>", ParagraphStyle(
        'CoverDocType', parent=body_style, fontSize=11, leading=15, textColor=c_navy
    )))
    story.append(Spacer(1, 4 * mm))

    meta_text = f"""
    <b>Document Version:</b> 2.0 (Production Master Release)<br/>
    <b>Date of Publication:</b> {datetime.now().strftime('%B %d, %Y')}<br/>
    <b>System Classification:</b> Enterprise Retail Jewellery Management System<br/>
    <b>Technical Foundation:</b> Django 6.1 • Python 3.12 • Bootstrap 5.3 • ReportLab • Progressive Web App (PWA)<br/>
    <b>Database:</b> SQLite (Local Dev) / PostgreSQL (Production & Cloud Hosting)
    """
    story.append(Paragraph(meta_text, body_style))
    story.append(Spacer(1, 8 * mm))

    # Executive Summary Card
    exec_summary_html = """
    <b>EXECUTIVE SUMMARY:</b><br/>
    <b>JewelDesk</b> is an end-to-end, production-grade jewellery showroom management, billing, inventory, and artisan (karigar) manufacturing ERP application. Specifically tailored to the Indian and global jewellery trade, the application incorporates statutory GST (3%) calculation, Hallmark Unique Identification (HUID) compliance, purity calculations (24K, 22K, 18K, 925), dynamic pricing based on live metal rates, customer old gold exchange and cash buybacks, bespoke custom order lifecycles, artisan metal loss/wastage tracking, role-based employee access control, and complete Progressive Web App (PWA) offline resilience.
    """
    exec_card = Table(
        [[Paragraph(exec_summary_html, callout_style)]],
        colWidths=[180 * mm]
    )
    exec_card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 1, c_gold),
        ('PADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(exec_card)
    story.append(Spacer(1, 8 * mm))

    # Quick Feature Matrix Table on Cover Page
    story.append(Paragraph("<b>System Core Modules Summary:</b>", h2_style))
    core_summary_data = [
        [Paragraph("Module", table_header_style), Paragraph("Core Functionality", table_header_style), Paragraph("Key Business Benefits", table_header_style)],
        [Paragraph("<b>1. Cockpit Dashboard</b>", table_cell_bold), Paragraph("Executive summary, sales totals, inventory value, pending dues, live metal prices, alerts.", table_cell_style), Paragraph("Instant business visibility and one-click actions.", table_cell_style)],
        [Paragraph("<b>2. Inventory & Stock</b>", table_cell_bold), Paragraph("HUID tag tracking, purity, weight details, making charges, CSV import, audit movement log.", table_cell_style), Paragraph("Zero stock leakage; full hallmark compliance.", table_cell_style)],
        [Paragraph("<b>3. Pricing Engine</b>", table_cell_bold), Paragraph("Live gold & silver price feeds, dynamic formula calculation, live AJAX price calculator.", table_cell_style), Paragraph("Accurate real-time retail pricing automatically.", table_cell_style)],
        [Paragraph("<b>4. Sales & Invoicing</b>", table_cell_bold), Paragraph("Multi-item billing, GST (3%), split payments, ReportLab PDF tax invoices, WhatsApp billing.", table_cell_style), Paragraph("Instant retail billing with print & mobile sharing.", table_cell_style)],
        [Paragraph("<b>5. Old Gold Exchange</b>", table_cell_bold), Paragraph("Karat testing, melt value calculation, wastage deduction, invoice offset or cash buyback.", table_cell_style), Paragraph("Profitable and transparent scrap metal handling.", table_cell_style)],
        [Paragraph("<b>6. Customer CRM</b>", table_cell_bold), Paragraph("Customer directory, purchase ledger, PAN/Aadhaar compliance, enquiries and lead follow-up.", table_cell_style), Paragraph("Repeat sales and statutory compliance tracking.", table_cell_style)],
        [Paragraph("<b>7. Custom Orders</b>", table_cell_bold), Paragraph("Bespoke design specs, reference photo uploads, advance payments, 8-stage progress tracking.", table_cell_style), Paragraph("Eliminates delivery delays and design mistakes.", table_cell_style)],
        [Paragraph("<b>8. Karigar & Artisans</b>", table_cell_bold), Paragraph("Raw metal issue, work order assignments, scrap return, metal loss/wastage audit, settlements.", table_cell_style), Paragraph("Complete control over workshop metal inventory.", table_cell_style)],
        [Paragraph("<b>9. Team & Multi-Branch</b>", table_cell_bold), Paragraph("Staff management, granular 7-module RBAC, branch allocations, privilege escalation guards.", table_cell_style), Paragraph("Multi-store management with strict security.", table_cell_style)],
        [Paragraph("<b>10. UI, Mobile & PWA</b>", table_cell_bold), Paragraph("Multi-breakpoint responsive layouts, off-canvas navigation drawer, service worker, offline fallback.", table_cell_style), Paragraph("App-like mobile & tablet experience everywhere.", table_cell_style)],
    ]
    core_table = Table(core_summary_data, colWidths=[42 * mm, 80 * mm, 58 * mm])
    core_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_navy_light),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_bg_alt]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(core_table)

    story.append(PageBreak())

    # ==================================================================
    # 2. SECTION 1: ARCHITECTURE & TECHNICAL FOUNDATIONS
    # ==================================================================
    story.append(Paragraph("1. Technical Architecture & System Foundations", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=c_gold, spaceBefore=2, spaceAfter=8))

    story.append(Paragraph(
        "JewelDesk is designed according to clean, modular Django architecture principles. "
        "Each functional business domain is encapsulated in an isolated Django application with dedicated models, "
        "views, forms, URL namespaces, and template sets.", body_style
    ))

    arch_data = [
        [Paragraph("Component", table_header_style), Paragraph("Technology / Pattern", table_header_style), Paragraph("Role in JewelDesk", table_header_style)],
        [Paragraph("<b>Backend Framework</b>", table_cell_bold), Paragraph("Django 6.1.1 (Python 3.12)", table_cell_style), Paragraph("Robust MVC/MVT architecture, ORM, authentication, CSRF security.", table_cell_style)],
        [Paragraph("<b>Frontend & UI</b>", table_cell_bold), Paragraph("Bootstrap 5.3.3 + Custom CSS & JS", table_cell_style), Paragraph("Modern styling system, multi-theme tokens (Light, Dark, Gold).", table_cell_style)],
        [Paragraph("<b>Responsive Engine</b>", table_cell_bold), Paragraph("Mobile-first Media Queries + Flex/Grid", table_cell_style), Paragraph("Full compatibility across Phones (320px+), Tablets, Laptops & Desktops.", table_cell_style)],
        [Paragraph("<b>PWA Engine</b>", table_cell_bold), Paragraph("W3C Manifest + Service Worker", table_cell_style), Paragraph("App-like installability, caching shell, offline fallback page.", table_cell_style)],
        [Paragraph("<b>Document Engine</b>", table_cell_bold), Paragraph("ReportLab PDF Library", table_cell_style), Paragraph("Statutory GST tax invoices and enterprise operational reports.", table_cell_style)],
        [Paragraph("<b>Database</b>", table_cell_bold), Paragraph("SQLite (Dev) / PostgreSQL (Prod)", table_cell_style), Paragraph("ACID transaction safety, connection pooling & Supabase support.", table_cell_style)],
        [Paragraph("<b>Static Delivery</b>", table_cell_bold), Paragraph("WhiteNoise Middleware", table_cell_style), Paragraph("High performance, compressed, versioned static assets serving.", table_cell_style)],
    ]
    arch_table = Table(arch_data, colWidths=[40 * mm, 55 * mm, 85 * mm])
    arch_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_navy_light),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_bg_alt]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(arch_table)
    story.append(Spacer(1, 4 * mm))

    # Multi-Theme Architecture Box
    theme_box = """
    <b>MULTI-THEME ARCHITECTURE:</b><br/>
    JewelDesk supports three curated visual themes to suit showroom lighting conditions:
    <br/>• <b>Light Theme:</b> Crisp white surfaces with subtle border dividers and dark typography. Optimized for well-lit office counters.
    <br/>• <b>Dark Theme:</b> Deep obsidian background (<code>#121824</code>) with dark card surfaces. Eliminates glare in intimate jewellery showrooms.
    <br/>• <b>Gold / Premium Theme:</b> Warm ivory and champagne surfaces with antique gold accents. Delivers a luxury jewellery brand feeling.
    <br/><i>Theme persistence is implemented via cookie and localStorage sync, with an inline pre-paint script that guarantees zero theme-flicker on page load.</i>
    """
    theme_card = Table([[Paragraph(theme_box, callout_style)]], colWidths=[180 * mm])
    theme_card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fefce8')),
        ('BOX', (0, 0), (-1, -1), 1, c_gold),
        ('PADDING', (0, 0), (-1, -1), 7),
    ]))
    story.append(theme_card)
    story.append(Spacer(1, 6 * mm))

    # ==================================================================
    # 3. SECTION 2: DETAILED MODULE-BY-MODULE SPECIFICATIONS
    # ==================================================================
    story.append(Paragraph("2. Detailed Module Specifications & Feature Breakdown", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=c_gold, spaceBefore=2, spaceAfter=8))

    # Module 1: Cockpit Dashboard
    story.append(Paragraph("2.1 Executive Cockpit Dashboard", h2_style))
    story.append(Paragraph(
        "The Dashboard serves as the central command cockpit for the showroom proprietor and staff. "
        "It aggregates critical financial, inventory, and operational metrics in real time upon page load.", body_style
    ))
    story.append(Paragraph("• <b>Today's Sales & Transactions:</b> Real-time revenue generated today with transaction counter.", bullet_style))
    story.append(Paragraph("• <b>Lifetime Revenue & Outstanding Due:</b> Total sales volume vs pending customer receivables.", bullet_style))
    story.append(Paragraph("• <b>Inventory Valuation:</b> Live retail stock valuation dynamically computed across all categories.", bullet_style))
    story.append(Paragraph("• <b>Low Stock Warnings:</b> Automatic design alerts when stock falls below pre-configured thresholds.", bullet_style))
    story.append(Paragraph("• <b>Pending Custom Orders:</b> Visual badge highlighting custom orders currently in production.", bullet_style))
    story.append(Paragraph("• <b>Quick Actions:</b> One-click shortcut tiles for New Sale, Add Customer, Inward Inventory, and Bespoke Order.", bullet_style))
    story.append(Paragraph("• <b>Live Metal Rates Widget:</b> Displays 24K Gold, 22K Gold, and 999 Silver prices with an API refresh button.", bullet_style))

    story.append(Spacer(1, 3 * mm))

    # Module 2: Inventory & Stock Management
    story.append(Paragraph("2.2 Inventory & Stock Management Module", h2_style))
    story.append(Paragraph(
        "Jewellery inventory requires exacting precision beyond standard retail goods. JewelDesk tracks every single "
        "piece by individual tag, hallmark, weights, and purity levels.", body_style
    ))
    story.append(Paragraph("• <b>Item Identity & Tagging:</b> Unique Tag Number (barcode/RFID ready) and government-mandated HUID (6-character alphanumeric hallmark).", bullet_style))
    story.append(Paragraph("• <b>Metal & Purity Classification:</b> Gold (24K, 22K, 18K, 14K), Silver (999, 925 Sterling), and Platinum.", bullet_style))
    story.append(Paragraph("• <b>Three-Tier Weight Breakdown:</b> Gross Weight (total item weight), Stone Weight (diamonds, gemstones, pearls), and Net Weight (pure metal weight for billing).", bullet_style))
    story.append(Paragraph("• <b>Making Charges & Wastage:</b> Configurable making charge (per gram or fixed percentage) and wastage percentage.", bullet_style))
    story.append(Paragraph("• <b>Bulk CSV Inventory Import:</b> Upload hundreds of inventory records in seconds. Includes sample CSV download, preview confirmation, duplicate tag detection, and validation checks.", bullet_style))
    story.append(Paragraph("• <b>Audit Trail Stock Movements:</b> Every stock change creates an immutable <code>StockMovement</code> record (Inward, Outward, Sale deduction, Return addition, or Reconciliation Adjustment) logging user, timestamp, and reason.", bullet_style))

    story.append(Spacer(1, 3 * mm))

    # Module 3: Pricing Engine & Real-Time Metal Rates
    story.append(Paragraph("2.3 Dynamic Pricing Engine & Metal Rates", h2_style))
    story.append(Paragraph(
        "Due to continuous fluctuations in bullion markets, JewelDesk decouples metal price updates from individual item records. "
        "When metal rates update, the entire catalogue re-prices dynamically.", body_style
    ))
    story.append(Paragraph("• <b>Live Rate Integration:</b> Gold and silver rates can be fetched via live external financial APIs or manually updated by store managers.", bullet_style))
    story.append(Paragraph("• <b>Mathematical Pricing Model:</b>", bullet_style))

    # Formula Box
    formula_html = """
    <b>JEWELDESK STANDARD PRICING FORMULA:</b><br/>
    <code>Metal Value = Net Metal Weight (g) × Current Metal Rate per Gram (for specific Karat)</code><br/>
    <code>Making Cost = (Making Rate per Gram × Gross Weight) OR (Metal Value × Making %)</code><br/>
    <code>Stone Value = Sum of (Stone Carats/Weight × Stone Rate)</code><br/>
    <code>Subtotal = Metal Value + Making Cost + Stone Value - Trade Discount</code><br/>
    <code>GST (3.0%) = Subtotal × 0.03  (CGST 1.5% + SGST 1.5% or IGST 3.0%)</code><br/>
    <b>Final Retail Invoice Price = Subtotal + GST</b>
    """
    formula_card = Table([[Paragraph(formula_html, callout_style)]], colWidths=[180 * mm])
    formula_card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f1f5f9')),
        ('BOX', (0, 0), (-1, -1), 1, c_border),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(formula_card)
    story.append(Paragraph("• <b>AJAX Pricing Calculator Endpoint:</b> <code>/pricing/api/calculate/</code> allows counter staff to calculate quotations instantly on the fly without page reloads.", bullet_style))

    story.append(PageBreak())

    # Module 4: Sales, Billing & Tax Invoicing
    story.append(Paragraph("2.4 Sales, Invoicing & Tax Billing Module", h2_style))
    story.append(Paragraph(
        "The sales module enables counter sales executives to generate statutory GST-compliant invoices in under 60 seconds.", body_style
    ))
    story.append(Paragraph("• <b>Multi-Item Invoices:</b> Multiple jewellery items, coins, and loose stones on a single consolidated bill.", bullet_style))
    story.append(Paragraph("• <b>Tag Search & Quick Scan:</b> Scan or enter Tag Number to instantly populate metal weight, purity, HUID, and calculate prices automatically.", bullet_style))
    story.append(Paragraph("• <b>Customer Onboarding on the Fly:</b> Add a new customer directly inside the billing screen without losing cart state.", bullet_style))
    story.append(Paragraph("• <b>Multi-Mode & Split Payments:</b> Supports multiple payment tender types on a single invoice (e.g. ₹50,000 Cash + ₹75,000 Credit Card + ₹25,000 UPI).", bullet_style))
    story.append(Paragraph("• <b>Partial Payments & Credit Ledger:</b> Record partial payments; the system automatically marks the invoice status as 'Partial' and tracks the pending balance.", bullet_style))
    story.append(Paragraph("• <b>ReportLab PDF Tax Invoices:</b> Generates professional A4 PDF tax invoices with store logo, GSTIN, HUID breakdown, tax breakup, payment receipts, and terms.", bullet_style))
    story.append(Paragraph("• <b>Instant WhatsApp Invoicing:</b> One-click WhatsApp button generates pre-formatted message links (<code>https://wa.me/</code>) to send invoices directly to customer phones.", bullet_style))
    story.append(Paragraph("• <b>Sales Analytics & Presets:</b> Preset filters for Today, This Week, This Month, and Custom Date Ranges with exportable totals.", bullet_style))

    story.append(Spacer(1, 3 * mm))

    # Module 5: Old Gold Exchange & Buyback
    story.append(Paragraph("2.5 Old Gold Exchange & Buyback Module", h2_style))
    story.append(Paragraph(
        "A cornerstone of the retail jewellery business is taking old scrap gold from customers. JewelDesk provides "
        "transparent calculation and auditable record-keeping.", body_style
    ))
    story.append(Paragraph("• <b>Old Metal Karat Testing:</b> Staff record gross weight, stone weight deduction, and tested purity (e.g. 18K, 20K, 22K).", bullet_style))
    story.append(Paragraph("• <b>Melt Value & Melting Wastage:</b> Calculates pure gold content and applies permissible melting wastage percentage.", bullet_style))
    story.append(Paragraph("• <b>Two Operational Modes:</b>", bullet_style))
    story.append(Paragraph("  - <i>Exchange Mode:</i> Value of old gold is credited directly as a deduction on the customer's new purchase invoice.", bullet_style))
    story.append(Paragraph("  - <i>Buyback Mode:</i> Store purchases old gold for cash or bank payout with a signed statutory voucher.", bullet_style))
    story.append(Paragraph("• <b>Inward Scrap Audit Trail:</b> Detailed records of all old gold received, providing complete stock reconciliation when scrap is sent to refineries or karigars.", bullet_style))

    story.append(Spacer(1, 3 * mm))

    # Module 6: Customer Relationship Management (CRM)
    story.append(Paragraph("2.6 Customer Relationship Management (CRM)", h2_style))
    story.append(Paragraph(
        "JewelDesk CRM records long-term customer relationships, purchase ledgers, and sales leads.", body_style
    ))
    story.append(Paragraph("• <b>Customer Profiles:</b> Full name, mobile number, email address, physical address, and anniversary/birthday for festive loyalty campaigns.", bullet_style))
    story.append(Paragraph("• <b>Statutory Compliance (KYC):</b> Fields for PAN card and Aadhaar numbers to satisfy mandatory compliance for cash sales over ₹2,00,000.", bullet_style))
    story.append(Paragraph("• <b>Customer Financial Ledger:</b> Complete history of all lifetime purchases, invoices, returned items, and outstanding credit dues.", bullet_style))
    story.append(Paragraph("• <b>Enquiries & Lead Pipeline:</b> Record customer enquiries (e.g. bridal set enquiry, solitaire ring), scheduled follow-up dates, notes, and conversion status.", bullet_style))

    story.append(Spacer(1, 3 * mm))

    # Module 7: Custom Orders & Bespoke Jewellery
    story.append(Paragraph("2.7 Custom Orders & Bespoke Jewellery Module", h2_style))
    story.append(Paragraph(
        "High-margin bespoke jewellery orders require strict milestone tracking from design to delivery.", body_style
    ))
    story.append(Paragraph("• <b>Design Uploads:</b> Customer reference sketches, CAD renderings, and photo uploads stored securely.", bullet_style))
    story.append(Paragraph("• <b>Detailed Specifications:</b> Target weight, metal karat, gemstone details, sizing, engraving instructions.", bullet_style))
    story.append(Paragraph("• <b>8-Stage Lifecycle Tracking:</b> Pending → In Design → Approved → With Karigar → In Finishing → Ready for Delivery → Delivered → Cancelled.", bullet_style))
    story.append(Paragraph("• <b>Advance Payments & Quotations:</b> Tracks estimated order cost, advance deposit received, and remaining balance due on handover.", bullet_style))

    story.append(Spacer(1, 3 * mm))

    # Module 8: Karigar & Manufacturing Management
    story.append(Paragraph("2.8 Karigar & Manufacturing Management Module", h2_style))
    story.append(Paragraph(
        "JewelDesk includes an integrated manufacturing submodule for tracking independent artisans and workshops.", body_style
    ))
    story.append(Paragraph("• <b>Artisan Profiles:</b> Workshop names, contact details, specialized craft (Bengali, Kundan, Casting, Stone setting), making wage rates.", bullet_style))
    story.append(Paragraph("• <b>Raw Metal Issue & Work Orders:</b> Issue raw pure metal (gold/silver bars, grains) to karigars with recorded issue weight, purity, and expected delivery date.", bullet_style))
    story.append(Paragraph("• <b>Wastage & Metal Loss Auditing:</b> Compares issued weight against finished jewellery weight and returned scrap. Automatically flags excess metal loss exceeding allowable contractual wastage limits.", bullet_style))
    story.append(Paragraph("• <b>Karigar Settlements:</b> Tracks making wage payables, advances given, deductions, and settles accounts with payment vouchers.", bullet_style))
    story.append(Paragraph("• <b>Manufacturing Cockpit:</b> Real-time dashboard showing active workshop assignments, overdue jobs, and total metal currently held by artisans.", bullet_style))

    story.append(PageBreak())

    # Module 9: Team, Roles & Multi-Branch HR
    story.append(Paragraph("2.9 Team, Roles & Multi-Branch HR Module", h2_style))
    story.append(Paragraph(
        "JewelDesk provides enterprise-level security and multi-branch showroom control.", body_style
    ))
    story.append(Paragraph("• <b>Employee Profiles:</b> Employee code, full name, designation (Store Manager, Salesperson, Cashier, Appraiser), contact info, login credentials.", bullet_style))
    story.append(Paragraph("• <b>Granular Role-Based Access Control (RBAC):</b> 7 distinct modules (Sales, Inventory, Pricing, Customers, Custom Orders, Karigar, Team) with independent View, Add, Edit, Delete flags.", bullet_style))
    story.append(Paragraph("• <b>Multi-Branch Store Support:</b> Group retail showrooms into branches (e.g. Main Showroom, Mall Branch). Staff and inventory can be mapped to specific branches.", bullet_style))
    story.append(Paragraph("• <b>Privilege Escalation Protection:</b> Strict security prevents regular employees from modifying their own permissions or assigning Administrator roles.", bullet_style))

    story.append(Spacer(1, 3 * mm))

    # Module 10: Responsive UI & Progressive Web App (PWA)
    story.append(Paragraph("2.10 Responsive UI & Progressive Web App (PWA)", h2_style))
    story.append(Paragraph(
        "JewelDesk is designed to operate seamlessly across desktops, laptops, tablets (e.g. iPad at counter), and mobile phones.", body_style
    ))
    story.append(Paragraph("• <b>Multi-Breakpoint Responsive Design:</b> Desktop (1200px+), Laptop (992px–1199px), Tablet (768px–991px), and Mobile (320px–576px).", bullet_style))
    story.append(Paragraph("• <b>Adaptive Off-Canvas Navigation:</b> Pinned 260px desktop sidebar transforms into a slide-out drawer on tablets and mobile with backdrop dismissal and body scroll-lock.", bullet_style))
    story.append(Paragraph("• <b>Zero Page Blowout:</b> Strict viewport safety ensures horizontal scroll containment inside table components, preventing annoying horizontal webpage scrolling.", bullet_style))
    story.append(Paragraph("• <b>Touch Target Accessibility:</b> Inputs enforce 16px font size on mobile to prevent iOS Safari auto-zoom, and buttons maintain ≥40px touch targets.", bullet_style))
    story.append(Paragraph("• <b>Web App Manifest (manifest.json):</b> Standard standalone PWA definition with custom luxury jewel icons (192px, 512px, maskable, apple-touch-icon).", bullet_style))
    story.append(Paragraph("• <b>Root-Scoped Service Worker (sw.js):</b> Network-first caching for dynamic business data, stale-while-revalidate for static assets, and pre-cached shell.", bullet_style))
    story.append(Paragraph("• <b>Dedicated Offline Fallback Page (offline.html):</b> Branded offline screen with connection detection, retry triggers, and automatic reconnection when internet restores.", bullet_style))
    story.append(Paragraph("• <b>In-App PWA Install Prompt:</b> Browser-native install banner and sidebar install button allowing store owners to install JewelDesk as a desktop or mobile application.", bullet_style))

    story.append(Spacer(1, 6 * mm))

    # ==================================================================
    # 4. SECTION 3: STEP-BY-STEP OPERATIONAL WORKFLOWS (HOW IT WORKS)
    # ==================================================================
    story.append(Paragraph("3. Step-by-Step Operational Workflows (Kese Kaam Krte H)", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=c_gold, spaceBefore=2, spaceAfter=8))

    # Workflow 1
    story.append(Paragraph("3.1 Workflow: Billing a New Jewellery Sale with Old Gold Exchange", h2_style))
    wf1_steps = [
        ("Step 1: Open Sales Billing", "Navigate to <code>Sales & Exchange → New Sale</code> (or click the 'New Sale' shortcut on the Dashboard)."),
        ("Step 2: Customer Selection", "Select an existing customer from the dropdown, or click 'Add Customer' to register a new customer in a lightweight modal."),
        ("Step 3: Add Items to Invoice", "Enter or scan the Item Tag Number. JewelDesk instantly loads the item's Gross Weight, Net Weight, Purity, HUID, and calculates the retail price based on the live metal rate."),
        ("Step 4: Old Gold Exchange (Optional)", "If the customer brings old scrap jewellery: click 'Add Old Gold Exchange'. Enter tested karat, gross weight, and melting wastage. The calculated value is automatically deducted from the bill total."),
        ("Step 5: Record Payment Tender", "Enter payment modes (Cash, UPI, Credit Card, or Split). JewelDesk calculates balance due and marks payment status (Paid / Partial)."),
        ("Step 6: Generate Invoice & Share", "Submit the sale. Instantly print the ReportLab PDF tax invoice or click the WhatsApp button to send a digital bill directly to the customer's phone."),
    ]
    wf1_data = [[Paragraph(s[0], table_cell_bold), Paragraph(s[1], table_cell_style)] for s in wf1_steps]
    wf1_table = Table([[Paragraph("Workflow Step", table_header_style), Paragraph("Action & Operational Description", table_header_style)]] + wf1_data, colWidths=[50 * mm, 130 * mm])
    wf1_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_navy_light),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_bg_alt]),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    story.append(wf1_table)

    story.append(Spacer(1, 4 * mm))

    # Workflow 2
    story.append(Paragraph("3.2 Workflow: Custom Order to Karigar Manufacturing & Handover", h2_style))
    wf2_steps = [
        ("Step 1: Consultation & Booking", "Navigate to <code>Custom Orders → New Custom Order</code>. Enter customer details, design notes, upload reference sketch/photos, specify target metal weight & karat, and collect advance deposit."),
        ("Step 2: Assign to Karigar", "Open <code>Manufacturing & Karigars → Work Assignments → New Assignment</code>. Select the Karigar, link the Custom Order, issue pure gold/silver raw metal, and record the issued metal weight."),
        ("Step 3: Manufacturing & Tracking", "The job progress is monitored on the Karigar Dashboard. The system highlights pending and overdue artisan assignments automatically."),
        ("Step 4: Receive Finished Piece & Audit", "When the artisan brings the finished piece: record finished weight, returned scrap metal, and dust loss. JewelDesk calculates the wastage percentage and alerts if it exceeds agreed limits."),
        ("Step 5: Stock / Direct Delivery", "The bespoke piece is approved, HUID is recorded, and the order status is updated to 'Ready for Delivery'."),
        ("Step 6: Customer Handover & Balance", "Customer inspects the piece, pays the remaining balance invoice, and the order is marked 'Delivered'."),
    ]
    wf2_data = [[Paragraph(s[0], table_cell_bold), Paragraph(s[1], table_cell_style)] for s in wf2_steps]
    wf2_table = Table([[Paragraph("Workflow Step", table_header_style), Paragraph("Action & Operational Description", table_header_style)]] + wf2_data, colWidths=[50 * mm, 130 * mm])
    wf2_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_navy_light),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_bg_alt]),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    story.append(wf2_table)

    story.append(PageBreak())

    # Workflow 3
    story.append(Paragraph("3.3 Workflow: Inventory Inward, HUID Tagging & Dynamic Re-Pricing", h2_style))
    wf3_steps = [
        ("Step 1: Inventory Entry / CSV Upload", "Add single jewellery items via <code>Inventory → Add Jewellery Stock</code> or upload hundreds via <code>Import Inventory</code> CSV file."),
        ("Step 2: Tag & HUID Recording", "Assign unique Tag Number (e.g. RNG-2026-001) and Bureau of Indian Standards (BIS) Hallmark Unique ID (HUID) for legal hallmarking compliance."),
        ("Step 3: Weight Specification", "Input Gross Weight, Stone Weight (carats/grams), and Net Weight. Set making charges per gram or as a percentage."),
        ("Step 4: Dynamic Re-Pricing", "When bullion market rates fluctuate, staff click 'Refresh Rates' in Pricing Engine. All inventory items automatically recalculate retail prices instantly."),
        ("Step 5: Physical Reconciliation", "Perform periodic stock audits via <code>Adjust Stock</code> to log physical verification counts and adjustments."),
    ]
    wf3_data = [[Paragraph(s[0], table_cell_bold), Paragraph(s[1], table_cell_style)] for s in wf3_steps]
    wf3_table = Table([[Paragraph("Workflow Step", table_header_style), Paragraph("Action & Operational Description", table_header_style)]] + wf3_data, colWidths=[50 * mm, 130 * mm])
    wf3_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_navy_light),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_bg_alt]),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    story.append(wf3_table)

    story.append(Spacer(1, 4 * mm))

    # Workflow 4
    story.append(Paragraph("3.4 Workflow: PWA Installation & Offline Operation", h2_style))
    wf4_steps = [
        ("Step 1: App Installation", "Open JewelDesk in Chrome, Edge, or Safari. Click the 'Install JewelDesk' button in the sidebar or the browser address bar install icon. The app installs to your desktop or mobile home screen as a standalone application."),
        ("Step 2: Offline Resilience", "If the showroom Wi-Fi or internet connection drops: JewelDesk automatically intercepts navigation requests via its Service Worker."),
        ("Step 3: Offline Screen & Data Safety", "Displays a dedicated, branded Offline page reassuring staff that existing data is safe, and provides a 'Retry Connection' button."),
        ("Step 4: Automatic Reconnection", "As soon as Wi-Fi/mobile internet reconnects, the application detects the <code>online</code> event and automatically refreshes to resume full operations."),
    ]
    wf4_data = [[Paragraph(s[0], table_cell_bold), Paragraph(s[1], table_cell_style)] for s in wf4_steps]
    wf4_table = Table([[Paragraph("Workflow Step", table_header_style), Paragraph("Action & Operational Description", table_header_style)]] + wf4_data, colWidths=[50 * mm, 130 * mm])
    wf4_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_navy_light),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_bg_alt]),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    story.append(wf4_table)

    story.append(Spacer(1, 6 * mm))

    # ==================================================================
    # 5. SECTION 4: MASTER URL ENDPOINTS & PERMISSIONS DIRECTORY
    # ==================================================================
    story.append(Paragraph("4. Master URL Endpoints & Permissions Directory", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=c_gold, spaceBefore=2, spaceAfter=8))

    endpoints_data = [
        [Paragraph("URL Pattern", table_header_style), Paragraph("HTTP", table_header_style), Paragraph("Module / View Function", table_header_style), Paragraph("Access Role", table_header_style)],
        [Paragraph("<code>/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>inventory.views.dashboard</code>", table_cell_style), Paragraph("Authenticated Staff", table_cell_style)],
        [Paragraph("<code>/inventory/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>inventory.views.inventory_list</code>", table_cell_style), Paragraph("Inventory View", table_cell_style)],
        [Paragraph("<code>/inventory/add/</code>", table_cell_bold), Paragraph("GET, POST", table_cell_style), Paragraph("<code>inventory.views.inventory_add</code>", table_cell_style), Paragraph("Inventory Add", table_cell_style)],
        [Paragraph("<code>/inventory/import/</code>", table_cell_bold), Paragraph("GET, POST", table_cell_style), Paragraph("<code>inventory.views.inventory_import</code>", table_cell_style), Paragraph("Inventory Add", table_cell_style)],
        [Paragraph("<code>/pricing/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>inventory.views.pricing_calculator</code>", table_cell_style), Paragraph("Pricing View", table_cell_style)],
        [Paragraph("<code>/pricing/api/calculate/</code>", table_cell_bold), Paragraph("POST", table_cell_style), Paragraph("<code>inventory.views.api_calculate_price</code>", table_cell_style), Paragraph("Authenticated", table_cell_style)],
        [Paragraph("<code>/sales/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>sales.views.sale_list</code>", table_cell_style), Paragraph("Sales View", table_cell_style)],
        [Paragraph("<code>/sales/add/</code>", table_cell_bold), Paragraph("GET, POST", table_cell_style), Paragraph("<code>sales.views.sale_create</code>", table_cell_style), Paragraph("Sales Add", table_cell_style)],
        [Paragraph("<code>/sales/&lt;id&gt;/pdf/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>sales.views.sale_invoice_pdf</code>", table_cell_style), Paragraph("Sales View", table_cell_style)],
        [Paragraph("<code>/sales/report/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>sales.views.sales_report</code>", table_cell_style), Paragraph("Sales View", table_cell_style)],
        [Paragraph("<code>/old-gold/exchange/</code>", table_cell_bold), Paragraph("GET, POST", table_cell_style), Paragraph("<code>sales.views.old_gold_exchange_create</code>", table_cell_style), Paragraph("Sales Add", table_cell_style)],
        [Paragraph("<code>/customers/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>customers.views.customer_list</code>", table_cell_style), Paragraph("Customers View", table_cell_style)],
        [Paragraph("<code>/custom-orders/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>custom_orders.views.custom_order_list</code>", table_cell_style), Paragraph("Orders View", table_cell_style)],
        [Paragraph("<code>/karigar/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>karigar.views.dashboard</code>", table_cell_style), Paragraph("Karigar View", table_cell_style)],
        [Paragraph("<code>/karigar/assignments/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>karigar.views.assignment_list</code>", table_cell_style), Paragraph("Karigar View", table_cell_style)],
        [Paragraph("<code>/team/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>team.views.employee_list</code>", table_cell_style), Paragraph("Team View", table_cell_style)],
        [Paragraph("<code>/accounts/company-settings/</code>", table_cell_bold), Paragraph("GET, POST", table_cell_style), Paragraph("<code>accounts.views.company_settings</code>", table_cell_style), Paragraph("Store Admin", table_cell_style)],
        [Paragraph("<code>/manifest.json</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>config.pwa_views.manifest_view</code>", table_cell_style), Paragraph("Public", table_cell_style)],
        [Paragraph("<code>/sw.js</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>config.pwa_views.service_worker_view</code>", table_cell_style), Paragraph("Public", table_cell_style)],
        [Paragraph("<code>/offline/</code>", table_cell_bold), Paragraph("GET", table_cell_style), Paragraph("<code>config.pwa_views.offline_view</code>", table_cell_style), Paragraph("Public", table_cell_style)],
    ]
    endpoints_table = Table(endpoints_data, colWidths=[48 * mm, 18 * mm, 68 * mm, 46 * mm])
    endpoints_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_navy_light),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_bg_alt]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(endpoints_table)

    story.append(PageBreak())

    # ==================================================================
    # 6. SECTION 5: DEPLOYMENT & PRODUCTION READINESS
    # ==================================================================
    story.append(Paragraph("5. Deployment, Security & Production Readiness", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=c_gold, spaceBefore=2, spaceAfter=8))

    deploy_summary = """
    <b>PRODUCTION DEPLOYMENT CHECKLIST & ENVIRONMENT CONFIGURATION:</b><br/>
    JewelDesk is designed to run in production with complete security and high availability.
    <br/><br/>
    • <b>Database Storage:</b>
    During local development, SQLite (<code>db.sqlite3</code>) is used. In production, configure the <code>DATABASE_URL</code> environment variable to point to PostgreSQL (Supabase, Neon, AWS RDS, or standard PostgreSQL). Supabase transaction pooler compatibility is pre-configured with <code>DISABLE_SERVER_SIDE_CURSORS = True</code> and SSL enforcement.
    <br/><br/>
    • <b>Static Assets & WhiteNoise:</b>
    Static assets are served via WhiteNoise with <code>CompressedStaticFilesStorage</code> for automatic gzip/brotli compression and long-term browser cache headers. Run <code>python manage.py collectstatic --noinput</code> during deployment.
    <br/><br/>
    • <b>Email Dispatch:</b>
    Password reset and system alerts support SMTP (SendGrid, Mailgun, Amazon SES, or Gmail) via <code>EMAIL_HOST</code>, <code>EMAIL_PORT</code>, <code>EMAIL_HOST_USER</code>, and <code>EMAIL_HOST_PASSWORD</code>.
    <br/><br/>
    • <b>Live Bullion Rate API:</b>
    Set <code>JEWELDESK_METAL_PRICE_API_URL</code> and <code>JEWELDESK_METAL_PRICE_API_KEY</code> to enable automated daily metal rates fetch.
    <br/><br/>
    • <b>Security Hardening:</b>
    In production set <code>DEBUG = False</code>, configure <code>ALLOWED_HOSTS</code>, set <code>CSRF_COOKIE_SECURE = True</code>, <code>SESSION_COOKIE_SECURE = True</code>, and enable HTTPS enforcement.
    """
    deploy_card = Table([[Paragraph(deploy_summary, callout_style)]], colWidths=[180 * mm])
    deploy_card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 1, c_navy_light),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(deploy_card)
    story.append(Spacer(1, 6 * mm))

    # Concluding Sign-off Card
    sign_off_html = """
    <b>SUMMARY CONCLUSION:</b><br/>
    JewelDesk is fully functional, robustly tested, and features a production-grade responsive UI and PWA architecture.
    All business calculations, inventory tracking, hallmark compliances, PDF invoice rendering, artisan metal auditing,
    and security barriers are verified and operational.
    <br/><br/>
    <i>Generated on behalf of JewelDesk Retail Management System.</i>
    """
    sign_off_card = Table([[Paragraph(sign_off_html, callout_style)]], colWidths=[180 * mm])
    sign_off_card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fef9c3')),
        ('BOX', (0, 0), (-1, -1), 1, c_gold),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(sign_off_card)

    # Build the document using NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Report successfully compiled into: {output_filename}")


if __name__ == '__main__':
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_pdf = os.path.join(project_root, 'JewelDesk_Complete_Project_Report.pdf')
    generate_pdf_report(target_pdf)
