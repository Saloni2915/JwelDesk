import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import Tenant, CompanySettings
from accounts.forms import JewelDeskSignUpForm
from customers.models import Customer
from custom_orders.models import CustomOrder
from custom_orders.forms import CustomOrderForm
from inventory.models import Category, JewelleryItem
from karigar.models import Karigar, KarigarWorkAssignment
from karigar.forms import KarigarWorkAssignmentForm
from sales.models import Sale, Enquiry
from sales.forms import SaleForm, StandalonePaymentForm
from team.models import Role, Employee, Branch, EmployeePermission

User = get_user_model()


class MultiTenantBaseTestCase(TestCase):
    """Base test fixture setting up two isolated tenants with full domain data."""

    def setUp(self):
        super().setUp()
        Role.ensure_builtin_roles()
        self.admin_role = Role.objects.get(name=Role.ROLE_ADMIN)
        self.sales_role = Role.objects.get(name=Role.ROLE_SALES)

        # ---------------------------------------------------------------------
        # TENANT A: "Aura Jewellers"
        # ---------------------------------------------------------------------
        self.user_a = User.objects.create_user(
            username='aura_owner',
            email='aura@example.com',
            password='Password123!',
            first_name='Aura',
            last_name='Admin',
            is_staff=False,
            is_superuser=False,
        )
        self.tenant_a = Tenant.objects.create(
            name='Aura Jewellers',
            owner=self.user_a,
            slug='aura-jewellers',
            is_active=True,
        )
        self.settings_a = CompanySettings.objects.create(
            tenant=self.tenant_a,
            company_name='Aura Jewellers',
            phone='9876543210',
            email='aura@example.com',
        )
        self.emp_owner_a = Employee.objects.create(
            user=self.user_a,
            tenant=self.tenant_a,
            full_name='Aura Owner',
            email='aura@example.com',
            role=self.admin_role,
            status=Employee.STATUS_ACTIVE,
            designation='Store Owner / Admin',
        )
        self.emp_owner_a.apply_default_permissions()

        self.branch_a = Branch.objects.create(
            tenant=self.tenant_a,
            name='Aura Main Showroom',
            is_active=True,
        )
        self.cat_a = Category.objects.create(
            tenant=self.tenant_a,
            name='Aura Crown Rings',
            description='Aura Rings',
        )
        self.item_a = JewelleryItem.objects.create(
            tenant=self.tenant_a,
            category=self.cat_a,
            item_code='AUR-RNG-001',
            tag_number='TAG-AUR-001',
            name='Aura Gold Solitaire Ring',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('5.500'),
            net_weight=Decimal('5.200'),
            making_charge=Decimal('800.00'),
            making_charge_type='Per Gram',
            selling_price=Decimal('45000.00'),
            status='Available',
            quantity=1,
        )
        self.cust_a = Customer.objects.create(
            tenant=self.tenant_a,
            name='Customer Alpha',
            mobile='9000000001',
            email='alpha@client.com',
        )
        self.sale_a = Sale.objects.create(
            tenant=self.tenant_a,
            customer=self.cust_a,
            jewellery_item=self.item_a,
            sale_price=Decimal('45000.00'),
            payment_method='Cash',
        )
        self.enquiry_a = Enquiry.objects.create(
            tenant=self.tenant_a,
            customer=self.cust_a,
            category=self.cat_a,
            interested_item='Aura Diamond Band',
            budget=Decimal('30000.00'),
            status='Open',
        )
        self.custom_order_a = CustomOrder.objects.create(
            tenant=self.tenant_a,
            customer=self.cust_a,
            category=self.cat_a,
            order_number='ORD-AUR-0001',
            metal_type='Gold',
            purity='22K',
            approx_gross_weight=Decimal('10.000'),
            approx_net_weight=Decimal('9.500'),
            estimated_price=Decimal('85000.00'),
            advance_amount=Decimal('15000.00'),
            status=CustomOrder.STATUS_ENQUIRY,
            design_description='Custom Temple Wedding Choker for Alpha',
        )
        self.karigar_a = Karigar.objects.create(
            tenant=self.tenant_a,
            karigar_code='KRG-AUR-01',
            name='Mahesh Artisan Alpha',
            mobile='9111111111',
            specialization='Kundan',
            status=Karigar.STATUS_ACTIVE,
        )

        # ---------------------------------------------------------------------
        # TENANT B: "Bhavani Jewellers"
        # ---------------------------------------------------------------------
        self.user_b = User.objects.create_user(
            username='bhavani_owner',
            email='bhavani@example.com',
            password='Password123!',
            first_name='Bhavani',
            last_name='Admin',
            is_staff=False,
            is_superuser=False,
        )
        self.tenant_b = Tenant.objects.create(
            name='Bhavani Jewellers',
            owner=self.user_b,
            slug='bhavani-jewellers',
            is_active=True,
        )
        self.settings_b = CompanySettings.objects.create(
            tenant=self.tenant_b,
            company_name='Bhavani Jewellers',
            phone='9876543222',
            email='bhavani@example.com',
        )
        self.emp_owner_b = Employee.objects.create(
            user=self.user_b,
            tenant=self.tenant_b,
            full_name='Bhavani Owner',
            email='bhavani@example.com',
            role=self.admin_role,
            status=Employee.STATUS_ACTIVE,
            designation='Store Owner / Admin',
        )
        self.emp_owner_b.apply_default_permissions()

        self.branch_b = Branch.objects.create(
            tenant=self.tenant_b,
            name='Bhavani Branch 1',
            is_active=True,
        )
        self.cat_b = Category.objects.create(
            tenant=self.tenant_b,
            name='Bhavani Royal Necklaces',
            description='Bhavani Necklaces',
        )
        self.item_b = JewelleryItem.objects.create(
            tenant=self.tenant_b,
            category=self.cat_b,
            item_code='BHV-NCK-001',
            tag_number='TAG-BHV-001',
            name='Bhavani Emerald Choker',
            metal_type='Gold',
            purity='22K',
            gross_weight=Decimal('22.000'),
            net_weight=Decimal('20.000'),
            making_charge=Decimal('1200.00'),
            making_charge_type='Per Gram',
            selling_price=Decimal('180000.00'),
            status='Available',
            quantity=1,
        )
        self.cust_b = Customer.objects.create(
            tenant=self.tenant_b,
            name='Customer Beta',
            mobile='9000000002',
            email='beta@client.com',
        )
        self.sale_b = Sale.objects.create(
            tenant=self.tenant_b,
            customer=self.cust_b,
            jewellery_item=self.item_b,
            sale_price=Decimal('180000.00'),
            payment_method='UPI',
        )
        self.enquiry_b = Enquiry.objects.create(
            tenant=self.tenant_b,
            customer=self.cust_b,
            category=self.cat_b,
            interested_item='Bhavani Antique Haram',
            budget=Decimal('250000.00'),
            status='Open',
        )
        self.custom_order_b = CustomOrder.objects.create(
            tenant=self.tenant_b,
            customer=self.cust_b,
            category=self.cat_b,
            order_number='ORD-BHV-0001',
            metal_type='Gold',
            purity='22K',
            approx_gross_weight=Decimal('35.000'),
            approx_net_weight=Decimal('32.000'),
            estimated_price=Decimal('280000.00'),
            advance_amount=Decimal('50000.00'),
            status=CustomOrder.STATUS_ENQUIRY,
            design_description='Custom Bridal Haram for Beta',
        )
        self.karigar_b = Karigar.objects.create(
            tenant=self.tenant_b,
            karigar_code='KRG-BHV-01',
            name='Ramesh Artisan Beta',
            mobile='9222222222',
            specialization='Plain Gold',
            status=Karigar.STATUS_ACTIVE,
        )


