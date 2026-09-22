"""
Global context processor for company branding.

Makes the CompanySettings singleton available to every request as
the ``company`` context variable, so the header/sidebar and every
other template can render the shop name/logo/GSTIN dynamically.
Fetches the singleton once per process (process-lifetime cache) and
invalidates on changes — no per-request DB hit after warm.
"""
import threading
from django.db.models.signals import post_delete, post_save

from .models import CompanySettings


_process_cache = {
    'brand': None,          # cached CompanySettings instance
    'update_signal': False,
    'lock': threading.Lock(),
}


def company_settings_context(request):
    """Return {'company': CompanySettings} for every template render."""
    brand = _get_brand()
    if brand is None:
        return {'company': _make_fallback_company()}
    return {'company': brand}


from .models import CompanySettings


def _get_brand():
    """Return the process-cached CompanySettings brand instance (or None)."""
    with _process_cache['lock']:
        if _process_cache['update_signal']:
            _process_cache['brand'] = None
            _process_cache['update_signal'] = False
        brand = _process_cache['brand']
        if brand is None:
            brand = _load_brand()
            _process_cache['brand'] = brand
        return brand


def _load_brand():
    """Load the singleton from the database (process-level fetch)."""
    try:
        return CompanySettings.objects.get(pk=1)
    except CompanySettings.DoesNotExist:
        return None


def invalidate_cache(sender, **kwargs):
    """Cache invalidation hook wired to CompanySettings save/delete signals."""
    with _process_cache['lock']:
        _process_cache['update_signal'] = True


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
