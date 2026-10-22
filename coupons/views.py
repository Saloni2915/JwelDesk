"""
coupons/views.py
----------------
Tenant-facing views for Customer Coupons & Promotional Offers:
- Campaign management (CRUD, duplicate, pause, activate, archive).
- Custom HTML/CSS Designer with live sandboxed preview.
- A4 multi-sheet & individual voucher printing with vector Code 128 / QR codes.
- POS / Counter validation API for live billing.
- Comprehensive campaign performance reports with CSV export.
"""

import csv
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Sum, Q, F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from accounts.models import CompanySettings
from super_admin.models import CouponDesignTemplate
from .models import CustomerCoupon, CouponCodeItem, CouponRedemption
from .forms import CustomerCouponForm, CouponBatchGenerateForm, ClonePlatformTemplateForm
from .services import (
    validate_coupon_for_sale,
    calculate_coupon_discount,
    generate_unique_tenant_coupon_codes,
    render_coupon_template,
    get_tenant_preset_markup,
    generate_barcode_svg,
    generate_qr_svg,
    sanitize_coupon_html,
    sanitize_coupon_css,
)


# ==============================================================================
# 1. Tenant Verification Helper
# ==============================================================================

def _require_tenant(request):
    """Ensure an active tenant exists on the request."""
    if not request.tenant:
        messages.error(request, "No active showroom business account found for this user.")
        return None
    return request.tenant


# ==============================================================================
# 2. Coupon Campaign Management (List, Detail, Create, Edit, Duplicate, Status)
# ==============================================================================

@login_required
def coupon_list(request):
    """List all coupons and campaigns belonging to current tenant."""
    tenant = _require_tenant(request)
    if not tenant:
        return redirect('dashboard')

    qs = CustomerCoupon.objects.filter(tenant=tenant).select_related(
        'applicable_category', 'specific_customer'
    ).annotate(
        codes_count=Count('code_items', distinct=True)
    )

    # Search query
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(code__icontains=q) |
            Q(description__icontains=q)
        )

    # Status filter
    status = request.GET.get('status', '').strip()
    if status in dict(CustomerCoupon.STATUS_CHOICES):
        qs = qs.filter(status=status)

    # Occasion filter
    occasion = request.GET.get('occasion', '').strip()
    if occasion in dict(CustomerCoupon.OCCASION_CHOICES):
        qs = qs.filter(occasion=occasion)

    # KPI summary metrics
    total_campaigns = CustomerCoupon.objects.filter(tenant=tenant).count()
    active_campaigns = CustomerCoupon.objects.filter(tenant=tenant, status=CustomerCoupon.STATUS_ACTIVE).count()
    total_redemptions = CouponRedemption.objects.filter(tenant=tenant).count()
    total_discount_granted = CouponRedemption.objects.filter(tenant=tenant).aggregate(
        total=Sum('discount_amount')
    )['total'] or Decimal('0.00')

    qs = qs.order_by('-created_at')
    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    clone_form = ClonePlatformTemplateForm()

    context = {
        'coupons': page_obj,
        'page_obj': page_obj,
        'q': q,
        'selected_status': status,
        'selected_occasion': occasion,
        'status_choices': CustomerCoupon.STATUS_CHOICES,
        'occasion_choices': CustomerCoupon.OCCASION_CHOICES,
        'total_campaigns': total_campaigns,
        'active_campaigns': active_campaigns,
        'total_redemptions': total_redemptions,
        'total_discount_granted': total_discount_granted,
        'clone_form': clone_form,
    }
    return render(request, 'coupons/coupon_list.html', context)