class PublicSignupSecurityTests(TestCase):
    """Test public signup flow: zero-escalation, automatic tenant creation and scoping."""

    def setUp(self):
        super().setUp()
        Role.ensure_builtin_roles()

    def test_signup_creates_isolated_tenant_and_non_staff_user(self):
        """Public signup must create an isolated tenant shop with is_staff=False and is_superuser=False."""
        post_data = {
            'first_name': 'Devendra Sharma',
            'shop_name': 'Royal Heritage Jewellers',
            'username': 'devendra_royal',
            'email': 'devendra@royaljewels.test',
            'password1': 'StrongP@ssw0rd2026',
            'password2': 'StrongP@ssw0rd2026',
        }
        response = self.client.post(reverse('signup'), post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # 1. User verification: strictly non-staff, non-superuser
        new_user = User.objects.get(username='devendra_royal')
        self.assertTrue(new_user.is_active)
        self.assertFalse(new_user.is_staff, "Tenant owner must NOT have is_staff=True (zero-escalation policy).")
        self.assertFalse(new_user.is_superuser, "Tenant owner must NOT have is_superuser=True.")
        self.assertEqual(new_user.email, 'devendra@royaljewels.test')

        # 2. Tenant verification
        tenant = Tenant.objects.get(owner=new_user)
        self.assertEqual(tenant.name, 'Royal Heritage Jewellers')
        self.assertTrue(tenant.slug.startswith('royal-heritage-jewellers'))
        self.assertTrue(tenant.is_active)

        # 3. CompanySettings verification
        settings = CompanySettings.objects.get(tenant=tenant)
        self.assertEqual(settings.company_name, 'Royal Heritage Jewellers')

        # 4. Employee profile verification
        emp = getattr(new_user, 'employee_profile', None)
        self.assertIsNotNone(emp)
        self.assertEqual(emp.tenant, tenant)
        self.assertIn(emp.role.name, (Role.ROLE_TENANT_ADMIN, Role.ROLE_ADMIN))
        self.assertEqual(emp.status, Employee.STATUS_ACTIVE)

        # 5. Verify request.tenant resolves to new tenant upon login
        self.client.force_login(new_user)
        dash_res = self.client.get(reverse('dashboard'))
        self.assertEqual(dash_res.status_code, 200)
        self.assertEqual(dash_res.context['request'].tenant, tenant)

    def test_new_tenant_owner_denied_django_admin_access(self):
        """Tenant owner with is_staff=False cannot access Django admin site."""
        post_data = {
            'first_name': 'Sanjay Verma',
            'shop_name': 'Verma Gold House',
            'username': 'sanjay_verma',
            'email': 'sanjay@vermajewels.test',
            'password1': 'StrongP@ssw0rd2026',
            'password2': 'StrongP@ssw0rd2026',
        }
        self.client.post(reverse('signup'), post_data)
        user = User.objects.get(username='sanjay_verma')
        self.client.force_login(user)

        # Admin route must reject or redirect to admin login
        admin_res = self.client.get('/admin/')
        # Django admin redirects non-staff authenticated users to login with ?next=/admin/
        self.assertEqual(admin_res.status_code, 302)
        self.assertIn('/admin/login/', admin_res.url)

    def test_duplicate_shop_names_produce_unique_tenant_slugs(self):
        """Multiple signups with the same store name must generate distinct slugs."""
        form1 = JewelDeskSignUpForm({
            'first_name': 'Owner One',
            'shop_name': 'Diamond Palace',
            'username': 'owner_one',
            'email': 'one@palace.test',
            'password1': 'StrongP@ssw0rd2026',
            'password2': 'StrongP@ssw0rd2026',
        })
        self.assertTrue(form1.is_valid(), form1.errors)
        u1 = form1.save()

        form2 = JewelDeskSignUpForm({
            'first_name': 'Owner Two',
            'shop_name': 'Diamond Palace',
            'username': 'owner_two',
            'email': 'two@palace.test',
            'password1': 'StrongP@ssw0rd2026',
            'password2': 'StrongP@ssw0rd2026',
        })
        self.assertTrue(form2.is_valid(), form2.errors)
        u2 = form2.save()

        t1 = Tenant.objects.get(owner=u1)
        t2 = Tenant.objects.get(owner=u2)
        self.assertNotEqual(t1.slug, t2.slug)
        self.assertNotEqual(t1.pk, t2.pk)


class TenantDataScopingTests(MultiTenantBaseTestCase):
    """Test strict list and dashboard scoping: Tenant B cannot view Tenant A records."""

    def test_inventory_views_scoped_to_tenant(self):
        """Inventory list and categories only display items belonging to active tenant."""
        self.client.force_login(self.user_b)

        # 1. Inventory list
        res_inv = self.client.get(reverse('inventory_list'))
        self.assertEqual(res_inv.status_code, 200)
        self.assertContains(res_inv, self.item_b.name)
        self.assertNotContains(res_inv, self.item_a.name)

        # 2. Category list
        res_cat = self.client.get(reverse('category_list'))
        self.assertEqual(res_cat.status_code, 200)
        self.assertContains(res_cat, self.cat_b.name)
        self.assertNotContains(res_cat, self.cat_a.name)

    def test_customer_views_scoped_to_tenant(self):
        """Customer list view only displays customers belonging to active tenant."""
        self.client.force_login(self.user_b)
        res_cust = self.client.get(reverse('customer_list'))
        self.assertEqual(res_cust.status_code, 200)
        self.assertContains(res_cust, self.cust_b.name)
        self.assertNotContains(res_cust, self.cust_a.name)

    def test_sales_and_enquiry_views_scoped_to_tenant(self):
        """Sales and enquiry lists only show records for the authenticated tenant."""
        self.client.force_login(self.user_b)

        # Sales list
        res_sales = self.client.get(reverse('sale_list'))
        self.assertEqual(res_sales.status_code, 200)
        self.assertContains(res_sales, self.cust_b.name)
        self.assertNotContains(res_sales, self.cust_a.name)

        # Enquiries list
        res_enq = self.client.get(reverse('enquiry_list'))
        self.assertEqual(res_enq.status_code, 200)
        self.assertContains(res_enq, self.enquiry_b.interested_item)
        self.assertNotContains(res_enq, self.enquiry_a.interested_item)

    def test_custom_orders_scoped_to_tenant(self):
        """Custom orders list only displays orders belonging to active tenant."""
        self.client.force_login(self.user_b)
        res_co = self.client.get(reverse('custom_orders:custom_order_list'))
        self.assertEqual(res_co.status_code, 200)
        self.assertContains(res_co, self.custom_order_b.order_number)
        self.assertNotContains(res_co, self.custom_order_a.order_number)

    def test_karigar_views_scoped_to_tenant(self):
        """Karigar directory only displays artisans belonging to active tenant."""
        self.client.force_login(self.user_b)
        res_krg = self.client.get(reverse('karigar:karigar_list'))
        self.assertEqual(res_krg.status_code, 200)
        self.assertContains(res_krg, self.karigar_b.name)
        self.assertNotContains(res_krg, self.karigar_a.name)

    def test_team_views_scoped_to_tenant(self):
        """Staff directory only displays employees belonging to active tenant."""
        self.client.force_login(self.user_b)
        res_team = self.client.get(reverse('team:employee_list'))
        self.assertEqual(res_team.status_code, 200)
        self.assertContains(res_team, self.emp_owner_b.full_name)
        self.assertNotContains(res_team, self.emp_owner_a.full_name)

    def test_dashboard_metrics_scoped_to_tenant(self):
        """Dashboard totals and charts strictly compute values from current tenant."""
        self.client.force_login(self.user_b)
        res_dash = self.client.get(reverse('dashboard'))
        self.assertEqual(res_dash.status_code, 200)
        # Context metrics must reflect only Tenant B
        self.assertEqual(res_dash.context['total_items'], 1)
        self.assertEqual(res_dash.context['available_items'], 1)
        self.assertEqual(Decimal(str(res_dash.context['total_sales_amount'])), Decimal('180000.00'))


class CrossTenantURLTamperingTests(MultiTenantBaseTestCase):
    """Test protection against URL tampering: cross-tenant access returns HTTP 404 or 403."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user_b)

    def test_inventory_cross_tenant_access_returns_404(self):
        """Accessing Tenant A's inventory item from Tenant B session returns 404."""
        # Detail view
        res_detail = self.client.get(reverse('inventory_detail', kwargs={'pk': self.item_a.pk}))
        self.assertEqual(res_detail.status_code, 404)

        # Edit view
        res_edit = self.client.get(reverse('inventory_edit', kwargs={'pk': self.item_a.pk}))
        self.assertEqual(res_edit.status_code, 404)

        # Delete view
        res_del = self.client.post(reverse('inventory_delete', kwargs={'pk': self.item_a.pk}))
        self.assertEqual(res_del.status_code, 404)

    def test_customer_cross_tenant_access_returns_404(self):
        """Accessing Tenant A's customer profile from Tenant B session returns 404."""
        # Detail view
        res_detail = self.client.get(reverse('customer_detail', kwargs={'pk': self.cust_a.pk}))
        self.assertEqual(res_detail.status_code, 404)

        # Edit view
        res_edit = self.client.get(reverse('customer_edit', kwargs={'pk': self.cust_a.pk}))
        self.assertEqual(res_edit.status_code, 404)

        # Delete view
        res_del = self.client.post(reverse('customer_delete', kwargs={'pk': self.cust_a.pk}))
        self.assertEqual(res_del.status_code, 404)

    def test_sale_cross_tenant_access_returns_404(self):
        """Accessing Tenant A's sale or invoice from Tenant B session returns 404."""
        # Sale receipt/detail view
        res_detail = self.client.get(reverse('sale_detail', kwargs={'pk': self.sale_a.pk}))
        self.assertEqual(res_detail.status_code, 404)

        # Invoice PDF download view
        res_pdf = self.client.get(reverse('sale_invoice_pdf', kwargs={'pk': self.sale_a.pk}))
        self.assertEqual(res_pdf.status_code, 404)

    def test_enquiry_cross_tenant_access_returns_404(self):
        """Accessing Tenant A's enquiry from Tenant B session returns 404."""
        res_detail = self.client.get(reverse('enquiry_detail', kwargs={'pk': self.enquiry_a.pk}))
        self.assertEqual(res_detail.status_code, 404)

        res_edit = self.client.get(reverse('enquiry_edit', kwargs={'pk': self.enquiry_a.pk}))
        self.assertEqual(res_edit.status_code, 404)

    def test_custom_order_cross_tenant_access_returns_404(self):
        """Accessing Tenant A's custom order from Tenant B session returns 404."""
        res_detail = self.client.get(reverse('custom_orders:custom_order_detail', kwargs={'pk': self.custom_order_a.pk}))
        self.assertEqual(res_detail.status_code, 404)

        res_edit = self.client.get(reverse('custom_orders:custom_order_edit', kwargs={'pk': self.custom_order_a.pk}))
        self.assertEqual(res_edit.status_code, 404)

    def test_karigar_cross_tenant_access_returns_404(self):
        """Accessing Tenant A's karigar profile from Tenant B session returns 404."""
        res_detail = self.client.get(reverse('karigar:karigar_detail', kwargs={'pk': self.karigar_a.pk}))
        self.assertEqual(res_detail.status_code, 404)

        res_edit = self.client.get(reverse('karigar:karigar_edit', kwargs={'pk': self.karigar_a.pk}))
        self.assertEqual(res_edit.status_code, 404)

    def test_employee_cross_tenant_access_returns_404(self):
        """Accessing Tenant A's employee profile from Tenant B session returns 404."""
        res_detail = self.client.get(reverse('team:employee_detail', kwargs={'pk': self.emp_owner_a.pk}))
        self.assertEqual(res_detail.status_code, 404)

        res_edit = self.client.get(reverse('team:employee_edit', kwargs={'pk': self.emp_owner_a.pk}))
        self.assertEqual(res_edit.status_code, 404)


class CrossTenantFKInjectionTests(MultiTenantBaseTestCase):
    """Test validation guards against submitting another tenant's foreign key IDs."""

    def test_sale_form_rejects_foreign_customer_or_item(self):
        """SaleForm rejects customer or jewellery piece belonging to another tenant."""
        # Available item in Tenant A
        item_a2 = JewelleryItem.objects.create(
            tenant=self.tenant_a,
            category=self.cat_a,
            item_code='AUR-RNG-002',
            tag_number='TAG-AUR-002',
            name='Aura Silver Band',
            metal_type='Silver',
            purity='925',
            gross_weight=Decimal('4.000'),
            net_weight=Decimal('4.000'),
            making_charge=Decimal('200.00'),
            making_charge_type='Fixed Amount',
            selling_price=Decimal('2500.00'),
            status='Available',
            quantity=1,
        )

        # Attempt to inject Tenant B customer into Tenant A's SaleForm
        form_cross_cust = SaleForm(
            data={
                'customer': self.cust_b.pk,
                'jewellery_item': item_a2.pk,
                'sale_price': '2500.00',
                'payment_method': 'Cash',
            },
            tenant=self.tenant_a,
        )
        self.assertFalse(form_cross_cust.is_valid(), "Form must reject cross-tenant customer.")
        self.assertIn('customer', form_cross_cust.errors)

        # Attempt to inject Tenant B item into Tenant A's SaleForm
        form_cross_item = SaleForm(
            data={
                'customer': self.cust_a.pk,
                'jewellery_item': self.item_b.pk,
                'sale_price': '180000.00',
                'payment_method': 'Cash',
            },
            tenant=self.tenant_a,
        )
        self.assertFalse(form_cross_item.is_valid(), "Form must reject cross-tenant inventory item.")
        self.assertIn('jewellery_item', form_cross_item.errors)

    def test_custom_order_form_rejects_foreign_customer(self):
        """CustomOrderForm rejects customer belonging to another tenant."""
        form = CustomOrderForm(
            data={
                'customer': self.cust_b.pk,
                'category': self.cat_a.pk,
                'metal_type': 'Gold',
                'purity': '22K',
                'approx_gross_weight': '12.000',
                'approx_net_weight': '11.500',
                'making_charge': '500.00',
                'estimated_price': '95000.00',
                'advance_amount': '10000.00',
                'design_description': 'Injected order with Tenant B customer',
            },
            tenant=self.tenant_a,
        )
        self.assertFalse(form.is_valid(), "Form must reject cross-tenant customer.")
        self.assertIn('customer', form.errors)

    def test_karigar_assignment_form_rejects_foreign_karigar_or_customer(self):
        """KarigarWorkAssignmentForm rejects artisan or customer belonging to another tenant."""
        form_cross_krg = KarigarWorkAssignmentForm(
            data={
                'karigar': self.karigar_b.pk,  # Artisan from Tenant B
                'customer': self.cust_a.pk,
                'work_type': 'Custom Manufacture',
                'priority': 'Medium',
                'description': 'Cross-tenant assignment test',
                'metal_type': 'Gold',
                'purity': '22K',
                'gross_weight_issued': '15.000',
                'stone_weight_issued': '0.000',
                'wastage_allowed_percent': '1.50',
                'making_charge_type': 'per_gram',
                'making_charge_rate': '350.00',
                'issue_date': datetime.date.today().isoformat(),
                'expected_completion_date': (datetime.date.today() + datetime.timedelta(days=7)).isoformat(),
            },
            tenant=self.tenant_a,
        )
        self.assertFalse(form_cross_krg.is_valid(), "Form must reject cross-tenant artisan.")
        self.assertIn('karigar', form_cross_krg.errors)

    def test_standalone_payment_form_rejects_foreign_sale(self):
        """StandalonePaymentForm rejects sale belonging to another tenant."""
        form = StandalonePaymentForm(
            data={
                'sale': self.sale_b.pk,  # Sale from Tenant B
                'amount': '1000.00',
                'payment_method': 'Cash',
            },
            tenant=self.tenant_a,
        )
        self.assertFalse(form.is_valid(), "Form must reject cross-tenant sale.")
        self.assertIn('sale', form.errors)


class RBACModuleSecurityTests(MultiTenantBaseTestCase):
    """Test server-side RBAC without staff bypasses or module exemptions."""

    def setUp(self):
        super().setUp()
        # Create non-admin Sales Associate in Tenant A
        self.sales_user_a = User.objects.create_user(
            username='sales_rep_a',
            email='salesrep@aura.test',
            password='Password123!',
            first_name='Rahul',
            last_name='Sales',
            is_staff=False,
            is_superuser=False,
        )
        self.sales_emp_a = Employee.objects.create(
            user=self.sales_user_a,
            tenant=self.tenant_a,
            full_name='Rahul Sales Associate',
            email='salesrep@aura.test',
            role=self.sales_role,
            status=Employee.STATUS_ACTIVE,
            designation='Counter Sales',
        )
        # Explicit permissions: view and add on Sales module ONLY
        EmployeePermission.objects.create(
            employee=self.sales_emp_a,
            module=EmployeePermission.MODULE_SALES,
            can_view=True,
            can_add=True,
            can_edit=False,
            can_delete=False,
        )

    def test_sales_employee_authorized_for_sales_views(self):
        """Sales associate can view sales list and add sales."""
        self.client.force_login(self.sales_user_a)
        res = self.client.get(reverse('sale_list'))
        self.assertEqual(res.status_code, 200)

    def test_sales_employee_blocked_from_team_management_with_403(self):
        """Sales associate without team permissions is rejected with HTTP 403."""
        self.client.force_login(self.sales_user_a)
        res_list = self.client.get(reverse('team:employee_list'))
        self.assertEqual(res_list.status_code, 403)

        res_create = self.client.get(reverse('team:employee_create'))
        self.assertEqual(res_create.status_code, 403)

        res_roles = self.client.get(reverse('team:role_list'))
        self.assertEqual(res_roles.status_code, 403)

    def test_sales_employee_blocked_from_karigar_module_with_403(self):
        """Sales associate without karigar permissions is rejected with HTTP 403."""
        self.client.force_login(self.sales_user_a)
        res_list = self.client.get(reverse('karigar:karigar_list'))
        self.assertEqual(res_list.status_code, 403)

        res_create = self.client.get(reverse('karigar:karigar_create'))
        self.assertEqual(res_create.status_code, 403)

    def test_sales_employee_cannot_manage_permissions_or_escalate_privilege(self):
        """Non-admin employee attempting to access permission editing is rejected with 403."""
        self.client.force_login(self.sales_user_a)
        perm_url = reverse('team:employee_permissions', kwargs={'pk': self.sales_emp_a.pk})
        res = self.client.get(perm_url)
        self.assertEqual(res.status_code, 403)
