"""
tests/test_coupon_designer.py
------------------------------
Comprehensive test suite for Coupon Designer, Discount Templates,
Security Sanitization, Collision-Resistant Unique Code Generation,
and Browser-Native Print Management in the Super Admin Portal.
"""

from decimal import Decimal
import re
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Tenant, CompanySettings
from super_admin.models import (
    CouponBatchItem,
    CouponDesignTemplate,
    CouponPrintBatch,
    PlatformAuditLog,
)
from super_admin.coupon_engine import (
    ALLOWED_PLACEHOLDERS,
    generate_barcode_svg,
    generate_qr_svg,
    generate_random_code,
    generate_unique_batch_codes,
    get_builtin_template_markup,
    render_single_coupon_html,
    sanitize_coupon_css,
    sanitize_coupon_html,
    substitute_placeholders,
)

User = get_user_model()


class CouponSecurityAndSanitizationTests(TestCase):
    """Verify security isolation: treat HTML/CSS as untrusted, strip XSS vectors."""

    def test_strip_script_tags(self):
        malicious = "<div>Hello</div><script>alert('pwned')</script><span>World</span>"
        sanitized = sanitize_coupon_html(malicious)
        self.assertNotIn('<script', sanitized.lower())
        self.assertNotIn("alert('pwned')", sanitized)
        self.assertIn('<div>Hello</div>', sanitized)
        self.assertIn('<span>World</span>', sanitized)

    def test_strip_inline_event_handlers(self):
        malicious = '<div onclick="stealCookies()" onmouseover="evil()" onload="exploit()">Click Me</div>'
        sanitized = sanitize_coupon_html(malicious)
        self.assertNotIn('onclick', sanitized.lower())
        self.assertNotIn('onmouseover', sanitized.lower())
        self.assertNotIn('onload', sanitized.lower())
        self.assertIn('Click Me', sanitized)

    def test_strip_dangerous_url_schemes(self):
        malicious = '<a href="javascript:alert(1)">Claim</a><img src="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">'
        sanitized = sanitize_coupon_html(malicious)
        self.assertNotIn('javascript:', sanitized.lower())
        self.assertNotIn('data:text/html', sanitized.lower())

    def test_sanitize_css_expressions_and_imports(self):
        malicious_css = """
        @import url('https://evil.com/hack.css');
        .voucher {
            color: expression(alert(1));
            -moz-binding: url('http://evil.com/xss.xml#test');
            background: #110e0c;
        }
        """
        sanitized_css = sanitize_coupon_css(malicious_css)
        self.assertNotIn('@import', sanitized_css.lower())
        self.assertNotIn('expression(', sanitized_css.lower())
        self.assertNotIn('-moz-binding', sanitized_css.lower())
        self.assertIn('background: #110e0c', sanitized_css)

    def test_safe_placeholder_escaping(self):
        raw_html = "<div class='brand'>{{business_name}}</div><div class='code'>{{coupon_code}}</div>"
        context = {
            'business_name': "Royal & Sons <script>evil()</script>",
            'coupon_code': 'VIP-100',
        }
        rendered = substitute_placeholders(raw_html, context)
        self.assertNotIn('<script>', rendered)
        self.assertIn('Royal &amp; Sons &lt;script&gt;evil()&lt;/script&gt;', rendered)
        self.assertIn('VIP-100', rendered)


