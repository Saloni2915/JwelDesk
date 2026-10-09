from django.contrib import messages
from django.contrib.auth import get_user_model, logout as auth_logout
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.views import (
    LoginView,
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.db import IntegrityError, transaction
from django.db.models import Q
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

    def form_valid(self, form):
        user = form.get_user()
        if user and not user.is_staff:
            emp = getattr(user, 'employee_profile', None)
            if not emp:
                user.is_staff = True
                user.save(update_fields=['is_staff'])
        return super().form_valid(form)


# Function alias so the URLconf entry ``views.login_view`` keeps working
# without any URL changes.
login_view = JewelDeskLoginView.as_view()


def signup_view(request):
    """Render the registration card and handle user account creation."""
    if request.method == 'POST':
        # If an existing session is active (e.g. admin testing in the same browser),
        # terminate the old session so the registration POST is processed and committed.
        if request.user.is_authenticated:
            auth_logout(request)

        form = JewelDeskSignUpForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
            except IntegrityError:
                # Handle database-level unique constraint violations (e.g. auth_user_username_key
                # or concurrent double-submit race conditions) safely without raising HTTP 500.
                email = (form.cleaned_data.get('email') or '').strip().lower()
                username = (form.cleaned_data.get('username') or '').strip()
                User = get_user_model()

                if email and User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
                    form.add_error('email', 'An account with this email already exists.')
                elif username and User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).exists():
                    form.add_error('username', 'A user with that username already exists.')
                else:
                    form.add_error('email', 'An account with this email already exists.')

                messages.error(
                    request,
                    'Unable to create account. Please check the errors highlighted below and try again.'
                )
                return render(request, 'accounts/signup.html', {'form': form})

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
        # On GET, if the user is already authenticated, redirect them to dashboard.
        if request.user.is_authenticated:
            return redirect('dashboard')
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
    requested_theme = request.GET.get('theme')
    current_theme = requested_theme if requested_theme in ('light', 'dark', 'gold') else request.COOKIES.get('jd-theme', 'light')
    if current_theme not in ('light', 'dark', 'gold'):
        current_theme = 'light'
    response = render(request, 'accounts/themes.html', {
        'current_theme': current_theme,
        'theme_options': THEME_OPTIONS,
    })
    if requested_theme in ('light', 'dark', 'gold'):
        response.set_cookie('jd-theme', requested_theme, max_age=31536000, samesite='Lax')
    return response

