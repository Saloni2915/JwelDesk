"""
tests/test_branch_management.py
--------------------------------
Comprehensive test suite for the JewelDesk Branch-Based Management System.

Covers:
1. Branch Switching & Session Persistence
2. Backend Data Isolation & URL Tampering Prevention (HTTP 403 PermissionDenied)
3. Branch-scoped Stock Calculations & Valuation
4. Branch-to-Branch Stock Transfers & Dual Movement Ledger Audit
5. Dashboard Scoping per Branch vs Consolidated
"""

from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CompanySettings, Tenant
from customers.models import Customer
from custom_orders.models import CustomOrder
from inventory.models import Category, JewelleryItem, StockMovement, StockTransfer, StockTransferItem
from inventory.stock import inventory_summary
from karigar.models import Karigar
from sales.models import Sale
from team.models import Branch, Employee, EmployeePermission, Role
from wholesale.models import RetailerParty

User = get_user_model()


class BranchManagementBaseTestCase(TestCase):
    """Base setup for branch-management test suites."""

    def setUp(self):
        super().setUp()
        Role.ensure_builtin_roles()
        self.admin_role = Role.objects.get(name=Role.ROLE_ADMIN)
        self.sales_role = Role.objects.get(name=Role.ROLE_SALES)

        # ---------------------------------------------------------------------
        # 1. Primary Tenant: Aura Jewellers
        # ---------------------------------------------------------------------
        self.owner_user = User.objects.create_user(
            username='aura_owner',
            email='aura_owner@example.com',
            password='Password123!',
            first_name='Aura',
            last_name='Owner',
        )
        self.tenant = Tenant.objects.create(
            name='Aura Jewellers',
            owner=self.owner_user,
            slug='aura-jewellers',
            is_active=True,
            business_type=Tenant.TYPE_BOTH,
        )
        self.settings = CompanySettings.objects.create(
            tenant=self.tenant,
            company_name='Aura Jewellers',
            phone='9876543210',
            email='aura@example.com',
        )
        self.owner_emp = Employee.objects.create(
            user=self.owner_user,
            tenant=self.tenant,
            full_name='Aura Admin',
            email='aura_owner@example.com',
            role=self.admin_role,
            status=Employee.STATUS_ACTIVE,
            designation='Managing Director',
        )
        self.owner_emp.apply_default_permissions()

        # Branches in Primary Tenant
        self.branch_a = Branch.objects.create(
            tenant=self.tenant,
            name='Downtown Flagship',
            code='DT-01',
            is_default=True,
            is_active=True,
        )
        self.branch_b = Branch.objects.create(
            tenant=self.tenant,
            name='Mall Boutique',
            code='MB-02',
            is_default=False,
            is_active=True,
        )

        # Restricted Staff Member assigned ONLY to branch_a
        self.staff_user = User.objects.create_user(
            username='staff_downtown',
            email='staff@example.com',
            password='Password123!',
            first_name='Staff',
            last_name='Downtown',
        )
        self.staff_emp = Employee.objects.create(
            user=self.staff_user,
            tenant=self.tenant,
            full_name='Downtown Staff',
            email='staff@example.com',
            role=self.sales_role,
            status=Employee.STATUS_ACTIVE,
            designation='Senior Sales Executive',
        )
        self.staff_emp.apply_default_permissions()
        self.staff_emp.branches.add(self.branch_a)
        EmployeePermission.objects.update_or_create(
            employee=self.staff_emp,
            module=EmployeePermission.MODULE_WHOLESALE,
            defaults={'can_view': True, 'can_add': True, 'can_edit': True}
        )

        # ---------------------------------------------------------------------
        # 2. Foreign Tenant: Zenith Jewels (for multi-tenant leak tests)
        # ---------------------------------------------------------------------
        self.foreign_owner = User.objects.create_user(
            username='zenith_owner',
            email='zenith@example.com',
            password='Password123!',
        )
        self.foreign_tenant = Tenant.objects.create(
            name='Zenith Jewels',
            owner=self.foreign_owner,
            slug='zenith-jewels',
            is_active=True,
        )
        self.foreign_branch = Branch.objects.create(
            tenant=self.foreign_tenant,
            name='Zenith Branch 1',
            code='ZN-01',
            is_default=True,
            is_active=True,
        )

        # Category
        self.category = Category.objects.create(
            tenant=self.tenant,
            name='Rings',
        )