@login_required
def coupon_create(request):
    """Create a new promotional campaign and coupon for this business."""
    tenant = _require_tenant(request)
    if not tenant:
        return redirect('dashboard')

    if request.method == 'POST':
        form = CustomerCouponForm(request.POST, tenant=tenant)
        if form.is_valid():
            coupon = form.save(commit=False)
            coupon.tenant = tenant
            coupon.created_by = request.user
            coupon.save()
            messages.success(request, f"Coupon offer '{coupon.name}' [{coupon.code}] created successfully!")
            return redirect('coupons:coupon_detail', pk=coupon.pk)
    else:
        # Prepopulate with business details
        company = CompanySettings.load(tenant=tenant)
        biz_name = company.name if company and company.name else tenant.name
        initial_data = {
            'design_source': 'preset',
            'preset_style': 'luxury_gold',
            'status': 'active',
            'discount_type': 'percentage',
            'discount_value': Decimal('15.00'),
            'min_purchase_amount': Decimal('5000.00'),
        }
        form = CustomerCouponForm(initial=initial_data, tenant=tenant)

    company = CompanySettings.load(tenant=tenant)
    context = {
        'form': form,
        'page_title': 'Create Customer Coupon / Promotional Offer',
        'is_create': True,
        'business_name': company.name if company and company.name else tenant.name,
    }
    return render(request, 'coupons/coupon_form.html', context)


@login_required
def coupon_edit(request, pk):
    """Edit an existing customer coupon owned by this business."""
    tenant = _require_tenant(request)
    if not tenant:
        return redirect('dashboard')

    coupon = get_object_or_404(CustomerCoupon, pk=pk, tenant=tenant)

    if request.method == 'POST':
        form = CustomerCouponForm(request.POST, instance=coupon, tenant=tenant)
        if form.is_valid():
            coupon = form.save()
            messages.success(request, f"Coupon '{coupon.name}' updated successfully!")
            return redirect('coupons:coupon_detail', pk=coupon.pk)
    else:
        form = CustomerCouponForm(instance=coupon, tenant=tenant)

    company = CompanySettings.load(tenant=tenant)
    context = {
        'form': form,
        'coupon': coupon,
        'page_title': f"Edit Offer — {coupon.name}",
        'is_create': False,
        'business_name': company.name if company and company.name else tenant.name,
    }
    return render(request, 'coupons/coupon_form.html', context)


@login_required
@require_POST
def coupon_duplicate(request, pk):
    """Duplicate an existing coupon to quickly spin up a new campaign."""
    tenant = _require_tenant(request)
    if not tenant:
        return redirect('dashboard')

    source = get_object_or_404(CustomerCoupon, pk=pk, tenant=tenant)

    # Generate an unused unique code for the copy
    base_code = source.code
    counter = 2
    new_code = f"{base_code}-COPY"
    while CustomerCoupon.objects.filter(tenant=tenant, code=new_code).exists():
        new_code = f"{base_code}-{counter}"
        counter += 1

    duplicated = CustomerCoupon.objects.create(
        tenant=tenant,
        name=f"{source.name} (Copy)",
        code=new_code,
        occasion=source.occasion,
        description=source.description,
        discount_type=source.discount_type,
        discount_value=source.discount_value,
        max_discount_amount=source.max_discount_amount,
        min_purchase_amount=source.min_purchase_amount,
        applicable_category=source.applicable_category,
        specific_customer=source.specific_customer,
        valid_from=timezone.localdate(),
        valid_until=source.valid_until,
        status=CustomerCoupon.STATUS_ACTIVE,
        is_single_use=source.is_single_use,
        max_uses_total=source.max_uses_total,
        max_uses_per_customer=source.max_uses_per_customer,
        times_redeemed=0,
        terms_and_conditions=source.terms_and_conditions,
        design_source=source.design_source,
        preset_style=source.preset_style,
        custom_html=source.custom_html,
        custom_css=source.custom_css,
        primary_color=source.primary_color,
        background_color=source.background_color,
        text_color=source.text_color,
        page_size=source.page_size,
        orientation=source.orientation,
        coupon_width_mm=source.coupon_width_mm,
        coupon_height_mm=source.coupon_height_mm,
        grid_columns=source.grid_columns,
        grid_rows=source.grid_rows,
        margin_mm=source.margin_mm,
        spacing_mm=source.spacing_mm,
        show_barcode=source.show_barcode,
        show_qr_code=source.show_qr_code,
        created_by=request.user,
    )

    messages.success(request, f"Duplicated campaign as '{duplicated.name}' [{duplicated.code}]!")
    return redirect('coupons:coupon_edit', pk=duplicated.pk)


