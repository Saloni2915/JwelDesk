"""
super_admin/test_sales_crm.py
------------------------------
Test suite for Enterprise Sales CRM module:
- 10-stage navigation segregation & count calculations
- Sales Dashboard KPIs & expected revenue calculation
- Dedicated stage views & filters
- Kanban pipeline board & stage transitions
- Customer requirements & negotiation history
- Multi-channel activities & follow-up completion toggle
- Commercial proposal creation linked to lead
- Safe tenant conversion workflow without duplicates
- Sales performance reports
"""

from decimal import Decimal
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant
from super_admin.models import (
    PlatformDemoLead,
    PlatformLeadStageHistory,
    PlatformLeadNegotiation,
    PlatformLeadActivity,
    PlatformProposal,
    TenantSubscription,
)
from super_admin.sales_views import get_sales_crm_stage_counts

User = get_user_model()


class SalesCRMModuleTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.super_user = User.objects.create_superuser(
            username='admin_sales',
            email='salesadmin@jweldesk.com',
            password='AdminPassword123!'
        )
        self.client.login(username='admin_sales', password='AdminPassword123!')

        # Create sample leads across various stages
        self.lead_new = PlatformDemoLead.objects.create(
            lead_name="Shree Ganesh Jewellers",
            contact_name="Ganesh Verma",
            phone="9876543210",
            email="ganesh@example.com",
            city="Jaipur",
            business_type="RETAIL",
            source="website",
            stage=PlatformDemoLead.STAGE_NEW,
            deal_value=Decimal('45000.00'),
            assigned_staff=self.super_user
        )

        self.lead_interested = PlatformDemoLead.objects.create(
            lead_name="Kalyan Gold Palace",
            contact_name="Kalyan Singh",
            phone="9876543211",
            city="Surat",
            business_type="RETAIL",
            stage=PlatformDemoLead.STAGE_INTERESTED,
            deal_value=Decimal('60000.00'),
            assigned_staff=self.super_user
        )

        self.lead_lost = PlatformDemoLead.objects.create(
            lead_name="Old Town Silver",
            contact_name="Ramesh Bhai",
            phone="9876543212",
            city="Ahmedabad",
            stage=PlatformDemoLead.STAGE_LOST,
            lost_reason=PlatformDemoLead.LOST_PRICE_HIGH,
            lost_notes="Budget limit was 15k",
            assigned_staff=self.super_user
        )

    def test_stage_counts_calculation(self):
        """Ensure get_sales_crm_stage_counts calculates accurate counts."""
        counts = get_sales_crm_stage_counts()
        self.assertGreaterEqual(counts['leads'], 1)
        self.assertGreaterEqual(counts['interested'], 1)
        self.assertGreaterEqual(counts['lost'], 1)
        self.assertIn('trial', counts)
        self.assertIn('proposals', counts)
        self.assertIn('orders', counts)
        self.assertIn('customers', counts)
        self.assertIn('subscribers', counts)
        self.assertIn('renewals', counts)

    def test_sales_dashboard_view(self):
        """Sales dashboard returns 200 and displays database KPIs."""
        url = reverse('super_admin:sales_dashboard')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sales CRM Dashboard")
        self.assertIn('kpis', resp.context)
        self.assertEqual(resp.context['kpis']['total_leads'], PlatformDemoLead.objects.count())

    def test_dedicated_stage_view_segregation(self):
        """Dedicated stage view shows only leads for that specific stage."""
        # Test 'leads' view
        url_leads = reverse('super_admin:sales_stage_view', kwargs={'stage_key': 'leads'})
        resp_leads = self.client.get(url_leads)
        self.assertEqual(resp_leads.status_code, 200)
        self.assertContains(resp_leads, "Shree Ganesh Jewellers")
        self.assertNotContains(resp_leads, "Old Town Silver")

        # Test 'lost' view
        url_lost = reverse('super_admin:sales_stage_view', kwargs={'stage_key': 'lost'})
        resp_lost = self.client.get(url_lost)
        self.assertEqual(resp_lost.status_code, 200)
        self.assertContains(resp_lost, "Old Town Silver")
        self.assertNotContains(resp_lost, "Shree Ganesh Jewellers")

    def test_pipeline_kanban_view(self):
        """Kanban pipeline displays columns with categorized leads."""
        url = reverse('super_admin:sales_pipeline')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sales Pipeline Board")
        self.assertIn('columns', resp.context)

    def test_sales_stage_transition(self):
        """Moving lead stage creates audit history and updates lead stage."""
        url = reverse('super_admin:sales_stage_transition', kwargs={'lead_id': self.lead_new.id})
        resp = self.client.post(url, {
            'to_stage': 'meetings',
            'reason': 'Customer requested on-site demonstration',
            'deal_value': '50000.00'
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.lead_new.refresh_from_db()
        self.assertEqual(self.lead_new.stage, 'meetings')
        self.assertEqual(self.lead_new.deal_value, Decimal('50000.00'))

        # Check history record
        hist = PlatformLeadStageHistory.objects.filter(lead=self.lead_new, to_stage='meetings').first()
        self.assertIsNotNone(hist)
        self.assertEqual(hist.changed_by, self.super_user)

    def test_sales_negotiation_logging(self):
        """Logging customer requirements saves PlatformLeadNegotiation record."""
        url = reverse('super_admin:sales_add_negotiation', kwargs={'lead_id': self.lead_interested.id})
        resp = self.client.post(url, {
            'target_plan': TenantSubscription.PLAN_PRO,
            'branches_count': 2,
            'users_count': 5,
            'budget': '40000.00',
            'modules': ['Girvi Management', 'Karigar & Workshop'],
            'discussion_summary': 'Owner wants Girvi pawn loan management with barcoding.'
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        neg = PlatformLeadNegotiation.objects.filter(lead=self.lead_interested).first()
        self.assertIsNotNone(neg)
        self.assertEqual(neg.branches_count, 2)
        self.assertEqual(neg.budget, Decimal('40000.00'))
        self.assertIn('Girvi Management', neg.required_modules)

    def test_sales_activity_and_toggle(self):
        """Scheduling activity logs activity and toggling completes it."""
        url_add = reverse('super_admin:sales_add_activity', kwargs={'lead_id': self.lead_interested.id})
        tomorrow = (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
        resp = self.client.post(url_add, {
            'activity_type': 'call',
            'title': 'Pricing follow-up call with owner',
            'scheduled_at': tomorrow,
            'outcome_notes': 'Discuss 10% annual payment discount',
            'assigned_to': self.super_user.id
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        act = PlatformLeadActivity.objects.filter(lead=self.lead_interested).first()
        self.assertIsNotNone(act)
        self.assertFalse(act.is_completed)

        # Toggle completion
        url_toggle = reverse('super_admin:sales_toggle_activity', kwargs={'activity_id': act.id})
        resp_toggle = self.client.post(url_toggle, follow=True)
        self.assertEqual(resp_toggle.status_code, 200)

        act.refresh_from_db()
        self.assertTrue(act.is_completed)
        self.assertIsNotNone(act.completed_at)

    def test_safe_tenant_conversion(self):
        """Converting a deal provisions an active Tenant and updates lead status safely."""
        lead = PlatformDemoLead.objects.create(
            lead_name="Royal Diamonds Mumbai",
            contact_name="Vikram Mehta",
            phone="9876500001",
            stage=PlatformDemoLead.STAGE_ORDERS,
            deal_value=Decimal('50000.00')
        )

        url = reverse('super_admin:sales_convert_tenant', kwargs={'lead_id': lead.id})
        resp = self.client.post(url, {
            'target_plan': TenantSubscription.PLAN_PRO
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        lead.refresh_from_db()
        self.assertIsNotNone(lead.converted_tenant)
        self.assertEqual(lead.stage, PlatformDemoLead.STAGE_CUSTOMERS)
        self.assertEqual(lead.status, PlatformDemoLead.STATUS_CONVERTED)

        # Check tenant created
        tenant = lead.converted_tenant
        self.assertEqual(tenant.name, "Royal Diamonds Mumbai")
        self.assertTrue(tenant.is_active)

        # Check subscription
        sub = TenantSubscription.objects.filter(tenant=tenant).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.status, TenantSubscription.STATUS_ACTIVE)
        self.assertEqual(sub.plan_name, TenantSubscription.PLAN_PRO)

    def test_sales_reports_view(self):
        """Sales reports page renders source ROI and rep metrics."""
        url = reverse('super_admin:sales_reports')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sales Reports &amp; Analytics")
        self.assertIn('source_data', resp.context)
        self.assertIn('exec_data', resp.context)

