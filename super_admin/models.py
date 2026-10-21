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
    ACTION_DEMO_CREATE         = 'DEMO_CREATE'
    ACTION_DEMO_UPDATE         = 'DEMO_UPDATE'
    ACTION_DEMO_COMPLETE       = 'DEMO_COMPLETE'
    ACTION_DEMO_CONVERT        = 'DEMO_CONVERT'
    ACTION_TICKET_CREATE       = 'TICKET_CREATE'
    ACTION_TICKET_UPDATE       = 'TICKET_UPDATE'
    ACTION_TICKET_RESOLVE      = 'TICKET_RESOLVE'
    ACTION_SUBSCRIPTION_UPDATE = 'SUBSCRIPTION_UPDATE'
    ACTION_PAYMENT_RECORD      = 'PAYMENT_RECORD'

    ACTION_CHOICES = [
        (ACTION_IMPERSONATION_START, 'Started Customer Impersonation'),
        (ACTION_IMPERSONATION_END,   'Ended Customer Impersonation'),
        (ACTION_TENANT_DEACTIVATE,   'Deactivated Showroom Tenant'),
        (ACTION_TENANT_ACTIVATE,     'Activated Showroom Tenant'),
        (ACTION_TENANT_VIEW,         'Viewed Showroom Details'),
        (ACTION_DEMO_CREATE,         'Created Demo Lead / Meeting'),
        (ACTION_DEMO_UPDATE,         'Updated Demo Lead / Meeting'),
        (ACTION_DEMO_COMPLETE,       'Completed Demo Meeting'),
        (ACTION_DEMO_CONVERT,        'Converted Lead to Tenant'),
        (ACTION_TICKET_CREATE,       'Created Support Ticket'),
        (ACTION_TICKET_UPDATE,       'Updated Support Ticket'),
        (ACTION_TICKET_RESOLVE,      'Resolved Support Ticket'),
        (ACTION_SUBSCRIPTION_UPDATE, 'Updated Tenant Subscription'),
        (ACTION_PAYMENT_RECORD,      'Recorded Subscription Payment'),
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


# ============================================================================
# 4. Demo Meetings & Lead Management
# ============================================================================

class PlatformDemoLead(models.Model):
    """Prospective jewellery business lead and scheduled software demonstration."""

    STATUS_NEW            = 'new'
    STATUS_CONTACTED      = 'contacted'
    STATUS_SCHEDULED      = 'scheduled'
    STATUS_COMPLETED      = 'completed'
    STATUS_RESCHEDULED    = 'rescheduled'
    STATUS_CANCELLED      = 'cancelled'
    STATUS_NOT_INTERESTED = 'not_interested'

    STATUS_CHOICES = [
        (STATUS_NEW,            'New Lead / Enquiry'),
        (STATUS_CONTACTED,      'Contacted / In Discussion'),
        (STATUS_SCHEDULED,      'Demo Scheduled'),
        (STATUS_COMPLETED,      'Demo Completed'),
        (STATUS_RESCHEDULED,    'Rescheduled'),
        (STATUS_CANCELLED,      'Cancelled'),
        (STATUS_NOT_INTERESTED, 'Not Interested / Lost'),
    ]

    MODE_ONLINE    = 'online'
    MODE_PHONE     = 'phone'
    MODE_IN_PERSON = 'in_person'

    MODE_CHOICES = [
        (MODE_ONLINE,    'Online Video (Google Meet / Zoom)'),
        (MODE_PHONE,     'Phone Consultation'),
        (MODE_IN_PERSON, 'In-Person Showroom Visit'),
    ]

    SOURCE_WEBSITE    = 'website'
    SOURCE_BROCHURE   = 'brochure'
    SOURCE_REFERRAL   = 'referral'
    SOURCE_WHATSAPP   = 'whatsapp'
    SOURCE_EXHIBITION = 'exhibition'
    SOURCE_COLD_CALL  = 'cold_call'
    SOURCE_OTHER      = 'other'

    SOURCE_CHOICES = [
        (SOURCE_WEBSITE,    'Website Landing Page'),
        (SOURCE_BROCHURE,   'Product Brochure Download'),
        (SOURCE_REFERRAL,   'Jeweller Referral'),
        (SOURCE_WHATSAPP,   'WhatsApp / Phone Inquiry'),
        (SOURCE_EXHIBITION, 'Trade Exhibition / Expo'),
        (SOURCE_COLD_CALL,  'Direct Outreach'),
        (SOURCE_OTHER,      'Other'),
    ]

    lead_name = models.CharField(
        max_length=200,
        help_text="Showroom or jewellery business name"
    )
    contact_name = models.CharField(
        max_length=150,
        help_text="Contact person or owner name"
    )
    email = models.EmailField(blank=True)
    phone = models.CharField(
        max_length=30,
        help_text="Primary mobile or WhatsApp number"
    )
    city = models.CharField(max_length=100, blank=True)
    business_type = models.CharField(
        max_length=20,
        choices=[
            ('RETAIL',    'Retail Jewellery Showroom'),
            ('WHOLESALE', 'Wholesaler / Supplier'),
            ('BOTH',      'Retail & Wholesale (Hybrid)'),
            ('OTHER',     'Other Jewellery Firm'),
        ],
        default='RETAIL'
    )
    business_size = models.CharField(
        max_length=60,
        blank=True,
        help_text="e.g. Single counter, 2-5 counters, Multi-branch"
    )
    source = models.CharField(
        max_length=30,
        choices=SOURCE_CHOICES,
        default=SOURCE_WEBSITE
    )
    requested_datetime = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Scheduled demo date and time"
    )
    assigned_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_demo_leads',
        help_text="Product specialist assigned to conduct this demo"
    )
    meeting_mode = models.CharField(
        max_length=20,
        choices=MODE_CHOICES,
        default=MODE_ONLINE
    )
    meeting_link = models.CharField(
        max_length=300,
        blank=True,
        help_text="Online meeting link (Google Meet / Zoom) or physical meeting address"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
        db_index=True
    )
    follow_up_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date for next follow-up touchpoint"
    )
    next_action = models.CharField(
        max_length=255,
        blank=True,
        help_text="Immediate next action (e.g. Send quote, call on Tuesday)"
    )
    notes = models.TextField(
        blank=True,
        help_text="Interaction history, feature requirements, notes"
    )
    converted_tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='originating_demo_leads',
        help_text="Showroom tenant account created if lead converted"
    )
    conversion_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Platform Demo Lead'
        verbose_name_plural = 'Platform Demo Leads'

    def __str__(self):
        return f"{self.lead_name} ({self.contact_name}) - {self.get_status_display()}"

    @property
    def is_upcoming_meeting(self):
        from django.utils import timezone
        return (
            self.status == self.STATUS_SCHEDULED and
            self.requested_datetime is not None and
            self.requested_datetime >= timezone.now()
        )

    @property
    def is_overdue_followup(self):
        from django.utils import timezone
        if self.follow_up_date and self.status not in (self.STATUS_COMPLETED, self.STATUS_CANCELLED, self.STATUS_NOT_INTERESTED):
            return self.follow_up_date < timezone.localdate()
        return False

    @property
    def is_converted(self):
        return self.converted_tenant_id is not None