@login_required
@require_POST
def coupon_toggle_status(request, pk):
    """Toggle coupon status (active, paused, expired, archived)."""
    tenant = _require_tenant(request)
    if not tenant:
        return redirect('dashboard')

    coupon = get_object_or_404(CustomerCoupon, pk=pk, tenant=tenant)
    new_status = request.POST.get('status', '').strip()

    if new_status in dict(CustomerCoupon.STATUS_CHOICES):
        coupon.status = new_status
        coupon.save(update_fields=['status', 'updated_at'])
        messages.success(request, f"Coupon '{coupon.name}' status updated to {coupon.get_status_display()}.")
    else:
        messages.error(request, "Invalid status choice.")

    return redirect('coupons:coupon_detail', pk=coupon.pk)


@login_required
def coupon_detail(request, pk):
    """Detailed view for an individual coupon campaign with stats and code batches."""
    tenant = _require_tenant(request)
    if not tenant:
        return redirect('dashboard')

    coupon = get_object_or_404(
        CustomerCoupon.objects.select_related('applicable_category', 'specific_customer', 'created_by'),
        pk=pk,
        tenant=tenant
    )

    # Generated unique codes
    code_items_qs = coupon.code_items.select_related('redeemed_by_customer', 'redeemed_in_sale').order_by('serial_number')
    total_codes = code_items_qs.count()
    redeemed_codes = code_items_qs.filter(is_redeemed=True).count()

    # Redemptions history
    redemptions = CouponRedemption.objects.filter(coupon=coupon).select_related(
        'customer', 'sale', 'redeemed_by_user'
    ).order_by('-redeemed_at')[:30]

    total_discount_granted = CouponRedemption.objects.filter(coupon=coupon).aggregate(
        total=Sum('discount_amount')
    )['total'] or Decimal('0.00')

    total_linked_sales = CouponRedemption.objects.filter(coupon=coupon).aggregate(
        total=Sum('final_total')
    )['total'] or Decimal('0.00')

    batch_form = CouponBatchGenerateForm(initial={'code_prefix': f"{coupon.code[:6]}-"})

    # Render a sample preview of this coupon
    company = CompanySettings.load(tenant=tenant)
    biz_name = company.name if company and company.name else tenant.name
    preview_ctx = {
        'business_name': biz_name,
        'business_logo': f'<img src="{company.logo_url}" style="max-height:30px;" />' if getattr(company, 'logo_url', None) else '',
        'coupon_code': coupon.code,
        'discount_value': coupon.formatted_discount,
        'minimum_purchase': f"₹{coupon.min_purchase_amount:,.2f}" if coupon.min_purchase_amount > 0 else "No Minimum",
        'valid_until': coupon.valid_until.strftime('%d-%b-%Y') if coupon.valid_until else "No Expiry",
        'terms_and_conditions': coupon.terms_and_conditions or "Terms apply.",
        'offer_title': coupon.name,
        'serial_number': "0001",
        'barcode_svg': generate_barcode_svg(coupon.code) if coupon.show_barcode else "",
        'qr_svg': generate_qr_svg(coupon.code) if coupon.show_qr_code else "",
    }

    if coupon.design_source == CustomerCoupon.DESIGN_CUSTOM and coupon.custom_html:
        rendered_html = render_coupon_template(coupon.custom_html, preview_ctx)
        rendered_css = coupon.custom_css
    else:
        preset = get_tenant_preset_markup(coupon.preset_style)
        rendered_html = render_coupon_template(preset['html'], preview_ctx)
        rendered_css = preset['css']

    context = {
        'coupon': coupon,
        'total_codes': total_codes,
        'redeemed_codes': redeemed_codes,
        'remaining_codes': total_codes - redeemed_codes,
        'redemptions': redemptions,
        'total_discount_granted': total_discount_granted,
        'total_linked_sales': total_linked_sales,
        'batch_form': batch_form,
        'rendered_html': rendered_html,
        'rendered_css': rendered_css,
    }
    return render(request, 'coupons/coupon_detail.html', context)


# ==============================================================================
# 3. Batch Code Generation
# ==============================================================================

