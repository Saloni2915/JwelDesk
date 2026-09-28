import csv
import io
from decimal import Decimal
from unittest.mock import patch

import openpyxl
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.urls import reverse
from django.utils.html import escape
from inventory import import_utils, stock
from inventory.models import Category, JewelleryItem, StockMovement
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

    def test_net_weight_defaults_to_gross_minus_stone_weight(self):
        item = JewelleryItem(
            item_code='NET-CALC-001',
            name='Stone Set Ring',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('6.000'),
            stone_weight=Decimal('0.750'),
            selling_price=Decimal('50000.00'),
        )
        item.clean()
        self.assertEqual(item.net_weight, Decimal('5.250'))

    def test_stone_weight_cannot_exceed_gross_weight(self):
        item = JewelleryItem(
            item_code='STN-001',
            name='Over Stone Weight Item',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            stone_weight=Decimal('5.500'),
            selling_price=Decimal('50000.00'),
        )
        with self.assertRaises(ValidationError) as ctx:
            item.clean()
        self.assertIn('stone_weight', ctx.exception.message_dict)

    def test_net_and_stone_weight_together_cannot_exceed_gross_weight(self):
        item = JewelleryItem(
            item_code='STN-002',
            name='Weight Mismatch Item',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            stone_weight=Decimal('1.000'),
            net_weight=Decimal('4.500'),
            selling_price=Decimal('50000.00'),
        )
        with self.assertRaises(ValidationError) as ctx:
            item.clean()
        self.assertIn('stone_weight', ctx.exception.message_dict)

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

    def test_tag_number_is_generated_when_left_blank(self):
        piece = JewelleryItem.objects.create(
            item_code='TAG-AUTO-001',
            name='Auto Tag Ring',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('50000.00'),
        )
        self.assertTrue(piece.tag_number.startswith('JWL-'))
        self.assertEqual(len(piece.tag_number.split('-')[-1]), 6)

    def test_generated_tag_numbers_are_sequential_and_unique(self):
        first = JewelleryItem.objects.create(
            item_code='TAG-AUTO-010', name='Auto Tag Ring 1', category=self.category,
            metal_type='Gold', purity='22K', gross_weight=Decimal('5.000'),
            selling_price=Decimal('50000.00'),
        )
        second = JewelleryItem.objects.create(
            item_code='TAG-AUTO-011', name='Auto Tag Ring 2', category=self.category,
            metal_type='Gold', purity='22K', gross_weight=Decimal('5.100'),
            selling_price=Decimal('51000.00'),
        )
        self.assertNotEqual(first.tag_number, second.tag_number)
        self.assertEqual(
            int(second.tag_number.split('-')[-1]),
            int(first.tag_number.split('-')[-1]) + 1,
        )

    def test_manual_tag_number_is_kept_as_entered(self):
        piece = JewelleryItem.objects.create(
            item_code='TAG-MANUAL-001',
            tag_number='TD-1412',
            name='Tagged Ring',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('50000.00'),
        )
        self.assertEqual(piece.tag_number, 'TD-1412')

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
    'purity', 'gross_weight', 'stone_weight', 'net_weight', 'making_charge', 'selling_price', 'status',
]


