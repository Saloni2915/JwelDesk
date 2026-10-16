"""
inventory/test_photo_studio.py
--------------------------------
Comprehensive test suite for Phase 2: AI Jewellery Photo Studio.
Tests:
1. Authentication & permission enforcement across studio endpoints.
2. Multi-tenant isolation (Tenant B cannot generate with, save to, or download Tenant A's images/items).
3. Image input validation (unsupported formats, non-image files, corrupted data, oversized files).
4. Missing API credentials handling (graceful 503 response with setup instructions).
5. Generation with Mock Photo Studio Provider (Catalogue & Model modes).
6. Saving approved studio results to JewelleryItemImage (source_type='AI_STUDIO').
7. Secure, tenant-isolated image downloading.
8. Jewellery fidelity prompt construction.
"""

import base64
import io
import os
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import CompanySettings, Tenant
from inventory.models import Category, JewelleryItem, JewelleryItemImage
from inventory.studio.providers import (
    GeminiPhotoStudioProvider,
    MockPhotoStudioProvider,
    ProviderResult,
    get_photo_studio_provider,
)
from inventory.studio.service import (
    CATALOGUE_PRESETS,
    MODEL_PRESETS,
    image_to_data_url,
    normalize_image_for_ai,
    validate_uploaded_image,
)
from team.models import Employee, Role

User = get_user_model()


def make_test_image(format='JPEG', size=(200, 200), color=(212, 175, 55)) -> bytes:
    """Generate minimal valid image bytes in memory for tests."""
    buf = io.BytesIO()
    mode = 'RGBA' if format.upper() == 'PNG' else 'RGB'
    img = Image.new(mode, size, color=color)
    img.save(buf, format=format)
    return buf.getvalue()


class PhotoStudioBaseTestCase(TestCase):
    """Fixture establishing two completely isolated tenants (Showroom A and Showroom B)."""

    def setUp(self):
        super().setUp()
        Role.ensure_builtin_roles()
        self.admin_role = Role.objects.get(name=Role.ROLE_ADMIN)

        # -------------------------------------------------------------
        # TENANT A: "Aura Luxury Jewels"
        # -------------------------------------------------------------
        self.user_a = User.objects.create_user(
            username='aura_owner',
            email='aura@example.com',
            password='Password123!',
        )
        self.tenant_a = Tenant.objects.create(
            name='Aura Luxury Jewels',
            owner=self.user_a,
            slug='aura-jewels',
            is_active=True,
        )
        self.settings_a = CompanySettings.objects.create(
            tenant=self.tenant_a,
            company_name='Aura Luxury Jewels',
        )
        self.emp_a = Employee.objects.create(
            user=self.user_a,
            tenant=self.tenant_a,
            full_name='Aura Admin',
            email='aura@example.com',
            role=self.admin_role,
            status=Employee.STATUS_ACTIVE,
        )
        self.emp_a.apply_default_permissions()

        self.cat_a = Category.objects.create(tenant=self.tenant_a, name='Diamond Necklaces')
        self.item_a = JewelleryItem.objects.create(
            tenant=self.tenant_a,
            category=self.cat_a,
            item_code='AUR-NCK-001',
            tag_number='TAG-AUR-001',
            name='Aura Royal Diamond Choker',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('42.000'),
            selling_price=Decimal('280000.00'),
            status='Available',
            quantity=1,
        )
        # Create an existing uploaded image for item_a
        img_bytes_a = make_test_image('JPEG', color=(212, 175, 55))
        self.image_a = JewelleryItemImage(
            tenant=self.tenant_a,
            item=self.item_a,
            is_primary=True,
            caption='Original Choker Photo',
            source_type=JewelleryItemImage.SOURCE_UPLOAD,
            created_by=self.user_a,
        )
        self.image_a.image.save('aur_choker.jpg', ContentFile(img_bytes_a), save=True)

        # -------------------------------------------------------------
        # TENANT B: "Bhavani Gold Palace"
        # -------------------------------------------------------------
        self.user_b = User.objects.create_user(
            username='bhavani_owner',
            email='bhavani@example.com',
            password='Password123!',
        )
        self.tenant_b = Tenant.objects.create(
            name='Bhavani Gold Palace',
            owner=self.user_b,
            slug='bhavani-gold',
            is_active=True,
        )
        self.settings_b = CompanySettings.objects.create(
            tenant=self.tenant_b,
            company_name='Bhavani Gold Palace',
        )
        self.emp_b = Employee.objects.create(
            user=self.user_b,
            tenant=self.tenant_b,
            full_name='Bhavani Admin',
            email='bhavani@example.com',
            role=self.admin_role,
            status=Employee.STATUS_ACTIVE,
        )
        self.emp_b.apply_default_permissions()

        self.cat_b = Category.objects.create(tenant=self.tenant_b, name='Gold Bangles')
        self.item_b = JewelleryItem.objects.create(
            tenant=self.tenant_b,
            category=self.cat_b,
            item_code='BHV-BNG-001',
            tag_number='TAG-BHV-001',
            name='Bhavani Filigree Bangles',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('25.000'),
            selling_price=Decimal('150000.00'),
            status='Available',
            quantity=2,
        )


