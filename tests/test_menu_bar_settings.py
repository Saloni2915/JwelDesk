from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
import json

from accounts.models import Tenant, CompanySettings
from team.models import Role, Employee

User = get_user_model()


class MenuBarSettingsTestCase(TestCase):
    """Test suite for sidebar menu bar hide/unhide functionality."""

    def setUp(self):
        super().setUp()
        Role.ensure_builtin_roles()
        self.admin_role = Role.objects.get(name=Role.ROLE_ADMIN)

        # Tenant A
        self.user_a = User.objects.create_user(
            username='shop_a_admin',
            email='shop_a@example.com',
            password='TestPassword123!',
        )
        self.tenant_a = Tenant.objects.create(
            name='Shop Alpha',
            owner=self.user_a,
            slug='shop-alpha',
            is_active=True,
        )
        self.settings_a = CompanySettings.objects.create(
            tenant=self.tenant_a,
            company_name='Shop Alpha',
        )
        self.emp_a = Employee.objects.create(
            user=self.user_a,
            tenant=self.tenant_a,
            full_name='Alpha Admin',
            email='shop_a@example.com',
            role=self.admin_role,
            status=Employee.STATUS_ACTIVE,
        )
        self.emp_a.apply_default_permissions()

        # Tenant B
        self.user_b = User.objects.create_user(
            username='shop_b_admin',
            email='shop_b@example.com',
            password='TestPassword123!',
        )
        self.tenant_b = Tenant.objects.create(
            name='Shop Beta',
            owner=self.user_b,
            slug='shop-beta',
            is_active=True,
        )
        self.settings_b = CompanySettings.objects.create(
            tenant=self.tenant_b,
            company_name='Shop Beta',
        )
        self.emp_b = Employee.objects.create(
            user=self.user_b,
            tenant=self.tenant_b,
            full_name='Beta Admin',
            email='shop_b@example.com',
            role=self.admin_role,
            status=Employee.STATUS_ACTIVE,
        )
        self.emp_b.apply_default_permissions()

        self.client_a = Client()
        self.client_a.login(username='shop_a_admin', password='TestPassword123!')

        self.client_b = Client()
        self.client_b.login(username='shop_b_admin', password='TestPassword123!')

    def test_model_hidden_menus_helper_methods(self):
        """Verify model methods for adding, removing, and checking hidden menus."""
        settings = self.settings_a
        self.assertEqual(settings.get_hidden_menus(), [])
        self.assertFalse(settings.is_menu_hidden('sales'))

        # Hide 'sales'
        settings.set_menu_hidden('sales', True)
        self.assertEqual(settings.get_hidden_menus(), ['sales'])
        self.assertTrue(settings.is_menu_hidden('sales'))

        # Hide 'reports'
        settings.set_menu_hidden('reports', True)
        self.assertEqual(set(settings.get_hidden_menus()), {'sales', 'reports'})
        self.assertTrue(settings.is_menu_hidden('reports'))

        # Unhide 'sales'
        settings.set_menu_hidden('sales', False)
        self.assertEqual(settings.get_hidden_menus(), ['reports'])
        self.assertFalse(settings.is_menu_hidden('sales'))
        self.assertTrue(settings.is_menu_hidden('reports'))

    def test_multitenant_menu_settings_isolation(self):
        """Hiding a menu for Tenant A should not affect Tenant B."""
        self.settings_a.set_menu_hidden('karigar', True, commit=True)
        self.settings_a.refresh_from_db()
        self.settings_b.refresh_from_db()

        self.assertTrue(self.settings_a.is_menu_hidden('karigar'))
        self.assertFalse(self.settings_b.is_menu_hidden('karigar'))
        self.assertEqual(self.settings_b.get_hidden_menus(), [])

    def test_menu_settings_page_get(self):
        """GET /settings/menu/ renders the menu options and displays KPI counts."""
        url = reverse('accounts:menu_settings')
        resp = self.client_a.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Menu Bar &amp; Sub-Options Visibility')
        self.assertContains(resp, 'Total Menu Modules')
        self.assertContains(resp, 'Custom Orders')
        self.assertContains(resp, 'Karigar &amp; Workshop')

    def test_menu_settings_post_save(self):
        """POST /settings/menu/ saves hidden menu items list."""
        url = reverse('accounts:menu_settings')
        resp = self.client_a.post(url, {
            'hidden_items': ['sales', 'customers', 'karigar']
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.settings_a.refresh_from_db()
        hidden = self.settings_a.get_hidden_menus()
        self.assertIn('sales', hidden)
        self.assertIn('customers', hidden)
        self.assertIn('karigar', hidden)
        self.assertNotIn('inventory', hidden)

    def test_menu_settings_unhide_all_action(self):
        """Submitting action=unhide_all clears all hidden items."""
        self.settings_a.hidden_menu_items = 'sales,inventory,reports'
        self.settings_a.save()

        url = reverse('accounts:menu_settings')
        resp = self.client_a.post(url, {'action': 'unhide_all'}, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.settings_a.refresh_from_db()
        self.assertEqual(self.settings_a.get_hidden_menus(), [])

    def test_menu_toggle_api(self):
        """AJAX POST /settings/menu/toggle/ toggles single menu item status."""
        url = reverse('accounts:menu_toggle_api')

        # 1. Turn Hide ON for 'reports'
        resp = self.client_a.post(
            url,
            data=json.dumps({'menu_key': 'reports', 'hide': True}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_hidden'])

        self.settings_a.refresh_from_db()
        self.assertTrue(self.settings_a.is_menu_hidden('reports'))

        # 2. Turn Hide OFF (unhide) for 'reports'
        resp = self.client_a.post(
            url,
            data=json.dumps({'menu_key': 'reports', 'hide': False}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertFalse(data['is_hidden'])

        self.settings_a.refresh_from_db()
        self.assertFalse(self.settings_a.is_menu_hidden('reports'))

    def test_sidebar_rendering_hides_and_unhides_items(self):
        """When an item is hidden, it is excluded from sidebar navigation HTML."""
        # Baseline: All visible
        resp = self.client_a.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-menu-key="sales"')
        self.assertContains(resp, 'data-menu-key="karigar"')

        # Hide 'sales' and 'karigar'
        self.settings_a.hidden_menu_items = 'sales,karigar'
        self.settings_a.save()

        resp = self.client_a.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'data-menu-key="sales"')
        self.assertNotContains(resp, 'data-menu-key="karigar"')
        # Other items remain visible
        self.assertContains(resp, 'data-menu-key="inventory"')

        # Tenant B still sees 'sales' and 'karigar'
        resp_b = self.client_b.get(reverse('dashboard'))
        self.assertEqual(resp_b.status_code, 200)
        self.assertContains(resp_b, 'data-menu-key="sales"')
        self.assertContains(resp_b, 'data-menu-key="karigar"')

    def test_language_defaults_and_switching(self):
        """Verify default language is English and switching to Hindi persists in DB, session, and cookies."""
        # 1. Default is 'en'
        self.assertEqual(self.settings_a.language, 'en')

        # 2. Switch to Hindi via POST
        url = reverse('accounts:set_language')
        resp = self.client_a.post(url, {'language': 'hi'}, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.settings_a.refresh_from_db()
        self.assertEqual(self.settings_a.language, 'hi')
        self.assertEqual(self.client_a.session.get('django_language'), 'hi')
        self.assertIn('django_language', self.client_a.cookies)
        self.assertEqual(self.client_a.cookies['django_language'].value, 'hi')

        # 3. Switching affects dashboard and menu settings template rendering
        dash_resp = self.client_a.get(reverse('dashboard'))
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, 'lang="hi"')
        self.assertContains(dash_resp, 'jd-lang-hi')
        self.assertContains(dash_resp, 'बिक्री एवं एक्सचेंज')
        self.assertContains(dash_resp, 'लॉग आउट')

        # Menu settings page renders Hindi names, descriptions, and controls
        menu_resp = self.client_a.get(reverse('accounts:menu_settings'))
        self.assertEqual(menu_resp.status_code, 200)
        self.assertContains(menu_resp, 'बिक्री एवं एक्सचेंज')
        self.assertNotContains(menu_resp, 'थोक व्यापार (B2B)')
        self.assertContains(menu_resp, 'मेनू बार दृश्यता')
        self.assertContains(menu_resp, 'नेविगेशन मेनू')
        self.assertContains(menu_resp, 'सभी बदलाव सहेजें')
        self.assertContains(menu_resp, 'मेनू मॉड्यूल विकल्प')
        self.assertContains(menu_resp, 'छिपाएं / दिखाएं नियंत्रण')

        # 4. Switch back to English via AJAX
        ajax_resp = self.client_a.post(
            url,
            data=json.dumps({'language': 'en'}),
            content_type='application/json'
        )
        self.assertEqual(ajax_resp.status_code, 200)
        ajax_data = ajax_resp.json()
        self.assertTrue(ajax_data['success'])
        self.assertEqual(ajax_data['language'], 'en')

        self.settings_a.refresh_from_db()
        self.assertEqual(self.settings_a.language, 'en')

        # English check
        menu_resp_en = self.client_a.get(reverse('accounts:menu_settings'))
        self.assertEqual(menu_resp_en.status_code, 200)
        self.assertContains(menu_resp_en, 'Sales &amp; Exchange')
        self.assertContains(menu_resp_en, 'Save All Changes')
        self.assertContains(menu_resp_en, 'Menu Module Option')

    def test_submenu_visibility_in_sidebar_and_isolation(self):
        """Hiding a specific sub-option hides only that sub-link, keeping parent module and other sub-links visible."""
        # 1. Baseline: both Tenant A and Tenant B have sub-option in dashboard
        dash_a = self.client_a.get(reverse('dashboard'))
        self.assertEqual(dash_a.status_code, 200)
        self.assertContains(dash_a, 'data-menu-key="sales"')
        self.assertContains(dash_a, 'data-submenu-key="sub_sales_add"')
        self.assertContains(dash_a, 'data-submenu-key="sub_sales_og_buyback"')

        dash_b = self.client_b.get(reverse('dashboard'))
        self.assertEqual(dash_b.status_code, 200)
        self.assertContains(dash_b, 'data-submenu-key="sub_sales_og_buyback"')

        # 2. Hide only 'sub_sales_og_buyback' for Tenant A
        self.settings_a.set_menu_hidden('sub_sales_og_buyback', True, commit=True)
        self.settings_a.refresh_from_db()
        self.assertTrue(self.settings_a.is_menu_hidden('sub_sales_og_buyback'))

        dash_a_after = self.client_a.get(reverse('dashboard'))
        self.assertEqual(dash_a_after.status_code, 200)
        # Parent module 'sales' is STILL visible
        self.assertContains(dash_a_after, 'data-menu-key="sales"')
        # Other sub-menu 'sub_sales_add' is STILL visible
        self.assertContains(dash_a_after, 'data-submenu-key="sub_sales_add"')
        # Target sub-menu 'sub_sales_og_buyback' is HIDDEN from Tenant A sidebar
        self.assertNotContains(dash_a_after, 'data-submenu-key="sub_sales_og_buyback"')

        # 3. Tenant B is completely unaffected (isolation)
        dash_b_after = self.client_b.get(reverse('dashboard'))
        self.assertEqual(dash_b_after.status_code, 200)
        self.assertContains(dash_b_after, 'data-menu-key="sales"')
        self.assertContains(dash_b_after, 'data-submenu-key="sub_sales_og_buyback"')

    def test_submenu_toggle_api(self):
        """AJAX API can toggle individual sub-option keys."""
        url = reverse('accounts:menu_toggle_api')

        # 1. Hide sub_pricing_rates
        resp = self.client_a.post(
            url,
            data=json.dumps({'menu_key': 'sub_pricing_rates', 'is_hidden': True}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_hidden'])
        self.assertEqual(data['menu_key'], 'sub_pricing_rates')

        self.settings_a.refresh_from_db()
        self.assertIn('sub_pricing_rates', self.settings_a.get_hidden_menus())

        # 2. Unhide sub_pricing_rates
        resp_unhide = self.client_a.post(
            url,
            data=json.dumps({'menu_key': 'sub_pricing_rates', 'is_hidden': False}),
            content_type='application/json'
        )
        self.assertEqual(resp_unhide.status_code, 200)
        data_unhide = resp_unhide.json()
        self.assertTrue(data_unhide['success'])
        self.assertFalse(data_unhide['is_hidden'])

        self.settings_a.refresh_from_db()
        self.assertNotIn('sub_pricing_rates', self.settings_a.get_hidden_menus())

    def test_menu_settings_page_sub_options_rendered(self):
        """Menu settings page renders sub-options with individual switches."""
        resp = self.client_a.get(reverse('accounts:menu_settings'))
        self.assertEqual(resp.status_code, 200)
        # Sub-option switches exist
        self.assertContains(resp, 'switch-sub_sales_add')
        self.assertContains(resp, 'switch-sub_sales_og_buyback')
        self.assertContains(resp, 'switch-sub_inventory_items')
        self.assertContains(resp, 'switch-sub_pricing_rates')
        self.assertContains(resp, 'sub-items-collapse')
    def test_retail_tenant_menu_settings_filtering(self):
        """Retail store sees retail modules and does NOT see wholesale in menu settings."""
        self.tenant_a.business_type = Tenant.TYPE_RETAIL
        self.tenant_a.save()

        url = reverse('accounts:menu_settings')
        resp = self.client_a.get(url)
        self.assertEqual(resp.status_code, 200)

        # Retail items are visible
        self.assertContains(resp, 'Sales &amp; Exchange')
        self.assertContains(resp, 'Customers')
        self.assertContains(resp, 'Custom Orders')
        self.assertContains(resp, 'switch-sub_sales_add')

        # Wholesale items are filtered out
        self.assertNotContains(resp, 'Wholesale &amp; B2B')
        self.assertNotContains(resp, 'switch-sub_wholesale_dashboard')
        self.assertNotContains(resp, 'switch-sub_reports_wholesale')

    def test_wholesale_tenant_menu_settings_filtering(self):
        """Wholesale store sees wholesale modules and does NOT see retail-only modules."""
        self.tenant_a.business_type = Tenant.TYPE_WHOLESALE
        self.tenant_a.save()

        url = reverse('accounts:menu_settings')
        resp = self.client_a.get(url)
        self.assertEqual(resp.status_code, 200)

        # Wholesale items are visible
        self.assertContains(resp, 'Wholesale &amp; B2B')
        self.assertContains(resp, 'switch-sub_wholesale_dashboard')
        self.assertContains(resp, 'switch-sub_reports_wholesale')

        # Retail-only items are filtered out from menu options table
        self.assertNotContains(resp, 'id="row-sales"')
        self.assertNotContains(resp, 'id="row-customers"')
        self.assertNotContains(resp, 'id="row-custom_orders"')
        self.assertNotContains(resp, 'switch-sub_sales_add')

    def test_hybrid_tenant_menu_settings_filtering(self):
        """Hybrid store (BOTH) sees both retail and wholesale modules in menu settings."""
        self.tenant_a.business_type = Tenant.TYPE_BOTH
        self.tenant_a.save()

        url = reverse('accounts:menu_settings')
        resp = self.client_a.get(url)
        self.assertEqual(resp.status_code, 200)

        # Both retail and wholesale items are visible
        self.assertContains(resp, 'Sales &amp; Exchange')
        self.assertContains(resp, 'Wholesale &amp; B2B')
        self.assertContains(resp, 'switch-sub_sales_add')
        self.assertContains(resp, 'switch-sub_wholesale_dashboard')

    def test_toggle_api_rejects_incompatible_business_model_menu(self):
        """Attempting to toggle a wholesale menu on a pure retail tenant returns 400 error."""
        self.tenant_a.business_type = Tenant.TYPE_RETAIL
        self.tenant_a.save()

        url = reverse('accounts:menu_toggle_api')
        resp = self.client_a.post(
            url,
            data=json.dumps({'menu_key': 'wholesale', 'is_hidden': True}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('not available for this business model', resp.json().get('error', ''))