class BranchSwitchingTests(BranchManagementBaseTestCase):
    """Test switching branches and session persistence."""

    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_admin_switch_to_valid_branch(self):
        """Admin switches to Branch B; session active_branch_id is updated."""
        self.client.login(username='aura_owner', password='Password123!')
        url = reverse('team:branch_switch')
        response = self.client.post(url, {'branch_id': str(self.branch_b.id)}, HTTP_REFERER='/inventory/')
        self.assertEqual(response.status_code, 302)

        session_key = f'active_branch_id_{self.tenant.id}'
        self.assertEqual(self.client.session.get(session_key), self.branch_b.id)

    def test_admin_switch_to_all_branches(self):
        """Admin switches to consolidated 'all' branches mode."""
        self.client.login(username='aura_owner', password='Password123!')
        url = reverse('team:branch_switch')
        response = self.client.post(url, {'branch_id': 'all'}, HTTP_REFERER='/inventory/')
        self.assertEqual(response.status_code, 302)

        session_key = f'active_branch_id_{self.tenant.id}'
        self.assertEqual(self.client.session.get(session_key), 'all')

    def test_restricted_staff_cannot_switch_to_all(self):
        """Restricted employee assigned to a single branch cannot switch to 'all'."""
        self.client.login(username='staff_downtown', password='Password123!')
        url = reverse('team:branch_switch')
        response = self.client.post(url, {'branch_id': 'all'}, HTTP_REFERER='/inventory/')
        self.assertEqual(response.status_code, 302)

        session_key = f'active_branch_id_{self.tenant.id}'
        # Should NOT be 'all'
        self.assertNotEqual(self.client.session.get(session_key), 'all')

    def test_restricted_staff_cannot_switch_to_unassigned_branch(self):
        """Restricted employee cannot switch to Branch B which they don't belong to."""
        self.client.login(username='staff_downtown', password='Password123!')
        url = reverse('team:branch_switch')
        response = self.client.post(url, {'branch_id': str(self.branch_b.id)}, HTTP_REFERER='/inventory/')
        self.assertEqual(response.status_code, 302)

        session_key = f'active_branch_id_{self.tenant.id}'
        self.assertNotEqual(self.client.session.get(session_key), self.branch_b.id)

    def test_cannot_switch_to_foreign_tenant_branch(self):
        """User cannot switch to a branch owned by another tenant."""
        self.client.login(username='aura_owner', password='Password123!')
        url = reverse('team:branch_switch')
        response = self.client.post(url, {'branch_id': str(self.foreign_branch.id)}, HTTP_REFERER='/inventory/')
        self.assertEqual(response.status_code, 302)

        session_key = f'active_branch_id_{self.tenant.id}'
        self.assertNotEqual(self.client.session.get(session_key), self.foreign_branch.id)


