from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from inventory.models import Category, JewelleryItem
from customers.models import Customer
from django.core.exceptions import ValidationError
from sales.models import Payment, Sale, Enquiry, OldGoldTransaction, generate_old_gold_number
from team.models import Role, Employee, EmployeePermission


class SalesAndEnquiryTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='cashier', password='Password123')
        self.client.login(username='cashier', password='Password123')

        self.category = Category.objects.create(name='Rings', description='Gold Rings')
        self.customer = Customer.objects.create(
            name='Ramesh Kumar',
            mobile='+91 9888877777',
            email='ramesh@example.com'
        )
        self.item = JewelleryItem.objects.create(
            item_code='RN-001',
            name='22K Solitaire Ring',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            net_weight=Decimal('4.800'),
            selling_price=Decimal('45000.00'),
            status='Available'
        )

    # ---------------------------------------------------------
    # SALES TESTS
    # ---------------------------------------------------------
    def test_sale_creation_marks_item_as_sold(self):
        response = self.client.post(reverse('sale_add'), {
            'customer': self.customer.id,
            'jewellery_item': self.item.id,
            'sale_price': '45000.00',
            'payment_method': 'UPI',
            'notes': 'Test payment'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify sale was recorded
        sale = Sale.objects.filter(jewellery_item=self.item).first()
        self.assertIsNotNone(sale)
        self.assertEqual(sale.customer, self.customer)
        self.assertEqual(sale.sale_price, Decimal('45000.00'))

        # Verify jewellery item status is now 'Sold'
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'Sold')

    def test_selling_one_piece_does_not_affect_other_pieces_of_same_design(self):
        # Create piece 2 with the same design code
        piece2 = JewelleryItem.objects.create(
            item_code='RN-001-B',
            design_code=self.item.design_code,
            name='22K Solitaire Ring (Piece 2)',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.200'),
            net_weight=Decimal('5.000'),
            selling_price=Decimal('47000.00'),
            status='Available'
        )

        # Sell piece 1
        response = self.client.post(reverse('sale_add'), {
            'customer': self.customer.id,
            'jewellery_item': self.item.id,
            'sale_price': '45000.00',
            'payment_method': 'Cash',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        # Piece 1 is now Sold
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'Sold')

        # Piece 2 is STILL Available and unaffected
        piece2.refresh_from_db()
        self.assertEqual(piece2.status, 'Available')

        # Now sell Piece 2 to verify it can be sold independently
        response2 = self.client.post(reverse('sale_add'), {
            'customer': self.customer.id,
            'jewellery_item': piece2.id,
            'sale_price': '47000.00',
            'payment_method': 'UPI',
        }, follow=True)
        self.assertEqual(response2.status_code, 200)

        piece2.refresh_from_db()
        self.assertEqual(piece2.status, 'Sold')
        self.assertEqual(Sale.objects.filter(customer=self.customer).count(), 2)

    def test_cannot_sell_already_sold_item(self):
        # Set item as already sold
        self.item.status = 'Sold'
        self.item.save()

        response = self.client.post(reverse('sale_add'), {
            'customer': self.customer.id,
            'jewellery_item': self.item.id,
            'sale_price': '45000.00',
            'payment_method': 'Cash',
        }, follow=True)

        # Should not create another sale or succeed
        self.assertContains(response, 'already SOLD')
        self.assertEqual(Sale.objects.count(), 0)

    def test_sale_list_and_filter(self):
        sale = Sale.objects.create(
            customer=self.customer,
            jewellery_item=self.item,
            sale_price=Decimal('45000.00'),
            payment_method='UPI'
        )
        response = self.client.get(reverse('sale_list'), {'payment': 'UPI'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '#1' if sale.id == 1 else f'#{sale.id}')
        self.assertContains(response, 'Ramesh Kumar')

    def test_sale_detail_receipt_view(self):
        sale = Sale.objects.create(
            customer=self.customer,
            jewellery_item=self.item,
            sale_price=Decimal('45000.00'),
            payment_method='Card',
            notes='Invoice note'
        )
        response = self.client.get(reverse('sale_detail', kwargs={'pk': sale.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'sales/sale_detail.html')
        self.assertContains(response, 'INVOICE')
        self.assertContains(response, 'Ramesh Kumar')
        self.assertContains(response, '45000.00')

    # ---------------------------------------------------------
    # ENQUIRY TESTS
    # ---------------------------------------------------------
    def test_enquiry_creation_and_followup(self):
        today = timezone.localdate()
        response = self.client.post(reverse('enquiry_add'), {
            'customer': self.customer.id,
            'category': self.category.id,
            'interested_item': 'Antique Bridal Set',
            'budget': '350000.00',
            'status': 'New',
            'next_followup_date': str(today),
            'notes': 'Looking for wedding next month'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        enquiry = Enquiry.objects.filter(customer=self.customer).first()
        self.assertIsNotNone(enquiry)
        self.assertEqual(enquiry.interested_item, 'Antique Bridal Set')

    def test_enquiry_list_filters(self):
        today = timezone.localdate()
        # Today's enquiry
        Enquiry.objects.create(
            customer=self.customer,
            category=self.category,
            interested_item='Item Today',
            status='New',
            next_followup_date=today
        )
        # Upcoming enquiry
        Enquiry.objects.create(
            customer=self.customer,
            category=self.category,
            interested_item='Item Upcoming',
            status='Contacted',
            next_followup_date=today + timedelta(days=5)
        )

        # Filter today
        resp_today = self.client.get(reverse('enquiry_list'), {'followup': 'today'})
        self.assertEqual(resp_today.status_code, 200)
        self.assertContains(resp_today, 'Item Today')
        self.assertNotContains(resp_today, 'Item Upcoming')

        # Filter upcoming
        resp_up = self.client.get(reverse('enquiry_list'), {'followup': 'upcoming'})
        self.assertEqual(resp_up.status_code, 200)
        self.assertContains(resp_up, 'Item Upcoming')
        self.assertNotContains(resp_up, 'Item Today')

    def test_enquiry_edit_view(self):
        enquiry = Enquiry.objects.create(
            customer=self.customer,
            category=self.category,
            interested_item='Gold Coin',
            status='New'
        )
        response = self.client.post(reverse('enquiry_edit', kwargs={'pk': enquiry.pk}), {
            'customer': self.customer.id,
            'category': self.category.id,
            'interested_item': 'Gold Coin (Updated)',
            'status': 'Purchased',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.interested_item, 'Gold Coin (Updated)')
        self.assertEqual(enquiry.status, 'Purchased')

    def test_enquiry_delete_view(self):
        enquiry = Enquiry.objects.create(
            customer=self.customer,
            category=self.category,
            interested_item='Silver Glass',
            status='Closed'
        )
        response = self.client.post(reverse('enquiry_delete', kwargs={'pk': enquiry.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Enquiry.objects.filter(pk=enquiry.pk).exists())


# ==============================================================================
# SALES REPORT TESTS
# ==============================================================================

class SalesReportTests(TestCase):
    """Tests for the protected sales report page."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='reporter', password='Password123')

        self.category = Category.objects.create(name='Report Rings', description='Report gold rings')
        self.customer = Customer.objects.create(
            name='Report Customer',
            mobile='+91 9000000001',
            email='report@example.com',
        )

        self.sale_date_one = timezone.now() - timedelta(days=20)
        self.sale_date_two = timezone.now() - timedelta(days=5)

        self.item_one = JewelleryItem.objects.create(
            item_code='RPT-001',
            design_code='DSN-RPT-001',
            name='Report Ring One',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            net_weight=Decimal('4.800'),
            selling_price=Decimal('30000.00'),
            status='Available',
        )
        self.item_two = JewelleryItem.objects.create(
            item_code='RPT-002',
            design_code='DSN-RPT-002',
            name='Report Ring Two',
            category=self.category,
            metal_type='Silver',
            purity='925',
            gross_weight=Decimal('6.000'),
            net_weight=Decimal('5.500'),
            selling_price=Decimal('50000.00'),
            status='Available',
        )
        self.sale_one = Sale.objects.create(
            customer=self.customer,
            jewellery_item=self.item_one,
            sale_price=Decimal('30000.00'),
            sale_date=self.sale_date_one,
            payment_method='Cash',
        )
        self.sale_two = Sale.objects.create(
            customer=self.customer,
            jewellery_item=self.item_two,
            sale_price=Decimal('50000.00'),
            sale_date=self.sale_date_two,
            payment_method='UPI',
        )

    def report_url(self, **params):
        base_url = reverse('sales_report')
        if not params:
            return base_url
        query = '&'.join(f'{key}={value}' for key, value in params.items())
        return f'{base_url}?{query}'

    # REPORT_TESTS_PART2

    def test_report_requires_login(self):
        response = self.client.get(reverse('sales_report'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_report_renders_for_authenticated_user(self):
        self.client.login(username='reporter', password='Password123')
        response = self.client.get(reverse('sales_report'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'sales/sales_report.html')
        self.assertContains(response, 'Sales Report')

    def test_today_filter_includes_only_today_sales(self):
        self.client.login(username='reporter', password='Password123')
        self.sale_one.sale_date = timezone.now()
        self.sale_one.save()

        response = self.client.get(reverse('sales_report'), {'period': 'today'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sales_count'], 1)
        self.assertEqual(response.context['total_amount'], Decimal('30000.00'))
        self.assertEqual(response.context['items_sold'], 1)
        self.assertEqual(response.context['average_sale_value'], Decimal('30000.00'))
        self.assertContains(response, 'RPT-001')
        self.assertNotContains(response, 'RPT-002')

    def test_this_month_filter_includes_current_month_sales(self):
        self.client.login(username='reporter', password='Password123')
        self.sale_one.sale_date = timezone.now().replace(day=1, hour=10)
        self.sale_one.save()
        self.sale_two.sale_date = timezone.now()
        self.sale_two.save()

        response = self.client.get(reverse('sales_report'), {'period': 'month'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sales_count'], 2)
        self.assertEqual(response.context['total_amount'], Decimal('80000.00'))
        self.assertEqual(response.context['items_sold'], 2)
        self.assertEqual(response.context['average_sale_value'], Decimal('40000.00'))

    # REPORT_TESTS_PART3

    def test_custom_date_range_filters_sales(self):
        self.client.login(username='reporter', password='Password123')
        start = (self.sale_date_one - timedelta(days=2)).date().isoformat()
        end = (self.sale_date_one + timedelta(days=2)).date().isoformat()

        response = self.client.get(reverse('sales_report'), {
            'period': 'custom',
            'start_date': start,
            'end_date': end,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sales_count'], 1)
        self.assertEqual(response.context['total_amount'], Decimal('30000.00'))
        self.assertEqual(response.context['items_sold'], 1)
        self.assertEqual(response.context['average_sale_value'], Decimal('30000.00'))
        self.assertContains(response, 'RPT-001')
        self.assertNotContains(response, 'RPT-002')

    def test_custom_range_accepts_reversed_dates(self):
        self.client.login(username='reporter', password='Password123')
        start = (self.sale_date_one - timedelta(days=2)).date().isoformat()
        end = (self.sale_date_one + timedelta(days=2)).date().isoformat()

        response = self.client.get(reverse('sales_report'), {
            'period': 'custom',
            'start_date': end,
            'end_date': start,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sales_count'], 1)
        self.assertEqual(response.context['total_amount'], Decimal('30000.00'))

    def test_invalid_custom_range_redirects_with_message(self):
        self.client.login(username='reporter', password='Password123')
        response = self.client.get(self.report_url(
            period='custom',
            start_date='not-a-date',
            end_date='',
        ))

        self.assertRedirects(response, reverse('sales_report'), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse('sales_report')), 'valid custom date range')

    # REPORT_TESTS_PART4

    def test_correct_totals_for_sales_in_range(self):
        self.client.login(username='reporter', password='Password123')
        start = (self.sale_date_two - timedelta(days=2)).date().isoformat()
        end = timezone.localdate().isoformat()

        response = self.client.get(reverse('sales_report'), {
            'period': 'custom',
            'start_date': start,
            'end_date': end,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sales_count'], 1)
        self.assertEqual(response.context['total_amount'], Decimal('50000.00'))
        self.assertEqual(response.context['items_sold'], 1)
        self.assertEqual(response.context['average_sale_value'], Decimal('50000.00'))

    def test_report_shows_item_and_customer_details(self):
        self.client.login(username='reporter', password='Password123')
        start = (self.sale_date_two - timedelta(days=2)).date().isoformat()
        end = timezone.localdate().isoformat()

        response = self.client.get(reverse('sales_report'), {
            'period': 'custom',
            'start_date': start,
            'end_date': end,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Report Customer')
        self.assertContains(response, '+91 9000000001')
        self.assertContains(response, 'Report Ring Two')
        self.assertContains(response, 'RPT-002')
        self.assertContains(response, 'DSN-RPT-002')
        self.assertContains(response, 'Silver')
        self.assertContains(response, '50000.00')
        self.assertContains(response, 'UPI')

    def test_empty_date_range_shows_zero_totals(self):
        self.client.login(username='reporter', password='Password123')
        start = (timezone.localdate() - timedelta(days=365)).isoformat()
        end = (timezone.localdate() - timedelta(days=300)).isoformat()

        response = self.client.get(reverse('sales_report'), {
            'period': 'custom',
            'start_date': start,
            'end_date': end,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sales_count'], 0)
        self.assertEqual(response.context['items_sold'], 0)
        self.assertEqual(response.context['total_amount'], Decimal('0.00'))
        self.assertEqual(response.context['average_sale_value'], Decimal('0.00'))
        self.assertContains(response, 'No sales recorded for the selected date range.')


class WhatsAppHelperTests(TestCase):
    """Unit tests for the WhatsApp click-to-chat helpers (Phase 1)."""

    def setUp(self):
        self.category = Category.objects.create(name='Rings')
        self.customer = Customer.objects.create(
            name='Ramesh Kumar', mobile='+91 9888877777')
        self.item = JewelleryItem.objects.create(
            item_code='WA-RING-001',
            name='22K Solitaire Ring',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.000'),
            net_weight=Decimal('4.800'),
            selling_price=Decimal('45000.00'),
            status='Available',
        )

    def test_indian_10_digit_number_gets_country_code(self):
        from sales.whatsapp import normalize_phone
        self.assertEqual(normalize_phone('9876543210'), '919876543210')
        self.assertEqual(normalize_phone('98888 77777'), '919888877777')
        self.assertEqual(normalize_phone('6123456789'), '916123456789')

    def test_number_with_punctuation_is_stripped(self):
        from sales.whatsapp import normalize_phone
        self.assertEqual(normalize_phone('+91 98888 77777'), '919888877777')
        self.assertEqual(normalize_phone('+91-98765-43210'), '919876543210')

    def test_trunk_prefix_zero_is_dropped(self):
        from sales.whatsapp import normalize_phone
        self.assertEqual(normalize_phone('09876543210'), '919876543210')

    def test_already_country_coded_number_untouched(self):
        from sales.whatsapp import normalize_phone
        self.assertEqual(normalize_phone('919876543210'), '919876543210')
        self.assertEqual(normalize_phone('+441234567890'), '441234567890')

    def test_invalid_or_missing_numbers_return_none(self):
        from sales.whatsapp import normalize_phone
        self.assertIsNone(normalize_phone(''))
        self.assertIsNone(normalize_phone(None))
        self.assertIsNone(normalize_phone('12345'))
        self.assertIsNone(normalize_phone('not-a-phone'))
        self.assertIsNone(normalize_phone('000987654321'))

    def test_message_contains_required_details(self):
        from sales.whatsapp import build_thank_you_message, SHOP_NAME
        message = build_thank_you_message(
            'Ramesh Kumar', '22K Solitaire Ring', 'INV-00001')
        self.assertIn('Ramesh Kumar', message)
        self.assertIn('22K Solitaire Ring', message)
        self.assertIn('INV-00001', message)
        self.assertIn('Thank you', message)
        self.assertIn(SHOP_NAME, message)

    def test_url_generation_and_encoding(self):
        from urllib.parse import unquote, urlparse, parse_qs
        from sales.whatsapp import build_whatsapp_url
        url = build_whatsapp_url('9876543210', 'Thank you & enjoy!')
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, 'https')
        self.assertEqual(parsed.netloc, 'wa.me')
        self.assertEqual(parsed.path.lstrip('/'), '919876543210')
        self.assertEqual(parse_qs(parsed.query)['text'], ['Thank you & enjoy!'])
        self.assertNotIn(' ', url)
        self.assertIsNone(build_whatsapp_url('', 'hello'))

    def test_context_for_sale_with_valid_number(self):
        from sales.whatsapp import get_whatsapp_context_for_sale
        sale = Sale.objects.create(
            customer=self.customer,
            jewellery_item=self.item,
            sale_price=Decimal('45000.00'),
        )
        ctx = get_whatsapp_context_for_sale(sale)
        self.assertIn('whatsapp_url', ctx)
        self.assertIn('wa.me/919888877777?text=', ctx['whatsapp_url'])
        self.assertIn('text=', ctx['whatsapp_url'])
        self.assertEqual(ctx['whatsapp_customer_name'], 'Ramesh Kumar')
        self.assertNotIn('whatsapp_unavailable', ctx)

    def test_context_for_sale_without_valid_number(self):
        from sales.whatsapp import get_whatsapp_context_for_sale
        self.customer.mobile = '12'
        self.customer.save()
        sale = Sale.objects.create(
            customer=self.customer,
            jewellery_item=self.item,
            sale_price=Decimal('45000.00'),
        )
        ctx = get_whatsapp_context_for_sale(sale)
        self.assertTrue(ctx.get('whatsapp_unavailable'))
        self.assertNotIn('whatsapp_url', ctx)

# __WA_END__

class WhatsAppSaleDetailTests(TestCase):
    """WhatsApp button visibility on the sale detail/invoice page."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='wastaff', password='Password123')
        self.client.login(username='wastaff', password='Password123')
        self.category = Category.objects.create(name='Chains')
        self.customer = Customer.objects.create(
            name='WhatsApp Customer', mobile='9876500000')
        self.item = JewelleryItem.objects.create(
            item_code='WA-CHAIN-001',
            name='22K Rope Chain',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('12.000'),
            net_weight=Decimal('11.500'),
            selling_price=Decimal('82000.00'),
            status='Available',
        )
        self.sale = Sale.objects.create(
            customer=self.customer,
            jewellery_item=self.item,
            sale_price=Decimal('82000.00'),
            payment_method='UPI',
        )

    def test_detail_page_shows_whatsapp_button(self):
        response = self.client.get(
            reverse('sale_detail', args=[self.sale.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Send WhatsApp Thank You')
        self.assertContains(response, 'wa.me/919876500000')
        self.assertContains(response, 'target="_blank"')
        self.assertIn('whatsapp_url', response.context)

    def test_detail_page_shows_unavailable_state_for_bad_number(self):
        self.customer.mobile = '123'
        self.customer.save()
        response = self.client.get(
            reverse('sale_detail', args=[self.sale.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'wa.me/')
        self.assertContains(response, 'Send WhatsApp Thank You')
        self.assertTrue(response.context.get('whatsapp_unavailable'))
        self.assertNotIn('whatsapp_url', response.context)

    def test_detail_page_unauthenticated_redirects(self):
        self.client.logout()
        response = self.client.get(
            reverse('sale_detail', args=[self.sale.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)


class InvoicePdfTests(TestCase):
    """PDF invoice download endpoint tests."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='pdfuser', password='Password123')
        self.client.login(username='pdfuser', password='Password123')
        self.category = Category.objects.create(name='Chains')
        self.customer = Customer.objects.create(
            name='PDF Customer', mobile='+91 9876500011',
            email='pdf@example.com', address='12 MG Road, Mumbai')
        self.item = JewelleryItem.objects.create(
            item_code='CH-PDF-01', name='PDF Gold Chain',
            category=self.category, metal_type='Gold', purity='22K',
            gross_weight=Decimal('10.000'), net_weight=Decimal('9.500'),
            selling_price=Decimal('55000.00'), status='Available')
        self.sale = Sale.objects.create(
            customer=self.customer, jewellery_item=self.item,
            sale_price=Decimal('55000.00'), payment_method='UPI')
        self.url = reverse('sale_invoice_pdf', args=[self.sale.pk])

    def test_authenticated_user_can_download_invoice_pdf(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content), 1000)

    def test_response_is_pdf(self):
        response = self.client.get(self.url)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_filename_is_invoice_number(self):
        response = self.client.get(self.url)
        self.assertEqual(
            response['Content-Disposition'],
            f'attachment; filename="INV-{self.sale.pk:05d}.pdf"')

    def test_invoice_contains_sale_and_customer_data(self):
        # pageCompression=0 keeps text readable in the raw bytes.
        response = self.client.get(self.url)
        pdf_text = response.content
        self.assertIn(b'PDF Customer', pdf_text)
        self.assertIn(b'PDF Gold Chain', pdf_text)
        self.assertIn(f'INV-{self.sale.pk:05d}'.encode(), pdf_text)
        self.assertIn(b'55,000.00', pdf_text)
        self.assertIn(b'TAX INVOICE', pdf_text)
        self.assertIn(b'12 MG Road, Mumbai', pdf_text)

    def test_invoice_uses_company_settings_values(self):
        from accounts.models import CompanySettings
        settings_obj = CompanySettings.load()
        settings_obj.company_name = 'Shree Jewellers Test'
        settings_obj.gstin = '27ABCDE1234F1Z5'
        settings_obj.save()
        response = self.client.get(self.url)
        self.assertIn(b'Shree Jewellers Test', response.content)
        self.assertIn(b'27ABCDE1234F1Z5', response.content)

    def test_invoice_generates_without_company_settings(self):
        from accounts.models import CompanySettings
        CompanySettings.objects.all().delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn(b'PDF Customer', response.content)

    def test_unauthenticated_pdf_access_blocked(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)
class PaymentTests(TestCase):
    """Payments & Outstanding Phase 1: statuses, validation, outstanding."""

    def setUp(self):
        self.user = User.objects.create_user(username='paydesk', password='Password123')
        self.client.login(username='paydesk', password='Password123')
        self.customer = Customer.objects.create(name='Riya Shah', mobile='+91 9333344444')
        cat = Category.objects.create(name='Rings')
        self.item = JewelleryItem.objects.create(
            item_code='RG-101', name='Diamond Ring', category=cat,
            metal_type='Gold', purity='18K',
            gross_weight=Decimal('6.500'), net_weight=Decimal('6.200'),
            selling_price=Decimal('50000.00'))
        self.sale = Sale.objects.create(
            customer=self.customer, jewellery_item=self.item,
            sale_price=Decimal('50000.00'))

    def _pay(self, amount, method='Cash', reference='', payment_date=None):
        kwargs = {'payment_date': payment_date} if payment_date else {}
        return Payment.objects.create(
            sale=self.sale, amount=Decimal(str(amount)),
            payment_method=method, reference=reference, **kwargs)

    def test_unpaid_sale(self):
        self.assertEqual(self.sale.paid_amount, 0)
        self.assertEqual(self.sale.due_amount, Decimal('50000.00'))
        self.assertEqual(self.sale.payment_status, 'Unpaid')

    def test_partially_paid_sale(self):
        self._pay('20000', method='UPI', reference='UPI-20K')
        self.assertEqual(self.sale.paid_amount, Decimal('20000'))
        self.assertEqual(self.sale.due_amount, Decimal('30000'))
        self.assertEqual(self.sale.payment_status, 'Partially Paid')

    def test_fully_paid_sale(self):
        self._pay('50000', method='UPI')
        self.assertEqual(self.sale.due_amount, 0)
        self.assertEqual(self.sale.payment_status, 'Paid')

    def test_multiple_payments_correct_remaining(self):
        self._pay('20000', method='UPI')
        self._pay('30000', method='Bank Transfer')
        self.assertEqual(Payment.objects.filter(sale=self.sale).count(), 2)
        self.assertEqual(self.sale.paid_amount, Decimal('50000'))
        self.assertEqual(self.sale.due_amount, 0)
        self.assertEqual(self.sale.payment_status, 'Paid')

    def test_reject_zero_and_negative_payment(self):
        from django.core.exceptions import ValidationError
        for bad in (Decimal('0'), Decimal('-100')):
            with self.assertRaises(ValidationError):
                Payment(sale=self.sale, amount=bad, payment_method='Cash').full_clean()

    def test_reject_payment_above_remaining_due(self):
        from django.core.exceptions import ValidationError
        self._pay('20000')
        with self.assertRaises(ValidationError):
            Payment(sale=self.sale, amount=Decimal('30000.01'), payment_method='Cash').full_clean()
        # Exactly the remaining due is allowed.
        Payment(sale=self.sale, amount=Decimal('30000'), payment_method='UPI').full_clean()

    def test_payment_form_validation(self):
        from sales.forms import PaymentForm
        zero = PaymentForm({'amount': '0', 'payment_method': 'Cash'}, sale=self.sale)
        self.assertFalse(zero.is_valid())
        self.assertIn('amount', zero.errors)
        over = PaymentForm({'amount': '50000.01', 'payment_method': 'Cash'}, sale=self.sale)
        self.assertFalse(over.is_valid())
        ok = PaymentForm({'amount': '20000', 'payment_method': 'UPI'}, sale=self.sale)
        self.assertTrue(ok.is_valid())
        self._pay('40000')
        over2 = PaymentForm({'amount': '15000', 'payment_method': 'Cash'}, sale=self.sale)
        self.assertFalse(over2.is_valid())

    def test_payment_method_choices(self):
        methods = dict(Payment.PAYMENT_METHODS)
        for m in ('Cash', 'UPI', 'Card', 'Bank Transfer', 'Cheque'):
            self.assertIn(m, methods)
        Payment(sale=self.sale, amount=Decimal('1000'), payment_method='Cheque').full_clean()

    def test_payment_history_newest_first(self):
        import datetime as dt
        from django.utils import timezone
        self._pay('1000', reference='OLD-REF', payment_date=timezone.now() - dt.timedelta(days=2))
        self._pay('2000', reference='NEW-REF', payment_date=timezone.now())
        refs = [p.reference for p in self.sale.payments.all()]
        self.assertEqual(refs, ['NEW-REF', 'OLD-REF'])

    def test_customer_outstanding_calculation(self):
        self._pay('20000')
        self.assertEqual(self.customer.total_purchases_amount, Decimal('50000'))
        self.assertEqual(self.customer.total_paid_amount, Decimal('20000'))
        self.assertEqual(self.customer.outstanding_amount, Decimal('30000'))
        self._pay('30000')
        self.assertEqual(self.customer.outstanding_amount, 0)

    # ---- View / template integration ----

    def test_sale_detail_shows_payment_summary_and_history(self):
        self._pay('20000', method='UPI', reference='UPI-REF-1', payment_date=None)
        response = self.client.get(
            reverse('sale_detail', kwargs={'pk': self.sale.pk}))
        self.assertEqual(response.status_code, 200)
        # Summary labels
        self.assertContains(response, 'Total Amount')
        self.assertContains(response, 'Paid Amount')
        self.assertContains(response, 'Due Amount')
        # Status after partial payment
        self.assertContains(response, 'Partially Paid')
        # Payment history row (reference visible, newest easy to find)
        self.assertContains(response, 'UPI-REF-1')
        # Add Payment action available while due > 0
        self.assertContains(response, 'Add Payment')
        self.assertContains(response, 'Payment History')

    def test_sale_detail_hides_add_payment_when_fully_paid(self):
        self._pay('50000', method='UPI')
        response = self.client.get(
            reverse('sale_detail', kwargs={'pk': self.sale.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sale'].payment_status, 'Paid')
        # Button + modal only render when there is a due amount.
        self.assertNotContains(response, 'Add Payment')

    def test_add_payment_via_view_success(self):
        response = self.client.post(
            reverse('payment_add', kwargs={'pk': self.sale.pk}),
            {'amount': '20000', 'payment_method': 'UPI',
             'reference': 'UPI-VIEW-1', 'notes': 'Part payment'})
        self.assertRedirects(
            response, reverse('sale_detail', kwargs={'pk': self.sale.pk}))
        self.assertEqual(Payment.objects.filter(sale=self.sale).count(), 1)
        self.assertEqual(self.sale.paid_amount, Decimal('20000'))
        self.assertEqual(self.sale.payment_status, 'Partially Paid')

    def test_add_payment_rejects_overpayment_via_view(self):
        self._pay('20000')
        response = self.client.post(
            reverse('payment_add', kwargs={'pk': self.sale.pk}),
            {'amount': '40000', 'payment_method': 'Cash'})
        # View redirects back with an error message; nothing is saved.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.filter(sale=self.sale).count(), 1)
        self.assertEqual(self.sale.paid_amount, Decimal('20000'))

    def test_add_payment_requires_login(self):
        self.client.logout()
        response = self.client.post(
            reverse('payment_add', kwargs={'pk': self.sale.pk}),
            {'amount': '1000', 'payment_method': 'Cash'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_sales_list_shows_payment_status_badge(self):
        response = self.client.get(reverse('sale_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Unpaid')
        self._pay('50000', method='UPI')
        response = self.client.get(reverse('sale_list'))
        self.assertContains(response, 'Paid')

    def test_invoice_pdf_shows_paid_and_due(self):
        self._pay('20000', method='UPI')
        response = self.client.get(
            reverse('sale_invoice_pdf', kwargs={'pk': self.sale.pk}))
        self.assertEqual(response.status_code, 200)
        body = response.content
        self.assertIn(b'Paid', body)
        self.assertIn(b'Due', body)


class OldGoldTransactionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='sales_rep', password='Password123')
        self.client.login(username='sales_rep', password='Password123')

        self.category = Category.objects.create(name='Necklaces', description='Gold Necklaces')
        self.customer = Customer.objects.create(
            name='Priya Sharma',
            mobile='+91 9123456780',
            email='priya@example.com'
        )
        self.available_item = JewelleryItem.objects.create(
            item_code='NK-001',
            tag_number='JWL-000099',
            name='22K Heritage Gold Necklace',
            category=self.category,
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('15.000'),
            net_weight=Decimal('14.500'),
            selling_price=Decimal('120000.00'),
            quantity=1,
            status='Available'
        )

    def test_valuation_formula_24k(self):
        val = OldGoldTransaction.compute_valuation(
            gross_weight=Decimal('10.000'),
            stone_weight=Decimal('0.000'),
            metal_type='Gold',
            purity='24K',
            applicable_rate=Decimal('7500.00'),
            deduction_percent=Decimal('0.00')
        )
        self.assertEqual(val['net_weight'], Decimal('10.000'))
        self.assertEqual(val['purity_factor'], Decimal('1.000000'))
        self.assertEqual(val['effective_rate'], Decimal('7500.00'))
        self.assertEqual(val['gross_valuation'], Decimal('75000.00'))
        self.assertEqual(val['deduction_amount'], Decimal('0.00'))
        self.assertEqual(val['final_value'], Decimal('75000.00'))

    def test_valuation_formula_22k_with_stone_and_deduction(self):
        val = OldGoldTransaction.compute_valuation(
            gross_weight=Decimal('10.000'),
            stone_weight=Decimal('1.000'),
            metal_type='Gold',
            purity='22K',
            applicable_rate=Decimal('7200.00'),
            deduction_percent=Decimal('2.00')
        )
        # Net weight = 10 - 1 = 9g
        self.assertEqual(val['net_weight'], Decimal('9.000'))
        # 22/24 purity factor: 7200 * 22/24 = 6600.00
        self.assertEqual(val['effective_rate'], Decimal('6600.00'))
        # 9g * 6600 = 59400.00
        self.assertEqual(val['gross_valuation'], Decimal('59400.00'))
        # 2% deduction = 1188.00
        self.assertEqual(val['deduction_amount'], Decimal('1188.00'))
        # Final value = 59400 - 1188 = 58212.00
        self.assertEqual(val['final_value'], Decimal('58212.00'))

    def test_valuation_formula_18k(self):
        val = OldGoldTransaction.compute_valuation(
            gross_weight=Decimal('8.000'),
            stone_weight=Decimal('0.000'),
            metal_type='Gold',
            purity='18K',
            applicable_rate=Decimal('8000.00'),
            deduction_percent=Decimal('3.00')
        )
        # 18/24 = 0.75 * 8000 = 6000.00/g
        self.assertEqual(val['effective_rate'], Decimal('6000.00'))
        # 8g * 6000 = 48000.00
        self.assertEqual(val['gross_valuation'], Decimal('48000.00'))
        # 3% of 48000 = 1440.00
        self.assertEqual(val['deduction_amount'], Decimal('1440.00'))
        self.assertEqual(val['final_value'], Decimal('46560.00'))

    def test_valuation_formula_custom_purity(self):
        val = OldGoldTransaction.compute_valuation(
            gross_weight=Decimal('5.000'),
            stone_weight=Decimal('0.000'),
            metal_type='Gold',
            purity='Other',
            custom_purity_percent=Decimal('80.00'),
            applicable_rate=Decimal('7000.00'),
            deduction_percent=Decimal('0.00')
        )
        self.assertEqual(val['purity_factor'], Decimal('0.800000'))
        self.assertEqual(val['effective_rate'], Decimal('5600.00'))
        self.assertEqual(val['final_value'], Decimal('28000.00'))

    def test_model_validation_errors(self):
        # Gross weight <= 0
        tx = OldGoldTransaction(
            transaction_number='OG-TEST-1',
            customer=self.customer,
            gross_weight=Decimal('0.000'),
            stone_weight=Decimal('0.000'),
            net_weight=Decimal('0.000'),
            applicable_rate=Decimal('7000.00'),
            effective_rate=Decimal('6400.00'),
            gross_valuation=Decimal('0.00'),
            final_value=Decimal('0.00')
        )
        with self.assertRaises(ValidationError):
            tx.clean()

        # Stone weight >= gross weight
        tx.gross_weight = Decimal('5.000')
        tx.stone_weight = Decimal('5.000')
        with self.assertRaises(ValidationError):
            tx.clean()

    def test_exchange_creation_workflow(self):
        """Old gold exchange against new necklace item."""
        response = self.client.post(reverse('old_gold_exchange_create'), {
            'customer': self.customer.id,
            'metal_type': 'Gold',
            'old_gold_type': 'Broken Jewellery',
            'item_description': 'Old 22K bangles (2 pcs broken)',
            'gross_weight': '10.000',
            'stone_weight': '1.000',
            'purity': '22K',
            'applicable_rate': '7200.00',
            'deduction_percent': '2.00',
            'new_jewellery_item': self.available_item.id,
            'new_sale_price': '120000.00',
            'settlement_payment_method': 'UPI',
            'settlement_payment_reference': 'UPI-REF-998877',
            'notes': 'Test exchange'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        # 1. OldGoldTransaction created
        tx = OldGoldTransaction.objects.filter(customer=self.customer, transaction_type='Exchange').first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.net_weight, Decimal('9.000'))
        self.assertEqual(tx.final_value, Decimal('58212.00'))
        self.assertEqual(tx.inventory_status, 'Vault Stock')
        self.assertTrue(tx.transaction_number.startswith('OGX-'))

        # 2. Sale created for new necklace
        sale = tx.new_sale
        self.assertIsNotNone(sale)
        self.assertEqual(sale.jewellery_item, self.available_item)
        self.assertEqual(sale.sale_price, Decimal('120000.00'))

        # 3. Piece status marked Sold and inventory stock decremented
        self.available_item.refresh_from_db()
        self.assertEqual(self.available_item.status, 'Sold')
        self.assertEqual(self.available_item.quantity, 0)

        # 4. Exchange payment credited and UPI settlement payment recorded
        payments = sale.payments.all()
        self.assertEqual(payments.count(), 2)

        exchange_payment = payments.filter(payment_method='Exchange').first()
        self.assertIsNotNone(exchange_payment)
        self.assertEqual(exchange_payment.amount, Decimal('58212.00'))

        upi_payment = payments.filter(payment_method='UPI').first()
        self.assertIsNotNone(upi_payment)
        self.assertEqual(upi_payment.amount, Decimal('61788.00'))  # 120,000 - 58,212

        # 5. Sale is fully paid
        self.assertEqual(sale.paid_amount, Decimal('120000.00'))
        self.assertEqual(sale.due_amount, Decimal('0.00'))
        self.assertEqual(sale.payment_status, 'Paid')

    def test_exchange_where_old_gold_exceeds_new_item_price(self):
        """Old gold value (e.g. 58,212) > New Ring price (e.g. 40,000)."""
        cheap_ring = JewelleryItem.objects.create(
            item_code='RN-CHEAP',
            name='Simple 18K Band',
            category=self.category,
            metal_type='Gold',
            purity='18K',
            gross_weight=Decimal('3.000'),
            net_weight=Decimal('3.000'),
            selling_price=Decimal('40000.00'),
            quantity=1,
            status='Available'
        )

        response = self.client.post(reverse('old_gold_exchange_create'), {
            'customer': self.customer.id,
            'metal_type': 'Gold',
            'old_gold_type': 'Coins / Bullion',
            'item_description': '22K Gold Coin 10g',
            'gross_weight': '10.000',
            'stone_weight': '1.000',
            'purity': '22K',
            'applicable_rate': '7200.00',
            'deduction_percent': '2.00',
            'new_jewellery_item': cheap_ring.id,
            'new_sale_price': '40000.00',
            'notes': 'Exchange with refund due'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        tx = OldGoldTransaction.objects.filter(customer=self.customer, new_sale__jewellery_item=cheap_ring).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.final_value, Decimal('58212.00'))
        self.assertEqual(tx.difference_amount, Decimal('-18212.00'))
        self.assertEqual(tx.customer_refund, Decimal('18212.00'))
        self.assertEqual(tx.customer_payable, Decimal('0.00'))

        # Sale paid_amount is capped at 40000 without overpayment error
        sale = tx.new_sale
        self.assertEqual(sale.paid_amount, Decimal('40000.00'))
        self.assertEqual(sale.due_amount, Decimal('0.00'))
        self.assertEqual(sale.payment_status, 'Paid')

    def test_buyback_creation_workflow(self):
        """Outright buyback with cash payout."""
        response = self.client.post(reverse('old_gold_buyback_create'), {
            'customer': self.customer.id,
            'metal_type': 'Gold',
            'old_gold_type': 'Old Jewellery',
            'item_description': 'Old broken chain and earring',
            'gross_weight': '5.000',
            'stone_weight': '0.500',
            'purity': '22K',
            'applicable_rate': '7200.00',
            'deduction_percent': '1.00',
            'payment_method': 'Cash',
            'payment_status': 'Paid',
            'payment_reference': 'CASH-VOUCHER-01',
            'notes': 'Scrap purchase'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        tx = OldGoldTransaction.objects.filter(customer=self.customer, transaction_type='Buyback').first()
        self.assertIsNotNone(tx)
        self.assertTrue(tx.transaction_number.startswith('OGB-'))
        self.assertEqual(tx.inventory_status, 'Vault Stock')
        # Net wt = 4.5g, effective rate = 6600, gross = 29700, 1% ded = 297 -> 29403
        self.assertEqual(tx.net_weight, Decimal('4.500'))
        self.assertEqual(tx.final_value, Decimal('29403.00'))
        self.assertEqual(tx.payment_method, 'Cash')
        self.assertEqual(tx.payment_status, 'Paid')

        # Verify showroom inventory is NOT contaminated with scrap
        self.assertFalse(JewelleryItem.objects.filter(name__icontains='broken chain').exists())

    def test_sequential_number_generation(self):
        num1 = generate_old_gold_number('Exchange')
        OldGoldTransaction.objects.create(
            transaction_number=num1,
            transaction_type='Exchange',
            customer=self.customer,
            gross_weight=Decimal('1.000'),
            net_weight=Decimal('1.000'),
            applicable_rate=Decimal('7000.00'),
            effective_rate=Decimal('6400.00'),
            gross_valuation=Decimal('6400.00'),
            final_value=Decimal('6400.00')
        )
        num2 = generate_old_gold_number('Exchange')
        self.assertEqual(num1, 'OGX-00001')
        self.assertEqual(num2, 'OGX-00002')

    def test_cancellation_preserves_audit_trail(self):
        tx = OldGoldTransaction.objects.create(
            transaction_number='OGX-AUDIT-1',
            transaction_type='Exchange',
            customer=self.customer,
            gross_weight=Decimal('5.000'),
            net_weight=Decimal('5.000'),
            applicable_rate=Decimal('7000.00'),
            effective_rate=Decimal('6400.00'),
            gross_valuation=Decimal('32000.00'),
            final_value=Decimal('32000.00')
        )

        response = self.client.post(reverse('old_gold_cancel', kwargs={'pk': tx.pk}), {
            'cancellation_reason': 'Customer changed mind and took back gold'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        tx.refresh_from_db()
        self.assertEqual(tx.status, 'Cancelled')
        self.assertEqual(tx.cancelled_by, self.user)
        self.assertIsNotNone(tx.cancelled_at)
        self.assertIn('Customer changed mind', tx.cancellation_reason)

    def test_rate_api_endpoint(self):
        response = self.client.get(reverse('old_gold_rate_api'), {
            'metal_type': 'Gold',
            'purity': '18K'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['purity'], '18K')
        self.assertAlmostEqual(data['purity_factor'], 0.75, places=2)
        self.assertGreater(data['effective_rate'], 0)

    def test_sales_report_preserves_normal_sales_totals(self):
        # Create normal sale
        sale = Sale.objects.create(
            customer=self.customer,
            jewellery_item=self.available_item,
            sale_price=Decimal('120000.00'),
            payment_method='Cash'
        )

        # Create buyback
        OldGoldTransaction.objects.create(
            transaction_number='OGB-REP-1',
            transaction_type='Buyback',
            customer=self.customer,
            gross_weight=Decimal('10.000'),
            net_weight=Decimal('10.000'),
            applicable_rate=Decimal('7000.00'),
            effective_rate=Decimal('6400.00'),
            gross_valuation=Decimal('64000.00'),
            final_value=Decimal('64000.00')
        )

        response = self.client.get(reverse('sales_report'), {'period': 'today'})
        self.assertEqual(response.status_code, 200)
        # Normal sales totals MUST remain uncorrupted
        self.assertEqual(response.context['total_amount'], Decimal('120000.00'))
        self.assertEqual(response.context['sales_count'], 1)
        # Old gold buyback is tracked in separate dedicated metrics
        self.assertEqual(response.context['buyback_count'], 1)
        self.assertEqual(response.context['buyback_payout'], Decimal('64000.00'))

    def test_permissions_unauthorized_access(self):
        # Create an employee with no sales permissions
        unauth_user = User.objects.create_user(username='hr_rep', password='Password123')
        role, _ = Role.objects.get_or_create(name='HR')
        emp = Employee.objects.create(
            user=unauth_user,
            employee_id='EMP-9999',
            full_name='HR Staff',
            email='hr@example.com',
            mobile='+91 9000000001',
            designation='HR Assistant',
            role=role,
            status=Employee.STATUS_ACTIVE
        )
        EmployeePermission.objects.create(
            employee=emp,
            module='sales',
            can_view=False,
            can_add=False,
            can_edit=False,
            can_delete=False
        )

        # Login as unauth_user
        self.client.login(username='hr_rep', password='Password123')

        # Accessing old gold list should return HTTP 403 Forbidden
        response = self.client.get(reverse('old_gold_list'))
        self.assertEqual(response.status_code, 403)

        # Accessing exchange create should return HTTP 403 Forbidden
        response2 = self.client.get(reverse('old_gold_exchange_create'))
        self.assertEqual(response2.status_code, 403)






