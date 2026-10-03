from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from customers.models import Customer
from custom_orders.models import CustomOrder
from inventory.models import Category, JewelleryItem, StockMovement
from team.models import Branch, Employee, EmployeePermission, Role
from .models import (
    Karigar,
    KarigarSettlement,
    KarigarWorkAssignment,
    generate_karigar_code,
    generate_assignment_number,
    generate_settlement_number,
)

User = get_user_model()


class KarigarTestCaseBase(TestCase):
    """Common test fixture with admin, employee, branch, and sample items."""

    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin_user = User.objects.create_superuser(
            username='admin@jeweldesk.com',
            email='admin@jeweldesk.com',
            password='AdminPassword123!'
        )

        # Standard non-permission user
        self.plain_user = User.objects.create_user(
            username='staff@jeweldesk.com',
            email='staff@jeweldesk.com',
            password='StaffPassword123!'
        )

        # Setup Branch & Roles
        self.branch = Branch.objects.create(name='Main Flagship')
        Role.ensure_builtin_roles()
        self.admin_role = Role.objects.get(name=Role.ROLE_ADMIN)
        self.sales_role = Role.objects.get(name=Role.ROLE_SALES)
        self.support_role = Role.objects.get(name=Role.ROLE_SUPPORT)

        # Employee with restricted support role (view only, no edit/add for karigar)
        self.support_emp = Employee.objects.create(
            user=self.plain_user,
            employee_id='EMP-9001',
            full_name='Support User',
            email='staff@jeweldesk.com',
            mobile='9876543210',
            role=self.support_role,
            designation='Support Exec',
            status=Employee.STATUS_ACTIVE,
        )
        self.support_emp.apply_default_permissions()

        # Create sample Category and JewelleryItem
        self.category = Category.objects.create(name='Bangles')
        self.item = JewelleryItem.objects.create(
            item_code='JW-BNG-001',
            name='22K Floral Gold Kangan',
            category=self.category,
            metal_type='Gold',
            purity='22K (916)',
            gross_weight=Decimal('25.500'),
            net_weight=Decimal('24.000'),
            stone_weight=Decimal('1.500'),
            quantity=5,
            status='Available',
            selling_price=Decimal('185000.00'),
        )

        # Create sample Customer
        self.customer = Customer.objects.create(
            name='Ramesh Kothari',
            mobile='9820011223',
            email='ramesh@example.com',
        )

        # Create sample Karigar
        self.karigar = Karigar.objects.create(
            name='Suresh Soni',
            mobile='9811122233',
            specialization='Gold Jewellery',
            status=Karigar.STATUS_ACTIVE,
            address='Zaveri Bazaar, Mumbai',
        )


class KarigarMasterTests(KarigarTestCaseBase):
    """Test Karigar profile creation, sequential code generation, and properties."""

    def test_sequential_karigar_code_generation(self):
        k1 = Karigar.objects.create(name='Mahesh Patil', mobile='9800011122')
        self.assertTrue(k1.karigar_code.startswith('KRG-'))

        k2 = Karigar.objects.create(name='Ganesh Jewellers', mobile='9800011123')
        self.assertTrue(k2.karigar_code.startswith('KRG-'))
        self.assertNotEqual(k1.karigar_code, k2.karigar_code)

    def test_karigar_duplicate_code_prevention(self):
        with self.assertRaises(Exception):
            Karigar.objects.create(
                karigar_code=self.karigar.karigar_code,
                name='Duplicate Artisan',
                mobile='9999988888',
            )

    def test_karigar_toggle_status_view(self):
        self.client.force_login(self.admin_user)
        self.assertEqual(self.karigar.status, Karigar.STATUS_ACTIVE)

        response = self.client.post(reverse('karigar:karigar_toggle_status', args=[self.karigar.pk]))
        self.assertRedirects(response, reverse('karigar:karigar_detail', args=[self.karigar.pk]))
        self.karigar.refresh_from_db()
        self.assertEqual(self.karigar.status, Karigar.STATUS_INACTIVE)

        # Toggle back to active
        self.client.post(reverse('karigar:karigar_toggle_status', args=[self.karigar.pk]))
        self.karigar.refresh_from_db()
        self.assertEqual(self.karigar.status, Karigar.STATUS_ACTIVE)


