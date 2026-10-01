"""
team/tests.py
-------------
Comprehensive test suite for JewelDesk Team / Employee Management module.
"""

from django.contrib.auth import authenticate, get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from .forms import (
    EmployeeCreateForm,
    EmployeeEditForm,
    EmployeeLinkAccountForm,
    EmployeePasswordResetForm,
    PermissionForm,
    RoleForm,
)
from .models import (
    Branch,
    Employee,
    EmployeeDocument,
    EmployeePermission,
    Role,
)
from .permissions import has_module_perm, is_admin_user

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

        # Pre-seed default roles
        self.admin_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_ADMIN,
            defaults={'description': 'Full access to all modules.', 'is_builtin': True}
        )
        self.hr_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_HR,
            defaults={'description': 'HR and team management.', 'is_builtin': True}
        )
        self.manager_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_MANAGER,
            defaults={'description': 'General management.', 'is_builtin': True}
        )
        self.sales_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SALES_EXECUTIVE,
            defaults={'description': 'Handle customer interactions and sales.', 'is_builtin': True}
        )
        self.inventory_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_INVENTORY_MANAGER,
            defaults={'description': 'Manage stock and inventory.', 'is_builtin': True}
        )
        self.support_role, _ = Role.objects.get_or_create(
            name=Role.ROLE_SUPPORT,
            defaults={'description': 'Customer support and enquiries.', 'is_builtin': True}
        )

        # Branch
        self.main_branch = Branch.objects.create(
            name='Main Showroom',
            address='101 Jewel Street',
            phone='9876543210',
            is_active=True,
        )

    def test_default_roles_exist(self):
        """Verify standard jewellery business roles exist in DB."""
        self.assertTrue(Role.objects.filter(name='Admin').exists())
        self.assertTrue(Role.objects.filter(name='HR').exists())
        self.assertTrue(Role.objects.filter(name='Manager').exists())
        self.assertTrue(Role.objects.filter(name='Sales Executive').exists())
        self.assertTrue(Role.objects.filter(name='Inventory Manager').exists())
        self.assertTrue(Role.objects.filter(name='Support').exists())

    def test_create_employee_with_linked_user(self):
        """Creating an employee must create and link a Django User account atomically."""
        form_data = {
            'username': 'johnsales',
            'password1': 'Secret@123',
            'password2': 'Secret@123',
            'full_name': 'John Sales',
            'email': 'john@jeweldesk.test',
            'mobile': '9898989898',
            'designation': 'Senior Sales Associate',
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
        self.assertEqual(emp.designation, 'Senior Sales Associate')
        self.assertEqual(emp.user.username, 'johnsales')
        self.assertEqual(emp.user.email, 'john@jeweldesk.test')
        self.assertEqual(emp.user.first_name, 'John')
        self.assertEqual(emp.user.last_name, 'Sales')
        self.assertTrue(emp.user.is_staff)  # Back-office access
        self.assertTrue(emp.user.is_active)

        # Password must be hashed, never stored in plain text
        self.assertNotEqual(emp.user.password, 'Secret@123')
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

    def test_create_employee_link_existing_user(self):
        """Creating an employee linking an existing Django user."""
        existing_u = User.objects.create_user(
            username='existinguser',
            email='existing@jeweldesk.test',
            password='Password123!',
        )
        form_data = {
            'account_mode': EmployeeCreateForm.ACCOUNT_LINK_EXISTING,
            'existing_user': existing_u.pk,
            'full_name': 'Existing Linked',
            'email': 'existing@jeweldesk.test',
            'designation': 'Store Manager',
            'role': self.manager_role.pk,
            'department': 'Administration',
            'status': Employee.STATUS_ACTIVE,
        }
        form = EmployeeCreateForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        emp = form.save(created_by=self.admin_user)

        self.assertEqual(emp.user.pk, existing_u.pk)
        self.assertTrue(emp.user.is_staff)

    def test_create_employee_without_login_account(self):
        """Creating an employee record without an immediate login account."""
        form_data = {
            'account_mode': EmployeeCreateForm.ACCOUNT_NONE,
            'full_name': 'No Account Staff',
            'email': 'noaccount@jeweldesk.test',
            'designation': 'Artisan / Bench Jeweler',
            'role': self.sales_role.pk,
            'department': 'Operations',
            'status': Employee.STATUS_ACTIVE,
        }
        form = EmployeeCreateForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        emp = form.save(created_by=self.admin_user)

        self.assertIsNone(emp.user)
        self.assertEqual(emp.designation, 'Artisan / Bench Jeweler')

    def test_enable_login_access_for_unlinked_employee(self):
        """Admin uses employee_link_account to enable login for an unlinked employee."""
        emp = Employee.objects.create(
            user=None,
            full_name='Unlinked Emp',
            email='unlinked@jeweldesk.test',
            role=self.sales_role,
            status=Employee.STATUS_ACTIVE,
        )

        self.client.force_login(self.admin_user)
        url = reverse('team:employee_link_account', kwargs={'pk': emp.pk})
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, 200)

        # POST new user credentials
        post_res = self.client.post(url, {
            'mode': 'create',
            'username': 'unlinkeduser',
            'password1': 'NewPass123!',
            'password2': 'NewPass123!',
        })
        self.assertEqual(post_res.status_code, 302)

        emp.refresh_from_db()
        self.assertIsNotNone(emp.user)
        self.assertEqual(emp.user.username, 'unlinkeduser')
        self.assertTrue(emp.user.check_password('NewPass123!'))

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

        self.assertIsNone(authenticate(username='wrongpwuser', password='BadPassword!'))
        self.assertIsNone(authenticate(username='wrongpw@jeweldesk.test', password='BadPassword!'))

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
        self.assertIsNone(authenticate(username='inactiveemp', password='SecretPass123!'))

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
        self.assertIsNone(authenticate(username='empdeact', password='Password123!'))

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

        edit_data = {
            'full_name': 'Edit Sync Updated',
            'email': 'newemail@jeweldesk.test',
            'designation': 'Lead Appraiser',
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
        self.assertEqual(emp.designation, 'Lead Appraiser')

    def test_admin_password_reset_for_employee(self):
        """Admin can reset employee password via employee_password_reset view."""
        user = User.objects.create_user(
            username='resetpwemp',
            email='resetpw@jeweldesk.test',
            password='OldPassword123!',
            is_staff=True,
        )
        emp = Employee.objects.create(
            user=user,
            full_name='Reset PW Emp',
            email=user.email,
            role=self.sales_role,
            status=Employee.STATUS_ACTIVE,
        )

        self.client.force_login(self.admin_user)
        url = reverse('team:employee_password_reset', kwargs={'pk': emp.pk})
        response = self.client.post(url, {
            'new_password1': 'BrandNewPass123!',
            'new_password2': 'BrandNewPass123!',
        })
        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        self.assertTrue(user.check_password('BrandNewPass123!'))
        self.assertIsNotNone(authenticate(username='resetpwemp', password='BrandNewPass123!'))

    def test_admin_employee_list_view(self):
        """Admin can access employee list view."""
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('team:employee_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Employees Directory')

    def test_unauthorized_user_rejected_by_backend_with_403(self):
        """Backend authorization rejects unauthorized access with 403 Forbidden."""
        self.client.force_login(self.regular_user)

        # Direct access to protected URLs must return HTTP 403
        list_res = self.client.get(reverse('team:employee_list'))
        self.assertEqual(list_res.status_code, 403)

        create_res = self.client.get(reverse('team:employee_create'))
        self.assertEqual(create_res.status_code, 403)

        roles_res = self.client.get(reverse('team:role_list'))
        self.assertEqual(roles_res.status_code, 403)

    def test_unauthenticated_user_redirected_to_login(self):
        """Unauthenticated user accessing protected views is redirected to login."""
        response = self.client.get(reverse('team:employee_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_hr_user_authorized_team_access(self):
        """HR role has permission to view team and add employees."""
        hr_user = User.objects.create_user(
            username='hrspecialist',
            email='hr@jeweldesk.test',
            password='Password123!',
            is_staff=True,
        )
        hr_emp = Employee.objects.create(
            user=hr_user,
            full_name='HR Specialist',
            email=hr_user.email,
            role=self.hr_role,
            status=Employee.STATUS_ACTIVE,
        )
        hr_emp.apply_default_permissions()

        self.client.force_login(hr_user)

        # HR can view employee list
        res_list = self.client.get(reverse('team:employee_list'))
        self.assertEqual(res_list.status_code, 200)

        # HR can view employee create form
        res_create = self.client.get(reverse('team:employee_create'))
        self.assertEqual(res_create.status_code, 200)

    def test_self_privilege_escalation_prevented(self):
        """Normal employees cannot edit their own permissions or assign Admin role."""
        hr_user = User.objects.create_user(
            username='hrescalate',
            email='hrescalate@jeweldesk.test',
            password='Password123!',
            is_staff=True,
        )
        hr_emp = Employee.objects.create(
            user=hr_user,
            full_name='HR Escalation Test',
            email=hr_user.email,
            role=self.hr_role,
            status=Employee.STATUS_ACTIVE,
        )
        hr_emp.apply_default_permissions()

        self.client.force_login(hr_user)

        # 1. Attempting to edit own permissions must be rejected with 403
        own_perms_url = reverse('team:employee_permissions', kwargs={'pk': hr_emp.pk})
        perm_res = self.client.get(own_perms_url)
        self.assertEqual(perm_res.status_code, 403)

        # 2. Attempting to assign Admin role when creating an employee must fail
        create_res = self.client.post(reverse('team:employee_create'), {
            'account_mode': EmployeeCreateForm.ACCOUNT_NONE,
            'full_name': 'Sneaky Admin',
            'email': 'sneaky@jeweldesk.test',
            'role': self.admin_role.pk,
            'department': 'Administration',
            'status': Employee.STATUS_ACTIVE,
        })
        self.assertEqual(create_res.status_code, 200)
        self.assertContains(create_res, 'Only administrators can assign the Admin role')

    def test_self_deactivation_prevented(self):
        """A user cannot deactivate their own account."""
        admin_emp = Employee.objects.create(
            user=self.admin_user,
            full_name='Admin Boss',
            email=self.admin_user.email,
            role=self.admin_role,
            status=Employee.STATUS_ACTIVE,
        )

        self.client.force_login(self.admin_user)
        toggle_url = reverse('team:employee_toggle_status', kwargs={'pk': admin_emp.pk})
        res = self.client.post(toggle_url, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'You cannot deactivate your own account')

        admin_emp.refresh_from_db()
        self.assertEqual(admin_emp.status, Employee.STATUS_ACTIVE)

    def test_custom_roles_crud(self):
        """Admin can view roles list and create custom roles."""
        self.client.force_login(self.admin_user)

        # View roles list
        list_res = self.client.get(reverse('team:role_list'))
        self.assertEqual(list_res.status_code, 200)
        self.assertContains(list_res, 'System Roles &amp; Access Profiles')

        # Create custom role
        create_res = self.client.post(reverse('team:role_create'), {
            'name': 'Master Jeweler',
            'description': 'Head of custom jewelry manufacturing workshop.',
        })
        self.assertEqual(create_res.status_code, 302)

        role = Role.objects.filter(name='Master Jeweler').first()
        self.assertIsNotNone(role)
        self.assertFalse(role.is_builtin)

    def test_employee_document_upload_and_delete(self):
        """Admin can upload and delete HR documents for an employee."""
        emp = Employee.objects.create(
            user=None,
            full_name='Doc Test Emp',
            email='doctest@jeweldesk.test',
            role=self.sales_role,
            status=Employee.STATUS_ACTIVE,
        )

        self.client.force_login(self.admin_user)
        upload_url = reverse('team:employee_document_upload', kwargs={'pk': emp.pk})

        test_file = SimpleUploadedFile(
            'contract.pdf',
            b'%PDF-1.4 test contract content',
            content_type='application/pdf'
        )

        upload_res = self.client.post(upload_url, {
            'document_type': EmployeeDocument.DOC_CONTRACT,
            'title': 'Employment Agreement 2026',
            'file': test_file,
            'notes': 'Signed by employee and HR',
        })
        self.assertEqual(upload_res.status_code, 302)

        doc = EmployeeDocument.objects.filter(employee=emp).first()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.title, 'Employment Agreement 2026')

        # Delete document
        delete_url = reverse('team:employee_document_delete', kwargs={'pk': emp.pk, 'doc_pk': doc.pk})
        del_res = self.client.post(delete_url)
        self.assertEqual(del_res.status_code, 302)
        self.assertFalse(EmployeeDocument.objects.filter(pk=doc.pk).exists())

    # -----------------------------------------------------------------------
    # Additional tests added to increase coverage
    # -----------------------------------------------------------------------

    def test_permission_matrix_save_and_reload_via_view(self):
        """Saving permissions via the permissions view correctly persists them."""
        hr_user = User.objects.create_user(
            username='hrpermtest',
            email='hrperm@jeweldesk.test',
            password='Password123!',
            is_staff=True,
        )
        target_user = User.objects.create_user(
            username='permbulk',
            email='permbulk@jeweldesk.test',
            password='Password123!',
            is_staff=True,
        )
        hr_emp = Employee.objects.create(
            user=hr_user,
            full_name='HR Perm Manager',
            email=hr_user.email,
            role=self.hr_role,
            status=Employee.STATUS_ACTIVE,
        )
        hr_emp.apply_default_permissions()

        target_emp = Employee.objects.create(
            user=target_user,
            full_name='Perm Target',
            email=target_user.email,
            role=self.sales_role,
            status=Employee.STATUS_ACTIVE,
        )
        target_emp.apply_default_permissions()

        self.client.force_login(hr_user)
        url = reverse('team:employee_permissions', kwargs={'pk': target_emp.pk})

        # Post: grant full inventory access
        post_data = {}
        for module_key, _ in EmployeePermission.MODULE_CHOICES:
            for action in PermissionForm.ACTIONS:
                field_name = f'{module_key}__{action}'
                # Grant all access to inventory module only
                post_data[field_name] = True if module_key == 'inventory' else False

        resp = self.client.post(url, post_data)
        self.assertEqual(resp.status_code, 302)

        # Verify inventory permissions saved
        inv_perm = EmployeePermission.objects.get(employee=target_emp, module='inventory')
        self.assertTrue(inv_perm.can_view)
        self.assertTrue(inv_perm.can_add)
        self.assertTrue(inv_perm.can_edit)
        self.assertTrue(inv_perm.can_delete)
        self.assertTrue(inv_perm.can_export)

        # Verify dashboard (not granted) is false
        dash_perm = EmployeePermission.objects.get(employee=target_emp, module='dashboard')
        self.assertFalse(dash_perm.can_view)

    def test_role_assignment_creates_correct_default_permissions(self):
        """Default permissions are applied correctly for each of the major roles."""
        roles_to_check = [
            (self.hr_role,        'team',      'view',   True),
            (self.hr_role,        'team',      'add',    True),
            (self.hr_role,        'inventory', 'view',   False),
            (self.manager_role,   'customers', 'view',   True),
            (self.manager_role,   'sales',     'delete', True),
            (self.inventory_role, 'inventory', 'view',   True),
            (self.inventory_role, 'sales',     'view',   False),
            (self.support_role,   'customers', 'add',    True),
            (self.support_role,   'team',      'add',    False),
        ]

        for role, module, action, expected in roles_to_check:
            defaults = EmployeePermission.default_permissions_for_role(role.name)
            actual = defaults.get(module, {}).get(f'can_{action}', False)
            self.assertEqual(
                actual, expected,
                f'Role {role.name}: expected {action} on {module} = {expected}, got {actual}'
            )

    def test_has_module_perm_for_admin_role(self):
        """An employee with Admin role has permission to all modules and actions."""
        admin_user = User.objects.create_user(
            username='adminemp2',
            email='adminemp2@jeweldesk.test',
            password='Password123!',
            is_staff=True,
        )
        admin_emp = Employee.objects.create(
            user=admin_user,
            full_name='Admin Employee',
            email=admin_user.email,
            role=self.admin_role,
            status=Employee.STATUS_ACTIVE,
        )
        admin_emp.apply_default_permissions()

        for module_key, _ in EmployeePermission.MODULE_CHOICES:
            for action in ['view', 'add', 'edit', 'delete', 'export']:
                self.assertTrue(
                    has_module_perm(admin_user, module_key, action),
                    f'Admin should have {action} on {module_key}'
                )

    def test_has_module_perm_inactive_employee_denied(self):
        """An inactive employee's user gets no module permissions."""
        user = User.objects.create_user(
            username='inactiveperm',
            email='inactiveperm@jeweldesk.test',
            password='Password123!',
            is_staff=True,
        )
        emp = Employee.objects.create(
            user=user,
            full_name='Inactive Perm',
            email=user.email,
            role=self.hr_role,
            status=Employee.STATUS_INACTIVE,  # Inactive
        )
        emp.apply_default_permissions()

        self.assertFalse(has_module_perm(user, 'team', 'view'))
        self.assertFalse(has_module_perm(user, 'dashboard', 'view'))

    def test_role_edit_view_updates_role_description(self):
        """Admin can edit a custom role description via role_edit view."""
        custom_role = Role.objects.create(
            name='Gemologist',
            description='Original description.',
            is_builtin=False,
        )
        self.client.force_login(self.admin_user)
        url = reverse('team:role_edit', kwargs={'pk': custom_role.pk})
        resp = self.client.post(url, {
            'name': 'Gemologist',
            'description': 'Expert in gem identification and grading.',
        })
        self.assertEqual(resp.status_code, 302)
        custom_role.refresh_from_db()
        self.assertEqual(custom_role.description, 'Expert in gem identification and grading.')

    def test_builtin_role_cannot_be_renamed(self):
        """Built-in roles must not have their name changed via RoleForm."""
        form = RoleForm(
            data={'name': 'SuperAdmin', 'description': 'Renamed built-in.'},
            instance=self.admin_role,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)

    def test_employee_detail_view_accessible_by_self(self):
        """An employee can view their own profile without team:view permission."""
        user = User.objects.create_user(
            username='selfview',
            email='selfview@jeweldesk.test',
            password='Password123!',
            is_staff=True,
        )
        emp = Employee.objects.create(
            user=user,
            full_name='Self View Emp',
            email=user.email,
            role=self.sales_role,
            status=Employee.STATUS_ACTIVE,
        )
        # No permissions applied → cannot normally view team
        self.client.force_login(user)
        url = reverse('team:employee_detail', kwargs={'pk': emp.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_employee_detail_view_blocked_for_other_employee(self):
        """An employee cannot view another employee's profile without team:view."""
        user_a = User.objects.create_user(
            username='empA',
            email='empa@jeweldesk.test',
            password='Password123!',
            is_staff=True,
        )
        emp_a = Employee.objects.create(
            user=user_a,
            full_name='Emp A',
            email=user_a.email,
            role=self.sales_role,
            status=Employee.STATUS_ACTIVE,
        )
        emp_b = Employee.objects.create(
            user=None,
            full_name='Emp B',
            email='empb@jeweldesk.test',
            role=self.sales_role,
            status=Employee.STATUS_ACTIVE,
        )
        # No permissions applied
        self.client.force_login(user_a)
        url = reverse('team:employee_detail', kwargs={'pk': emp_b.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_employee_id_auto_generated_sequentially(self):
        """Employee IDs are generated sequentially starting from EMP-0001."""
        emp1 = Employee.objects.create(
            full_name='First Emp',
            email='first@jeweldesk.test',
            role=self.sales_role,
        )
        emp2 = Employee.objects.create(
            full_name='Second Emp',
            email='second@jeweldesk.test',
            role=self.sales_role,
        )
        self.assertTrue(emp1.employee_id.startswith('EMP-'))
        self.assertTrue(emp2.employee_id.startswith('EMP-'))
        # IDs should be different (auto-incremented)
        self.assertNotEqual(emp1.employee_id, emp2.employee_id)
        # The second ID should be numerically greater
        num1 = int(emp1.employee_id.split('-')[1])
        num2 = int(emp2.employee_id.split('-')[1])
        self.assertGreater(num2, num1)

    def test_seed_roles_management_command(self):
        """seed_roles management command creates roles idempotently."""
        from django.core.management import call_command
        from io import StringIO

        # Delete a built-in role to simulate a clean state
        Role.objects.filter(name='Cashier').delete()
        self.assertFalse(Role.objects.filter(name='Cashier').exists())

        out = StringIO()
        call_command('seed_roles', stdout=out)

        # Role should be recreated
        self.assertTrue(Role.objects.filter(name='Cashier').exists())
        cashier = Role.objects.get(name='Cashier')
        self.assertTrue(cashier.is_builtin)

        # Running a second time should be safe (idempotent)
        call_command('seed_roles', stdout=StringIO())
        self.assertEqual(Role.objects.filter(name='Cashier').count(), 1)

    def test_branch_list_and_create_view(self):
        """Admin can access branch list and create a new branch."""
        self.client.force_login(self.admin_user)

        # Branch list
        list_resp = self.client.get(reverse('team:branch_list'))
        self.assertEqual(list_resp.status_code, 200)

        # Create branch
        create_resp = self.client.post(reverse('team:branch_create'), {
            'name': 'Downtown Branch',
            'address': '202 Gold Street',
            'phone': '9090909090',
            'is_active': True,
        })
        self.assertEqual(create_resp.status_code, 302)
        self.assertTrue(Branch.objects.filter(name='Downtown Branch').exists())

