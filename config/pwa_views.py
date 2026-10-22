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
def app_version_view(request):
    """Serve JSON details about the current application version and changelog.

    Used by the client browser and Progressive Web App (PWA) to detect new
    deployments, notify the user, and prompt them to reload immediately.
    """
    from django.http import JsonResponse
    version = getattr(settings, 'APP_VERSION', '2.4.0')
    build_id = getattr(settings, 'APP_BUILD_ID', '20261022-v240')

    data = {
        'version': version,
        'build': build_id,
        'title': 'New Update Available!',
        'summary': 'JewelDesk v' + str(version) + ' is ready. Please reload the app to apply the latest jewellery invoice, theme, and PWA icon improvements.',
        'changelog': [
            'Enhanced Mobile PWA Branding: High-precision luxury gold squircle icon with flawless anti-aliased borders and safe-zone compliance',
            'Theme-Adaptive UI: Electric Cyan & Sapphire Blue palette integration across Dark Theme',
            'Standard Jewellery Tax Invoice: Authentic showroom layout, HSN 7113, weights & rates alignment'
        ],
        'release_date': '2026-10-22'
    }
    response = JsonResponse(data)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
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


@require_GET
def download_apk_view(request):
    """Serve the signed JewelDesk Android APK package for direct download."""
    from django.http import FileResponse
    apk_path = settings.BASE_DIR / 'static' / 'downloads' / 'JewelDesk.apk'
    if not apk_path.exists():
        raise Http404("JewelDesk APK file not found.")
    response = FileResponse(
        open(apk_path, 'rb'),
        as_attachment=True,
        filename='JewelDesk.apk',
        content_type='application/vnd.android.package-archive'
    )
    # Set persistent cookie so the landing page and app know APK has been downloaded
    response.set_cookie('jd_apk_downloaded', 'true', max_age=365 * 24 * 60 * 60, samesite='Lax')
    return response


def system_migrate_view(request):
    """Secure endpoint to trigger and inspect database migrations on remote environments."""
    import io
    from django.http import JsonResponse, HttpResponseForbidden
    from django.core.management import call_command
    from django.db import connection

    expected_key = getattr(settings, 'MIGRATION_SECRET_KEY', 'jweldesk_migrate_2026')
    provided_key = request.GET.get('key') or request.POST.get('key')
    user = getattr(request, 'user', None)

    is_authorized = (
        (provided_key and provided_key == expected_key)
        or (user and user.is_authenticated and user.is_superuser)
    )

    if not is_authorized:
        return HttpResponseForbidden("Forbidden: invalid migration authorization key.")

    out = io.StringIO()
    err = io.StringIO()
    try:
        call_command('migrate', interactive=False, stdout=out, stderr=err)
        tables = connection.introspection.table_names()
        return JsonResponse({
            'status': 'success',
            'output': out.getvalue(),
            'error': err.getvalue(),
            'has_tenant_table': 'accounts_tenant' in tables,
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'exception': str(e),
            'output': out.getvalue(),
            'error': err.getvalue(),
        }, status=500)