class BranchDataIsolationTests(BranchManagementBaseTestCase):
    """Test data isolation and 403 PermissionDenied on unauthorized branch access."""

    def setUp(self):
        super().setUp()
        self.client = Client()

        # Item in Branch B
        self.item_b = JewelleryItem.objects.create(
            tenant=self.tenant,
            branch=self.branch_b,
            category=self.category,
            item_code='AUR-B-001',
            name='Emerald Ring Branch B',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('6.000'),
            net_weight=Decimal('5.500'),
            selling_price=Decimal('60000.00'),
            status='Available',
            quantity=1,
        )

        # Customer in Branch B
        self.customer_b = Customer.objects.create(
            tenant=self.tenant,
            branch=self.branch_b,
            name='Branch B Client',
            mobile='9988776655',
        )

        # Sale in Branch B
        self.sale_b = Sale.objects.create(
            tenant=self.tenant,
            branch=self.branch_b,
            customer=self.customer_b,
            jewellery_item=self.item_b,
            sale_price=Decimal('60000.00'),
            payment_method='Card',
        )

        # Custom Order in Branch B
        self.order_b = CustomOrder.objects.create(
            tenant=self.tenant,
            branch=self.branch_b,
            customer=self.customer_b,
            category=self.category,
            design_description='Custom diamond ring',
            metal_type='Gold',
            approx_gross_weight=Decimal('5.000'),
            approx_net_weight=Decimal('4.500'),
            estimated_price=Decimal('50000.00'),
            advance_amount=Decimal('10000.00'),
            status=CustomOrder.STATUS_CONFIRMED,
        )

        # Karigar in Branch B
        self.karigar_b = Karigar.objects.create(
            tenant=self.tenant,
            branch=self.branch_b,
            name='Master Karigar B',
            mobile='9123456780',
        )

        # Retailer Party in Branch B
        self.party_b = RetailerParty.objects.create(
            tenant=self.tenant,
            branch=self.branch_b,
            name='Wholesale Retailer B',
            phone='9811122233',
        )

    def test_restricted_staff_cannot_view_other_branch_item(self):
        """Staff assigned to Branch A attempting to view Branch B item detail gets 403."""
        self.client.login(username='staff_downtown', password='Password123!')
        response = self.client.get(reverse('inventory_detail', kwargs={'pk': self.item_b.pk}))
        self.assertEqual(response.status_code, 403)

    def test_restricted_staff_cannot_edit_other_branch_item(self):
        """Staff assigned to Branch A attempting to edit Branch B item gets 403."""
        self.client.login(username='staff_downtown', password='Password123!')
        response = self.client.get(reverse('inventory_edit', kwargs={'pk': self.item_b.pk}))
        self.assertEqual(response.status_code, 403)

    def test_restricted_staff_cannot_view_other_branch_customer(self):
        """Staff assigned to Branch A attempting to view Branch B customer gets 403."""
        self.client.login(username='staff_downtown', password='Password123!')
        response = self.client.get(reverse('customer_detail', kwargs={'pk': self.customer_b.pk}))
        self.assertEqual(response.status_code, 403)

    def test_restricted_staff_cannot_view_other_branch_sale(self):
        """Staff assigned to Branch A attempting to view Branch B sale gets 403."""
        self.client.login(username='staff_downtown', password='Password123!')
        response = self.client.get(reverse('sale_detail', kwargs={'pk': self.sale_b.pk}))
        self.assertEqual(response.status_code, 403)

    def test_restricted_staff_cannot_view_other_branch_custom_order(self):
        """Staff assigned to Branch A attempting to view Branch B custom order gets 403."""
        self.client.login(username='staff_downtown', password='Password123!')
        response = self.client.get(reverse('custom_orders:custom_order_detail', kwargs={'pk': self.order_b.pk}))
        self.assertEqual(response.status_code, 403)

    def test_restricted_staff_cannot_view_other_branch_karigar(self):
        """Staff assigned to Branch A attempting to view Branch B karigar gets 403."""
        self.client.login(username='staff_downtown', password='Password123!')
        response = self.client.get(reverse('karigar:karigar_detail', kwargs={'pk': self.karigar_b.pk}))
        self.assertEqual(response.status_code, 403)

    def test_restricted_staff_cannot_view_other_branch_party(self):
        """Staff assigned to Branch A attempting to view Branch B wholesale party gets 403."""
        self.client.login(username='staff_downtown', password='Password123!')
        response = self.client.get(reverse('wholesale:party_detail', kwargs={'pk': self.party_b.pk}))
        self.assertEqual(response.status_code, 403)