@login_required
@require_POST
def coupon_generate_batch(request, pk):
    """Generate bulk unique collision-resistant codes for a coupon."""
    tenant = _require_tenant(request)
    if not tenant:
        return redirect('dashboard')

    coupon = get_object_or_404(CustomerCoupon, pk=pk, tenant=tenant)
    form = CouponBatchGenerateForm(request.POST)

    if form.is_valid():
        quantity = form.cleaned_data['quantity']
        prefix = form.cleaned_data['code_prefix']
        length = form.cleaned_data['code_length']
        serial_start = form.cleaned_data['serial_start']

        # Determine next serial number if items already exist
        last_item = coupon.code_items.order_by('-serial_number').first()
        if last_item and serial_start <= last_item.serial_number:
            serial_start = last_item.serial_number + 1

        try:
            items = generate_unique_tenant_coupon_codes(
                tenant=tenant,
                coupon=coupon,
                count=quantity,
                prefix=prefix,
                length=length,
                serial_start=serial_start,
            )
            messages.success(request, f"Successfully generated {len(items)} unique voucher codes for '{coupon.name}'!")
        except Exception as e:
            messages.error(request, f"Error generating batch codes: {e}")
    else:
        messages.error(request, "Invalid batch parameters provided.")

    return redirect('coupons:coupon_detail', pk=coupon.pk)


# ==============================================================================
# 4. Printing & Sheet Layout Engine
# ==============================================================================

@login_required
def coupon_print(request, pk):
    """
    Renders printable vouchers:
    - Mode: 'identical' (multiples of the master promo artwork) or 'unique' (using generated batch codes).
    - Grid: A4 sheet multi-coupon or single voucher per page.
    - Native browser print triggers automatically or via button.
    """
    tenant = _require_tenant(request)
    if not tenant:
        return redirect('dashboard')

    coupon = get_object_or_404(CustomerCoupon, pk=pk, tenant=tenant)
    company = CompanySettings.load(tenant=tenant)
    biz_name = company.name if company and company.name else tenant.name
    biz_logo = f'<img src="{company.logo_url}" style="max-height:30px;" />' if getattr(company, 'logo_url', None) else ''

    mode = request.GET.get('mode', 'identical')  # 'identical' or 'unique'
    copies = int(request.GET.get('copies', 6) or 6)
    copies = max(1, min(copies, 100))

    coupons_data = []

    if mode == 'unique':
        items_qs = coupon.code_items.all()
        # Filter unredeemed only if requested
        if request.GET.get('unredeemed_only') == '1':
            items_qs = items_qs.filter(is_redeemed=False)
        items = list(items_qs[:copies])
        if not items:
            messages.warning(request, "No generated unique voucher codes found to print. Please generate a batch first.")
            return redirect('coupons:coupon_detail', pk=coupon.pk)

        for item in items:
            coupons_data.append({
                'code': item.code,
                'serial': f"{item.serial_number:04d}",
                'barcode_svg': generate_barcode_svg(item.code) if coupon.show_barcode else "",
                'qr_svg': generate_qr_svg(item.code) if coupon.show_qr_code else "",
            })
    else:
        # Identical promotional artwork
        barcode_svg = generate_barcode_svg(coupon.code) if coupon.show_barcode else ""
        qr_svg = generate_qr_svg(coupon.code) if coupon.show_qr_code else ""
        for i in range(1, copies + 1):
            coupons_data.append({
                'code': coupon.code,
                'serial': f"{i:04d}",
                'barcode_svg': barcode_svg,
                'qr_svg': qr_svg,
            })

    # Render each coupon card HTML
    rendered_cards = []
    if coupon.design_source == CustomerCoupon.DESIGN_CUSTOM and coupon.custom_html:
        base_html = coupon.custom_html
        custom_css = coupon.custom_css
    else:
        preset = get_tenant_preset_markup(coupon.preset_style)
        base_html = preset['html']
        custom_css = preset['css']

    for c in coupons_data:
        ctx = {
            'business_name': biz_name,
            'business_logo': biz_logo,
            'coupon_code': c['code'],
            'discount_value': coupon.formatted_discount,
            'minimum_purchase': f"₹{coupon.min_purchase_amount:,.2f}" if coupon.min_purchase_amount > 0 else "No Minimum",
            'valid_until': coupon.valid_until.strftime('%d-%b-%Y') if coupon.valid_until else "No Expiry",
            'terms_and_conditions': coupon.terms_and_conditions or "",
            'offer_title': coupon.name,
            'serial_number': c['serial'],
            'barcode_svg': c['barcode_svg'],
            'qr_svg': c['qr_svg'],
        }
        rendered_cards.append(render_coupon_template(base_html, ctx))

    # Split into sheets based on capacity per sheet
    per_sheet = max(1, coupon.grid_columns * coupon.grid_rows)
    sheets = []
    for i in range(0, len(rendered_cards), per_sheet):
        sheets.append(rendered_cards[i:i + per_sheet])

    context = {
        'coupon': coupon,
        'sheets': sheets,
        'custom_css': custom_css,
        'total_coupons': len(rendered_cards),
        'total_sheets': len(sheets),
        'mode': mode,
    }
    return render(request, 'coupons/coupon_print.html', context)