class CouponCodeAndSVGGenerationTests(TestCase):
    """Test cryptographic collision-resistant codes and resolution-independent vector SVG."""

    def test_generate_random_code_format(self):
        code = generate_random_code(prefix='GOLD-', length=8)
        self.assertTrue(code.startswith('GOLD-'))
        self.assertEqual(len(code), 5 + 8)
        # Verify no ambiguous characters (0, O, 1, I, L)
        for char in ['0', 'O', '1', 'I', 'L']:
            self.assertNotIn(char, code[5:])

    def test_generate_unique_batch_codes_uniqueness(self):
        template = CouponDesignTemplate.objects.create(
            name="Test Template",
            template_type=CouponDesignTemplate.TYPE_BUILT_IN,
            built_in_style=CouponDesignTemplate.STYLE_LUXURY_GOLD,
        )
        batch = CouponPrintBatch.objects.create(
            batch_number="TEST-BATCH-001",
            template=template,
            name="Test Batch",
            batch_type=CouponPrintBatch.BATCH_UNIQUE,
            total_quantity=25,
            discount_type=CouponDesignTemplate.DISCOUNT_PERCENTAGE,
            discount_value=Decimal('20.00'),
            offer_title="Privilege",
            business_name="JewelDesk",
        )
        codes = generate_unique_batch_codes(batch, count=25, prefix='JD-', length=8)
        self.assertEqual(len(codes), 25)
        # All codes must be unique
        self.assertEqual(len(set(codes)), 25)

    def test_vector_barcode_svg_generation(self):
        svg = generate_barcode_svg("JD-8Y7W2K")
        self.assertTrue(svg.startswith('<svg'))
        self.assertTrue(svg.endswith('</svg>'))
        self.assertIn('JD-8Y7W2K', svg)
        self.assertIn('<rect', svg)

    def test_vector_qr_svg_generation(self):
        svg = generate_qr_svg("JD-8Y7W2K")
        self.assertTrue(svg.startswith('<svg'))
        self.assertTrue(svg.endswith('</svg>'))
        self.assertIn('viewBox', svg)


