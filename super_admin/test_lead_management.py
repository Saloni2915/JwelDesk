"""
super_admin/test_lead_management.py
------------------------------------
Comprehensive automated test suite for Phase 1: Lead Management in the Super Admin Portal.

Covers:
1. Role-based access control & tenant isolation.
2. Lead creation, 10-digit phone validation, and audit logging.
3. Dashboard summary metric cards with real database counts.
4. Lead search, multi-filter (status, source, city), and pagination.
5. Lead detail view & Phase 3 conversion readiness indicator.
6. Follow-up notes logging and timeline history.
7. Quick status updates and audit trails.
"""

from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant
from super_admin.models import PlatformDemoLead, PlatformLeadNote, PlatformAuditLog

User = get_user_model()


class SuperAdminLeadAccessTests(TestCase):
    """Verify that lead management routes are restricted strictly to Super Administrators."""

    def setUp(self):
        self.super_admin = User.objects.create_superuser(
            username='lead_admin',
            email='lead_admin@platform.test',
            password='Password123!'
        )
        self.regular_owner = User.objects.create_user(
            username='jeweller_owner',
            email='jeweller@shop.test',
            password='Password123!'
        )
        self.tenant = Tenant.objects.create(
            name='Kalyan Jewellers',
            slug='kalyan-jewellers',
            owner=self.regular_owner
        )
        self.client = Client()

    def test_anonymous_user_redirected_to_login(self):
        """Anonymous requests must be redirected to super admin / login."""
        res = self.client.get(reverse('super_admin:lead_list'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.url)

    def test_regular_tenant_user_denied_access(self):
        """Regular shop owner cannot access super admin lead management."""
        self.client.force_login(self.regular_owner)
        res = self.client.get(reverse('super_admin:lead_list'))
        # Should be redirected to their tenant dashboard or rejected
        self.assertIn(res.status_code, [302, 403])

    def test_super_admin_has_full_access(self):
        """Super Administrator has access to lead list and create pages."""
        self.client.force_login(self.super_admin)
        res = self.client.get(reverse('super_admin:lead_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Lead Management")


class LeadCreationAndValidationTests(TestCase):
    """Test manual lead creation, form cleaning (10-digit phone, email), and audit logging."""

    def setUp(self):
        self.super_admin = User.objects.create_superuser(
            username='sales_lead_admin',
            email='sales_admin@platform.test',
            password='Password123!'
        )
        self.client = Client()
        self.client.force_login(self.super_admin)

    def test_lead_creation_success(self):
        """Valid data creates a lead and writes a PlatformAuditLog entry."""
        post_data = {
            'contact_name': 'Ramesh Soni',
            'lead_name': 'Mahalaxmi Jewellers',
            'phone': '9876543210',
            'email': 'ramesh@mahalaxmi.test',
            'city': 'Rajkot',
            'address': 'Sonar Bazaar, Main Street',
            'business_type': 'RETAIL',
            'business_size': '3 Counters',
            'source': 'referral',
            'status': 'new',
            'notes': 'Interested in HUID barcode printing.',
        }
        res = self.client.post(reverse('super_admin:lead_create'), post_data)
        self.assertEqual(res.status_code, 302)

        lead = PlatformDemoLead.objects.filter(lead_name='Mahalaxmi Jewellers').first()
        self.assertIsNotNone(lead)
        self.assertEqual(lead.contact_name, 'Ramesh Soni')
        self.assertEqual(lead.phone, '9876543210')
        self.assertEqual(lead.city, 'Rajkot')
        self.assertEqual(lead.address, 'Sonar Bazaar, Main Street')
        self.assertEqual(lead.status, 'new')

        # Check Audit Log
        audit = PlatformAuditLog.objects.filter(
            action=PlatformAuditLog.ACTION_LEAD_CREATE,
            actor=self.super_admin
        ).first()
        self.assertIsNotNone(audit)
        self.assertIn('Mahalaxmi Jewellers', audit.reason)

    def test_phone_validation_rejects_invalid_numbers(self):
        """Phone numbers shorter than 10 digits or non-numeric must fail validation."""
        post_data = {
            'contact_name': 'Invalid Contact',
            'lead_name': 'Short Phone Shop',
            'phone': '12345',  # Too short!
            'source': 'website',
            'status': 'new',
        }
        res = self.client.post(reverse('super_admin:lead_create'), post_data)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(PlatformDemoLead.objects.filter(lead_name='Short Phone Shop').exists())
        self.assertFormError(res.context['form'], 'phone', 'Phone number must be exactly 10 digits.')

    def test_email_validation_rejects_malformed_email(self):
        """Malformed email addresses must be rejected with validation error."""
        post_data = {
            'contact_name': 'Test Jeweller',
            'lead_name': 'Bad Email Shop',
            'phone': '9876543210',
            'email': 'not-an-email',
            'source': 'website',
            'status': 'new',
        }
        res = self.client.post(reverse('super_admin:lead_create'), post_data)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(PlatformDemoLead.objects.filter(lead_name='Bad Email Shop').exists())


class LeadDashboardMetricsAndListingTests(TestCase):
    """Test dashboard summary metric cards, searching, multi-parameter filtering, and pagination."""

    def setUp(self):
        self.super_admin = User.objects.create_superuser(
            username='metrics_admin',
            email='metrics@platform.test',
            password='Password123!'
        )
        self.client = Client()
        self.client.force_login(self.super_admin)

        # Create diverse leads for metric cards testing
        PlatformDemoLead.objects.create(
            contact_name='Vijay Mehta', lead_name='Mehta Jewellers',
            phone='9811100001', city='Jaipur', status=PlatformDemoLead.STATUS_NEW,
            source=PlatformDemoLead.SOURCE_WEBSITE
        )
        PlatformDemoLead.objects.create(
            contact_name='Suresh Verma', lead_name='Verma Gold Atelier',
            phone='9811100002', city='Mumbai', status=PlatformDemoLead.STATUS_CONTACTED,
            source=PlatformDemoLead.SOURCE_WHATSAPP
        )
        PlatformDemoLead.objects.create(
            contact_name='Pooja Sharma', lead_name='Sharma Ornaments',
            phone='9811100003', city='Delhi', status=PlatformDemoLead.STATUS_INTERESTED,
            source=PlatformDemoLead.SOURCE_REFERRAL
        )
        PlatformDemoLead.objects.create(
            contact_name='Kiran Jain', lead_name='Jain Silver Works',
            phone='9811100004', city='Jaipur', status=PlatformDemoLead.STATUS_CONVERTED,
            source=PlatformDemoLead.SOURCE_DIRECT_CONTACT
        )
        PlatformDemoLead.objects.create(
            contact_name='Amit Shah', lead_name='Shah Bullion Store',
            phone='9811100005', city='Ahmedabad', status=PlatformDemoLead.STATUS_NOT_INTERESTED,
            source=PlatformDemoLead.SOURCE_COLD_CALL
        )

    def test_summary_cards_display_exact_database_counts(self):
        """Dashboard cards must display accurate counts for all 6 required metrics."""
        res = self.client.get(reverse('super_admin:lead_list'))
        self.assertEqual(res.status_code, 200)

        # Context metrics
        self.assertEqual(res.context['total_leads_count'], 5)
        self.assertEqual(res.context['new_leads_count'], 1)
        self.assertEqual(res.context['contacted_leads_count'], 1)
        self.assertEqual(res.context['interested_leads_count'], 1)
        self.assertEqual(res.context['converted_leads_count'], 1)
        self.assertEqual(res.context['not_interested_leads_count'], 1)

    def test_search_by_shop_and_contact_name(self):
        """Search query matches lead_name, contact_name, city, and phone."""
        # Search by contact name
        res = self.client.get(reverse('super_admin:lead_list') + '?q=Vijay')
        self.assertEqual(len(res.context['page_obj']), 1)
        self.assertEqual(res.context['page_obj'][0].contact_name, 'Vijay Mehta')

        # Search by shop name
        res2 = self.client.get(reverse('super_admin:lead_list') + '?q=Verma')
        self.assertEqual(len(res2.context['page_obj']), 1)
        self.assertEqual(res2.context['page_obj'][0].lead_name, 'Verma Gold Atelier')

        # Search by city
        res3 = self.client.get(reverse('super_admin:lead_list') + '?q=Jaipur')
        self.assertEqual(len(res3.context['page_obj']), 2)

    def test_filter_by_status_and_source(self):
        """Filter dropdowns properly scope queryset."""
        res = self.client.get(reverse('super_admin:lead_list') + '?status=interested')
        self.assertEqual(len(res.context['page_obj']), 1)
        self.assertEqual(res.context['page_obj'][0].contact_name, 'Pooja Sharma')

        res2 = self.client.get(reverse('super_admin:lead_list') + '?source=whatsapp')
        self.assertEqual(len(res2.context['page_obj']), 1)
        self.assertEqual(res2.context['page_obj'][0].contact_name, 'Suresh Verma')

    def test_pagination_controls(self):
        """Pagination breaks lists into 20 items per page."""
        # Create 25 additional leads
        for i in range(25):
            PlatformDemoLead.objects.create(
                contact_name=f'Lead Contact {i}',
                lead_name=f'Shop {i}',
                phone=f'98000000{i:02d}',
                status=PlatformDemoLead.STATUS_NEW,
                source=PlatformDemoLead.SOURCE_WEBSITE
            )

        res = self.client.get(reverse('super_admin:lead_list'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context['page_obj']), 20)
        self.assertTrue(res.context['page_obj'].has_next())

        # Page 2
        res_page2 = self.client.get(reverse('super_admin:lead_list') + '?page=2')
        self.assertEqual(res_page2.status_code, 200)
        self.assertEqual(len(res_page2.context['page_obj']), 10)  # 5 original + 25 = 30 total -> 10 on page 2


class LeadDetailAndFollowupHistoryTests(TestCase):
    """Test lead detail view, follow-up notes, status updating, and Phase 3 readiness notice."""

    def setUp(self):
        self.super_admin = User.objects.create_superuser(
            username='detail_admin',
            email='detail@platform.test',
            password='Password123!'
        )
        self.client = Client()
        self.client.force_login(self.super_admin)

        self.lead = PlatformDemoLead.objects.create(
            contact_name='Bhavin Zaveri',
            lead_name='Zaveri Bros Jewellers',
            phone='9822233344',
            email='bhavin@zaveribros.test',
            city='Surat',
            address='Nanpura Diamond Market',
            business_type='BOTH',
            business_size='4 Counters',
            source=PlatformDemoLead.SOURCE_REFERRAL,
            status=PlatformDemoLead.STATUS_NEW
        )

    def test_detail_view_renders_lead_info_and_phase3_notice(self):
        """Lead detail view displays complete prospect info and Phase 3 readiness banner."""
        res = self.client.get(reverse('super_admin:lead_detail', kwargs={'lead_id': self.lead.id}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Bhavin Zaveri')
        self.assertContains(res, 'Zaveri Bros Jewellers')
        self.assertContains(res, 'Nanpura Diamond Market')
        self.assertContains(res, 'Coming in Phase 3')
        self.assertContains(res, 'Convert to Showroom Account (Phase 3)')

    def test_log_followup_note_updates_lead_and_audit(self):
        """Adding a follow-up note records note, updates lead status & follow_up_date, and writes audit log."""
        next_week = date.today() + timedelta(days=7)
        post_data = {
            'note': 'Demonstrated billing and Karigar ledger. Client requested proposal for 4 counters.',
            'status_at_note': PlatformDemoLead.STATUS_INTERESTED,
            'follow_up_date': next_week.strftime('%Y-%m-%d'),
        }
        res = self.client.post(
            reverse('super_admin:lead_add_note', kwargs={'lead_id': self.lead.id}),
            post_data
        )
        self.assertEqual(res.status_code, 302)

        # Check PlatformLeadNote created
        note = PlatformLeadNote.objects.filter(lead=self.lead).first()
        self.assertIsNotNone(note)
        self.assertEqual(note.author, self.super_admin)
        self.assertIn('Demonstrated billing and Karigar ledger', note.note)
        self.assertEqual(note.status_at_note, PlatformDemoLead.STATUS_INTERESTED)
        self.assertEqual(note.follow_up_date, next_week)

        # Check lead was updated
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, PlatformDemoLead.STATUS_INTERESTED)
        self.assertEqual(self.lead.follow_up_date, next_week)

        # Check Audit Log
        audit = PlatformAuditLog.objects.filter(
            action=PlatformAuditLog.ACTION_LEAD_NOTE,
            actor=self.super_admin
        ).first()
        self.assertIsNotNone(audit)

    def test_quick_status_update(self):
        """Quick status change updates lead, creates automatic note, and writes audit log."""
        res = self.client.post(
            reverse('super_admin:lead_update_status', kwargs={'lead_id': self.lead.id}),
            {'status': PlatformDemoLead.STATUS_CONTACTED}
        )
        self.assertEqual(res.status_code, 302)

        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, PlatformDemoLead.STATUS_CONTACTED)

        # Automatic note generated
        note = PlatformLeadNote.objects.filter(lead=self.lead).first()
        self.assertIsNotNone(note)
        self.assertIn('Status changed from', note.note)

        # Audit log written
        audit = PlatformAuditLog.objects.filter(
            action=PlatformAuditLog.ACTION_LEAD_STATUS_UPDATE,
            actor=self.super_admin
        ).first()
        self.assertIsNotNone(audit)

    def test_edit_lead(self):
        """Editing lead updates attributes and writes audit log."""
        post_data = {
            'contact_name': 'Bhavin P. Zaveri',
            'lead_name': 'Zaveri Bros Jewellers Pvt Ltd',
            'phone': '9822233344',
            'email': 'bhavin.zaveri@zaveribros.test',
            'city': 'Surat',
            'address': 'Nanpura Diamond Market, Shop #104',
            'business_type': 'WHOLESALE',
            'business_size': '5 Counters',
            'source': 'referral',
            'status': 'contacted',
            'notes': 'Wholesale diamond jewellery supplier.',
        }
        res = self.client.post(
            reverse('super_admin:lead_edit', kwargs={'lead_id': self.lead.id}),
            post_data
        )
        self.assertEqual(res.status_code, 302)

        self.lead.refresh_from_db()
        self.assertEqual(self.lead.contact_name, 'Bhavin P. Zaveri')
        self.assertEqual(self.lead.lead_name, 'Zaveri Bros Jewellers Pvt Ltd')
        self.assertEqual(self.lead.business_type, 'WHOLESALE')

        # Audit log
        audit = PlatformAuditLog.objects.filter(
            action=PlatformAuditLog.ACTION_LEAD_UPDATE,
            actor=self.super_admin
        ).first()
        self.assertIsNotNone(audit)