# ==============================================================================
# 5. Live Sandboxed Designer Preview API
# ==============================================================================

@login_required
@require_POST
def coupon_preview_api(request):
    """
    Live sandboxed AJAX preview endpoint for the Coupon Designer:
    Takes HTML/CSS, sanitizes, interpolates dynamic placeholders, and returns rendered snippet.
    """
    tenant = _require_tenant(request)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'No tenant context'})

    raw_html = request.POST.get('custom_html', '')
    raw_css = request.POST.get('custom_css', '')
    preset_style = request.POST.get('preset_style', 'luxury_gold')
    design_source = request.POST.get('design_source', 'preset')

    company = CompanySettings.load(tenant=tenant)
    biz_name = company.name if company and company.name else tenant.name
    biz_logo = f'<img src="{company.logo_url}" style="max-height:30px;" />' if getattr(company, 'logo_url', None) else ''

    # Build context from POST fields or defaults
    code = request.POST.get('code', 'SAMPLE-VIP').strip().upper() or 'SAMPLE-VIP'
    disc_type = request.POST.get('discount_type', 'percentage')
    disc_val = request.POST.get('discount_value', '20')
    min_spend = request.POST.get('min_purchase_amount', '5000')

    try:
        disc_val_num = Decimal(str(disc_val))
        if disc_type == 'percentage':
            disc_str = f"{int(disc_val_num) if disc_val_num % 1 == 0 else disc_val_num}% OFF"
        else:
            disc_str = f"₹{disc_val_num:,.0f} OFF"
    except Exception:
        disc_str = "20% OFF"

    ctx = {
        'business_name': biz_name,
        'business_logo': biz_logo,
        'coupon_code': code,
        'discount_value': disc_str,
        'minimum_purchase': f"₹{Decimal(min_spend):,.2f}" if min_spend else "No Minimum",
        'valid_until': request.POST.get('valid_until') or "31-Dec-2026",
        'terms_and_conditions': request.POST.get('terms_and_conditions') or "Terms and conditions apply.",
        'offer_title': request.POST.get('name') or "Privilege Customer Voucher",
        'serial_number': "0001",
        'barcode_svg': generate_barcode_svg(code),
        'qr_svg': generate_qr_svg(code),
    }

    if design_source == 'custom' and raw_html:
        clean_html = sanitize_coupon_html(raw_html)
        clean_css = sanitize_coupon_css(raw_css)
        rendered_html = render_coupon_template(clean_html, ctx)
        rendered_css = clean_css
    else:
        preset = get_tenant_preset_markup(preset_style)
        rendered_html = render_coupon_template(preset['html'], ctx)
        rendered_css = preset['css']

    return JsonResponse({
        'success': True,
        'rendered_html': rendered_html,
        'rendered_css': rendered_css,
    })


# ==============================================================================
# 6. Billing Counter / POS Validation API
# ==============================================================================