class CouponSuperAdminViewsTests(TestCase):
    """Test Super Admin authorization, template management, batch generation, and printing."""

    def setUp(self):
        # Regular Tenant user (not superuser)
        self.normal_user = User.objects.create_user(
            username='showroom_manager',
            email='manager@jewellers.com',
            password='TestPassword123!',
        )
        self.tenant = Tenant.objects.create(
            name='Kalyan Jewellers',
            owner=self.normal_user,
            slug='kalyan-jewellers',
            is_active=True,
        )

        # Super Admin user
        self.super_admin = User.objects.create_superuser(
            username='platform_superadmin',
            email='admin@jeweldesk.com',
            password='SuperAdminPass123!',
        )

        self.client_anon = Client()
        self.client_normal = Client()
        self.client_normal.login(username='showroom_manager', password='TestPassword123!')
        self.client_admin = Client()
        self.client_admin.login(username='platform_superadmin', password='SuperAdminPass123!')

    def test_access_control(self):
        """Only authenticated superusers can access coupon administration."""
        url = reverse('super_admin:coupon_list')

        # Anonymous redirected to login
        res_anon = self.client_anon.get(url)
        self.assertEqual(res_anon.status_code, 302)

        # Regular authenticated user gets 403 Forbidden
        res_normal = self.client_normal.get(url)
        self.assertEqual(res_normal.status_code, 403)

        # Super Admin gets 200 OK
        res_admin = self.client_admin.get(url)
        self.assertEqual(res_admin.status_code, 200)

    def test_create_and_edit_template(self):
        """Super Admin can create and modify coupon design templates."""
        create_url = reverse('super_admin:coupon_create')
        post_data = {
            'name': 'Festive Heritage Gold 25% Off',
            'description': 'Showroom VIP brochure insert',
            'template_type': CouponDesignTemplate.TYPE_BUILT_IN,
            'built_in_style': CouponDesignTemplate.STYLE_LUXURY_GOLD,
            'discount_type': CouponDesignTemplate.DISCOUNT_PERCENTAGE,
            'discount_value': '25.00',
            'offer_title': 'Special Heritage Privilege',
            'sample_coupon_code': 'HERITAGE25',
            'business_name': 'Atelier Fine Gems',
            'minimum_purchase': '15000.00',
            'page_size': 'a4',
            'orientation': 'portrait',
            'coupon_width_mm': '180',
            'coupon_height_mm': '70',
            'grid_columns': '1',
            'grid_rows': '3',
            'margin_mm': '8',
            'spacing_mm': '6',
            'show_barcode': 'on',
            'show_qr_code': 'on',
            'primary_color': '#d4af37',
            'background_color': '#160f09',
            'text_color': '#fef9ed',
        }
        res = self.client_admin.post(create_url, post_data, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(CouponDesignTemplate.objects.filter(name='Festive Heritage Gold 25% Off').exists())

        tpl = CouponDesignTemplate.objects.get(name='Festive Heritage Gold 25% Off')
        self.assertEqual(tpl.discount_value, Decimal('25.00'))
        self.assertEqual(tpl.formatted_discount, "25% OFF")

        # Check Audit Log created
        self.assertTrue(PlatformAuditLog.objects.filter(
            action=PlatformAuditLog.ACTION_COUPON_TEMPLATE_CREATE,
            actor=self.super_admin,
        ).exists())

    def test_duplicate_and_archive_template(self):
        """Super Admin can duplicate and archive templates."""
        tpl = CouponDesignTemplate.objects.create(
            name="Original Voucher",
            template_type=CouponDesignTemplate.TYPE_BUILT_IN,
            built_in_style=CouponDesignTemplate.STYLE_LUXURY_GOLD,
            created_by=self.super_admin,
        )

        # Duplicate
        dup_url = reverse('super_admin:coupon_duplicate', args=[tpl.id])
        res_dup = self.client_admin.post(dup_url, follow=True)
        self.assertEqual(res_dup.status_code, 200)
        self.assertTrue(CouponDesignTemplate.objects.filter(name="Original Voucher (Copy)").exists())

        # Archive
        arch_url = reverse('super_admin:coupon_archive', args=[tpl.id])
        self.client_admin.post(arch_url)
        tpl.refresh_from_db()
        self.assertTrue(tpl.is_archived)

        # Unarchive
        self.client_admin.post(arch_url)
        tpl.refresh_from_db()
        self.assertFalse(tpl.is_archived)

    def test_batch_generation_unique_codes(self):
        """Generate a print batch with unique codes and verify registry items."""
        tpl = CouponDesignTemplate.objects.create(
            name="Diwali 2026 Template",
            template_type=CouponDesignTemplate.TYPE_BUILT_IN,
            built_in_style=CouponDesignTemplate.STYLE_LUXURY_GOLD,
            discount_type=CouponDesignTemplate.DISCOUNT_PERCENTAGE,
            discount_value=Decimal('20.00'),
            offer_title="Diwali Special",
            business_name="JewelDesk",
            created_by=self.super_admin,
        )

        batch_url = reverse('super_admin:coupon_batch_create')
        batch_data = {
            'template': tpl.id,
            'name': 'Diwali Mailer 10 Vouchers',
            'batch_type': CouponPrintBatch.BATCH_UNIQUE,
            'total_quantity': 10,
            'code_prefix': 'DIWALI-',
            'code_length': 6,
            'include_serial_numbers': 'on',
            'serial_start': 101,
            'grid_columns': 1,
            'grid_rows': 3,
            'margin_mm': 8,
            'spacing_mm': 6,
            'discount_type': CouponDesignTemplate.DISCOUNT_PERCENTAGE,
            'discount_value': '20.00',
            'offer_title': 'Diwali Special',
            'business_name': 'JewelDesk',
        }
        res = self.client_admin.post(batch_url, batch_data, follow=True)
        self.assertEqual(res.status_code, 200)

        batch = CouponPrintBatch.objects.get(name='Diwali Mailer 10 Vouchers')
        self.assertEqual(batch.total_quantity, 10)
        self.assertEqual(batch.items.count(), 10)

        # Serials should start at 101
        serials = list(batch.items.values_list('serial_number', flat=True))
        self.assertEqual(serials, list(range(101, 111)))

        # All codes must be unique and have prefix
        codes = list(batch.items.values_list('coupon_code', flat=True))
        self.assertEqual(len(set(codes)), 10)
        for code in codes:
            self.assertTrue(code.startswith('DIWALI-'))

        # Sheet count: 10 coupons with 3 per sheet = 4 sheets
        self.assertEqual(batch.sheet_count, 4)

    def test_batch_generation_identical_code(self):
        """Generate a batch with identical promotional code and sequential serial numbers."""
        tpl = CouponDesignTemplate.objects.create(
            name="Festive Promo Template",
            template_type=CouponDesignTemplate.TYPE_BUILT_IN,
            discount_type=CouponDesignTemplate.DISCOUNT_FIXED,
            discount_value=Decimal('500.00'),
            created_by=self.super_admin,
        )

        batch_url = reverse('super_admin:coupon_batch_create')
        batch_data = {
            'template': tpl.id,
            'name': 'Diwali Shared Flyer',
            'batch_type': CouponPrintBatch.BATCH_IDENTICAL,
            'total_quantity': 5,
            'shared_code': 'GOLD500',
            'include_serial_numbers': 'on',
            'serial_start': 1,
            'grid_columns': 1,
            'grid_rows': 3,
            'margin_mm': 8,
            'spacing_mm': 6,
            'discount_type': CouponDesignTemplate.DISCOUNT_FIXED,
            'discount_value': '500.00',
            'offer_title': '₹500 Discount',
            'business_name': 'JewelDesk',
        }
        res = self.client_admin.post(batch_url, batch_data, follow=True)
        self.assertEqual(res.status_code, 200)

        batch = CouponPrintBatch.objects.get(name='Diwali Shared Flyer')
        self.assertEqual(batch.items.count(), 5)
        for item in batch.items.all():
            self.assertEqual(item.coupon_code, 'GOLD500')

    def test_native_print_layout_view(self):
        """Verify dedicated print page renders @page, multi-coupon grid, and excludes admin chrome."""
        tpl = CouponDesignTemplate.objects.create(
            name="Print Test Template",
            template_type=CouponDesignTemplate.TYPE_BUILT_IN,
            built_in_style=CouponDesignTemplate.STYLE_LUXURY_GOLD,
            discount_type=CouponDesignTemplate.DISCOUNT_PERCENTAGE,
            discount_value=Decimal('20.00'),
            created_by=self.super_admin,
        )
        batch = CouponPrintBatch.objects.create(
            batch_number="TEST-BATCH-PRINT",
            template=tpl,
            name="Print Test Batch",
            batch_type=CouponPrintBatch.BATCH_UNIQUE,
            total_quantity=3,
            discount_type=CouponDesignTemplate.DISCOUNT_PERCENTAGE,
            discount_value=Decimal('20.00'),
            offer_title="Privilege",
            business_name="JewelDesk",
            created_by=self.super_admin,
        )
        codes = generate_unique_batch_codes(batch, count=3, prefix='PRN-', length=6)
        for idx, code in enumerate(codes):
            CouponBatchItem.objects.create(batch=batch, serial_number=idx + 1, coupon_code=code)

        print_url = reverse('super_admin:coupon_batch_print', args=[batch.id])
        res = self.client_admin.get(print_url)
        self.assertEqual(res.status_code, 200)

        content = res.content.decode('utf-8')
        # Check print CSS rules
        self.assertIn('@media print', content)
        self.assertIn('@page', content)
        self.assertIn('no-print', content)
        # Check all coupon codes are rendered
        for code in codes:
            self.assertIn(code, content)
        # Check window.print() trigger button exists
        self.assertIn('window.print()', content)

    def test_item_redemption_toggle(self):
        """Verify marking a coupon claimed / redeemed at billing desk."""
        tpl = CouponDesignTemplate.objects.create(name="Redemption Test")
        batch = CouponPrintBatch.objects.create(
            batch_number="RED-001",
            template=tpl,
            name="Redeem Batch",
            discount_value=Decimal('10.00'),
        )
        item = CouponBatchItem.objects.create(
            batch=batch,
            serial_number=1,
            coupon_code="REDEEM-TEST",
        )
        self.assertFalse(item.is_redeemed)

        toggle_url = reverse('super_admin:coupon_batch_item_toggle', args=[item.id])
        self.client_admin.post(toggle_url, {'redemption_note': 'Redeemed by Counter 1 on Invoice #1029'})
        item.refresh_from_db()
        self.assertTrue(item.is_redeemed)
        self.assertIsNotNone(item.redeemed_at)
        self.assertIn('Invoice #1029', item.redemption_note)

    def test_live_preview_api(self):
        """Verify sandboxed live preview API returns sanitized preview HTML."""
        api_url = reverse('super_admin:coupon_preview_api')
        res = self.client_admin.post(api_url, {
            'template_type': CouponDesignTemplate.TYPE_BUILT_IN,
            'built_in_style': CouponDesignTemplate.STYLE_LUXURY_GOLD,
            'offer_title': 'Diwali Gold Gala',
            'discount_type': CouponDesignTemplate.DISCOUNT_PERCENTAGE,
            'discount_value': '30.00',
            'sample_coupon_code': 'DIWALI-GALA30',
            'business_name': 'Royal Jewellery Atelier',
        })
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('DIWALI-GALA30', content)
        self.assertIn('Royal Jewellery Atelier', content)
        self.assertIn('30% OFF', content)
        self.assertEqual(res['X-Frame-Options'], 'SAMEORIGIN')
