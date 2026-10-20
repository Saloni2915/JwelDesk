from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, CompanySettings
from inventory.models import Category, JewelleryItem, StockMovement
from team.models import Role, Employee, EmployeePermission
from wholesale.models import (
    RetailerParty,
    RetailerPayment,
    RetailerPaymentAllocation,
    RetailerLedgerEntry,
    WholesaleOrder,
    WholesaleOrderItem,
    WholesaleDispatch,
    WholesaleDispatchItem,
    WholesaleInvoice,
    WholesaleInvoiceItem,
    WholesaleReturn,
    WholesaleReturnItem,
    WholesalePricingRule,
    WholesaleSequence,
)
from wholesale.stock_service import (
    confirm_wholesale_order,
    execute_wholesale_dispatch,
    restock_wholesale_return_item,
    validate_order_stock_availability,
)
from wholesale.invoice_service import (
    create_invoice_for_order,
    record_retailer_payment,
    issue_wholesale_credit_note,
)
from wholesale.pricing_service import get_wholesale_item_price

User = get_user_model()


class WholesaleModuleTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Tenant 1: Wholesale Supplier
        self.user1 = User.objects.create_user(
            username='supplier1',
            email='supplier1@test.com',
            password='Password123!',
            first_name='Supplier One'
        )
        self.tenant1 = Tenant.objects.create(
            name='Kuber Bullion Wholesale',
            owner=self.user1,
            business_type=Tenant.TYPE_WHOLESALE
        )
        self.settings1 = CompanySettings.objects.create(
            tenant=self.tenant1,
            company_name='Kuber Bullion Wholesale',
            gstin='27ABCDE1234F1Z5'
        )
        Employee.ensure_tenant_admin(self.tenant1, self.user1)

        # Tenant 2: Separate Supplier (for Cross-Tenant Isolation checks)
        self.user2 = User.objects.create_user(
            username='supplier2',
            email='supplier2@test.com',
            password='Password123!',
            first_name='Supplier Two'
        )
        self.tenant2 = Tenant.objects.create(
            name='Laxmi Gems Wholesaler',
            owner=self.user2,
            business_type=Tenant.TYPE_WHOLESALE
        )
        self.settings2 = CompanySettings.objects.create(
            tenant=self.tenant2,
            company_name='Laxmi Gems Wholesaler'
        )
        Employee.ensure_tenant_admin(self.tenant2, self.user2)

        # Inventory in Tenant 1
        self.cat_gold = Category.objects.create(tenant=self.tenant1, name='Gold Necklaces')
        self.item1 = JewelleryItem.objects.create(
            tenant=self.tenant1,
            category=self.cat_gold,
            name='22K Heritage Royal Necklace',
            item_code='NK-001',
            tag_number='JWL-100001',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('25.500'),
            stone_weight=Decimal('0.500'),
            net_weight=Decimal('25.000'),
            selling_price=Decimal('150000.00'),
            quantity=5,
            status='Available'
        )
        self.item2 = JewelleryItem.objects.create(
            tenant=self.tenant1,
            category=self.cat_gold,
            name='22K Floral Bangles Pair',
            item_code='BG-002',
            tag_number='JWL-100002',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('30.000'),
            net_weight=Decimal('30.000'),
            selling_price=Decimal('180000.00'),
            quantity=2,
            status='Available'
        )

        # Inventory in Tenant 2
        self.cat2 = Category.objects.create(tenant=self.tenant2, name='Silver Chains')
        self.item_tenant2 = JewelleryItem.objects.create(
            tenant=self.tenant2,
            category=self.cat2,
            name='925 Silver Curb Chain',
            item_code='SLV-001',
            tag_number='JWL-200001',
            metal_type='Silver',
            purity='925',
            gross_weight=Decimal('50.000'),
            net_weight=Decimal('50.000'),
            selling_price=Decimal('5000.00'),
            quantity=10,
            status='Available'
        )

        # Retailer Party in Tenant 1
        self.party1 = RetailerParty.objects.create(
            tenant=self.tenant1,
            name='Sri Balaji Jewellers',
            contact_person='Ramesh Balaji',
            phone='9876543210',
            email='balaji@jewellers.com',
            gstin='27AAAAA0000A1Z5',
            credit_limit=Decimal('500000.00'),
            payment_terms_days=30,
            opening_balance=Decimal('10000.00')
        )

        # Retailer Party in Tenant 2
        self.party2 = RetailerParty.objects.create(
            tenant=self.tenant2,
            name='Mangal Murti Jewellers',
            contact_person='Suresh Joshi',
            phone='9123456780',
            credit_limit=Decimal('200000.00')
        )

    # --------------------------------------------------------------------------
    # 1. Business Type & Tenant Isolation Tests
    # --------------------------------------------------------------------------
    def test_tenant_business_type_helpers(self):
        self.assertTrue(self.tenant1.is_wholesale)
        self.assertFalse(self.tenant1.is_retail)

        hybrid = Tenant.objects.create(name='Hybrid Store', owner=self.user1, business_type=Tenant.TYPE_BOTH)
        self.assertTrue(hybrid.is_retail)
        self.assertTrue(hybrid.is_wholesale)

        retail = Tenant.objects.create(name='Retail Store', owner=self.user1, business_type=Tenant.TYPE_RETAIL)
        self.assertTrue(retail.is_retail)
        self.assertFalse(retail.is_wholesale)

    def test_cross_tenant_isolation_party_access(self):
        """Supplier 2 must not be able to view or edit Supplier 1's retailer party."""
        self.client.login(username='supplier2', password='Password123!')

        # Attempt to access party of Tenant 1
        url = reverse('wholesale:party_detail', kwargs={'pk': self.party1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        edit_url = reverse('wholesale:party_edit', kwargs={'pk': self.party1.pk})
        response = self.client.get(edit_url)
        self.assertEqual(response.status_code, 404)

    def test_party_name_unique_per_tenant(self):
        """Duplicate party name in the same tenant must raise ValidationError, but allowed across tenants."""
        with self.assertRaises(ValidationError):
            p_dup = RetailerParty(tenant=self.tenant1, name='Sri Balaji Jewellers', phone='9999999999')
            p_dup.full_clean()

        # Same name in Tenant 2 is completely valid
        p_tenant2 = RetailerParty.objects.create(
            tenant=self.tenant2,
            name='Sri Balaji Jewellers',
            phone='9999999999'
        )
        self.assertEqual(p_tenant2.tenant, self.tenant2)

    # --------------------------------------------------------------------------
    # 2. Pricing Engine & Pricing Rules Tests
    # --------------------------------------------------------------------------
    def test_wholesale_pricing_rule_application(self):
        """Test category-wide and party-specific wholesale pricing calculation."""
        # Baseline price without rule
        p_base = get_wholesale_item_price(self.item1)
        self.assertEqual(p_base['unit_price'], Decimal('150000.00'))

        # Add 10% wholesale discount rule for Gold Necklaces category
        rule = WholesalePricingRule.objects.create(
            tenant=self.tenant1,
            category=self.cat_gold,
            discount_percent=Decimal('10.00'),
            minimum_order_quantity=1
        )

        p_discounted = get_wholesale_item_price(self.item1)
        # 150000 - 10% = 135000
        self.assertEqual(p_discounted['unit_price'], Decimal('135000.00'))
        self.assertEqual(p_discounted['discount_percent'], Decimal('10.00'))

    # --------------------------------------------------------------------------
    # 3. Wholesale Order Lifecycle & Stock Verification Tests
    # --------------------------------------------------------------------------
    def test_order_creation_and_confirmation(self):
        order = WholesaleOrder.objects.create(
            tenant=self.tenant1,
            order_number='WORD-00001',
            party=self.party1,
            status=WholesaleOrder.STATUS_DRAFT
        )
        line = WholesaleOrderItem.objects.create(
            order=order,
            item=self.item1,
            quantity=3,
            unit_price=Decimal('140000.00'),
            tax_rate=Decimal('3.00'),
            tax_amount=Decimal('12600.00'),
            total_price=Decimal('432600.00')
        )
        order.calculate_totals(save=True)
        self.assertEqual(order.total_quantity, 3)

        # Confirm order (verifies stock)
        confirm_wholesale_order(order, user=self.user1)
        order.refresh_from_db()
        self.assertEqual(order.status, WholesaleOrder.STATUS_CONFIRMED)

    def test_order_confirmation_fails_if_insufficient_stock(self):
        """Order confirmation must fail if requested quantity exceeds in-stock quantity."""
        order = WholesaleOrder.objects.create(
            tenant=self.tenant1,
            order_number='WORD-00002',
            party=self.party1,
            status=WholesaleOrder.STATUS_DRAFT
        )
        # Item 1 only has 5 pieces in stock, order requests 10
        WholesaleOrderItem.objects.create(
            order=order,
            item=self.item1,
            quantity=10,
            unit_price=Decimal('140000.00'),
            total_price=Decimal('1400000.00')
        )
        with self.assertRaises(ValidationError):
            confirm_wholesale_order(order, user=self.user1)

    # --------------------------------------------------------------------------
    # 4. Atomic Stock Dispatch & Inventory Reduction Tests
    # --------------------------------------------------------------------------
    def test_dispatch_reduces_physical_stock_and_creates_movement(self):
        """Dispatching must atomically reduce inventory stock and log a StockMovement."""
        initial_stock = self.item1.quantity
        order = WholesaleOrder.objects.create(
            tenant=self.tenant1,
            order_number='WORD-00003',
            party=self.party1,
            status=WholesaleOrder.STATUS_CONFIRMED
        )
        line = WholesaleOrderItem.objects.create(
            order=order,
            item=self.item1,
            quantity=2,
            unit_price=Decimal('140000.00'),
            tax_rate=Decimal('3.00'),
            tax_amount=Decimal('8400.00'),
            total_price=Decimal('288400.00')
        )
        order.calculate_totals(save=True)

        dispatch = execute_wholesale_dispatch(
            order=order,
            dispatch_items_data=[{'order_item_id': line.id, 'quantity': 2, 'tag_number': 'JWL-100001'}],
            courier_name='BVC Secure Logistics',
            tracking_number='AWB-123456',
            user=self.user1
        )

        self.item1.refresh_from_db()
        self.assertEqual(self.item1.quantity, initial_stock - 2)

        # Check stock movement audit
        movement = StockMovement.objects.filter(item=self.item1, reason='Wholesale Dispatch').latest('id')
        self.assertEqual(movement.quantity_change, -2)
        self.assertEqual(movement.stock_after, initial_stock - 2)

        line.refresh_from_db()
        self.assertEqual(line.dispatched_quantity, 2)
        order.refresh_from_db()
        self.assertEqual(order.status, WholesaleOrder.STATUS_DISPATCHED)

    def test_dispatch_cannot_exceed_order_quantity(self):
        """Attempting to dispatch more than remaining order quantity must raise ValidationError."""
        order = WholesaleOrder.objects.create(
            tenant=self.tenant1,
            order_number='WORD-00004',
            party=self.party1,
            status=WholesaleOrder.STATUS_CONFIRMED
        )
        line = WholesaleOrderItem.objects.create(
            order=order,
            item=self.item1,
            quantity=1,
            unit_price=Decimal('140000.00'),
            total_price=Decimal('140000.00')
        )
        with self.assertRaises(ValidationError):
            execute_wholesale_dispatch(
                order=order,
                dispatch_items_data=[{'order_item_id': line.id, 'quantity': 5}],
                user=self.user1
            )

    # --------------------------------------------------------------------------
    # 5. Invoicing, Payments, Allocations & Ledger Reconciliation
    # --------------------------------------------------------------------------
    def test_invoice_creation_and_party_ledger_debit(self):
        order = WholesaleOrder.objects.create(
            tenant=self.tenant1,
            order_number='WORD-00005',
            party=self.party1,
            status=WholesaleOrder.STATUS_CONFIRMED
        )
        WholesaleOrderItem.objects.create(
            order=order,
            item=self.item1,
            quantity=1,
            unit_price=Decimal('100000.00'),
            tax_rate=Decimal('3.00'),
            tax_amount=Decimal('3000.00'),
            total_price=Decimal('103000.00')
        )
        order.calculate_totals(save=True)

        inv = create_invoice_for_order(order=order, user=self.user1)
        self.assertEqual(inv.total_amount, Decimal('103000.00'))

        # Check that a ledger entry was recorded for debit
        entry = RetailerLedgerEntry.objects.filter(party=self.party1, invoice=inv).latest('id')
        self.assertEqual(entry.entry_type, RetailerLedgerEntry.TYPE_INVOICE)
        self.assertEqual(entry.debit_amount, Decimal('103000.00'))

    def test_payment_recording_allocations_and_ledger_credit(self):
        # Create an invoice
        order = WholesaleOrder.objects.create(
            tenant=self.tenant1,
            order_number='WORD-00006',
            party=self.party1,
            status=WholesaleOrder.STATUS_CONFIRMED
        )
        WholesaleOrderItem.objects.create(
            order=order,
            item=self.item1,
            quantity=1,
            unit_price=Decimal('50000.00'),
            tax_rate=Decimal('3.00'),
            tax_amount=Decimal('1500.00'),
            total_price=Decimal('51500.00')
        )
        order.calculate_totals(save=True)
        inv = create_invoice_for_order(order=order, user=self.user1)

        # Record partial payment of 30,000
        pay = record_retailer_payment(
            party=self.party1,
            amount=Decimal('30000.00'),
            payment_method='Bank Transfer',
            reference='UTR-999888',
            user=self.user1
        )

        inv.refresh_from_db()
        self.assertEqual(inv.paid_amount, Decimal('30000.00'))
        self.assertEqual(inv.outstanding_amount, Decimal('21500.00'))
        self.assertEqual(inv.status, WholesaleInvoice.STATUS_PARTIALLY_PAID)

        # Verify ledger credit
        credit_entry = RetailerLedgerEntry.objects.filter(party=self.party1, payment=pay).latest('id')
        self.assertEqual(credit_entry.credit_amount, Decimal('30000.00'))

        # Pay remaining balance
        record_retailer_payment(
            party=self.party1,
            amount=Decimal('21500.00'),
            user=self.user1
        )
        inv.refresh_from_db()
        self.assertEqual(inv.status, WholesaleInvoice.STATUS_PAID)
        self.assertEqual(inv.outstanding_amount, Decimal('0.00'))

    # --------------------------------------------------------------------------
    # 6. Returns, Restocking & Credit Note Tests
    # --------------------------------------------------------------------------
    def test_wholesale_return_restock_and_credit_note(self):
        ret = WholesaleReturn.objects.create(
            tenant=self.tenant1,
            return_number='WRET-00001',
            party=self.party1,
            reason='Customer size exchange',
            status=WholesaleReturn.STATUS_REQUESTED
        )
        ret_item = WholesaleReturnItem.objects.create(
            wholesale_return=ret,
            item=self.item1,
            quantity=1,
            unit_price=Decimal('100000.00'),
            disposition=WholesaleReturnItem.DISP_SELLABLE,
            restocked=False
        )
        ret.calculate_totals(save=True)

        # Approve return
        ret.status = WholesaleReturn.STATUS_APPROVED
        ret.save()

        # Restock item into showroom inventory
        stock_before = self.item1.quantity
        restock_wholesale_return_item(ret_item, user=self.user1)

        self.item1.refresh_from_db()
        self.assertEqual(self.item1.quantity, stock_before + 1)
        ret_item.refresh_from_db()
        self.assertTrue(ret_item.restocked)

        # Issue Credit Note
        issue_wholesale_credit_note(ret, user=self.user1)
        ret.refresh_from_db()
        self.assertTrue(ret.credit_note_issued)
        self.assertTrue(ret.credit_note_number.startswith('WCN-'))

        # Verify credit note in retailer ledger
        cn_entry = RetailerLedgerEntry.objects.filter(party=self.party1, return_ref=ret).latest('id')
        self.assertEqual(cn_entry.entry_type, RetailerLedgerEntry.TYPE_CREDIT_NOTE)
        self.assertEqual(cn_entry.credit_amount, Decimal('100000.00'))

    # --------------------------------------------------------------------------
    # 7. UI Views & Integration Endpoints
    # --------------------------------------------------------------------------
    def test_wholesale_views_render(self):
        self.client.login(username='supplier1', password='Password123!')

        # Dashboard
        res = self.client.get(reverse('wholesale:dashboard'))
        self.assertEqual(res.status_code, 200)

        # Retailer Parties List
        res = self.client.get(reverse('wholesale:party_list'))
        self.assertEqual(res.status_code, 200)

        # Retailer Party Detail
        res = self.client.get(reverse('wholesale:party_detail', kwargs={'pk': self.party1.pk}))
        self.assertEqual(res.status_code, 200)

        # Catalogue View
        res = self.client.get(reverse('wholesale:catalogue'))
        self.assertEqual(res.status_code, 200)

        # Orders List
        res = self.client.get(reverse('wholesale:order_list'))
        self.assertEqual(res.status_code, 200)

        # Dispatches List
        res = self.client.get(reverse('wholesale:dispatch_list'))
        self.assertEqual(res.status_code, 200)

        # Invoices List
        res = self.client.get(reverse('wholesale:invoice_list'))
        self.assertEqual(res.status_code, 200)

        # Payments List
        res = self.client.get(reverse('wholesale:payment_list'))
        self.assertEqual(res.status_code, 200)

        # Ledger View
        res = self.client.get(reverse('wholesale:ledger_view'))
        self.assertEqual(res.status_code, 200)

        # Returns List
        res = self.client.get(reverse('wholesale:return_list'))
        self.assertEqual(res.status_code, 200)

        # Reports Dashboard
        res = self.client.get(reverse('wholesale:reports'))
        self.assertEqual(res.status_code, 200)

        # CSV Export
        res = self.client.get(reverse('wholesale:party_ledger_csv', kwargs={'party_pk': self.party1.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'text/csv')