class BranchStockCalculationsTests(BranchManagementBaseTestCase):
    """Test stock summary and inventory valuation scoped per branch vs consolidated."""

    def setUp(self):
        super().setUp()
        # Item 1 in Branch A: 2 pieces, 5g net weight each, selling_price 50,000 each
        self.item_a1 = JewelleryItem.objects.create(
            tenant=self.tenant,
            branch=self.branch_a,
            category=self.category,
            item_code='CALC-A-01',
            name='Gold Ring A1',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.500'),
            net_weight=Decimal('5.000'),
            selling_price=Decimal('50000.00'),
            status='Available',
            quantity=2,
        )
        # Item 2 in Branch A: 1 piece, 10g net weight, selling_price 100,000
        self.item_a2 = JewelleryItem.objects.create(
            tenant=self.tenant,
            branch=self.branch_a,
            category=self.category,
            item_code='CALC-A-02',
            name='Gold Ring A2',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('10.500'),
            net_weight=Decimal('10.000'),
            selling_price=Decimal('100000.00'),
            status='Available',
            quantity=1,
        )
        # Item 3 in Branch B: 3 pieces, 4g net weight each, selling_price 40,000 each
        self.item_b1 = JewelleryItem.objects.create(
            tenant=self.tenant,
            branch=self.branch_b,
            category=self.category,
            item_code='CALC-B-01',
            name='Gold Ring B1',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('4.500'),
            net_weight=Decimal('4.000'),
            selling_price=Decimal('40000.00'),
            status='Available',
            quantity=3,
        )

    def test_summary_scoped_to_branch_a(self):
        """Summary for Branch A counts only Branch A pieces and value."""
        summary = inventory_summary(tenant=self.tenant, branch=self.branch_a)
        # Branch A has 2 catalogue items, total available stock = 2 + 1 = 3 pieces
        self.assertEqual(summary['total_items'], 2)
        self.assertEqual(summary['available_stock'], 3)
        # Total gold weight = 2*5.000 + 1*10.000 = 20.000g
        self.assertEqual(summary['gold_weight'], Decimal('20.000'))
        # Total value = 2*50,000 + 1*100,000 = 200,000.00
        self.assertEqual(summary['inventory_value'], Decimal('200000.00'))

    def test_summary_scoped_to_branch_b(self):
        """Summary for Branch B counts only Branch B pieces and value."""
        summary = inventory_summary(tenant=self.tenant, branch=self.branch_b)
        self.assertEqual(summary['total_items'], 1)
        self.assertEqual(summary['available_stock'], 3)
        # Total gold weight = 3*4.000 = 12.000g
        self.assertEqual(summary['gold_weight'], Decimal('12.000'))
        # Total value = 3*40,000 = 120,000.00
        self.assertEqual(summary['inventory_value'], Decimal('120000.00'))

    def test_summary_consolidated_all_branches(self):
        """Summary with branch=None returns consolidated figures across the entire tenant."""
        summary = inventory_summary(tenant=self.tenant, branch=None)
        # Total items = 3, available stock = 3 + 3 = 6 pieces
        self.assertEqual(summary['total_items'], 3)
        self.assertEqual(summary['available_stock'], 6)
        # Consolidated weight = 20.000 + 12.000 = 32.000g
        self.assertEqual(summary['gold_weight'], Decimal('32.000'))
        # Consolidated value = 200,000 + 120,000 = 320,000.00
        self.assertEqual(summary['inventory_value'], Decimal('320000.00'))


