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






