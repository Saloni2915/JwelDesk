import csv
import io
from decimal import Decimal
from unittest.mock import patch

import openpyxl
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.urls import reverse
from django.utils.html import escape
from inventory import import_utils
from inventory.models import Category, JewelleryItem
from customers.models import Customer
from sales.models import Sale, Enquiry


class InventoryModelTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Rings', description='Gold & Diamond Rings')

    def test_item_net_weight_cannot_exceed_gross_weight(self):
        item = JewelleryItem(
            item_code='ERR-001',
            name='Invalid Weight Item',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            net_weight=Decimal('6.500'),  # Greater than gross weight
            selling_price=Decimal('50000.00'),
        )
        with self.assertRaises(ValidationError):
            item.clean()

    def test_valid_item_creation(self):
        item = JewelleryItem.objects.create(
            item_code='GLD-001',
            design_code='DSN-001',
            name='22K Ring',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('6.000'),
            net_weight=Decimal('5.800'),
            selling_price=Decimal('50000.00'),
        )
        self.assertEqual(item.status, 'Available')
        self.assertEqual(item.design_code, 'DSN-001')
        self.assertIn('DSN-001', str(item))

    def test_multiple_pieces_same_design_code(self):
        piece1 = JewelleryItem.objects.create(
            item_code='DSN-01-P1',
            design_code='DSN-01',
            name='Solitaire Ring Piece 1',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.200'),
            net_weight=Decimal('5.000'),
            selling_price=Decimal('48000.00'),
            status='Available'
        )
        piece2 = JewelleryItem.objects.create(
            item_code='DSN-01-P2',
            design_code='DSN-01',
            name='Solitaire Ring Piece 2',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.500'),
            net_weight=Decimal('5.300'),
            selling_price=Decimal('49500.00'),
            status='Available'
        )
        self.assertEqual(piece1.design_code, piece2.design_code)
        self.assertNotEqual(piece1.item_code, piece2.item_code)
        self.assertNotEqual(piece1.selling_price, piece2.selling_price)
        self.assertEqual(JewelleryItem.objects.filter(design_code='DSN-01').count(), 2)


class InventoryViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='staff', password='Password123')
        self.client.login(username='staff', password='Password123')

        self.category = Category.objects.create(name='Necklaces', description='Gold Necklaces')
        self.item = JewelleryItem.objects.create(
            item_code='NK-001',
            name='Temple Gold Necklace',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('30.000'),
            net_weight=Decimal('28.500'),
            making_charge=Decimal('10000.00'),
            selling_price=Decimal('250000.00'),
            status='Available'
        )

    def test_dashboard_view(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'inventory/dashboard.html')
        self.assertEqual(response.context['total_items'], 1)
        self.assertEqual(response.context['available_items'], 1)

    def test_inventory_list_view_and_search(self):
        response = self.client.get(reverse('inventory_list'), {'q': 'Temple'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Temple Gold Necklace')

        # Negative search
        response_neg = self.client.get(reverse('inventory_list'), {'q': 'NonExistent'})
        self.assertNotContains(response_neg, 'Temple Gold Necklace')

    def test_inventory_add_valid(self):
        response = self.client.post(reverse('inventory_add'), {
            'item_code': 'RN-NEW-01',
            'name': 'New Gold Ring',
            'category': self.category.id,
            'metal_type': 'Gold',
            'purity': '22K',
            'gross_weight': '4.500',
            'net_weight': '4.200',
            'making_charge': '1500.00',
            'selling_price': '35000.00',
            'status': 'Available',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(JewelleryItem.objects.filter(item_code='RN-NEW-01').exists())

    def test_inventory_detail_view(self):
        # Create a second piece of same design
        JewelleryItem.objects.create(
            item_code='NK-001-B',
            design_code=self.item.design_code,
            name='Temple Gold Necklace (Piece 2)',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('31.000'),
            net_weight=Decimal('29.000'),
            making_charge=Decimal('10000.00'),
            selling_price=Decimal('255000.00'),
            status='Available'
        )
        response = self.client.get(reverse('inventory_detail', kwargs={'pk': self.item.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Temple Gold Necklace')
        self.assertContains(response, 'NK-001')
        self.assertContains(response, 'NK-001-B')
        self.assertEqual(len(response.context['other_pieces']), 1)

    def test_inventory_add_with_duplicate_from_prefill(self):
        response = self.client.get(reverse('inventory_add'), {'duplicate_from': self.item.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].initial['design_code'], self.item.design_code)
        self.assertEqual(response.context['form'].initial['name'], self.item.name)

    def test_inventory_edit_view(self):
        response = self.client.post(reverse('inventory_edit', kwargs={'pk': self.item.pk}), {
            'item_code': 'NK-001',
            'name': 'Updated Temple Gold Necklace',
            'category': self.category.id,
            'metal_type': 'Gold',
            'purity': '22K',
            'gross_weight': '30.000',
            'net_weight': '28.500',
            'making_charge': '12000.00',
            'selling_price': '260000.00',
            'status': 'Available',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, 'Updated Temple Gold Necklace')
        self.assertEqual(self.item.selling_price, Decimal('260000.00'))

    def test_inventory_delete_view(self):
        response = self.client.post(reverse('inventory_delete', kwargs={'pk': self.item.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JewelleryItem.objects.filter(pk=self.item.pk).exists())


class CategoryViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='admin_staff', password='Password123')
        self.client.login(username='admin_staff', password='Password123')
        self.category = Category.objects.create(name='Bangles', description='Traditional bangles')

    def test_category_list_view(self):
        response = self.client.get(reverse('category_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bangles')

    def test_category_add_view(self):
        response = self.client.post(reverse('category_add'), {
            'name': 'Chains',
            'description': 'Gold chains',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Category.objects.filter(name='Chains').exists())

    def test_category_edit_view(self):
        response = self.client.post(reverse('category_edit', kwargs={'pk': self.category.pk}), {
            'name': 'Gold Bangles & Kadas',
            'description': 'Updated description',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, 'Gold Bangles & Kadas')

    def test_category_delete_protection_when_items_exist(self):
        # Create an item in this category
        JewelleryItem.objects.create(
            item_code='BG-001',
            name='Gold Kada',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('20.000'),
            net_weight=Decimal('20.000'),
            selling_price=Decimal('150000.00'),
        )
        # Attempt to delete category
        response = self.client.post(reverse('category_delete', kwargs={'pk': self.category.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())
        self.assertContains(response, 'Cannot delete category')

    def test_category_delete_success_when_empty(self):
        empty_cat = Category.objects.create(name='Empty Cat')
        response = self.client.post(reverse('category_delete', kwargs={'pk': empty_cat.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Category.objects.filter(pk=empty_cat.pk).exists())


# ==============================================================================
# BULK IMPORT TESTS
# ==============================================================================

IMPORT_HEADERS = [
    'item_code', 'design_code', 'name', 'category', 'metal_type',
    'purity', 'gross_weight', 'net_weight', 'making_charge', 'selling_price', 'status',
]


def valid_import_row(item_code='IMP-RN-001', design_code='DSN-IMP-001', name='Imported Gold Ring',
                     category='Bulk Import Rings', metal_type='Gold', purity='22K (916)',
                     gross_weight='5.500', net_weight='5.200', making_charge='2500.00',
                     selling_price='48500.00', status='Available'):
    """Return one data row (list of cell values) for the bulk import tests."""
    return [
        item_code, design_code, name, category, metal_type,
        purity, gross_weight, net_weight, making_charge, selling_price, status,
    ]


def build_import_csv(rows):
    """Return CSV file bytes with the bulk import headers and the given data rows."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(IMPORT_HEADERS)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode('utf-8')


def build_import_xlsx(rows):
    """Return .xlsx file bytes with the bulk import headers and the given data rows."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(IMPORT_HEADERS)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class BulkImportViewTests(TestCase):
    """Tests for the CSV / Excel bulk inventory import screens and workflow."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='importstaff', password='Password123')
        self.client.login(username='importstaff', password='Password123')

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------
    def upload_csv(self, rows, filename='stock.csv'):
        """Upload a CSV file to the bulk import screen."""
        return self.client.post(reverse('inventory_import'), {
            'action': 'upload',
            'import_file': SimpleUploadedFile(filename, build_import_csv(rows), content_type='text/csv'),
        })

    def upload_xlsx(self, rows, filename='stock.xlsx'):
        """Upload an Excel file to the bulk import screen."""
        return self.client.post(reverse('inventory_import'), {
            'action': 'upload',
            'import_file': SimpleUploadedFile(
                filename,
                build_import_xlsx(rows),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            ),
        })

    def preview_page(self, **params):
        """Render the validation preview for the file that was uploaded last."""
        return self.client.get(reverse('inventory_import'), params)

    def post_confirm(self):
        """Post the confirmation step of the import."""
        return self.client.post(reverse('inventory_import'), {'action': 'confirm'})

    # ---------------------------------------------------------
    # ACCESS CONTROL
    # ---------------------------------------------------------
    def test_import_pages_require_login(self):
        self.client.logout()

        for url_name in ['inventory_import', 'inventory_import_sample']:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse('accounts:login'), response.url)

        post_response = self.client.post(reverse('inventory_import'), {'action': 'confirm'})
        self.assertEqual(post_response.status_code, 302)
        self.assertIn(reverse('accounts:login'), post_response.url)

    def test_upload_page_renders_upload_form(self):
        response = self.client.get(reverse('inventory_import'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'inventory/import.html')
        self.assertContains(response, 'Upload Jewellery Stock File')
        self.assertContains(response, reverse('inventory_import_sample'))

    # ---------------------------------------------------------
    # CSV AND EXCEL UPLOAD / PREVIEW
    # ---------------------------------------------------------
    def test_csv_upload_previews_valid_rows_without_importing(self):
        response = self.upload_csv([
            valid_import_row(item_code='IMP-RN-001', design_code='DSN-IMP-001'),
            valid_import_row(item_code='IMP-RN-002', design_code='DSN-IMP-002', category='Bulk Import Chains'),
        ])
        self.assertRedirects(response, reverse('inventory_import'))

        preview = self.preview_page()
        self.assertTemplateUsed(preview, 'inventory/import_preview.html')
        self.assertEqual(preview.context['summary']['total_rows'], 2)
        self.assertEqual(preview.context['summary']['valid_count'], 2)
        self.assertEqual(preview.context['summary']['invalid_count'], 0)
        self.assertTrue(preview.context['can_import'])
        self.assertContains(preview, 'IMP-RN-001')

        # Nothing may be written to the inventory before the import is confirmed
        self.assertEqual(JewelleryItem.objects.count(), 0)
        self.assertEqual(Category.objects.count(), 0)

    def test_excel_upload_previews_valid_rows(self):
        response = self.upload_xlsx([valid_import_row(item_code='IMP-XL-001')])
        self.assertRedirects(response, reverse('inventory_import'))

        preview = self.preview_page()
        self.assertEqual(preview.context['summary']['valid_count'], 1)
        self.assertTrue(preview.context['can_import'])
        self.assertContains(preview, 'IMP-XL-001')
        self.assertEqual(JewelleryItem.objects.count(), 0)

    def test_valid_rows_preview_is_paginated(self):
        rows = [
            valid_import_row(item_code=f'IMP-PG-{index:03d}', design_code=f'DSN-PG-{index:03d}')
            for index in range(1, 31)
        ]
        self.upload_csv(rows)

        first_page = self.preview_page()
        self.assertEqual(len(first_page.context['valid_rows']), 25)
        self.assertContains(first_page, 'Showing 1 to 25 of 30 entries')

        second_page = self.preview_page(page=2)
        self.assertEqual(len(second_page.context['valid_rows']), 5)

    # ---------------------------------------------------------
    # INVALID ROWS AND FILE PROBLEMS
    # ---------------------------------------------------------
    def test_invalid_rows_are_reported_and_block_the_import(self):
        self.upload_csv([
            valid_import_row(item_code='IMP-OK-001'),
            valid_import_row(
                item_code='IMP-BAD-001', name='Broken Row', metal_type='Brass',
                gross_weight='4.000', net_weight='5.000', selling_price='',
            ),
        ])

        preview = self.preview_page()
        self.assertEqual(preview.context['summary']['valid_count'], 1)
        self.assertEqual(preview.context['summary']['invalid_count'], 1)
        self.assertFalse(preview.context['can_import'])

        # The individual validation errors are shown on the preview
        self.assertContains(preview, 'Net weight (5.000g) cannot exceed gross weight (4.000g).')
        self.assertContains(preview, escape("Invalid metal type 'Brass'."))
        self.assertContains(preview, 'Selling price is required.')

        # Confirming must not insert a single record
        confirm = self.post_confirm()
        self.assertRedirects(confirm, reverse('inventory_import'), fetch_redirect_response=False)
        self.assertEqual(JewelleryItem.objects.count(), 0)
        self.assertEqual(Category.objects.count(), 0)

        message_page = self.preview_page()
        self.assertContains(message_page, 'Nothing was imported')

    def test_unsupported_file_type_is_rejected(self):
        response = self.client.post(reverse('inventory_import'), {
            'action': 'upload',
            'import_file': SimpleUploadedFile('stock.txt', b'item_code,name\n', content_type='text/plain'),
        })
        self.assertRedirects(response, reverse('inventory_import'), fetch_redirect_response=False)

        page = self.preview_page()
        self.assertTemplateUsed(page, 'inventory/import.html')
        self.assertContains(page, 'Unsupported file type')
        self.assertEqual(JewelleryItem.objects.count(), 0)

    def test_file_without_data_rows_is_reported(self):
        self.upload_csv([])

        page = self.preview_page()
        self.assertTemplateUsed(page, 'inventory/import.html')
        self.assertContains(page, 'No data rows were found')

    def test_corrupt_excel_file_is_reported_without_crashing(self):
        response = self.client.post(reverse('inventory_import'), {
            'action': 'upload',
            'import_file': SimpleUploadedFile(
                'broken.xlsx',
                b'this is not a real workbook',
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            ),
        })
        self.assertRedirects(response, reverse('inventory_import'), fetch_redirect_response=False)

        page = self.preview_page()
        self.assertTemplateUsed(page, 'inventory/import.html')
        self.assertContains(page, 'Could not read')

    # ---------------------------------------------------------
    # DUPLICATE PIECE IDS AND DESIGN CODES
    # ---------------------------------------------------------
    def test_duplicate_item_code_inside_file_is_reported(self):
        self.upload_csv([
            valid_import_row(item_code='IMP-DUP-001', design_code='DSN-DUP-001'),
            valid_import_row(item_code='IMP-DUP-001', design_code='DSN-DUP-002', name='Second Piece'),
        ])

        preview = self.preview_page()
        self.assertEqual(preview.context['summary']['valid_count'], 1)
        self.assertEqual(preview.context['summary']['invalid_count'], 1)
        self.assertEqual(preview.context['duplicate_count'], 1)
        self.assertFalse(preview.context['can_import'])
        self.assertContains(preview, escape("Duplicate Piece ID 'IMP-DUP-001' found within uploaded file."))

        self.post_confirm()
        self.assertEqual(JewelleryItem.objects.count(), 0)

    def test_duplicate_item_code_already_in_database_is_reported(self):
        category = Category.objects.create(name='Existing Rings')
        existing_item = JewelleryItem.objects.create(
            item_code='IMP-EXIST-001',
            name='Already Stocked Ring',
            category=category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            net_weight=Decimal('4.800'),
            selling_price=Decimal('45000.00'),
        )

        self.upload_csv([valid_import_row(item_code='IMP-EXIST-001')])

        preview = self.preview_page()
        self.assertEqual(preview.context['summary']['invalid_count'], 1)
        self.assertEqual(preview.context['duplicate_count'], 1)
        self.assertEqual(preview.context['duplicate_rows'][0]['row_num'], 2)
        self.assertContains(preview, escape("Piece ID 'IMP-EXIST-001' already exists in database."))

        # Confirming leaves the existing record untouched and creates nothing new
        self.post_confirm()
        self.assertEqual(JewelleryItem.objects.count(), 1)
        existing_item.refresh_from_db()
        self.assertEqual(existing_item.name, 'Already Stocked Ring')

    def test_repeated_design_code_with_unique_piece_ids_is_allowed(self):
        self.upload_csv([
            valid_import_row(item_code='IMP-DSN-001-A', design_code='DSN-MULTI-001'),
            valid_import_row(item_code='IMP-DSN-001-B', design_code='DSN-MULTI-001'),
        ])

        preview = self.preview_page()
        self.assertEqual(preview.context['summary']['valid_count'], 2)
        self.assertEqual(preview.context['summary']['invalid_count'], 0)
        self.assertEqual(preview.context['duplicate_count'], 0)
        self.assertTrue(preview.context['can_import'])

        self.post_confirm()
        self.assertEqual(JewelleryItem.objects.filter(design_code='DSN-MULTI-001').count(), 2)

    # ---------------------------------------------------------
    # SUCCESSFUL IMPORT
    # ---------------------------------------------------------
    def test_successful_import_creates_items_and_reports_the_count(self):
        self.upload_csv([
            valid_import_row(item_code='IMP-RN-001', category='Imported Rings'),
            valid_import_row(
                item_code='IMP-CH-002', design_code='DSN-IMP-002', name='Sterling Silver Chain',
                category='Imported Chains', metal_type='silver', purity='925 Silver',
                gross_weight='12.000', net_weight='12.000', making_charge='', status='reserved',
            ),
        ], filename='march-stock.csv')

        response = self.post_confirm()
        self.assertRedirects(response, reverse('inventory_list'), fetch_redirect_response=False)

        # Both pieces (and both categories) were created
        self.assertEqual(JewelleryItem.objects.count(), 2)
        self.assertTrue(Category.objects.filter(name='Imported Rings').exists())
        self.assertTrue(Category.objects.filter(name='Imported Chains').exists())

        # Lower-case metal/status values are normalised and blank charges default to 0
        imported = JewelleryItem.objects.get(item_code='IMP-CH-002')
        self.assertEqual(imported.metal_type, 'Silver')
        self.assertEqual(imported.status, 'Reserved')
        self.assertEqual(imported.design_code, 'DSN-IMP-002')
        self.assertEqual(imported.making_charge, Decimal('0.00'))
        self.assertEqual(imported.category.name, 'Imported Chains')

        # The count is reported and the pieces are visible in the inventory list
        inventory_page = self.client.get(reverse('inventory_list'))
        self.assertContains(inventory_page, '2 jewellery item(s)')
        self.assertContains(inventory_page, 'IMP-RN-001')
        self.assertContains(inventory_page, 'IMP-CH-002')

    def test_uploaded_file_is_forgotten_after_a_successful_import(self):
        self.upload_csv([valid_import_row(item_code='IMP-ONCE-001')])
        self.post_confirm()

        # A second confirmation must not import the same file again
        self.post_confirm()
        self.assertEqual(JewelleryItem.objects.count(), 1)

        page = self.preview_page()
        self.assertTemplateUsed(page, 'inventory/import.html')
        self.assertContains(page, 'There is no validated file to import')

    def test_cancel_discards_the_uploaded_file(self):
        self.upload_csv([valid_import_row(item_code='IMP-CANCEL-001')])

        response = self.client.post(reverse('inventory_import'), {'action': 'cancel'})
        self.assertRedirects(response, reverse('inventory_import'), fetch_redirect_response=False)
        self.assertEqual(JewelleryItem.objects.count(), 0)

        page = self.preview_page()
        self.assertTemplateUsed(page, 'inventory/import.html')
        self.assertContains(page, 'Bulk import cancelled')

    def test_confirm_without_an_uploaded_file_is_rejected(self):
        response = self.post_confirm()
        self.assertRedirects(response, reverse('inventory_import'), fetch_redirect_response=False)
        self.assertEqual(JewelleryItem.objects.count(), 0)

        page = self.preview_page()
        self.assertContains(page, 'There is no validated file to import')

    # ---------------------------------------------------------
    # ROLLBACK SAFETY
    # ---------------------------------------------------------
    def test_import_is_blocked_when_a_row_becomes_a_duplicate_after_the_preview(self):
        self.upload_csv([
            valid_import_row(item_code='IMP-RACE-001', design_code='DSN-RACE-001'),
            valid_import_row(item_code='IMP-RACE-002', design_code='DSN-RACE-002'),
        ])

        # Another user adds one of the pieces after the preview was validated
        category = Category.objects.create(name='Raced Rings')
        JewelleryItem.objects.create(
            item_code='IMP-RACE-001',
            name='Piece added meanwhile',
            category=category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            net_weight=Decimal('4.900'),
            selling_price=Decimal('47000.00'),
        )

        response = self.post_confirm()
        self.assertRedirects(response, reverse('inventory_import'), fetch_redirect_response=False)

        # Not even the still-valid second row may be imported
        self.assertFalse(JewelleryItem.objects.filter(item_code='IMP-RACE-002').exists())
        self.assertEqual(JewelleryItem.objects.count(), 1)

        page = self.preview_page()
        self.assertContains(page, 'Nothing was imported')

    def test_import_rolls_back_atomically_when_a_database_error_occurs(self):
        self.upload_csv([
            valid_import_row(item_code='IMP-TX-001', category='Transaction Rings'),
            valid_import_row(item_code='IMP-TX-002', design_code='DSN-TX-002', category='Transaction Rings'),
        ])

        original_create = import_utils.create_jewellery_item_from_row
        calls = {'count': 0}

        def flaky_create(row, category):
            calls['count'] += 1
            if calls['count'] == 2:
                raise IntegrityError('simulated database failure')
            return original_create(row, category)

        with patch.object(import_utils, 'create_jewellery_item_from_row', side_effect=flaky_create):
            response = self.post_confirm()

        self.assertRedirects(response, reverse('inventory_import'), fetch_redirect_response=False)
        self.assertEqual(calls['count'], 2)

        # The first insert was rolled back and the auto-created category is gone too
        self.assertEqual(JewelleryItem.objects.count(), 0)
        self.assertFalse(Category.objects.filter(name='Transaction Rings').exists())

        page = self.preview_page()
        self.assertContains(page, 'was rolled back')

    # ---------------------------------------------------------
    # SAMPLE CSV TEMPLATE
    # ---------------------------------------------------------
    def test_sample_csv_download_returns_attachment_template(self):
        response = self.client.get(reverse('inventory_import_sample'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn(
            'attachment; filename="jeweldesk_inventory_import_sample.csv"',
            response['Content-Disposition'],
        )

        content = response.content.decode('utf-8')
        lines = [line for line in content.strip().splitlines() if line]
        self.assertTrue(lines[0].startswith('item_code,design_code,name,category,metal_type'))
        self.assertEqual(len(lines), 7)  # heading row + 6 sample pieces

    def test_downloaded_sample_csv_validates_and_imports(self):
        sample_csv = self.client.get(reverse('inventory_import_sample')).content

        upload = self.client.post(reverse('inventory_import'), {
            'action': 'upload',
            'import_file': SimpleUploadedFile('sample.csv', sample_csv, content_type='text/csv'),
        })
        self.assertRedirects(upload, reverse('inventory_import'), fetch_redirect_response=False)

        preview = self.preview_page()
        self.assertEqual(preview.context['summary']['valid_count'], 6)
        self.assertEqual(preview.context['summary']['invalid_count'], 0)
        self.assertTrue(preview.context['can_import'])

        self.post_confirm()
        self.assertEqual(JewelleryItem.objects.count(), 6)
        # Rings, Earrings, Necklaces, Coins & Bars and Anklets
        self.assertEqual(Category.objects.count(), 5)
        self.assertEqual(JewelleryItem.objects.filter(design_code='DSN-RN-101').count(), 2)


# ==== Metal price (dashboard) tests =========================================

import json
import socket
import urllib.error

from django.core.cache import cache
from django.test import override_settings

from inventory import metal_prices

METAL_PRICE_TEST_SETTINGS = override_settings(
    METAL_PRICE_API_URL=(
        'https://api.example.test/latest?api_key={api_key}&base=INR'
        '&currencies=XAU,XAG'),
    METAL_PRICE_API_KEY='test-key-123',
    METAL_PRICE_API_KEY_HEADER='x-access-token',
    METAL_PRICE_API_TIMEOUT=5,
    METAL_PRICE_CACHE_TTL=1800,
)

URLOPEN_TARGET = 'inventory.metal_prices.urllib.request.urlopen'


class _FakeResponse:
    """Minimal urlopen() stand-in returning a fixed body."""

    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _clear_price_cache():
    cache.delete(metal_prices.SNAPSHOT_CACHE_KEY)
    cache.delete(metal_prices.LAST_GOOD_CACHE_KEY)


@METAL_PRICE_TEST_SETTINGS
class MetalPriceServiceTests(TestCase):
    """Unit tests for the metal price service (success/failure/config)."""

    def setUp(self):
        _clear_price_cache()

    def tearDown(self):
        _clear_price_cache()

    def test_successful_refresh_direct_per_ounce_rates(self):
        payload = {'rates': {'XAU': 343000.0, 'XAG': 4000.0}}
        with patch(URLOPEN_TARGET, return_value=_FakeResponse(payload)) as mock_urlopen:
            result = metal_prices.refresh_prices()
        self.assertTrue(result['ok'], result['message'])
        snapshot = result['snapshot']
        self.assertTrue(snapshot['available'])
        self.assertTrue(snapshot['configured'])
        self.assertIsNotNone(snapshot['last_updated'])
        self.assertEqual(snapshot['age_minutes'], 0)
        self.assertAlmostEqual(
            snapshot['gold_price_per_gram'],
            343000.0 / metal_prices.GRAMS_PER_TROY_OUNCE, places=2)
        self.assertAlmostEqual(
            snapshot['silver_price_per_gram'],
            4000.0 / metal_prices.GRAMS_PER_TROY_OUNCE, places=2)
        # Key substituted into the {api_key} placeholder and sent as header.
        request = mock_urlopen.call_args[0][0]
        self.assertIn('test-key-123', request.full_url)
        self.assertEqual(request.get_header('X-access-token'), 'test-key-123')

    def test_successful_refresh_inverse_rates(self):
        payload = {'rates': {'XAU': 0.00000292, 'XAG': 0.00025}}
        with patch(URLOPEN_TARGET, return_value=_FakeResponse(payload)):
            result = metal_prices.refresh_prices()
        self.assertTrue(result['ok'], result['message'])
        self.assertAlmostEqual(
            result['snapshot']['gold_price_per_gram'],
            (1 / 0.00000292) / metal_prices.GRAMS_PER_TROY_OUNCE, places=2)
        self.assertAlmostEqual(
            result['snapshot']['silver_price_per_gram'],
            (1 / 0.00025) / metal_prices.GRAMS_PER_TROY_OUNCE, places=2)

    @override_settings(METAL_PRICE_API_URL='', METAL_PRICE_API_KEY='')
    def test_missing_config_never_calls_api(self):
        with patch(URLOPEN_TARGET) as mock_urlopen:
            result = metal_prices.refresh_prices()
        mock_urlopen.assert_not_called()
        self.assertFalse(result['ok'])
        self.assertIn('not configured', result['message'])
        self.assertFalse(result['snapshot']['configured'])
        self.assertFalse(result['snapshot']['available'])

    def test_api_failure_is_friendly_unavailable(self):
        with patch(URLOPEN_TARGET, side_effect=urllib.error.URLError('refused')):
            result = metal_prices.refresh_prices()
        self.assertFalse(result['ok'])
        self.assertIn('Could not reach the price service', result['message'])
        self.assertFalse(result['snapshot']['available'])
        self.assertTrue(result['snapshot']['configured'])

    def test_api_timeout_is_friendly(self):
        with patch(URLOPEN_TARGET, side_effect=socket.timeout('timed out')):
            result = metal_prices.refresh_prices()
        self.assertFalse(result['ok'])
        self.assertIn('timed out', result['message'])

    def test_http_error_is_reported(self):
        error = urllib.error.HTTPError(
            'https://api.example.test', 500, 'Server Error', None, None)
        with patch(URLOPEN_TARGET, side_effect=error):
            result = metal_prices.refresh_prices()
        self.assertFalse(result['ok'])
        self.assertIn('HTTP 500', result['message'])

    def test_malformed_json_is_reported(self):
        with patch(URLOPEN_TARGET, return_value=_FakeResponse(b'<html>oops</html>')):
            result = metal_prices.refresh_prices()
        self.assertFalse(result['ok'])
        self.assertIn('unexpected response format', result['message'])

    def test_payload_without_usable_rates_is_reported(self):
        with patch(URLOPEN_TARGET, return_value=_FakeResponse({'rates': {}})):
            result = metal_prices.refresh_prices()
        self.assertFalse(result['ok'])
        self.assertIn('did not contain usable rates', result['message'])

    def test_stale_prices_survive_failed_refresh(self):
        good = {'rates': {'XAU': 343000.0, 'XAG': 4000.0}}
        with patch(URLOPEN_TARGET, return_value=_FakeResponse(good)):
            self.assertTrue(metal_prices.refresh_prices()['ok'])
        # Simulate TTL expiry of the "fresh" snapshot.
        cache.delete(metal_prices.SNAPSHOT_CACHE_KEY)
        with patch(URLOPEN_TARGET, side_effect=urllib.error.URLError('down')):
            result = metal_prices.refresh_prices()
        self.assertFalse(result['ok'])
        # The dashboard still shows the last good prices.
        stale = metal_prices.get_price_snapshot()
        self.assertTrue(stale['available'])
        self.assertEqual(result['snapshot']['gold_price_per_gram'],
                         stale['gold_price_per_gram'])

    def test_get_price_snapshot_is_cache_only(self):
        with patch(URLOPEN_TARGET) as mock_urlopen:
            snapshot = metal_prices.get_price_snapshot()
        mock_urlopen.assert_not_called()
        self.assertFalse(snapshot['available'])
        payload = {'rates': {'XAU': 343000.0, 'XAG': 4000.0}}
        with patch(URLOPEN_TARGET, return_value=_FakeResponse(payload)):
            self.assertTrue(metal_prices.refresh_prices()['ok'])
        with patch(URLOPEN_TARGET) as mock_urlopen:
            snapshot = metal_prices.get_price_snapshot()
        mock_urlopen.assert_not_called()
        self.assertTrue(snapshot['available'])


@METAL_PRICE_TEST_SETTINGS
class MetalPriceDashboardTests(TestCase):
    """Dashboard rendering and refresh action behaviour."""

    def setUp(self):
        User.objects.create_user('mpstaff', password='testpass123')
        self.client.login(username='mpstaff', password='testpass123')
        _clear_price_cache()

    def tearDown(self):
        _clear_price_cache()

    def test_dashboard_never_calls_the_api(self):
        with patch(URLOPEN_TARGET) as mock_urlopen:
            response = self.client.get(reverse('dashboard'))
        mock_urlopen.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['metal_prices']['available'])
        self.assertContains(response, 'Price unavailable')
        self.assertContains(response, 'Refresh')

    def test_dashboard_shows_cached_prices(self):
        payload = {'rates': {'XAU': 343000.0, 'XAG': 4000.0}}
        with patch(URLOPEN_TARGET, return_value=_FakeResponse(payload)):
            self.assertTrue(metal_prices.refresh_prices()['ok'])
        with patch(URLOPEN_TARGET) as mock_urlopen:
            response = self.client.get(reverse('dashboard'))
        mock_urlopen.assert_not_called()
        self.assertTrue(response.context['metal_prices']['available'])
        self.assertContains(response, 'Gold (XAU)')
        self.assertContains(response, 'Silver (XAG)')
        self.assertContains(response, 'Last updated')
        self.assertContains(response, '/ gram')

    def test_refresh_view_requires_login_and_post(self):
        url = reverse('metal_price_refresh')
        self.client.logout()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)
        self.client.login(username='mpstaff', password='testpass123')
        with patch(URLOPEN_TARGET) as mock_urlopen:
            response = self.client.get(url)
        mock_urlopen.assert_not_called()
        self.assertRedirects(response, reverse('dashboard'),
                             fetch_redirect_response=False)

    def test_refresh_view_success_message(self):
        payload = {'rates': {'XAU': 343000.0, 'XAG': 4000.0}}
        with patch(URLOPEN_TARGET, return_value=_FakeResponse(payload)):
            response = self.client.post(reverse('metal_price_refresh'),
                                        follow=True)
        self.assertContains(response, 'Metal prices updated.')
        self.assertContains(response, 'Gold (XAU)')

    def test_refresh_view_failure_message_with_stale_fallback(self):
        payload = {'rates': {'XAU': 343000.0, 'XAG': 4000.0}}
        with patch(URLOPEN_TARGET, return_value=_FakeResponse(payload)):
            metal_prices.refresh_prices()
        with patch(URLOPEN_TARGET, side_effect=urllib.error.URLError('down')):
            response = self.client.post(reverse('metal_price_refresh'),
                                        follow=True)
        self.assertContains(response, 'Price update failed')
        self.assertContains(response, 'Showing the last available prices.')

