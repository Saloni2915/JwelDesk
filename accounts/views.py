from django.contrib import messages
from django.contrib.auth import logout as auth_logout, login as auth_login
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect, render
from django.urls import reverse

from .forms import CompanySettingsForm
from .models import CompanySettings


def _login_view(request):
    """Render the branded login card and handle sign-in.

    (Function-based replacement for auth_views.LoginView so the whole
    accounts app follows the project's function-based view convention.)
    """
    if request.user.is_authenticated:
        return redirect('dashboard')
    from django.contrib.auth.views import LoginView
    return LoginView.as_view(
        template_name='accounts/login.html',
        redirect_authenticated_user=True,
    )(request)


# Exposed under the name the URLconf expects.
login_view = _login_view


def logout_view(request):
    """Log the user out.

    POST performs the logout and redirects to the login page; GET shows a
    small confirmation page with a logout button (Django 5+ requires POST
    for the logout action, so a plain GET link cannot log out directly).
    """
    if request.method == 'POST':
        auth_logout(request)
        messages.success(request, 'You have been logged out successfully.')
        return redirect('accounts:login')
    return render(request, 'accounts/logout_confirm.html')


staff_required = user_passes_test(lambda u: u.is_active and u.is_staff)


@staff_required
def company_settings(request):
    """Edit the single company/business settings record (admin only)."""
    settings_obj = CompanySettings.load()
    if request.method == 'POST':
        form = CompanySettingsForm(
            request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Company settings saved successfully.')
            return redirect('accounts:company_settings')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = CompanySettingsForm(instance=settings_obj)
    return render(request, 'accounts/company_settings.html', {
        'form': form,
        'settings_obj': settings_obj,
    })


THEME_OPTIONS = (
    {
        'key': 'light',
        'name': 'Light',
        'desc': 'Clean, bright business UI with white surfaces, subtle borders and dark text. '
                'Ideal for everyday counter and back-office use.',
    },
    {
        'key': 'dark',
        'name': 'Dark',
        'desc': 'Genuinely dark interface with dark chrome, cards, tables and forms. '
                'Comfortable in low-light showrooms.',
    },
    {
        'key': 'gold',
        'name': 'Gold / Premium',
        'desc': 'Warm cream surfaces with a sophisticated gold accent used sparingly. '
                'An elegant, premium jewellery-brand look.',
    },
)


@staff_required
def themes(request):
    """Display the Themes settings page (authenticated back-office)."""
    current_theme = request.COOKIES.get('jd-theme', 'light')
    if current_theme not in ('light', 'dark', 'gold'):
        current_theme = 'light'
    if current_theme not in ('light', 'dark', 'gold'):
        current_theme = 'light'
    return render(request, 'accounts/themes.html', {
        'current_theme': current_theme,
        'theme_options': THEME_OPTIONS,
    })