class WeightAccountabilityAndCalculationsTests(KarigarTestCaseBase):
    """Test accurate weight formulas, wastage, and accountability difference."""

    def test_weight_accountability_math(self):
        """
        Issued: Gross 50.000g, Stones 5.000g -> Net 45.000g
        Wastage allowed: 2.00% -> Allowed loss = 45.000 * 0.02 = 0.900g
        Received: Gross 42.000g, Stones 2.000g -> Net 40.000g
        Scrap returned: 3.800g
        Total accounted = 40.000 + 3.800 = 43.800g
        Actual loss = 45.000 - 43.800 = 1.200g
        Weight difference = Actual Loss (1.200) - Allowed Loss (0.900) = +0.300g (Excess Loss)
        """
        asg = KarigarWorkAssignment(
            karigar=self.karigar,
            work_type='New Making',
            metal_type='Gold',
            gross_weight_issued=Decimal('50.000'),
            stone_weight_issued=Decimal('5.000'),
            wastage_allowed_percent=Decimal('2.00'),
            gross_weight_received=Decimal('42.000'),
            stone_weight_received=Decimal('2.000'),
            scrap_weight_returned=Decimal('3.800'),
            status=KarigarWorkAssignment.STATUS_RECEIVED,
        )
        asg.calculate_weights()

        self.assertEqual(asg.net_weight_issued, Decimal('45.000'))
        self.assertEqual(asg.net_weight_received, Decimal('40.000'))
        self.assertEqual(asg.wastage_weight_allowed, Decimal('0.900'))
        self.assertEqual(asg.actual_wastage_weight, Decimal('1.200'))
        self.assertEqual(asg.weight_difference, Decimal('0.300'))
        self.assertTrue(asg.has_excess_wastage)

    def test_negative_weight_validation_error(self):
        asg = KarigarWorkAssignment(
            karigar=self.karigar,
            gross_weight_issued=Decimal('-10.000'),
        )
        with self.assertRaises(ValidationError):
            asg.clean()

    def test_stone_weight_exceeding_gross_validation(self):
        asg = KarigarWorkAssignment(
            karigar=self.karigar,
            gross_weight_issued=Decimal('10.000'),
            stone_weight_issued=Decimal('15.000'),
        )
        with self.assertRaises(ValidationError):
            asg.clean()


class LabourChargeCalculationsTests(KarigarTestCaseBase):
    """Test making charge formulas (Fixed Amount, Per Gram, Percentage)."""

    def test_per_gram_labour_charge(self):
        asg = KarigarWorkAssignment.objects.create(
            karigar=self.karigar,
            gross_weight_issued=Decimal('20.000'),
            stone_weight_issued=Decimal('0.000'),
            gross_weight_received=Decimal('19.500'),
            stone_weight_received=Decimal('0.000'),
            making_charge_type='Per Gram',
            making_charge_rate=Decimal('500.00'),
            stone_charges=Decimal('250.00'),
            other_charges=Decimal('150.00'),
            status=KarigarWorkAssignment.STATUS_RECEIVED,
        )
        # wt_basis = 19.500g * 500 = 9750.00 + 250 stone + 150 other = 10150.00
        self.assertEqual(asg.labour_charge, Decimal('9750.00'))
        self.assertEqual(asg.total_charge, Decimal('10150.00'))
        self.assertEqual(asg.payment_status, 'Unpaid')
        self.assertEqual(asg.due_charge_amount, Decimal('10150.00'))

    def test_fixed_amount_labour_charge(self):
        asg = KarigarWorkAssignment.objects.create(
            karigar=self.karigar,
            gross_weight_issued=Decimal('15.000'),
            making_charge_type='Fixed Amount',
            making_charge_rate=Decimal('3500.00'),
            stone_charges=Decimal('0.00'),
            other_charges=Decimal('0.00'),
        )
        self.assertEqual(asg.labour_charge, Decimal('3500.00'))
        self.assertEqual(asg.total_charge, Decimal('3500.00'))