@login_required
@require_http_methods(['GET', 'POST'])
def coupon_validate_api(request):
    """
    POS Cashier API endpoint:
    Called when a coupon code is entered or scanned at the showroom billing counter.
    Returns JSON validation result and preview discount amount.
    """
    tenant = request.tenant
    if not tenant:
        return JsonResponse({'valid': False, 'message': 'No tenant context'})

    coupon_code = request.GET.get('code') or request.POST.get('code') or ''
    customer_id = request.GET.get('customer_id') or request.POST.get('customer_id')
    item_id = request.GET.get('item_id') or request.POST.get('item_id')
    subtotal_str = request.GET.get('subtotal') or request.POST.get('subtotal') or '0.00'

    try:
        subtotal = Decimal(str(subtotal_str))
    except Exception:
        subtotal = Decimal('0.00')

    customer = None
    if customer_id:
        from customers.models import Customer
        customer = Customer.objects.filter(pk=customer_id, tenant=tenant).first()

    item = None
    if item_id:
        from inventory.models import JewelleryItem
        item = JewelleryItem.objects.select_related('category').filter(pk=item_id, tenant=tenant).first()

    result = validate_coupon_for_sale(
        tenant=tenant,
        coupon_code=coupon_code,
        customer=customer,
        item=item,
        subtotal=subtotal
    )

    return JsonResponse({
        'valid': result['valid'],
        'discount_amount': float(result['discount_amount']),
        'discount_amount_formatted': f"₹{result['discount_amount']:,.2f}",
        'message': result['message'],
        'coupon_code': result['coupon_code'],
        'coupon_name': result['coupon_name'],
    })


# ==============================================================================
# 7. Clone Platform Template into Tenant Library
# ==============================================================================

@login_required
@require_POST
def coupon_clone_platform(request):
    """Copy a platform-level Super Admin template into the tenant's own offer library."""
    tenant = _require_tenant(request)
    if not tenant:
        return redirect('dashboard')

    form = ClonePlatformTemplateForm(request.POST)
    if form.is_valid():
        platform_tmpl = form.cleaned_data['platform_template']
        new_code = form.cleaned_data['new_coupon_code'].strip().upper()

        if CustomerCoupon.objects.filter(tenant=tenant, code=new_code).exists():
            messages.error(request, f"A coupon with code '{new_code}' already exists in your showroom.")
            return redirect('coupons:coupon_list')

        cloned = CustomerCoupon.objects.create(
            tenant=tenant,
            name=platform_tmpl.name,
            code=new_code,
            occasion=CustomerCoupon.OCCASION_GENERAL,
            description=platform_tmpl.description,
            discount_type=platform_tmpl.discount_type,
            discount_value=platform_tmpl.discount_value,
            max_discount_amount=platform_tmpl.maximum_discount,
            min_purchase_amount=platform_tmpl.minimum_purchase,
            valid_from=timezone.localdate(),
            valid_until=platform_tmpl.valid_until,
            status=CustomerCoupon.STATUS_ACTIVE,
            terms_and_conditions=platform_tmpl.terms_and_conditions,
            design_source=CustomerCoupon.DESIGN_CUSTOM if platform_tmpl.template_type == 'custom' else CustomerCoupon.DESIGN_PRESET,
            preset_style=platform_tmpl.built_in_style,
            custom_html=platform_tmpl.custom_html,
            custom_css=platform_tmpl.custom_css,
            primary_color=platform_tmpl.primary_color,
            background_color=platform_tmpl.background_color,
            text_color=platform_tmpl.text_color,
            page_size=platform_tmpl.page_size,
            orientation=platform_tmpl.orientation,
            coupon_width_mm=platform_tmpl.coupon_width_mm,
            coupon_height_mm=platform_tmpl.coupon_height_mm,
            grid_columns=platform_tmpl.grid_columns,
            grid_rows=platform_tmpl.grid_rows,
            margin_mm=platform_tmpl.margin_mm,
            spacing_mm=platform_tmpl.spacing_mm,
            show_barcode=platform_tmpl.show_barcode,
            show_qr_code=platform_tmpl.show_qr_code,
            created_by=request.user,
        )
        messages.success(request, f"Platform template successfully copied as '{cloned.name}' [{cloned.code}]!")
        return redirect('coupons:coupon_edit', pk=cloned.pk)
    else:
        messages.error(request, "Failed to clone template. Please check the code entered.")
        return redirect('coupons:coupon_list')


# ==============================================================================
# 8. Campaign Reports & Analytics
# ==============================================================================