def valid_import_row(item_code='IMP-RN-001', design_code='DSN-IMP-001', name='Imported Gold Ring',
                     category='Bulk Import Rings', metal_type='Gold', purity='22K (916)',
                     gross_weight='5.500', stone_weight='0.300', net_weight='5.200',
                     making_charge='2500.00', selling_price='48500.00', status='Available'):
    """Return one data row (list of cell values) for the bulk import tests."""
    return [
        item_code, design_code, name, category, metal_type,
        purity, gross_weight, stone_weight, net_weight, making_charge, selling_price, status,
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
                gross_weight='12.000', stone_weight='0.000', net_weight='12.000',
                making_charge='', status='reserved',
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

    # ---------------------------------------------------------
    # STONE / NET WEIGHT HANDLING
    # ---------------------------------------------------------
    def test_stone_weight_column_is_imported(self):
        self.upload_csv([
            valid_import_row(item_code='IMP-STN-001', name='Stone Studded Ring',
                             gross_weight='6.000', stone_weight='0.750', net_weight='5.250'),
        ])

        preview = self.preview_page()
        self.assertEqual(preview.context['summary']['valid_count'], 1)
        self.assertContains(preview, '0.750')

        self.post_confirm()
        imported = JewelleryItem.objects.get(item_code='IMP-STN-001')
        self.assertEqual(imported.stone_weight, Decimal('0.750'))
        self.assertEqual(imported.net_weight, Decimal('5.250'))
        self.assertEqual(imported.gross_weight, Decimal('6.000'))

    def test_blank_net_weight_is_derived_from_gross_and_stone_weight(self):
        self.upload_csv([
            valid_import_row(item_code='IMP-NETCALC-001', name='Beaded Gold Chain',
                             gross_weight='11.250', stone_weight='1.250', net_weight=''),
        ])

        preview = self.preview_page()
        self.assertEqual(preview.context['summary']['valid_count'], 1)
        self.assertEqual(preview.context['summary']['invalid_count'], 0)
        self.assertTrue(preview.context['can_import'])

        self.post_confirm()
        imported = JewelleryItem.objects.get(item_code='IMP-NETCALC-001')
        self.assertEqual(imported.stone_weight, Decimal('1.250'))
        self.assertEqual(imported.net_weight, Decimal('10.000'))

    def test_stone_weight_greater_than_gross_weight_is_reported(self):
        self.upload_csv([
            valid_import_row(item_code='IMP-STN-BAD-001', gross_weight='4.000',
                             stone_weight='4.500', net_weight=''),
        ])

        preview = self.preview_page()
        self.assertEqual(preview.context['summary']['valid_count'], 0)
        self.assertEqual(preview.context['summary']['invalid_count'], 1)
        self.assertContains(preview, 'Stone weight (4.500g) cannot exceed gross weight (4.000g).')

    def test_net_plus_stone_weight_greater_than_gross_weight_is_reported(self):
        self.upload_csv([
            valid_import_row(item_code='IMP-STN-BAD-002', gross_weight='5.000',
                             stone_weight='1.000', net_weight='4.500'),
        ])

        preview = self.preview_page()
        self.assertEqual(preview.context['summary']['invalid_count'], 1)
        self.assertContains(
            preview,
            'Net weight (4.500g) plus stone weight (1.000g) exceeds gross weight (5.000g).',
        )

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
        self.assertIn('gross_weight,stone_weight,net_weight', lines[0])
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



# ==============================================================================
# STOCK TRACKING (inventory management phase 1)
# ==============================================================================

def make_item(category, item_code, **overrides):
    """Small helper: create a JewelleryItem with sensible defaults."""
    defaults = {
        'name': f'Item {item_code}',
        'category': category,
        'metal_type': 'Gold',
        'purity': '22K',
        'gross_weight': Decimal('5.000'),
        'net_weight': Decimal('4.800'),
        'selling_price': Decimal('50000.00'),
        'status': 'Available',
    }
    defaults.update(overrides)
    return JewelleryItem.objects.create(item_code=item_code, **defaults)


class StockServiceTests(TestCase):
    """Stock value, summary, low stock and the stock movement service."""

    def setUp(self):
        self.user = User.objects.create_user(username='stockkeeper', password='Password123')
        self.category = Category.objects.create(name='Rings')
        self.item = make_item(self.category, 'STK-001')

    # -------------------------------------------------------------- valuation
    def test_item_stock_value_is_quantity_times_selling_price(self):
        self.item.quantity = 3
        self.item.save()
        self.assertEqual(stock.item_stock_value(self.item), Decimal('150000.00'))
        self.assertEqual(stock.inventory_value(), Decimal('150000.00'))

    def test_inventory_value_excludes_sold_and_reserved_items(self):
        make_item(self.category, 'STK-002', quantity=2)                       # 100000
        make_item(self.category, 'STK-003', quantity=5, status='Reserved')    # excluded
        make_item(self.category, 'STK-004', quantity=1, status='Sold')        # excluded
        # 50000 (STK-001) + 100000 (STK-002)
        self.assertEqual(stock.inventory_value(), Decimal('150000.00'))

    # ---------------------------------------------------------------- summary
    def test_inventory_summary_reports_stock_value_metals_and_low_stock(self):
        make_item(self.category, 'STK-GOLD', quantity=2,
                  gross_weight=Decimal('6.500'), net_weight=Decimal('6.000'))
        make_item(self.category, 'STK-SILVER', metal_type='Silver', purity='925',
                  quantity=4, gross_weight=Decimal('11.000'),
                  net_weight=Decimal('10.000'), selling_price=Decimal('2000.00'))
        make_item(self.category, 'STK-SOLD', status='Sold')

        summary = stock.inventory_summary()

        self.assertEqual(summary['total_items'], 4)
        self.assertEqual(summary['available_stock'], 7)   # 1 + 2 + 4
        self.assertEqual(summary['out_of_stock_items'], 1)
        self.assertEqual(summary['gold_stock'], 3)        # 1 + 2
        self.assertEqual(summary['silver_stock'], 4)
        self.assertEqual(summary['gold_weight'], Decimal('16.800'))    # 4.8 + (2 * 6.0)
        self.assertEqual(summary['silver_weight'], Decimal('40.000'))
        self.assertEqual(summary['inventory_value'], Decimal('158000.00'))
        self.assertEqual(summary['low_stock_threshold'], 1)

    def test_inventory_summary_on_empty_inventory(self):
        JewelleryItem.objects.all().delete()
        summary = stock.inventory_summary()
        self.assertEqual(summary['total_items'], 0)
        self.assertEqual(summary['available_stock'], 0)
        self.assertEqual(summary['inventory_value'], Decimal('0.00'))
        self.assertEqual(summary['low_stock_design_count'], 0)

    # -------------------------------------------------------------- low stock
    def test_low_stock_detection_at_or_below_threshold(self):
        make_item(self.category, 'LOW-001', quantity=1, design_code='DSN-LOW')
        make_item(self.category, 'LOW-002', quantity=1, design_code='DSN-LOW')
        make_item(self.category, 'OK-001', quantity=5, design_code='DSN-OK')

        codes = stock.low_stock_design_codes()          # default threshold = 1
        self.assertNotIn('DSN-LOW', codes)              # 2 available pieces > 1

        codes = stock.low_stock_design_codes(2)
        self.assertIn('DSN-LOW', codes)
        self.assertNotIn('DSN-OK', codes)

        low_items = {i.item_code for i in stock.low_stock_items(2)
                     if i.design_code == 'DSN-LOW'}
        self.assertEqual(low_items, {'LOW-001', 'LOW-002'})

    def test_low_stock_ignores_designs_with_no_stock_left(self):
        make_item(self.category, 'GONE-001', status='Sold', design_code='DSN-GONE')
        self.assertNotIn('DSN-GONE', stock.low_stock_design_codes(5))
        self.assertNotIn('GONE-001', {i.item_code for i in stock.low_stock_items(5)})

    def test_low_stock_threshold_setting_and_override(self):
        make_item(self.category, 'TH-001', quantity=3)
        self.assertEqual(stock.get_low_stock_threshold(), 1)
        self.assertEqual(stock.get_low_stock_threshold(''), 1)
        self.assertEqual(stock.get_low_stock_threshold('4'), 4)
        self.assertEqual(stock.get_low_stock_threshold('not-a-number'), 1)
        self.assertEqual(stock.get_low_stock_threshold('-5'), 0)
        self.assertEqual(stock.get_low_stock_threshold(99999), 1000)
        with override_settings(INVENTORY_LOW_STOCK_THRESHOLD=3):
            self.assertEqual(stock.get_low_stock_threshold(), 3)

    def test_low_stock_designs_report_lists_pieces_left(self):
        make_item(self.category, 'DSN-A-1', quantity=1, design_code='DSN-A')
        report = {d['design_code']: d for d in stock.low_stock_designs(2)}
        self.assertIn('DSN-A', report)
        self.assertEqual(report['DSN-A']['available'], 1)
        self.assertEqual(report['DSN-A']['item_count'], 1)



    # ------------------------------------------------------------ adjustments
    def test_stock_increase_creates_movement_and_updates_quantity(self):
        movement = stock.apply_stock_change(
            self.item, 4, StockMovement.ADDITION,
            reason='New Stock Received', notes='Supplier invoice 42', user=self.user)

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 5)
        self.assertEqual(self.item.status, 'Available')
        self.assertEqual(movement.stock_before, 1)
        self.assertEqual(movement.stock_after, 5)
        self.assertEqual(movement.quantity_change, 4)
        self.assertEqual(movement.reason, 'New Stock Received')
        self.assertEqual(movement.notes, 'Supplier invoice 42')
        self.assertEqual(movement.created_by, self.user)
        self.assertEqual(self.item.stock_movements.count(), 1)

    def test_stock_decrease_creates_movement(self):
        self.item.quantity = 4
        self.item.save()
        movement = stock.apply_stock_change(
            self.item, -3, StockMovement.REDUCTION, reason='Damaged Item')

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 1)
        self.assertEqual(movement.quantity_change, -3)
        self.assertEqual(movement.stock_before, 4)
        self.assertEqual(movement.stock_after, 1)

    def test_stock_reduction_to_zero_marks_the_item_sold(self):
        movement = stock.apply_stock_change(
            self.item, -1, StockMovement.REDUCTION, reason='Lost Item')
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 0)
        self.assertEqual(self.item.status, 'Sold')
        self.assertTrue(self.item.is_out_of_stock)
        self.assertEqual(movement.stock_after, 0)

    def test_negative_stock_is_rejected(self):
        with self.assertRaises(ValidationError):
            stock.apply_stock_change(self.item, -2, StockMovement.REDUCTION)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 1)
        self.assertEqual(self.item.status, 'Available')
        self.assertEqual(self.item.stock_movements.count(), 0)

    def test_zero_change_is_rejected(self):
        with self.assertRaises(ValidationError):
            stock.apply_stock_change(self.item, 0, StockMovement.ADJUSTMENT)
        self.assertEqual(self.item.stock_movements.count(), 0)

    def test_multiple_movements_keep_a_consistent_chain(self):
        stock.apply_stock_change(self.item, 4, StockMovement.ADDITION)
        stock.apply_stock_change(self.item, -2, StockMovement.REDUCTION)
        stock.apply_stock_change(self.item, 3, StockMovement.ADJUSTMENT)

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 6)

        movements = list(self.item.stock_movements.order_by('id'))
        self.assertEqual(len(movements), 3)
        # Chronological chain: each movement starts where the previous one ended
        # (the item starts with one piece in stock).
        expected = [(1, 5), (5, 3), (3, 6)]
        for movement, (before, after) in zip(movements, expected):
            self.assertEqual((movement.stock_before, movement.stock_after), (before, after))
        self.assertEqual(movements[-1].stock_after, self.item.quantity)

    def test_restocking_a_sold_item_makes_it_available_again(self):
        make_item(self.category, 'BACK-001', status='Sold')
        sold = JewelleryItem.objects.get(item_code='BACK-001')
        stock.apply_stock_change(sold, 2, StockMovement.ADDITION)
        sold.refresh_from_db()
        self.assertEqual(sold.quantity, 3)
        self.assertEqual(sold.status, 'Available')

    def test_movement_model_rejects_inconsistent_values(self):
        movement = StockMovement(
            item=self.item, movement_type=StockMovement.ADDITION,
            quantity_change=2, stock_before=1, stock_after=99)
        with self.assertRaises(ValidationError):
            movement.clean()

    def test_movement_constraints_block_a_zero_quantity_change(self):
        with self.assertRaises((IntegrityError, ValidationError)):
            StockMovement.objects.create(
                item=self.item, movement_type=StockMovement.ADJUSTMENT,
                quantity_change=0, stock_before=1, stock_after=1)


