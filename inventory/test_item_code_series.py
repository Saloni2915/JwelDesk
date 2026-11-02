from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import Tenant, CompanySettings
from inventory.models import JewelleryItem, Category
from inventory.forms import JewelleryItemForm

User = get_user_model()


class ItemCodeSeriesAndMandatoryFieldsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='jeweller_test',
            email='test@jeweller.com',
            password='Password123!',
            is_staff=True
        )
        self.tenant = Tenant.objects.create(
            name="Apex Jewellers",
            slug="apex-jewellers",
            owner=self.user,
            is_active=True
        )
        self.settings = CompanySettings.load(tenant=self.tenant)
        self.client = Client()
        self.client.login(username='jeweller_test', password='Password123!')

    def test_only_metal_type_is_mandatory_in_form(self):
        """Form must be valid with ONLY metal_type provided. All other fields optional."""
        # 1. Missing metal_type -> Invalid
        form_empty = JewelleryItemForm(data={}, tenant=self.tenant)
        self.assertFalse(form_empty.is_valid())
        self.assertIn('metal_type', form_empty.errors)

        # 2. Only metal_type provided -> Valid!
        form_minimal = JewelleryItemForm(data={'metal_type': 'Gold'}, tenant=self.tenant)
        self.assertTrue(form_minimal.is_valid(), f"Errors: {form_minimal.errors}")

    def test_item_creation_with_only_metal_type_auto_generates_series_code(self):
        """When an item is created with only metal_type, item_code is auto-generated according to series."""
        self.settings.item_code_prefix = 'JW'
        self.settings.item_code_digits = 5
        self.settings.item_code_next_number = 1
        self.settings.save()

        # Item 1
        item1 = JewelleryItem.objects.create(
            tenant=self.tenant,
            metal_type='Gold'
        )
        self.assertEqual(item1.item_code, 'JW-00001')
        self.assertIn('Gold', item1.name)

        # Item 2
        item2 = JewelleryItem.objects.create(
            tenant=self.tenant,
            metal_type='Silver'
        )
        self.assertEqual(item2.item_code, 'JW-00002')

    def test_series_custom_prefix_and_next_number_in_settings(self):
        """Shop can configure custom prefix and starting number in CompanySettings."""
        self.settings.item_code_prefix = 'APX'
        self.settings.item_code_digits = 4
        self.settings.item_code_next_number = 500
        self.settings.save()

        item = JewelleryItem.objects.create(
            tenant=self.tenant,
            metal_type='Diamond'
        )
        self.assertEqual(item.item_code, 'APX-0500')

        item_next = JewelleryItem.objects.create(
            tenant=self.tenant,
            metal_type='Diamond'
        )
        self.assertEqual(item_next.item_code, 'APX-0501')

    def test_metal_prefix_series_mode(self):
        """Metal prefix mode generates GLD-, SLV-, DIA-, PLT- codes."""
        self.settings.item_code_series_mode = 'metal_prefix_number'
        self.settings.item_code_digits = 4
        self.settings.save()

        gold_item = JewelleryItem.objects.create(
            tenant=self.tenant,
            metal_type='Gold'
        )
        self.assertEqual(gold_item.item_code, 'GLD-0001')

        silver_item = JewelleryItem.objects.create(
            tenant=self.tenant,
            metal_type='Silver'
        )
        self.assertEqual(silver_item.item_code, 'SLV-0001')

    def test_manual_item_code_override(self):
        """If user explicitly provides an item_code, that custom code is kept."""
        item = JewelleryItem.objects.create(
            tenant=self.tenant,
            metal_type='Gold',
            item_code='CUSTOM-PIECE-99'
        )
        self.assertEqual(item.item_code, 'CUSTOM-PIECE-99')

    def test_inventory_add_view_with_only_metal_type(self):
        """POST to inventory_add with only metal_type succeeds and redirects."""
        url = reverse('inventory_add')
        resp = self.client.post(url, {
            'metal_type': 'Platinum',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        created_item = JewelleryItem.objects.filter(tenant=self.tenant, metal_type='Platinum').first()
        self.assertIsNotNone(created_item)
        self.assertTrue(created_item.item_code.startswith('JW-'))
        self.assertGreater(len(created_item.item_code), 4)

    def test_series_preview_helper(self):
        """get_next_item_code_preview accurately previews the next code."""
        self.settings.item_code_prefix = 'RN'
        self.settings.item_code_digits = 4
        self.settings.item_code_next_number = 12
        preview = self.settings.get_next_item_code_preview()
        self.assertEqual(preview, 'RN-0012')

