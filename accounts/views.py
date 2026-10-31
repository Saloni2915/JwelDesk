from django.contrib import messages
from django.contrib.auth import get_user_model, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    LoginView,
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
import logging

logger = logging.getLogger(__name__)

from .forms import (
    CompanySettingsForm,
    JewelDeskPasswordResetForm,
    JewelDeskSetPasswordForm,
    JewelDeskSignUpForm,
)
from .models import CompanySettings, save_logo_blob, clear_logo_blob


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
        try:
            return super().form_valid(form)
        except Exception as exc:
            logger.exception("Password reset email delivery failed: %s", exc)
            return HttpResponseRedirect(self.get_success_url())


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

    def get_success_url(self):
        url = self.get_redirect_url()
        if url:
            return url
        user = self.request.user
        if user and user.is_authenticated and user.is_superuser:
            return reverse('super_admin:dashboard')
        return super().get_success_url()


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
                User = get_user_model()

                if email and User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
                    form.add_error('email', 'An account with this email already exists.')
                else:
                    form.add_error('email', 'An account with this email already exists.')

                messages.error(
                    request,
                    'Unable to create account. Please check the errors highlighted below and try again.'
                )
                return render(request, 'accounts/signup.html', {'form': form})

            messages.success(
                request,
                'Your account and shop have been created successfully! You can now sign in with your credentials.'
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


@login_required
def company_settings(request):
    """Edit the company/business settings record for the user's active tenant."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No active store found for your account.')
        return redirect('dashboard')

    from team.permissions import is_admin_user
    if not (is_admin_user(request.user, tenant=tenant) or tenant.owner_id == request.user.id):
        messages.error(request, 'Access restricted. Only store administrators can modify company settings.')
        return redirect('dashboard')

    try:
        settings_obj = CompanySettings.load(tenant=tenant)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Error loading company settings: %s", e)
        settings_obj = CompanySettings(tenant=tenant, company_name=tenant.name)

    if request.method == 'POST':
        # 1. 1-Click quick restore of official brand insignia
        if request.POST.get('reset_default_logo') == '1':
            try:
                from pathlib import Path
                from django.conf import settings
                static_logo = settings.BASE_DIR / 'static' / 'images' / 'branding' / 'company_logo.png'
                if static_logo.exists():
                    logo_bytes = static_logo.read_bytes()
                    final_name = f'company/logo_{tenant.id}.png'
                    save_logo_blob(final_name, logo_bytes, 'image/png')
                    dest = Path(settings.MEDIA_ROOT) / final_name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(logo_bytes)
                    settings_obj.logo.name = final_name
                    settings_obj.save()
                    try:
                        from django.core.cache import cache
                        cache.delete(f'company_settings:tenant:{tenant.id}')
                    except Exception:
                        pass
                    messages.success(request, 'JewelDesk official brand insignia restored successfully!')
                    return redirect('accounts:company_settings')
            except Exception as reset_err:
                import logging
                logging.getLogger(__name__).warning("Reset logo warning: %s", reset_err)

        form = CompanySettingsForm(
            request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            uploaded_logo = request.FILES.get('logo')
            logo_cleared = request.POST.get('logo-clear') == 'on'

            if uploaded_logo:
                try:
                    logo_bytes = uploaded_logo.read()
                    uploaded_logo.seek(0)
                    content_type = uploaded_logo.content_type or 'image/png'
                except Exception:
                    logo_bytes = None
                    content_type = 'image/png'
            else:
                logo_bytes = None

            try:
                instance = form.save(commit=False)
                instance.tenant = tenant
                instance.save()
                if hasattr(instance, 'language') and instance.language:
                    request.session['django_language'] = instance.language

                if logo_cleared:
                    clear_logo_blob()
                    instance.logo = None
                    instance.save(update_fields=['logo'])
                elif uploaded_logo and instance.logo and logo_bytes:
                    try:
                        final_filename = instance.logo.name
                        save_logo_blob(final_filename, logo_bytes, content_type)
                        from pathlib import Path
                        from django.conf import settings
                        dest = Path(settings.MEDIA_ROOT) / final_filename
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(logo_bytes)
                    except Exception as blob_err:
                        import logging
                        logging.getLogger(__name__).warning("Logo blob backup warning: %s", blob_err)

                try:
                    from django.core.cache import cache
                    cache.delete(f'company_settings:tenant:{tenant.id}')
                except Exception:
                    pass
                messages.success(request, 'Company settings and showroom logo updated successfully!')
                return redirect('accounts:company_settings')
            except Exception as e:
                import logging
                logging.getLogger(__name__).error("Failed to save company settings: %s", e)
                # Resilient fallback: update text fields and record filename directly
                try:
                    for field in ('company_name', 'gstin', 'phone', 'email', 'address', 'invoice_footer_note'):
                        setattr(settings_obj, field, form.cleaned_data.get(field, getattr(settings_obj, field)))
                    if uploaded_logo and logo_bytes:
                        final_filename = f"company/{uploaded_logo.name}"
                        settings_obj.logo.name = final_filename
                        save_logo_blob(final_filename, logo_bytes, content_type)
                        from pathlib import Path
                        from django.conf import settings
                        dest = Path(settings.MEDIA_ROOT) / final_filename
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(logo_bytes)
                    elif logo_cleared:
                        settings_obj.logo = None
                        clear_logo_blob()
                    settings_obj.save()
                    try:
                        from django.core.cache import cache
                        cache.delete('company_settings:singleton')
                    except Exception:
                        pass
                    messages.success(request, 'Company settings and showroom logo updated successfully!')
                    return redirect('accounts:company_settings')
                except Exception as fallback_err:
                    logging.getLogger(__name__).error("Fallback save also failed: %s", fallback_err)
                    messages.error(request, f'Unable to save company settings: {e}')
        else:
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


@login_required
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


def is_menu_allowed_for_tenant(business_type_attr, tenant, user=None):
    """
    Check if a menu item or sub-item with business_type ('retail', 'wholesale', or 'all')
    is applicable to the current tenant's business model (RETAIL, WHOLESALE, BOTH).
    If no tenant is specified, all options are allowed.
    """
    if not business_type_attr or business_type_attr == 'all':
        return True

    if not tenant:
        return True

    is_retail = getattr(tenant, 'is_retail', True)
    is_wholesale = getattr(tenant, 'is_wholesale', False)

    if business_type_attr == 'retail':
        return bool(is_retail)
    elif business_type_attr == 'wholesale':
        return bool(is_wholesale)

    return True


SIDEBAR_MENU_OPTIONS = (
    {
        'key': 'dashboard',
        'business_type': 'all',
        'name': 'Dashboard',
        'name_hi': 'डैशबोर्ड',
        'icon': 'bi-speedometer2',
        'category': 'Overview',
        'category_hi': 'विवरण / सारांश',
        'desc': 'Showroom dashboard overview, KPI summary statistics, and daily business metrics.',
        'desc_hi': 'शोरूम डैशबोर्ड विवरण, मुख्य केपीआई आंकड़े और दैनिक व्यापार मेट्रिक्स।',
        'sub_items': [],
    },
    {
        'key': 'sales',
        'business_type': 'retail',
        'name': 'Sales & Exchange',
        'name_hi': 'बिक्री एवं एक्सचेंज',
        'icon': 'bi-receipt',
        'category': 'Sales & Billing',
        'category_hi': 'बिक्री एवं बिलिंग',
        'desc': 'Counter retail sales billing, payments ledger, old gold exchange and buyback records.',
        'desc_hi': 'काउंटर खुदरा बिक्री बिलिंग, भुगतान लेज़र, पुराना सोना एक्सचेंज और बायबैक रिकॉर्ड्स।',
        'sub_items': [
            {
                'key': 'sub_sales_add',
                'business_type': 'retail',
                'name': 'New Sale (POS)',
                'name_hi': 'नई बिक्री (POS)',
                'icon': 'bi-cart-plus',
                'desc': 'Instant retail POS billing counter',
                'desc_hi': 'त्वरित खुदरा पीओएस बिलिंग काउंटर',
            },
            {
                'key': 'sub_sales_list',
                'business_type': 'retail',
                'name': 'All Sales & Bills',
                'name_hi': 'सभी बिक्री एवं बिल',
                'icon': 'bi-receipt',
                'desc': 'All customer sales invoices and cash memos',
                'desc_hi': 'सभी ग्राहक बिक्री बिल और कैश मेमो',
            },
            {
                'key': 'sub_sales_payments',
                'business_type': 'retail',
                'name': 'Payments & Receipts',
                'name_hi': 'भुगतान एवं रसीदें',
                'icon': 'bi-cash-coin',
                'desc': 'Customer advance receipts and split tender payments',
                'desc_hi': 'ग्राहक अग्रिम रसीदें और भुगतान विवरण',
            },
            {
                'key': 'sub_sales_og_exchange',
                'business_type': 'retail',
                'name': 'Old Gold Exchange',
                'name_hi': 'पुराना सोना एक्सचेंज',
                'icon': 'bi-arrow-repeat',
                'desc': 'Exchange customer old jewellery towards new bill',
                'desc_hi': 'पुराने आभूषण के बदले नए बिल में एक्सचेंज',
            },
            {
                'key': 'sub_sales_og_buyback',
                'business_type': 'retail',
                'name': 'Old Gold Buyback',
                'name_hi': 'पुराना सोना बायबैक',
                'icon': 'bi-cash-stack',
                'desc': 'Instant cash buyback for scrap gold/silver',
                'desc_hi': 'पुराने सोने/चांदी का नकद बायबैक',
            },
            {
                'key': 'sub_sales_og_history',
                'business_type': 'retail',
                'name': 'Old Gold History',
                'name_hi': 'पुराना सोना इतिहास',
                'icon': 'bi-journal-text',
                'desc': 'Historical old metal purchases and melt purity records',
                'desc_hi': 'पुराने सोने-चांदी के पूर्व रिकॉर्ड एवं शुद्धता',
            },
        ],
    },
    {
        'key': 'wholesale',
        'business_type': 'wholesale',
        'name': 'Wholesale & B2B',
        'name_hi': 'थोक व्यापार (B2B)',
        'icon': 'bi-buildings',
        'category': 'Sales & Billing',
        'category_hi': 'बिक्री एवं बिलिंग',
        'desc': 'B2B merchant portal, retailer parties, wholesale bulk order booking, dispatches, and ledger.',
        'desc_hi': 'B2B व्यापारी पोर्टल, खुदरा विक्रेता पार्टियां, थोक ऑर्डर बुकिंग, प्रेषण और लेज़र।',
        'sub_items': [
            {
                'key': 'sub_wholesale_dashboard',
                'business_type': 'wholesale',
                'name': 'Wholesale Dashboard',
                'name_hi': 'थोक डैशबोर्ड',
                'icon': 'bi-speedometer2',
                'desc': 'Executive wholesale operations telemetry and order pipelines',
                'desc_hi': 'थोक व्यापार संचालन टेलीमेट्री और ऑर्डर पाइपलाइन',
            },
            {
                'key': 'sub_wholesale_parties',
                'business_type': 'wholesale',
                'name': 'Retailer Parties',
                'name_hi': 'व्यापारी पार्टियां',
                'icon': 'bi-people',
                'desc': 'B2B customer master, credit limits, and contact directory',
                'desc_hi': 'B2B ग्राहक मास्टर, क्रेडिट सीमा और संपर्क निर्देशिका',
            },
            {
                'key': 'sub_wholesale_catalogue',
                'business_type': 'wholesale',
                'name': 'B2B Catalogue',
                'name_hi': 'B2B कैटलॉग',
                'icon': 'bi-grid-3x3-gap',
                'desc': 'Wholesale jewellery design catalogue with weight matrices',
                'desc_hi': 'वजन मैट्रिक्स के साथ थोक आभूषण डिज़ाइन कैटलॉग',
            },
            {
                'key': 'sub_wholesale_orders',
                'business_type': 'wholesale',
                'name': 'Wholesale Orders',
                'name_hi': 'थोक ऑर्डर्स',
                'icon': 'bi-bag-check',
                'desc': 'Bulk purchase orders booked by retail partners',
                'desc_hi': 'खुदरा भागीदारों द्वारा बुक किए गए थोक खरीद ऑर्डर',
            },
            {
                'key': 'sub_wholesale_dispatches',
                'business_type': 'wholesale',
                'name': 'Outward Dispatches',
                'name_hi': 'बाहरी प्रेषण',
                'icon': 'bi-truck',
                'desc': 'Track parcels, delivery challans, and courier manifests',
                'desc_hi': 'पार्सल, डिलीवरी चालान और कूरियर घोषणापत्र ट्रैक करें',
            },
            {
                'key': 'sub_wholesale_invoices',
                'business_type': 'wholesale',
                'name': 'Wholesale Invoices',
                'name_hi': 'थोक बिल / इनवॉइस',
                'icon': 'bi-receipt',
                'desc': 'Tax invoices, bullion settlement rate, and making breakdown',
                'desc_hi': 'टैक्स इनवॉइस, बुलियन निपटान दर और मेकिंग विवरण',
            },
            {
                'key': 'sub_wholesale_payments',
                'business_type': 'wholesale',
                'name': 'Wholesale Payments',
                'name_hi': 'थोक भुगतान',
                'icon': 'bi-cash-coin',
                'desc': 'Record multi-mode B2B payments, NEFT, and RTGS deposits',
                'desc_hi': 'मल्टी-मोड B2B भुगतान, NEFT और RTGS जमा रिकॉर्ड करें',
            },
            {
                'key': 'sub_wholesale_ledger',
                'business_type': 'wholesale',
                'name': 'Wholesale Khata Ledger',
                'name_hi': 'थोक खाता लेज़र',
                'icon': 'bi-journal-bookmark',
                'desc': 'Running metal balance and currency khata statement per merchant',
                'desc_hi': 'प्रत्येक व्यापारी का रनिंग मेटल बैलेंस और मुद्रा खाता विवरण',
            },
            {
                'key': 'sub_wholesale_returns',
                'business_type': 'wholesale',
                'name': 'Wholesale Returns',
                'name_hi': 'थोक वापसी',
                'icon': 'bi-arrow-return-left',
                'desc': 'Process credit notes and stock returns from retailers',
                'desc_hi': 'क्रेडिट नोट और खुदरा विक्रेताओं से स्टॉक वापसी संसाधित करें',
            },
        ],
    },
    {
        'key': 'outstation',
        'business_type': 'all',
        'name': 'Outstation Sales',
        'name_hi': 'आउटस्टेशन बिक्री',
        'icon': 'bi-airplane',
        'category': 'Sales & Billing',
        'category_hi': 'बिक्री एवं बिलिंग',
        'desc': 'Outstation sales trips, travelling representative orders, and exhibition expos.',
        'desc_hi': 'आउटस्टेशन बिक्री यात्राएं, यात्रा विक्रेता ऑर्डर और प्रदर्शनी एक्सपो।',
        'sub_items': [
            {
                'key': 'sub_outstation_trips',
                'business_type': 'all',
                'name': 'Sales Trips',
                'name_hi': 'बिक्री यात्राएं',
                'icon': 'bi-compass',
                'desc': 'Tour schedules, luggage tracking, and field orders',
                'desc_hi': 'दौरा कार्यक्रम, सामान ट्रैकिंग और फ़ील्ड ऑर्डर',
            },
            {
                'key': 'sub_outstation_new_trip',
                'business_type': 'all',
                'name': 'Create Sales Trip',
                'name_hi': 'नई यात्रा शुरू करें',
                'icon': 'bi-plus-circle',
                'desc': 'Initialize outward travel trunk with stock manifest',
                'desc_hi': 'स्टॉक घोषणापत्र के साथ यात्रा ट्रंक प्रारंभ करें',
            },
            {
                'key': 'sub_outstation_exhibitions',
                'business_type': 'all',
                'name': 'Exhibitions & Expos',
                'name_hi': 'प्रदर्शनी एवं एक्सपो',
                'icon': 'bi-easel2',
                'desc': 'Trade shows, B2B booths, and stall sales accounting',
                'desc_hi': 'ट्रेड शो, B2B बूथ और स्टॉल बिक्री लेखांकन',
            },
            {
                'key': 'sub_outstation_new_exhibition',
                'business_type': 'all',
                'name': 'Add Exhibition',
                'name_hi': 'नई प्रदर्शनी जोड़ें',
                'icon': 'bi-calendar-plus',
                'desc': 'Register new jewellery exhibition booth',
                'desc_hi': 'नया आभूषण प्रदर्शनी बूथ पंजीकृत करें',
            },
        ],
    },
    {
        'key': 'inventory',
        'business_type': 'all',
        'name': 'Jewellery Stock',
        'name_hi': 'आभूषण स्टॉक',
        'icon': 'bi-gem',
        'category': 'Inventory & Catalog',
        'category_hi': 'इन्वेंट्री एवं कैटलॉग',
        'desc': 'Physical stock items, weights, purity grades, BIS hallmarks, HUIDs & AI Photo Studio.',
        'desc_hi': 'भौतिक स्टॉक आभूषण, वजन, शुद्धता ग्रेड, बीआईएस हॉलमार्क, HUIDs और AI फोटो स्टूडियो।',
        'sub_items': [
            {
                'key': 'sub_inventory_items',
                'business_type': 'all',
                'name': 'All Stock Items',
                'name_hi': 'सभी स्टॉक आइटम',
                'icon': 'bi-gem',
                'desc': 'Complete inventory stock register with barcode labels',
                'desc_hi': 'बारकोड लेबल के साथ पूर्ण इन्वेंट्री स्टॉक रजिस्टर',
            },
            {
                'key': 'sub_inventory_categories',
                'business_type': 'all',
                'name': 'Category Management',
                'name_hi': 'कैटगरी प्रबंधन',
                'icon': 'bi-tag',
                'desc': 'Organize showroom jewellery into custom collections and categories',
                'desc_hi': 'शोरूम आभूषणों को कस्टम श्रेणियों और संग्रहों में व्यवस्थित करें',
            },
            {
                'key': 'sub_inventory_history',
                'business_type': 'all',
                'name': 'Stock Audit Log',
                'name_hi': 'स्टॉक ऑडिट लॉग',
                'icon': 'bi-clock-history',
                'desc': 'Timestamped audit trail of stock modifications',
                'desc_hi': 'स्टॉक संशोधनों का समयबद्ध ऑडिट ट्रेल',
            },
            {
                'key': 'sub_inventory_import',
                'business_type': 'all',
                'name': 'Import Excel / CSV',
                'name_hi': 'एक्सेल/सीएसवी आयात',
                'icon': 'bi-file-earmark-spreadsheet',
                'desc': 'Bulk upload jewellery stock catalog from spreadsheet',
                'desc_hi': 'स्प्रेडशीट से थोक आभूषण स्टॉक कैटलॉग अपलोड करें',
            },
            {
                'key': 'sub_inventory_photo_studio',
                'business_type': 'all',
                'name': 'AI Photo Studio',
                'name_hi': 'AI फोटो स्टूडियो',
                'icon': 'bi-camera',
                'desc': 'AI jewellery background enhancement and digital showroom rendering',
                'desc_hi': 'AI आभूषण बैकग्राउंड संवर्धन और डिजिटल रेंडरिंग',
            },
        ],
    },
    {
        'key': 'pricing',
        'business_type': 'all',
        'name': 'Pricing & Rates',
        'name_hi': 'मूल्य निर्धारण एवं दरें',
        'icon': 'bi-currency-rupee',
        'category': 'Inventory & Catalog',
        'category_hi': 'इन्वेंट्री एवं कैटलॉग',
        'desc': 'Live gold & silver bullion market rates, making charges, and retail price calculator.',
        'desc_hi': 'लाइव सोना और चांदी बुलियन बाजार दरें, मेकिंग चार्ज और खुदरा मूल्य कैलकुलेटर।',
        'sub_items': [
            {
                'key': 'sub_pricing_calculator',
                'business_type': 'all',
                'name': 'Price Calculator',
                'name_hi': 'मूल्य कैलकुलेटर',
                'icon': 'bi-calculator',
                'desc': 'Real-time retail price estimator based on current metal rates',
                'desc_hi': 'वर्तमान धातु दरों के आधार पर वास्तविक समय खुदरा मूल्य अनुमानक',
            },
            {
                'key': 'sub_pricing_rates',
                'business_type': 'all',
                'name': 'Live Bullion Rates',
                'name_hi': 'लाइव बुलियन दरें',
                'icon': 'bi-graph-up',
                'desc': 'Showroom gold, silver, and platinum daily base rates',
                'desc_hi': 'शोरूम सोना, चांदी और प्लैटिनम दैनिक आधार दरें',
            },
        ],
    },
    {
        'key': 'customers',
        'business_type': 'retail',
        'name': 'Customers',
        'name_hi': 'ग्राहक',
        'icon': 'bi-people',
        'category': 'CRM & Relationship',
        'category_hi': 'ग्राहक संबंध',
        'desc': 'Customer profiles, loyalty directory, outstanding credit khata, and sales enquiries.',
        'desc_hi': 'ग्राहक प्रोफाइल, लॉयल्टी डायरेक्टरी, बकाया उधारी खाता और बिक्री पूछताछ।',
        'sub_items': [
            {
                'key': 'sub_customers_list',
                'business_type': 'retail',
                'name': 'Customer Directory',
                'name_hi': 'ग्राहक निर्देशिका',
                'icon': 'bi-person-lines-fill',
                'desc': 'Customer ledger accounts, KYC records, and reward points',
                'desc_hi': 'ग्राहक खाता विवरण, केवाईसी रिकॉर्ड और रिवॉर्ड पॉइंट्स',
            },
            {
                'key': 'sub_customers_enquiries',
                'business_type': 'retail',
                'name': 'Sales Enquiries & Leads',
                'name_hi': 'बिक्री पूछताछ एवं लीड्स',
                'icon': 'bi-chat-left-text',
                'desc': 'Track visitor enquiries, callbacks, and interest pipeline',
                'desc_hi': 'आगंतुक पूछताछ, कॉलबैक और रुचि पाइपलाइन ट्रैक करें',
            },
        ],
    },
    {
        'key': 'marketing',
        'business_type': 'retail',
        'name': 'Marketing & Offers',
        'name_hi': 'मार्केटिंग एवं कूपन',
        'icon': 'bi-tag-fill',
        'category': 'CRM & Relationship',
        'category_hi': 'ग्राहक संबंध',
        'desc': 'Promotional campaigns, customer discount coupons, and festive offer vouchers.',
        'desc_hi': 'प्रमोशनल अभियान, ग्राहक डिस्काउंट कूपन और त्योहारी ऑफर वाउचर्स।',
        'sub_items': [
            {
                'key': 'sub_marketing_coupons',
                'business_type': 'retail',
                'name': 'All Coupons & Offers',
                'name_hi': 'सभी कूपन एवं ऑफर्स',
                'icon': 'bi-tags',
                'desc': 'Directory of active and upcoming discount coupons',
                'desc_hi': 'सक्रिय और आगामी डिस्काउंट कूपनों की सूची',
            },
            {
                'key': 'sub_marketing_create',
                'business_type': 'retail',
                'name': 'Create Offer',
                'name_hi': 'नया कूपन ऑफर',
                'icon': 'bi-plus-circle',
                'desc': 'Create new promotional discount or festive coupon',
                'desc_hi': 'नया प्रचारक डिस्काउंट या फेस्टिव कूपन बनाएं',
            },
            {
                'key': 'sub_marketing_reports',
                'business_type': 'retail',
                'name': 'Offer Reports',
                'name_hi': 'अभियान रिपोर्ट्स',
                'icon': 'bi-graph-up-arrow',
                'desc': 'Redemption telemetry and campaign performance',
                'desc_hi': 'कूपन उपयोग और अभियान प्रदर्शन आंकड़े',
            },
        ],
    },
    {
        'key': 'custom_orders',
        'business_type': 'retail',
        'name': 'Custom Orders',
        'name_hi': 'कस्टम ऑर्डर्स',
        'icon': 'bi-hammer',
        'category': 'Workshop & Manufacturing',
        'category_hi': 'कारीगर एवं निर्माण',
        'desc': 'Bespoke ornament customer orders, custom designs, CAD milestones, and delivery tracking.',
        'desc_hi': 'कस्टम आभूषण ग्राहक ऑर्डर, विशेष डिज़ाइन, सीएडी चरण और डिलीवरी ट्रैकिंग।',
        'sub_items': [
            {
                'key': 'sub_custom_orders_list',
                'business_type': 'retail',
                'name': 'All Custom Orders',
                'name_hi': 'सभी कस्टम ऑर्डर्स',
                'icon': 'bi-list-task',
                'desc': 'Order pipeline from CAD stage to final showroom delivery',
                'desc_hi': 'सीएडी चरण से अंतिम शोरूम डिलीवरी तक ऑर्डर पाइपलाइन',
            },
            {
                'key': 'sub_custom_orders_add',
                'business_type': 'retail',
                'name': 'New Custom Order',
                'name_hi': 'नया कस्टम ऑर्डर',
                'icon': 'bi-plus-circle',
                'desc': 'Book new custom jewellery order with gold advance',
                'desc_hi': 'सोना अग्रिम के साथ नया कस्टम आभूषण ऑर्डर बुक करें',
            },
        ],
    },
    {
        'key': 'karigar',
        'business_type': 'all',
        'name': 'Karigar & Workshop',
        'name_hi': 'कारीगर एवं वर्कशॉप',
        'icon': 'bi-tools',
        'category': 'Workshop & Manufacturing',
        'category_hi': 'कारीगर एवं निर्माण',
        'desc': 'Artisan job cards, gold issue/receive weights, scrap recovery, and karigar wage settlements.',
        'desc_hi': 'कारीगर जॉब कार्ड, सोना जारी/प्राप्ति वजन, छीलन रिकवरी और मजदूरी भुगतान।',
        'sub_items': [
            {
                'key': 'sub_karigar_dashboard',
                'business_type': 'all',
                'name': 'Workshop Dashboard',
                'name_hi': 'वर्कशॉप डैशबोर्ड',
                'icon': 'bi-speedometer2',
                'desc': 'Manufacturing telemetry, pending pieces, and artisan capacity',
                'desc_hi': 'निर्माण टेलीमेट्री, लंबित आभूषण और कारीगर कार्यक्षमता',
            },
            {
                'key': 'sub_karigar_list',
                'business_type': 'all',
                'name': 'Artisans Directory',
                'name_hi': 'कारीगर निर्देशिका',
                'icon': 'bi-person-workspace',
                'desc': 'Artisans profile, skills, metal purity ledger, and contacts',
                'desc_hi': 'कारीगर प्रोफाइल, कौशल, धातु शुद्धता लेज़र और संपर्क',
            },
            {
                'key': 'sub_karigar_assignments',
                'business_type': 'all',
                'name': 'Active Job Cards',
                'name_hi': 'सक्रिय जॉब कार्ड्स',
                'icon': 'bi-journal-check',
                'desc': 'Live assignments with issued gold/silver bullion weights',
                'desc_hi': 'जारी सोना/चांदी बुलियन वजन के साथ सक्रिय असाइनमेंट',
            },
            {
                'key': 'sub_karigar_pending',
                'business_type': 'all',
                'name': 'Pending Deliveries',
                'name_hi': 'लंबित निर्माण डिलीवरी',
                'icon': 'bi-hourglass-split',
                'desc': 'Jobs due for delivery from artisans to showroom vault',
                'desc_hi': 'कारीगरों से शोरूम वॉल्ट तक डिलीवरी के लिए लंबित कार्य',
            },
            {
                'key': 'sub_karigar_settlements',
                'business_type': 'all',
                'name': 'Wage Settlements',
                'name_hi': 'मजदूरी निपटान',
                'icon': 'bi-cash-coin',
                'desc': 'Making wage calculation, metal balance settlement, and receipts',
                'desc_hi': 'मेकिंग मजदूरी गणना, धातु संतुलन निपटान और रसीदें',
            },
        ],
    },
    {
        'key': 'girvi',
        'business_type': 'all',
        'name': 'Girvi Management',
        'name_hi': 'गिरवी प्रबंधन',
        'icon': 'bi-safe',
        'category': 'Financial Services',
        'category_hi': 'वित्तीय सेवाएं',
        'desc': 'Pledged jewellery loans, collateral tracking, interest calculation, and pledge release.',
        'desc_hi': 'गिरवी सोने के ऋण, बंधक आभूषण ट्रैकिंग, ब्याज गणना और गिरवी छुड़ाना।',
        'sub_items': [
            {
                'key': 'sub_girvi_dashboard',
                'business_type': 'all',
                'name': 'Girvi Dashboard',
                'name_hi': 'गिरवी डैशबोर्ड',
                'icon': 'bi-speedometer2',
                'desc': 'Overview of active girvi loans, interest due, and collateral',
                'desc_hi': 'सक्रिय गिरवी ऋणों, देय ब्याज और बंधक आभूषणों का विवरण',
            },
            {
                'key': 'sub_girvi_create',
                'business_type': 'all',
                'name': 'New Girvi Loan',
                'name_hi': 'नया गिरवी ऋण',
                'icon': 'bi-plus-circle',
                'desc': 'Issue a new pledged jewellery loan record',
                'desc_hi': 'नया बंधक आभूषण ऋण दर्ज करें',
            },
        ],
    },
    {
        'key': 'team',
        'business_type': 'all',
        'name': 'Team & HR',
        'name_hi': 'टीम एवं एचआर',
        'icon': 'bi-person-badge',
        'category': 'Administration',
        'category_hi': 'प्रशासनिक सेटिंग्स',
        'desc': 'Counter sales staff, store employees, role-based module permissions, and showroom branches.',
        'desc_hi': 'काउंटर सेल्स स्टाफ, स्टोर कर्मचारी, भूमिका-आधारित अनुमतियां और शोरूम शाखाएं।',
        'sub_items': [
            {
                'key': 'sub_team_employees',
                'business_type': 'all',
                'name': 'Staff Directory',
                'name_hi': 'स्टाफ निर्देशिका',
                'icon': 'bi-people',
                'desc': 'Active staff roster, login accounts, and branch assignment',
                'desc_hi': 'सक्रिय स्टाफ रोस्टर, लॉगिन खाते और शाखा असाइनमेंट',
            },
            {
                'key': 'sub_team_add_employee',
                'business_type': 'all',
                'name': 'Add Staff Member',
                'name_hi': 'नया कर्मचारी जोड़ें',
                'icon': 'bi-person-plus',
                'desc': 'Onboard new counter sales, karigar manager, or cashier',
                'desc_hi': 'नया काउंटर सेल्स, कारीगर मैनेजर या कैशियर ऑनबोर्ड करें',
            },
            {
                'key': 'sub_team_roles',
                'business_type': 'all',
                'name': 'Roles & Permissions',
                'name_hi': 'भूमिकाएं एवं अनुमतियां',
                'icon': 'bi-shield-check',
                'desc': 'Granular feature permissions for cashier, manager, and staff',
                'desc_hi': 'कैशियर, मैनेजर और कर्मचारियों के लिए विस्तृत अनुमतियां',
            },
            {
                'key': 'sub_team_branches',
                'business_type': 'all',
                'name': 'Showroom Branches',
                'name_hi': 'शोरूम शाखाएं',
                'icon': 'bi-building',
                'desc': 'Manage multiple physical retail outlets and stock vaults',
                'desc_hi': 'कई खुदरा स्टोर और स्टॉक वॉल्ट प्रबंधित करें',
            },
        ],
    },
    {
        'key': 'reports',
        'business_type': 'all',
        'name': 'Reports & Analytics',
        'name_hi': 'रिपोर्ट्स एवं विश्लेषण',
        'icon': 'bi-bar-chart-line',
        'category': 'Administration',
        'category_hi': 'प्रशासनिक सेटिंग्स',
        'desc': 'Comprehensive retail GST invoices, wholesale turnover ledgers, and artisan workshop reports.',
        'desc_hi': 'विस्तृत खुदरा जीएसटी इनवॉइस, थोक कारोबार लेज़र और कारीगर वर्कशॉप रिपोर्ट।',
        'sub_items': [
            {
                'key': 'sub_reports_retail',
                'business_type': 'retail',
                'name': 'Retail Sales Report',
                'name_hi': 'खुदरा बिक्री रिपोर्ट',
                'icon': 'bi-receipt',
                'desc': 'Counter sales bills and GST breakdown',
                'desc_hi': 'काउंटर बिक्री बिल और जीएसटी रिपोर्ट',
            },
            {
                'key': 'sub_reports_wholesale',
                'business_type': 'wholesale',
                'name': 'Wholesale Reports',
                'name_hi': 'थोक व्यापार रिपोर्ट',
                'icon': 'bi-bar-chart-line',
                'desc': 'B2B turnover, dispatch ledgers, and pending bills',
                'desc_hi': 'B2B टर्नओवर, प्रेषण लेज़र और बकाया बिल',
            },
            {
                'key': 'sub_reports_karigar',
                'business_type': 'all',
                'name': 'Karigar Workshop Reports',
                'name_hi': 'कारीगर वर्कशॉप रिपोर्ट',
                'icon': 'bi-tools',
                'desc': 'Metal issue/receipt ledgers and wastage telemetry',
                'desc_hi': 'सोना जारी/प्राप्ति लेज़र और छीलन रिपोर्ट',
            },
        ],
    },
    {
        'key': 'settings',
        'business_type': 'all',
        'name': 'Settings',
        'name_hi': 'सेटिंग्स',
        'icon': 'bi-gear',
        'category': 'Administration',
        'category_hi': 'प्रशासनिक सेटिंग्स',
        'desc': 'Company branding, invoice settings, themes and menu bar customization.',
        'desc_hi': 'कंपनी ब्रांडिंग, इनवॉइस सेटिंग्स, थीम्स और मेनू बार कस्टमाइज़ेशन।',
        'sub_items': [
            {
                'key': 'sub_settings_company',
                'business_type': 'all',
                'name': 'Company Settings',
                'name_hi': 'कंपनी सेटिंग्स',
                'icon': 'bi-building-gear',
                'desc': 'Store name, GSTIN, invoice prefix, contact details, and showroom logo',
                'desc_hi': 'स्टोर का नाम, जीएसटी नंबर, इनवॉइस प्रीफिक्स और शोरूम लोगो',
            },
            {
                'key': 'sub_settings_themes',
                'business_type': 'all',
                'name': 'Themes & Appearance',
                'name_hi': 'थीम एवं दिखावट',
                'icon': 'bi-palette',
                'desc': 'Switch Dark Roast Gold or Royal Alabaster showroom themes',
                'desc_hi': 'डार्क रोस्ट गोल्ड या रॉयल अलाबास्टर शोरूम थीम चुनें',
            },
        ],
    },
    {
        'key': 'app_install',
        'business_type': 'all',
        'name': 'Get the App',
        'name_hi': 'ऐप डाउनलोड करें',
        'icon': 'bi-phone',
        'category': 'App & Shortcuts',
        'category_hi': 'ऐप और शॉर्टकट',
        'desc': 'Install JwelDesk Android APK / PWA application on mobile and tablet.',
        'desc_hi': 'मोबाइल और टैबलेट पर ज्वेलडेस्क एंड्रॉइड ऐप / PWA इंस्टॉल करें।',
        'sub_items': [],
    },
)

@login_required
def menu_settings(request):
    """Configure which sidebar navigation menu options and sub-options are visible or hidden for the active store."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        tenant = getattr(request.user, 'owned_tenants', None)
        tenant = tenant.first() if tenant else None

    # Tenant admin permission check
    if tenant and not request.user.is_superuser:
        from team.permissions import is_admin_user
        if not (is_admin_user(request.user, tenant=tenant) or tenant.owner_id == request.user.id):
            messages.error(request, 'Access restricted. Only store administrators can modify menu bar settings.')
            return redirect('dashboard')

    settings_obj = CompanySettings.load(tenant=tenant)

    # Collect valid keys across modules and sub-options matching this tenant's business model
    visible_valid_keys = set()
    for item in SIDEBAR_MENU_OPTIONS:
        if is_menu_allowed_for_tenant(item.get('business_type', 'all'), tenant, request.user):
            visible_valid_keys.add(item['key'])
            for sub in item.get('sub_items', []):
                if is_menu_allowed_for_tenant(sub.get('business_type', 'all'), tenant, request.user):
                    visible_valid_keys.add(sub['key'])

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'unhide_all':
            existing_hidden = set(settings_obj.get_hidden_menus())
            existing_hidden -= visible_valid_keys
            settings_obj.hidden_menu_items = ','.join(sorted(existing_hidden))
            settings_obj.save()
            messages.success(request, 'All menu options and sub-options have been restored and unhidden!')
            return redirect('accounts:menu_settings')

        submitted_lists = set(request.POST.getlist('hidden_menus') + request.POST.getlist('hidden_items'))
        existing_hidden = set(settings_obj.get_hidden_menus())
        for key in visible_valid_keys:
            if request.POST.get(f'hide_{key}') in ('1', 'on', 'true') or key in submitted_lists:
                existing_hidden.add(key)
            else:
                existing_hidden.discard(key)

        settings_obj.hidden_menu_items = ','.join(sorted(existing_hidden))
        settings_obj.save()
        messages.success(request, 'Menu bar navigation settings updated successfully!')
        return redirect('accounts:menu_settings')

    is_hindi = (
        request.session.get('django_language') == 'hi'
        or request.COOKIES.get('django_language') == 'hi'
        or request.COOKIES.get('jd_language') == 'hi'
        or (settings_obj and getattr(settings_obj, 'language', None) == 'hi')
    )

    hidden_set = set(settings_obj.get_hidden_menus())
    menu_items_with_state = []
    total_options_count = 0
    total_hidden_count = 0

    for item in SIDEBAR_MENU_OPTIONS:
        if not is_menu_allowed_for_tenant(item.get('business_type', 'all'), tenant, request.user):
            continue

        is_hidden = item['key'] in hidden_set
        name_val = item.get('name_hi') if is_hindi else item['name']
        desc_val = item.get('desc_hi') if is_hindi else item['desc']
        cat_val = item.get('category_hi') if is_hindi else item.get('category', 'General')

        processed_subs = []
        for sub in item.get('sub_items', []):
            if not is_menu_allowed_for_tenant(sub.get('business_type', 'all'), tenant, request.user):
                continue

            sub_is_hidden = sub['key'] in hidden_set
            total_options_count += 1
            if sub_is_hidden:
                total_hidden_count += 1
            processed_subs.append({
                'key': sub['key'],
                'name': sub.get('name_hi') if is_hindi else sub['name'],
                'desc': sub.get('desc_hi') if is_hindi else sub.get('desc', ''),
                'english_name': sub['name'],
                'icon': sub.get('icon', 'bi-circle'),
                'is_hidden': sub_is_hidden,
            })

        total_options_count += 1
        if is_hidden:
            total_hidden_count += 1

        menu_items_with_state.append({
            'key': item['key'],
            'name': name_val,
            'desc': desc_val,
            'category': cat_val,
            'english_name': item['name'],
            'icon': item['icon'],
            'is_hidden': is_hidden,
            'is_locked': item.get('is_locked', False),
            'sub_items': processed_subs,
            'sub_count': len(processed_subs),
        })

    hidden_count = sum(1 for it in menu_items_with_state if it['is_hidden'])
    visible_count = len(menu_items_with_state) - hidden_count

    return render(request, 'accounts/menu_settings.html', {
        'menu_options': menu_items_with_state,
        'hidden_count': hidden_count,
        'visible_count': visible_count,
        'total_count': len(menu_items_with_state),
        'total_options_count': total_options_count,
        'total_hidden_count': total_hidden_count,
        'settings_obj': settings_obj,
        'is_hindi': is_hindi,
    })


@login_required
def menu_toggle_api(request):
    """AJAX endpoint for instant real-time toggle of menu bar or sub-option visibility."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required.'}, status=405)

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        tenant = getattr(request.user, 'owned_tenants', None)
        tenant = tenant.first() if tenant else None

    if tenant and not request.user.is_superuser:
        from team.permissions import is_admin_user
        if not (is_admin_user(request.user, tenant=tenant) or tenant.owner_id == request.user.id):
            return JsonResponse({'error': 'Only store administrators can modify menu settings.'}, status=403)

    import json
    menu_key = None
    is_hidden = None

    if request.content_type == 'application/json':
        try:
            payload = json.loads(request.body.decode('utf-8'))
            menu_key = payload.get('menu_key')
            if 'is_hidden' in payload:
                is_hidden = payload.get('is_hidden')
            elif 'hide' in payload:
                is_hidden = payload.get('hide')
        except Exception:
            pass
    else:
        menu_key = request.POST.get('menu_key')
        is_hidden_raw = request.POST.get('is_hidden') if request.POST.get('is_hidden') is not None else request.POST.get('hide')
        if is_hidden_raw is not None:
            if isinstance(is_hidden_raw, bool):
                is_hidden = is_hidden_raw
            else:
                is_hidden = str(is_hidden_raw).lower() in ('1', 'true', 'on', 'yes')

    visible_valid_keys = set()
    for item in SIDEBAR_MENU_OPTIONS:
        if is_menu_allowed_for_tenant(item.get('business_type', 'all'), tenant, request.user):
            visible_valid_keys.add(item['key'])
            for sub in item.get('sub_items', []):
                if is_menu_allowed_for_tenant(sub.get('business_type', 'all'), tenant, request.user):
                    visible_valid_keys.add(sub['key'])

    if not menu_key or menu_key not in visible_valid_keys:
        return JsonResponse({'error': f"Menu option '{menu_key}' is not available for this business model."}, status=400)

    if is_hidden is None:
        return JsonResponse({'error': 'is_hidden flag is required.'}, status=400)

    settings_obj = CompanySettings.load(tenant=tenant)
    settings_obj.set_menu_hidden(menu_key, is_hidden=bool(is_hidden))
    settings_obj.save()

    hidden_list = settings_obj.get_hidden_menus()
    return JsonResponse({
        'success': True,
        'menu_key': menu_key,
        'is_hidden': bool(is_hidden),
        'hidden_count': len(hidden_list),
        'hidden_menus': hidden_list,
        'message': f"Menu option '{menu_key}' is now {'hidden' if is_hidden else 'visible'}.",
    })


def set_language_view(request):
    """
    Switch application UI language between English ('en') and Hindi ('hi').
    Saves language choice to:
      1. Tenant's CompanySettings record (if authenticated tenant owner/admin)
      2. request.session['django_language']
      3. response cookie 'django_language' and 'jd_language'
    Supports both traditional POST/GET and AJAX requests.
    """
    import json
    lang_code = None

    if request.content_type == 'application/json':
        try:
            payload = json.loads(request.body.decode('utf-8'))
            lang_code = payload.get('language')
        except Exception:
            pass

    if not lang_code:
        lang_code = request.POST.get('language') or request.GET.get('language')

    if not lang_code or lang_code not in ('en', 'hi'):
        lang_code = 'en'

    # 1. Update company settings if user has a tenant
    tenant = getattr(request, 'tenant', None)
    if not tenant and request.user.is_authenticated:
        tenant = getattr(request.user, 'owned_tenants', None)
        tenant = tenant.first() if tenant else None

    if tenant:
        try:
            settings_obj = CompanySettings.load(tenant=tenant)
            settings_obj.language = lang_code
            settings_obj.save()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to save language to CompanySettings: %s", e)

    # 2. Update session
    if hasattr(request, 'session'):
        request.session['django_language'] = lang_code

    try:
        from django.utils import translation
        translation.activate(lang_code)
    except Exception:
        pass

    # 3. Respond
    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or request.content_type == 'application/json'
    )
    if is_ajax:
        res = JsonResponse({
            'success': True,
            'language': lang_code,
            'label': 'हिंदी' if lang_code == 'hi' else 'English',
            'message': 'भाषा बदलकर हिंदी कर दी गई है।' if lang_code == 'hi' else 'Language changed to English.',
        })
        res.set_cookie('django_language', lang_code, max_age=365*24*60*60, path='/')
        res.set_cookie('jd_language', lang_code, max_age=365*24*60*60, path='/')
        return res

    next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER') or '/'
    from urllib.parse import urlparse
    if urlparse(next_url).netloc and urlparse(next_url).netloc != request.get_host():
        next_url = '/'

    if lang_code == 'hi':
        messages.success(request, 'सिस्टम की भाषा सफलतापूर्वक बदलकर हिंदी कर दी गई है। (System language switched to Hindi)')
    else:
        messages.success(request, 'System language successfully switched to English.')

    res = redirect(next_url)
    res.set_cookie('django_language', lang_code, max_age=365*24*60*60, path='/')
    res.set_cookie('jd_language', lang_code, max_age=365*24*60*60, path='/')
    return res


def trial_expired_view(request):
    """
    Render professional Trial Expired page for showroom tenants whose 15-day trial has concluded.
    Displays clear explanation, reassurance of data safety, and direct renewal contact actions.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return redirect('accounts:login')

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return redirect('accounts:login')

    sub = getattr(tenant, 'subscription', None)

    # If subscription is active and unexpired, redirect to dashboard
    from super_admin.trial_services import is_tenant_subscription_active
    if is_tenant_subscription_active(tenant):
        return redirect('dashboard')

    is_owner = (tenant.owner_id == user.id)

    context = {
        'tenant': tenant,
        'subscription': sub,
        'is_owner': is_owner,
        'support_phone': '+91 98765 43210',
        'support_email': 'support@jweldesk.com',
        'whatsapp_number': '+91 98765 43210',
    }
    return render(request, 'accounts/trial_expired.html', context)

