import json
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.exceptions import ValidationError

from accounts.models import Tenant, CompanySettings
from team.models import Branch
from inventory.models import Category, JewelleryItem, StockMovement
from purchases.models import (
    Supplier,
    PurchaseSetting,
    PurchaseSequence,
    PurchaseInvoice,
    PurchaseItem,
    SupplierPayment,
    SupplierLedgerEntry,
    PurchaseReturn,
    PurchaseReturnItem,
)
from purchases.services import (
    confirm_purchase_invoice,
    cancel_purchase_invoice,
    record_supplier_payment,
    cancel_supplier_payment,
    process_purchase_return,
)


class BasePurchaseTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='jeweller_admin',
            password='Password123!',
            email='admin@jeweller.com'
        )
        self.tenant = Tenant.objects.create(
            name="Navratan Jewellers",
            owner=self.user,
            business_type='all'
        )
        self.branch = Branch.objects.create(
            tenant=self.tenant,
            name="Main Showroom",
            code="MSH",
            is_default=True,
            is_active=True
        )
        self.category = Category.objects.create(
            tenant=self.tenant,
            name="Gold Bangles"
        )
        self.settings_obj = PurchaseSetting.load(tenant=self.tenant)

        self.client = Client()
        self.client.login(username='jeweller_admin', password='Password123!')


class SupplierTests(BasePurchaseTestCase):
    def test_supplier_creation_and_auto_code(self):
        """Suppliers must receive auto-generated sequence codes per tenant."""
        s1 = Supplier.objects.create(
            tenant=self.tenant,
            name="Rajesh Exports Bullion",
            mobile="9876543210"
        )
        self.assertTrue(s1.supplier_code.startswith("SUP-"))

        s2 = Supplier.objects.create(
            tenant=self.tenant,
            name="Kalyan Gold Refinery",
            mobile="9876543211"
        )
        self.assertEqual(s2.supplier_code, "SUP-00002")

    def test_supplier_opening_balance_creates_ledger_entry(self):
        """Supplier opening balance must record opening balance in SupplierLedgerEntry and current_balance."""
        sup = Supplier.objects.create(
            tenant=self.tenant,
            name="Shree Bullion",
            mobile="9876543212",
            opening_balance=Decimal('50000.00')
        )
        self.assertEqual(sup.current_balance, Decimal('50000.00'))

        entry = SupplierLedgerEntry.objects.filter(supplier=sup, entry_type='OPENING_BALANCE').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.credit_amount, Decimal('50000.00'))
        self.assertEqual(entry.balance_after, Decimal('50000.00'))


