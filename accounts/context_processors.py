"""
Global context processor for company branding.

Makes the CompanySettings singleton available to every request as
the ``company`` context variable, so the header/sidebar and every
other template can render the shop name/logo/GSTIN dynamically.
Reads the singleton on every request so saved branding changes appear
immediately; a safe fallback is used while nothing is configured.
"""
from django.core.cache import cache
from .models import CompanySettings


def company_settings_context(request):
    """Return ``{'company': <branding>, 'current_tenant': <tenant>}`` for template renders.

    - On the public landing page, branding is not needed, so DB query is bypassed entirely.
    - On all other pages, the row is read for request.tenant from cache (invalidated when saved),
      saving an expensive remote DB round-trip on every page navigation.
    """
    path = getattr(request, 'path', '')
    tenant = getattr(request, 'tenant', None)
    if path in ('/', '/landing/'):
        fallback = _make_fallback_company()
        return {
            'company': fallback,
            'current_tenant': tenant,
            'hidden_menus': [],
        }

    company_obj = _load_company(tenant=tenant)

    # Resolve current language: check session, cookie, or company setting
    lang = (
        (request.session.get('django_language') if hasattr(request, 'session') else None)
        or request.COOKIES.get('django_language')
        or request.COOKIES.get('jd_language')
    )

    if not lang and company_obj and hasattr(company_obj, 'language') and company_obj.language:
        lang = company_obj.language

    if lang not in ('en', 'hi'):
        lang = 'en'

    hidden_menus = company_obj.get_hidden_menus() if hasattr(company_obj, 'get_hidden_menus') else []
    return {
        'company': company_obj,
        'current_tenant': tenant,
        'hidden_menus': hidden_menus,
        'current_language': lang,
        'is_hindi': (lang == 'hi'),
        'available_languages': [
            {'code': 'en', 'name': 'English', 'flag': '🇬🇧'},
            {'code': 'hi', 'name': 'हिंदी', 'flag': '🇮🇳'},
        ],
    }


def _load_company(tenant=None):
    """Return the cached CompanySettings row for the tenant, or a safe fallback object."""
    if not tenant:
        return _make_fallback_company()

    cache_key = f'company_settings:tenant:{tenant.id}'
    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        company = CompanySettings.load(tenant=tenant)
        if company is None:
            return _make_fallback_company()

        try:
            cache.set(cache_key, company, timeout=60)
        except Exception:
            pass
        return company
    except Exception:
        return _make_fallback_company()


class _FallbackCompany:
    """Safe fallback branding when no CompanySettings record exists yet."""

    name = 'JewelDesk'
    logo = None          # no logo URL at all
    logo_url = None
    gstin = ''
    address = ''
    phone = ''
    email = ''
    invoice_footer_note = ''
    hidden_menu_items = ''
    language = 'en'

    def get_hidden_menus(self):
        return []

    def is_menu_hidden(self, menu_key):
        return False


def _make_fallback_company():
    return _FallbackCompany()
