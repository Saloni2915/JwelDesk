"""
team/tests.py
-------------
Comprehensive test suite for JewelDesk Team / Employee Management module.
"""

from django.contrib.auth import authenticate, get_user_model
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
        self.assertEqual(emp.user.first_name, 'John')
        self.assertEqual(emp.user.last_name, 'Sales')
        self.assertTrue(emp.user.is_staff)  # Back-office access
        self.assertTrue(emp.user.is_active)

        # Password must be hashed, never stored in plain text
        self.assertNotEqual(emp.user.password, 'Secret@123')
        self.assertTrue(emp.user.password.startswith('pbkdf2_sha256$') or
                        emp.user.password.startswith('argon2') or
                        emp.user.password.startswith('bcrypt'))
        self.assertTrue(emp.user.check_password('Secret@123'))

        # authenticate() must succeed with username credentials
        user_by_username = authenticate(username='johnsales', password='Secret@123')
        self.assertIsNotNone(user_by_username)
        self.assertEqual(user_by_username.pk, emp.user.pk)

        # authenticate() must succeed with email credentials
        user_by_email = authenticate(username='john@jeweldesk.test', password='Secret@123')
        self.assertIsNotNone(user_by_email)
        self.assertEqual(user_by_email.pk, emp.user.pk)

        # Login view POST succeeds with username
        resp_user = self.client.post(reverse('accounts:login'), {
            'username': 'johnsales',
            'password': 'Secret@123',
        }, follow=True)
        self.assertTrue(resp_user.context['user'].is_authenticated)
        self.assertEqual(resp_user.context['user'].pk, emp.user.pk)
        self.client.logout()

        # Login view POST succeeds with email
        resp_email = self.client.post(reverse('accounts:login'), {
            'username': 'john@jeweldesk.test',
            'password': 'Secret@123',
        }, follow=True)
        self.assertTrue(resp_email.context['user'].is_authenticated)
        self.assertEqual(resp_email.context['user'].pk, emp.user.pk)
        self.client.logout()

        # Verify default permissions were auto-applied for Sales role
        sales_perms = emp.permissions.filter(module='sales').first()
        self.assertIsNotNone(sales_perms)
        self.assertTrue(sales_perms.can_view)
        self.assertTrue(sales_perms.can_add)

        # Verify branch link
        self.assertIn(self.main_branch, emp.branches.all())

    def test_wrong_password_rejected_for_employee(self):
        """Wrong password must be rejected by authenticate() and login view."""
        form_data = {
            'username': 'wrongpwuser',
            'password1': 'CorrectPass123!',
            'password2': 'CorrectPass123!',
            'full_name': 'Wrong Pass Test',
            'email': 'wrongpw@jeweldesk.test',
            'role': self.sales_role.pk,
            'department': 'Sales',
            'status': Employee.STATUS_ACTIVE,
        }
        form = EmployeeCreateForm(data=form_data)
        self.assertTrue(form.is_valid())
        emp = form.save(created_by=self.admin_user)

        # authenticate() returns None for wrong password
        self.assertIsNone(authenticate(username='wrongpwuser', password='BadPassword!'))
        self.assertIsNone(authenticate(username='wrongpw@jeweldesk.test', password='BadPassword!'))

        # Login view returns 200 with error
        resp = self.client.post(reverse('accounts:login'), {
            'username': 'wrongpwuser',
            'password': 'BadPassword!',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Invalid username or password')

    def test_inactive_employee_cannot_authenticate_or_login(self):
        """Inactive employees and their users must not be allowed to log in."""
        form_data = {
            'username': 'inactiveemp',
            'password1': 'SecretPass123!',
            'password2': 'SecretPass123!',
            'full_name': 'Inactive Person',
            'email': 'inactive@jeweldesk.test',
            'role': self.sales_role.pk,
            'department': 'Sales',
            'status': Employee.STATUS_INACTIVE,
        }
        form = EmployeeCreateForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        emp = form.save(created_by=self.admin_user)

        self.assertFalse(emp.user.is_active)

        # authenticate() must return None for inactive user
        self.assertIsNone(authenticate(username='inactiveemp', password='SecretPass123!'))
        self.assertIsNone(authenticate(username='inactive@jeweldesk.test', password='SecretPass123!'))

        # Login view must reject inactive employee
        resp = self.client.post(reverse('accounts:login'), {
            'username': 'inactiveemp',
            'password': 'SecretPass123!',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Invalid username or password')

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

        # Deactivated user cannot authenticate or log in
        self.assertIsNone(authenticate(username='empdeact', password='Password123!'))
        self.assertIsNone(authenticate(username='empdeact@test.com', password='Password123!'))

        resp = self.client.post(reverse('accounts:login'), {
            'username': 'empdeact',
            'password': 'Password123!',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Invalid username or password')

    def test_employee_edit_syncs_user_active_and_email(self):
        """Editing employee status via EmployeeEditForm syncs user.is_active and email."""
        form_data = {
            'username': 'editsync',
            'password1': 'SyncPass123!',
            'password2': 'SyncPass123!',
            'full_name': 'Edit Sync',
            'email': 'editsync@jeweldesk.test',
            'role': self.sales_role.pk,
            'department': 'Sales',
            'status': Employee.STATUS_ACTIVE,
        }
        form = EmployeeCreateForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        emp = form.save(created_by=self.admin_user)
        self.assertTrue(emp.user.is_active)

        # Edit to Inactive
        edit_data = {
            'full_name': 'Edit Sync Updated',
            'email': 'newemail@jeweldesk.test',
            'mobile': '9876543210',
            'role': self.sales_role.pk,
            'department': 'Sales',
            'status': Employee.STATUS_INACTIVE,
        }
        edit_form = EmployeeEditForm(data=edit_data, instance=emp)
        self.assertTrue(edit_form.is_valid(), edit_form.errors)
        emp = edit_form.save()

        emp.user.refresh_from_db()
        self.assertFalse(emp.user.is_active)
        self.assertEqual(emp.user.email, 'newemail@jeweldesk.test')
        self.assertIsNone(authenticate(username='editsync', password='SyncPass123!'))

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