class PurchaseInvoiceCalculationTests(BasePurchaseTestCase):
    def setUp(self):
        super().setUp()
        self.supplier = Supplier.objects.create(
            tenant=self.tenant,
            name="MMTC-PAMP Bullion",
            mobile="9876500001",
            state="Maharashtra",
            state_code="27"
        )

    def test_multi_item_invoice_totals_and_weights(self):
        """Purchase invoice must accurately sum weights, metal value, making charges, and taxes."""
        inv = PurchaseInvoice.objects.create(
            tenant=self.tenant,
            branch=self.branch,
            supplier=self.supplier,
            purchase_type='READY_MADE',
            tax_rate=Decimal('3.00'),
            tax_type='CGST_SGST',
            created_by=self.user
        )

        # Item 1: 22K Gold Bangle (10g, rate 6000/g, making 400/g)
        # Metal value = 10 * 6000 = 60000, Making = 10 * 400 = 4000 => Line pre-tax = 64000
        item1 = PurchaseItem(
            purchase=inv,
            item_name="22K Fancy Bangle",
            category=self.category,
            metal_type="Gold",
            purity="22K",
            purity_percentage=Decimal("91.60"),
            quantity=1,
            gross_weight=Decimal("10.000"),
            stone_weight=Decimal("0.000"),
            purchase_rate=Decimal("6000.00"),
            rate_type="PER_GRAM",
            making_charge_type="Per Gram",
            making_charge_rate=Decimal("400.00"),
            tax_rate=Decimal("3.00")
        )
        item1.save()

        # Item 2: Silver Ring (20g, rate 80/g, flat making 200)
        # Metal value = 20 * 80 = 1600, Making = 200 => Line pre-tax = 1800
        item2 = PurchaseItem(
            purchase=inv,
            item_name="925 Silver Ring",
            category=self.category,
            metal_type="Silver",
            purity="925",
            purity_percentage=Decimal("92.50"),
            quantity=1,
            gross_weight=Decimal("20.000"),
            stone_weight=Decimal("0.000"),
            purchase_rate=Decimal("80.00"),
            rate_type="PER_GRAM",
            making_charge_type="Fixed",
            making_charge_rate=Decimal("200.00"),
            tax_rate=Decimal("3.00")
        )
        item2.save()

        inv.recalculate_totals(save=True)

        self.assertEqual(inv.total_gross_weight, Decimal("30.000"))
        self.assertEqual(inv.total_net_weight, Decimal("30.000"))
        # Fine weights: 10 * 0.916 = 9.160g, 20 * 0.925 = 18.500g => 27.660g
        self.assertEqual(inv.total_fine_weight, Decimal("27.660"))

        # Subtotal: 64000 + 1800 = 65800.00
        self.assertEqual(inv.subtotal, Decimal("65800.00"))
        # 3% GST on 65800 = 1974.00
        self.assertEqual(inv.total_tax_amount, Decimal("1974.00"))
        # CGST/SGST split: 1974 / 2 = 987.00 each
        self.assertEqual(inv.cgst_amount, Decimal("987.00"))
        self.assertEqual(inv.sgst_amount, Decimal("987.00"))
        self.assertEqual(inv.igst_amount, Decimal("0.00"))
        # Grand total = 65800 + 1974 = 67774.00
        self.assertEqual(inv.grand_total, Decimal("67774.00"))
        self.assertEqual(inv.balance_amount, Decimal("67774.00"))

    def test_igst_split_when_interstate(self):
        """Interstate purchases must apply IGST instead of CGST/SGST."""
        inv = PurchaseInvoice.objects.create(
            tenant=self.tenant,
            branch=self.branch,
            supplier=self.supplier,
            purchase_type='GOLD',
            tax_rate=Decimal('3.00'),
            tax_type='IGST',
            created_by=self.user
        )
        item = PurchaseItem.objects.create(
            purchase=inv,
            item_name="Gold Bullion Bar 100g",
            metal_type="Gold",
            purity="24K",
            purity_percentage=Decimal("99.90"),
            quantity=1,
            gross_weight=Decimal("100.000"),
            stone_weight=Decimal("0.000"),
            purchase_rate=Decimal("7000.00"),
            rate_type="PER_GRAM",
            tax_rate=Decimal("3.00")
        )
        inv.recalculate_totals(save=True)

        self.assertEqual(inv.subtotal, Decimal("700000.00"))
        self.assertEqual(inv.cgst_amount, Decimal("0.00"))
        self.assertEqual(inv.sgst_amount, Decimal("0.00"))
        self.assertEqual(inv.igst_amount, Decimal("21000.00"))
        self.assertEqual(inv.grand_total, Decimal("721000.00"))


