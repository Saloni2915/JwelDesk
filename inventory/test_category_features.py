from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Tenant
from inventory.models import Category, ensure_default_categories, DEFAULT_JEWELLERY_CATEGORIES
from inventory.forms import JewelleryItemForm

User = get_user_model()


class CategoryFeatureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testjeweller',
            email='test@jeweller.com',
            password='Password@123',
            first_name='Test',
            last_name='Jeweller'
        )
        self.tenant = Tenant.objects.create(
            name='Test Jewellers',
            owner=self.user,
            business_type=Tenant.TYPE_RETAIL
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_ensure_default_categories_seeds_standard_categories(self):
        """When a tenant has 0 categories, ensure_default_categories seeds all standard categories."""
        self.assertEqual(Category.objects.filter(tenant=self.tenant).count(), 0)
        qs = ensure_default_categories(self.tenant)
        self.assertEqual(qs.count(), len(DEFAULT_JEWELLERY_CATEGORIES))
        self.assertTrue(Category.objects.filter(tenant=self.tenant, name="Rings").exists())
        self.assertTrue(Category.objects.filter(tenant=self.tenant, name="Mangalsutra").exists())

    def test_ensure_default_categories_does_not_duplicate_existing(self):
        """Calling ensure_default_categories multiple times does not create duplicates."""
        ensure_default_categories(self.tenant)
        initial_count = Category.objects.filter(tenant=self.tenant).count()
        ensure_default_categories(self.tenant)
        self.assertEqual(Category.objects.filter(tenant=self.tenant).count(), initial_count)

    def test_item_form_auto_seeds_categories(self):
        """Instantiating JewelleryItemForm for a tenant auto-seeds categories so dropdown is not empty."""
        self.assertEqual(Category.objects.filter(tenant=self.tenant).count(), 0)
        form = JewelleryItemForm(tenant=self.tenant)
        self.assertGreater(form.fields['category'].queryset.count(), 0)
        self.assertTrue(form.fields['category'].queryset.filter(name="Rings").exists())

    def test_category_quick_add_api_success(self):
        """category_quick_add endpoint successfully creates and returns category JSON."""
        url = reverse('category_quick_add')
        response = self.client.post(url, {
            'name': 'Custom Kundan Sets',
            'description': 'Handcrafted bridal kundan'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['category']['name'], 'Custom Kundan Sets')

        cat = Category.objects.get(id=data['category']['id'])
        self.assertEqual(cat.tenant, self.tenant)
        self.assertEqual(cat.name, 'Custom Kundan Sets')

    def test_category_quick_add_handles_existing_name(self):
        """category_quick_add returns existing category ID instead of throwing error if name already exists."""
        Category.objects.create(tenant=self.tenant, name='Solitaires')
        url = reverse('category_quick_add')
        response = self.client.post(url, {
            'name': 'Solitaires'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data.get('already_exists'))
        self.assertEqual(data['category']['name'], 'Solitaires')

    def test_category_quick_add_validation_error_on_empty(self):
        """category_quick_add rejects empty name."""
        url = reverse('category_quick_add')
        response = self.client.post(url, {'name': '   '})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])