class InventoryIntegrationTests(KarigarTestCaseBase):
    """Test audited stock movement integration when issuing and receiving items."""

    def test_stock_issue_and_return_lifecycle(self):
        self.client.force_login(self.admin_user)
        initial_qty = self.item.quantity  # 5

        # 1. Issue work assignment with showroom item selected and issue_stock_item checked
        post_data = {
            'karigar': self.karigar.pk,
            'work_type': 'Polishing',
            'priority': 'Medium',
            'inventory_item': self.item.pk,
            'issue_stock_item': True,
            'description': 'Polish showroom piece and touch up rhodium',
            'issue_date': timezone.localdate().isoformat(),
            'expected_completion_date': (timezone.localdate() + timezone.timedelta(days=3)).isoformat(),
            'metal_type': 'Gold',
            'purity': '22K',
            'gross_weight_issued': '25.500',
            'stone_weight_issued': '1.500',
            'wastage_allowed_percent': '0.50',
            'making_charge_type': 'Fixed Amount',
            'making_charge_rate': '800.00',
            'stone_charges': '0.00',
            'other_charges': '0.00',
        }
        response = self.client.post(reverse('karigar:assignment_create'), post_data)
        self.assertEqual(response.status_code, 302)

        asg = KarigarWorkAssignment.objects.latest('id')
        self.item.refresh_from_db()
        # Stock decreased by 1
        self.assertEqual(self.item.quantity, initial_qty - 1)
        self.assertIsNotNone(asg.stock_movement_issued)
        self.assertEqual(asg.stock_movement_issued.quantity_change, -1)

        # 2. Receive work back and return to available stock
        receive_data = {
            'actual_completion_date': timezone.localdate().isoformat(),
            'gross_weight_received': '25.450',
            'stone_weight_received': '1.500',
            'scrap_weight_returned': '0.000',
            'making_charge_type': 'Fixed Amount',
            'making_charge_rate': '800.00',
            'stone_charges': '0.00',
            'other_charges': '0.00',
            'return_to_inventory': True,
            'notes': 'Polished piece verified and restocked',
        }
        response = self.client.post(reverse('karigar:assignment_receive', args=[asg.pk]), receive_data)
        self.assertEqual(response.status_code, 302)

        asg.refresh_from_db()
        self.item.refresh_from_db()
        # Stock restored by 1
        self.assertEqual(self.item.quantity, initial_qty)
        self.assertIsNotNone(asg.stock_movement_received)
        self.assertEqual(asg.stock_movement_received.quantity_change, 1)
        self.assertEqual(asg.status, KarigarWorkAssignment.STATUS_RECEIVED)

    def test_cancelled_work_restores_deducted_stock(self):
        self.client.force_login(self.admin_user)
        initial_qty = self.item.quantity

        post_data = {
            'karigar': self.karigar.pk,
            'work_type': 'Repair',
            'priority': 'High',
            'inventory_item': self.item.pk,
            'issue_stock_item': True,
            'description': 'Repair clasp',
            'issue_date': timezone.localdate().isoformat(),
            'metal_type': 'Gold',
            'purity': '22K',
            'gross_weight_issued': '24.000',
            'stone_weight_issued': '0.000',
            'wastage_allowed_percent': '0.00',
            'making_charge_type': 'Fixed Amount',
            'making_charge_rate': '500.00',
            'stone_charges': '0.00',
            'other_charges': '0.00',
        }
        self.client.post(reverse('karigar:assignment_create'), post_data)
        asg = KarigarWorkAssignment.objects.latest('id')
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, initial_qty - 1)

        # Cancel assignment
        self.client.post(reverse('karigar:assignment_status_update', args=[asg.pk]), {'status': 'Cancelled'})
        asg.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(asg.status, KarigarWorkAssignment.STATUS_CANCELLED)
        # Item restored to stock
        self.assertEqual(self.item.quantity, initial_qty)


