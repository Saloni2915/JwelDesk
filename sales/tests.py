from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from inventory.models import Category, JewelleryItem
from customers.models import Customer
from sales.models import Sale, Enquiry


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
        self.assertIn(b'55000.00', pdf_text)
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




