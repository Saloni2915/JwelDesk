from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.views import (
    LoginView,
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy

from .forms import (
    CompanySettingsForm,
    JewelDeskPasswordResetForm,
    JewelDeskSetPasswordForm,
    JewelDeskSignUpForm,
)
from .models import CompanySettings


class JewelDeskPasswordResetView(PasswordResetView):
    """View to request a password reset email."""
    template_name = 'accounts/password_reset_form.html'
    email_template_name = 'accounts/password_reset_email.txt'
    html_email_template_name = 'accounts/password_reset_email.html'
    subject_template_name = 'accounts/password_reset_subject.txt'
    success_url = reverse_lazy('accounts:password_reset_done')
    form_class = JewelDeskPasswordResetForm

    def get_extra_email_context(self):
        try:
            settings_obj = CompanySettings.load()
            name = settings_obj.name
        except Exception:
            name = 'JewelDesk'
        return {
            'site_name': name,
            'company_name': name,
        }

    def form_valid(self, form):
        self.extra_email_context = self.get_extra_email_context()
        return super().form_valid(form)


class JewelDeskPasswordResetDoneView(PasswordResetDoneView):
    """Confirmation page shown after requesting a password reset."""
    template_name = 'accounts/password_reset_done.html'


class JewelDeskPasswordResetConfirmView(PasswordResetConfirmView):
    """View allowing the user to set a new password via secure token."""
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('accounts:password_reset_complete')
    form_class = JewelDeskSetPasswordForm


class JewelDeskPasswordResetCompleteView(PasswordResetCompleteView):
    """Success page shown after successfully setting a new password."""
    template_name = 'accounts/password_reset_complete.html'


# View aliases exposed for URLconfs
password_reset_view = JewelDeskPasswordResetView.as_view()
password_reset_done_view = JewelDeskPasswordResetDoneView.as_view()
password_reset_confirm_view = JewelDeskPasswordResetConfirmView.as_view()
password_reset_complete_view = JewelDeskPasswordResetCompleteView.as_view()



class JewelDeskLoginView(LoginView):
    """Branded login view for JewelDesk.

    Subclasses Django's LoginView so it participates correctly in the
    class-based view dispatch chain, including CSRF middleware, session
    handling and the ``redirect_authenticated_user`` shortcut.
    """
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True


# Function alias so the URLconf entry ``views.login_view`` keeps working
# without any URL changes.
login_view = JewelDeskLoginView.as_view()


def signup_view(request):
    """Render the registration card and handle user account creation."""
    if request.user.is_authenticated:
        messages.info(
            request,
            'You are already signed in. Please log out first if you wish to create a new account.'
        )
        return redirect('dashboard')

    if request.method == 'POST':
        form = JewelDeskSignUpForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                'Your account has been created successfully! You can now sign in with your credentials.'
            )
            return redirect('accounts:login')
        else:
            messages.error(
                request,
                'Unable to create account. Please check the errors highlighted below and try again.'
            )
    else:
        form = JewelDeskSignUpForm()

    return render(request, 'accounts/signup.html', {'form': form})


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