class InvoiceConfirmationAndStockIntegrationTests(BasePurchaseTestCase):
    def setUp(self):
        super().setUp()
        self.supplier = Supplier.objects.create(
            tenant=self.tenant,
            name="Zaveri Pearls Manufacturer",
            mobile="9876500002"
        )
        self.invoice = PurchaseInvoice.objects.create(
            tenant=self.tenant,
            branch=self.branch,
            supplier=self.supplier,
            purchase_type='READY_MADE',
            tax_rate=Decimal('3.00'),
            created_by=self.user
        )
        self.item = PurchaseItem.objects.create(
            purchase=self.invoice,
            item_name="22K Traditional Choker",
            category=self.category,
            metal_type="Gold",
            purity="22K",
            purity_percentage=Decimal("91.60"),
            quantity=2,
            gross_weight=Decimal("25.000"),
            stone_weight=Decimal("2.000"),
            purchase_rate=Decimal("6200.00"),
            rate_type="PER_GRAM",
            huid="HUID77",
            hallmark_details="BIS 916",
            tax_rate=Decimal("3.00")
        )
        self.invoice.recalculate_totals(save=True)

    def test_draft_invoice_does_not_affect_stock_or_ledger(self):
        """A draft invoice must not create inventory pieces or change supplier balances."""
        self.assertEqual(self.invoice.status, 'DRAFT')
        self.assertEqual(self.invoice.inventory_status, 'PENDING')
        self.assertEqual(JewelleryItem.objects.filter(tenant=self.tenant).count(), 0)
        self.assertEqual(self.supplier.current_balance, Decimal('0.00'))

    def test_confirm_purchase_creates_inventory_and_posts_ledger(self):
        """Confirming an invoice auto-creates JewelleryItem in branch and updates supplier balance."""
        inv = confirm_purchase_invoice(self.invoice.pk, user=self.user)

        self.assertEqual(inv.status, 'CONFIRMED')
        self.assertEqual(inv.inventory_status, 'STOCKED')
        self.assertIsNotNone(inv.confirmed_at)
        self.assertEqual(inv.confirmed_by, self.user)

        # 1. JewelleryItem was created
        self.item.refresh_from_db()
        self.assertIsNotNone(self.item.inventory_item)
        stock_item = self.item.inventory_item
        self.assertEqual(stock_item.tenant, self.tenant)
        self.assertEqual(stock_item.branch, self.branch)
        self.assertEqual(stock_item.quantity, 2)
        self.assertEqual(stock_item.gross_weight, Decimal("25.000"))
        self.assertEqual(stock_item.net_weight, Decimal("23.000"))
        self.assertEqual(stock_item.huid, "HUID77")
        self.assertEqual(stock_item.status, "Available")
        self.assertTrue(len(stock_item.item_code) > 0)

        # 2. StockMovement audit trail recorded
        movement = StockMovement.objects.filter(item=stock_item).first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity_change, 2)
        self.assertEqual(movement.stock_after, 2)
        self.assertIn("Purchase Intake", movement.notes)

        # 3. Supplier Ledger updated
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.current_balance, inv.grand_total)

        ledger_entry = SupplierLedgerEntry.objects.filter(purchase_invoice=inv).first()
        self.assertIsNotNone(ledger_entry)
        self.assertEqual(ledger_entry.credit_amount, inv.grand_total)
        self.assertEqual(ledger_entry.balance_after, inv.grand_total)

    def test_idempotent_confirmation_prevents_duplicate_stock(self):
        """Re-confirming an already confirmed invoice must fail gracefully and not duplicate stock."""
        confirm_purchase_invoice(self.invoice.pk, user=self.user)
        self.assertEqual(JewelleryItem.objects.filter(tenant=self.tenant).count(), 1)

        # Second confirmation call should raise ValidationError
        with self.assertRaises(ValidationError):
            confirm_purchase_invoice(self.invoice.pk, user=self.user)

        # Stock count remains 1
        self.assertEqual(JewelleryItem.objects.filter(tenant=self.tenant).count(), 1)


