"""
Global context processor for company branding.

Makes the CompanySettings singleton available to every request as
the ``company`` context variable, so the header/sidebar and every
other template can render the shop name/logo/GSTIN dynamically.
Reads the singleton on every request so saved branding changes appear
immediately; a safe fallback is used while nothing is configured.
"""
from .models import CompanySettings


def company_settings_context(request):
    """Return ``{'company': <branding>}`` for every template render.

    The branding row is read fresh from the database on every request, so a
    change saved in Company Settings is visible in the header and sidebar on
    the very next page load. (An earlier revision cached the row for the whole
    process lifetime, which is why saved changes appeared to be ignored.)
    """
    return {'company': _load_company()}


def _load_company():
    """Return the CompanySettings row (pk=1), or a safe fallback object."""
    company = CompanySettings.objects.filter(pk=1).first()
    if company is None:
        return _make_fallback_company()
    return company


class _FallbackCompany:
    """Safe fallback branding when no CompanySettings record exists yet."""

    name = 'JewelDesk'
    logo = None          # no logo URL at all
    gstin = ''
    address = ''
    phone = ''
    email = ''
    invoice_footer_note = ''


def _make_fallback_company():
    return _FallbackCompany()