class PhotoStudioAuthenticationTests(PhotoStudioBaseTestCase):
    """Ensure all studio endpoints require authenticated session."""

    def test_unauthenticated_requests_redirect(self):
        client = Client()
        urls = [
            reverse('photo_studio'),
            reverse('photo_studio_generate'),
            reverse('photo_studio_save'),
            reverse('photo_studio_download', args=[self.image_a.pk]),
        ]
        for url in urls:
            resp = client.get(url)
            self.assertEqual(resp.status_code, 302, f"Unauthenticated GET to {url} should redirect")

    def test_authenticated_user_accesses_studio(self):
        client = Client()
        client.login(username='aura_owner', password='Password123!')
        resp = client.get(reverse('photo_studio'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'AI Jewellery Photo Studio')
        self.assertContains(resp, 'Catalogue Photo')
        self.assertContains(resp, 'Model Try-On')
        self.assertContains(resp, 'TAG-AUR-001')

    def test_item_preselection_via_query_param(self):
        client = Client()
        client.login(username='aura_owner', password='Password123!')
        url = reverse('photo_studio') + f"?item_id={self.item_a.pk}"
        resp = client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['selected_item'].pk, self.item_a.pk)


@override_settings(AI_STUDIO_MOCK=True)
class PhotoStudioMultiTenantTests(PhotoStudioBaseTestCase):
    """Enforce strict cross-tenant data isolation on generation, save, and download."""

    def setUp(self):
        super().setUp()
        self.client_b = Client()
        self.client_b.login(username='bhavani_owner', password='Password123!')

    def test_tenant_b_cannot_generate_using_tenant_a_image(self):
        """Tenant B must not be able to use Tenant A's existing JewelleryItemImage."""
        resp = self.client_b.post(
            reverse('photo_studio_generate'),
            {
                'existing_image_id': self.image_a.pk,
                'generation_type': 'catalogue',
                'preset': 'black_velvet',
            },
        )
        self.assertEqual(resp.status_code, 404)
        data = resp.json()
        self.assertFalse(data['success'])
        self.assertIn('belong to your showroom', data['error'].lower())

    def test_tenant_b_cannot_generate_using_tenant_a_item(self):
        """Tenant B must not be able to pull primary image from Tenant A's item."""
        resp = self.client_b.post(
            reverse('photo_studio_generate'),
            {
                'item_id': self.item_a.pk,
                'generation_type': 'catalogue',
                'preset': 'black_velvet',
            },
        )
        self.assertEqual(resp.status_code, 404)
        data = resp.json()
        self.assertFalse(data['success'])
        self.assertIn('belong to your showroom', data['error'].lower())

    def test_tenant_b_cannot_save_image_to_tenant_a_item(self):
        """Tenant B must not be able to attach generated photos to Tenant A's inventory item."""
        dummy_b64 = "data:image/jpeg;base64," + base64.b64encode(make_test_image('JPEG')).decode('ascii')
        resp = self.client_b.post(
            reverse('photo_studio_save'),
            {
                'item_id': self.item_a.pk,
                'image_data': dummy_b64,
                'caption': 'Malicious Injection Attempt',
            },
        )
        self.assertEqual(resp.status_code, 404)
        data = resp.json()
        self.assertFalse(data['success'])
        self.assertIn('belong to your showroom', data['error'].lower())
        # Confirm no image record was created under Tenant A's item
        self.assertEqual(self.item_a.images.count(), 1)

    def test_tenant_b_cannot_download_tenant_a_image(self):
        """Tenant B must receive 404 when attempting to download Tenant A's photo."""
        url = reverse('photo_studio_download', args=[self.image_a.pk])
        resp = self.client_b.get(url)
        self.assertEqual(resp.status_code, 404)