class SupplierPaymentTests(BasePurchaseTestCase):
    def setUp(self):
        super().setUp()
        self.supplier = Supplier.objects.create(
            tenant=self.tenant,
            name="Emerald Diamond Imports",
            mobile="9876500003"
        )
        self.invoice = PurchaseInvoice.objects.create(
            tenant=self.tenant,
            branch=self.branch,
            supplier=self.supplier,
            purchase_type='READY_MADE',
            tax_rate=Decimal('3.00'),
            created_by=self.user
        )
        PurchaseItem.objects.create(
            purchase=self.invoice,
            item_name="Diamond Solitaire Ring",
            metal_type="Gold",
            purity="18K",
            quantity=1,
            gross_weight=Decimal("5.000"),
            net_weight=Decimal("5.000"),
            purchase_rate=Decimal("100000.00"),
            rate_type="FLAT",
            tax_rate=Decimal("3.00")
        )
        self.invoice.recalculate_totals(save=True)
        confirm_purchase_invoice(self.invoice.pk, user=self.user)
        self.invoice.refresh_from_db()
        # Grand total = 100000 + 3% = 103000.00

    def test_partial_payment_against_invoice(self):
        """Recording a partial payment updates invoice paid, balance, and status to PARTIALLY_PAID."""
        payment = record_supplier_payment(
            tenant=self.tenant,
            supplier=self.supplier,
            amount=Decimal('50000.00'),
            payment_method='Bank Transfer',
            purchase_invoice=self.invoice,
            branch=self.branch,
            user=self.user,
            reference='UTR123456789'
        )

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('50000.00'))
        self.assertEqual(self.invoice.balance_amount, Decimal('53000.00'))
        self.assertEqual(self.invoice.status, 'PARTIALLY_PAID')

        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.current_balance, Decimal('53000.00'))

        # Check ledger debit
        entry = SupplierLedgerEntry.objects.filter(payment=payment).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.debit_amount, Decimal('50000.00'))
        self.assertEqual(entry.balance_after, Decimal('53000.00'))

    def test_full_payment_against_invoice(self):
        """Paying the full balance transitions invoice status to PAID."""
        record_supplier_payment(
            tenant=self.tenant,
            supplier=self.supplier,
            amount=self.invoice.balance_amount,
            payment_method='UPI',
            purchase_invoice=self.invoice,
            branch=self.branch,
            user=self.user
        )

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.balance_amount, Decimal('0.00'))
        self.assertEqual(self.invoice.status, 'PAID')

        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.current_balance, Decimal('0.00'))

    def test_payment_cancellation_reverses_balance_and_ledger(self):
        """Cancelling a payment safely restores invoice balance and adds reversing ledger entry."""
        payment = record_supplier_payment(
            tenant=self.tenant,
            supplier=self.supplier,
            amount=Decimal('30000.00'),
            payment_method='Cash',
            purchase_invoice=self.invoice,
            user=self.user
        )

        cancel_supplier_payment(payment.pk, user=self.user, reason="Bounced cheque")

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))
        self.assertEqual(self.invoice.balance_amount, Decimal('103000.00'))

        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.current_balance, Decimal('103000.00'))


class PurchaseReturnTests(BasePurchaseTestCase):
    def setUp(self):
        super().setUp()
        self.supplier = Supplier.objects.create(
            tenant=self.tenant,
            name="Siddhivinayak Chains",
            mobile="9876500004"
        )
        self.invoice = PurchaseInvoice.objects.create(
            tenant=self.tenant,
            branch=self.branch,
            supplier=self.supplier,
            purchase_type='READY_MADE',
            tax_rate=Decimal('3.00'),
            created_by=self.user
        )
        self.item = PurchaseItem.objects.create(
            purchase=self.invoice,
            item_name="Gold Hollow Chain",
            metal_type="Gold",
            purity="22K",
            quantity=5,
            gross_weight=Decimal("50.000"),
            net_weight=Decimal("50.000"),
            purchase_rate=Decimal("6000.00"),
            rate_type="PER_GRAM",
            tax_rate=Decimal("3.00")
        )
        self.invoice.recalculate_totals(save=True)
        confirm_purchase_invoice(self.invoice.pk, user=self.user)
        self.invoice.refresh_from_db()
        self.item.refresh_from_db()

    def test_purchase_return_reduces_stock_and_generates_debit_note(self):
        """Returning 2 pieces must reduce stock to 3, post debit note, and adjust bill balance."""
        stock_item = self.item.inventory_item
        self.assertEqual(stock_item.quantity, 5)

        ret = process_purchase_return(
            invoice_id=self.invoice.pk,
            return_items_data=[{
                'item_id': self.item.pk,
                'quantity': 2,
                'weight': Decimal('20.000'),
                'reason': 'Purity mismatch'
            }],
            reason="Purity mismatch",
            adjustment_mode='REDUCE_INVOICE_BALANCE',
            user=self.user
        )

        # 1. Debit Note created
        self.assertEqual(ret.total_return_quantity, 2)
        self.assertEqual(ret.total_return_weight, Decimal('20.000'))
        self.assertTrue(ret.total_return_amount > 0)

        # 2. Stock decremented
        stock_item.refresh_from_db()
        self.assertEqual(stock_item.quantity, 3)

        # 3. StockMovement logged
        sm = StockMovement.objects.filter(item=stock_item).latest('created_at')
        self.assertEqual(sm.quantity_change, -2)
        self.assertIn("Purchase Return", sm.notes)

        # 4. Item returned_quantity updated
        self.item.refresh_from_db()
        self.assertEqual(self.item.returned_quantity, 2)
        self.assertEqual(self.item.returned_weight, Decimal('20.000'))

        # 5. Invoice return status updated
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.inventory_status, 'PARTIALLY_RETURNED')

    def test_cannot_return_more_than_purchased_quantity(self):
        """Attempting to return more than purchased pieces must raise a ValidationError."""
        with self.assertRaises(ValidationError):
            process_purchase_return(
                invoice_id=self.invoice.pk,
                return_items_data=[{
                    'item_id': self.item.pk,
                    'quantity': 10,  # Only 5 purchased
                    'weight': Decimal('100.000'),
                    'reason': 'Excess return'
                }],
                reason="Invalid",
                user=self.user
            )


