"""
super_admin/tests.py
--------------------
Comprehensive security, access-control, tenant-management, and customer-impersonation
test suite for the JewelDesk Super Admin Portal.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import Tenant, CompanySettings
from team.models import Role, Employee
from super_admin.models import PlatformAuditLog

User = get_user_model()


class SuperAdminAccessControlTests(TestCase):
    """Test that unauthorized users are strictly barred from the Super Admin portal."""

    def setUp(self):
        # 1. Platform Superuser
        self.super_admin = User.objects.create_superuser(
            username='platform_superadmin',
            email='superadmin@jeweldesk.test',
            password='Password123!'
        )

        # 2. Showroom Owner (Ordinary Customer)
        self.owner_user = User.objects.create_user(
            username='showroom_owner',
            email='owner@mahalaxmi.test',
            password='Password123!'
        )
        self.tenant_a = Tenant.objects.create(
            name='Mahalaxmi Jewellers',
            slug='mahalaxmi-jewellers',
            owner=self.owner_user,
            is_active=True
        )

        # 3. Normal Staff Member
        self.staff_user = User.objects.create_user(
            username='sales_staff',
            email='staff@mahalaxmi.test',
            password='Password123!'
        )
        role_sales, _ = Role.objects.get_or_create(
            name='Sales',
            defaults={'description': 'Sales Staff', 'is_builtin': True}
        )
        self.employee = Employee.objects.create(
            user=self.staff_user,
            tenant=self.tenant_a,
            employee_id='EMP-0001',
            full_name='Rohan Sharma',
            email='staff@mahalaxmi.test',
            role=role_sales,
            status='Active'
        )

        self.client = Client()

    def test_anonymous_user_redirected_to_login(self):
        """Anonymous requests to /super-admin/ endpoints must be redirected to login."""
        urls = [
            reverse('super_admin:dashboard'),
            reverse('super_admin:showroom_list'),
            reverse('super_admin:showroom_detail', kwargs={'tenant_id': self.tenant_a.id}),
            reverse('super_admin:audit_logs'),
            reverse('super_admin:subscriptions'),
            reverse('super_admin:settings'),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, f"Failed on URL: {url}")
            self.assertIn('/accounts/login/', response.url)

    def test_showroom_owner_rejected_with_403(self):
        """Ordinary showroom owners cannot access any super-admin portal pages."""
        self.client.force_login(self.owner_user)
        urls = [
            reverse('super_admin:dashboard'),
            reverse('super_admin:showroom_list'),
            reverse('super_admin:showroom_detail', kwargs={'tenant_id': self.tenant_a.id}),
            reverse('super_admin:audit_logs'),
            reverse('super_admin:subscriptions'),
            reverse('super_admin:settings'),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, f"Owner was not blocked on: {url}")

    def test_staff_employee_rejected_with_403(self):
        """Normal showroom staff members cannot access super-admin portal pages."""
        self.client.force_login(self.staff_user)
        urls = [
            reverse('super_admin:dashboard'),
            reverse('super_admin:showroom_list'),
            reverse('super_admin:audit_logs'),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, f"Staff was not blocked on: {url}")

    def test_superuser_access_allowed(self):
        """Verified Django superuser has full access to the portal."""
        self.client.force_login(self.super_admin)
        response = self.client.get(reverse('super_admin:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Platform Overview")
        self.assertContains(response, "Mahalaxmi Jewellers")

    def test_normal_storefront_hides_super_admin_link_from_unauthorized_users(self):
        """Normal showroom interface must not display Super Admin links to unauthorized users."""
        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="/super-admin/"')
        self.assertNotContains(response, 'Platform Super Admin')

    def test_super_admin_user_sees_portal_link_in_storefront(self):
        """Superusers visiting the showroom storefront see the discreet Super Admin portal link."""
        self.client.force_login(self.super_admin)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('super_admin:dashboard'))


class SuperAdminTenantManagementTests(TestCase):
    """Test tenant listing, search, filtering, and activation/deactivation."""

    def setUp(self):
        self.super_admin = User.objects.create_superuser(
            username='admin_boss',
            email='boss@platform.test',
            password='Password123!'
        )

        # Tenant 1 (Active)
        self.user_a = User.objects.create_user(username='owner_a', email='a@gold.test')
        self.tenant_a = Tenant.objects.create(
            name='Kalyan Ornaments',
            slug='kalyan-ornaments',
            owner=self.user_a,
            is_active=True
        )

        # Tenant 2 (Inactive / Suspended)
        self.user_b = User.objects.create_user(username='owner_b', email='b@silver.test')
        self.tenant_b = Tenant.objects.create(
            name='Tanishq Reseller',
            slug='tanishq-reseller',
            owner=self.user_b,
            is_active=False
        )

        self.client = Client()
        self.client.force_login(self.super_admin)

    def test_tenant_list_shows_all_tenants_across_platform(self):
        """Authorized super admin can inspect all tenants across the platform."""
        response = self.client.get(reverse('super_admin:showroom_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kalyan Ornaments')
        self.assertContains(response, 'Tanishq Reseller')

    def test_tenant_search_filter(self):
        """Search query properly filters tenants by name or slug."""
        response = self.client.get(reverse('super_admin:showroom_list') + '?q=Kalyan')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kalyan Ornaments')
        self.assertNotContains(response, 'Tanishq Reseller')

    def test_tenant_status_filter(self):
        """Status filter properly isolates active vs inactive tenants."""
        response_active = self.client.get(reverse('super_admin:showroom_list') + '?status=active')
        self.assertContains(response_active, 'Kalyan Ornaments')
        self.assertNotContains(response_active, 'Tanishq Reseller')

        response_inactive = self.client.get(reverse('super_admin:showroom_list') + '?status=inactive')
        self.assertNotContains(response_inactive, 'Kalyan Ornaments')
        self.assertContains(response_inactive, 'Tanishq Reseller')

    def test_tenant_detail_view(self):
        """Tenant detail page displays showroom details and account info."""
        response = self.client.get(reverse('super_admin:showroom_detail', kwargs={'tenant_id': self.tenant_a.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kalyan Ornaments')
        self.assertContains(response, 'owner_a')
        self.assertContains(response, 'Core Plan (Standard Tier)')

    def test_toggle_tenant_status_requires_post_and_reason(self):
        """Toggling tenant status must require POST and a justification reason."""
        # GET request must be rejected
        url = reverse('super_admin:toggle_tenant_status', kwargs={'tenant_id': self.tenant_a.id})
        response_get = self.client.get(url)
        self.assertEqual(response_get.status_code, 405)

        # POST without reason fails with message and does not mutate status
        response_empty = self.client.post(url, {'reason': ''})
        self.tenant_a.refresh_from_db()
        self.assertTrue(self.tenant_a.is_active)

        # POST with reason deactivates tenant and records audit log
        response_valid = self.client.post(url, {'reason': 'Non-payment of subscription fee'})
        self.tenant_a.refresh_from_db()
        self.assertFalse(self.tenant_a.is_active)

        # Verify audit log was created
        log = PlatformAuditLog.objects.filter(
            target_tenant=self.tenant_a,
            action=PlatformAuditLog.ACTION_TENANT_DEACTIVATE
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.super_admin)
        self.assertIn('Non-payment', log.reason)


class CustomerImpersonationSecurityTests(TestCase):
    """Test the complete customer impersonation lifecycle, security boundaries, and exit flow."""

    def setUp(self):
        self.super_admin = User.objects.create_superuser(
            username='admin_alice',
            email='alice@platform.test',
            password='Password123!'
        )

        self.customer_user = User.objects.create_user(
            username='customer_bob',
            email='bob@jewels.test',
            password='CustomerSecretPassword!'
        )
        self.tenant = Tenant.objects.create(
            name='Bob Jewels Atelier',
            slug='bob-jewels-atelier',
            owner=self.customer_user,
            is_active=True
        )

        self.other_admin = User.objects.create_superuser(
            username='other_admin',
            email='other@platform.test',
            password='Password123!'
        )

        self.client = Client()

    def test_impersonation_requires_post_and_confirmation_reason(self):
        """Impersonation cannot be started via GET or without a justification reason."""
        self.client.force_login(self.super_admin)
        url = reverse('super_admin:impersonate_start', kwargs={'tenant_id': self.tenant.id})

        # GET request blocked (405)
        response_get = self.client.get(url)
        self.assertEqual(response_get.status_code, 405)

        # POST without reason is rejected
        response_no_reason = self.client.post(url, {'reason': ''})
        self.assertEqual(response_no_reason.status_code, 302)
        self.assertEqual(PlatformAuditLog.objects.count(), 0)

    def test_cannot_impersonate_superuser_or_staff(self):
        """Impersonating another superuser or staff member must be strictly blocked (403)."""
        self.client.force_login(self.super_admin)
        # Point tenant owner to another superuser
        self.tenant.owner = self.other_admin
        self.tenant.save()

        url = reverse('super_admin:impersonate_start', kwargs={'tenant_id': self.tenant.id})
        response = self.client.post(url, {'reason': 'Attempting unauthorized admin impersonation'})
        self.assertEqual(response.status_code, 403)

    def test_cannot_impersonate_suspended_tenant(self):
        """Impersonation of a deactivated showroom must be refused."""
        self.client.force_login(self.super_admin)
        self.tenant.is_active = False
        self.tenant.save()

        url = reverse('super_admin:impersonate_start', kwargs={'tenant_id': self.tenant.id})
        response = self.client.post(url, {'reason': 'Support ticket'})
        self.assertEqual(response.status_code, 302)
        # Should redirect back to detail with error message
        self.assertEqual(PlatformAuditLog.objects.count(), 0)

    def test_successful_impersonation_lifecycle(self):
        """Test full impersonation flow: start, session switch, audit log, banner, and safe exit."""
        self.client.force_login(self.super_admin)
        start_url = reverse('super_admin:impersonate_start', kwargs={'tenant_id': self.tenant.id})

        # 1. Start impersonation
        response = self.client.post(start_url, {'reason': 'Investigating custom order #1234'}, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify audit log recorded
        log_start = PlatformAuditLog.objects.filter(
            action=PlatformAuditLog.ACTION_IMPERSONATION_START,
            target_tenant=self.tenant
        ).first()
        self.assertIsNotNone(log_start)
        self.assertEqual(log_start.actor, self.super_admin)
        self.assertEqual(log_start.target_user, self.customer_user)
        self.assertIn('Investigating custom order', log_start.reason)

        # 2. Verify session is now logged in as customer Bob
        session = self.client.session
        self.assertEqual(session.get('impersonator_id'), self.super_admin.id)
        self.assertEqual(session.get('impersonator_username'), 'admin_alice')
        self.assertEqual(session.get('impersonated_tenant_id'), self.tenant.id)

        # 3. Verify customer cannot access Super Admin while impersonating (HTTP 403)
        response_sa = self.client.get(reverse('super_admin:dashboard'))
        self.assertEqual(response_sa.status_code, 403)

        response_sa_list = self.client.get(reverse('super_admin:showroom_list'))
        self.assertEqual(response_sa_list.status_code, 403)

        # 4. Verify storefront page renders the persistent high-visibility impersonation banner
        response_storefront = self.client.get(reverse('dashboard'))
        self.assertEqual(response_storefront.status_code, 200)
        self.assertContains(response_storefront, 'Support Impersonation Mode Active')
        self.assertContains(response_storefront, 'Bob Jewels Atelier')
        self.assertContains(response_storefront, 'admin_alice')
        self.assertContains(response_storefront, 'Return to Super Admin')

        # 5. Customer password was NEVER touched or changed
        self.customer_user.refresh_from_db()
        self.assertTrue(self.customer_user.check_password('CustomerSecretPassword!'))

        # 6. Exit impersonation safely
        exit_url = reverse('super_admin:impersonate_exit')
        response_exit = self.client.post(exit_url, follow=True)
        self.assertEqual(response_exit.status_code, 200)

        # Verify impersonation session markers are cleaned up
        session_after = self.client.session
        self.assertIsNone(session_after.get('impersonator_id'))
        self.assertIsNone(session_after.get('impersonated_tenant_id'))

        # Verify original super admin user is restored
        self.assertEqual(int(self.client.session.get('_auth_user_id')), self.super_admin.id)

        # Verify exit audit log recorded
        log_end = PlatformAuditLog.objects.filter(
            action=PlatformAuditLog.ACTION_IMPERSONATION_END,
            target_tenant=self.tenant
        ).first()
        self.assertIsNotNone(log_end)
        self.assertEqual(log_end.actor, self.super_admin)

    def test_impersonation_blocks_nested_impersonation(self):
        """An impersonated session cannot initiate another impersonation."""
        self.client.force_login(self.super_admin)
        start_url = reverse('super_admin:impersonate_start', kwargs={'tenant_id': self.tenant.id})
        self.client.post(start_url, {'reason': 'Initial support session'})

        # Now in impersonation mode, trying to start another impersonation
        response_nested = self.client.post(start_url, {'reason': 'Nested attempt'})
        # Should be blocked by middleware or view with 403
        self.assertEqual(response_nested.status_code, 403)


class SubscriptionAndProposalFeatureTests(TestCase):
    """Test SaaS Subscriptions and Customer Proposals workflows."""

    def setUp(self):
        from decimal import Decimal
        self.super_admin = User.objects.create_superuser(
            username='admin_sub',
            email='adminsub@jeweldesk.test',
            password='Password123!'
        )
        self.owner = User.objects.create_user(
            username='owner_sub',
            email='ownersub@jeweldesk.test',
            password='Password123!'
        )
        self.tenant = Tenant.objects.create(
            name='Kalyan Jewellers Demo',
            slug='kalyan-demo',
            owner=self.owner,
            is_active=True
        )
        self.client = Client()

    def test_subscriptions_view_and_payment_recording(self):
        from decimal import Decimal
        from super_admin.models import TenantSubscription, SubscriptionPayment
        self.client.force_login(self.super_admin)

        # 1. View subscriptions page - triggers auto provisioning
        response = self.client.get(reverse('super_admin:subscriptions'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(TenantSubscription.objects.filter(tenant=self.tenant).exists())
        sub = self.tenant.subscription

        # 2. Update subscription plan
        update_url = reverse('super_admin:subscription_update', kwargs={'tenant_id': self.tenant.id})
        res_update = self.client.post(update_url, {
            'plan_name': 'pro',
            'status': 'active',
            'billing_cycle': 'yearly',
            'price': '39999.00',
            'discount': '5000.00',
            'payment_status': 'pending',
            'notes': 'Special inaugural discount',
        })
        self.assertEqual(res_update.status_code, 302)
        sub.refresh_from_db()
        self.assertEqual(sub.plan_name, 'pro')
        self.assertEqual(sub.price, Decimal('39999.00'))

        # 3. Record a payment
        pay_url = reverse('super_admin:subscription_record_payment', kwargs={'tenant_id': self.tenant.id})
        res_pay = self.client.post(pay_url, {
            'amount': '34999.00',
            'payment_date': '2026-10-17',
            'payment_method': 'upi',
            'reference_id': 'UPI291839218',
            'invoice_number': 'INV-2026-001',
            'notes': 'Advance payment via GPay',
        })
        self.assertEqual(res_pay.status_code, 302)
        self.assertEqual(SubscriptionPayment.objects.filter(tenant=self.tenant).count(), 1)
        sub.refresh_from_db()
        self.assertEqual(sub.payment_status, 'paid')
        self.assertEqual(sub.total_revenue_collected, Decimal('34999.00'))

    def test_proposal_lifecycle_and_client_public_view(self):
        from decimal import Decimal
        from super_admin.models import PlatformProposal
        self.client.force_login(self.super_admin)

        # 1. Create a proposal
        create_url = reverse('super_admin:proposal_create')
        res_create = self.client.post(create_url, {
            'client_name': 'Shri Mohanlal Soni',
            'client_showroom_name': 'Mohanlal Jewellers',
            'client_email': 'mohan@jewel.test',
            'client_phone': '9876543210',
            'client_city': 'Ahmedabad',
            'target_plan': 'core',
            'billing_cycle': 'yearly',
            'quoted_amount': '29999.00',
            'discount_amount': '5000.00',
            'features_summary': '• Feature 1\n• Feature 2',
            'terms_notes': '1. Standard terms',
        })
        self.assertEqual(res_create.status_code, 302)
        proposal = PlatformProposal.objects.filter(client_showroom_name='Mohanlal Jewellers').first()
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.final_amount, Decimal('24999.00'))
        self.assertEqual(proposal.status, 'draft')

        # 2. View proposal detail
        detail_url = reverse('super_admin:proposal_detail', kwargs={'proposal_id': proposal.id})
        res_detail = self.client.get(detail_url)
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, 'Mohanlal Jewellers')
        self.assertContains(res_detail, proposal.proposal_number)

        # 3. Change status to sent
        status_url = reverse('super_admin:proposal_status_update', kwargs={'proposal_id': proposal.id})
        res_status = self.client.post(status_url, {'status': 'sent'})
        self.assertEqual(res_status.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, 'sent')

        # 4. Public client view without any login
        anon_client = Client()
        share_url = reverse('super_admin:proposal_client_view', kwargs={'token': proposal.share_token})
        res_client = anon_client.get(share_url)
        self.assertEqual(res_client.status_code, 200)
        self.assertContains(res_client, 'Mohanlal Jewellers')
        self.assertContains(res_client, '24999')
        # Check that viewing automatically updated status to viewed
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, 'viewed')

        # 5. Client accepts proposal
        res_accept = anon_client.post(share_url, {'action': 'accept'})
        self.assertEqual(res_accept.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, 'accepted')

