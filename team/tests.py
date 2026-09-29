"""
team/tests.py
-------------
Comprehensive test suite for JewelDesk Team / Employee Management module.
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .forms import EmployeeCreateForm, EmployeeEditForm, PermissionForm
from .models import Branch, Employee, EmployeePermission, Role

User = get_user_model()


class TeamModuleTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin_user = User.objects.create_superuser(
            username='adminuser',
            email='admin@jeweldesk.test',
            password='Password123!',
        )

        # Non-staff user
        self.regular_user = User.objects.create_user(
            username='regularuser',
            email='regular@jeweldesk.test',
            password='Password123!',
            is_staff=False,
        )

        # Roles (seeded via data migration, but ensure they exist in test DB)
        self.admin_role, _ = Role.objects.get_or_create(
            name='Admin',
            defaults={'is_admin_role': True, 'can_access_all_branches': True}
        )
        self.sales_role, _ = Role.objects.get_or_create(
            name='Sales Executive',
            defaults={'is_admin_role': False, 'can_access_all_branches': False}
        )

        # Branch
        self.main_branch = Branch.objects.create(
            name='Main Showroom',
            address='101 Jewel Street',
            phone='9876543210',
            is_active=True,
        )

    def test_default_roles_exist(self):
        """Verify standard jewellery business roles."""
        self.assertTrue(Role.objects.filter(name='Admin').exists())
        self.assertTrue(Role.objects.filter(name='Sales Executive').exists())

    def test_create_employee_with_linked_user(self):
        """Creating an employee must create and link a Django User account atomically."""
        form_data = {
            'username': 'johnsales',
            'password1': 'Secret@123',
            'password2': 'Secret@123',
            'full_name': 'John Sales',
            'email': 'john@jeweldesk.test',
            'mobile': '9898989898',
            'role': self.sales_role.pk,
            'department': 'Sales',
            'status': Employee.STATUS_ACTIVE,
            'branches': [self.main_branch.pk],
        }
        form = EmployeeCreateForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)

        emp = form.save(created_by=self.admin_user)

        self.assertIsNotNone(emp.pk)
        self.assertTrue(emp.employee_id.startswith('EMP-'))
        self.assertEqual(emp.user.username, 'johnsales')
        self.assertEqual(emp.user.email, 'john@jeweldesk.test')
        self.assertTrue(emp.user.is_staff)  # Back-office access
        self.assertTrue(emp.user.check_password('Secret@123'))

        # Verify employee is able to login
        login_success = self.client.login(username='johnsales', password='Secret@123')
        self.assertTrue(login_success)
        self.client.logout()

        # Verify default permissions were auto-applied for Sales role
        sales_perms = emp.permissions.filter(module='sales').first()
        self.assertIsNotNone(sales_perms)
        self.assertTrue(sales_perms.can_view)
        self.assertTrue(sales_perms.can_add)

        # Verify branch link
        self.assertIn(self.main_branch, emp.branches.all())

    def test_employee_deactivation_disables_login(self):
        """Deactivating an employee sets employee status and user is_active to False."""
        user = User.objects.create_user(
            username='empdeact',
            email='empdeact@test.com',
            password='Password123!',
            is_staff=True,
        )
        emp = Employee.objects.create(
            user=user,
            full_name='Deact User',
            email=user.email,
            role=self.sales_role,
            status=Employee.STATUS_ACTIVE,
        )

        emp.deactivate()
        emp.refresh_from_db()
        user.refresh_from_db()

        self.assertEqual(emp.status, Employee.STATUS_INACTIVE)
        self.assertFalse(user.is_active)

        # Deactivated user cannot log in
        login_success = self.client.login(username='empdeact', password='Password123!')
        self.assertFalse(login_success)

    def test_admin_employee_list_view(self):
        """Admin can access employee list view."""
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('team:employee_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Employees')

    def test_regular_user_cannot_access_employee_list(self):
        """Non-staff users are redirected away from employee list."""
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse('team:employee_list'))
        # Should redirect to login because user_passes_test fails
        self.assertEqual(response.status_code, 302)

    def test_employee_permissions_view(self):
        """Admin can update employee module permissions."""
        user = User.objects.create_user(username='permtarget', password='Password123!', is_staff=True)
        emp = Employee.objects.create(
            user=user,
            full_name='Perm Target',
            email='perm@test.com',
            role=self.sales_role,
        )
        emp.apply_default_permissions()

        self.client.force_login(self.admin_user)
        url = reverse('team:employee_permissions', kwargs={'pk': emp.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Submit change: enable custom_orders view
        post_data = {
            'custom_orders__view': 'on',
            'custom_orders__add': 'on',
        }
        post_resp = self.client.post(url, post_data)
        self.assertEqual(post_resp.status_code, 302)

        perm = emp.permissions.get(module='custom_orders')
        self.assertTrue(perm.can_view)
        self.assertTrue(perm.can_add)

    def test_branch_management(self):
        """Admin can create and list branches."""
        self.client.force_login(self.admin_user)

        # Create branch via POST
        create_url = reverse('team:branch_create')
        res = self.client.post(create_url, {
            'name': 'North Outlet',
            'phone': '9123456780',
            'address': 'Sector 17, North City',
            'is_active': True,
        })
        self.assertEqual(res.status_code, 302)
        self.assertTrue(Branch.objects.filter(name='North Outlet').exists())

        # List branches
        list_res = self.client.get(reverse('team:branch_list'))
        self.assertEqual(list_res.status_code, 200)
        self.assertContains(list_res, 'North Outlet')