class CustomOrderIntegrationTests(KarigarTestCaseBase):
    """Test linking work assignments to Customer and CustomOrder workflows."""

    def test_custom_order_lifecycle_with_assignment(self):
        self.client.force_login(self.admin_user)

        # Create Custom Order in Confirmed state
        order = CustomOrder.objects.create(
            customer=self.customer,
            category=self.category,
            design_description='Bespoke Peacock Kada',
            metal_type='Gold',
            purity='22K',
            approx_gross_weight=Decimal('35.000'),
            approx_net_weight=Decimal('32.000'),
            estimated_price=Decimal('220000.00'),
            status=CustomOrder.STATUS_CONFIRMED,
        )

        # Issue Karigar assignment linked to custom order
        post_data = {
            'karigar': self.karigar.pk,
            'custom_order': order.pk,
            'customer': self.customer.pk,
            'work_type': 'Custom Work',
            'priority': 'High',
            'description': 'Make Peacock Kada according to order specs',
            'issue_date': timezone.localdate().isoformat(),
            'metal_type': 'Gold',
            'purity': '22K',
            'gross_weight_issued': '35.000',
            'stone_weight_issued': '0.000',
            'wastage_allowed_percent': '1.50',
            'making_charge_type': 'Per Gram',
            'making_charge_rate': '650.00',
            'stone_charges': '1200.00',
            'other_charges': '0.00',
        }
        response = self.client.post(reverse('karigar:assignment_create'), post_data)
        self.assertEqual(response.status_code, 302)

        order.refresh_from_db()
        # Order should transition to In Making
        self.assertEqual(order.status, CustomOrder.STATUS_IN_MAKING)

        asg = KarigarWorkAssignment.objects.latest('id')

        # Receive completed piece
        receive_data = {
            'actual_completion_date': timezone.localdate().isoformat(),
            'gross_weight_received': '34.800',
            'stone_weight_received': '2.000',
            'scrap_weight_returned': '0.200',
            'making_charge_type': 'Per Gram',
            'making_charge_rate': '650.00',
            'stone_charges': '1200.00',
            'other_charges': '0.00',
            'notes': 'Kada ready for customer pickup',
        }
        self.client.post(reverse('karigar:assignment_receive', args=[asg.pk]), receive_data)

        order.refresh_from_db()
        # Custom order transitions to Ready
        self.assertEqual(order.status, CustomOrder.STATUS_READY)


class SettlementAndFinancialWorkflowTests(KarigarTestCaseBase):
    """Test settlements, allocations, and safe cancellation rollback."""

    def test_settlement_creation_and_safe_cancellation(self):
        self.client.force_login(self.admin_user)

        # Create two assignments for this karigar
        asg1 = KarigarWorkAssignment.objects.create(
            karigar=self.karigar,
            gross_weight_issued=Decimal('20.000'),
            gross_weight_received=Decimal('20.000'),
            making_charge_type='Fixed Amount',
            making_charge_rate=Decimal('4000.00'),
            status=KarigarWorkAssignment.STATUS_RECEIVED,
        )
        asg2 = KarigarWorkAssignment.objects.create(
            karigar=self.karigar,
            gross_weight_issued=Decimal('10.000'),
            gross_weight_received=Decimal('10.000'),
            making_charge_type='Fixed Amount',
            making_charge_rate=Decimal('2000.00'),
            status=KarigarWorkAssignment.STATUS_RECEIVED,
        )

        self.assertEqual(self.karigar.pending_balance, Decimal('6000.00'))

        # Post settlement of ₹5000 allocated to both assignments
        settlement_data = {
            'karigar': self.karigar.pk,
            'payment_date': timezone.localdate().isoformat(),
            'amount': '5000.00',
            'payment_method': 'Bank Transfer',
            'payment_reference': 'UTR1234567890',
            'assignments': [asg1.pk, asg2.pk],
            'notes': 'NEFT payment for jobs',
        }
        response = self.client.post(reverse('karigar:settlement_create'), settlement_data)
        self.assertEqual(response.status_code, 302)

        st = KarigarSettlement.objects.latest('id')
        self.assertTrue(st.settlement_number.startswith('KST-'))

        asg1.refresh_from_db()
        asg2.refresh_from_db()
        # asg1 settled in full (4000), asg2 partially settled (1000)
        self.assertEqual(asg1.paid_amount, Decimal('4000.00'))
        self.assertEqual(asg1.payment_status, 'Paid')
        self.assertEqual(asg2.paid_amount, Decimal('1000.00'))
        self.assertEqual(asg2.payment_status, 'Partially Paid')
        self.assertEqual(self.karigar.pending_balance, Decimal('1000.00'))

        # Now test cancellation with audit reason
        cancel_response = self.client.post(
            reverse('karigar:settlement_cancel', args=[st.pk]),
            {'cancellation_reason': 'Bank transfer failed/reversed by artisan bank'}
        )
        self.assertEqual(cancel_response.status_code, 302)

        st.refresh_from_db()
        asg1.refresh_from_db()
        asg2.refresh_from_db()

        self.assertEqual(st.status, KarigarSettlement.STATUS_CANCELLED)
        self.assertEqual(st.cancelled_by, self.admin_user)
        self.assertIn('Bank transfer failed', st.cancellation_reason)

        # Assignment balances must be rolled back
        self.assertEqual(asg1.paid_amount, Decimal('0.00'))
        self.assertEqual(asg1.payment_status, 'Unpaid')
        self.assertEqual(asg2.paid_amount, Decimal('0.00'))
        self.assertEqual(asg2.payment_status, 'Unpaid')
        self.assertEqual(self.karigar.pending_balance, Decimal('6000.00'))


