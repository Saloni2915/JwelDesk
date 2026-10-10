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
    """Return ``{'company': <branding>}`` for template renders.

    - On the public landing page, branding is not needed, so DB query is bypassed entirely.
    - On all other pages, the row is read from cache (invalidated when saved in Company Settings),
      saving an expensive remote DB round-trip on every page navigation.
    """
    path = getattr(request, 'path', '')
    if path in ('/', '/landing/'):
        return {'company': _make_fallback_company()}

    return {'company': _load_company()}


def _load_company():
    """Return the cached CompanySettings row, or a safe fallback object."""
    try:
        cached = cache.get('company_settings:singleton')
        if cached is not None:
            return cached

        company = CompanySettings.objects.first()
        if company is None:
            return _make_fallback_company()

        try:
            cache.set('company_settings:singleton', company, timeout=3600)
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


def _make_fallback_company():
    return _FallbackCompany()
