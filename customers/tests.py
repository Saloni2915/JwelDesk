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

