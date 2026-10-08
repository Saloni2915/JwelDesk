"""
config/pwa_views.py
-------------------
Progressive Web App (PWA) controller views for JewelDesk.
Provides root-scoped endpoints for the manifest, service worker, and offline fallback.
"""

from pathlib import Path
from django.conf import settings
from django.http import HttpResponse, Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def manifest_view(request):
    """Serve the Web App Manifest with the proper content-type."""
    manifest_path = settings.BASE_DIR / 'static' / 'manifest.json'
    if not manifest_path.exists():
        raise Http404("Manifest file not found.")

    with open(manifest_path, 'r', encoding='utf-8') as f:
        content = f.read()

    response = HttpResponse(content, content_type='application/manifest+json')
    response['Cache-Control'] = 'public, max-age=86400'
    return response


@require_GET
def service_worker_view(request):
    """Serve the root-level Service Worker script.

    Setting `Service-Worker-Allowed: /` and serving at `/sw.js` ensures
    the service worker controls all routes across the entire JewelDesk application.
    """
    sw_path = settings.BASE_DIR / 'static' / 'js' / 'sw.js'
    if not sw_path.exists():
        raise Http404("Service worker script not found.")

    with open(sw_path, 'r', encoding='utf-8') as f:
        content = f.read()

    response = HttpResponse(content, content_type='application/javascript; charset=utf-8')
    response['Service-Worker-Allowed'] = '/'
    # Prevent aggressive caching of the service worker itself
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@require_GET
def offline_view(request):
    """Render the branded offline fallback page when network is unavailable."""
    return render(request, 'offline.html')


@require_GET
def download_report_view(request):
    """Serve the complete JewelDesk project report as a downloadable PDF attachment."""
    from django.http import FileResponse
    pdf_path = settings.BASE_DIR / 'JewelDesk_Complete_Project_Report.pdf'
    if not pdf_path.exists():
        raise Http404("Report PDF file not found.")
    return FileResponse(open(pdf_path, 'rb'), as_attachment=True, filename='JewelDesk_Complete_Project_Report.pdf', content_type='application/pdf')


@require_GET
def view_report_view(request):
    """Display the complete JewelDesk project report inline in the browser."""
    from django.http import FileResponse
    pdf_path = settings.BASE_DIR / 'JewelDesk_Complete_Project_Report.pdf'
    if not pdf_path.exists():
        raise Http404("Report PDF file not found.")
    return FileResponse(open(pdf_path, 'rb'), as_attachment=False, filename='JewelDesk_Complete_Project_Report.pdf', content_type='application/pdf')


@require_GET
def download_brochure_view(request):
    """Serve the customer-facing JewelDesk brochure as a downloadable PDF attachment."""
    from django.http import FileResponse
    pdf_path = settings.BASE_DIR / 'JewelDesk_Product_Brochure.pdf'
    if not pdf_path.exists():
        raise Http404("Brochure PDF file not found.")
    return FileResponse(open(pdf_path, 'rb'), as_attachment=True, filename='JewelDesk_Product_Brochure.pdf', content_type='application/pdf')


@require_GET
def view_brochure_view(request):
    """Display the customer-facing JewelDesk brochure inline in the browser."""
    from django.http import FileResponse
    pdf_path = settings.BASE_DIR / 'JewelDesk_Product_Brochure.pdf'
    if not pdf_path.exists():
        raise Http404("Brochure PDF file not found.")
    return FileResponse(open(pdf_path, 'rb'), as_attachment=False, filename='JewelDesk_Product_Brochure.pdf', content_type='application/pdf')


@require_GET
def digital_brochure_view(request):
    """Serve the interactive digital HTML brochure."""
    html_path = settings.BASE_DIR / 'brochure' / 'jeweldesk_brochure.html'
    if not html_path.exists():
        raise Http404("Digital brochure file not found.")
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return HttpResponse(content, content_type='text/html; charset=utf-8')