class PhotoStudioValidationTests(PhotoStudioBaseTestCase):
    """Test rigorous validation of uploaded image files and payloads."""

    def setUp(self):
        super().setUp()
        self.client_a = Client()
        self.client_a.login(username='aura_owner', password='Password123!')

    def test_rejects_non_image_upload(self):
        """Plain text, PDF or script files masquerading as images must be rejected."""
        fake_file = SimpleUploadedFile(
            name='shell.jpg',
            content=b'<?php echo "evil"; ?>',
            content_type='image/jpeg',
        )
        resp = self.client_a.post(
            reverse('photo_studio_generate'),
            {
                'image_file': fake_file,
                'generation_type': 'catalogue',
            },
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])
        self.assertIn('valid', data['error'].lower())

    def test_rejects_oversized_file(self):
        """Files exceeding 10MB limit must be rejected."""
        big_content = b'0' * (11 * 1024 * 1024)
        big_file = SimpleUploadedFile(
            name='oversized.jpg',
            content=big_content,
            content_type='image/jpeg',
        )
        resp = self.client_a.post(
            reverse('photo_studio_generate'),
            {
                'image_file': big_file,
                'generation_type': 'catalogue',
            },
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])
        self.assertIn('10 mb', data['error'].lower())

    def test_save_rejects_missing_item_id(self):
        dummy_b64 = "data:image/jpeg;base64," + base64.b64encode(make_test_image('JPEG')).decode('ascii')
        resp = self.client_a.post(
            reverse('photo_studio_save'),
            {'image_data': dummy_b64},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])
        self.assertIn('select a jewellery piece', data['error'].lower())

    def test_save_rejects_invalid_base64_data(self):
        resp = self.client_a.post(
            reverse('photo_studio_save'),
            {
                'item_id': self.item_a.pk,
                'image_data': 'not-valid-base64-content!@#$%',
            },
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])


class PhotoStudioProviderCredentialTests(PhotoStudioBaseTestCase):
    """Test missing or invalid provider configuration."""

    def setUp(self):
        super().setUp()
        self.client_a = Client()
        self.client_a.login(username='aura_owner', password='Password123!')

    @override_settings(AI_STUDIO_MOCK=False)
    def test_missing_gemini_key_returns_clean_503(self):
        """When GEMINI_API_KEY is not set, a clear 503 response must be returned instead of crash."""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop('GEMINI_API_KEY', None)
            os.environ.pop('AI_STUDIO_MOCK', None)
            resp = self.client_a.post(
                reverse('photo_studio_generate'),
                {
                    'existing_image_id': self.image_a.pk,
                    'generation_type': 'catalogue',
                    'preset': 'black_velvet',
                },
            )
            self.assertEqual(resp.status_code, 503)
            data = resp.json()
            self.assertFalse(data['success'])
            self.assertIn('gemini_api_key', data['error'].lower())


