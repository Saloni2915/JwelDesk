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


SIDEBAR_MENU_OPTIONS = (
    {
        'key': 'dashboard',
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
                'name': 'New Sale (POS)',
                'name_hi': 'नई बिक्री (POS)',
                'icon': 'bi-cart-plus',
                'desc': 'Instant retail POS billing counter',
                'desc_hi': 'त्वरित खुदरा पीओएस बिलिंग काउंटर',
            },
            {
                'key': 'sub_sales_list',
                'name': 'All Sales & Bills',
                'name_hi': 'सभी बिक्री एवं बिल',
                'icon': 'bi-receipt',
                'desc': 'All customer sales invoices and cash memos',
                'desc_hi': 'सभी ग्राहक बिक्री बिल और कैश मेमो',
            },
            {
                'key': 'sub_sales_payments',
                'name': 'Payments & Receipts',
                'name_hi': 'भुगतान एवं रसीदें',
                'icon': 'bi-cash-coin',
                'desc': 'Customer advance receipts and split tender payments',
                'desc_hi': 'ग्राहक अग्रिम रसीदें और भुगतान विवरण',
            },
            {
                'key': 'sub_sales_og_exchange',
                'name': 'Old Gold Exchange',
                'name_hi': 'पुराना सोना एक्सचेंज',
                'icon': 'bi-arrow-repeat',
                'desc': 'Exchange customer old jewellery towards new bill',
                'desc_hi': 'पुराने आभूषण के बदले नए बिल में एक्सचेंज',
            },
            {
                'key': 'sub_sales_og_buyback',
                'name': 'Old Gold Buyback',
                'name_hi': 'पुराना सोना बायबैक',
                'icon': 'bi-cash-stack',
                'desc': 'Instant cash buyback for scrap gold/silver',
                'desc_hi': 'पुराने सोने/चांदी का नकद बायबैक',
            },
            {
                'key': 'sub_sales_og_history',
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
                'name': 'Wholesale Dashboard',
                'name_hi': 'थोक डैशबोर्ड',
                'icon': 'bi-speedometer2',
                'desc': 'B2B overview, orders, and merchant KPIs',
                'desc_hi': 'थोक व्यापार सारांश और केपीआई आंकड़े',
            },
            {
                'key': 'sub_wholesale_parties',
                'name': 'Retailers / Parties',
                'name_hi': 'खुदरा विक्रेता / पार्टियां',
                'icon': 'bi-shop',
                'desc': 'Wholesale merchant accounts and store parties',
                'desc_hi': 'थोक व्यापारी खाते और खुदरा स्टोर पार्टियां',
            },
            {
                'key': 'sub_wholesale_catalogue',
                'name': 'Products & Pricing',
                'name_hi': 'उत्पाद एवं मूल्य निर्धारण',
                'icon': 'bi-gem',
                'desc': 'Wholesale catalogue and tiered discount rules',
                'desc_hi': 'थोक उत्पाद कैटलॉग और मूल्य नियम',
            },
            {
                'key': 'sub_wholesale_orders',
                'name': 'Wholesale Orders',
                'name_hi': 'थोक ऑर्डर्स',
                'icon': 'bi-bag-check',
                'desc': 'Bulk merchant bookings and production status',
                'desc_hi': 'थोक व्यापार बुकिंग और उत्पादन स्थिति',
            },
            {
                'key': 'sub_wholesale_dispatches',
                'name': 'Dispatches & Shipping',
                'name_hi': 'प्रेषण एवं शिपिंग',
                'icon': 'bi-truck',
                'desc': 'Parcel dispatches, logistics, and delivery slips',
                'desc_hi': 'पार्सल प्रेषण, लॉजिस्टिक्स और डिलीवरी रसीदें',
            },
            {
                'key': 'sub_wholesale_invoices',
                'name': 'Wholesale Invoices',
                'name_hi': 'थोक बिल / इनवॉइस',
                'icon': 'bi-receipt',
                'desc': 'B2B tax invoices and GST delivery challans',
                'desc_hi': 'थोक जीएसटी बिल और डिलीवरी चालान',
            },
            {
                'key': 'sub_wholesale_payments',
                'name': 'Payments Received',
                'name_hi': 'प्राप्त भुगतान',
                'icon': 'bi-cash-stack',
                'desc': 'B2B payment collections and bank receipts',
                'desc_hi': 'थोक वसूली और बैंक भुगतान रसीदें',
            },
            {
                'key': 'sub_wholesale_ledger',
                'name': 'Party Ledger',
                'name_hi': 'पार्टी खाता बही',
                'icon': 'bi-journal-text',
                'desc': 'Retailer party outstanding balance and statements',
                'desc_hi': 'पार्टी बकाया उधारी और विस्तृत खाता विवरण',
            },
            {
                'key': 'sub_wholesale_returns',
                'name': 'Returns & Credit Notes',
                'name_hi': 'वापसी एवं क्रेडिट नोट',
                'icon': 'bi-arrow-return-left',
                'desc': 'Goods returns and wholesale credit notes',
                'desc_hi': 'माल वापसी और क्रेडिट नोट जारी करना',
            },
        ],
    },
    {
        'key': 'outstation',
        'name': 'Outstation Sales',
        'name_hi': 'आउटस्टेशन बिक्री',
        'icon': 'bi-airplane-engines',
        'category': 'Sales & Billing',
        'category_hi': 'बिक्री एवं बिलिंग',
        'desc': 'Outstation sales trips, travelling representative orders, and exhibition expos.',
        'desc_hi': 'आउटस्टेशन बिक्री यात्राएं, प्रतिनिधि ऑर्डर्स और आभूषण प्रदर्शनी एक्सपो।',
        'sub_items': [
            {
                'key': 'sub_outstation_trips',
                'name': 'All Trips & Dashboard',
                'name_hi': 'सभी यात्राएं एवं डैशबोर्ड',
                'icon': 'bi-briefcase',
                'desc': 'Sales agent trips, samples carried and tour summary',
                'desc_hi': 'प्रतिनिधि दौरे, सैंपल स्टॉक और यात्रा सारांश',
            },
            {
                'key': 'sub_outstation_new_trip',
                'name': 'New Trip',
                'name_hi': 'नई यात्रा',
                'icon': 'bi-plus-circle',
                'desc': 'Create new outstation route and issue jewellery box',
                'desc_hi': 'नया आउटस्टेशन दौरा दर्ज करें और बॉक्स जारी करें',
            },
            {
                'key': 'sub_outstation_exhibitions',
                'name': 'Exhibitions & Expos',
                'name_hi': 'प्रदर्शनी एवं एक्सपो',
                'icon': 'bi-building',
                'desc': 'Jewellery exhibitions, stall orders, and trade expos',
                'desc_hi': 'आभूषण प्रदर्शनियां, स्टॉल और एक्सपो ऑर्डर्स',
            },
            {
                'key': 'sub_outstation_new_exhibition',
                'name': 'Register Exhibition',
                'name_hi': 'नई प्रदर्शनी दर्ज करें',
                'icon': 'bi-plus-square',
                'desc': 'Register upcoming jewellery expo participation',
                'desc_hi': 'आगामी आभूषण प्रदर्शनी में भागीदारी दर्ज करें',
            },
        ],
    },
    {
        'key': 'inventory',
        'name': 'Jewellery Stock',
        'name_hi': 'आभूषण स्टॉक',
        'icon': 'bi-gem',
        'category': 'Inventory & Catalog',
        'category_hi': 'इन्वेंट्री एवं कैटलॉग',
        'desc': 'Physical stock items, weights, purity grades, BIS hallmarks, HUIDs & AI Photo Studio.',
        'desc_hi': 'भौतिक स्टॉक आभूषण, वज़न, शुद्धता ग्रेड, बीआईएस हॉलमार्क, एचयूआईडी और एआई फोटो स्टूडियो।',
        'sub_items': [
            {
                'key': 'sub_inventory_items',
                'name': 'All Stock Items',
                'name_hi': 'सभी स्टॉक आभूषण',
                'icon': 'bi-gem',
                'desc': 'Catalog of live ornaments with tags and purity',
                'desc_hi': 'टैग, वज़न और शुद्धता के साथ स्टॉक सूची',
            },
            {
                'key': 'sub_inventory_history',
                'name': 'Stock History',
                'name_hi': 'स्टॉक गतिविधि इतिहास',
                'icon': 'bi-arrow-left-right',
                'desc': 'Stock additions, adjustments, inward and outward logs',
                'desc_hi': 'स्टॉक आगमन, निकासी और परिवर्तन इतिहास',
            },
            {
                'key': 'sub_inventory_import',
                'name': 'Import Stock',
                'name_hi': 'स्टॉक आयात',
                'icon': 'bi-upload',
                'desc': 'Bulk upload jewellery items via Excel/CSV spreadsheet',
                'desc_hi': 'एक्सेल/सीएसवी से थोक स्टॉक आयात करें',
            },
            {
                'key': 'sub_inventory_photo_studio',
                'name': 'AI Photo Studio',
                'name_hi': 'एआई फोटो स्टूडियो',
                'icon': 'bi-camera-fill',
                'desc': 'AI jewellery photography background enhancer',
                'desc_hi': 'आभूषणों के लिए एआई फोटो बैकग्राउंड स्टूडियो',
            },
        ],
    },
    {
        'key': 'pricing',
        'name': 'Pricing & Rates',
        'name_hi': 'मूल्य एवं दरें',
        'icon': 'bi-calculator',
        'category': 'Inventory & Catalog',
        'category_hi': 'इन्वेंट्री एवं कैटलॉग',
        'desc': 'Live gold & silver bullion market rates, making charges, and retail price calculator.',
        'desc_hi': 'सोना एवं चांदी के लाइव बाजार भाव, मेकिंग चार्ज नियम और खुदरा मूल्य कैलकुलेटर।',
        'sub_items': [
            {
                'key': 'sub_pricing_calculator',
                'name': 'Price Calculator',
                'name_hi': 'मूल्य कैलकुलेटर',
                'icon': 'bi-calculator',
                'desc': 'Estimate live jewellery retail sale price and taxes',
                'desc_hi': 'लाइव धातु भाव और बनाई के साथ अनुमानित मूल्य',
            },
            {
                'key': 'sub_pricing_rates',
                'name': 'Metal Rates',
                'name_hi': 'धातु के भाव (Metal Rates)',
                'icon': 'bi-coin',
                'desc': 'Daily gold and silver market buying/selling rates',
                'desc_hi': 'दैनिक सोना और चांदी के क्रय-विक्रय बाजार भाव',
            },
        ],
    },
    {
        'key': 'customers',
        'name': 'Customers',
        'name_hi': 'ग्राहक (कस्टमर)',
        'icon': 'bi-people',
        'category': 'CRM & Relationship',
        'category_hi': 'ग्राहक संबंध (CRM)',
        'desc': 'Customer profiles, loyalty directory, outstanding credit khata, and sales enquiries.',
        'desc_hi': 'ग्राहक प्रोफ़ाइल, लॉयल्टी डायरेक्टरी, बकाया उधारी खाता और बिक्री पूछताछ।',
        'sub_items': [
            {
                'key': 'sub_customers_list',
                'name': 'All Customers',
                'name_hi': 'सभी ग्राहक',
                'icon': 'bi-people',
                'desc': 'Customer database, contact directory and balance khata',
                'desc_hi': 'ग्राहक संपर्क सूची और उधारी/जमा खाता',
            },
            {
                'key': 'sub_customers_enquiries',
                'name': 'Customer Enquiries',
                'name_hi': 'ग्राहक पूछताछ',
                'icon': 'bi-chat-left-text',
                'desc': 'Follow up showroom leads, requests and wedding quotes',
                'desc_hi': 'दुकान पूछताछ, लीड्स और शादी के कोटेशन',
            },
        ],
    },
    {
        'key': 'custom_orders',
        'name': 'Custom Orders',
        'name_hi': 'कस्टम ऑर्डर्स',
        'icon': 'bi-hammer',
        'category': 'Workshop & Manufacturing',
        'category_hi': 'वर्कशॉप एवं निर्माण',
        'desc': 'Bespoke ornament customer orders, custom designs, CAD milestones, and delivery tracking.',
        'desc_hi': 'कस्टम आभूषण ऑर्डर्स, विशेष डिज़ाइन, सीएडी चरण और डिलीवरी ट्रैकिंग।',
        'sub_items': [
            {
                'key': 'sub_custom_orders_list',
                'name': 'All Custom Orders',
                'name_hi': 'सभी कस्टम ऑर्डर्स',
                'icon': 'bi-hammer',
                'desc': 'Directory of bespoke orders with milestones and due dates',
                'desc_hi': 'कस्टम आभूषण ऑर्डर्स और डिलीवरी तारीखें',
            },
            {
                'key': 'sub_custom_orders_add',
                'name': 'New Custom Order',
                'name_hi': 'नया कस्टम ऑर्डर',
                'icon': 'bi-plus-circle',
                'desc': 'Book bespoke jewellery order with design reference',
                'desc_hi': 'डिज़ाइन और अग्रिम भुगतान के साथ नया ऑर्डर लें',
            },
        ],
    },
    {
        'key': 'karigar',
        'name': 'Karigar & Workshop',
        'name_hi': 'कारीगर एवं कार्यशाला',
        'icon': 'bi-person-workspace',
        'category': 'Workshop & Manufacturing',
        'category_hi': 'वर्कशॉप एवं निर्माण',
        'desc': 'Artisan job cards, gold issue/receive weights, scrap recovery, and karigar wage settlements.',
        'desc_hi': 'कारीगर जॉब कार्ड, सोना जारी/प्राप्ति वज़न, छीलन रिकवरी और मजदूरी भुगतान।',
        'sub_items': [
            {
                'key': 'sub_karigar_dashboard',
                'name': 'Karigar Dashboard',
                'name_hi': 'कारीगर डैशबोर्ड',
                'icon': 'bi-speedometer2',
                'desc': 'Artisan workshop overview, active gold and pending jobs',
                'desc_hi': 'वर्कशॉप सारांश, कारीगरों के पास सोना और सक्रिय कार्य',
            },
            {
                'key': 'sub_karigar_list',
                'name': 'Karigar List',
                'name_hi': 'कारीगर सूची',
                'icon': 'bi-person-workspace',
                'desc': 'Master directory of goldsmiths, artisans and workshops',
                'desc_hi': 'कारीगरों की मास्टर सूची एवं संपर्क विवरण',
            },
            {
                'key': 'sub_karigar_assignments',
                'name': 'Karigar Jobs',
                'name_hi': 'कारीगर जॉब्स',
                'icon': 'bi-clipboard2-check',
                'desc': 'Job cards with gold issue weight and design deadline',
                'desc_hi': 'जॉब कार्ड, सोना जारी वज़न और निर्माण अवधि',
            },
            {
                'key': 'sub_karigar_pending',
                'name': 'Pending & Overdue',
                'name_hi': 'लंबित एवं बकाया कार्य',
                'icon': 'bi-hourglass-split',
                'desc': 'Urgent jobs past target completion deadline',
                'desc_hi': 'समय सीमा पार कर चुके जरूरी आभूषण कार्य',
            },
            {
                'key': 'sub_karigar_settlements',
                'name': 'Karigar Payments',
                'name_hi': 'कारीगर भुगतान',
                'icon': 'bi-cash-stack',
                'desc': 'Wages calculation, scrap reconciliation and settlements',
                'desc_hi': 'मजदूरी हिसाब, छीलन कटौती और भुगतान',
            },
        ],
    },
    {
        'key': 'team',
        'name': 'Team & HR',
        'name_hi': 'टीम एवं कर्मचारी',
        'icon': 'bi-people-fill',
        'category': 'Administration',
        'category_hi': 'प्रशासन (Admin)',
        'desc': 'Counter sales staff, store employees, role-based module permissions, and showroom branches.',
        'desc_hi': 'काउंटर सेल्स स्टाफ, दुकान कर्मचारी, भूमिका-आधारित अनुमतियां और शाखाएं।',
        'sub_items': [
            {
                'key': 'sub_team_employees',
                'name': 'Employees',
                'name_hi': 'कर्मचारी सूची',
                'icon': 'bi-people-fill',
                'desc': 'Staff profiles, designated branch and permissions',
                'desc_hi': 'कर्मचारी प्रोफ़ाइल, शाखा और असाइन की गई भूमिकाएं',
            },
            {
                'key': 'sub_team_add_employee',
                'name': 'Add Employee',
                'name_hi': 'नया कर्मचारी जोड़ें',
                'icon': 'bi-person-plus-fill',
                'desc': 'Register new staff member login and showroom branch',
                'desc_hi': 'नया स्टाफ खाता बनाएं और शाखा आवंटित करें',
            },
            {
                'key': 'sub_team_roles',
                'name': 'Roles & Permissions',
                'name_hi': 'भूमिकाएं एवं अनुमतियां',
                'icon': 'bi-shield-lock-fill',
                'desc': 'Manage role access matrix (Sales, Accounts, Karigar)',
                'desc_hi': 'मॉड्यूल पहुंच अनुमतियां और अधिकार मैट्रिक्स',
            },
            {
                'key': 'sub_team_branches',
                'name': 'Branches',
                'name_hi': 'दुकान शाखाएं',
                'icon': 'bi-shop',
                'desc': 'Store branches, locations and inventory warehouses',
                'desc_hi': 'दुकान की शाखाएं, स्थान और स्टॉक गोदाम',
            },
        ],
    },
    {
        'key': 'reports',
        'name': 'Reports & Analytics',
        'name_hi': 'रिपोर्ट्स एवं विश्लेषण',
        'icon': 'bi-bar-chart-line',
        'category': 'Administration',
        'category_hi': 'प्रशासन (Admin)',
        'desc': 'Comprehensive retail GST invoices, wholesale turnover ledgers, and artisan workshop reports.',
        'desc_hi': 'विस्तृत खुदरा जीएसटी बिल, थोक टर्नओवर लेज़र और कारीगर वर्कशॉप रिपोर्ट्स।',
        'sub_items': [
            {
                'key': 'sub_reports_retail',
                'name': 'Retail Sales Report',
                'name_hi': 'खुदरा बिक्री रिपोर्ट',
                'icon': 'bi-receipt',
                'desc': 'Detailed GST retail sales ledger and daily counter receipts',
                'desc_hi': 'जीएसटी बिक्री लेज़र और दैनिक काउंटर बिक्री रिपोर्ट',
            },
            {
                'key': 'sub_reports_wholesale',
                'name': 'Wholesale Reports',
                'name_hi': 'थोक व्यापार रिपोर्ट',
                'icon': 'bi-bar-chart-line',
                'desc': 'B2B turnover, dispatch reports and party balances',
                'desc_hi': 'थोक व्यापार टर्नओवर और पार्टी बैलेंस रिपोर्ट',
            },
            {
                'key': 'sub_reports_karigar',
                'name': 'Karigar Reports',
                'name_hi': 'कारीगर रिपोर्ट्स',
                'icon': 'bi-hammer',
                'desc': 'Artisan job cards, gold issue/recovery, and karigar wage settlements',
                'desc_hi': 'कारीगर जॉब कार्ड, सोना जारी/प्राप्ति और मजदूरी भुगतान रिपोर्ट्स',
            },
        ],
    },
    {
        'key': 'settings',
        'name': 'Settings',
        'name_hi': 'सेटिंग्स',
        'icon': 'bi-gear',
        'category': 'Administration',
        'category_hi': 'प्रशासन (Admin)',
        'desc': 'Company branding, invoice settings, themes and menu bar customization.',
        'desc_hi': 'दुकान ब्रांडिंग, बिल सेटिंग्स, थीम्स और मेनू बार अनुकूलन।',
        'is_locked': True,
        'sub_items': [
            {
                'key': 'sub_settings_company',
                'name': 'Company Settings',
                'name_hi': 'दुकान सेटिंग्स',
                'icon': 'bi-building',
                'desc': 'Shop profile, GSTIN, invoice address and logo',
                'desc_hi': 'दुकान प्रोफ़ाइल, जीएसटी नंबर, पता और बिल लोगो',
            },
            {
                'key': 'sub_settings_themes',
                'name': 'Themes / Colors',
                'name_hi': 'थीम्स / रंग',
                'icon': 'bi-palette',
                'desc': 'Dark, light, and luxury gold display modes',
                'desc_hi': 'डार्क, लाइट और लग्जरी गोल्ड डिस्प्ले मोड',
            },
        ],
    },
    {
        'key': 'app_install',
        'name': 'Get the App',
        'name_hi': 'मोबाइल ऐप डाउनलोड',
        'icon': 'bi-phone',
        'category': 'App & Shortcuts',
        'category_hi': 'ऐप एवं शॉर्टकट',
        'desc': 'JewelDesk Progressive Web App (PWA) and Android APK install shortcut in sidebar.',
        'desc_hi': 'JewelDesk प्रोग्रेसिव वेब ऐप (PWA) और एंड्रॉइड एपीके इंस्टॉल शॉर्टकट।',
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

    # Collect all valid keys across modules and sub-options
    valid_keys = set()
    for item in SIDEBAR_MENU_OPTIONS:
        valid_keys.add(item['key'])
        for sub in item.get('sub_items', []):
            valid_keys.add(sub['key'])

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'unhide_all':
            settings_obj.hidden_menu_items = ''
            settings_obj.save()
            messages.success(request, 'All menu options and sub-options have been restored and unhidden!')
            return redirect('accounts:menu_settings')

        submitted_lists = set(request.POST.getlist('hidden_menus') + request.POST.getlist('hidden_items'))
        hidden_keys = set()
        for key in valid_keys:
            if request.POST.get(f'hide_{key}') in ('1', 'on', 'true') or key in submitted_lists:
                hidden_keys.add(key)

        settings_obj.hidden_menu_items = ','.join(sorted(hidden_keys))
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
        is_hidden = item['key'] in hidden_set
        name_val = item.get('name_hi') if is_hindi else item['name']
        desc_val = item.get('desc_hi') if is_hindi else item['desc']
        cat_val = item.get('category_hi') if is_hindi else item.get('category', 'General')

        processed_subs = []
        for sub in item.get('sub_items', []):
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

    valid_keys = set()
    for item in SIDEBAR_MENU_OPTIONS:
        valid_keys.add(item['key'])
        for sub in item.get('sub_items', []):
            valid_keys.add(sub['key'])

    if not menu_key or menu_key not in valid_keys:
        return JsonResponse({'error': f"Invalid menu key '{menu_key}'."}, status=400)

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