class BranchStockTransferWorkflowTests(BranchManagementBaseTestCase):
    """Test full branch-to-branch transfer cycle and dual StockMovement ledger entries."""

    def setUp(self):
        super().setUp()
        self.transfer_item = JewelleryItem.objects.create(
            tenant=self.tenant,
            branch=self.branch_a,
            category=self.category,
            item_code='TRF-TEST-001',
            name='Transfer Gold Necklace',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('15.000'),
            net_weight=Decimal('14.500'),
            selling_price=Decimal('150000.00'),
            status='Available',
            quantity=1,
        )

    def test_complete_transfer_relocates_piece_and_creates_dual_audit_movements(self):
        """Completing a transfer reassigns item.branch and logs dual audit movements."""
        transfer = StockTransfer.objects.create(
            tenant=self.tenant,
            from_branch=self.branch_a,
            to_branch=self.branch_b,
            status=StockTransfer.STATUS_IN_TRANSIT,
            notes='Showroom display replenishment',
            created_by=self.owner_user,
        )
        transfer_rel = StockTransferItem.objects.create(
            transfer=transfer,
            jewellery_item=self.transfer_item,
            quantity=1,
        )

        # Complete the transfer
        transfer.complete_transfer(user=self.owner_user)

        # 1. Transfer record status
        self.assertEqual(transfer.status, StockTransfer.STATUS_RECEIVED)
        self.assertEqual(transfer.received_by, self.owner_user)
        self.assertIsNotNone(transfer.received_at)

        # 2. Item physical location reassigned
        self.transfer_item.refresh_from_db()
        self.assertEqual(self.transfer_item.branch, self.branch_b)

        # 3. Dual StockMovement audit ledger verification
        movements = StockMovement.objects.filter(item=self.transfer_item).order_by('id')
        self.assertEqual(movements.count(), 2)

        out_movement = movements[0]
        self.assertEqual(out_movement.branch, self.branch_a)
        self.assertEqual(out_movement.movement_type, StockMovement.REDUCTION)
        self.assertEqual(out_movement.quantity_change, -1)
        self.assertEqual(out_movement.reason, 'Branch Transfer Out')
        self.assertIn(self.branch_b.name, out_movement.notes)
        out_movement.full_clean()  # Must satisfy model validation

        in_movement = movements[1]
        self.assertEqual(in_movement.branch, self.branch_b)
        self.assertEqual(in_movement.movement_type, StockMovement.ADDITION)
        self.assertEqual(in_movement.quantity_change, 1)
        self.assertEqual(in_movement.reason, 'Branch Transfer In')
        self.assertIn(self.branch_a.name, in_movement.notes)
        in_movement.full_clean()  # Must satisfy model validation


class BranchDashboardScopingTests(BranchManagementBaseTestCase):
    """Test dashboard and list views branch scoping in HTML responses."""

    def setUp(self):
        super().setUp()
        self.client = Client()

        # Item 1 in Branch A
        self.item_a = JewelleryItem.objects.create(
            tenant=self.tenant,
            branch=self.branch_a,
            category=self.category,
            item_code='DASH-A-01',
            name='Dash Item A',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            net_weight=Decimal('5.000'),
            selling_price=Decimal('50000.00'),
            status='Available',
            quantity=5,
        )
        # Item 2 in Branch B
        self.item_b = JewelleryItem.objects.create(
            tenant=self.tenant,
            branch=self.branch_b,
            category=self.category,
            item_code='DASH-B-01',
            name='Dash Item B',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('8.000'),
            net_weight=Decimal('8.000'),
            selling_price=Decimal('80000.00'),
            status='Available',
            quantity=8,
        )

    def test_dashboard_scoped_to_active_branch(self):
        """Dashboard view returns summary scoped to active branch in session."""
        self.client.login(username='aura_owner', password='Password123!')
        # Set session to Branch A
        session = self.client.session
        session[f'active_branch_id_{self.tenant.id}'] = self.branch_a.id
        session.save()

        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['available_items'], 5)

    def test_dashboard_consolidated_in_all_branches_mode(self):
        """Dashboard view returns consolidated summary when 'all' branches is active."""
        self.client.login(username='aura_owner', password='Password123!')
        # Set session to all branches
        session = self.client.session
        session[f'active_branch_id_{self.tenant.id}'] = 'all'
        session.save()

        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        # Consolidated stock = 5 + 8 = 13
        self.assertEqual(response.context['available_items'], 13)

    def test_inventory_list_scoped_to_branch(self):
        """Inventory catalogue shows only active branch items."""
        self.client.login(username='aura_owner', password='Password123!')
        session = self.client.session
        session[f'active_branch_id_{self.tenant.id}'] = self.branch_a.id
        session.save()

        response = self.client.get(reverse('inventory_list'))
        self.assertEqual(response.status_code, 200)
        item_codes = [it.item_code for it in response.context['items']]
        self.assertIn('DASH-A-01', item_codes)
        self.assertNotIn('DASH-B-01', item_codes)

    def test_stock_transfer_list_view_accessible(self):
        """Stock transfer list page renders with 200 OK."""
        self.client.login(username='aura_owner', password='Password123!')
        response = self.client.get(reverse('stock_transfer_list'))
        self.assertEqual(response.status_code, 200)

