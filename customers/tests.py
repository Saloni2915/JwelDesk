from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from customers.models import Customer
from inventory.models import Category, JewelleryItem
from sales.models import Sale


class CustomerModelTests(TestCase):
    def test_customer_creation_and_properties(self):
        customer = Customer.objects.create(
            name='Amit Verma',
            mobile='+91 9988776655',
            email='amit@example.com',
            address='Bengaluru, Karnataka'
        )
        self.assertEqual(str(customer), 'Amit Verma (+91 9988776655)')
        self.assertEqual(customer.total_purchases_count, 0)
        self.assertEqual(customer.total_purchases_amount, 0)

        # Create Category, Item, and Sale
        cat = Category.objects.create(name='Pendants')
        item = JewelleryItem.objects.create(
            item_code='PD-001',
            name='Gold Pendant',
            category=cat,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('4.000'),
            net_weight=Decimal('4.000'),
            selling_price=Decimal('30000.00')
        )
        Sale.objects.create(
            customer=customer,
            jewellery_item=item,
            sale_price=Decimal('30000.00'),
            payment_method='Cash'
        )

        self.assertEqual(customer.total_purchases_count, 1)
        self.assertEqual(customer.total_purchases_amount, Decimal('30000.00'))


class CustomerViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='salesperson', password='Password123')
        self.client.login(username='salesperson', password='Password123')
        self.customer = Customer.objects.create(
            name='Sunita Rao',
            mobile='+91 9123456780',
            email='sunita@example.com',
            address='Hyderabad'
        )

    def test_customer_list_and_search(self):
        response = self.client.get(reverse('customer_list'), {'q': 'Sunita'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sunita Rao')

        response_mobile = self.client.get(reverse('customer_list'), {'q': '9123456780'})
        self.assertEqual(response_mobile.status_code, 200)
        self.assertContains(response_mobile, 'Sunita Rao')

    def test_customer_add_view(self):
        response = self.client.post(reverse('customer_add'), {
            'name': 'Karan Gupta',
            'mobile': '+91 9876000000',
            'email': 'karan@example.com',
            'address': 'Chandigarh',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Customer.objects.filter(mobile='+91 9876000000').exists())

    def test_customer_detail_view(self):
        response = self.client.get(reverse('customer_detail', kwargs={'pk': self.customer.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sunita Rao')
        self.assertContains(response, '+91 9123456780')

    def test_customer_edit_view(self):
        response = self.client.post(reverse('customer_edit', kwargs={'pk': self.customer.pk}), {
            'name': 'Sunita Rao-Patil',
            'mobile': '+91 9123456780',
            'email': 'sunita.patil@example.com',
            'address': 'Secunderabad',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, 'Sunita Rao-Patil')

    def test_customer_delete_view(self):
        response = self.client.post(reverse('customer_delete', kwargs={'pk': self.customer.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Customer.objects.filter(pk=self.customer.pk).exists())



class CustomerOutstandingTests(TestCase):
    """Customer outstanding = Total Sales - Total Paid (derived, never stored)."""

    def setUp(self):
        self.user = User.objects.create_user(username='outdesk', password='Password123')
        self.client.login(username='outdesk', password='Password123')
        self.customer = Customer.objects.create(
            name='Meera Iyer', mobile='+91 9222233333')
        cat = Category.objects.create(name='Bracelets')
        self.item1 = JewelleryItem.objects.create(
            item_code='BR-001', name='Gold Bracelet', category=cat,
            metal_type='Gold', purity='22K',
            gross_weight=Decimal('8.000'), net_weight=Decimal('7.800'),
            selling_price=Decimal('40000.00'))
        self.item2 = JewelleryItem.objects.create(
            item_code='BR-002', name='Silver Bracelet', category=cat,
            metal_type='Silver', purity='925',
            gross_weight=Decimal('30.000'), net_weight=Decimal('29.000'),
            selling_price=Decimal('10000.00'))
        self.sale1 = Sale.objects.create(
            customer=self.customer, jewellery_item=self.item1,
            sale_price=Decimal('40000.00'))
        self.sale2 = Sale.objects.create(
            customer=self.customer, jewellery_item=self.item2,
            sale_price=Decimal('10000.00'))

    def test_outstanding_zero_without_sales(self):
        fresh = Customer.objects.create(name='No Sales Yet', mobile='+91 9111122222')
        self.assertEqual(fresh.total_purchases_amount, 0)
        self.assertEqual(fresh.total_paid_amount, 0)
        self.assertEqual(fresh.outstanding_amount, 0)

    def test_outstanding_before_any_payment(self):
        self.assertEqual(
            self.customer.total_purchases_amount, Decimal('50000.00'))
        self.assertEqual(self.customer.total_paid_amount, 0)
        self.assertEqual(
            self.customer.outstanding_amount, Decimal('50000.00'))

    def test_outstanding_after_partial_payment(self):
        from sales.models import Payment
        Payment.objects.create(
            sale=self.sale1, amount=Decimal('30000.00'), payment_method='UPI')
        self.assertEqual(
            self.customer.total_paid_amount, Decimal('30000.00'))
        self.assertEqual(
            self.customer.outstanding_amount, Decimal('20000.00'))

    def test_outstanding_zero_when_fully_paid(self):
        from sales.models import Payment
        Payment.objects.create(
            sale=self.sale1, amount=Decimal('40000.00'), payment_method='Cash')
        Payment.objects.create(
            sale=self.sale2, amount=Decimal('10000.00'), payment_method='Card')
        self.assertEqual(
            self.customer.total_paid_amount, Decimal('50000.00'))
        self.assertEqual(self.customer.outstanding_amount, 0)

    def test_customer_detail_shows_financial_summary(self):
        from sales.models import Payment
        Payment.objects.create(
            sale=self.sale1, amount=Decimal('30000.00'), payment_method='Cash')
        response = self.client.get(
            reverse('customer_detail', kwargs={'pk': self.customer.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Total Purchase')
        self.assertContains(response, 'Total Paid')
        self.assertContains(response, 'Outstanding')
        # Total purchases 50000.00 and outstanding 20000.00 are rendered
        self.assertContains(response, '50000.00')
        self.assertContains(response, '20000.00')
