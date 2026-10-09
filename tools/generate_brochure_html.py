#!/usr/bin/env python3
"""
tools/generate_brochure_html.py
-------------------------------
Generates a customer-friendly, professional, print-ready A4 brochure (HTML + CSS)
for JewelDesk — Jewellery Retail Management Software.
Strictly follows the prompt requirements, brand guidelines, and verified codebase features.
"""

import os
import sys
import base64
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def load_b64(path):
    if not path.exists():
        return ""
    with open(path, "rb") as f:
        ext = path.suffix.lower().replace(".", "")
        if ext == "jpg":
            ext = "jpeg"
        return f"data:image/{ext};base64," + base64.b64encode(f.read()).decode("utf-8")

def main():
    brochure_dir = BASE_DIR / "brochure"
    brochure_dir.mkdir(parents=True, exist_ok=True)
    html_path = brochure_dir / "jeweldesk_brochure.html"

    # Assets
    logo_b64 = load_b64(BASE_DIR / "static" / "images" / "branding" / "company_logo.png")
    if not logo_b64:
        logo_b64 = load_b64(BASE_DIR / "static" / "images" / "branding" / "logo.png")
    
    icon_b64 = load_b64(BASE_DIR / "static" / "icons" / "icon-192x192.png")
    dash_b64 = load_b64(BASE_DIR / "static" / "images" / "brochure" / "screenshot_dashboard.png")
    inv_b64 = load_b64(BASE_DIR / "static" / "images" / "brochure" / "screenshot_inventory.png")
    pos_b64 = load_b64(BASE_DIR / "static" / "images" / "brochure" / "screenshot_pos_sale.png")
    rep_b64 = load_b64(BASE_DIR / "static" / "images" / "brochure" / "screenshot_reports.png")

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JewelDesk — Customer Product Brochure</title>
    <!-- Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600;700;800&family=Outfit:wght@300;400;500;600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">

    <style>
        /* =============================================================
           EXACT A4 PORTRAIT PRINT & LAYOUT SPECIFICATIONS
           ============================================================= */
        @page {{
            size: A4 portrait;
            margin: 0;
        }}

        :root {{
            --bg-ivory: #FAF8F5;
            --bg-ivory-light: #FFFDF9;
            --bg-card: #FFFFFF;
            --charcoal-900: #15130E;
            --charcoal-800: #221C14;
            --charcoal-700: #332C22;
            --charcoal-600: #4A4033;
            --charcoal-500: #665C4E;
            --text-dark: #1E1A14;
            --text-muted: #6B6255;
            --text-light: #F5EFEB;
            --gold-primary: #C59B27;
            --gold-bright: #D4AF37;
            --gold-light: #F7E7B4;
            --gold-soft-bg: rgba(197, 155, 39, 0.08);
            --gold-border: rgba(197, 155, 39, 0.28);
            --border-light: #E8E2D8;
            --shadow-subtle: 0 4px 16px rgba(21, 19, 14, 0.06);
            --shadow-card: 0 8px 24px rgba(21, 19, 14, 0.08);
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
        }}

        body {{
            font-family: 'Outfit', 'Plus Jakarta Sans', -apple-system, sans-serif;
            background-color: #0E0C09;
            color: var(--text-dark);
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }}

        /* On-Screen Container */
        @media screen {{
            body {{
                padding: 30px 15px 80px 15px;
                background: #0E0C09;
            }}
            .brochure-container {{
                display: flex;
                flex-direction: column;
                gap: 36px;
                align-items: center;
                max-width: 210mm;
                margin: 0 auto;
            }}
            .brochure-page {{
                box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7), 0 0 0 1px rgba(197, 155, 39, 0.25);
            }}
            .screen-controls {{
                position: fixed;
                bottom: 24px;
                right: 24px;
                background: rgba(21, 19, 14, 0.94);
                backdrop-filter: blur(12px);
                border: 1px solid rgba(197, 155, 39, 0.45);
                border-radius: 40px;
                padding: 10px 20px;
                display: flex;
                gap: 14px;
                align-items: center;
                z-index: 9999;
                box-shadow: 0 12px 36px rgba(0, 0, 0, 0.6);
            }}
            .screen-controls .tag {{
                color: var(--gold-light);
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0.5px;
            }}
            .screen-controls button {{
                background: linear-gradient(135deg, #D4AF37 0%, #C59B27 100%);
                color: #15130E;
                border: none;
                font-family: 'Outfit', sans-serif;
                font-weight: 700;
                font-size: 13px;
                padding: 8px 18px;
                border-radius: 24px;
                cursor: pointer;
                transition: all 0.2s;
                display: flex;
                align-items: center;
                gap: 6px;
            }}
            .screen-controls button:hover {{
                transform: translateY(-1px);
                box-shadow: 0 4px 15px rgba(212, 175, 55, 0.4);
            }}
            .screen-controls .view-btn {{
                background: rgba(255, 255, 255, 0.08);
                color: #FAF8F5;
                border: 1px solid rgba(255, 255, 255, 0.15);
            }}
            .screen-controls .view-btn:hover {{
                background: rgba(255, 255, 255, 0.15);
            }}
        }}

        @media print {{
            .screen-controls {{
                display: none !important;
            }}
            body {{
                background: transparent;
                padding: 0;
            }}
            .brochure-container {{
                gap: 0;
            }}
            .brochure-page {{
                box-shadow: none !important;
                border: none !important;
            }}
        }}

        /* Exact A4 Portrait Page Dimensions */
        .brochure-page {{
            width: 210mm;
            height: 297mm;
            min-height: 297mm;
            max-height: 297mm;
            position: relative;
            overflow: hidden;
            page-break-after: always;
            break-after: page;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            padding: 14mm 16mm 12mm 16mm;
            background-color: var(--bg-ivory);
            color: var(--text-dark);
        }}

        /* Page Background Variants */
        .page-theme-dark {{
            background: radial-gradient(circle at 85% 15%, rgba(197, 155, 39, 0.15) 0%, transparent 45%),
                        radial-gradient(circle at 10% 85%, rgba(212, 175, 55, 0.1) 0%, transparent 40%),
                        var(--charcoal-900);
            color: var(--text-light);
        }}

        .page-theme-ivory {{
            background: linear-gradient(180deg, #FFFDF9 0%, #FAF8F5 50%, #F5F0E8 100%);
            color: var(--text-dark);
        }}

        /* -------------------------------------------------------------
           SHARED RUNNING HEADER & FOOTER
           ------------------------------------------------------------- */
        .page-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--gold-border);
            padding-bottom: 2.8mm;
            margin-bottom: 4mm;
            flex-shrink: 0;
        }}
        .page-theme-ivory .page-header {{
            border-bottom: 1px solid rgba(197, 155, 39, 0.25);
        }}

        .header-brand {{
            display: flex;
            align-items: center;
            gap: 9px;
        }}
        .header-brand img {{
            height: 22px;
            width: auto;
            object-fit: contain;
        }}
        .header-brand-title {{
            font-family: 'Cinzel', serif;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 1px;
            color: var(--gold-primary);
        }}
        .header-category {{
            font-size: 9.5px;
            text-transform: uppercase;
            letter-spacing: 1.2px;
            font-weight: 600;
            color: var(--text-muted);
            padding-left: 8px;
            border-left: 1px solid var(--border-light);
        }}
        .page-theme-dark .header-category {{
            color: #A39686;
            border-left-color: rgba(255, 255, 255, 0.15);
        }}

        .header-badge {{
            font-size: 9.5px;
            font-weight: 700;
            letter-spacing: 1px;
            text-transform: uppercase;
            padding: 3px 10px;
            border-radius: 20px;
            background: var(--gold-soft-bg);
            color: var(--gold-primary);
            border: 1px solid var(--gold-border);
        }}
        .page-theme-dark .header-badge {{
            background: rgba(212, 175, 55, 0.12);
            color: var(--gold-light);
            border-color: rgba(212, 175, 55, 0.35);
        }}

        .page-footer {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-top: 1px solid rgba(197, 155, 39, 0.2);
            padding-top: 2.8mm;
            margin-top: 3.5mm;
            flex-shrink: 0;
            font-size: 9.5px;
            color: var(--text-muted);
        }}
        .page-theme-dark .page-footer {{
            border-top-color: rgba(255, 255, 255, 0.1);
            color: #8C8072;
        }}
        .footer-tagline {{
            font-weight: 500;
            letter-spacing: 0.3px;
        }}
        .footer-page-num {{
            font-weight: 700;
            color: var(--gold-primary);
            font-size: 10px;
        }}

        /* -------------------------------------------------------------
           TYPOGRAPHY & UTILITIES
           ------------------------------------------------------------- */
        .gold-text {{
            color: var(--gold-primary);
        }}
        .gold-gradient-text {{
            background: linear-gradient(135deg, #F3E5BE 0%, #D4AF37 50%, #B89230 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .section-eyebrow {{
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 1.8px;
            font-weight: 700;
            color: var(--gold-primary);
            margin-bottom: 1.5mm;
            display: inline-block;
        }}
        .page-theme-dark .section-eyebrow {{
            color: var(--gold-bright);
        }}

        .page-headline {{
            font-family: 'Cinzel', serif;
            font-size: 21px;
            font-weight: 700;
            letter-spacing: 0.5px;
            line-height: 1.25;
            color: var(--charcoal-900);
            margin-bottom: 2mm;
        }}
        .page-theme-dark .page-headline {{
            color: #FAF8F5;
        }}

        .page-intro {{
            font-size: 11.5px;
            color: var(--charcoal-600);
            line-height: 1.5;
            margin-bottom: 3.5mm;
        }}
        .page-theme-dark .page-intro {{
            color: #B5A898;
        }}

        /* Highlight banner */
        .highlight-banner {{
            background: var(--gold-soft-bg);
            border-left: 3px solid var(--gold-primary);
            border-radius: 0 6px 6px 0;
            padding: 2.8mm 4mm;
            font-size: 11.5px;
            font-weight: 600;
            color: var(--charcoal-800);
            line-height: 1.45;
            margin-bottom: 4mm;
        }}
        .page-theme-dark .highlight-banner {{
            background: rgba(212, 175, 55, 0.1);
            color: #F8F5EE;
            border-left-color: var(--gold-bright);
        }}

        /* -------------------------------------------------------------
           PAGE 1: COVER SPECIFICS
           ------------------------------------------------------------- */
        .cover-wrapper {{
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            flex-grow: 1;
            padding-top: 4mm;
        }}
        .cover-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .cover-badge-pill {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(212, 175, 55, 0.12);
            border: 1px solid rgba(212, 175, 55, 0.35);
            padding: 4px 12px;
            border-radius: 30px;
            font-size: 10px;
            font-weight: 700;
            color: var(--gold-light);
            letter-spacing: 1.2px;
            text-transform: uppercase;
        }}

        .cover-hero-text {{
            text-align: center;
            margin-top: 4mm;
            margin-bottom: 4mm;
        }}
        .cover-logo-img {{
            height: 52px;
            width: auto;
            object-fit: contain;
            margin-bottom: 3.5mm;
            filter: drop-shadow(0 4px 12px rgba(212, 175, 55, 0.3));
        }}
        .cover-title {{
            font-family: 'Cinzel', serif;
            font-size: 38px;
            font-weight: 800;
            letter-spacing: 2px;
            line-height: 1.1;
            margin-bottom: 2mm;
        }}
        .cover-subtitle {{
            font-family: 'Outfit', sans-serif;
            font-size: 18px;
            font-weight: 600;
            color: var(--gold-bright);
            letter-spacing: 0.8px;
            margin-bottom: 3.5mm;
        }}
        .cover-lead {{
            font-size: 13px;
            color: #D6CCC0;
            max-width: 145mm;
            margin: 0 auto 3mm auto;
            line-height: 1.55;
            font-weight: 400;
        }}
        .cover-lead strong {{
            color: #FFFFFF;
        }}
        .cover-tagline-box {{
            display: inline-block;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(212, 175, 55, 0.25);
            border-radius: 30px;
            padding: 4px 16px;
            font-size: 11px;
            font-weight: 600;
            color: var(--gold-light);
            letter-spacing: 0.5px;
        }}

        .cover-mockup-container {{
            position: relative;
            margin: 3mm 0 4mm 0;
            border-radius: 10px;
            overflow: hidden;
            border: 1.5px solid rgba(212, 175, 55, 0.4);
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.7), 0 0 30px rgba(197, 155, 39, 0.15);
            background: #11151F;
        }}
        .mockup-window-bar {{
            background: #1A1F2D;
            padding: 4px 10px;
            display: flex;
            align-items: center;
            gap: 6px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }}
        .mockup-dot {{
            width: 7px;
            height: 7px;
            border-radius: 50%;
        }}
        .dot-red {{ background: #EF4444; }}
        .dot-yellow {{ background: #F59E0B; }}
        .dot-green {{ background: #10B981; }}
        .mockup-title {{
            font-size: 9px;
            color: #94A3B8;
            margin-left: 6px;
            font-family: monospace;
        }}
        .cover-mockup-img {{
            width: 100%;
            height: auto;
            display: block;
        }}

        .cover-highlights-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 2.5mm;
            margin-top: 1mm;
        }}
        .cover-highlight-pill {{
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(212, 175, 55, 0.2);
            border-radius: 6px;
            padding: 2.8mm 3mm;
            text-align: center;
        }}
        .cover-highlight-pill strong {{
            display: block;
            font-size: 11px;
            color: #FFFFFF;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 1px;
        }}
        .cover-highlight-pill span {{
            font-size: 9px;
            color: #A39686;
        }}

        /* -------------------------------------------------------------
           PAGE 2: WHY & WHAT (STORY & PHILOSOPHY)
           ------------------------------------------------------------- */
        .story-container {{
            display: flex;
            flex-direction: column;
            gap: 3.5mm;
            flex-grow: 1;
        }}
        .story-box {{
            background: var(--bg-card);
            border: 1px solid var(--border-light);
            border-radius: 8px;
            padding: 3.8mm 5mm;
            box-shadow: var(--shadow-subtle);
        }}
        .story-box-title {{
            font-family: 'Cinzel', serif;
            font-size: 14.5px;
            font-weight: 700;
            color: var(--charcoal-900);
            margin-bottom: 2mm;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .story-box-title .badge-icon {{
            width: 22px;
            height: 22px;
            border-radius: 5px;
            background: var(--gold-soft-bg);
            color: var(--gold-primary);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 800;
        }}
        .story-p {{
            font-size: 11.2px;
            color: var(--charcoal-600);
            line-height: 1.55;
            margin-bottom: 2mm;
        }}
        .story-p:last-child {{
            margin-bottom: 0;
        }}
        .story-keynote {{
            background: #FAF7F0;
            border-left: 3px solid var(--gold-primary);
            padding: 2.2mm 3.5mm;
            border-radius: 0 5px 5px 0;
            font-size: 11px;
            font-weight: 600;
            color: var(--charcoal-900);
            margin-top: 2mm;
        }}

        .pillars-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 3mm;
            margin-top: 1mm;
        }}
        .pillar-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-light);
            border-radius: 8px;
            padding: 3.5mm 4mm;
            box-shadow: var(--shadow-subtle);
            display: flex;
            flex-direction: column;
            gap: 1.5mm;
        }}
        .pillar-header {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .pillar-num {{
            font-family: monospace;
            font-size: 10px;
            font-weight: 800;
            color: var(--gold-primary);
            background: var(--gold-soft-bg);
            padding: 2px 7px;
            border-radius: 4px;
            border: 1px solid var(--gold-border);
        }}
        .pillar-title {{
            font-size: 12px;
            font-weight: 700;
            color: var(--charcoal-900);
        }}
        .pillar-desc {{
            font-size: 10.3px;
            color: var(--charcoal-500);
            line-height: 1.45;
        }}

        /* -------------------------------------------------------------
           PAGE 3 & 4: HOW JEWELDESK CAN HELP YOUR SHOP (FEATURES)
           ------------------------------------------------------------- */
        .features-grid-3 {{
            display: flex;
            flex-direction: column;
            gap: 2.8mm;
            flex-grow: 1;
        }}
        .feat-item-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-light);
            border-radius: 8px;
            padding: 3mm 4.5mm;
            box-shadow: var(--shadow-subtle);
            display: flex;
            gap: 4mm;
            align-items: flex-start;
        }}
        .feat-item-card:hover {{
            border-color: var(--gold-primary);
        }}
        .feat-icon-col {{
            width: 28px;
            height: 28px;
            border-radius: 6px;
            background: var(--gold-soft-bg);
            border: 1px solid var(--gold-border);
            color: var(--gold-primary);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: 800;
            flex-shrink: 0;
            margin-top: 1px;
        }}
        .feat-content-col {{
            flex: 1;
        }}
        .feat-title-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.2mm;
        }}
        .feat-heading {{
            font-size: 12.5px;
            font-weight: 700;
            color: var(--charcoal-900);
        }}
        .feat-tag {{
            font-size: 8.5px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--gold-primary);
            background: #FDF9EE;
            padding: 2px 7px;
            border-radius: 12px;
            border: 1px solid rgba(197, 155, 39, 0.2);
        }}
        .feat-problem-box {{
            background: #FFF7F5;
            border-left: 2.5px solid #E05252;
            padding: 1.8mm 3mm;
            border-radius: 0 4px 4px 0;
            font-size: 10px;
            color: #7A2E2E;
            line-height: 1.4;
            margin-bottom: 1.5mm;
        }}
        .feat-problem-box strong {{
            color: #B91C1C;
            text-transform: uppercase;
            font-size: 8.5px;
            letter-spacing: 0.5px;
            display: block;
            margin-bottom: 0.5px;
        }}
        .feat-benefit-box {{
            background: #F4FAF6;
            border-left: 2.5px solid #10B981;
            padding: 1.8mm 3mm;
            border-radius: 0 4px 4px 0;
            font-size: 10.2px;
            color: #1A5336;
            line-height: 1.4;
        }}
        .feat-benefit-box strong {{
            color: #047857;
            text-transform: uppercase;
            font-size: 8.5px;
            letter-spacing: 0.5px;
            display: block;
            margin-bottom: 0.5px;
        }}

        .ui-visual-strip {{
            background: var(--bg-card);
            border: 1px solid var(--border-light);
            border-radius: 8px;
            padding: 2.5mm 3.5mm;
            box-shadow: var(--shadow-subtle);
            display: flex;
            align-items: center;
            gap: 4mm;
            margin-top: 1mm;
        }}
        .ui-visual-img {{
            width: 75mm;
            height: auto;
            border-radius: 6px;
            border: 1px solid var(--border-light);
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.08);
            display: block;
        }}
        .ui-visual-text {{
            flex: 1;
        }}
        .ui-visual-title {{
            font-size: 11px;
            font-weight: 700;
            color: var(--charcoal-900);
            margin-bottom: 1mm;
        }}
        .ui-visual-desc {{
            font-size: 9.8px;
            color: var(--charcoal-500);
            line-height: 1.4;
        }}

        /* -------------------------------------------------------------
           PAGE 5: COMPARISON & AUDIENCE
           ------------------------------------------------------------- */
        .comparison-table-wrapper {{
            background: var(--bg-card);
            border: 1px solid var(--border-light);
            border-radius: 8px;
            padding: 3.5mm 4.5mm;
            box-shadow: var(--shadow-subtle);
            margin-bottom: 3.5mm;
        }}
        .comp-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 4mm;
        }}
        .comp-col {{
            border-radius: 6px;
            padding: 3mm 3.5mm;
        }}
        .comp-col-before {{
            background: #FFF9F8;
            border: 1px solid #FCDAD7;
        }}
        .comp-col-after {{
            background: #F6FAF7;
            border: 1px solid #CDE8D8;
        }}
        .comp-header {{
            font-size: 11.5px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            margin-bottom: 2mm;
            padding-bottom: 1.5mm;
            border-bottom: 1px dashed;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .comp-col-before .comp-header {{
            color: #B91C1C;
            border-bottom-color: #F8B4AF;
        }}
        .comp-col-after .comp-header {{
            color: #047857;
            border-bottom-color: #A3D9B9;
        }}
        .comp-list {{
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 1.8mm;
        }}
        .comp-list-item {{
            display: flex;
            align-items: flex-start;
            gap: 6px;
            font-size: 10.3px;
            line-height: 1.4;
        }}
        .comp-bullet {{
            font-weight: 800;
            font-size: 11px;
            line-height: 1;
            margin-top: 1px;
            flex-shrink: 0;
        }}
        .comp-col-before .comp-bullet {{ color: #EF4444; }}
        .comp-col-after .comp-bullet {{ color: #10B981; }}

        .honest-note {{
            font-size: 9.8px;
            color: var(--charcoal-500);
            text-align: center;
            margin-top: 2mm;
            font-style: italic;
        }}

        /* Who Can Benefit Cards */
        .audience-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 2.8mm;
            flex-grow: 1;
        }}
        .audience-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-light);
            border-radius: 7px;
            padding: 3mm 3.8mm;
            box-shadow: var(--shadow-subtle);
            display: flex;
            gap: 8px;
            align-items: flex-start;
        }}
        .audience-icon {{
            width: 24px;
            height: 24px;
            border-radius: 5px;
            background: var(--gold-soft-bg);
            border: 1px solid var(--gold-border);
            color: var(--gold-primary);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 700;
            flex-shrink: 0;
            margin-top: 1px;
        }}
        .audience-title {{
            font-size: 11.5px;
            font-weight: 700;
            color: var(--charcoal-900);
            margin-bottom: 0.8mm;
            line-height: 1.25;
        }}
        .audience-desc {{
            font-size: 9.8px;
            color: var(--charcoal-500);
            line-height: 1.4;
        }}

        /* -------------------------------------------------------------
           PAGE 6: VALUE & CLOSING PAGE
           ------------------------------------------------------------- */
        .value-hero-box {{
            background: linear-gradient(135deg, var(--charcoal-900) 0%, var(--charcoal-800) 100%);
            border: 1.5px solid var(--gold-primary);
            border-radius: 10px;
            padding: 5mm 6mm;
            color: #FFFFFF;
            text-align: center;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
            margin-bottom: 4mm;
        }}
        .value-tagline {{
            font-family: 'Cinzel', serif;
            font-size: 16px;
            font-weight: 700;
            color: var(--gold-bright);
            letter-spacing: 0.5px;
            margin-bottom: 2.5mm;
            line-height: 1.35;
        }}
        .value-text {{
            font-size: 11.2px;
            color: #D6CCC0;
            line-height: 1.6;
            max-width: 150mm;
            margin: 0 auto;
        }}

        .workflow-steps-box {{
            background: var(--bg-card);
            border: 1px solid var(--border-light);
            border-radius: 8px;
            padding: 3.5mm 5mm;
            box-shadow: var(--shadow-subtle);
            margin-bottom: 4mm;
        }}
        .wf-box-title {{
            font-family: 'Cinzel', serif;
            font-size: 13.5px;
            font-weight: 700;
            color: var(--charcoal-900);
            margin-bottom: 2.5mm;
            text-align: center;
        }}
        .steps-flex {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 3mm;
        }}
        .step-item {{
            background: #FAF8F4;
            border: 1px solid var(--border-light);
            border-radius: 6px;
            padding: 3mm 3.2mm;
            text-align: center;
        }}
        .step-circle {{
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: var(--gold-primary);
            color: #FFFFFF;
            font-size: 10px;
            font-weight: 800;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 1.5mm auto;
        }}
        .step-item strong {{
            display: block;
            font-size: 11px;
            color: var(--charcoal-900);
            margin-bottom: 1mm;
            line-height: 1.25;
        }}
        .step-item p {{
            font-size: 9.6px;
            color: var(--charcoal-500);
            line-height: 1.4;
        }}

        /* Contact Details Section */
        .closing-contact-card {{
            background: var(--bg-card);
            border: 1.5px solid var(--gold-primary);
            border-radius: 9px;
            padding: 4mm 5.5mm;
            box-shadow: var(--shadow-card);
        }}
        .contact-card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-light);
            padding-bottom: 2.5mm;
            margin-bottom: 3mm;
        }}
        .contact-brand-title {{
            font-family: 'Cinzel', serif;
            font-size: 16px;
            font-weight: 700;
            color: var(--charcoal-900);
            letter-spacing: 0.5px;
        }}
        .contact-brand-tag {{
            font-size: 10px;
            font-weight: 600;
            color: var(--gold-primary);
        }}
        .contact-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 3mm;
            margin-bottom: 3mm;
        }}
        .contact-cell {{
            background: #FAF8F5;
            border: 1px solid var(--border-light);
            border-radius: 6px;
            padding: 2.5mm 3.5mm;
        }}
        .contact-label {{
            font-size: 8px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            font-weight: 700;
            color: var(--gold-primary);
            margin-bottom: 1px;
            display: block;
        }}
        .contact-val {{
            font-size: 11px;
            font-weight: 600;
            color: var(--charcoal-900);
            font-family: 'Outfit', sans-serif;
            word-break: break-word;
        }}
        .contact-address-box {{
            background: #FAF8F5;
            border: 1px solid var(--border-light);
            border-radius: 6px;
            padding: 2.5mm 3.5mm;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .contact-address-text {{
            font-size: 10px;
            color: var(--charcoal-600);
            line-height: 1.4;
        }}
        .contact-demo-badge {{
            font-size: 9.5px;
            font-weight: 700;
            background: var(--gold-soft-bg);
            border: 1px solid var(--gold-border);
            color: var(--gold-primary);
            padding: 3px 10px;
            border-radius: 20px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
        }}

    </style>
</head>
<body>

    <!-- On-screen Floating Control Bar -->
    <div class="screen-controls">
        <span class="tag">JewelDesk Customer Brochure • 6 Pages (A4)</span>
        <button onclick="window.print()">📥 Print / Save as PDF</button>
        <button class="view-btn" onclick="window.location.href='/download-brochure/'">📄 Download Official PDF</button>
    </div>

    <div class="brochure-container">

        <!-- =========================================================
             PAGE 1: COVER PAGE
             ========================================================= -->
        <section class="brochure-page page-theme-dark page-1">
            <header class="cover-top">
                <div class="header-brand">
                    <img src="{icon_b64}" alt="JewelDesk Icon" style="height: 26px; width: 26px; border-radius: 6px;">
                    <span class="header-brand-title" style="color: #FFFFFF;">JewelDesk</span>
                </div>
                <div class="cover-badge-pill">
                    Jewellery Retail Management Software
                </div>
            </header>

            <div class="cover-wrapper">
                <div class="cover-hero-text">
                    <img src="{logo_b64}" alt="JewelDesk Logo" class="cover-logo-img">
                    <h1 class="cover-title gold-gradient-text">JewelDesk</h1>
                    <div class="cover-subtitle">Your Jewellery Business, Simplified.</div>
                    <p class="cover-lead">
                        Manage your <strong>jewellery stock</strong>, <strong>sales</strong>, <strong>customers</strong> and <strong>business records</strong> in one organized place.
                    </p>
                    <div class="cover-tagline-box">
                        ✨ A smarter way to manage your jewellery shop.
                    </div>
                </div>

                <!-- Software Interface Mockup -->
                <div class="cover-mockup-container">
                    <div class="mockup-window-bar">
                        <span class="mockup-dot dot-red"></span>
                        <span class="mockup-dot dot-yellow"></span>
                        <span class="mockup-dot dot-green"></span>
                        <span class="mockup-title">JewelDesk — Showroom Management Overview</span>
                    </div>
                    <img src="{dash_b64}" alt="JewelDesk Dashboard Interface" class="cover-mockup-img">
                </div>

                <!-- Highlights Bar -->
                <div class="cover-highlights-grid">
                    <div class="cover-highlight-pill">
                        <strong>Jewellery Stock</strong>
                        <span>Gold, Silver & Purity</span>
                    </div>
                    <div class="cover-highlight-pill">
                        <strong>Fast POS Billing</strong>
                        <span>Clean Tax Invoices</span>
                    </div>
                    <div class="cover-highlight-pill">
                        <strong>Bullion Rates</strong>
                        <span>Daily Rate Setting</span>
                    </div>
                    <div class="cover-highlight-pill">
                        <strong>Customer Records</strong>
                        <span>WhatsApp Follow-ups</span>
                    </div>
                </div>
            </div>

            <footer class="page-footer">
                <span class="footer-tagline">JewelDesk — Commercial Product Brochure</span>
                <span class="footer-page-num">Page 1 of 6</span>
            </footer>
        </section>


        <!-- =========================================================
             PAGE 2: WHY WAS JEWELDESK CREATED? & WHAT IS JEWELDESK?
             ========================================================= -->
        <section class="brochure-page page-theme-ivory page-2">
            <header class="page-header">
                <div class="header-brand">
                    <img src="{logo_b64}" alt="JewelDesk Logo">
                    <span class="header-brand-title">JewelDesk</span>
                    <span class="header-category">Retail Management</span>
                </div>
                <div class="header-badge">The Background & Purpose</div>
            </header>

            <div class="story-container">
                <!-- Section 2: Why was it created? -->
                <div class="story-box">
                    <div class="section-eyebrow">Understanding The Shop Owner's Journey</div>
                    <h2 class="story-box-title">
                        <span class="badge-icon">1</span>
                        Why Was JewelDesk Created?
                    </h2>
                    <p class="story-p">
                        Running a jewellery shop involves much more than just selling jewellery. Every day, shop owners need to manage ornaments in trays, calculate prices based on shifting metal rates, prepare customer bills, maintain customer records, track payments, and understand their shop's financial performance.
                    </p>
                    <p class="story-p">
                        When information is scattered across handwritten registers, loose paper slips, mental calculations, or disconnected spreadsheets, daily work can become time-consuming, tiring, and confusing for both the owner and showroom staff.
                    </p>
                    <div class="story-keynote">
                        <strong>JewelDesk was created to help jewellery retailers manage their everyday business activities in a more organized and convenient way.</strong>
                    </div>
                </div>

                <!-- Section 3: What is JewelDesk? -->
                <div class="story-box">
                    <div class="section-eyebrow">The Simple Explanation</div>
                    <h2 class="story-box-title">
                        <span class="badge-icon">2</span>
                        What Is JewelDesk?
                    </h2>
                    <p class="story-p">
                        JewelDesk is jewellery retail management software that brings important shop-management activities together in one place. Instead of managing business records separately across multiple registers, you can use JewelDesk to organize your inventory, record sales transactions, maintain customer details, and view useful business reports.
                    </p>
                    <div class="highlight-banner" style="margin-bottom: 2mm;">
                        💡 <strong>In simple words:</strong> JewelDesk helps you keep your jewellery business organized and gives you a clearer view of your shop's daily activities.
                    </div>
                </div>

                <!-- The 4 Core Pillars of JewelDesk -->
                <div class="section-eyebrow" style="margin-top: 1mm;">The 4 Core Pillars of Daily Shop Management</div>
                <div class="pillars-grid">
                    <div class="pillar-card">
                        <div class="pillar-header">
                            <span class="pillar-num">Pillar 1</span>
                            <span class="pillar-title">Organized Stock</span>
                        </div>
                        <p class="pillar-desc">
                            Record every jewellery piece with its category, metal, gross weight, net weight, purity, and hallmark identification.
                        </p>
                    </div>
                    <div class="pillar-card">
                        <div class="pillar-header">
                            <span class="pillar-num">Pillar 2</span>
                            <span class="pillar-title">Smooth Counter Sales</span>
                        </div>
                        <p class="pillar-desc">
                            Select items quickly, apply the day's metal rate and making charges transparently, and generate clean invoices.
                        </p>
                    </div>
                    <div class="pillar-card">
                        <div class="pillar-header">
                            <span class="pillar-num">Pillar 3</span>
                            <span class="pillar-title">Organized Customer Care</span>
                        </div>
                        <p class="pillar-desc">
                            Save customer contact details and purchase histories so you can serve returning families with familiarity.
                        </p>
                    </div>
                    <div class="pillar-card">
                        <div class="pillar-header">
                            <span class="pillar-num">Pillar 4</span>
                            <span class="pillar-title">Clear Business Visibility</span>
                        </div>
                        <p class="pillar-desc">
                            Review sales summaries and stock movements date-wise to know exactly how your showroom is performing.
                        </p>
                    </div>
                </div>
            </div>

            <footer class="page-footer">
                <span class="footer-tagline">JewelDesk — Designed for Indian Jewellery Retailers</span>
                <span class="footer-page-num">Page 2 of 6</span>
            </footer>
        </section>


        <!-- =========================================================
             PAGE 3: HOW JEWELDESK CAN HELP YOUR SHOP (PART 1)
             ========================================================= -->
        <section class="brochure-page page-theme-ivory page-3">
            <header class="page-header">
                <div class="header-brand">
                    <img src="{logo_b64}" alt="JewelDesk Logo">
                    <span class="header-brand-title">JewelDesk</span>
                    <span class="header-category">Core Capabilities</span>
                </div>
                <div class="header-badge">Daily Counter & Stock</div>
            </header>

            <div>
                <span class="section-eyebrow">Practical Solutions for Daily Shop Problems</span>
                <h2 class="page-headline">How Can JewelDesk Help Your Shop?</h2>
                <p class="page-intro">
                    JewelDesk was designed around the actual daily rhythm of a jewellery showroom. Here is how it addresses everyday shop challenges:
                </p>
            </div>

            <div class="features-grid-3">
                <!-- Feature 1: Stock -->
                <div class="feat-item-card">
                    <div class="feat-icon-col">01</div>
                    <div class="feat-content-col">
                        <div class="feat-title-row">
                            <h3 class="feat-heading">Manage Your Jewellery Stock</h3>
                            <span class="feat-tag">Inventory</span>
                        </div>
                        <div class="feat-problem-box">
                            <strong>Everyday Problem:</strong> Searching through trays and notebooks to find piece details or verify actual stock is slow and stressful during customer rush.
                        </div>
                        <div class="feat-benefit-box">
                            <strong>How JewelDesk Helps:</strong> Keep your inventory organized and find item details more easily. Get a clearer view of the stock recorded in your system, including gross weight, net weight, purity (22K, 18K, 14K), and item category.
                        </div>
                    </div>
                </div>

                <!-- Feature 2: Sales -->
                <div class="feat-item-card">
                    <div class="feat-icon-col">02</div>
                    <div class="feat-content-col">
                        <div class="feat-title-row">
                            <h3 class="feat-heading">Record Sales Easily</h3>
                            <span class="feat-tag">Point of Sale</span>
                        </div>
                        <div class="feat-problem-box">
                            <strong>Everyday Problem:</strong> Calculating making charges, metal prices, and tax manually on paper bills can cause arithmetic errors and slow down the billing counter.
                        </div>
                        <div class="feat-benefit-box">
                            <strong>How JewelDesk Helps:</strong> Maintain sales records in one place and make it easier to review previous transactions. Select items, apply rates, and generate clean, printed tax invoices quickly.
                        </div>
                    </div>
                </div>

                <!-- Feature 3: Rates -->
                <div class="feat-item-card">
                    <div class="feat-icon-col">03</div>
                    <div class="feat-content-col">
                        <div class="feat-title-row">
                            <h3 class="feat-heading">Track Gold and Silver Rates</h3>
                            <span class="feat-tag">Daily Bullion</span>
                        </div>
                        <div class="feat-problem-box">
                            <strong>Everyday Problem:</strong> Metal rates change regularly; staff members can sometimes quote inconsistent rates to walk-in customers.
                        </div>
                        <div class="feat-benefit-box">
                            <strong>How JewelDesk Helps:</strong> View gold and silver rate information available in the software to support your daily business workflow. Enter your daily board rates so calculations at the counter remain uniform and transparent.
                        </div>
                    </div>
                </div>

                <!-- Feature 4: Jewellery Identity & HUID -->
                <div class="feat-item-card">
                    <div class="feat-icon-col">04</div>
                    <div class="feat-content-col">
                        <div class="feat-title-row">
                            <h3 class="feat-heading">Maintain Jewellery Identity Details (HUID)</h3>
                            <span class="feat-tag">Hallmark Tracking</span>
                        </div>
                        <div class="feat-problem-box">
                            <strong>Everyday Problem:</strong> Tracking 6-character Hallmark Unique Identification (HUID) codes and purity tags on paper is tedious and easy to mix up.
                        </div>
                        <div class="feat-benefit-box">
                            <strong>How JewelDesk Helps:</strong> Organize supported jewellery identification details, including HUID information, where applicable. Record and review HUID numbers directly alongside item weights on printed invoices.
                        </div>
                    </div>
                </div>
            </div>

            <!-- Visual Screenshot Strip -->
            <div class="ui-visual-strip">
                <img src="{inv_b64}" alt="Inventory Management Screen" class="ui-visual-img">
                <div class="ui-visual-text">
                    <div class="ui-visual-title">Actual Screen: Organized Jewellery Inventory</div>
                    <p class="ui-visual-desc">
                        Every ornament is clearly listed with item code, metal type, gross weight, net weight, purity karat, and hallmark HUID for effortless verification.
                    </p>
                </div>
            </div>

            <footer class="page-footer">
                <span class="footer-tagline">JewelDesk — Clear Inventory & Fast Counter Billing</span>
                <span class="footer-page-num">Page 3 of 6</span>
            </footer>
        </section>


        <!-- =========================================================
             PAGE 4: HOW JEWELDESK CAN HELP YOUR SHOP (PART 2)
             ========================================================= -->
        <section class="brochure-page page-theme-ivory page-4">
            <header class="page-header">
                <div class="header-brand">
                    <img src="{logo_b64}" alt="JewelDesk Logo">
                    <span class="header-brand-title">JewelDesk</span>
                    <span class="header-category">Core Capabilities</span>
                </div>
                <div class="header-badge">Reports, Payments & Care</div>
            </header>

            <div>
                <span class="section-eyebrow">Operations, Records & Follow-Up</span>
                <h2 class="page-headline">More Ways JewelDesk Supports Your Shop</h2>
                <p class="page-intro">
                    From tracking stock movements to keeping customer records organized and reviewing business reports:
                </p>
            </div>

            <div class="features-grid-3">
                <!-- Feature 5: Stock Movement -->
                <div class="feat-item-card">
                    <div class="feat-icon-col">05</div>
                    <div class="feat-content-col">
                        <div class="feat-title-row">
                            <h3 class="feat-heading">Understand Stock Movement</h3>
                            <span class="feat-tag">Audit Trail</span>
                        </div>
                        <div class="feat-problem-box">
                            <strong>Everyday Problem:</strong> It is difficult to know when an item entered stock, when it was sold, or whether a piece was adjusted or returned.
                        </div>
                        <div class="feat-benefit-box">
                            <strong>How JewelDesk Helps:</strong> Review recorded stock movements to understand how inventory changes over time. Every purchase, sale, or return is tracked in a date-wise history.
                        </div>
                    </div>
                </div>

                <!-- Feature 6: Reports -->
                <div class="feat-item-card">
                    <div class="feat-icon-col">06</div>
                    <div class="feat-content-col">
                        <div class="feat-title-row">
                            <h3 class="feat-heading">View Business Reports</h3>
                            <span class="feat-tag">Business Insights</span>
                        </div>
                        <div class="feat-problem-box">
                            <strong>Everyday Problem:</strong> Spending late evenings after closing manually adding up daily sales and category totals from registers requires hours of extra effort.
                        </div>
                        <div class="feat-benefit-box">
                            <strong>How JewelDesk Helps:</strong> Use available reports to review sales and other recorded business information over selected periods without manually compiling everything from scratch.
                        </div>
                    </div>
                </div>

                <!-- Feature 7: Payments -->
                <div class="feat-item-card">
                    <div class="feat-icon-col">07</div>
                    <div class="feat-content-col">
                        <div class="feat-title-row">
                            <h3 class="feat-heading">Manage Payment Information</h3>
                            <span class="feat-tag">Payment Records</span>
                        </div>
                        <div class="feat-problem-box">
                            <strong>Everyday Problem:</strong> Customers often pay using mixed modes—part cash, UPI transfer, and debit/credit card—making payment reconciliation confusing.
                        </div>
                        <div class="feat-benefit-box">
                            <strong>How JewelDesk Helps:</strong> Keep relevant payment records organized and make it easier to review transaction details. Split payments across cash, card, UPI, and bank transfer are clearly recorded.
                        </div>
                    </div>
                </div>

                <!-- Feature 8 & 9: Customers & WhatsApp -->
                <div class="feat-item-card">
                    <div class="feat-icon-col">08</div>
                    <div class="feat-content-col">
                        <div class="feat-title-row">
                            <h3 class="feat-heading">Keep Customer Records & WhatsApp Communication</h3>
                            <span class="feat-tag">Customer Care</span>
                        </div>
                        <div class="feat-problem-box">
                            <strong>Everyday Problem:</strong> Customer contact details get lost in old diaries, and following up or sending a polite thank-you message after a sale is often forgotten.
                        </div>
                        <div class="feat-benefit-box">
                            <strong>How JewelDesk Helps:</strong> Store and access customer information more conveniently instead of searching through scattered records. Use the available WhatsApp thank-you message feature to support customer follow-up after a sale.
                        </div>
                    </div>
                </div>
            </div>

            <!-- Visual Screenshot Strip -->
            <div class="ui-visual-strip">
                <img src="{rep_b64}" alt="Business Reports Screen" class="ui-visual-img">
                <div class="ui-visual-text">
                    <div class="ui-visual-title">Actual Screen: Daily Sales & Business Reports</div>
                    <p class="ui-visual-desc">
                        Review recorded daily counters, payment collection breakdowns, and transaction summaries over chosen date ranges with just a few clicks.
                    </p>
                </div>
            </div>

            <footer class="page-footer">
                <span class="footer-tagline">JewelDesk — Clear Business Reports & Customer Follow-Up</span>
                <span class="footer-page-num">Page 4 of 6</span>
            </footer>
        </section>


        <!-- =========================================================
             PAGE 5: BEFORE VS WITH JEWELDESK & WHO BENEFITS
             ========================================================= -->
        <section class="brochure-page page-theme-ivory page-5">
            <header class="page-header">
                <div class="header-brand">
                    <img src="{logo_b64}" alt="JewelDesk Logo">
                    <span class="header-brand-title">JewelDesk</span>
                    <span class="header-category">Comparison & Fit</span>
                </div>
                <div class="header-badge">Shop Owner's Perspective</div>
            </header>

            <!-- Section 5: Before vs With JewelDesk -->
            <div>
                <span class="section-eyebrow">Side-by-Side Comparison</span>
                <h2 class="page-headline">Before JewelDesk vs With JewelDesk</h2>
                <p class="page-intro">
                    See how transitioning from scattered paper records to an organized software system makes a practical difference in your daily shop routine:
                </p>
            </div>

            <div class="comparison-table-wrapper">
                <div class="comp-grid">
                    <!-- Before Column -->
                    <div class="comp-col comp-col-before">
                        <div class="comp-header">
                            <span>✕</span> Without an Organized System
                        </div>
                        <ul class="comp-list">
                            <li class="comp-list-item">
                                <span class="comp-bullet">•</span>
                                <span>Searching through records can take time when a customer asks about a previous purchase.</span>
                            </li>
                            <li class="comp-list-item">
                                <span class="comp-bullet">•</span>
                                <span>Stock information may be difficult to review across multiple physical trays and registers.</span>
                            </li>
                            <li class="comp-list-item">
                                <span class="comp-bullet">•</span>
                                <span>Sales and customer details may be scattered across handwritten notebooks and paper slips.</span>
                            </li>
                            <li class="comp-list-item">
                                <span class="comp-bullet">•</span>
                                <span>Preparing reports can require extra effort and long manual calculations after showroom hours.</span>
                            </li>
                        </ul>
                    </div>

                    <!-- With Column -->
                    <div class="comp-col comp-col-after">
                        <div class="comp-header">
                            <span>✓</span> With JewelDesk
                        </div>
                        <ul class="comp-list">
                            <li class="comp-list-item">
                                <span class="comp-bullet">•</span>
                                <span>Keep supported business information in one place, accessible whenever you need it.</span>
                            </li>
                            <li class="comp-list-item">
                                <span class="comp-bullet">•</span>
                                <span>Find recorded inventory details more conveniently by item code, metal, or category.</span>
                            </li>
                            <li class="comp-list-item">
                                <span class="comp-bullet">•</span>
                                <span>Review sales and customer records more easily from a unified billing screen.</span>
                            </li>
                            <li class="comp-list-item">
                                <span class="comp-bullet">•</span>
                                <span>Access available reports without manually compiling everything from scattered papers.</span>
                            </li>
                        </ul>
                    </div>
                </div>
                <div class="honest-note">
                    * Note: JewelDesk is designed to support and assist shop staff by organizing recorded information; it does not eliminate all manual showroom care or promise error-free records.
                </div>
            </div>

            <!-- Section 6: Who Can Benefit? -->
            <div style="margin-top: 1mm;">
                <span class="section-eyebrow">Designed for Your Needs</span>
                <h2 class="page-headline" style="font-size: 17px; margin-bottom: 2mm;">Who Can Benefit from JewelDesk?</h2>
                <p class="page-intro" style="margin-bottom: 2.5mm;">
                    JewelDesk is designed for jewellery retailers who want a more organized way to manage everyday shop activities, including:
                </p>
            </div>

            <div class="audience-grid">
                <div class="audience-card">
                    <div class="audience-icon">✦</div>
                    <div>
                        <div class="audience-title">Jewellery Shop Owners</div>
                        <p class="audience-desc">
                            Owners who want peace of mind knowing that inventory, daily sales, and transaction records are organized in one dependable system.
                        </p>
                    </div>
                </div>

                <div class="audience-card">
                    <div class="audience-icon">✦</div>
                    <div>
                        <div class="audience-title">Independent Jewellery Retailers</div>
                        <p class="audience-desc">
                            Family-run and standalone jewellery retail shops looking to step up from physical paper registers to clean, professional digital records.
                        </p>
                    </div>
                </div>

                <div class="audience-card">
                    <div class="audience-icon">✦</div>
                    <div>
                        <div class="audience-title">Shops Managing Inventory & Sales</div>
                        <p class="audience-desc">
                            Showrooms handling gold, silver, and gemstones that need quick weight lookups, accurate pricing, and printed tax invoices at the counter.
                        </p>
                    </div>
                </div>

                <div class="audience-card">
                    <div class="audience-icon">✦</div>
                    <div>
                        <div class="audience-title">Retailers Seeking Better Visibility</div>
                        <p class="audience-desc">
                            Business owners who want a clear, day-to-day picture of their recorded stock levels, sales turnover, and customer histories.
                        </p>
                    </div>
                </div>
            </div>

            <footer class="page-footer">
                <span class="footer-tagline">JewelDesk — Designed for Everyday Retail Practicality</span>
                <span class="footer-page-num">Page 5 of 6</span>
            </footer>
        </section>


        <!-- =========================================================
             PAGE 6: THE VALUE OF JEWELDESK & CLOSING PAGE
             ========================================================= -->
        <section class="brochure-page page-theme-ivory page-6">
            <header class="page-header">
                <div class="header-brand">
                    <img src="{logo_b64}" alt="JewelDesk Logo">
                    <span class="header-brand-title">JewelDesk</span>
                    <span class="header-category">Summary & Contact</span>
                </div>
                <div class="header-badge">Get in Touch</div>
            </header>

            <!-- Section 7: The Value of JewelDesk -->
            <div class="value-hero-box">
                <div class="section-eyebrow" style="color: var(--gold-light);">The True Value of JewelDesk</div>
                <div class="value-tagline">
                    "Less confusion. Better organization.<br>A clearer view of your business."
                </div>
                <p class="value-text">
                    JewelDesk helps bring essential jewellery retail activities together so shop owners can spend less time searching through scattered information and more time focusing on customers and their business.
                </p>
            </div>

            <!-- 3 Simple Steps to Fit Your Workflow -->
            <div class="workflow-steps-box">
                <div class="wf-box-title">How JewelDesk Fits into Your Daily Shop Workflow</div>
                <div class="steps-flex">
                    <div class="step-item">
                        <div class="step-circle">1</div>
                        <strong>Set Up Daily Rates</strong>
                        <p>Enter the morning gold and silver rates so your counter billing is always accurate and consistent.</p>
                    </div>
                    <div class="step-item">
                        <div class="step-circle">2</div>
                        <strong>Record Counter Sales</strong>
                        <p>Select customer jewellery, apply making charges, split payments, and print clean tax invoices.</p>
                    </div>
                    <div class="step-item">
                        <div class="step-circle">3</div>
                        <strong>Review Daily Summary</strong>
                        <p>Review daily sales summaries and customer records without late-night register calculations.</p>
                    </div>
                </div>
            </div>

            <!-- Section 8: Closing Page & Editable Contact Placeholders -->
            <div class="closing-contact-card">
                <div class="contact-card-header">
                    <div>
                        <div class="contact-brand-title">Make Your Jewellery Business Easier to Manage.</div>
                        <div style="font-size: 11px; color: var(--charcoal-600); margin-top: 1px;">
                            Discover how JewelDesk can fit into your shop's daily workflow.
                        </div>
                    </div>
                    <div class="contact-brand-tag">
                        JewelDesk v2.0
                    </div>
                </div>

                <div class="contact-grid">
                    <div class="contact-cell">
                        <span class="contact-label">Phone Support</span>
                        <div class="contact-val">+91 98XXX XXXXX</div>
                    </div>
                    <div class="contact-cell">
                        <span class="contact-label">Email Inquiries</span>
                        <div class="contact-val">contact@jeweldesk.in</div>
                    </div>
                    <div class="contact-cell">
                        <span class="contact-label">Official Website</span>
                        <div class="contact-val">www.jeweldesk.in</div>
                    </div>
                </div>

                <div class="contact-address-box">
                    <div>
                        <span class="contact-label">Office & Showroom Support</span>
                        <div class="contact-address-text">
                            <strong>JewelDesk Solutions</strong> • Retail Software Division<br>
                            Address: [Your Jewellery Showroom / Company Address Placeholder]
                        </div>
                    </div>
                    <div class="contact-demo-badge">
                        Walkthrough Available
                    </div>
                </div>
            </div>

            <!-- Brand Tagline at Bottom -->
            <div style="text-align: center; margin-top: 2.5mm;">
                <div style="font-family: 'Cinzel', serif; font-size: 13px; font-weight: 700; color: var(--gold-primary); letter-spacing: 1px;">
                    JewelDesk — Your Jewellery Business, Simplified.
                </div>
            </div>

            <footer class="page-footer">
                <span class="footer-tagline">JewelDesk • Jewellery Retail Management Software • All Rights Reserved</span>
                <span class="footer-page-num">Page 6 of 6</span>
            </footer>
        </section>

    </div>

</body>
</html>
"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Successfully generated brochure HTML at {html_path} ({len(html_content)} bytes)")

if __name__ == "__main__":
    main()
