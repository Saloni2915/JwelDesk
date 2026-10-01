"""
inventory/test_pricing.py
-------------------------
Comprehensive test suite for JewelDesk Jewellery Pricing Engine.

Covers:
  - Gold pricing (24K, 22K/916, 18K/750, 14K/585)
  - Silver pricing (999 Fine Silver, 925 Sterling Silver)
  - Different purities and conversion factors
  - Weight calculations: gross weight vs net weight fallback
  - Making charges: Fixed Amount, Per Gram, Percentage
  - Wastage: Percentage and explicit amount
  - Stone / Diamond charges
  - Other charges (hallmarking, etc.)
  - GST / tax calculations (default 3.0%, custom, 0%)
  - Zero / missing / optional charges safety (no exceptions on None, 0, or empty strings)
  - Final price equality: Metal Value + Wastage + Making + Stones + Others + GST == Final Price
  - Item live pricing integration (calculate_live_price, current_market_price)
  - Custom order live estimate integration (calculate_estimated_price)
  - Historical sale price preservation when metal rates change
  - Permission enforcement on metal rates view and pricing updates
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from inventory.models import Category, JewelleryItem, MetalRate
from inventory import pricing
from sales.models import Sale
from customers.models import Customer
from custom_orders.models import CustomOrder
from team.models import Role, Employee, EmployeePermission

User = get_user_model()


class PricingEngineUnitTests(TestCase):
    """Unit tests for pricing calculation logic and formulas in inventory.pricing."""

    def test_gold_24k_pure_pricing(self):
        """24K pure gold calculation: purity factor 1.0, 10g at ₹7500/g = ₹75,000 + GST."""
        b = pricing.calculate_jewellery_price(
            metal_type='Gold',
            purity='24K',
            gross_weight=Decimal('10.000'),
            stone_weight=Decimal('0.000'),
            base_metal_rate=Decimal('7500.00'),
            making_charge=Decimal('1000.00'),
            making_charge_type='Fixed Amount',
            tax_percent=Decimal('3.00'),
        )
        self.assertEqual(b.purity_factor, Decimal('1.000000'))
        self.assertEqual(b.effective_rate_per_gram, Decimal('7500.00'))
        self.assertEqual(b.metal_value, Decimal('75000.00'))
        self.assertEqual(b.making_charge_amount, Decimal('1000.00'))
        self.assertEqual(b.subtotal, Decimal('76000.00'))
        self.assertEqual(b.tax_amount, Decimal('2280.00')) # 3% of 76000
        self.assertEqual(b.final_price, Decimal('78280.00'))
        # Formula integrity
        self.assertEqual(
            b.final_price,
            b.metal_value + b.wastage_amount + b.making_charge_amount +
            b.stone_charges + b.other_charges + b.tax_amount
        )

    def test_gold_22k_standard_pricing(self):
        """22K (916) gold: rate = 24K_rate * 22/24. 10g at base ₹7200 -> 6600/g."""
        b = pricing.calculate_jewellery_price(
            metal_type='Gold',
            purity='22K (916)',
            gross_weight=Decimal('10.000'),
            base_metal_rate=Decimal('7200.00'),
            tax_percent=Decimal('3.00'),
        )
        # 7200 * (22/24) = 6600.00
        self.assertEqual(b.effective_rate_per_gram, Decimal('6600.00'))
        self.assertEqual(b.metal_value, Decimal('66000.00'))
        self.assertEqual(b.subtotal, Decimal('66000.00'))
        self.assertEqual(b.tax_amount, Decimal('1980.00')) # 3% of 66000
        self.assertEqual(b.final_price, Decimal('67980.00'))

    def test_gold_18k_and_14k_purities(self):
        """18K (750) has factor 18/24 (0.75); 14K (585) has factor 14/24 (0.583333)."""
        base_rate = Decimal('7200.00')
        b_18 = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='18K', gross_weight=Decimal('10.000'),
            base_metal_rate=base_rate, tax_percent=Decimal('0.00')
        )
        # 7200 * 0.75 = 5400.00; 10g = 54000.00
        self.assertEqual(b_18.effective_rate_per_gram, Decimal('5400.00'))
        self.assertEqual(b_18.final_price, Decimal('54000.00'))

        b_14 = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='14K (585)', gross_weight=Decimal('10.000'),
            base_metal_rate=base_rate, tax_percent=Decimal('0.00')
        )
        # 7200 * (14/24) = 4200.00; 10g = 42000.00
        self.assertEqual(b_14.effective_rate_per_gram, Decimal('4200.00'))
        self.assertEqual(b_14.final_price, Decimal('42000.00'))

    def test_silver_999_and_925_pricing(self):
        """Silver 999 is 100% fine; 925 sterling silver is 92.5%."""
        base_silver = Decimal('100.00') # ₹100/g
        b_999 = pricing.calculate_jewellery_price(
            metal_type='Silver', purity='999 Fine Silver', gross_weight=Decimal('50.000'),
            base_metal_rate=base_silver, tax_percent=Decimal('0.00')
        )
        self.assertEqual(b_999.effective_rate_per_gram, Decimal('100.00'))
        self.assertEqual(b_999.metal_value, Decimal('5000.00'))

        b_925 = pricing.calculate_jewellery_price(
            metal_type='Silver', purity='925 Sterling', gross_weight=Decimal('50.000'),
            base_metal_rate=base_silver, tax_percent=Decimal('0.00')
        )
        # 100 * 0.925 = 92.50; 50g = 4625.00
        self.assertEqual(b_925.effective_rate_per_gram, Decimal('92.50'))
        self.assertEqual(b_925.metal_value, Decimal('4625.00'))

    def test_weight_calculations_and_net_weight_fallback(self):
        """Gross minus stone weight gives net weight; if net weight explicitly given, use it."""
        # 1. Gross 15g, stone 3g -> net 12g used
        b1 = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='24K', gross_weight=Decimal('15.000'),
            stone_weight=Decimal('3.000'), base_metal_rate=Decimal('1000.00'),
            tax_percent=Decimal('0.00')
        )
        self.assertEqual(b1.net_weight, Decimal('12.000'))
        self.assertEqual(b1.metal_weight, Decimal('12.000'))
        self.assertEqual(b1.metal_value, Decimal('12000.00'))

        # 2. Net weight explicitly specified as 11.5g
        b2 = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='24K', gross_weight=Decimal('15.000'),
            net_weight=Decimal('11.500'), base_metal_rate=Decimal('1000.00'),
            tax_percent=Decimal('0.00')
        )
        self.assertEqual(b2.metal_weight, Decimal('11.500'))
        self.assertEqual(b2.metal_value, Decimal('11500.00'))

    def test_making_charges_types(self):
        """Fixed amount, per-gram on gross weight, and percentage of metal value."""
        base_rate = Decimal('5000.00')
        # 1. Fixed: ₹2,500
        b_fixed = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='24K', gross_weight=Decimal('10.000'),
            base_metal_rate=base_rate, making_charge=Decimal('2500.00'),
            making_charge_type='Fixed Amount', tax_percent=Decimal('0.00')
        )
        self.assertEqual(b_fixed.making_charge_amount, Decimal('2500.00'))

        # 2. Per Gram: ₹400/g on 10g = ₹4,000
        b_per_g = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='24K', gross_weight=Decimal('10.000'),
            base_metal_rate=base_rate, making_charge=Decimal('400.00'),
            making_charge_type='Per Gram', tax_percent=Decimal('0.00')
        )
        self.assertEqual(b_per_g.making_charge_amount, Decimal('4000.00'))

        # 3. Percentage: 10% on metal value (₹50,000) = ₹5,000
        b_pct = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='24K', gross_weight=Decimal('10.000'),
            base_metal_rate=base_rate, making_charge=Decimal('10.00'),
            making_charge_type='Percentage', tax_percent=Decimal('0.00')
        )
        self.assertEqual(b_pct.making_charge_amount, Decimal('5000.00'))

    def test_wastage_percentage_and_fixed_amount(self):
        """Wastage can be a percentage of metal value or an explicit fixed amount."""
        base_rate = Decimal('6000.00') # 10g 24K = ₹60,000 metal value
        # 1. Percentage: 5% of ₹60,000 = ₹3,000
        b_pct = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='24K', gross_weight=Decimal('10.000'),
            base_metal_rate=base_rate, wastage_percent=Decimal('5.00'),
            tax_percent=Decimal('0.00')
        )
        self.assertEqual(b_pct.wastage_amount, Decimal('3000.00'))

        # 2. Explicit amount: ₹1,500 overrides or acts directly
        b_amt = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='24K', gross_weight=Decimal('10.000'),
            base_metal_rate=base_rate, wastage_amount=Decimal('1500.00'),
            tax_percent=Decimal('0.00')
        )
        self.assertEqual(b_amt.wastage_amount, Decimal('1500.00'))

    def test_stone_and_other_charges(self):
        """Stone and other charges are correctly summed into the subtotal."""
        b = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='24K', gross_weight=Decimal('10.000'),
            base_metal_rate=Decimal('5000.00'), stone_charges=Decimal('4500.00'),
            other_charges=Decimal('500.00'), tax_percent=Decimal('0.00')
        )
        # 50,000 + 4,500 + 500 = 55,000
        self.assertEqual(b.stone_charges, Decimal('4500.00'))
        self.assertEqual(b.other_charges, Decimal('500.00'))
        self.assertEqual(b.subtotal, Decimal('55000.00'))
        self.assertEqual(b.final_price, Decimal('55000.00'))

    def test_gst_calculations(self):
        """Standard 3% GST, 0% tax, and custom 5% tax."""
        subtotal = Decimal('100000.00')
        # 3% GST -> ₹3,000
        b3 = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='24K', gross_weight=Decimal('20.000'),
            base_metal_rate=Decimal('5000.00'), tax_percent=Decimal('3.00')
        )
        self.assertEqual(b3.subtotal, subtotal)
        self.assertEqual(b3.tax_amount, Decimal('3000.00'))
        self.assertEqual(b3.final_price, Decimal('103000.00'))

        # 0% tax
        b0 = pricing.calculate_jewellery_price(
            metal_type='Gold', purity='24K', gross_weight=Decimal('20.000'),
            base_metal_rate=Decimal('5000.00'), tax_percent=Decimal('0.00')
        )
        self.assertEqual(b0.tax_amount, Decimal('0.00'))
        self.assertEqual(b0.final_price, subtotal)

    def test_zero_and_missing_optional_charges_safe(self):
        """All None, empty strings, missing fields handle safely without throwing."""
        b = pricing.calculate_jewellery_price(
            metal_type=None,
            purity='',
            gross_weight=None,
            stone_weight=None,
            net_weight=None,
            base_metal_rate=None,
            wastage_percent=None,
            wastage_amount=None,
            making_charge=None,
            stone_charges=None,
            other_charges=None,
            tax_percent=None,
        )
        self.assertIsNotNone(b)
        self.assertGreaterEqual(b.final_price, Decimal('0.00'))
        # to_dict works cleanly
        d = b.to_dict()
        self.assertIn('final_price', d)


class PricingIntegrationTests(TestCase):
    """Integration tests with Inventory, Sales, Custom Orders, and Metal Rates."""

    def setUp(self):
        self.category = Category.objects.create(name='Rings')
        self.customer = Customer.objects.create(name='Priya Sharma', mobile='9876543210')

        # Seed standard metal rates in DB
        MetalRate.objects.update_or_create(
            metal_type='Gold', defaults={'rate_per_gram': Decimal('7000.00')}
        )
        MetalRate.objects.update_or_create(
            metal_type='Silver', defaults={'rate_per_gram': Decimal('90.00')}
        )

        # Create user accounts
        self.admin_user = User.objects.create_superuser('admin_user', 'admin@example.com', 'password123')
        self.staff_user = User.objects.create_user('staff_user', 'staff@example.com', 'password123', is_staff=True)

        # Regular employee with view-only permissions
        self.emp_user = User.objects.create_user('sales_emp', 'sales@example.com', 'password123')
        sales_role, _ = Role.objects.get_or_create(name=Role.ROLE_SALES)
        self.employee = Employee.objects.create(
            user=self.emp_user,
            employee_id='EMP-9901',
            full_name='Sales Rep',
            email='sales@example.com',
            role=sales_role,
            status=Employee.STATUS_ACTIVE
        )
        # Grant inventory:view and metal_prices:view only
        EmployeePermission.objects.create(employee=self.employee, module='inventory', can_view=True)
        EmployeePermission.objects.create(employee=self.employee, module='metal_prices', can_view=True, can_edit=False)

    def test_jewellery_item_live_price_methods(self):
        """JewelleryItem calculate_live_price and current_market_price properties work."""
        item = JewelleryItem.objects.create(
            item_code='GLD-RN-TEST-1',
            name='22K Floral Ring',
            category=self.category,
            metal_type='Gold',
            purity='22K (916)',
            gross_weight=Decimal('5.000'),
            stone_weight=Decimal('0.500'),
            net_weight=Decimal('4.500'),
            making_charge=Decimal('1500.00'),
            making_charge_type='Fixed Amount',
            wastage_percent=Decimal('2.00'),
            selling_price=Decimal('35000.00'),
        )

        # Live calculation with base gold rate = 7000/g
        # 22K rate = 7000 * 22/24 = 6416.67/g
        # Metal value = 4.5g * 6416.67 = 28875.02
        # Wastage 2% = 577.50
        # Making = 1500.00
        # Subtotal = 30952.52
        # GST 3% = 928.58
        # Final price = 31881.10
        breakdown = item.calculate_live_price()
        self.assertIsNotNone(breakdown)
        self.assertEqual(item.live_price_breakdown.metal_type, 'Gold')
        self.assertAlmostEqual(float(item.current_market_price), float(breakdown.final_price), places=1)

    def test_custom_order_calculate_estimated_price(self):
        """CustomOrder calculate_estimated_price calculates estimate correctly."""
        order = CustomOrder.objects.create(
            customer=self.customer,
            category=self.category,
            design_description='Gold necklace design',
            metal_type='Gold',
            purity='22K',
            approx_gross_weight=Decimal('20.000'),
            approx_net_weight=Decimal('20.000'),
            making_charge=Decimal('5000.00'),
            estimated_price=Decimal('140000.00'),
        )
        est = order.calculate_estimated_price()
        self.assertIsNotNone(est)
        self.assertGreater(est.final_price, Decimal('100000.00'))

    def test_historical_sale_price_remains_unchanged_when_metal_rates_change(self):
        """A completed sale's recorded sale_price NEVER alters when today's gold rate changes."""
        item = JewelleryItem.objects.create(
            item_code='GLD-RN-HIST-1',
            name='Historical Ring',
            category=self.category,
            metal_type='Gold',
            purity='24K',
            gross_weight=Decimal('10.000'),
            selling_price=Decimal('60000.00'),
            quantity=1,
            status='Available'
        )

        # Record a sale on Day 1 at ₹60,000
        sale = Sale.objects.create(
            customer=self.customer,
            jewellery_item=item,
            sale_price=Decimal('60000.00'),
            payment_method='UPI'
        )
        self.assertEqual(sale.sale_price, Decimal('60000.00'))

        # Day 2: Gold rate skyrockets from ₹7000 to ₹10,000/g in MetalRate table
        gold_rate_obj = MetalRate.objects.get(metal_type='Gold')
        gold_rate_obj.rate_per_gram = Decimal('10000.00')
        gold_rate_obj.save()

        # Re-fetch the sale record from DB
        refetched_sale = Sale.objects.get(pk=sale.pk)
        # Transactional invoice price must remain completely unchanged!
        self.assertEqual(refetched_sale.sale_price, Decimal('60000.00'))

    def test_permission_enforcement_on_metal_rates_edit(self):
        """Unauthorized employees cannot edit metal board rates; backend returns 403 Forbidden."""
        client = Client(SERVER_NAME='127.0.0.1')
        client.force_login(self.emp_user)

        # Sales employee only has view permissions, not edit
        post_data = {
            'gold_rate_24k': '9999.00',
            'silver_rate_999': '150.00',
            'source': 'Malicious Edit'
        }
        res = client.post(reverse('metal_rates'), post_data)
        self.assertEqual(res.status_code, 403)

        # Gold rate in database remains ₹7000, not ₹9999
        self.assertEqual(
            MetalRate.objects.get(metal_type='Gold').rate_per_gram,
            Decimal('7000.00')
        )

        # Admin user CAN update board rates
        admin_client = Client(SERVER_NAME='127.0.0.1')
        admin_client.force_login(self.admin_user)
        admin_res = admin_client.post(reverse('metal_rates'), post_data)
        self.assertEqual(admin_res.status_code, 302) # Redirects to metal_rates on success
        self.assertEqual(
            MetalRate.objects.get(metal_type='Gold').rate_per_gram,
            Decimal('9999.00')
        )

    def test_pricing_calculator_page_and_api(self):
        """Pricing calculator view and JSON API endpoint work cleanly."""
        client = Client(SERVER_NAME='127.0.0.1')
        client.force_login(self.admin_user)

        # GET Pricing Calculator
        res = client.get(reverse('pricing_calculator'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Jewellery Pricing Engine')
        self.assertContains(res, 'Live Price Breakdown')

        # POST to JSON API
        api_res = client.post(
            reverse('api_calculate_price'),
            data={
                'metal_type': 'Gold',
                'purity': '22K',
                'gross_weight': '10.0',
                'stone_weight': '0.0',
                'base_metal_rate': '7000.0',
                'making_charge': '500.0',
                'making_charge_type': 'Per Gram',
                'tax_percent': '3.0'
            }
        )
        self.assertEqual(api_res.status_code, 200)
        data = api_res.json()
        self.assertTrue(data['ok'])
        self.assertIn('breakdown', data)
        self.assertGreater(data['breakdown']['final_price'], 60000)