# ============================================================================
# 5. Support Tickets & Customer Feedback
# ============================================================================

class PlatformSupportTicket(models.Model):
    """Customer support, issue tracking, and feature feedback for platform administrators."""

    PRIORITY_LOW    = 'low'
    PRIORITY_MEDIUM = 'medium'
    PRIORITY_HIGH   = 'high'
    PRIORITY_URGENT = 'urgent'

    PRIORITY_CHOICES = [
        (PRIORITY_LOW,    'Low'),
        (PRIORITY_MEDIUM, 'Medium'),
        (PRIORITY_HIGH,   'High'),
        (PRIORITY_URGENT, 'Urgent / Critical'),
    ]

    STATUS_OPEN           = 'open'
    STATUS_IN_PROGRESS    = 'in_progress'
    STATUS_WAITING_CLIENT = 'waiting_client'
    STATUS_RESOLVED       = 'resolved'
    STATUS_CLOSED         = 'closed'

    STATUS_CHOICES = [
        (STATUS_OPEN,           'Open'),
        (STATUS_IN_PROGRESS,    'In Progress'),
        (STATUS_WAITING_CLIENT, 'Waiting on Client'),
        (STATUS_RESOLVED,       'Resolved'),
        (STATUS_CLOSED,         'Closed'),
    ]

    CATEGORY_TECH       = 'technical'
    CATEGORY_BILLING    = 'billing'
    CATEGORY_FEATURE    = 'feature_request'
    CATEGORY_ONBOARDING = 'onboarding'
    CATEGORY_BUG        = 'bug'
    CATEGORY_FEEDBACK   = 'feedback'
    CATEGORY_GENERAL    = 'general'

    CATEGORY_CHOICES = [
        (CATEGORY_TECH,       'Technical Issue'),
        (CATEGORY_BILLING,    'Billing & Subscription'),
        (CATEGORY_FEATURE,    'Feature Request'),
        (CATEGORY_ONBOARDING, 'Onboarding / Training'),
        (CATEGORY_BUG,        'Bug Report'),
        (CATEGORY_FEEDBACK,   'Showroom Feedback'),
        (CATEGORY_GENERAL,    'General Inquiry'),
    ]

    ticket_number = models.CharField(
        max_length=40,
        unique=True,
        db_index=True
    )
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_tickets',
        help_text="Showroom tenant reporting the issue (if registered)"
    )
    contact_name = models.CharField(max_length=150)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_GENERAL
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default=PRIORITY_MEDIUM
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
        db_index=True
    )
    subject = models.CharField(max_length=255)
    description = models.TextField()
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_support_tickets'
    )
    resolution_notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Platform Support Ticket'
        verbose_name_plural = 'Platform Support Tickets'

    def __str__(self):
        return f"{self.ticket_number} - {self.subject} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            import random
            from django.utils import timezone
            year = timezone.localdate().year
            last = PlatformSupportTicket.objects.order_by('-id').first()
            next_id = (last.id + 1) if last else random.randint(1001, 1999)
            self.ticket_number = f"TICK-{year}-{next_id:04d}"
        super().save(*args, **kwargs)

