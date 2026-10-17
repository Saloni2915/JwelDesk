"""
super_admin/models.py
---------------------
Data models for the JewelDesk Super Admin Platform.
Provides append-only audit logging for platform-level actions and customer impersonation.
"""

from django.conf import settings
from django.db import models


class PlatformAuditLog(models.Model):
    """Immutable append-only audit trail for Super Admin platform actions.

    Records administrative operations such as Customer Impersonation (start/end)
    and Tenant Lifecycle changes (activation/deactivation/updates).
    """

    ACTION_IMPERSONATION_START = 'IMPERSONATION_START'
    ACTION_IMPERSONATION_END   = 'IMPERSONATION_END'
    ACTION_TENANT_DEACTIVATE   = 'TENANT_DEACTIVATE'
    ACTION_TENANT_ACTIVATE     = 'TENANT_ACTIVATE'
    ACTION_TENANT_VIEW         = 'TENANT_VIEW'

    ACTION_CHOICES = [
        (ACTION_IMPERSONATION_START, 'Started Customer Impersonation'),
        (ACTION_IMPERSONATION_END,   'Ended Customer Impersonation'),
        (ACTION_TENANT_DEACTIVATE,   'Deactivated Showroom Tenant'),
        (ACTION_TENANT_ACTIVATE,     'Activated Showroom Tenant'),
        (ACTION_TENANT_VIEW,         'Viewed Showroom Details'),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='platform_audit_logs',
        help_text="The Super Admin or platform operator who performed this action."
    )
    action = models.CharField(
        max_length=40,
        choices=ACTION_CHOICES,
        db_index=True
    )
    target_tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='platform_audit_records',
        help_text="Target showroom / tenant affected by this action."
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='targeted_audit_records',
        help_text="Target user account impersonated or affected."
    )
    reason = models.TextField(
        blank=True,
        help_text="Administrative justification or support ticket reference."
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True
    )
    user_agent = models.CharField(
        max_length=500,
        blank=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Platform Audit Log'
        verbose_name_plural = 'Platform Audit Logs'

    def __str__(self):
        actor_name = self.actor.username if self.actor else 'System'
        tenant_name = self.target_tenant.name if self.target_tenant else 'N/A'
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {actor_name} -> {self.action} on {tenant_name}"
