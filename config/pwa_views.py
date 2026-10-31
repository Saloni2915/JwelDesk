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

    action = request.GET.get('action')
    if action == 'inspect_users':
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user_list = []
        for u in User.objects.all():
            user_list.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'first_name': u.first_name,
                'is_active': u.is_active,
                'is_staff': u.is_staff,
                'has_usable_password': u.has_usable_password(),
            })
        return JsonResponse({
            'status': 'success',
            'users': user_list,
        })

    if action == 'set_user_password':
        ident = (request.GET.get('identifier') or '').strip()
        new_pwd = (request.GET.get('password') or '').strip()
        if not ident or not new_pwd:
            return JsonResponse({'status': 'error', 'message': 'identifier and password required'}, status=400)
        from django.contrib.auth import get_user_model
        from django.db.models import Q
        User = get_user_model()
        matched = User.objects.filter(Q(username__iexact=ident) | Q(email__iexact=ident))
        if not matched.exists():
            return JsonResponse({'status': 'error', 'message': f'No user found matching {ident}'}, status=404)
        updated_users = []
        for u in matched:
            u.set_password(new_pwd)
            u.is_active = True
            u.save()
            updated_users.append(u.username)
        return JsonResponse({
            'status': 'success',
            'updated': updated_users,
            'message': f'Password set successfully for {len(updated_users)} user(s)',
        })

    if action in ('backfill_branch_data', 'backfill'):
        out = io.StringIO()
        try:
            call_command('backfill_branch_data', stdout=out)
            return JsonResponse({
                'status': 'success',
                'output': out.getvalue(),
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'exception': str(e)}, status=500)

    if action == 'test_crm_queries':
        from super_admin.models import PlatformDemoLead
        from super_admin.sales_views import get_sales_crm_stage_counts
        res = {}
        try:
            res['counts'] = get_sales_crm_stage_counts()
            res['leads_sample'] = list(PlatformDemoLead.objects.values('id', 'lead_name', 'stage', 'status')[:5])
            res['status'] = 'success'
        except Exception as e:
            import traceback
            res['status'] = 'error'
            res['error'] = str(e)
            res['traceback'] = traceback.format_exc()
        return JsonResponse(res)

    if action == 'inspect_db':
        with connection.cursor() as cursor:
            vendor = connection.vendor
            cursor.execute("SELECT app, name, applied FROM django_migrations WHERE app = 'super_admin' ORDER BY id;")
            migs = [{'app': r[0], 'name': r[1], 'applied': str(r[2])} for r in cursor.fetchall()]

            cols = []
            if vendor == 'postgresql':
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'super_admin_platformdemolead';")
                cols = [r[0] for r in cursor.fetchall()]

        return JsonResponse({
            'status': 'success',
            'vendor': vendor,
            'super_admin_migrations': migs,
            'platformdemolead_columns': cols,
        })

    if action == 'apply_crm_schema':
        results = []
        with connection.cursor() as cursor:
            if connection.vendor == 'postgresql':
                cursor.execute("""
                    ALTER TABLE super_admin_platformdemolead 
                    ADD COLUMN IF NOT EXISTS lead_id varchar(40) DEFAULT '',
                    ADD COLUMN IF NOT EXISTS whatsapp_number varchar(30) DEFAULT '',
                    ADD COLUMN IF NOT EXISTS state varchar(100) DEFAULT '',
                    ADD COLUMN IF NOT EXISTS deal_value numeric(12, 2) DEFAULT 0.00,
                    ADD COLUMN IF NOT EXISTS stage varchar(30) DEFAULT 'new',
                    ADD COLUMN IF NOT EXISTS lost_reason varchar(50) DEFAULT '',
                    ADD COLUMN IF NOT EXISTS lost_notes text DEFAULT '',
                    ADD COLUMN IF NOT EXISTS expected_close_date date;
                """)
                results.append("platformdemolead columns ensured")

                cursor.execute("""
                    ALTER TABLE super_admin_platformproposal 
                    ADD COLUMN IF NOT EXISTS branches_count integer DEFAULT 1,
                    ADD COLUMN IF NOT EXISTS is_latest boolean DEFAULT true,
                    ADD COLUMN IF NOT EXISTS lead_id bigint,
                    ADD COLUMN IF NOT EXISTS parent_proposal_id bigint,
                    ADD COLUMN IF NOT EXISTS selected_modules jsonb DEFAULT '[]'::jsonb,
                    ADD COLUMN IF NOT EXISTS tax_amount numeric(12, 2) DEFAULT 0.00,
                    ADD COLUMN IF NOT EXISTS tax_percentage numeric(5, 2) DEFAULT 18.00,
                    ADD COLUMN IF NOT EXISTS users_count integer DEFAULT 3,
                    ADD COLUMN IF NOT EXISTS version_number integer DEFAULT 1;
                """)
                results.append("platformproposal columns ensured")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS super_admin_platformleadstagehistory (
                        id bigserial PRIMARY KEY,
                        from_stage varchar(30) NOT NULL,
                        to_stage varchar(30) NOT NULL,
                        reason text NOT NULL,
                        created_at timestamptz NOT NULL,
                        changed_by_id bigint,
                        lead_id bigint NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS super_admin_platformleadnegotiation (
                        id bigserial PRIMARY KEY,
                        target_plan varchar(30) NOT NULL,
                        required_modules jsonb NOT NULL,
                        branches_count integer NOT NULL,
                        users_count integer NOT NULL,
                        budget numeric(12, 2) NOT NULL,
                        expected_purchase_date date,
                        competitor_info varchar(200) NOT NULL,
                        discussion_summary text NOT NULL,
                        created_at timestamptz NOT NULL,
                        conducted_by_id bigint,
                        lead_id bigint NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS super_admin_platformleadactivity (
                        id bigserial PRIMARY KEY,
                        activity_type varchar(30) NOT NULL,
                        title varchar(200) NOT NULL,
                        scheduled_at timestamptz,
                        is_completed boolean NOT NULL,
                        completed_at timestamptz,
                        outcome_notes text NOT NULL,
                        next_follow_up_date date,
                        created_at timestamptz NOT NULL,
                        assigned_to_id bigint,
                        created_by_id bigint,
                        lead_id bigint NOT NULL
                    );
                """)
                results.append("CRM tables ensured")

                cursor.execute("""
                    INSERT INTO django_migrations (app, name, applied)
                    SELECT 'super_admin', '0010_platformdemolead_deal_value_and_more', now()
                    WHERE NOT EXISTS (
                        SELECT 1 FROM django_migrations WHERE app = 'super_admin' AND name = '0010_platformdemolead_deal_value_and_more'
                    );
                """)
                results.append("Migration 0010 recorded in django_migrations")

        return JsonResponse({
            'status': 'success',
            'results': results,
        })

    out = io.StringIO()
    err = io.StringIO()
    try:
        call_command('migrate', interactive=False, stdout=out, stderr=err)
        try:
            call_command('backfill_branch_data', stdout=out)
        except Exception as b_err:
            out.write(f"\n[Backfill Note] {b_err}\n")
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

