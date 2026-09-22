from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse


class AccountsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testjeweller', password='SecurePassword123')

    def test_login_page_renders(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')

    def test_successful_login(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'testjeweller',
            'password': 'SecurePassword123'
        }, follow=True)
        self.assertTrue(response.context['user'].is_authenticated)

    def test_failed_login(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'testjeweller',
            'password': 'WrongPassword'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid username or password')

    def test_unauthenticated_user_redirected_from_dashboard(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_logout_view(self):
        self.client.login(username='testjeweller', password='SecurePassword123')
        response = self.client.post(reverse('accounts:logout'), follow=True)
        self.assertFalse(response.context['user'].is_authenticated)


class LogoutRegressionTests(TestCase):
    """Logout must end the session and block protected pages afterwards."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='logoutuser', password='Password123')

    def test_logout_redirects_to_login(self):
        self.client.login(username='logoutuser', password='Password123')
        response = self.client.post(reverse('accounts:logout'))
        self.assertRedirects(response, reverse('accounts:login'))

    def test_session_invalidated_after_logout(self):
        self.client.login(username='logoutuser', password='Password123')
        session_key = self.client.session.session_key
        self.assertIsNotNone(session_key)
        self.client.post(reverse('accounts:logout'))
        from django.contrib.auth import get_user
        user = get_user(self.client)
        self.assertFalse(user.is_authenticated)
        from django.contrib.sessions.models import Session
        self.assertFalse(Session.objects.filter(pk=session_key).exists())

    def test_protected_pages_inaccessible_after_logout(self):
        self.client.login(username='logoutuser', password='Password123')
        self.client.post(reverse('accounts:logout'))
        for url in (reverse('dashboard'), reverse('sale_list'),
                    reverse('custom_orders:custom_order_list')):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn('login', response.url)

    def test_logout_confirm_page_shown_on_get(self):
        self.client.login(username='logoutuser', password='Password123')
        response = self.client.get(reverse('accounts:logout'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/logout_confirm.html')
        from django.contrib.auth import get_user
        self.assertTrue(get_user(self.client).is_authenticated)

class CompanySettingsTests(TestCase):
    """Company settings page, permissions, validation and invoice usage."""

    def setUp(self):
        self.client = Client()
        self.staff = User.objects.create_user(
            username='adminuser', password='Password123', is_staff=True)
        self.plain = User.objects.create_user(
            username='plainuser', password='Password123', is_staff=False)
        self.url = reverse('accounts:company_settings')

    def test_page_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_page_blocked_for_non_staff(self):
        self.client.login(username='plainuser', password='Password123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_page_renders_for_staff(self):
        self.client.login(username='adminuser', password='Password123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Company')

    def test_save_company_settings(self):
        self.client.login(username='adminuser', password='Password123')
        response = self.client.post(self.url, data={
            'company_name': 'Shree Jewellers Test',
            'gstin': '27ABCDE1234F1Z5',
            'address': '12 MG Road, Mumbai',
            'phone': '+91 22 4000 5000',
            'email': 'shop@example.com',
            'invoice_footer_note': 'Thank you for shopping with us.',
        })
        self.assertEqual(response.status_code, 302)
        from accounts.models import CompanySettings
        settings_obj = CompanySettings.load()
        self.assertEqual(settings_obj.company_name, 'Shree Jewellers Test')
        self.assertEqual(settings_obj.gstin, '27ABCDE1234F1Z5')

# __END__

    def test_update_existing_company_settings(self):
        self.client.login(username='adminuser', password='Password123')
        self.client.post(self.url, data={
            'company_name': 'First Name', 'gstin': '', 'address': '',
            'phone': '', 'email': '', 'invoice_footer_note': ''})
        response = self.client.post(self.url, data={
            'company_name': 'Updated Name', 'gstin': '', 'address': '',
            'phone': '', 'email': '', 'invoice_footer_note': ''})
        self.assertEqual(response.status_code, 302)
        from accounts.models import CompanySettings
        self.assertEqual(CompanySettings.objects.count(), 1)
        self.assertEqual(CompanySettings.load().company_name, 'Updated Name')

    def test_invalid_gstin_rejected(self):
        self.client.login(username='adminuser', password='Password123')
        response = self.client.post(self.url, data={
            'company_name': 'GST Shop', 'gstin': 'BAD-GSTIN', 'address': '',
            'phone': '', 'email': '', 'invoice_footer_note': ''})
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('gstin', form.errors)
        from accounts.models import CompanySettings
        self.assertNotEqual(CompanySettings.load().company_name, 'GST Shop')

    def test_valid_gstin_accepted(self):
        from .models import validate_gstin
        validate_gstin('24AACCE1234F1Z2')  # must not raise

    def test_invalid_phone_rejected(self):
        self.client.login(username='adminuser', password='Password123')
        response = self.client.post(self.url, data={
            'company_name': 'Phone Shop', 'gstin': '', 'address': '',
            'phone': 'call me maybe', 'email': '',
            'invoice_footer_note': ''})
        self.assertEqual(response.status_code, 200)
        self.assertIn('phone', response.context['form'].errors)

    def test_blank_settings_allowed(self):
        self.client.login(username='adminuser', password='Password123')
        response = self.client.post(self.url, data={
            'company_name': '', 'gstin': '', 'address': '',
            'phone': '', 'email': '', 'invoice_footer_note': ''})
        self.assertEqual(response.status_code, 302)

    def test_settings_page_linked_in_sidebar(self):
        self.client.login(username='adminuser', password='Password123')
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, self.url)




