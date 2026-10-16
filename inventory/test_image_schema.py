import os
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage, FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from accounts.models import Tenant
from inventory.models import (
    Category,
    JewelleryItem,
    JewelleryItemImage,
    item_image_upload_path,
    validate_jewellery_image_extension,
)

User = get_user_model()


class JewelleryItemImageSchemaTests(TestCase):
    """Unit tests for JewelleryItemImage schema, tenant isolation, and primary image logic."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='jeweller_test',
            email='jeweller@test.com',
            password='TestPassword123!',
        )
        self.tenant_a = Tenant.objects.create(name='Showroom A', owner=self.user)
        self.tenant_b = Tenant.objects.create(name='Showroom B', owner=self.user)

        self.category = Category.objects.create(
            tenant=self.tenant_a,
            name='Necklaces',
        )
        self.item = JewelleryItem.objects.create(
            tenant=self.tenant_a,
            tag_number='JWL-990001',
            item_code='NECK-001',
            name='Royal Emerald Choker',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('45.000'),
            selling_price=Decimal('350000.00'),
        )

    def test_create_image_and_link_to_jewellery_item(self):
        """Image records can be created, linked to item, and inherit tenant ownership."""
        sample_file = SimpleUploadedFile(
            name='choker_front.webp',
            content=b'fake-webp-image-data-bytes',
            content_type='image/webp',
        )
        image_obj = JewelleryItemImage.objects.create(
            item=self.item,
            image=sample_file,
            caption='Frontal Studio View',
            source_type=JewelleryItemImage.SOURCE_UPLOAD,
            created_by=self.user,
        )

        self.assertEqual(image_obj.tenant, self.tenant_a)
        self.assertEqual(self.item.images.count(), 1)
        self.assertEqual(self.item.images.first().pk, image_obj.pk)
        self.assertIn('Frontal Studio View', str(image_obj))

    def test_primary_image_property(self):
        """JewelleryItem.primary_image resolves the marked primary image or first available."""
        self.assertIsNone(self.item.primary_image)

        file1 = SimpleUploadedFile('side.jpg', b'data-side', content_type='image/jpeg')
        file2 = SimpleUploadedFile('front.jpg', b'data-front', content_type='image/jpeg')

        img1 = JewelleryItemImage.objects.create(
            item=self.item, image=file1, is_primary=False, caption='Side View'
        )
        img2 = JewelleryItemImage.objects.create(
            item=self.item, image=file2, is_primary=True, caption='Front View'
        )

        # Primary is img2
        self.assertEqual(self.item.primary_image.pk, img2.pk)
        self.assertEqual(self.item.primary_image.caption, 'Front View')

    def test_single_primary_image_enforcement(self):
        """Designating a new image as primary unsets previous primary images for that piece."""
        file1 = SimpleUploadedFile('img1.png', b'data1', content_type='image/png')
        file2 = SimpleUploadedFile('img2.png', b'data2', content_type='image/png')

        img1 = JewelleryItemImage.objects.create(
            item=self.item, image=file1, is_primary=True, caption='First Primary'
        )
        self.assertTrue(img1.is_primary)

        img2 = JewelleryItemImage.objects.create(
            item=self.item, image=file2, is_primary=True, caption='Second Primary'
        )
        self.assertTrue(img2.is_primary)

        # Refresh img1 from database
        img1.refresh_from_db()
        self.assertFalse(img1.is_primary)
        self.assertEqual(self.item.primary_image.pk, img2.pk)

    def test_tenant_cross_contamination_prevented(self):
        """Attempting to assign an item from Tenant A to Tenant B raises ValidationError."""
        file_sample = SimpleUploadedFile('hack.jpg', b'data', content_type='image/jpeg')
        cross_tenant_image = JewelleryItemImage(
            tenant=self.tenant_b,  # Tenant B
            item=self.item,        # Belongs to Tenant A
            image=file_sample,
        )
        with self.assertRaises(ValidationError) as ctx:
            cross_tenant_image.clean()

        self.assertIn('item', ctx.exception.message_dict)

    def test_allowed_image_extensions(self):
        """Only JPEG, PNG, and WEBP formats are accepted."""
        for valid_ext in ['test.jpg', 'test.jpeg', 'test.png', 'test.webp']:
            f = SimpleUploadedFile(valid_ext, b'valid', content_type='image/jpeg')
            try:
                validate_jewellery_image_extension(f)
            except ValidationError:
                self.fail(f"validate_jewellery_image_extension unexpectedly failed for {valid_ext}")

        for invalid_ext in ['test.exe', 'test.pdf', 'test.txt', 'test.svg', 'test.gif']:
            f = SimpleUploadedFile(invalid_ext, b'invalid', content_type='application/octet-stream')
            with self.assertRaises(ValidationError):
                validate_jewellery_image_extension(f)

    def test_item_image_upload_path_structure(self):
        """Upload path is tenant-isolated and sanitized."""
        image_obj = JewelleryItemImage(item=self.item, tenant=self.tenant_a)
        path = item_image_upload_path(image_obj, 'my exquisite choker! @#$.png')

        self.assertTrue(path.startswith(f"inventory/items/tenant_{self.tenant_a.id}/"))
        self.assertTrue(path.endswith('.png'))
        self.assertNotIn('@', path)
        self.assertNotIn('#', path)
        self.assertNotIn('!', path)


class StorageConfigurationTests(TestCase):
    """Tests verifying storage isolation between test/development and production."""

    def test_test_environment_uses_filesystem_storage(self):
        """Automated test execution always runs against local FileSystemStorage."""
        self.assertIsInstance(default_storage, FileSystemStorage)

    def test_storage_settings_structure(self):
        """Settings define default and staticfiles storage backends cleanly."""
        self.assertIn('default', settings.STORAGES)
        self.assertIn('staticfiles', settings.STORAGES)
        self.assertIn('BACKEND', settings.STORAGES['default'])

    def test_use_supabase_s3_flag_exposed(self):
        """settings.USE_SUPABASE_S3 is cleanly exposed and False during tests."""
        self.assertFalse(getattr(settings, 'USE_SUPABASE_S3', True))