class StockAdjustmentViewTests(TestCase):
    """The controlled stock adjustment screen (increase / decrease / stock take)."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='adjuster', password='Password123')
        self.client.login(username='adjuster', password='Password123')
        self.category = Category.objects.create(name='Chains')
        self.item = make_item(self.category, 'ADJ-001')

    def _post(self, **data):
        payload = {'adjustment_type': 'increase', 'reason': 'New Stock Received'}
        payload.update(data)
        return self.client.post(
            reverse('stock_adjust', kwargs={'pk': self.item.pk}), payload, follow=True)

    def test_adjust_view_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('stock_adjust', kwargs={'pk': self.item.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_adjust_page_renders_the_form(self):
        response = self.client.get(reverse('stock_adjust', kwargs={'pk': self.item.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'inventory/stock_adjust.html')
        self.assertContains(response, 'Stock Adjustment')
        self.assertContains(response, self.item.item_code)

    def test_stock_increase_via_view(self):
        response = self._post(adjustment_type='increase', quantity='5',
                              notes='New arrivals')
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 6)

        movement = self.item.stock_movements.get()
        self.assertEqual(movement.movement_type, StockMovement.ADDITION)
        self.assertEqual(movement.quantity_change, 5)
        self.assertEqual(movement.stock_before, 1)
        self.assertEqual(movement.stock_after, 6)
        self.assertEqual(movement.reason, 'New Stock Received')
        self.assertEqual(movement.notes, 'New arrivals')
        self.assertEqual(movement.created_by, self.user)
        self.assertIsNotNone(movement.created_at)

    def test_stock_decrease_via_view(self):
        self.item.quantity = 6
        self.item.save()
        self._post(adjustment_type='decrease', quantity='2', reason='Damaged Item')
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 4)
        self.assertEqual(self.item.stock_movements.get().movement_type, StockMovement.REDUCTION)

    def test_negative_stock_is_rejected_via_view(self):
        response = self._post(adjustment_type='decrease', quantity='5',
                              reason='Lost Item')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Stock can never become negative')
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 1)
        self.assertEqual(self.item.stock_movements.count(), 0)

    def test_stock_take_sets_the_exact_count(self):
        self.item.quantity = 7
        self.item.save()
        self._post(adjustment_type='set', new_stock='4', reason='Stock Correction')
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 4)
        movement = self.item.stock_movements.get()
        self.assertEqual(movement.movement_type, StockMovement.ADJUSTMENT)
        self.assertEqual(movement.quantity_change, -3)
        self.assertEqual(movement.stock_before, 7)
        self.assertEqual(movement.stock_after, 4)

    def test_stock_take_with_unchanged_count_is_rejected(self):
        response = self._post(adjustment_type='set', new_stock='1',
                              reason='Stock Correction')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'nothing to adjust')
        self.assertEqual(self.item.stock_movements.count(), 0)

    def test_reason_is_required(self):
        response = self.client.post(
            reverse('stock_adjust', kwargs={'pk': self.item.pk}),
            {'adjustment_type': 'increase', 'quantity': '2', 'reason': ''})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.item.stock_movements.count(), 0)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 1)

    def test_quantity_is_required_for_increase_and_decrease(self):
        response = self._post(adjustment_type='increase', quantity='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter the number of pieces')
        self.assertEqual(self.item.stock_movements.count(), 0)



class SaleStockIntegrationTests(TestCase):
    """Completing a sale must reduce stock exactly once."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='cashier2', password='Password123')
        self.client.login(username='cashier2', password='Password123')
        self.category = Category.objects.create(name='Bangles')
        self.customer = Customer.objects.create(name='Meera Shah', mobile='+91 9000000000')
        self.item = make_item(self.category, 'SALE-001')

    def _sell(self):
        return self.client.post(reverse('sale_add'), {
            'customer': self.customer.id,
            'jewellery_item': self.item.id,
            'sale_price': '50000.00',
            'payment_method': 'Cash',
        }, follow=True)

    def test_sale_reduces_stock_and_records_a_sale_movement(self):
        response = self._sell()
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 0)
        self.assertEqual(self.item.status, 'Sold')

        sale = Sale.objects.get(jewellery_item=self.item)
        movement = self.item.stock_movements.get()
        self.assertEqual(movement.movement_type, StockMovement.SALE)
        self.assertEqual(movement.quantity_change, -1)
        self.assertEqual(movement.stock_before, 1)
        self.assertEqual(movement.stock_after, 0)
        self.assertEqual(movement.sale, sale)
        self.assertEqual(movement.created_by, self.user)

    def test_sale_of_extra_pieces_keeps_the_item_available(self):
        self.item.quantity = 3
        self.item.save()
        self._sell()
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 2)
        self.assertEqual(self.item.status, 'Available')

    def test_stock_is_not_reduced_twice_when_item_sells_out(self):
        # Selling the last piece marks it as Sold. A second attempt must be
        # rejected and not reduce stock further or log another movement.
        self.item.quantity = 1
        self.item.save()
        first = self._sell()
        self.assertEqual(first.status_code, 200)
        second = self._sell()
        self.assertContains(second, 'already SOLD')
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 0)
        self.assertEqual(self.item.status, 'Sold')
        self.assertEqual(self.item.stock_movements.count(), 1)
        self.assertEqual(Sale.objects.count(), 1)

    def test_sale_is_blocked_when_no_stock_is_left(self):
        self.item.quantity = 0
        self.item.status = 'Available'
        self.item.save()
        response = self._sell()
        self.assertContains(response, 'already SOLD')
        self.assertEqual(Sale.objects.count(), 0)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 0)
        self.assertEqual(self.item.stock_movements.count(), 0)

    def test_invoice_pdf_still_works_after_the_stock_change(self):
        self._sell()
        sale = Sale.objects.get(jewellery_item=self.item)
        response = self.client.get(reverse('sale_invoice_pdf', kwargs={'pk': sale.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')


class InventoryStockPageTests(TestCase):
    """Inventory list summary/filters, item detail stock block and movement history."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='viewer', password='Password123')
        self.client.login(username='viewer', password='Password123')
        self.category = Category.objects.create(name='Earrings')
        self.silver_category = Category.objects.create(name='Silver Line')
        self.item = make_item(self.category, 'PG-001', quantity=2, design_code='DSN-PG')
        self.silver = make_item(
            self.silver_category, 'PG-002', metal_type='Silver', purity='925',
            quantity=6, design_code='DSN-AG', selling_price=Decimal('2000.00'))
        self.sold = make_item(self.category, 'PG-003', status='Sold', quantity=0)
        stock.apply_stock_change(self.item, 2, StockMovement.ADDITION,
                                 reason='New Stock Received', user=self.user)
        # item now has quantity=4 (low stock with default threshold 5)

    # ------------------------------------------------------------------ list
    def test_list_shows_the_inventory_summary(self):
        response = self.client.get(reverse('inventory_list'))
        self.assertEqual(response.status_code, 200)
        summary = response.context['summary']
        self.assertEqual(summary['total_items'], 3)
        self.assertEqual(summary['available_stock'], 10)          # 4 + 6
        self.assertEqual(summary['gold_stock'], 4)
        self.assertEqual(summary['silver_stock'], 6)
        self.assertEqual(summary['inventory_value'], Decimal('212000.00'))
        self.assertContains(response, 'Available Stock')
        self.assertContains(response, 'Stock Value')
        self.assertContains(response, 'Low Stock')
        self.assertContains(response, 'Stock Movements')

    def test_list_low_stock_filter_and_badge(self):
        # Set the threshold so PG-001 (quantity=4) is treated as low-stock
        # under the default page view without an explicit ?threshold= param.
        with self.settings(INVENTORY_LOW_STOCK_THRESHOLD=4):
            response = self.client.get(reverse('inventory_list'), {'stock': 'low_stock'})
            self.assertEqual(response.status_code, 200)
            codes = [item.item_code for item in response.context['items']]
            self.assertEqual(codes, ['PG-001'])

        response = self.client.get(reverse('inventory_list'),
                                   {'stock': 'low_stock', 'threshold': '7'})
        codes = sorted(item.item_code for item in response.context['items'])
        self.assertEqual(codes, ['PG-001', 'PG-002'])

    def test_list_stock_status_out_of_stock_filter(self):
        response = self.client.get(reverse('inventory_list'), {'stock': 'out_of_stock'})
        codes = [item.item_code for item in response.context['items']]
        self.assertEqual(codes, ['PG-003'])

    def test_list_reserved_and_available_filters(self):
        self.item.status = 'Reserved'
        self.item.save()
        reserved = self.client.get(reverse('inventory_list'), {'stock': 'reserved'})
        self.assertEqual([i.item_code for i in reserved.context['items']], ['PG-001'])
        available = self.client.get(reverse('inventory_list'), {'stock': 'available'})
        self.assertEqual([i.item_code for i in available.context['items']], ['PG-002'])

    def test_list_purity_filter_and_search(self):
        response = self.client.get(reverse('inventory_list'), {'purity': '925'})
        self.assertEqual([i.item_code for i in response.context['items']], ['PG-002'])
        response = self.client.get(reverse('inventory_list'), {'q': 'PG-002'})
        self.assertEqual([i.item_code for i in response.context['items']], ['PG-002'])

    def test_list_threshold_query_param_is_reported(self):
        response = self.client.get(reverse('inventory_list'), {'threshold': '3'})
        self.assertEqual(response.context['low_stock_threshold'], 3)

    # ---------------------------------------------------------------- detail
    def test_detail_shows_stock_value_and_movements(self):
        response = self.client.get(reverse('inventory_detail', kwargs={'pk': self.item.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['stock_value'], Decimal('200000.00'))
        self.assertEqual(response.context['movement_count'], 1)
        self.assertEqual(len(response.context['movements']), 1)
        self.assertContains(response, 'Valuation')
        self.assertContains(response, 'Recent Stock Movements')
        self.assertContains(response, 'New Stock Received')
        self.assertContains(response, 'Adjust Stock')

    # -------------------------------------------------------------- history
    def test_history_page_lists_movements_with_totals(self):
        response = self.client.get(reverse('stock_movement_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['totals']['movement_count'], 1)
        self.assertEqual(response.context['totals']['stock_in'], 2)
        self.assertEqual(response.context['totals']['stock_out'], 0)
        self.assertContains(response, 'PG-001')
        self.assertContains(response, 'New Stock Received')

    def test_history_page_filters(self):
        stock.apply_stock_change(self.silver, -2, StockMovement.REDUCTION,
                                 reason='Damaged Item', user=self.user)

        by_type = self.client.get(reverse('stock_movement_list'), {'type': 'Reduction'})
        self.assertEqual(by_type.context['totals']['movement_count'], 1)
        self.assertEqual(by_type.context['totals']['stock_out'], -2)

        by_item = self.client.get(reverse('stock_movement_list'),
                                  {'item': str(self.item.pk)})
        self.assertEqual(by_item.context['totals']['movement_count'], 1)
        self.assertTrue(by_item.context['is_item_filter'])

        by_search = self.client.get(reverse('stock_movement_list'), {'q': 'PG-002'})
        self.assertEqual(by_search.context['totals']['movement_count'], 1)

        by_date = self.client.get(reverse('stock_movement_list'), {'from': '2099-01-01'})
        self.assertEqual(by_date.context['totals']['movement_count'], 0)

    def test_history_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('stock_movement_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)


class OpeningStockTests(TestCase):
    """New items start their stock ledger at zero."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='creator', password='Password123')
        self.client.login(username='creator', password='Password123')
        self.category = Category.objects.create(name='Pendants')

    def test_new_item_records_its_opening_stock(self):
        self.client.post(reverse('inventory_add'), {
            'item_code': 'OPEN-001',
            'name': 'Opening Balance Pendant',
            'category': self.category.id,
            'metal_type': 'Gold',
            'purity': '22K',
            'gross_weight': '4.000',
            'net_weight': '3.800',
            'making_charge': '500.00',
            'selling_price': '25000.00',
            'status': 'Available',
        }, follow=True)

        item = JewelleryItem.objects.get(item_code='OPEN-001')
        self.assertEqual(item.quantity, 1)
        movement = item.stock_movements.get()
        self.assertEqual(movement.movement_type, StockMovement.ADDITION)
        self.assertEqual(movement.stock_before, 0)
        self.assertEqual(movement.stock_after, 1)
        self.assertEqual(movement.created_by, self.user)


class JewelleryTagAndHallmarkTests(TestCase):
    """
    Phase 1: Jewellery Tag + HUID / Hallmark tests.
    Tests internal tag generation, uniqueness, HUID optionality, HUID format/uniqueness,
    hallmark status, search/filter by tag and HUID, and admin/form/import integration.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='hallmark_staff', password='Password123')
        self.client.login(username='hallmark_staff', password='Password123')
        self.category = Category.objects.create(name='Pendants & Lockets')

    # ---- 1. Jewellery Tag ----------------------------------------------------
    def test_tag_number_auto_generation(self):
        item = JewelleryItem.objects.create(
            item_code='TAG-TEST-001',
            name='Gold Locket',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('4.500'),
            selling_price=Decimal('35000.00'),
        )
        self.assertTrue(item.tag_number.startswith('JWL-'))
        self.assertEqual(len(item.tag_number), 10)  # 'JWL-' + 6 digits
        suffix = item.tag_number.split('-')[-1]
        self.assertTrue(suffix.isdigit())

    def test_tag_number_uniqueness_on_auto_generation(self):
        item1 = JewelleryItem.objects.create(
            item_code='TAG-UNIQ-001', name='Item 1', category=self.category,
            metal_type='Gold', purity='22K', gross_weight=Decimal('4.000'),
            selling_price=Decimal('30000.00'),
        )
        item2 = JewelleryItem.objects.create(
            item_code='TAG-UNIQ-002', name='Item 2', category=self.category,
            metal_type='Gold', purity='22K', gross_weight=Decimal('4.000'),
            selling_price=Decimal('30000.00'),
        )
        self.assertNotEqual(item1.tag_number, item2.tag_number)
        num1 = int(item1.tag_number.split('-')[-1])
        num2 = int(item2.tag_number.split('-')[-1])
        self.assertEqual(num2, num1 + 1)

    def test_manual_tag_number_preserved(self):
        custom_tag = 'CUST-TAG-999'
        item = JewelleryItem.objects.create(
            item_code='TAG-MANUAL-999',
            tag_number=custom_tag,
            name='Custom Tagged Piece',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('40000.00'),
        )
        self.assertEqual(item.tag_number, custom_tag)

    def test_manual_duplicate_tag_rejected(self):
        JewelleryItem.objects.create(
            item_code='TAG-DUP-001',
            tag_number='DUP-TAG-001',
            name='First Tagged',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('40000.00'),
        )
        with self.assertRaises((ValidationError, IntegrityError)):
            second = JewelleryItem(
                item_code='TAG-DUP-002',
                tag_number='DUP-TAG-001',
                name='Second Tagged',
                category=self.category,
                metal_type='Gold',
                purity='22K',
                gross_weight=Decimal('5.000'),
                selling_price=Decimal('40000.00'),
            )
            second.save()

    def test_tag_generation_skips_existing_numbers_safely(self):
        # Manually create JWL-000002 before sequence reaches it
        manual = JewelleryItem.objects.create(
            item_code='TAG-SKIP-MANUAL',
            tag_number='JWL-000002',
            name='Pre-existing Tag',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('40000.00'),
        )
        # Next auto-generated item should not collide
        first_auto = JewelleryItem.objects.create(
            item_code='TAG-SKIP-AUTO-1',
            name='Auto Piece 1',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('40000.00'),
        )
        second_auto = JewelleryItem.objects.create(
            item_code='TAG-SKIP-AUTO-2',
            name='Auto Piece 2',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('40000.00'),
        )
        self.assertNotEqual(first_auto.tag_number, manual.tag_number)
        self.assertNotEqual(second_auto.tag_number, manual.tag_number)
        self.assertNotEqual(first_auto.tag_number, second_auto.tag_number)

    # ---- 2. HUID & Hallmark --------------------------------------------------
    def test_huid_can_be_blank_for_multiple_items(self):
        item1 = JewelleryItem.objects.create(
            item_code='BLANK-HUID-001',
            huid='',
            name='Non-hallmarked 1',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('3.000'),
            selling_price=Decimal('20000.00'),
        )
        item2 = JewelleryItem.objects.create(
            item_code='BLANK-HUID-002',
            huid='',
            name='Non-hallmarked 2',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('3.500'),
            selling_price=Decimal('25000.00'),
        )
        self.assertEqual(item1.huid, '')
        self.assertEqual(item2.huid, '')
        self.assertEqual(item1.huid_status, 'Not Applicable')
        self.assertEqual(item2.huid_status, 'Not Applicable')

    def test_duplicate_huid_is_rejected_on_clean(self):
        JewelleryItem.objects.create(
            item_code='HUID-DUP-001',
            huid='AB1234',
            name='Hallmarked Piece 1',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('45000.00'),
        )
        duplicate_item = JewelleryItem(
            item_code='HUID-DUP-002',
            huid='AB1234',
            name='Hallmarked Piece 2',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('45000.00'),
        )
        with self.assertRaises(ValidationError) as ctx:
            duplicate_item.clean()
        self.assertIn('huid', ctx.exception.message_dict)

    def test_duplicate_huid_rejected_by_db_constraint(self):
        JewelleryItem.objects.create(
            item_code='HUID-DB-001',
            huid='XY9876',
            name='DB Piece 1',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('45000.00'),
        )
        with self.assertRaises((IntegrityError, ValidationError)):
            JewelleryItem.objects.create(
                item_code='HUID-DB-002',
                huid='XY9876',
                name='DB Piece 2',
                category=self.category,
                metal_type='Gold',
                purity='22K',
                gross_weight=Decimal('5.000'),
                selling_price=Decimal('45000.00'),
            )

    def test_different_huids_work(self):
        item1 = JewelleryItem.objects.create(
            item_code='HUID-DIFF-001',
            huid='AB1234',
            huid_status='Verified',
            hallmark_status='Hallmarked',
            name='Piece AB',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('45000.00'),
        )
        item2 = JewelleryItem.objects.create(
            item_code='HUID-DIFF-002',
            huid='CD5678',
            huid_status='Verified',
            hallmark_status='Hallmarked',
            name='Piece CD',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('45000.00'),
        )
        self.assertEqual(item1.huid, 'AB1234')
        self.assertEqual(item2.huid, 'CD5678')
        self.assertEqual(JewelleryItem.objects.filter(huid__in=['AB1234', 'CD5678']).count(), 2)

    def test_huid_normalized_to_uppercase_and_trimmed(self):
        item = JewelleryItem.objects.create(
            item_code='HUID-NORM-001',
            huid='  ab1234  ',
            name='Lowercase HUID Piece',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('45000.00'),
        )
        self.assertEqual(item.huid, 'AB1234')

    def test_invalid_huid_length_or_characters_rejected(self):
        for invalid in ['12345', '1234567', 'AB-123', 'AB 123']:
            item = JewelleryItem(
                item_code=f'INV-HUID-{invalid}',
                huid=invalid,
                name='Invalid HUID Piece',
                category=self.category,
                metal_type='Gold',
                purity='22K',
                gross_weight=Decimal('5.000'),
                selling_price=Decimal('45000.00'),
            )
            with self.assertRaises(ValidationError):
                item.clean()

    def test_existing_jewellery_items_without_huid_remain_valid(self):
        item = JewelleryItem.objects.create(
            item_code='EXISTING-001',
            name='Existing Plain Ring',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('6.000'),
            selling_price=Decimal('55000.00'),
        )
        self.assertEqual(item.huid, '')
        item.name = 'Updated Plain Ring'
        item.selling_price = Decimal('57000.00')
        item.save()
        item.refresh_from_db()
        self.assertEqual(item.name, 'Updated Plain Ring')
        self.assertEqual(item.huid, '')

    def test_hallmark_status_and_details_fields(self):
        item = JewelleryItem.objects.create(
            item_code='HM-DETAIL-001',
            huid='HM1234',
            huid_status='Verified',
            hallmark_status='Hallmarked',
            hallmark_details='Assayed at BIS Center Mum-4001, Cert #9921',
            name='Certified Gold Chain',
            category=self.category,
            metal_type='Gold',
            purity='22K (916)',
            gross_weight=Decimal('12.000'),
            selling_price=Decimal('95000.00'),
        )
        self.assertEqual(item.hallmark_status, 'Hallmarked')
        self.assertEqual(item.huid_status, 'Verified')
        self.assertEqual(item.hallmark_details, 'Assayed at BIS Center Mum-4001, Cert #9921')

    # ---- 3. Search and Filters UI --------------------------------------------
    def test_search_by_tag_number(self):
        target = JewelleryItem.objects.create(
            item_code='SRCH-TAG-TARGET',
            tag_number='JWL-990001',
            name='Unique Tagged Necklace',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('15.000'),
            selling_price=Decimal('110000.00'),
        )
        other = JewelleryItem.objects.create(
            item_code='SRCH-TAG-OTHER',
            name='Other Necklace',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('10.000'),
            selling_price=Decimal('80000.00'),
        )
        # Search via ?q=
        resp = self.client.get(reverse('inventory_list'), {'q': 'JWL-990001'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Unique Tagged Necklace')
        self.assertNotContains(resp, 'Other Necklace')

        # Filter via ?tag_number=
        resp_tag = self.client.get(reverse('inventory_list'), {'tag_number': 'JWL-990001'})
        self.assertEqual(resp_tag.status_code, 200)
        self.assertContains(resp_tag, 'Unique Tagged Necklace')
        self.assertNotContains(resp_tag, 'Other Necklace')

    def test_search_by_huid(self):
        target = JewelleryItem.objects.create(
            item_code='SRCH-HUID-TARGET',
            huid='ZX9988',
            name='Unique HUID Bangle',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('20.000'),
            selling_price=Decimal('150000.00'),
        )
        other = JewelleryItem.objects.create(
            item_code='SRCH-HUID-OTHER',
            name='Unmarked Bangle',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('18.000'),
            selling_price=Decimal('130000.00'),
        )
        # Search via ?q=
        resp = self.client.get(reverse('inventory_list'), {'q': 'ZX9988'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Unique HUID Bangle')
        self.assertNotContains(resp, 'Unmarked Bangle')

        # Filter via ?huid=
        resp_huid = self.client.get(reverse('inventory_list'), {'huid': 'ZX9988'})
        self.assertEqual(resp_huid.status_code, 200)
        self.assertContains(resp_huid, 'Unique HUID Bangle')
        self.assertNotContains(resp_huid, 'Unmarked Bangle')

    def test_filter_by_huid_and_hallmark_status(self):
        verified_item = JewelleryItem.objects.create(
            item_code='STATUS-HM-001',
            huid='VR1111',
            huid_status='Verified',
            hallmark_status='Hallmarked',
            name='Fully Hallmarked Piece',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('8.000'),
            selling_price=Decimal('60000.00'),
        )
        pending_item = JewelleryItem.objects.create(
            item_code='STATUS-HM-002',
            huid='PN2222',
            huid_status='Pending',
            hallmark_status='Pending',
            name='Assay Pending Piece',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('8.000'),
            selling_price=Decimal('60000.00'),
        )
        resp_verified = self.client.get(reverse('inventory_list'), {'huid_status': 'Verified'})
        self.assertContains(resp_verified, 'Fully Hallmarked Piece')
        self.assertNotContains(resp_verified, 'Assay Pending Piece')

        resp_hallmarked = self.client.get(reverse('inventory_list'), {'hallmark_status': 'Hallmarked'})
        self.assertContains(resp_hallmarked, 'Fully Hallmarked Piece')
        self.assertNotContains(resp_hallmarked, 'Assay Pending Piece')

        resp_pending = self.client.get(reverse('inventory_list'), {'hallmark_status': 'Pending'})
        self.assertContains(resp_pending, 'Assay Pending Piece')
        self.assertNotContains(resp_pending, 'Fully Hallmarked Piece')

    def test_detail_view_shows_tag_number_and_huid_details(self):
        item = JewelleryItem.objects.create(
            item_code='DET-TAG-001',
            tag_number='JWL-123456',
            huid='HM8899',
            huid_status='Verified',
            hallmark_status='Hallmarked',
            hallmark_details='Mumbai Hallmarking Assay Centre',
            name='Royal Navratna Pendant',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('10.000'),
            net_weight=Decimal('9.500'),
            selling_price=Decimal('75000.00'),
        )
        resp = self.client.get(reverse('inventory_detail', kwargs={'pk': item.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'JWL-123456')
        self.assertContains(resp, 'HM8899')
        self.assertContains(resp, 'Verified')
        self.assertContains(resp, 'Hallmarked')
        self.assertContains(resp, 'Mumbai Hallmarking Assay Centre')

    # ---- 4. Form & UI Add/Edit -----------------------------------------------
    def test_form_auto_assigns_tag_when_left_blank(self):
        resp = self.client.post(reverse('inventory_add'), {
            'item_code': 'FORM-ADD-AUTO-01',
            'tag_number': '',
            'name': 'Form Added Ring',
            'category': self.category.id,
            'metal_type': 'Gold',
            'purity': '22K',
            'gross_weight': '5.000',
            'net_weight': '4.800',
            'selling_price': '40000.00',
            'status': 'Available',
            'huid': '',
            'huid_status': 'Not Applicable',
            'hallmark_status': 'Not Applicable',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        item = JewelleryItem.objects.get(item_code='FORM-ADD-AUTO-01')
        self.assertTrue(item.tag_number.startswith('JWL-'))

    def test_form_rejects_duplicate_huid(self):
        JewelleryItem.objects.create(
            item_code='FORM-EXIST-HUID',
            huid='UN5555',
            name='Existing HUID Item',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('40000.00'),
        )
        resp = self.client.post(reverse('inventory_add'), {
            'item_code': 'FORM-NEW-HUID',
            'name': 'New Item With Duplicate HUID',
            'category': self.category.id,
            'metal_type': 'Gold',
            'purity': '22K',
            'gross_weight': '5.000',
            'net_weight': '4.800',
            'selling_price': '40000.00',
            'status': 'Available',
            'huid': 'UN5555',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(resp.context['form'], 'huid', 'This HUID is already assigned to another item.')

    def test_form_rejects_invalid_huid(self):
        resp = self.client.post(reverse('inventory_add'), {
            'item_code': 'FORM-INV-HUID',
            'name': 'Invalid HUID Item',
            'category': self.category.id,
            'metal_type': 'Gold',
            'purity': '22K',
            'gross_weight': '5.000',
            'net_weight': '4.800',
            'selling_price': '40000.00',
            'status': 'Available',
            'huid': '12345',  # only 5 chars
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(resp.context['form'], 'huid', 'HUID must be exactly 6 alphanumeric characters.')

    # ---- 5. Bulk Import with Tag & HUID --------------------------------------
    def test_bulk_import_with_tag_number_and_huid(self):
        csv_content = (
            "item_code,tag_number,huid,name,category,metal_type,purity,gross_weight,stone_weight,net_weight,making_charge,selling_price,status\n"
            "IMP-TAG-01,JWL-777001,AB1122,Imported Tagged Pendant,Pendants,Gold,22K,6.000,0.200,5.800,2000.00,48000.00,Available\n"
        ).encode('utf-8')
        upload = self.client.post(reverse('inventory_import'), {
            'action': 'upload',
            'import_file': SimpleUploadedFile('test_huid.csv', csv_content, content_type='text/csv'),
        })
        self.assertRedirects(upload, reverse('inventory_import'), fetch_redirect_response=False)
        preview = self.client.get(reverse('inventory_import'))
        self.assertEqual(preview.context['summary']['valid_count'], 1)
        self.client.post(reverse('inventory_import'), {'action': 'confirm'})
        imported = JewelleryItem.objects.get(item_code='IMP-TAG-01')
        self.assertEqual(imported.tag_number, 'JWL-777001')
        self.assertEqual(imported.huid, 'AB1122')

    def test_bulk_import_rejects_duplicate_huid(self):
        JewelleryItem.objects.create(
            item_code='PRE-EXIST-HUID',
            huid='KL9999',
            name='Existing HUID Item',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            selling_price=Decimal('40000.00'),
        )
        csv_content = (
            "item_code,huid,name,category,metal_type,purity,gross_weight,stone_weight,net_weight,making_charge,selling_price,status\n"
            "IMP-HUID-DUP,KL9999,Import Duplicate HUID,Pendants,Gold,22K,6.000,0.000,6.000,2000.00,48000.00,Available\n"
        ).encode('utf-8')
        upload = self.client.post(reverse('inventory_import'), {
            'action': 'upload',
            'import_file': SimpleUploadedFile('dup_huid.csv', csv_content, content_type='text/csv'),
        })
        self.assertRedirects(upload, reverse('inventory_import'), fetch_redirect_response=False)
        preview = self.client.get(reverse('inventory_import'))
        self.assertEqual(preview.context['summary']['invalid_count'], 1)
        self.assertFalse(preview.context['can_import'])

