"""
accounts/test_tenant_trial.py
-----------------------------
Comprehensive automated test suite for Phase 2: Tenant-Based 15-Day Free Trial
and Trial Expiry Management in JwelDesk.

Tests:
1. Automatic 15-day trial creation for newly registered Tenant.
2. Trial start and expiry date precision.
3. Prevention of duplicate trial creation (idempotency & DB uniqueness).
4. Active trial grants full business operational access.
5. Expired trial blocks business functionality server-side.
6. API & AJAX endpoints return structured JSON 403 when expired.
7. Employees share identical trial status and expiry as their Tenant.
8. Multiple branches share identical trial status as their Tenant.
9. Platform superusers remain completely exempt.
10. Existing customer subscriptions (core/paid) remain completely protected and unchanged.
11. Expired trial preserves all business records (zero data loss).
12. Trial expired page renders renewal contact channels and allows clean logout.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, CompanySettings
from super_admin.models import TenantSubscription
from super_admin.trial_services import create_tenant_trial, is_tenant_subscription_active
from team.models import Branch, Employee, Role

User = get_user_model()


class TenantTrialCreationTests(TestCase):
    """Test automatic provisioning, dates, and idempotency of 15-day Free Trials."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='trial_owner_1',
            email='trial1@jeweller.test',
            password='Password123!'
        )

    def test_new_tenant_auto_provisions_15_day_trial(self):
        """Newly created Tenant automatically receives a 15-day active trial subscription."""
        before = timezone.now()
        tenant = Tenant.objects.create(
            name='Ambika Jewellers',
            owner=self.owner,
            business_type=Tenant.TYPE_RETAIL
        )
        create_tenant_trial(tenant)
        after = timezone.now()

        # Subscription must exist and be attached to the Tenant
        self.assertTrue(hasattr(tenant, 'subscription'))
        sub = tenant.subscription
        self.assertIsNotNone(sub)
        self.assertEqual(sub.plan_name, TenantSubscription.PLAN_TRIAL)
        self.assertEqual(sub.status, TenantSubscription.STATUS_ACTIVE)
        self.assertEqual(sub.price, Decimal('0.00'))
        self.assertEqual(sub.payment_status, TenantSubscription.PAYMENT_WAIVED)

        # Start date must be server-side timezone.now()
        self.assertTrue(before <= sub.started_at <= after)

        # Expiry date must be exactly 15 days from started_at
        diff = sub.expires_at - sub.started_at
        self.assertEqual(diff.days, 15)
        self.assertTrue(sub.is_trial)
        self.assertFalse(sub.is_expired)
        self.assertTrue(sub.is_valid_active)
        self.assertEqual(sub.days_remaining, 15)

    def test_prevent_duplicate_trial_creation(self):
        """Calling create_tenant_trial multiple times is idempotent and never creates duplicate rows."""
        tenant = Tenant.objects.create(
            name='Shreeji Ornaments',
            owner=self.owner,
            business_type=Tenant.TYPE_RETAIL
        )
        create_tenant_trial(tenant)

        initial_sub = tenant.subscription
        initial_sub_id = initial_sub.id

        # Attempt to create again
        second_sub = create_tenant_trial(tenant)
        self.assertEqual(second_sub.id, initial_sub_id)

        # Database must strictly have 1 row for this tenant
        self.assertEqual(TenantSubscription.objects.filter(tenant=tenant).count(), 1)


    def test_signup_auto_provisions_15_day_trial(self):
        """Newly registered tenant through signup form automatically receives a 15-day trial."""
        from accounts.forms import JewelDeskSignUpForm
        form = JewelDeskSignUpForm(data={
            'first_name': 'Hasmukh Soni',
            'shop_name': 'Hasmukh Ornaments',
            'business_type': Tenant.TYPE_RETAIL,
            'email': 'hasmukh@soni.test',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        tenant = user.owned_tenants.first()
        self.assertIsNotNone(tenant)
        self.assertTrue(hasattr(tenant, 'subscription'))
        self.assertEqual(tenant.subscription.plan_name, TenantSubscription.PLAN_TRIAL)
        self.assertEqual((tenant.subscription.expires_at - tenant.subscription.started_at).days, 15)


class TenantTrialEnforcementTests(TestCase):
    """Test server-side access enforcement for active, expired, employee, and branch contexts."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='shop_owner_raj',
            email='raj@soni.test',
            password='Password123!'
        )
        self.tenant = Tenant.objects.create(
            name='Raj Soni Jewellers',
            owner=self.owner,
            business_type=Tenant.TYPE_BOTH
        )
        create_tenant_trial(self.tenant)
        CompanySettings.objects.create(tenant=self.tenant, company_name=self.tenant.name)

        # Ensure default branch & admin employee profile for owner
        Branch.ensure_default_branch(self.tenant)
        Employee.ensure_tenant_admin(self.tenant, self.owner)

        self.client = Client()

    def test_active_trial_allows_full_business_access(self):
        """Tenants with an active trial have normal access to dashboard and operational views."""
        self.client.force_login(self.owner)

        # Access dashboard
        res_dash = self.client.get(reverse('dashboard'))
        self.assertEqual(res_dash.status_code, 200)

        # Access wholesale dashboard
        res_wholesale = self.client.get(reverse('wholesale:dashboard'))
        self.assertEqual(res_wholesale.status_code, 200)

    def test_expired_trial_blocks_normal_views_and_redirects(self):
        """When the trial expires, any business access redirects to /accounts/trial-expired/."""
        # Fast-forward trial expiry to the past
        sub = self.tenant.subscription
        sub.expires_at = timezone.now() - timedelta(hours=2)
        sub.save()

        self.client.force_login(self.owner)

        # Attempting to access dashboard must redirect to trial-expired
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('accounts:trial_expired'), res.url)

        # Follow redirect to trial expired page
        res_page = self.client.get(reverse('accounts:trial_expired'))
        self.assertEqual(res_page.status_code, 200)
        self.assertContains(res_page, "Raj Soni Jewellers")
        self.assertContains(res_page, "15-Day Free Trial Concluded")
        self.assertContains(res_page, "Your Business Data Is 100% Safe")

    def test_expired_trial_protects_api_endpoints_with_json_403(self):
        """API endpoints requested while expired return HTTP 403 with JSON error payload."""
        sub = self.tenant.subscription
        sub.expires_at = timezone.now() - timedelta(days=1)
        sub.save()

        self.client.force_login(self.owner)

        # AJAX request to a business route
        res = self.client.get(
            reverse('wholesale:dashboard'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 403)
        data = res.json()
        self.assertEqual(data.get('error'), 'trial_expired')
        self.assertIn("Raj Soni Jewellers", data.get('message', ''))
        self.assertIn('support_contact', data)

    def test_employees_share_same_tenant_trial_status(self):
        """Employees belonging to the Tenant share the exact same trial status."""
        emp_user = User.objects.create_user(
            username='sales_clerk_anil',
            email='anil@shop.test',
            password='Password123!'
        )
        emp_role, _ = Role.objects.get_or_create(
            name='Sales Associate',
            tenant=self.tenant
        )
        Employee.objects.create(
            user=emp_user,
            tenant=self.tenant,
            full_name='Anil Kumar',
            role=emp_role,
            status=Employee.STATUS_ACTIVE
        )

        emp_client = Client()
        emp_client.force_login(emp_user)

        # 1. While trial is active, employee has access
        res_active = emp_client.get(reverse('dashboard'))
        self.assertEqual(res_active.status_code, 200)

        # 2. Expire the Tenant's trial
        sub = self.tenant.subscription
        sub.expires_at = timezone.now() - timedelta(minutes=10)
        sub.save()

        # Employee must now be blocked
        res_blocked = emp_client.get(reverse('dashboard'))
        self.assertEqual(res_blocked.status_code, 302)
        self.assertIn(reverse('accounts:trial_expired'), res_blocked.url)

        # Employee visiting trial-expired page sees staff guidance
        res_page = emp_client.get(reverse('accounts:trial_expired'))
        self.assertEqual(res_page.status_code, 200)
        self.assertContains(res_page, "Staff Member Notice")

    def test_multiple_branches_share_same_tenant_trial(self):
        """All branches belonging to one Tenant share the same trial status."""
        # Create Branch 2
        branch_2 = Branch.objects.create(
            tenant=self.tenant,
            name='Branch 2 - Market Counter',
            code='BR2',
            is_active=True
        )

        self.client.force_login(self.owner)
        session = self.client.session
        session[f'active_branch_id_{self.tenant.id}'] = branch_2.id
        session.save()

        # Expire the trial
        sub = self.tenant.subscription
        sub.expires_at = timezone.now() - timedelta(days=2)
        sub.save()

        # Branch 2 request must be blocked
        res = self.client.get(reverse('wholesale:dashboard'))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('accounts:trial_expired'), res.url)

    def test_platform_superuser_remains_exempt(self):
        """Platform superusers are never blocked by tenant trial expiry."""
        super_admin = User.objects.create_superuser(
            username='platform_super',
            email='admin@platform.test',
            password='Password123!'
        )
        # Expire tenant trial
        sub = self.tenant.subscription
        sub.expires_at = timezone.now() - timedelta(days=3)
        sub.save()

        admin_client = Client()
        admin_client.force_login(super_admin)

        # Super Admin portal works
        res_super = admin_client.get(reverse('super_admin:dashboard'))
        self.assertEqual(res_super.status_code, 200)

    def test_expired_trial_preserves_all_business_data(self):
        """Trial expiry strictly blocks access without altering or deleting any business data."""
        from customers.models import Customer
        from wholesale.models import RetailerParty

        # Create business data during trial
        customer = Customer.objects.create(
            tenant=self.tenant,
            name='Kavita Patel',
            mobile='9811122334'
        )
        party = RetailerParty.objects.create(
            tenant=self.tenant,
            name='Surat Wholesale Hub',
            phone='9822233445'
        )

        # Expire trial
        sub = self.tenant.subscription
        sub.expires_at = timezone.now() - timedelta(days=5)
        sub.save()

        # Business access blocked
        self.client.force_login(self.owner)
        res = self.client.get(reverse('customer_list'))
        self.assertEqual(res.status_code, 302)

        # Database records remain 100% intact
        self.assertTrue(Customer.objects.filter(id=customer.id).exists())
        self.assertTrue(RetailerParty.objects.filter(id=party.id).exists())
        self.assertEqual(Customer.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(RetailerParty.objects.filter(tenant=self.tenant).count(), 1)

    def test_existing_paid_subscriptions_remain_unaffected(self):
        """Tenants with paid core/pro plans are never treated as expired trials."""
        paid_owner = User.objects.create_user(
            username='paid_owner_1',
            email='paid@jeweller.test',
            password='Password123!'
        )
        paid_tenant = Tenant.objects.create(
            name='Maharaja Jewellers',
            owner=paid_owner,
            business_type=Tenant.TYPE_RETAIL
        )
        create_tenant_trial(paid_tenant)
        CompanySettings.objects.create(tenant=paid_tenant, company_name=paid_tenant.name)

        # Upgrade to paid subscription expiring 1 year in future
        sub = paid_tenant.subscription
        sub.plan_name = TenantSubscription.PLAN_CORE
        sub.status = TenantSubscription.STATUS_ACTIVE
        sub.expires_at = timezone.now() + timedelta(days=365)
        sub.price = Decimal('24999.00')
        sub.payment_status = TenantSubscription.PAYMENT_PAID
        sub.save()

        paid_client = Client()
        paid_client.force_login(paid_owner)

        res = paid_client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.plan_name, TenantSubscription.PLAN_CORE)
        self.assertFalse(sub.is_trial)
        self.assertTrue(sub.is_valid_active)

    def test_trial_expired_page_renders_contacts_and_allows_logout(self):
        """Trial expired page shows renewal contacts and allows clean logout."""
        sub = self.tenant.subscription
        sub.expires_at = timezone.now() - timedelta(days=2)
        sub.save()

        self.client.force_login(self.owner)
        res = self.client.get(reverse('accounts:trial_expired'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "+91 98765 43210")
        self.assertContains(res, "support@jweldesk.com")
        self.assertContains(res, "Call Support")
        self.assertContains(res, "Chat on WhatsApp")

        # Verify logout works cleanly while in trial-expired state
        res_logout = self.client.post(reverse('accounts:logout'))
        self.assertIn(res_logout.status_code, (200, 302))

    def test_active_tenant_redirected_away_from_trial_expired_page(self):
        """Tenants with active subscriptions attempting to visit trial-expired are redirected to dashboard."""
        self.client.force_login(self.owner)
        res = self.client.get(reverse('accounts:trial_expired'))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('dashboard'), res.url)

    def test_extended_trial_displays_trial_extended_messages(self):
        """When a trial is extended beyond 15 days or flagged as extended, the UI displays 'Trial Extended'."""
        sub = self.tenant.subscription
        sub.expires_at = timezone.now() + timedelta(days=32)
        sub.trial_extended = True
        sub.save()

        self.client.force_login(self.owner)
        res = self.client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)

        # Header, navbar, and hero cards must display 'Trial Extended'
        self.assertContains(res, "Trial Extended")
        self.assertContains(res, "Free Trial Extended")
        self.assertTrue(self.tenant.is_trial_extended)


