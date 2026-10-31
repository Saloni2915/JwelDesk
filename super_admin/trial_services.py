"""
super_admin/trial_services.py
-----------------------------
Core business logic and service layer for Tenant-based 15-day Free Trials.

Key Rules:
1. Trials belong to the accounts.Tenant (shop/company account), NOT to individual users, employees, or branches.
2. All employees and branches belonging to one Tenant share the identical trial status and expiry date.
3. Thread-safe atomic creation guarantees exactly one initial trial per Tenant.
4. Server-side timestamps and timezone-aware calculations determine active vs. expired status.
5. Existing paid / core subscriptions are protected and never converted to trials.
"""

from datetime import timedelta
from decimal import Decimal
import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('super_admin.trials')


def create_tenant_trial(tenant):
    """
    Atomically provision a 15-day free trial for an eligible newly registered Tenant.

    Guarantees:
    - Attached directly to the accounts.Tenant instance.
    - Exactly 15 days duration from current server timezone.now().
    - Plan: PLAN_TRIAL ('trial'), Status: STATUS_ACTIVE ('active').
    - Price: 0.00, Payment status: PAYMENT_WAIVED ('waived').
    - Idempotent: If a subscription already exists for this tenant, returns the existing record.
    - Thread-safe and atomic: DB unique constraint on tenant_id prevents duplicate rows.
    """
    if not tenant:
        return None

    # Check if subscription is already cached in memory
    if hasattr(tenant, '_subscription_cache') and tenant._subscription_cache is not None:
        return tenant._subscription_cache

    from super_admin.models import TenantSubscription

    with transaction.atomic():
        now = timezone.now()
        sub, created = TenantSubscription.objects.get_or_create(
            tenant=tenant,
            defaults={
                'plan_name': TenantSubscription.PLAN_TRIAL,
                'status': TenantSubscription.STATUS_ACTIVE,
                'billing_cycle': TenantSubscription.CYCLE_MONTHLY,
                'price': Decimal('0.00'),
                'discount': Decimal('0.00'),
                'payment_status': TenantSubscription.PAYMENT_WAIVED,
                'started_at': now,
                'expires_at': now + timedelta(days=15),
                'notes': "Automatic 15-day free trial for new showroom account.",
            }
        )
        if created:
            logger.info(
                "Created 15-day Free Trial for Tenant '%s' (ID %s). Expires at: %s",
                tenant.name,
                tenant.id,
                sub.expires_at
            )
        return sub


def get_tenant_subscription(tenant):
    """Safely fetch the TenantSubscription for a given tenant."""
    if not tenant:
        return None
    try:
        sub = getattr(tenant, 'subscription', None)
        if sub is not None:
            return sub
    except Exception:
        pass

    from super_admin.models import TenantSubscription
    return TenantSubscription.objects.filter(tenant=tenant).first()


def is_tenant_subscription_active(tenant):
    """
    Check if the tenant has an active, valid, and unexpired subscription.
    Returns:
        True: Active trial or paid subscription (within validity).
        False: No subscription, trial expired, or subscription suspended.
    """
    sub = get_tenant_subscription(tenant)
    if not sub:
        return False

    from super_admin.models import TenantSubscription

    # Blocked if manually suspended or marked expired
    if sub.status in (TenantSubscription.STATUS_SUSPENDED, getattr(TenantSubscription, 'STATUS_EXPIRED', 'expired')):
        return False

    # Check real-time timestamp expiry
    if sub.expires_at and timezone.now() > sub.expires_at:
        return False

    return sub.status in (
        TenantSubscription.STATUS_ACTIVE,
        TenantSubscription.STATUS_TRIAL,
        TenantSubscription.STATUS_GRACE_PERIOD
    )


def is_tenant_trial(tenant):
    """Return True if the tenant's subscription is a trial plan."""
    sub = get_tenant_subscription(tenant)
    if not sub:
        return False
    from super_admin.models import TenantSubscription
    return sub.plan_name == TenantSubscription.PLAN_TRIAL or sub.status == TenantSubscription.STATUS_TRIAL


def get_trial_days_remaining(tenant):
    """Return the integer number of full days remaining in the tenant's trial, or 0 if expired."""
    sub = get_tenant_subscription(tenant)
    if not sub or not sub.expires_at:
        return 0
    now = timezone.now()
    if now >= sub.expires_at:
        return 0
    diff = sub.expires_at - now
    # Return days remaining, rounding up if fractional day exists
    return max(0, diff.days + (1 if diff.seconds > 0 else 0))


def is_tenant_trial_extended(tenant):
    """Return True if the tenant's trial has been extended beyond initial 15 days or flagged as extended."""
    sub = get_tenant_subscription(tenant)
    if not sub:
        return False
    return getattr(sub, 'is_trial_extended', False)

