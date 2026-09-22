"""
Metal price service — Gold (XAU) and Silver (XAG) rates in INR per gram.

Phase 1 of the metal-price feature: a small, dependency-free service used by
the inventory dashboard. Credentials are read from Django settings (sourced
from environment variables in config/settings.py) — a key is never hard-coded.

Design notes:
* The dashboard performs CACHE-ONLY reads (``get_price_snapshot``). The API is
  only called through the explicit "Refresh" action (``refresh_prices``), so
  ordinary page interactions never trigger repeated API calls.
* Nothing in this module raises on failure: an unavailable API, a timeout, a
  bad payload or missing credentials all produce a friendly "unavailable"
  snapshot so the dashboard keeps rendering.
"""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

# 1 troy ounce = 31.1034768 grams
GRAMS_PER_TROY_OUNCE = 31.1034768

SNAPSHOT_CACHE_KEY = 'metal_prices:snapshot'
LAST_GOOD_CACHE_KEY = 'metal_prices:last_good'


def _is_configured():
    """True when both the API URL and an API key are present."""
    return bool(getattr(settings, 'METAL_PRICE_API_KEY', '')) and bool(
        getattr(settings, 'METAL_PRICE_API_URL', ''))


def _build_snapshot(gold_per_gram, silver_per_gram, fetched_at,
                    configured=True):
    """Assemble the snapshot dict consumed by the dashboard template."""
    available = gold_per_gram is not None or silver_per_gram is not None
    age_minutes = 0
    if fetched_at is not None:
        age_minutes = int(
            (timezone.now() - fetched_at).total_seconds() // 60)
    return {
        'available': available,
        'configured': configured,
        'gold_price_per_gram': gold_per_gram,
        'silver_price_per_gram': silver_per_gram,
        'last_updated': fetched_at,
        'age_minutes': age_minutes,
    }


def _build_unavailable_snapshot(configured):
    """The "Price unavailable" state shown when no usable data is cached."""
    return _build_snapshot(None, None, fetched_at=None,
                           configured=configured)

def _per_gram(raw):
    """Convert one raw rate into INR per gram, or None when unusable.

    Rates >= 1 are treated as INR per troy ounce; values < 1 as an inverse
    rate (INR -> troy ounces, the metalpriceapi.com style).
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value <= 0:  # NaN or non-positive
        return None
    if value < 1:
        value = 1 / value
    return round(value / GRAMS_PER_TROY_OUNCE, 2)


def _extract_prices(payload):
    """Pull gold/silver INR-per-gram values out of an API payload.

    Supports the common shapes:
    * {"rates": {"XAU": ..., "XAG": ...}}            (per ounce or inverse)
    * {"metal_prices": {"gold": ..., "silver": ...}} (per gram)
    * {"gold": ..., "silver": ...}                   (per gram, top level)
    """
    if not isinstance(payload, dict):
        return None, None
    gold = silver = None
    rates = payload.get('rates')
    if isinstance(rates, dict):
        gold = _per_gram(rates.get('XAU'))
        silver = _per_gram(rates.get('XAG'))
    if gold is None or silver is None:
        alt = payload.get('metal_prices')
        if not isinstance(alt, dict):
            alt = payload
        if gold is None:
            gold = _per_gram(alt.get('gold'))
        if silver is None:
            silver = _per_gram(alt.get('silver'))
    return gold, silver


def _friendly_message(exc):
    """Map a caught exception to a short, user-friendly message."""
    if isinstance(exc, urllib.error.HTTPError):
        return f'The price service returned HTTP {exc.code}.'
    if isinstance(exc, socket.timeout):
        return 'The price service timed out.'
    if isinstance(exc, json.JSONDecodeError):
        return 'The price service returned an unexpected response format.'
    reason = getattr(exc, 'reason', None)
    return f'Could not reach the price service ({reason or exc}).'


def _fetch_payload():
    """Call the configured API once and return the parsed JSON payload."""
    url = getattr(settings, 'METAL_PRICE_API_URL', '')
    api_key = getattr(settings, 'METAL_PRICE_API_KEY', '')
    if '{api_key}' in url and api_key:
        url = url.replace('{api_key}', urllib.parse.quote_plus(api_key))
    headers = {'Accept': 'application/json'}
    header_name = getattr(settings, 'METAL_PRICE_API_KEY_HEADER', '')
    if api_key and header_name:
        headers[header_name] = api_key
    timeout = getattr(settings, 'METAL_PRICE_API_TIMEOUT', 5)
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def get_price_snapshot():
    """Cache-only read used by the dashboard. Never performs an API call."""
    snapshot = cache.get(SNAPSHOT_CACHE_KEY)
    if snapshot is None:
        snapshot = cache.get(LAST_GOOD_CACHE_KEY)
    if snapshot is None:
        return _build_unavailable_snapshot(_is_configured())
    return snapshot


def refresh_prices():
    """Fetch fresh prices once, cache them and report the outcome.

    Returns {'ok': bool, 'message': str, 'snapshot': dict}. On failure the
    last cached (stale) prices remain available to the dashboard.
    """
    if not _is_configured():
        return {
            'ok': False,
            'message': 'API credentials are not configured.',
            'snapshot': get_price_snapshot(),
        }
    try:
        payload = _fetch_payload()
        gold, silver = _extract_prices(payload)
    except (urllib.error.URLError, socket.timeout, TimeoutError,
            ConnectionError, json.JSONDecodeError, ValueError,
            OSError) as exc:
        return {
            'ok': False,
            'message': _friendly_message(exc),
            'snapshot': get_price_snapshot(),
        }
    if gold is None and silver is None:
        return {
            'ok': False,
            'message': 'The price service response did not contain usable rates.',
            'snapshot': get_price_snapshot(),
        }
    snapshot = _build_snapshot(gold, silver, timezone.now(), configured=True)
    cache.set(SNAPSHOT_CACHE_KEY, snapshot,
              timeout=getattr(settings, 'METAL_PRICE_CACHE_TTL', 1800))
    cache.set(LAST_GOOD_CACHE_KEY, snapshot, timeout=None)
    return {'ok': True, 'message': '', 'snapshot': snapshot}
