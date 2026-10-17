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


# ============================================================================
# 2. SaaS Subscriptions & Revenue Tracking
# ============================================================================

class TenantSubscription(models.Model):
    """SaaS Subscription record for each Jewellery Showroom Tenant."""

    PLAN_TRIAL      = 'trial'
    PLAN_CORE       = 'core'
    PLAN_PRO        = 'pro'
    PLAN_ENTERPRISE = 'enterprise'

    PLAN_CHOICES = [
        (PLAN_TRIAL,      '14-Day Free Trial'),
        (PLAN_CORE,       'Core Showroom Standard Tier'),
        (PLAN_PRO,        'Pro Atelier Suite'),
        (PLAN_ENTERPRISE, 'Custom Enterprise Tier'),
    ]

    CYCLE_MONTHLY = 'monthly'
    CYCLE_YEARLY  = 'yearly'

    CYCLE_CHOICES = [
        (CYCLE_MONTHLY, 'Monthly Recurring'),
        (CYCLE_YEARLY,  'Yearly / Annual'),
    ]

    STATUS_ACTIVE       = 'active'
    STATUS_TRIAL        = 'trial'
    STATUS_GRACE_PERIOD = 'grace_period'
    STATUS_OVERDUE      = 'overdue'
    STATUS_SUSPENDED    = 'suspended'

    STATUS_CHOICES = [
        (STATUS_ACTIVE,       'Active (Paid)'),
        (STATUS_TRIAL,        'Free Trial'),
        (STATUS_GRACE_PERIOD, 'Grace Period'),
        (STATUS_OVERDUE,      'Payment Overdue'),
        (STATUS_SUSPENDED,    'Suspended'),
    ]

    PAYMENT_PAID    = 'paid'
    PAYMENT_PENDING = 'pending'
    PAYMENT_WAIVED  = 'waived'

    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_PAID,    'Paid'),
        (PAYMENT_PENDING, 'Payment Pending'),
        (PAYMENT_WAIVED,  'Complimentary / Waived'),
    ]

    tenant = models.OneToOneField(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='subscription'
    )
    plan_name = models.CharField(
        max_length=30,
        choices=PLAN_CHOICES,
        default=PLAN_CORE,
        db_index=True
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True
    )
    billing_cycle = models.CharField(
        max_length=20,
        choices=CYCLE_CHOICES,
        default=CYCLE_YEARLY
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Recurring subscription fee in INR (₹)"
    )
    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default=PAYMENT_PAID
    )
    started_at = models.DateTimeField(
        default=models.functions.Now
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True
    )
    notes = models.TextField(
        blank=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )
    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Tenant Subscription'
        verbose_name_plural = 'Tenant Subscriptions'

    def __str__(self):
        return f"{self.tenant.name} - {self.get_plan_name_display()} ({self.get_status_display()})"

    @property
    def total_revenue_collected(self):
        res = self.payments.aggregate(total=models.Sum('amount'))['total']
        return res if res is not None else 0.00


class SubscriptionPayment(models.Model):
    """Payment transaction recorded against a showroom's subscription."""

    METHOD_UPI      = 'upi'
    METHOD_BANK     = 'bank_transfer'
    METHOD_RAZORPAY = 'razorpay'
    METHOD_CASH     = 'cash'
    METHOD_CHEQUE   = 'cheque'

    METHOD_CHOICES = [
        (METHOD_UPI,      'UPI (GPay / PhonePe / Paytm)'),
        (METHOD_BANK,     'Bank Transfer (NEFT / RTGS / IMPS)'),
        (METHOD_RAZORPAY, 'Razorpay Online Gateway'),
        (METHOD_CASH,     'Cash Payment'),
        (METHOD_CHEQUE,   'Cheque / DD'),
    ]

    subscription = models.ForeignKey(
        TenantSubscription,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='subscription_payments'
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Amount received in INR (₹)"
    )
    payment_date = models.DateField(
        default=models.functions.Now
    )
    payment_method = models.CharField(
        max_length=30,
        choices=METHOD_CHOICES,
        default=METHOD_UPI
    )
    reference_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="UTR / Transaction ID / Cheque Number"
    )
    invoice_number = models.CharField(
        max_length=60,
        blank=True,
        help_text="Invoice / Receipt Reference"
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recorded_subscription_payments'
    )
    notes = models.TextField(
        blank=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['-payment_date', '-created_at']
        verbose_name = 'Subscription Payment'
        verbose_name_plural = 'Subscription Payments'

    def __str__(self):
        return f"₹{self.amount} from {self.tenant.name} on {self.payment_date}"


# ============================================================================
# 3. SaaS Proposals & Quotes Generator
# ============================================================================

def default_proposal_token():
    import secrets
    return secrets.token_urlsafe(20)


class PlatformProposal(models.Model):
    """B2B SaaS Proposal / Quotation sent to prospective jewellery showroom customers."""

    STATUS_DRAFT    = 'draft'
    STATUS_SENT     = 'sent'
    STATUS_VIEWED   = 'viewed'
    STATUS_ACCEPTED = 'accepted'
    STATUS_DECLINED = 'declined'
    STATUS_EXPIRED  = 'expired'

    STATUS_CHOICES = [
        (STATUS_DRAFT,    'Draft (Unsent)'),
        (STATUS_SENT,     'Sent to Client'),
        (STATUS_VIEWED,   'Viewed by Client'),
        (STATUS_ACCEPTED, 'Accepted / Won'),
        (STATUS_DECLINED, 'Declined'),
        (STATUS_EXPIRED,  'Expired'),
    ]

    proposal_number = models.CharField(
        max_length=40,
        unique=True,
        db_index=True
    )
    client_name = models.CharField(
        max_length=150,
        help_text="Customer / Owner Name"
    )
    client_showroom_name = models.CharField(
        max_length=200,
        help_text="Jewellery Showroom or Business Name"
    )
    client_email = models.EmailField(
        blank=True
    )
    client_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text="Mobile / WhatsApp number"
    )
    client_city = models.CharField(
        max_length=100,
        blank=True
    )
    target_plan = models.CharField(
        max_length=30,
        choices=TenantSubscription.PLAN_CHOICES,
        default=TenantSubscription.PLAN_CORE
    )
    billing_cycle = models.CharField(
        max_length=20,
        choices=TenantSubscription.CYCLE_CHOICES,
        default=TenantSubscription.CYCLE_YEARLY
    )
    quoted_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=29999.00
    )
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00
    )
    final_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=29999.00
    )
    valid_until = models.DateField(
        null=True,
        blank=True
    )
    features_summary = models.TextField(
        blank=True,
        help_text="Bullet points or summary of features included in this proposal"
    )
    terms_notes = models.TextField(
        blank=True,
        help_text="Payment terms, onboarding schedule, warranty/support SLAs"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True
    )
    share_token = models.CharField(
        max_length=64,
        unique=True,
        default=default_proposal_token,
        db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_proposals'
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )
    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Platform Proposal'
        verbose_name_plural = 'Platform Proposals'

    def __str__(self):
        return f"{self.proposal_number} - {self.client_showroom_name} (₹{self.final_amount})"
