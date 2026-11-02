from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from accounts.models import Tenant
from team.models import Branch
from inventory.models import Category, JewelleryItem, StockMovement
from customers.models import Customer
from sales.models import Sale, Payment
from sales.forms import SaleForm


class MultiQuantitySaleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='cashier_test',
            password='Password123!',
            email='cashier@example.com'
        )
        self.tenant = Tenant.objects.create(name="Shree Jewellers", owner=self.user)
        self.branch = Branch.objects.create(
            tenant=self.tenant,
            name="Main Showroom",
            code="MAIN",
            is_default=True,
            is_active=True
        )

        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name="Vikas Sharma",
            mobile="9876543210"
        )
        self.category = Category.objects.create(
            tenant=self.tenant,
            name="Earrings"
        )

        # Create item with 10 quantity and branch=None (e.g. unassigned or added across branches)
        self.item = JewelleryItem.objects.create(
            tenant=self.tenant,
            branch=None,
            tag_number="SHIVAM",
            item_code="SLV-ER-10",
            name="Earing Set",
            category=self.category,
            metal_type="Silver",
            purity="Other",
            quantity=10,
            status="Available",
            gross_weight=Decimal("8.500"),
            net_weight=Decimal("8.500"),
            selling_price=Decimal("2295.00")
        )

        self.client = Client()
        self.client.login(username='cashier_test', password='Password123!')

    def test_unassigned_branch_item_appears_in_sale_form_with_active_branch(self):
        """Item with branch=None MUST be visible in SaleForm when active branch is set."""
        form = SaleForm(tenant=self.tenant, branch=self.branch)
        items_qs = form.fields['jewellery_item'].queryset
        self.assertTrue(
            items_qs.filter(pk=self.item.pk).exists(),
            "Item with branch=None was not found in SaleForm queryset for active branch"
        )

    def test_item_with_quantity_10_can_be_sold_and_sold_again(self):
        """
        Selling an item with 10 pieces must reduce stock to 9 and keep status Available.
        It must remain available for sale again immediately.
        """
        # First sale
        resp1 = self.client.post(reverse('sale_add'), {
            'customer': self.customer.id,
            'jewellery_item': self.item.id,
            'sale_price': '2295.00',
            'payment_method': 'Cash',
            'notes': 'First piece sold'
        }, follow=True)
        self.assertEqual(resp1.status_code, 200)

        # Refresh item from DB
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 9)
        self.assertEqual(self.item.status, 'Available')

        # Verify stock movement
        m1 = StockMovement.objects.filter(item=self.item, sale__isnull=False).latest('created_at')
        self.assertEqual(m1.quantity_change, -1)
        self.assertEqual(m1.stock_before, 10)
        self.assertEqual(m1.stock_after, 9)

        # Verify the item is STILL present in SaleForm for second sale ("sell again")
        form_after_first_sale = SaleForm(tenant=self.tenant, branch=self.branch)
        self.assertTrue(
            form_after_first_sale.fields['jewellery_item'].queryset.filter(pk=self.item.pk).exists(),
            "Item was not found in SaleForm queryset to sell again after first sale"
        )

        # Second sale ("sell again")
        resp2 = self.client.post(reverse('sale_add'), {
            'customer': self.customer.id,
            'jewellery_item': self.item.id,
            'sale_price': '2295.00',
            'payment_method': 'UPI',
            'notes': 'Second piece sold'
        }, follow=True)
        self.assertEqual(resp2.status_code, 200)

        # Refresh item from DB
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 8)
        self.assertEqual(self.item.status, 'Available')

        # Total sales for this item is now 2
        sales_count = Sale.objects.filter(jewellery_item=self.item).count()
        self.assertEqual(sales_count, 2)