@override_settings(AI_STUDIO_MOCK=True)
class PhotoStudioMockGenerationTests(PhotoStudioBaseTestCase):
    """Test end-to-end studio workflow using deterministic MockPhotoStudioProvider."""

    def setUp(self):
        super().setUp()
        self.client_a = Client()
        self.client_a.login(username='aura_owner', password='Password123!')

    def test_generate_catalogue_photo_from_existing_image(self):
        resp = self.client_a.post(
            reverse('photo_studio_generate'),
            {
                'existing_image_id': self.image_a.pk,
                'generation_type': 'catalogue',
                'preset': 'black_velvet',
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['generation_type'], 'catalogue')
        self.assertEqual(data['preset'], 'black_velvet')
        self.assertTrue(data['preview_data_url'].startswith('data:image/webp;base64,'))
        self.assertIn('Studio Catalogue', data['caption'])

    def test_generate_model_photo_from_uploaded_file(self):
        test_file = SimpleUploadedFile(
            name='earrings.png',
            content=make_test_image('PNG', size=(300, 300)),
            content_type='image/png',
        )
        resp = self.client_a.post(
            reverse('photo_studio_generate'),
            {
                'image_file': test_file,
                'generation_type': 'model',
                'preset': 'indian_bridal',
                'custom_prompt': 'Side profile focus on the gold finish',
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['generation_type'], 'model')
        self.assertEqual(data['preset'], 'indian_bridal')
        self.assertTrue(data['preview_data_url'].startswith('data:image/webp;base64,'))
        self.assertIn('Model Wearing', data['caption'])

    def test_save_generated_photo_to_item(self):
        """Verify saving creates a JewelleryItemImage with source_type='AI_STUDIO'."""
        img_bytes = make_test_image('JPEG', size=(400, 400))
        b64_str = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode('ascii')

        resp = self.client_a.post(
            reverse('photo_studio_save'),
            {
                'item_id': self.item_a.pk,
                'image_data': b64_str,
                'caption': 'AI Luxury Catalogue Presentation',
                'is_primary': 'true',
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        new_image_id = data['image_id']

        # Verify created record
        saved_img = JewelleryItemImage.objects.get(pk=new_image_id)
        self.assertEqual(saved_img.tenant, self.tenant_a)
        self.assertEqual(saved_img.item, self.item_a)
        self.assertEqual(saved_img.source_type, JewelleryItemImage.SOURCE_AI_STUDIO)
        self.assertEqual(saved_img.caption, 'AI Luxury Catalogue Presentation')
        self.assertTrue(saved_img.is_primary)

        # Since is_primary was true, item's primary_image should now point to this new image
        self.assertEqual(self.item_a.primary_image.pk, saved_img.pk)

    def test_download_saved_studio_image(self):
        """Verify tenant can securely download their saved studio photo."""
        img_bytes = make_test_image('JPEG', size=(400, 400))
        saved_img = JewelleryItemImage(
            tenant=self.tenant_a,
            item=self.item_a,
            caption='Downloadable Studio Photo',
            source_type=JewelleryItemImage.SOURCE_AI_STUDIO,
            created_by=self.user_a,
        )
        saved_img.image.save('test_download.jpg', ContentFile(img_bytes), save=True)

        url = reverse('photo_studio_download', args=[saved_img.pk])
        resp = self.client_a.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/jpeg')
        self.assertIn('attachment', resp['Content-Disposition'])


class PhotoStudioPromptAndServiceTests(TestCase):
    """Test prompt construction and service helper behaviors."""

    def test_catalogue_prompt_contains_jewellery_fidelity_rules(self):
        provider = GeminiPhotoStudioProvider(api_key='fake-key')
        prompt = provider._build_catalogue_prompt(
            preset_name='Midnight Black Velvet',
            preset_description='Deep midnight black velvet pedestal with warm directional spotlight',
            custom_prompt='Make reflections soft',
        )
        # Check strict fidelity instructions
        self.assertIn('PRESERVE EXACT METAL COLOR', prompt.upper())
        self.assertIn('DO NOT REDESIGN', prompt.upper())
        self.assertIn('DEEP MIDNIGHT BLACK VELVET', prompt.upper())
        self.assertIn('Make reflections soft', prompt)

    def test_model_prompt_contains_jewellery_fidelity_rules(self):
        provider = GeminiPhotoStudioProvider(api_key='fake-key')
        prompt = provider._build_model_prompt(
            preset_name='Indian Royal Bridal',
            preset_description='Graceful Indian bride in maroon lehenga wearing the jewellery',
            custom_prompt='Close-up necklace shot',
        )
        self.assertIn('WEARING THE EXACT PIECE', prompt.upper())
        self.assertIn('WITHOUT REDESIGNING', prompt.upper())
        self.assertIn('Indian bride in maroon lehenga', prompt)

    def test_normalize_image_downscales_large_image(self):
        large_bytes = make_test_image('JPEG', size=(2500, 2000))
        norm_bytes, norm_mime = normalize_image_for_ai(large_bytes)
        with Image.open(io.BytesIO(norm_bytes)) as img:
            self.assertLessEqual(max(img.size), 1536)
        self.assertEqual(norm_mime, 'image/webp')

    def test_image_to_data_url(self):
        raw = b'test-bytes'
        url = image_to_data_url(raw, 'image/jpeg')
        self.assertTrue(url.startswith('data:image/jpeg;base64,'))
