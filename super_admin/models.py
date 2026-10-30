"""
super_admin/models.py
---------------------
Data models for the JewelDesk Super Admin Platform.
Provides append-only audit logging for platform-level actions and customer impersonation.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from accounts.models import validate_email_address, validate_proper_email


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
    ACTION_LEAD_CREATE         = 'LEAD_CREATE'
    ACTION_LEAD_UPDATE         = 'LEAD_UPDATE'
    ACTION_LEAD_NOTE           = 'LEAD_NOTE'
    ACTION_LEAD_STATUS_UPDATE  = 'LEAD_STATUS_UPDATE'
    ACTION_TICKET_CREATE       = 'TICKET_CREATE'
    ACTION_TICKET_UPDATE       = 'TICKET_UPDATE'
    ACTION_TICKET_RESOLVE      = 'TICKET_RESOLVE'
    ACTION_SUBSCRIPTION_UPDATE = 'SUBSCRIPTION_UPDATE'
    ACTION_PAYMENT_RECORD      = 'PAYMENT_RECORD'
    ACTION_COUPON_TEMPLATE_CREATE  = 'COUPON_TEMPLATE_CREATE'
    ACTION_COUPON_TEMPLATE_UPDATE  = 'COUPON_TEMPLATE_UPDATE'
    ACTION_COUPON_TEMPLATE_ARCHIVE = 'COUPON_TEMPLATE_ARCHIVE'
    ACTION_COUPON_BATCH_GENERATE   = 'COUPON_BATCH_GENERATE'

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
        (ACTION_LEAD_CREATE,         'Created Lead'),
        (ACTION_LEAD_UPDATE,         'Updated Lead'),
        (ACTION_LEAD_NOTE,           'Added Lead Follow-up Note'),
        (ACTION_LEAD_STATUS_UPDATE,  'Updated Lead Status'),
        (ACTION_TICKET_CREATE,       'Created Support Ticket'),
        (ACTION_TICKET_UPDATE,       'Updated Support Ticket'),
        (ACTION_TICKET_RESOLVE,      'Resolved Support Ticket'),
        (ACTION_SUBSCRIPTION_UPDATE, 'Updated Tenant Subscription'),
        (ACTION_PAYMENT_RECORD,      'Recorded Subscription Payment'),
        (ACTION_COUPON_TEMPLATE_CREATE,  'Created Coupon Design Template'),
        (ACTION_COUPON_TEMPLATE_UPDATE,  'Updated Coupon Design Template'),
        (ACTION_COUPON_TEMPLATE_ARCHIVE, 'Archived/Unarchived Coupon Template'),
        (ACTION_COUPON_BATCH_GENERATE,   'Generated Coupon Print Batch'),
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
        (PLAN_TRIAL,      '15-Day Free Trial'),
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
    STATUS_EXPIRED      = 'expired'

    STATUS_CHOICES = [
        (STATUS_ACTIVE,       'Active (Paid)'),
        (STATUS_TRIAL,        'Free Trial (Active)'),
        (STATUS_GRACE_PERIOD, 'Grace Period'),
        (STATUS_OVERDUE,      'Payment Overdue'),
        (STATUS_SUSPENDED,    'Suspended'),
        (STATUS_EXPIRED,      'Trial Expired'),
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
    trial_extended = models.BooleanField(
        default=False,
        help_text="Whether this trial has been extended by platform administration"
    )
    trial_extended_at = models.DateTimeField(
        null=True,
        blank=True
    )
    trial_extension_days = models.PositiveIntegerField(
        default=0,
        help_text="Cumulative number of days added via extensions"
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
    def is_trial(self):
        """Return True if this subscription is a trial plan or in trial status."""
        return self.plan_name == self.PLAN_TRIAL or self.status == self.STATUS_TRIAL

    @property
    def is_trial_extended(self):
        """Return True if this trial has been extended beyond the initial 15 days or explicitly marked extended."""
        if not self.is_trial:
            return False
        if getattr(self, 'trial_extended', False):
            return True
        if self.notes and 'extend' in self.notes.lower():
            return True
        if self.expires_at and self.started_at:
            duration = self.expires_at - self.started_at
            if duration.total_seconds() > 15.5 * 86400:
                return True
        if self.days_remaining is not None and self.days_remaining > 15:
            return True
        return False

    @property
    def is_expired(self):
        """Check whether this subscription has expired based on current server-time."""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    @property
    def days_remaining(self):
        """Number of full days remaining in trial or subscription."""
        if not self.expires_at:
            return None
        now = timezone.now()
        if now >= self.expires_at:
            return 0
        diff = self.expires_at - now
        return max(0, diff.days + (1 if diff.seconds > 0 else 0))

    @property
    def is_valid_active(self):
        """
        Check if subscription allows active operations.
        Returns False if expired, suspended, or inactive.
        """
        if self.status in (self.STATUS_SUSPENDED, self.STATUS_EXPIRED):
            return False
        if self.is_expired:
            return False
        return self.status in (self.STATUS_ACTIVE, self.STATUS_TRIAL, self.STATUS_GRACE_PERIOD)

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
    trial_extended = models.BooleanField(
        default=False,
        help_text="Whether this trial has been extended by platform administration"
    )
    trial_extended_at = models.DateTimeField(
        null=True,
        blank=True
    )
    trial_extension_days = models.PositiveIntegerField(
        default=0,
        help_text="Cumulative number of days added via extensions"
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
        blank=True,
        validators=[validate_email_address]
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
    STATUS_INTERESTED     = 'interested'
    STATUS_SCHEDULED      = 'scheduled'
    STATUS_COMPLETED      = 'completed'
    STATUS_CONVERTED      = 'converted'
    STATUS_RESCHEDULED    = 'rescheduled'
    STATUS_CANCELLED      = 'cancelled'
    STATUS_NOT_INTERESTED = 'not_interested'

    STATUS_CHOICES = [
        (STATUS_NEW,            'New Lead / Enquiry'),
        (STATUS_CONTACTED,      'Contacted / In Discussion'),
        (STATUS_INTERESTED,     'Interested'),
        (STATUS_SCHEDULED,      'Demo Scheduled'),
        (STATUS_COMPLETED,      'Demo Completed'),
        (STATUS_CONVERTED,      'Converted'),
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

    SOURCE_WEBSITE        = 'website'
    SOURCE_REFERRAL       = 'referral'
    SOURCE_SOCIAL_MEDIA   = 'social_media'
    SOURCE_DIRECT_CONTACT = 'direct_contact'
    SOURCE_WHATSAPP       = 'whatsapp'
    SOURCE_BROCHURE       = 'brochure'
    SOURCE_EXHIBITION     = 'exhibition'
    SOURCE_COLD_CALL      = 'cold_call'
    SOURCE_OTHER          = 'other'

    SOURCE_CHOICES = [
        (SOURCE_WEBSITE,        'Website'),
        (SOURCE_REFERRAL,       'Referral'),
        (SOURCE_SOCIAL_MEDIA,   'Social Media'),
        (SOURCE_DIRECT_CONTACT, 'Direct Contact / Visit'),
        (SOURCE_WHATSAPP,       'WhatsApp'),
        (SOURCE_BROCHURE,       'Product Brochure Download'),
        (SOURCE_EXHIBITION,     'Trade Exhibition / Expo'),
        (SOURCE_COLD_CALL,      'Direct Outreach'),
        (SOURCE_OTHER,          'Other'),
    ]

    lead_name = models.CharField(
        max_length=200,
        help_text="Showroom or jewellery business name"
    )
    contact_name = models.CharField(
        max_length=150,
        help_text="Contact person or owner name"
    )
    email = models.EmailField(blank=True, validators=[validate_email_address])
    phone = models.CharField(
        max_length=30,
        help_text="Primary mobile or WhatsApp number"
    )
    city = models.CharField(max_length=100, blank=True)
    address = models.TextField(blank=True, help_text="Full showroom/business street address")
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
        return self.converted_tenant_id is not None or self.status in (self.STATUS_CONVERTED, self.STATUS_COMPLETED)


class PlatformLeadNote(models.Model):
    """Timestamped follow-up note and interaction log for a demo lead."""

    lead = models.ForeignKey(
        PlatformDemoLead,
        on_delete=models.CASCADE,
        related_name='followup_notes'
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lead_notes',
        help_text="Platform staff member who logged this note"
    )
    note = models.TextField(help_text="Details of interaction, call notes, or customer response")
    follow_up_date = models.DateField(null=True, blank=True, help_text="Next scheduled follow-up date")
    status_at_note = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Platform Lead Note'
        verbose_name_plural = 'Platform Lead Notes'

    def __str__(self):
        author_name = self.author.username if self.author else 'System'
        return f"Note on {self.lead.lead_name} by {author_name} at {self.created_at:%Y-%m-%d %H:%M}"


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
    STATUS_WAITING_CUSTOMER = 'waiting_client'
    STATUS_RESOLVED       = 'resolved'
    STATUS_CLOSED         = 'closed'

    STATUS_CHOICES = [
        (STATUS_OPEN,           'Open'),
        (STATUS_IN_PROGRESS,    'In Progress'),
        (STATUS_WAITING_CLIENT, 'Waiting on Client'),
        (STATUS_RESOLVED,       'Resolved'),
        (STATUS_CLOSED,         'Closed'),
    ]

    CATEGORY_ACCOUNT    = 'account'
    CATEGORY_BILLING    = 'billing'
    CATEGORY_INVENTORY  = 'inventory'
    CATEGORY_SALES      = 'sales'
    CATEGORY_CUSTOMERS  = 'customers'
    CATEGORY_REPORTS    = 'reports'
    CATEGORY_COUPONS    = 'coupons'
    CATEGORY_WHOLESALE  = 'wholesale'
    CATEGORY_TECH       = 'technical'
    CATEGORY_OTHER      = 'other'
    CATEGORY_FEATURE    = 'feature_request'
    CATEGORY_ONBOARDING = 'onboarding'
    CATEGORY_BUG        = 'bug'
    CATEGORY_FEEDBACK   = 'feedback'
    CATEGORY_GENERAL    = 'general'

    CATEGORY_CHOICES = [
        (CATEGORY_ACCOUNT,    'Login / Account'),
        (CATEGORY_BILLING,    'Billing & Subscription'),
        (CATEGORY_INVENTORY,  'Inventory & Stock'),
        (CATEGORY_SALES,      'Sales & Billing'),
        (CATEGORY_CUSTOMERS,  'Customer Management'),
        (CATEGORY_REPORTS,    'Reports & Analytics'),
        (CATEGORY_COUPONS,    'Coupons & Promotions'),
        (CATEGORY_WHOLESALE,  'Wholesale & Karigar'),
        (CATEGORY_TECH,       'Technical Issue'),
        (CATEGORY_OTHER,      'Other Inquiry'),
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
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_support_tickets',
        help_text="User who raised the ticket"
    )
    contact_name = models.CharField(max_length=150)
    contact_email = models.EmailField(blank=True, validators=[validate_email_address])
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
    attachment = models.FileField(
        upload_to='support_attachments/%Y/%m/',
        null=True,
        blank=True,
        help_text="Optional issue screenshot or attachment"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_support_tickets'
    )
    ai_suggested_category = models.CharField(max_length=50, blank=True)
    ai_suggested_priority = models.CharField(max_length=20, blank=True)
    ai_summary = models.TextField(blank=True, help_text="AI-generated concise summary for support team")
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


class PlatformTicketMessage(models.Model):
    """Threaded conversation message or internal staff note on a support ticket."""

    SENDER_CUSTOMER = 'customer'
    SENDER_STAFF    = 'staff'
    SENDER_AI       = 'ai'
    SENDER_SYSTEM   = 'system'

    SENDER_CHOICES = [
        (SENDER_CUSTOMER, 'Customer / Showroom'),
        (SENDER_STAFF,    'Support Specialist'),
        (SENDER_AI,       'AI Support Assistant'),
        (SENDER_SYSTEM,   'System Notification'),
    ]

    ticket = models.ForeignKey(
        PlatformSupportTicket,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_ticket_messages'
    )
    sender_type = models.CharField(
        max_length=20,
        choices=SENDER_CHOICES,
        default=SENDER_CUSTOMER
    )
    sender_name = models.CharField(max_length=150, blank=True)
    message = models.TextField()
    attachment = models.FileField(
        upload_to='support_attachments/%Y/%m/',
        null=True,
        blank=True
    )
    is_internal = models.BooleanField(
        default=False,
        help_text="Internal note only visible to platform support staff, never to customer."
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Ticket Message'
        verbose_name_plural = 'Ticket Messages'

    def __str__(self):
        return f"{self.ticket.ticket_number} - {self.get_sender_type_display()}: {self.message[:40]}"


class SupportChatSession(models.Model):
    """AI Support Assistant conversation session for authenticated users."""

    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='support_chat_sessions'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='support_chat_sessions'
    )
    session_key = models.CharField(max_length=64, blank=True, db_index=True)
    title = models.CharField(max_length=255, default='New Support Conversation')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Support Chat Session'
        verbose_name_plural = 'Support Chat Sessions'

    def __str__(self):
        return f"Chat #{self.id} - {self.user.username} ({self.updated_at.strftime('%d %b %H:%M')})"


class SupportChatMessage(models.Model):
    """Individual message within a SupportChatSession."""

    ROLE_USER      = 'user'
    ROLE_ASSISTANT = 'assistant'
    ROLE_SYSTEM    = 'system'

    ROLE_CHOICES = [
        (ROLE_USER,      'User'),
        (ROLE_ASSISTANT, 'AI Assistant'),
        (ROLE_SYSTEM,    'System'),
    ]

    session = models.ForeignKey(
        SupportChatSession,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_USER)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Support Chat Message'
        verbose_name_plural = 'Support Chat Messages'

    def __str__(self):
        return f"[{self.role}] {self.content[:40]}"


# ============================================================================
# 6. Coupon Designer, Discount Templates & Print Management
# ============================================================================

class CouponDesignTemplate(models.Model):
    """Reusable coupon design template supporting both built-in luxury presets and custom HTML/CSS."""

    TYPE_BUILT_IN = 'built_in'
    TYPE_CUSTOM   = 'custom'

    TYPE_CHOICES = [
        (TYPE_BUILT_IN, 'Ready-Made Built-in Template'),
        (TYPE_CUSTOM,   'Custom HTML / CSS Designer'),
    ]

    STYLE_LUXURY_GOLD   = 'luxury_gold'
    STYLE_MINIMAL_WHITE = 'minimal_white'
    STYLE_BOLD_PROMO    = 'bold_promo'
    STYLE_COMPACT_SHEET = 'compact_sheet'

    STYLE_CHOICES = [
        (STYLE_LUXURY_GOLD,   'Royal Heritage Gold (Dark Luxury)'),
        (STYLE_MINIMAL_WHITE, 'Minimalist Diamond White (Boutique Voucher)'),
        (STYLE_BOLD_PROMO,    'Bold Festive Celebration (High Contrast)'),
        (STYLE_COMPACT_SHEET, 'Compact Multi-Voucher Sheet (Perforated)'),
    ]

    DISCOUNT_PERCENTAGE = 'percentage'
    DISCOUNT_FIXED      = 'fixed'

    DISCOUNT_CHOICES = [
        (DISCOUNT_PERCENTAGE, 'Percentage Discount (%)'),
        (DISCOUNT_FIXED,      'Fixed Cash Discount (₹)'),
    ]

    PAGE_SIZE_A4     = 'a4'
    PAGE_SIZE_SINGLE = 'single'

    PAGE_SIZE_CHOICES = [
        (PAGE_SIZE_A4,     'A4 Multi-Coupon Sheet'),
        (PAGE_SIZE_SINGLE, 'Single Voucher per Page'),
    ]

    ORIENTATION_PORTRAIT  = 'portrait'
    ORIENTATION_LANDSCAPE = 'landscape'

    ORIENTATION_CHOICES = [
        (ORIENTATION_PORTRAIT,  'Portrait'),
        (ORIENTATION_LANDSCAPE, 'Landscape'),
    ]

    name = models.CharField(
        max_length=150,
        help_text="Descriptive template name (e.g. 'Diwali Gold Jewellery 20% Off')"
    )
    description = models.TextField(
        blank=True,
        help_text="Internal notes or marketing campaign purpose."
    )
    template_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_BUILT_IN,
        db_index=True
    )
    built_in_style = models.CharField(
        max_length=30,
        choices=STYLE_CHOICES,
        default=STYLE_LUXURY_GOLD
    )
    discount_type = models.CharField(
        max_length=20,
        choices=DISCOUNT_CHOICES,
        default=DISCOUNT_PERCENTAGE
    )
    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('20.00'),
        help_text="Discount percentage (e.g. 20.00 for 20%) or cash value in ₹ (e.g. 1000.00)"
    )
    offer_title = models.CharField(
        max_length=150,
        default="Exclusive Jewellery Privilege Voucher",
        help_text="Headline displayed prominently on the coupon."
    )
    sample_coupon_code = models.CharField(
        max_length=50,
        default="ROYAL-GOLD20",
        help_text="Default/sample promo code used in template previews."
    )
    business_name = models.CharField(
        max_length=150,
        default="JewelDesk Fine Atelier",
        help_text="Business or showroom brand name."
    )
    business_logo_url = models.URLField(
        blank=True,
        help_text="Optional absolute URL to showroom brand insignia image."
    )
    valid_from = models.DateField(
        null=True,
        blank=True,
        help_text="Optional campaign start date."
    )
    valid_until = models.DateField(
        null=True,
        blank=True,
        help_text="Expiration date displayed on the coupon."
    )
    minimum_purchase = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('10000.00'),
        help_text="Minimum invoice purchase amount in ₹ to redeem."
    )
    maximum_discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional maximum discount cap in ₹ for percentage offers."
    )
    applicable_categories = models.CharField(
        max_length=200,
        default="Gold, Diamond & Polki Jewellery",
        blank=True,
        help_text="Eligible product categories."
    )
    terms_and_conditions = models.TextField(
        default="1. Valid on select gold, diamond, and silver ornament purchases.\n"
                "2. Cannot be combined with raw bullion bar rates or ongoing offers.\n"
                "3. One voucher per customer transaction. Original voucher required at billing.",
        blank=True
    )
    show_barcode = models.BooleanField(
        default=True,
        help_text="Render vector Code 128 barcode badge."
    )
    show_qr_code = models.BooleanField(
        default=True,
        help_text="Render QR code verification badge."
    )
    primary_color = models.CharField(
        max_length=30,
        default="#d4af37",
        help_text="Primary accent/border color (hex, e.g. #d4af37 for gold)"
    )
    background_color = models.CharField(
        max_length=30,
        default="#160f09",
        help_text="Card background color (hex, e.g. #160f09 for dark velvet)"
    )
    text_color = models.CharField(
        max_length=30,
        default="#fef9ed",
        help_text="Primary text color"
    )

    # Physical Page Dimensions & Multi-Coupon Grid Settings
    page_size = models.CharField(
        max_length=20,
        choices=PAGE_SIZE_CHOICES,
        default=PAGE_SIZE_A4
    )
    orientation = models.CharField(
        max_length=20,
        choices=ORIENTATION_CHOICES,
        default=ORIENTATION_PORTRAIT
    )
    coupon_width_mm = models.PositiveIntegerField(
        default=180,
        help_text="Coupon width in millimeters"
    )
    coupon_height_mm = models.PositiveIntegerField(
        default=70,
        help_text="Coupon height in millimeters"
    )
    grid_columns = models.PositiveIntegerField(
        default=1,
        help_text="Coupons per row on sheet layout (e.g. 1 or 2)"
    )
    grid_rows = models.PositiveIntegerField(
        default=3,
        help_text="Coupons per column on sheet layout (e.g. 3 or 4)"
    )
    margin_mm = models.PositiveIntegerField(
        default=8,
        help_text="Page margin in millimeters"
    )
    spacing_mm = models.PositiveIntegerField(
        default=6,
        help_text="Spacing between coupons in millimeters"
    )

    # Custom Code Editor Fields
    custom_html = models.TextField(
        blank=True,
        help_text="Custom HTML layout with dynamic placeholders: {{coupon_code}}, {{discount_value}}, etc."
    )
    custom_css = models.TextField(
        blank=True,
        help_text="Custom print-friendly CSS rules."
    )

    is_archived = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Archived templates are hidden from active selection."
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_coupon_templates'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True
    )
    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ['-updated_at', '-created_at']
        verbose_name = 'Coupon Design Template'
        verbose_name_plural = 'Coupon Design Templates'

    def __str__(self):
        type_lbl = self.get_template_type_display()
        return f"{self.name} [{type_lbl}]"

    @property
    def formatted_discount(self):
        if self.discount_type == self.DISCOUNT_PERCENTAGE:
            val = int(self.discount_value) if self.discount_value % 1 == 0 else self.discount_value
            return f"{val}% OFF"
        val = int(self.discount_value) if self.discount_value % 1 == 0 else self.discount_value
        return f"₹{val:,.0f} OFF" if isinstance(val, (int, float, Decimal)) and val % 1 == 0 else f"₹{val} OFF"

    @property
    def capacity_per_sheet(self):
        return max(1, self.grid_columns * self.grid_rows)


class CouponPrintBatch(models.Model):
    """A generated print run of coupons with either identical or unique collision-resistant codes."""

    BATCH_IDENTICAL = 'identical'
    BATCH_UNIQUE    = 'unique_codes'

    BATCH_TYPE_CHOICES = [
        (BATCH_IDENTICAL, 'Identical Promotional Artwork (Single Shared Code)'),
        (BATCH_UNIQUE,    'Individual Unique Voucher Codes'),
    ]

    batch_number = models.CharField(
        max_length=40,
        unique=True,
        db_index=True,
        help_text="Unique batch identifier (e.g. BATCH-2026-001)"
    )
    template = models.ForeignKey(
        CouponDesignTemplate,
        on_delete=models.CASCADE,
        related_name='print_batches'
    )
    name = models.CharField(
        max_length=150,
        help_text="Title or campaign descriptor for this print run."
    )
    batch_type = models.CharField(
        max_length=30,
        choices=BATCH_TYPE_CHOICES,
        default=BATCH_UNIQUE
    )
    total_quantity = models.PositiveIntegerField(
        default=1,
        help_text="Number of coupon vouchers to generate and print."
    )
    shared_code = models.CharField(
        max_length=50,
        blank=True,
        help_text="Single common promo code if using identical artwork (e.g. 'DIWALI2026')"
    )
    code_prefix = models.CharField(
        max_length=20,
        default='JD-',
        help_text="Prefix for unique code generation (e.g. 'GOLD-', 'VIP-')"
    )
    code_length = models.PositiveIntegerField(
        default=8,
        help_text="Length of random characters in unique code."
    )
    include_serial_numbers = models.BooleanField(
        default=True,
        help_text="Include sequential serial numbering (e.g. #0001, #0002)"
    )
    serial_start = models.PositiveIntegerField(
        default=1,
        help_text="Starting sequential serial number."
    )

    # Immutably captured campaign snapshot fields
    offer_title = models.CharField(max_length=150)
    discount_type = models.CharField(max_length=20)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    business_name = models.CharField(max_length=150)
    minimum_purchase = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    maximum_discount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    applicable_categories = models.CharField(max_length=200, blank=True)
    terms_and_conditions = models.TextField(blank=True)

    grid_columns = models.PositiveIntegerField(default=1)
    grid_rows = models.PositiveIntegerField(default=3)
    margin_mm = models.PositiveIntegerField(default=8)
    spacing_mm = models.PositiveIntegerField(default=6)

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_coupon_batches'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Coupon Print Batch'
        verbose_name_plural = 'Coupon Print Batches'

    def __str__(self):
        return f"{self.batch_number} - {self.name} ({self.total_quantity} coupons)"

    @property
    def formatted_discount(self):
        if self.discount_type == CouponDesignTemplate.DISCOUNT_PERCENTAGE:
            val = int(self.discount_value) if self.discount_value % 1 == 0 else self.discount_value
            return f"{val}% OFF"
        val = int(self.discount_value) if self.discount_value % 1 == 0 else self.discount_value
        return f"₹{val:,.0f} OFF" if isinstance(val, (int, float, Decimal)) and val % 1 == 0 else f"₹{val} OFF"

    @property
    def sheet_count(self):
        per_sheet = max(1, self.grid_columns * self.grid_rows)
        import math
        return math.ceil(self.total_quantity / per_sheet)


class CouponBatchItem(models.Model):
    """An individual coupon instance in a print batch with its unique code and serial number."""

    batch = models.ForeignKey(
        CouponPrintBatch,
        on_delete=models.CASCADE,
        related_name='items'
    )
    serial_number = models.PositiveIntegerField()
    coupon_code = models.CharField(
        max_length=60,
        db_index=True,
        help_text="Promo code printed on the coupon (identical or unique)."
    )
    is_redeemed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Promotional redemption tracker."
    )
    redeemed_at = models.DateTimeField(
        null=True,
        blank=True
    )
    redemption_note = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional POS invoice or counter reference when claimed."
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['batch', 'serial_number']
        unique_together = [['batch', 'serial_number']]
        verbose_name = 'Coupon Batch Item'
        verbose_name_plural = 'Coupon Batch Items'

    def __str__(self):
        return f"#{self.serial_number:04d} [{self.coupon_code}] - {self.batch.batch_number}"


