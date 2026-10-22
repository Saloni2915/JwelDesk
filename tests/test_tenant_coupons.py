"""
tests/test_tenant_coupons.py
----------------------------
Comprehensive tests for JewelDesk Multi-Tenant Customer Coupon,
Promotional Offer, Designer, Printing, and POS Redemption System.
"""

from decimal import Decimal
import json
from django.db import transaction
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, CompanySettings
from customers.models import Customer
from inventory.models import JewelleryItem, Category
from sales.models import Sale
from coupons.models import CustomerCoupon, CouponCodeItem, CouponRedemption
from coupons.services import (
    calculate_coupon_discount,
    validate_coupon_for_sale,
    redeem_coupon_atomic,
    generate_unique_tenant_coupon_codes,
    render_coupon_template,
    sanitize_coupon_html,
    sanitize_coupon_css,
)

User = get_user_model()


class TenantCouponSystemTests(TestCase):
    """Unit and integration tests for customer coupon lifecycle and multi-tenant isolation."""

    def setUp(self):
        self.client = Client()

        # Create Tenant A (Retail Jeweller)
        self.user_a = User.objects.create_user(
            username="kalyan_admin",
            password="Password123!",
            first_name="Kalyan",
            last_name="Verma"
        )
        self.tenant_a = Tenant.objects.create(
            name="Kalyan Royal Jewellers",
            business_type=Tenant.TYPE_RETAIL,
            is_active=True,
            owner=self.user_a,
        )
        CompanySettings.objects.create(tenant=self.tenant_a, company_name="Kalyan Royal Jewellers")

        # Create Tenant B (Competitor Showroom)
        self.user_b = User.objects.create_user(
            username="malabar_admin",
            password="Password123!",
            first_name="Malabar",
            last_name="Seth"
        )
        self.tenant_b = Tenant.objects.create(
            name="Malabar Fine Atelier",
            business_type=Tenant.TYPE_RETAIL,
            is_active=True,
            owner=self.user_b,
        )
        CompanySettings.objects.create(tenant=self.tenant_b, company_name="Malabar Fine Atelier")

        # Inventory Categories for Tenant A
        self.cat_gold = Category.objects.create(tenant=self.tenant_a, name="Gold Ornaments")
        self.cat_diamond = Category.objects.create(tenant=self.tenant_a, name="Diamond Solitaires")

        # Customers
        self.cust_alice = Customer.objects.create(tenant=self.tenant_a, name="Alice Sharma", mobile="9876543210")
        self.cust_bob = Customer.objects.create(tenant=self.tenant_a, name="Bob Patel", mobile="9876543211")

        # Inventory Items for Tenant A
        self.item_necklace = JewelleryItem.objects.create(
            tenant=self.tenant_a,
            name="22K Temple Gold Necklace",
            item_code="NK-101",
            category=self.cat_gold,
            metal_type="Gold",
            purity="22K",
            gross_weight=Decimal('20.000'),
            net_weight=Decimal('20.000'),
            selling_price=Decimal('120000.00'),
            status="Available",
            quantity=1
        )
        self.item_ring = JewelleryItem.objects.create(
            tenant=self.tenant_a,
            name="Solitaire Diamond Ring",
            item_code="RG-202",
            category=self.cat_diamond,
            metal_type="Diamond",
            purity="18K",
            gross_weight=Decimal('4.500'),
            net_weight=Decimal('4.200'),
            selling_price=Decimal('50000.00'),
            status="Available",
            quantity=1
        )

    # =========================================================================
    # 1. Calculation & Discount Rules
    # =========================================================================

    def test_percentage_discount_calculation_and_cap(self):
        """Percentage discount is accurately calculated and constrained by ceiling cap."""
        # 10% discount on ₹50,000 = ₹5,000
        coupon = CustomerCoupon.objects.create(
            tenant=self.tenant_a,
            name="Diwali 10% Off",
            code="DIWALI10",
            discount_type=CustomerCoupon.DISCOUNT_PERCENTAGE,
            discount_value=Decimal('10.00'),
            max_discount_amount=Decimal('3000.00')  # Cap at ₹3,000
        )
        # Without cap, 10% of 50000 would be 5000; with cap, it must be 3000
        disc = calculate_coupon_discount(coupon, Decimal('50000.00'))
        self.assertEqual(disc, Decimal('3000.00'))

        # If subtotal is ₹20,000: 10% = ₹2,000 (below cap of ₹3,000)
        disc_low = calculate_coupon_discount(coupon, Decimal('20000.00'))
        self.assertEqual(disc_low, Decimal('2000.00'))

    def test_fixed_discount_calculation_and_zero_floor(self):
        """Fixed cash discount applies directly and never produces negative bill total."""
        coupon = CustomerCoupon.objects.create(
            tenant=self.tenant_a,
            name="Flat ₹2000 Off",
            code="FLAT2000",
            discount_type=CustomerCoupon.DISCOUNT_FIXED,
            discount_value=Decimal('2000.00')
        )
        # Order of ₹10,000 -> ₹2,000 discount
        disc = calculate_coupon_discount(coupon, Decimal('10000.00'))
        self.assertEqual(disc, Decimal('2000.00'))

        # Order of ₹1,500 (less than discount value of ₹2,000) -> clamped at ₹1,500
        disc_clamp = calculate_coupon_discount(coupon, Decimal('1500.00'))
        self.assertEqual(disc_clamp, Decimal('1500.00'))

    # =========================================================================
    # 2. Validation & Business Rule Eligibility
    # =========================================================================

    def test_minimum_purchase_requirement(self):
        """Coupons require the invoice subtotal to meet min_purchase_amount."""
        coupon = CustomerCoupon.objects.create(
            tenant=self.tenant_a,
            name="Dhanteras Privilege",
            code="DHANTERAS",
            discount_type=CustomerCoupon.DISCOUNT_FIXED,
            discount_value=Decimal('1000.00'),
            min_purchase_amount=Decimal('25000.00')
        )
        # Subtotal ₹20,000 < ₹25,000 -> rejected
        res_fail = validate_coupon_for_sale(self.tenant_a, "DHANTERAS", subtotal=Decimal('20000.00'))
        self.assertFalse(res_fail['valid'])
        self.assertIn("Minimum purchase", res_fail['message'])

        # Subtotal ₹30,000 >= ₹25,000 -> accepted
        res_ok = validate_coupon_for_sale(self.tenant_a, "DHANTERAS", subtotal=Decimal('30000.00'))
        self.assertTrue(res_ok['valid'])
        self.assertEqual(res_ok['discount_amount'], Decimal('1000.00'))

    def test_category_and_customer_restrictions(self):
        """Coupons restricted to specific category or customer reject ineligible orders."""
        coupon_cat = CustomerCoupon.objects.create(
            tenant=self.tenant_a,
            name="Diamond Solitaires Only",
            code="DIAMONDONLY",
            discount_type=CustomerCoupon.DISCOUNT_PERCENTAGE,
            discount_value=Decimal('10.00'),
            applicable_category=self.cat_diamond
        )
        # Gold necklace is not Diamond -> reject
        res_item_fail = validate_coupon_for_sale(self.tenant_a, "DIAMONDONLY", item=self.item_necklace, subtotal=self.item_necklace.selling_price)
        self.assertFalse(res_item_fail['valid'])
        self.assertIn("Diamond Solitaires", res_item_fail['message'])

        # Diamond ring is eligible -> pass
        res_item_ok = validate_coupon_for_sale(self.tenant_a, "DIAMONDONLY", item=self.item_ring, subtotal=self.item_ring.selling_price)
        self.assertTrue(res_item_ok['valid'])

        # Customer specific coupon
        coupon_vip = CustomerCoupon.objects.create(
            tenant=self.tenant_a,
            name="Alice Sharma VIP Reward",
            code="ALICEVIP",
            discount_type=CustomerCoupon.DISCOUNT_FIXED,
            discount_value=Decimal('500.00'),
            specific_customer=self.cust_alice
        )
        # Bob Patel tries to redeem Alice's coupon -> reject
        res_cust_fail = validate_coupon_for_sale(self.tenant_a, "ALICEVIP", customer=self.cust_bob, subtotal=Decimal('10000.00'))
        self.assertFalse(res_cust_fail['valid'])
        self.assertIn("Alice Sharma", res_cust_fail['message'])

        # Alice Sharma redeems -> accepted
        res_cust_ok = validate_coupon_for_sale(self.tenant_a, "ALICEVIP", customer=self.cust_alice, subtotal=Decimal('10000.00'))
        self.assertTrue(res_cust_ok['valid'])

    def test_validity_dates_and_status(self):
        """Coupons reject redemption outside of their active validity window or when paused."""
        today = timezone.localdate()
        coupon_paused = CustomerCoupon.objects.create(
            tenant=self.tenant_a,
            name="Akshaya Tritiya Offer",
            code="AKSHAYA",
            status=CustomerCoupon.STATUS_PAUSED,
            discount_value=Decimal('500.00')
        )
        res_paused = validate_coupon_for_sale(self.tenant_a, "AKSHAYA", subtotal=Decimal('10000.00'))
        self.assertFalse(res_paused['valid'])
        self.assertIn("paused", res_paused['message'])

        # Expired coupon
        coupon_exp = CustomerCoupon.objects.create(
            tenant=self.tenant_a,
            name="Past New Year",
            code="NEWYEAR",
            status=CustomerCoupon.STATUS_ACTIVE,
            valid_until=today - timezone.timedelta(days=2),
            discount_value=Decimal('500.00')
        )
        res_exp = validate_coupon_for_sale(self.tenant_a, "NEWYEAR", subtotal=Decimal('10000.00'))
        self.assertFalse(res_exp['valid'])
        self.assertIn("expired", res_exp['message'])

    # =========================================================================
    # 3. Security, Sanitization & Safe Dynamic Placeholders
    # =========================================================================

    def test_html_and_css_sanitization(self):
        """Untrusted custom HTML and CSS are sanitized: scripts, on* handlers, and bad schemes stripped."""
        malicious_html = (
            '<div class="card" onclick="stealData()">'
            '<script>alert("XSS Attack");</script>'
            '<iframe src="https://evil.com"></iframe>'
            '<a href="javascript:void(0)">Click Here</a>'
            '<h1>{{offer_title}}</h1>'
            '</div>'
        )
        clean_html = sanitize_coupon_html(malicious_html)
        self.assertNotIn('<script>', clean_html)
        self.assertNotIn('onclick', clean_html)
        self.assertNotIn('<iframe', clean_html)
        self.assertNotIn('javascript:', clean_html)
        self.assertIn('<h1>{{offer_title}}</h1>', clean_html)

        malicious_css = "body { background: expression(alert(1)); behavior: url(x.htc); color: #fff; }"
        clean_css = sanitize_coupon_css(malicious_css)
        self.assertNotIn('expression', clean_css)
        self.assertNotIn('behavior', clean_css)
        self.assertIn('color: #fff;', clean_css)

    def test_safe_placeholder_substitution_escapes_xss(self):
        """Placeholders escape all text variables and never execute arbitrary code."""
        template = "<div>{{business_name}} - {{discount_value}} - {{coupon_code}}</div>"
        context = {
            'business_name': '<script>alert(1)</script>Kalyan Gold',
            'discount_value': '20% OFF',
            'coupon_code': 'GOLD20'
        }
        rendered = render_coupon_template(template, context)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;Kalyan Gold', rendered)
        self.assertIn('20% OFF', rendered)
        self.assertIn('GOLD20', rendered)

    # =========================================================================
    # 4. Multi-Tenant Data Isolation
    # =========================================================================

    def test_tenant_isolation_prevents_cross_tenant_access_and_redemption(self):
        """Tenant A cannot view, edit, or redeem Tenant B's coupons."""
        coupon_b = CustomerCoupon.objects.create(
            tenant=self.tenant_b,
            name="Malabar Secret VIP",
            code="MALABARVIP",
            discount_type=CustomerCoupon.DISCOUNT_FIXED,
            discount_value=Decimal('5000.00'),
            status=CustomerCoupon.STATUS_ACTIVE
        )

        # 1. Tenant A POS cashier tries to validate Tenant B's coupon code
        res = validate_coupon_for_sale(self.tenant_a, "MALABARVIP", subtotal=Decimal('50000.00'))
        self.assertFalse(res['valid'])
        self.assertIn("invalid or does not belong to this business", res['message'])

        # 2. Tenant A logs in and accesses dashboard list
        self.client.force_login(self.user_a)
        resp_list = self.client.get(reverse('coupons:coupon_list'))
        self.assertEqual(resp_list.status_code, 200)
        self.assertNotContains(resp_list, "Malabar Secret VIP")

        # 3. Tenant A tries to directly view or edit Tenant B's coupon -> HTTP 404
        resp_detail = self.client.get(reverse('coupons:coupon_detail', kwargs={'pk': coupon_b.pk}))
        self.assertEqual(resp_detail.status_code, 404)

        resp_edit = self.client.get(reverse('coupons:coupon_edit', kwargs={'pk': coupon_b.pk}))
        self.assertEqual(resp_edit.status_code, 404)

    # =========================================================================
    # 5. Collision-Free Unique Code Generation & Printing
    # =========================================================================

    def test_unique_batch_code_generation(self):
        """Bulk generation creates exact requested count of collision-free unique codes."""
        coupon = CustomerCoupon.objects.create(
            tenant=self.tenant_a,
            name="Wedding Season Vouchers",
            code="WEDDING26",
            discount_value=Decimal('1000.00')
        )
        codes = generate_unique_tenant_coupon_codes(
            tenant=self.tenant_a,
            coupon=coupon,
            count=15,
            prefix="WED-",
            length=8,
            serial_start=1
        )
        self.assertEqual(len(codes), 15)
        # Ensure database count matches
        self.assertEqual(CouponCodeItem.objects.filter(coupon=coupon).count(), 15)
        # Ensure all codes are distinct
        distinct_codes = set(c.code for c in codes)
        self.assertEqual(len(distinct_codes), 15)
        # Verify prefix
        self.assertTrue(codes[0].code.startswith("WED-"))

    # =========================================================================
    # 6. Concurrency Protection & POS Atomic Redemption
    # =========================================================================

    def test_single_use_coupon_atomic_redemption_and_double_use_rejection(self):
        """Single-use coupon is redeemed atomically and cannot be used twice."""
        coupon = CustomerCoupon.objects.create(
            tenant=self.tenant_a,
            name="One-Time VIP Gift",
            code="ONETIME100",
            discount_type=CustomerCoupon.DISCOUNT_FIXED,
            discount_value=Decimal('100.00'),
            is_single_use=True
        )

        sale_1 = Sale.objects.create(
            tenant=self.tenant_a,
            customer=self.cust_alice,
            jewellery_item=self.item_ring,
            sale_price=Decimal('49900.00'),
            original_price=Decimal('50000.00'),
            coupon_discount=Decimal('100.00'),
            applied_coupon_code="ONETIME100"
        )

        # 1. First redemption succeeds
        with transaction.atomic():
            disc = redeem_coupon_atomic(
                tenant=self.tenant_a,
                coupon_code="ONETIME100",
                sale=sale_1,
                customer=self.cust_alice,
                subtotal=Decimal('50000.00'),
                user=self.user_a
            )
        self.assertEqual(disc, Decimal('100.00'))

        coupon.refresh_from_db()
        self.assertEqual(coupon.times_redeemed, 1)
        self.assertEqual(CouponRedemption.objects.filter(coupon=coupon).count(), 1)

        # 2. Second concurrent/subsequent attempt must be rejected
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                redeem_coupon_atomic(
                    tenant=self.tenant_a,
                    coupon_code="ONETIME100",
                    sale=sale_1,
                    customer=self.cust_bob,
                    subtotal=Decimal('50000.00'),
                    user=self.user_a
                )

    def test_pos_counter_billing_flow_with_coupon(self):
        """Cashier creates a sale with a valid coupon code in POS checkout counter."""
        self.client.force_login(self.user_a)

        coupon = CustomerCoupon.objects.create(
            tenant=self.tenant_a,
            name="Counter Promo 2026",
            code="COUNTER26",
            discount_type=CustomerCoupon.DISCOUNT_FIXED,
            discount_value=Decimal('2000.00'),
            min_purchase_amount=Decimal('10000.00'),
            status=CustomerCoupon.STATUS_ACTIVE
        )

        # 1. Cashier checks coupon via AJAX API preview
        api_url = reverse('coupons:coupon_validate_api') + f"?code=COUNTER26&subtotal=120000.00"
        resp_api = self.client.get(api_url)
        self.assertEqual(resp_api.status_code, 200)
        api_data = resp_api.json()
        self.assertTrue(api_data['valid'])
        self.assertEqual(api_data['discount_amount'], 2000.00)

        # 2. Cashier submits POS sale with coupon_code applied
        post_data = {
            'customer': self.cust_alice.pk,
            'jewellery_item': self.item_necklace.pk,
            'sale_price': '118000.00',  # 120,000 - 2,000 coupon discount
            'coupon_code': 'COUNTER26',
            'payment_method': 'Cash',
            'notes': 'Bill with coupon'
        }
        resp_sale = self.client.post(reverse('sale_add'), post_data)
        self.assertEqual(resp_sale.status_code, 302)

        # Verify sale recorded with coupon discount
        created_sale = Sale.objects.filter(tenant=self.tenant_a, customer=self.cust_alice).order_by('-id').first()
        self.assertIsNotNone(created_sale)
        self.assertEqual(created_sale.applied_coupon_code, "COUNTER26")
        self.assertEqual(created_sale.coupon_discount, Decimal('2000.00'))
        self.assertEqual(created_sale.original_price, Decimal('120000.00'))
        self.assertEqual(created_sale.sale_price, Decimal('118000.00'))

        # Verify CouponRedemption record created
        redemption = CouponRedemption.objects.filter(sale=created_sale).first()
        self.assertIsNotNone(redemption)
        self.assertEqual(redemption.discount_amount, Decimal('2000.00'))
        self.assertEqual(redemption.coupon_code_used, "COUNTER26")

        # Verify coupon times_redeemed incremented
        coupon.refresh_from_db()
        self.assertEqual(coupon.times_redeemed, 1)

    # =========================================================================
    # 7. Reports & CSV Export
    # =========================================================================

    def test_coupon_reports_and_csv_export(self):
        """Coupon reports view and CSV export accurately output metrics."""
        self.client.force_login(self.user_a)

        coupon = CustomerCoupon.objects.create(
            tenant=self.tenant_a,
            name="Report Test Campaign",
            code="RPT2026",
            discount_type=CustomerCoupon.DISCOUNT_FIXED,
            discount_value=Decimal('500.00')
        )
        sale = Sale.objects.create(
            tenant=self.tenant_a,
            customer=self.cust_alice,
            jewellery_item=self.item_ring,
            sale_price=Decimal('49500.00'),
            coupon_discount=Decimal('500.00'),
            applied_coupon_code="RPT2026"
        )
        CouponRedemption.objects.create(
            tenant=self.tenant_a,
            coupon=coupon,
            coupon_code_used="RPT2026",
            sale=sale,
            customer=self.cust_alice,
            order_subtotal=Decimal('50000.00'),
            discount_amount=Decimal('500.00'),
            final_total=Decimal('49500.00'),
            redeemed_by_user=self.user_a
        )

        # 1. Reports view
        resp_rpt = self.client.get(reverse('coupons:coupon_reports'))
        self.assertEqual(resp_rpt.status_code, 200)
        self.assertContains(resp_rpt, "Report Test Campaign")
        self.assertContains(resp_rpt, "500.00")

        # 2. CSV export
        resp_csv = self.client.get(reverse('coupons:coupon_reports_export'))
        self.assertEqual(resp_csv.status_code, 200)
        self.assertEqual(resp_csv['Content-Type'], 'text/csv')
        csv_content = resp_csv.content.decode('utf-8')
        self.assertIn("Redemption ID", csv_content)
        self.assertIn("Report Test Campaign", csv_content)
        self.assertIn("RPT2026", csv_content)
        self.assertIn("500.00", csv_content)