class PermissionsAndSecurityTests(KarigarTestCaseBase):
    """Test backend permission enforcement and unauthorized URL access blocking."""

    def test_unauthenticated_redirects_to_login(self):
        urls = [
            reverse('karigar:dashboard'),
            reverse('karigar:karigar_list'),
            reverse('karigar:karigar_create'),
            reverse('karigar:assignment_list'),
            reverse('karigar:assignment_create'),
            reverse('karigar:settlement_list'),
            reverse('karigar:reports'),
        ]
        for u in urls:
            response = self.client.get(u)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.url)

    def test_unauthorized_user_blocked_with_403(self):
        """User with support role lacks 'karigar.add', 'karigar.edit' permissions."""
        self.client.force_login(self.plain_user)

        # View operations: Support has view permission
        resp = self.client.get(reverse('karigar:dashboard'))
        self.assertEqual(resp.status_code, 200)

        # Add operations: Support lacks add permission -> HTTP 403
        resp_add_k = self.client.get(reverse('karigar:karigar_create'))
        self.assertEqual(resp_add_k.status_code, 403)

        resp_add_asg = self.client.get(reverse('karigar:assignment_create'))
        self.assertEqual(resp_add_asg.status_code, 403)

        resp_add_st = self.client.get(reverse('karigar:settlement_create'))
        self.assertEqual(resp_add_st.status_code, 403)

        # Edit operations: Support lacks edit permission -> HTTP 403
        resp_edit_k = self.client.get(reverse('karigar:karigar_edit', args=[self.karigar.pk]))
        self.assertEqual(resp_edit_k.status_code, 403)


class ReportsAndExportsTests(KarigarTestCaseBase):
    """Test report views and CSV generation."""

    def setUp(self):
        super().setUp()
        self.asg = KarigarWorkAssignment.objects.create(
            karigar=self.karigar,
            work_type='New Making',
            metal_type='Gold',
            gross_weight_issued=Decimal('20.000'),
            stone_weight_issued=Decimal('0.000'),
            gross_weight_received=Decimal('19.800'),
            status=KarigarWorkAssignment.STATUS_RECEIVED,
        )

    def test_reports_page_and_csv_export(self):
        self.client.force_login(self.admin_user)

        # 1. HTML Reports page loads
        response = self.client.get(reverse('karigar:reports'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Karigar &amp; Manufacturing Reports')

        # 2. Work report CSV export
        csv_resp = self.client.get(reverse('karigar:reports') + '?tab=work&export=csv')
        self.assertEqual(csv_resp.status_code, 200)
        self.assertEqual(csv_resp['Content-Type'], 'text/csv')
        self.assertIn(self.asg.assignment_number.encode(), csv_resp.content)

        # 3. Material accountability CSV export
        mat_resp = self.client.get(reverse('karigar:reports') + '?tab=material&export=csv')
        self.assertEqual(mat_resp.status_code, 200)
        self.assertEqual(mat_resp['Content-Type'], 'text/csv')
        self.assertIn(b'Actual Loss', mat_resp.content)

        # 4. Overdue report CSV export
        overdue_resp = self.client.get(reverse('karigar:reports') + '?tab=overdue&export=csv')
        self.assertEqual(overdue_resp.status_code, 200)
        self.assertEqual(overdue_resp['Content-Type'], 'text/csv')