@login_required
def coupon_reports(request):
    """
    Comprehensive campaign analytics and redemption report for the showroom:
    - KPIs: Total campaigns, generated coupons, redeemed count, total discounts given, linked sales volume.
    - Performance breakdown per campaign.
    - Date and occasion filters.
    """
    tenant = _require_tenant(request)
    if not tenant:
        return redirect('dashboard')

    redemptions_qs = CouponRedemption.objects.filter(tenant=tenant).select_related(
        'coupon', 'sale', 'customer'
    )

    # Date range filters
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    if start_date:
        redemptions_qs = redemptions_qs.filter(redeemed_at__date__gte=start_date)
    if end_date:
        redemptions_qs = redemptions_qs.filter(redeemed_at__date__lte=end_date)

    # Campaign filter
    campaign_id = request.GET.get('campaign', '')
    if campaign_id:
        redemptions_qs = redemptions_qs.filter(coupon_id=campaign_id)

    # Overall KPIs
    total_campaigns = CustomerCoupon.objects.filter(tenant=tenant).count()
    active_campaigns = CustomerCoupon.objects.filter(tenant=tenant, status=CustomerCoupon.STATUS_ACTIVE).count()
    paused_campaigns = CustomerCoupon.objects.filter(tenant=tenant, status=CustomerCoupon.STATUS_PAUSED).count()
    expired_campaigns = CustomerCoupon.objects.filter(tenant=tenant, status=CustomerCoupon.STATUS_EXPIRED).count()

    total_codes_generated = CouponCodeItem.objects.filter(tenant=tenant).count()
    total_redemptions = redemptions_qs.count()
    total_discount_granted = redemptions_qs.aggregate(total=Sum('discount_amount'))['total'] or Decimal('0.00')
    total_sales_revenue = redemptions_qs.aggregate(total=Sum('final_total'))['total'] or Decimal('0.00')

    # Redemption rate calculation
    redemption_rate = (
        (total_redemptions / total_codes_generated * 100) if total_codes_generated > 0 else 0
    )

    # Per-campaign breakdown
    campaign_stats = CustomerCoupon.objects.filter(tenant=tenant).annotate(
        codes_count=Count('code_items', distinct=True),
        redemptions_count=Count('redemptions', distinct=True),
        discount_sum=Sum('redemptions__discount_amount'),
        sales_sum=Sum('redemptions__final_total'),
    ).order_by('-redemptions_count', '-created_at')

    all_campaigns = CustomerCoupon.objects.filter(tenant=tenant).order_by('name')

    context = {
        'total_campaigns': total_campaigns,
        'active_campaigns': active_campaigns,
        'paused_campaigns': paused_campaigns,
        'expired_campaigns': expired_campaigns,
        'total_codes_generated': total_codes_generated,
        'total_redemptions': total_redemptions,
        'total_discount_granted': total_discount_granted,
        'total_sales_revenue': total_sales_revenue,
        'redemption_rate': round(redemption_rate, 1),
        'campaign_stats': campaign_stats,
        'all_campaigns': all_campaigns,
        'selected_campaign': campaign_id,
        'start_date': start_date,
        'end_date': end_date,
    }
    return render(request, 'coupons/coupon_reports.html', context)


@login_required
def coupon_reports_export(request):
    """Export coupon redemption records to CSV format."""
    tenant = _require_tenant(request)
    if not tenant:
        return redirect('dashboard')

    redemptions_qs = CouponRedemption.objects.filter(tenant=tenant).select_related(
        'coupon', 'sale', 'customer', 'redeemed_by_user'
    ).order_by('-redeemed_at')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="coupon_redemptions_{timezone.localdate()}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Redemption ID',
        'Date & Time',
        'Campaign Name',
        'Coupon Code',
        'Customer Name',
        'Sale ID',
        'Bill Subtotal (INR)',
        'Discount Amount (INR)',
        'Final Payable (INR)',
        'Processed By Staff',
    ])

    for r in redemptions_qs:
        writer.writerow([
            r.id,
            r.redeemed_at.strftime('%Y-%m-%d %H:%M'),
            r.coupon.name if r.coupon else 'N/A',
            r.coupon_code_used,
            r.customer.name if r.customer else 'Walk-in Customer',
            f"#{r.sale_id}",
            f"{r.order_subtotal:.2f}",
            f"{r.discount_amount:.2f}",
            f"{r.final_total:.2f}",
            r.redeemed_by_user.get_full_name() or r.redeemed_by_user.username if r.redeemed_by_user else 'Counter Staff',
        ])

    return response