class PurchaseViewsTests(BasePurchaseTestCase):
    def test_purchase_dashboard_view_200(self):
        """Dashboard view responds with 200 OK and metrics."""
        resp = self.client.get(reverse('purchases:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Purchase Management")

    def test_purchase_list_view_200(self):
        """Purchase register view responds with 200 OK."""
        resp = self.client.get(reverse('purchases:purchase_list'))
        self.assertEqual(resp.status_code, 200)

    def test_supplier_list_and_create_views(self):
        """Supplier listing and creation flow works."""
        resp = self.client.get(reverse('purchases:supplier_list'))
        self.assertEqual(resp.status_code, 200)

        post_resp = self.client.post(reverse('purchases:supplier_create'), {
            'name': 'Titan Tanishq Supplier',
            'mobile': '9988776655',
            'gstin': '27ABCDE1234F1Z5',
            'opening_balance': '10000.00',
            'is_active': True
        })
        self.assertEqual(post_resp.status_code, 302)
        supplier = Supplier.objects.filter(name='Titan Tanishq Supplier').first()
        self.assertIsNotNone(supplier)

        # Test supplier detail view renders with 200 OK without filter errors
        detail_resp = self.client.get(reverse('purchases:supplier_detail', kwargs={'pk': supplier.pk}))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, "Titan Tanishq Supplier")

    def test_purchase_reports_view_across_tabs(self):
        """Reports view loads for all 6 tab types without error."""
        for report_tab in ['register', 'supplier', 'metal', 'outstanding', 'payments', 'tax']:
            resp = self.client.get(reverse('purchases:reports'), {'report': report_tab})
            self.assertEqual(resp.status_code, 200)

    def test_purchase_settings_view_get_and_post(self):
        """Settings view allows changing module prefixes and tax defaults."""
        resp = self.client.get(reverse('purchases:settings'))
        self.assertEqual(resp.status_code, 200)

        post_resp = self.client.post(reverse('purchases:settings'), {
            'purchase_prefix': 'INV-P',
            'payment_prefix': 'VCH-P',
            'return_prefix': 'RET-P',
            'supplier_prefix': 'VND',
            'default_payment_terms_days': 45,
            'default_tax_rate': '3.00',
            'default_tax_type': 'CGST_SGST',
            'auto_create_inventory_for_ready_made': True
        })
        self.assertEqual(post_resp.status_code, 302)
        self.settings_obj.refresh_from_db()
        self.assertEqual(self.settings_obj.purchase_prefix, 'INV-P')
        self.assertEqual(self.settings_obj.default_payment_terms_days, 45)
