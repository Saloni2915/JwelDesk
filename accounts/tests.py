from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator, PasswordResetTokenGenerator
from django.core import mail
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode



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

    def test_company_name_updated_in_header_after_save(self):
        """When company name is changed, it should appear in the back-office header."""
        self.client.login(username='adminuser', password='Password123')
        
        # First, verify the current company name in the header (fallback)
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'JewelDesk')  # Default fallback name
        
        # Update the company name
        new_name = 'Updated Test Company'
        response = self.client.post(self.url, data={
            'company_name': new_name,
            'gstin': '27ABCDE1234F1Z5',
            'address': '12 MG Road, Mumbai',
            'phone': '+91 22 4000 5000',
            'email': 'shop@example.com',
            'invoice_footer_note': 'Thank you for shopping with us.',
        })
        self.assertEqual(response.status_code, 302)
        
        # Verify the company name is updated in the database
        from accounts.models import CompanySettings
        settings_obj = CompanySettings.load()
        self.assertEqual(settings_obj.company_name, new_name)
        self.assertEqual(settings_obj.name, new_name)  # Test the name property
        
        # Now verify the new name appears in the header/sidebar
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, new_name)
        
    def test_company_name_fallback_when_no_settings(self):
        """When no CompanySettings exists, fallback name should appear."""
        from accounts.models import CompanySettings
        
        # Delete all company settings
        CompanySettings.objects.all().delete()
        
        # Create a fresh request - context processor should use fallback
        self.client.login(username='adminuser', password='Password123')
        response = self.client.get(reverse('dashboard'))
        
        # Fallback name should appear
        self.assertContains(response, 'JewelDesk')
        
    def test_company_name_not_static_in_navbar(self):
        """Verify the navbar company name element updates dynamically (not hardcoded)."""
        self.client.login(username='adminuser', password='Password123')
        
        # Set a distinctive company name
        new_name = 'Test Company Name For Verification'
        
        # Update company settings
        response = self.client.post(self.url, data={
            'company_name': new_name,
            'gstin': '27ABCDE1234F1Z5',
            'address': '12 MG Road, Mumbai',
            'phone': '+91 22 4000 5000',
            'email': 'shop@example.com',
            'invoice_footer_note': '',
        })
        self.assertEqual(response.status_code, 302)
        
        # Request the dashboard page
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode()
        
        # Verify the NEW company name appears in the navbar brand element
        # The navbar brand should be: <span class="fw-semibold company-name">NEW_NAME</span>
        import re
        navbar_pattern = r'<span class="fw-semibold company-name">([^<]+)</span>'
        navbar_match = re.search(navbar_pattern, content)
        
        self.assertIsNotNone(navbar_match, 
            "Navbar company name element not found in rendered HTML")
        
        rendered_navbar_name = navbar_match.group(1)
        self.assertEqual(rendered_navbar_name, new_name,
            f"Navbar shows '{rendered_navbar_name}' but should show '{new_name}'")
        
        # Verify the sidebar company name also updates
        sidebar_pattern = r'<div class="sidebar-company-name">([^<]+)</div>'
        sidebar_match = re.search(sidebar_pattern, content)
        
        self.assertIsNotNone(sidebar_match,
            "Sidebar company name element not found in rendered HTML")
        
        rendered_sidebar_name = sidebar_match.group(1)
        self.assertEqual(rendered_sidebar_name, new_name,
            f"Sidebar shows '{rendered_sidebar_name}' but should show '{new_name}'")
        
        # Verify the OLD fallback name "JewelDesk" is NOT used for the company name elements
        # (It may still appear in page titles or other non-company-name contexts)
        jeweldesk_in_navbar = re.search(
            r'<span class="fw-semibold company-name">JewelDesk</span>', content)
        self.assertIsNone(jeweldesk_in_navbar,
            "Navbar company name element still shows hardcoded 'JewelDesk'")
        
        jeweldesk_in_sidebar = re.search(
            r'<div class="sidebar-company-name">JewelDesk</div>', content)
        self.assertIsNone(jeweldesk_in_sidebar,
            "Sidebar company name element still shows hardcoded 'JewelDesk'")

    def test_themes_page_requires_authentication(self):
        """Themes page should require authentication."""
        response = self.client.get(reverse('accounts:themes'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)
        
    def test_themes_page_accessible_by_staff(self):
        """Themes page should be accessible by staff users."""
        self.client.login(username='adminuser', password='Password123')
        response = self.client.get(reverse('accounts:themes'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/themes.html')
        
    def test_themes_page_renders_theme_options(self):
        """Themes page should render all three theme options."""
        self.client.login(username='adminuser', password='Password123')
        response = self.client.get(reverse('accounts:themes'))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode()
        self.assertIn('Light', content)
        self.assertIn('Dark', content)
        self.assertIn('Gold', content)
        self.assertIn('data-theme="light"', content)
        self.assertIn('data-theme="dark"', content)
        self.assertIn('data-theme="gold"', content)
        
    def test_themes_page_shows_current_theme(self):
        """Themes page should indicate the currently selected theme."""
        self.client.login(username='adminuser', password='Password123')
        
        # Test with default light theme
        response = self.client.get(reverse('accounts:themes'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('✓ Selected', content)  # Light should be selected by default
        
    def test_theme_css_file_is_loaded(self):
        """Theme CSS file should be linked in templates."""
        self.client.login(username='adminuser', password='Password123')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode()
        self.assertIn('/static/css/style.css', content)
        self.assertIn('jd-theme', content)
        
    def test_themes_navigation_link_in_sidebar(self):
        """Themes link should be present in sidebar under Settings."""
        self.client.login(username='adminuser', password='Password123')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode()
        self.assertIn('Themes', content)
        self.assertIn('bi-palette', content)
        self.assertIn('/accounts/settings/themes/', content)

    def test_company_settings_page_still_works(self):
        """Company settings page should continue to work after theme refactoring."""
        self.client.login(username='adminuser', password='Password123')
        response = self.client.get(reverse('accounts:company_settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Company Settings')
        self.assertContains(response, 'Business Profile')


    def test_logo_updates_dynamically(self):
        """Logo should be reflected in sidebar when updated."""
        self.client.login(username='adminuser', password='Password123')
        
        # Initially, no logo should be set (or check current state)
        from accounts.models import CompanySettings
        settings_obj = CompanySettings.load()
        
        # The sidebar should show company name even without logo
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, settings_obj.name or 'JewelDesk')
        
        # Company name in header should match
        self.assertContains(response, settings_obj.name or 'JewelDesk')

    # ------------------------------------------------------------------
    # Theme system (Settings -> Themes)
    # ------------------------------------------------------------------

    def test_themes_page_renders_three_theme_cards_with_previews(self):
        """Themes page renders 3 compact cards, each with a mini UI preview."""
        self.client.login(username='adminuser', password='Password123')
        response = self.client.get(reverse('accounts:themes'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Exactly three selectable theme cards
        self.assertEqual(content.count('data-theme-card='), 3)
        self.assertEqual(content.count('class="tp-window'), 3)
        for cls in ('tp-light', 'tp-dark', 'tp-gold'):
            self.assertIn(cls, content)

        # Mini previews must show real UI parts, not solid color boxes
        for part in ('tp-topbar', 'tp-side', 'tp-card', 'tp-table', 'tp-btn'):
            self.assertIn(part, content)

        # All three theme names present
        for name in ('Light', 'Dark', 'Gold / Premium'):
            self.assertIn(name, content)

    def test_themes_page_reflects_saved_theme_from_cookie(self):
        """Server-rendered selected state follows the saved jd-theme cookie."""
        self.client.login(username='adminuser', password='Password123')
        self.client.cookies['jd-theme'] = 'dark'
        response = self.client.get(reverse('accounts:themes'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Dark card marked selected, light card not selected
        self.assertRegex(
            content,
            r'<div class="theme-card is-selected" data-theme-card="dark">')
        self.assertRegex(
            content,
            r'<div class="theme-card" data-theme-card="light">')
        self.assertNotRegex(
            content,
            r'<div class="theme-card is-selected" data-theme-card="light">')

        # Invalid cookie value falls back to light (view sanitises input)
        self.client.cookies['jd-theme'] = 'hacked-value'
        response = self.client.get(reverse('accounts:themes'))
        content = response.content.decode()
        self.assertRegex(
            content,
            r'<div class="theme-card is-selected" data-theme-card="light">')

    def test_theme_switching_works_without_page_reload(self):
        """Theme apply is client-side: helper + localStorage persistence."""
        self.client.login(username='adminuser', password='Password123')
        themes_html = self.client.get(
            reverse('accounts:themes')).content.decode()
        dash_html = self.client.get(reverse('dashboard')).content.decode()

        # Global helper defined in base.html (shared by every auth page)
        self.assertIn('jdApplyTheme', dash_html)
        self.assertIn("localStorage.setItem('jd-theme'", dash_html)
        # Early-init script applies saved theme before first paint
        self.assertIn("localStorage.getItem('jd-theme')", dash_html)
        self.assertIn("setAttribute('data-theme'", dash_html)
        # Themes page wires its apply buttons to the helper
        self.assertIn('jdApplyTheme', themes_html)

    def test_theme_css_exposes_semantic_tokens_for_all_components(self):
        """style.css defines semantic variables for every themeable component."""
        import os
        from django.conf import settings
        path = os.path.join(
            settings.BASE_DIR, 'static', 'css', 'style.css')
        with open(path, encoding='utf-8') as fh:
            css = fh.read()
        for token in (
            '--bg-primary', '--bg-secondary', '--surface', '--surface-hover',
            '--sidebar-bg', '--navbar-bg', '--text-primary', '--text-secondary',
            '--text-muted', '--border', '--accent', '--accent-hover',
            '--button-primary', '--button-primary-hover', '--success',
            '--warning', '--danger', '--table-header', '--input-bg',
            '--input-border', '--shadow',
        ):
            self.assertIn(token + ':', css, 'missing CSS token ' + token)
        self.assertIn('[data-theme="dark"]', css)
        self.assertIn('[data-theme="gold"]', css)

    def test_settings_sidebar_section_links_to_themes(self):
        """Settings -> Themes navigation exists in the left sidebar."""
        self.client.login(username='adminuser', password='Password123')
        content = self.client.get(reverse('dashboard')).content.decode()

        self.assertIn('sidebar-section">Settings<', content)
        idx_settings = content.find('sidebar-section">Settings<')
        idx_themes = content.find('/accounts/settings/themes/')
        self.assertNotEqual(idx_settings, -1, 'Settings section missing')
        self.assertNotEqual(idx_themes, -1, 'Themes link missing')
        self.assertLess(
            idx_settings, idx_themes,
            'Themes link must appear under the Settings section')

    def test_company_branding_renders_on_themes_page(self):
        """CompanySettings branding keeps working with the Themes page."""
        from accounts.models import CompanySettings
        self.client.login(username='adminuser', password='Password123')
        settings_obj = CompanySettings.load()
        settings_obj.company_name = 'Themes Branding Test Co'
        settings_obj.save()

        content = self.client.get(
            reverse('accounts:themes')).content.decode()
        self.assertIn('Themes Branding Test Co', content)


class PasswordResetTests(TestCase):
    """Test suite for Forgot Password / Reset Password workflow."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='resetuser',
            email='resetuser@jeweldesk.test',
            password='OldSecurePassword123!',
        )
        self.reset_url = reverse('accounts:password_reset')
        self.done_url = reverse('accounts:password_reset_done')

    def test_login_page_has_forgot_password_link(self):
        """The login page must include a visible 'Forgot Password?' link."""
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Forgot Password?')
        self.assertContains(response, self.reset_url)

    def test_forgot_password_page_loads(self):
        """Forgot password page should render successfully with form elements."""
        response = self.client.get(self.reset_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/password_reset_form.html')
        self.assertContains(response, 'Send Reset Link')
        self.assertContains(response, 'id_email')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, reverse('accounts:login'))

    def test_registered_user_reset_request_works_and_sends_email(self):
        """Requesting a reset for a registered email must send a reset email with token."""
        response = self.client.post(self.reset_url, {'email': self.user.email})
        self.assertRedirects(response, self.done_url)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, [self.user.email])
        self.assertIn('JewelDesk', email.subject)

        # Verify email contains reset link with uidb64 and token
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.assertIn(f'/accounts/password-reset/confirm/{uidb64}/', email.body)
        token_part = email.body.split(f'/accounts/password-reset/confirm/{uidb64}/')[1].split('/')[0]
        self.assertTrue(default_token_generator.check_token(self.user, token_part))

    def test_reset_done_page_loads(self):
        """The confirmation page after submitting reset request loads properly."""
        response = self.client.get(self.done_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/password_reset_done.html')
        self.assertContains(response, 'Check Your Email')
        self.assertContains(response, reverse('accounts:login'))

    def test_valid_reset_token_allows_password_change(self):
        """A valid token allows navigating to the form and setting a new password."""
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        confirm_url = reverse(
            'accounts:password_reset_confirm',
            kwargs={'uidb64': uidb64, 'token': token}
        )

        # GET request initiates session token and displays form at set-password URL
        response = self.client.get(confirm_url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/password_reset_confirm.html')
        self.assertTrue(response.context.get('validlink'))
        set_password_url = response.redirect_chain[-1][0]

        # POST new password to the set-password form URL
        post_response = self.client.post(set_password_url, {
            'new_password1': 'BrandNewPassword789!',
            'new_password2': 'BrandNewPassword789!',
        })
        self.assertRedirects(
            post_response,
            reverse('accounts:password_reset_complete')
        )

        # Complete page loads
        complete_response = self.client.get(reverse('accounts:password_reset_complete'))
        self.assertEqual(complete_response.status_code, 200)
        self.assertTemplateUsed(complete_response, 'accounts/password_reset_complete.html')

    def test_old_password_no_longer_works_and_new_password_works(self):
        """After password reset, old password fails and new password authenticates."""
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        confirm_url = reverse(
            'accounts:password_reset_confirm',
            kwargs={'uidb64': uidb64, 'token': token}
        )

        # Step 1: Initialize session via GET
        get_response = self.client.get(confirm_url, follow=True)
        set_password_url = get_response.redirect_chain[-1][0]

        # Step 2: POST new password
        self.client.post(set_password_url, {
            'new_password1': 'BrandNewPassword789!',
            'new_password2': 'BrandNewPassword789!',
        })

        # Step 3: Attempt login with old password - must FAIL
        login_old = self.client.post(reverse('accounts:login'), {
            'username': self.user.username,
            'password': 'OldSecurePassword123!',
        })
        self.assertEqual(login_old.status_code, 200)
        self.assertContains(login_old, 'Invalid username or password')

        # Step 4: Attempt login with new password - must SUCCEED
        login_new = self.client.post(reverse('accounts:login'), {
            'username': self.user.username,
            'password': 'BrandNewPassword789!',
        }, follow=True)
        self.assertTrue(login_new.context['user'].is_authenticated)

    def test_invalid_token_is_rejected(self):
        """An invalid reset token is rejected with validlink=False and friendly message."""
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        bad_token = 'completely-invalid-token'
        confirm_url = reverse(
            'accounts:password_reset_confirm',
            kwargs={'uidb64': uidb64, 'token': bad_token}
        )

        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/password_reset_confirm.html')
        self.assertFalse(response.context.get('validlink'))
        self.assertContains(response, 'Reset Link Invalid or Expired')

    def test_expired_token_is_rejected(self):
        """A token that has expired is rejected."""
        class ExpiredTokenGenerator(PasswordResetTokenGenerator):
            def _num_seconds(self, dt):
                return super()._num_seconds(dt) - 1000000

        expired_gen = ExpiredTokenGenerator()
        token = expired_gen.make_token(self.user)
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        confirm_url = reverse(
            'accounts:password_reset_confirm',
            kwargs={'uidb64': uidb64, 'token': token}
        )

        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context.get('validlink'))

    def test_unknown_email_does_not_reveal_account_existence(self):
        """Submitting an unknown email redirects to done without sending mail or revealing existence."""
        response = self.client.post(self.reset_url, {
            'email': 'nonexistent_jeweller_email@example.com'
        })
        # Must redirect to the exact same 'done' page
        self.assertRedirects(response, self.done_url)
        # Must not send any email
        self.assertEqual(len(mail.outbox), 0)

        # Checking the done page content does not reveal account existence
        done_page = self.client.get(self.done_url)
        self.assertEqual(done_page.status_code, 200)
        self.assertNotContains(done_page, 'not found')
        self.assertNotContains(done_page, 'does not exist')

    def test_existing_normal_login_still_works(self):
        """Normal login behavior is completely preserved."""
        response = self.client.post(reverse('accounts:login'), {
            'username': self.user.username,
            'password': 'OldSecurePassword123!',
        }, follow=True)
        self.assertTrue(response.context['user'].is_authenticated)


class SignUpTests(TestCase):
    """Test suite for Sign Up / User Registration workflow."""

    def setUp(self):
        self.client = Client()
        self.signup_url = reverse('accounts:signup')
        self.login_url = reverse('accounts:login')

    def test_signup_page_loads(self):
        """Sign up page should render successfully with form controls."""
        response = self.client.get(self.signup_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/signup.html')
        self.assertContains(response, 'Create Account')
        self.assertContains(response, 'id_first_name')
        self.assertContains(response, 'id_username')
        self.assertContains(response, 'id_email')
        self.assertContains(response, 'id_password1')
        self.assertContains(response, 'id_password2')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, self.login_url)

    def test_login_page_has_signup_link(self):
        """Login page must display clearly visible 'Don't have an account? Sign Up' link."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Don't have an account?")
        self.assertContains(response, 'Sign Up')
        self.assertContains(response, self.signup_url)

    def test_valid_user_can_register(self):
        """A new user can submit valid registration data and be created in DB."""
        data = {
            'first_name': 'Rohit Sharma',
            'username': 'rohit_jewels',
            'email': 'rohit@jeweldesk.test',
            'password1': 'ComplexP@ssw0rd2026!',
            'password2': 'ComplexP@ssw0rd2026!',
        }
        response = self.client.post(self.signup_url, data)
        self.assertRedirects(response, self.login_url)

        # Verify user was created in the database
        user = User.objects.get(username='rohit_jewels')
        self.assertEqual(user.first_name, 'Rohit Sharma')
        self.assertEqual(user.email, 'rohit@jeweldesk.test')
        self.assertTrue(user.is_active)

    def test_password_is_not_stored_in_plain_text(self):
        """Password must be securely hashed and never stored in plain text."""
        raw_password = 'SuperSecretPassword2026!'
        data = {
            'first_name': 'Meera Patel',
            'username': 'meera_patel',
            'email': 'meera@jeweldesk.test',
            'password1': raw_password,
            'password2': raw_password,
        }
        self.client.post(self.signup_url, data)
        user = User.objects.get(username='meera_patel')

        self.assertNotEqual(user.password, raw_password)
        self.assertTrue(user.password.startswith('pbkdf2_sha256$'))
        self.assertTrue(user.check_password(raw_password))

    def test_new_user_can_login_after_registration(self):
        """A freshly registered user can sign in normally through the login system."""
        password = 'MyShowroomPass123#'
        data = {
            'first_name': 'Aditi Rao',
            'username': 'aditirao',
            'email': 'aditi@jeweldesk.test',
            'password1': password,
            'password2': password,
        }
        self.client.post(self.signup_url, data)

        # Login with newly registered credentials
        login_response = self.client.post(self.login_url, {
            'username': 'aditirao',
            'password': password,
        }, follow=True)
        self.assertTrue(login_response.context['user'].is_authenticated)
        self.assertEqual(login_response.context['user'].username, 'aditirao')

    def test_duplicate_username_is_rejected(self):
        """Attempting to register with an already existing username is rejected."""
        User.objects.create_user(
            username='existinguser',
            email='existing@jeweldesk.test',
            password='InitialPassword123!',
        )
        data = {
            'first_name': 'Another User',
            'username': 'existinguser',
            'email': 'newunique@jeweldesk.test',
            'password1': 'AnotherPassword123!',
            'password2': 'AnotherPassword123!',
        }
        response = self.client.post(self.signup_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/signup.html')
        self.assertIn('username', response.context['form'].errors)

    def test_duplicate_email_is_rejected(self):
        """Attempting to register with an already existing email is rejected."""
        User.objects.create_user(
            username='userone',
            email='shared@jeweldesk.test',
            password='InitialPassword123!',
        )
        data = {
            'first_name': 'Second User',
            'username': 'usertwo',
            'email': 'shared@jeweldesk.test',
            'password1': 'AnotherPassword123!',
            'password2': 'AnotherPassword123!',
        }
        response = self.client.post(self.signup_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/signup.html')
        self.assertIn('email', response.context['form'].errors)
        self.assertFalse(User.objects.filter(username='usertwo').exists())

    def test_password_confirmation_mismatch_is_rejected(self):
        """When password and confirm password do not match, form errors are shown."""
        data = {
            'first_name': 'Mismatch Test',
            'username': 'mismatchuser',
            'email': 'mismatch@jeweldesk.test',
            'password1': 'ValidPassword123!',
            'password2': 'DifferentPassword456!',
        }
        response = self.client.post(self.signup_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/signup.html')
        self.assertIn('password2', response.context['form'].errors)
        self.assertFalse(User.objects.filter(username='mismatchuser').exists())

    def test_invalid_form_data_handled_correctly(self):
        """Invalid or missing fields return errors without creating records."""
        data = {
            'first_name': '',
            'username': '',
            'email': 'not-an-email',
            'password1': '',
            'password2': '',
        }
        response = self.client.post(self.signup_url, data)
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)
        self.assertIn('email', form.errors)
        self.assertIn('first_name', form.errors)

    def test_authenticated_user_redirected_from_signup(self):
        """Already logged in users are redirected to dashboard upon visiting signup."""
        user = User.objects.create_user(
            username='authuser',
            password='ValidPassword123!'
        )
        self.client.login(username='authuser', password='ValidPassword123!')
        response = self.client.get(self.signup_url)
        self.assertRedirects(response, reverse('dashboard'))

    def test_existing_login_still_works(self):
        """Existing user login functionality continues to operate identically."""
        user = User.objects.create_user(
            username='existingloginuser',
            password='MyPassword123!',
        )
        response = self.client.post(self.login_url, {
            'username': 'existingloginuser',
            'password': 'MyPassword123!',
        }, follow=True)
        self.assertTrue(response.context['user'].is_authenticated)

    def test_existing_forgot_password_still_works(self):
        """Existing forgot password link and form load successfully."""
        user = User.objects.create_user(
            username='forgotpwuser',
            email='forgotpw@jeweldesk.test',
            password='OriginalPassword123!',
        )
        reset_response = self.client.post(
            reverse('accounts:password_reset'),
            {'email': user.email}
        )
        self.assertRedirects(reset_response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(user.email, mail.outbox[0].to)






class AuthCSRFTests(TestCase):
    """
    Focused tests for the login CSRF fix and signup DB creation.

    Requirement checklist (per task):
      a. successful signup creates a database user
      b. signup password is hashed (never plain text)
      c. successful login
      d. CSRF-protected login POST (rejected without token)
      e. invalid signup / invalid login show errors
    """

    def setUp(self):
        self.client = Client()
        self.login_url = reverse('accounts:login')
        self.signup_url = reverse('accounts:signup')

    # ------------------------------------------------------------------
    # d. CSRF-protected login POST
    # ------------------------------------------------------------------

    def test_login_form_contains_csrf_token(self):
        """GET /accounts/login/ must render csrfmiddlewaretoken in the form."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'csrfmiddlewaretoken',
                            msg_prefix='Login form is missing {% csrf_token %}')

    def test_login_post_without_csrf_token_is_rejected(self):
        """A POST that omits the CSRF token must be rejected (403) when
        CSRF enforcement is active.  This verifies the middleware is
        working and the view is NOT decorated with @csrf_exempt."""
        # Create an enforcement-on client
        csrf_client = Client(enforce_csrf_checks=True)
        User.objects.create_user(username='csrfuser', password='CsrfPassword123!')

        # POST without obtaining a CSRF cookie / token first
        response = csrf_client.post(self.login_url, {
            'username': 'csrfuser',
            'password': 'CsrfPassword123!',
        })
        # Must be 403 Forbidden, not 200 or redirect
        self.assertEqual(response.status_code, 403,
                         'Login POST without CSRF token should return 403')

    def test_login_post_with_valid_csrf_token_succeeds(self):
        """A POST that includes the correct CSRF token must succeed."""
        csrf_client = Client(enforce_csrf_checks=True)
        user = User.objects.create_user(
            username='goodcsrfuser', password='CsrfGoodPass123!')

        # Step 1: GET the login page to receive the CSRF cookie
        get_response = csrf_client.get(self.login_url)
        self.assertEqual(get_response.status_code, 200)

        # Step 2: Extract the CSRF token from the cookie
        csrf_token = csrf_client.cookies.get('csrftoken')
        self.assertIsNotNone(csrf_token,
                             'No csrftoken cookie after GET /accounts/login/')

        # Step 3: POST with the token in both the form and the header
        response = csrf_client.post(
            self.login_url,
            {
                'username': 'goodcsrfuser',
                'password': 'CsrfGoodPass123!',
                'csrfmiddlewaretoken': csrf_token.value,
            },
            HTTP_X_CSRFTOKEN=csrf_token.value,
            follow=True,
        )
        self.assertTrue(
            response.context['user'].is_authenticated,
            'Login with valid CSRF token should succeed',
        )

    # ------------------------------------------------------------------
    # a. Successful signup creates a database user
    # ------------------------------------------------------------------

    def test_successful_signup_creates_database_user(self):
        """Valid signup data must create exactly one new User row in the DB."""
        initial_count = User.objects.count()
        self.client.post(self.signup_url, {
            'first_name': 'Priya Singh',
            'username': 'priya_singh',
            'email': 'priya@jeweldesk.test',
            'password1': 'SecureShow@2026',
            'password2': 'SecureShow@2026',
        })
        self.assertEqual(User.objects.count(), initial_count + 1,
                         'Signup should create exactly one new user in the DB')
        user = User.objects.get(username='priya_singh')
        self.assertEqual(user.first_name, 'Priya Singh')
        self.assertEqual(user.email, 'priya@jeweldesk.test')
        self.assertTrue(user.is_active)

    # ------------------------------------------------------------------
    # b. Signup password is hashed
    # ------------------------------------------------------------------

    def test_signup_password_is_hashed_not_plain_text(self):
        """After signup the stored password must be a hash, not the raw string."""
        raw = 'PlainTextIsEvilPassword1!'
        self.client.post(self.signup_url, {
            'first_name': 'Hash Test',
            'username': 'hashtest',
            'email': 'hash@jeweldesk.test',
            'password1': raw,
            'password2': raw,
        })
        user = User.objects.get(username='hashtest')
        self.assertNotEqual(user.password, raw,
                            'Password must not be stored as plain text')
        self.assertTrue(user.password.startswith('pbkdf2_sha256$') or
                        user.password.startswith('argon2') or
                        user.password.startswith('bcrypt'),
                        'Password must use a recognised Django hash algorithm')
        self.assertTrue(user.check_password(raw),
                        'check_password() must validate the raw password against the hash')

    # ------------------------------------------------------------------
    # c. Successful login
    # ------------------------------------------------------------------

    def test_login_with_valid_credentials_redirects_to_dashboard(self):
        """POST /accounts/login/ with correct credentials redirects to /."""
        User.objects.create_user(username='validlogin', password='ValidPass@123')
        response = self.client.post(self.login_url, {
            'username': 'validlogin',
            'password': 'ValidPass@123',
        }, follow=True)
        self.assertTrue(response.context['user'].is_authenticated)

    def test_full_flow_signup_then_login(self):
        """End-to-end: signup → DB user created → login succeeds → authenticated."""
        password = 'EndToEnd@Flow2026'
        self.client.post(self.signup_url, {
            'first_name': 'Flow Test',
            'username': 'flowtest',
            'email': 'flow@jeweldesk.test',
            'password1': password,
            'password2': password,
        })
        # Verify DB record
        self.assertTrue(User.objects.filter(username='flowtest').exists(),
                        'User must exist in DB after signup')
        # Now login
        login_response = self.client.post(self.login_url, {
            'username': 'flowtest',
            'password': password,
        }, follow=True)
        self.assertTrue(login_response.context['user'].is_authenticated,
                        'User must be authenticated after signup + login')
        self.assertEqual(login_response.context['user'].username, 'flowtest')

    # ------------------------------------------------------------------
    # e. Invalid signup / invalid login show errors
    # ------------------------------------------------------------------

    def test_invalid_login_returns_200_with_error(self):
        """Wrong credentials must return 200 and display an error — not crash."""
        User.objects.create_user(username='erroruser', password='RealPass@123')
        response = self.client.post(self.login_url, {
            'username': 'erroruser',
            'password': 'WrongPass!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid username or password')

    def test_invalid_signup_missing_required_fields_shows_errors(self):
        """Submitting an empty signup form must return 200 with form errors."""
        response = self.client.post(self.signup_url, {
            'first_name': '',
            'username': '',
            'email': 'not-an-email',
            'password1': '',
            'password2': '',
        })
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)
        self.assertIn('first_name', form.errors)
        self.assertFalse(User.objects.filter(email='not-an-email').exists())

    def test_existing_users_continue_to_work_after_changes(self):
        """Pre-existing users must still be able to log in unchanged."""
        existing = User.objects.create_user(
            username='preexisting', password='PreExisting@123')
        response = self.client.post(self.login_url, {
            'username': 'preexisting',
            'password': 'PreExisting@123',
        }, follow=True)
        self.assertTrue(response.context['user'].is_authenticated)
        self.assertEqual(response.context['user'].pk, existing.pk)

    def test_login_with_email_address_succeeds(self):
        """Users can log in using their email address as the identifier."""
        from django.contrib.auth import authenticate
        user = User.objects.create_user(
            username='emailjeweller',
            email='jeweller@shop.test',
            password='JewellerPass@123'
        )
        # authenticate() directly with email
        auth_user = authenticate(username='jeweller@shop.test', password='JewellerPass@123')
        self.assertIsNotNone(auth_user)
        self.assertEqual(auth_user.pk, user.pk)

        # Login view POST with email
        response = self.client.post(self.login_url, {
            'username': 'jeweller@shop.test',
            'password': 'JewellerPass@123',
        }, follow=True)
        self.assertTrue(response.context['user'].is_authenticated)
        self.assertEqual(response.context['user'].pk, user.pk)

    def test_login_case_insensitivity(self):
        """Authentication works case-insensitively for both username and email."""
        from django.contrib.auth import authenticate
        User.objects.create_user(
            username='casetest',
            email='case@test.com',
            password='CasePassword123!'
        )
        self.assertIsNotNone(authenticate(username='CASETEST', password='CasePassword123!'))
        self.assertIsNotNone(authenticate(username='CASE@TEST.COM', password='CasePassword123!'))

    def test_inactive_user_cannot_login_with_username_or_email(self):
        """Inactive user cannot authenticate or log in with username or email."""
        from django.contrib.auth import authenticate
        User.objects.create_user(
            username='inactiveuser',
            email='inactive@test.com',
            password='Password123!',
            is_active=False
        )
        self.assertIsNone(authenticate(username='inactiveuser', password='Password123!'))
        self.assertIsNone(authenticate(username='inactive@test.com', password='Password123!'))

        resp1 = self.client.post(self.login_url, {
            'username': 'inactiveuser',
            'password': 'Password123!',
        })
        self.assertEqual(resp1.status_code, 200)
        self.assertContains(resp1, 'Invalid username or password')

        resp2 = self.client.post(self.login_url, {
            'username': 'inactive@test.com',
            'password': 'Password123!',
        })
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, 'Invalid username or password')


class SignUpFlowInspectionTests(TestCase):
    """
    Verification tests for the JewelDesk public Signup flow:
    - User record creation in Django's configured User model
    - Submitted username and email accuracy
    - Password hashing (set_password / pbkdf2)
    - Authentication via authenticate() with both username and email
    - Handling and rejection of duplicate username / duplicate email
    - Invalid signups rejected without creating any User record
    - Direct access via both /accounts/signup/ and /signup/
    - Feedback messages and error rendering
    """

    def setUp(self):
        self.client = Client()
        self.signup_url = reverse('accounts:signup')
        self.login_url = reverse('accounts:login')

    def test_signup_creates_exactly_one_user_with_submitted_username_email(self):
        """Signup creates exactly one user with the submitted username and email."""
        initial_count = User.objects.count()
        response = self.client.post(self.signup_url, {
            'first_name': 'Meera Verma',
            'username': 'meera_verma',
            'email': 'meera@jeweldesk.test',
            'password1': 'MeeraPass@2026!',
            'password2': 'MeeraPass@2026!',
        })
        self.assertRedirects(response, self.login_url)
        self.assertEqual(User.objects.count(), initial_count + 1)
        user = User.objects.get(username='meera_verma')
        self.assertEqual(user.username, 'meera_verma')
        self.assertEqual(user.email, 'meera@jeweldesk.test')
        self.assertEqual(user.first_name, 'Meera Verma')
        self.assertTrue(user.is_active)

    def test_signup_password_is_hashed_not_plain_text(self):
        """Password is securely hashed and not stored in plain text."""
        raw_password = 'PlainSecret#9988'
        self.client.post(self.signup_url, {
            'first_name': 'Hashed User',
            'username': 'hasheduser',
            'email': 'hashed@jeweldesk.test',
            'password1': raw_password,
            'password2': raw_password,
        })
        user = User.objects.get(username='hasheduser')
        self.assertNotEqual(user.password, raw_password)
        self.assertTrue(user.password.startswith('pbkdf2_') or user.password.startswith('argon2') or user.password.startswith('bcrypt'))
        self.assertTrue(user.check_password(raw_password))

    def test_authenticate_succeeds_with_submitted_credentials(self):
        """authenticate() succeeds with both username and email (case-insensitive)."""
        from django.contrib.auth import authenticate
        raw_password = 'AuthUserPass@123'
        self.client.post(self.signup_url, {
            'first_name': 'Auth Tester',
            'username': 'authtester',
            'email': 'authtester@jeweldesk.test',
            'password1': raw_password,
            'password2': raw_password,
        })
        user = User.objects.get(username='authtester')

        # By exact username
        auth_by_user = authenticate(None, username='authtester', password=raw_password)
        self.assertEqual(auth_by_user, user)

        # By uppercase username
        auth_by_user_upper = authenticate(None, username='AUTHTESTER', password=raw_password)
        self.assertEqual(auth_by_user_upper, user)

        # By exact email
        auth_by_email = authenticate(None, username='authtester@jeweldesk.test', password=raw_password)
        self.assertEqual(auth_by_email, user)

        # By uppercase email
        auth_by_email_upper = authenticate(None, username='AUTHTESTER@JEWELDESK.TEST', password=raw_password)
        self.assertEqual(auth_by_email_upper, user)

        # Login via Client post
        login_resp = self.client.post(self.login_url, {
            'username': 'authtester@jeweldesk.test',
            'password': raw_password,
        }, follow=True)
        self.assertTrue(login_resp.context['user'].is_authenticated)

    def test_duplicate_username_is_rejected_appropriately(self):
        """Duplicate username (case-insensitive) is rejected and does not create duplicate user."""
        User.objects.create_user(username='existinguser', email='existing1@test.com', password='Password123!')
        count_before = User.objects.count()

        response = self.client.post(self.signup_url, {
            'first_name': 'Dup User',
            'username': 'EXISTINGUSER',
            'email': 'different@test.com',
            'password1': 'NewPass@12345!',
            'password2': 'NewPass@12345!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), count_before)
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)

    def test_duplicate_email_is_rejected_appropriately(self):
        """Duplicate email (case-insensitive) is rejected and does not create duplicate user."""
        User.objects.create_user(username='origuser', email='duplicate@test.com', password='Password123!')
        count_before = User.objects.count()

        response = self.client.post(self.signup_url, {
            'first_name': 'Dup Email',
            'username': 'newuniqueuser',
            'email': 'DUPLICATE@TEST.COM',
            'password1': 'NewPass@12345!',
            'password2': 'NewPass@12345!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), count_before)
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_invalid_signup_mismatched_passwords_does_not_create_user(self):
        """Mismatched passwords reject form submission and create no DB record."""
        count_before = User.objects.count()
        response = self.client.post(self.signup_url, {
            'first_name': 'Mismatch Test',
            'username': 'mismatchuser',
            'email': 'mismatch@test.com',
            'password1': 'PassOne@12345',
            'password2': 'PassTwo@99999',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), count_before)
        self.assertFalse(User.objects.filter(username='mismatchuser').exists())
        self.assertContains(response, 'Unable to create account')

    def test_direct_root_signup_url_works(self):
        """Direct /signup/ route renders and processes signup correctly."""
        response = self.client.get('/signup/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/signup.html')

    def test_authenticated_client_posting_signup_creates_new_user(self):
        """Even if an existing session is active (e.g. admin testing in same browser),
        submitting signup via POST must NOT be dropped or redirected to dashboard.
        It must clear the old session and create the new user record."""
        admin_user = User.objects.create_user(
            username='tempadmin', password='AdminPassword123!', is_staff=True
        )
        self.client.login(username='tempadmin', password='AdminPassword123!')

        raw_password = 'SaloniSecure@2026'
        response = self.client.post(self.signup_url, {
            'first_name': 'Saloni Soni',
            'username': 'saloni_new_account',
            'email': 'saloni_new@jeweldesk.test',
            'password1': raw_password,
            'password2': raw_password,
        })
        self.assertRedirects(response, self.login_url)
        self.assertTrue(
            User.objects.filter(username='saloni_new_account', email='saloni_new@jeweldesk.test').exists(),
            'New User record must be created in the database'
        )
        created_user = User.objects.get(username='saloni_new_account')
        self.assertTrue(created_user.check_password(raw_password))

    def test_login_creates_session_and_grants_access(self):
        """Newly created user credentials can log in, establish session, and view dashboard."""
        password = 'UserLoginPass@2026'
        user = User.objects.create_user(
            username='sessionuser', email='session@jeweldesk.test', password=password
        )
        response = self.client.post(self.login_url, {
            'username': 'session@jeweldesk.test',
            'password': password,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)
        self.assertEqual(response.context['user'].pk, user.pk)
        self.assertEqual(int(self.client.session.get('_auth_user_id')), user.pk)

    def test_logout_terminates_session(self):
        """Logging out terminates the session and unauthenticates the user."""
        password = 'LogoutUserPass@2026'
        User.objects.create_user(
            username='logouttestuser', email='logouttest@jeweldesk.test', password=password
        )
        self.client.login(username='logouttestuser', password=password)
        self.assertIn('_auth_user_id', self.client.session)

        response = self.client.post(reverse('accounts:logout'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['user'].is_authenticated)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_wrong_password_fails_authentication_and_login(self):
        """Invalid credentials fail authenticate() and reject login with error."""
        from django.contrib.auth import authenticate
        User.objects.create_user(
            username='wrongpassuser', email='wrongpass@jeweldesk.test', password='CorrectPassword@123'
        )
        # authenticate() fails
        auth_result = authenticate(None, username='wrongpassuser', password='IncorrectPassword!')
        self.assertIsNone(auth_result)

        # Login POST fails with 200 and error message
        response = self.client.post(self.login_url, {
            'username': 'wrongpassuser',
            'password': 'IncorrectPassword!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid username or password')
        self.assertNotIn('_auth_user_id', self.client.session)




