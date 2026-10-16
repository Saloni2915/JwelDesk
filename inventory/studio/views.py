"""
inventory/studio/views.py
--------------------------
HTTP request handlers for the AI Jewellery Photo Studio.
Enforces multi-tenancy, input validation, secure downloads,
and integration with the JewelleryItemImage schema.
"""

import base64
import logging
import os
import time
from typing import Optional

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import DatabaseError, OperationalError, ProgrammingError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from inventory.models import JewelleryItem, JewelleryItemImage
from .providers import get_photo_studio_provider
from .service import (
    CATALOGUE_PRESETS,
    MODEL_PRESETS,
    image_to_data_url,
    normalize_image_for_ai,
    validate_uploaded_image,
)

logger = logging.getLogger('inventory.studio')


@login_required
def photo_studio_view(request):
    """Main atelier view for the AI Jewellery Photo Studio."""
    try:
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            messages.error(request, 'No active showroom was found for your account.')
            return redirect('dashboard')

        # Fetch showroom items with resilient fallback if images table is not yet migrated
        has_image_table = True
        try:
            items = list(
                JewelleryItem.objects.filter(tenant=tenant)
                .select_related('category')
                .prefetch_related('images')
                .order_by('-created_at')[:150]
            )
        except (OperationalError, ProgrammingError, DatabaseError) as db_err:
            has_image_table = False
            logger.warning(
                "Photo Studio: unable to prefetch images (schema may be pending migration): %s",
                db_err,
                exc_info=True,
            )
            try:
                items = list(
                    JewelleryItem.objects.filter(tenant=tenant)
                    .select_related('category')
                    .order_by('-created_at')[:150]
                )
            except Exception as fallback_err:
                logger.error("Photo Studio: failed loading inventory items: %s", fallback_err, exc_info=True)
                items = []

        selected_item = None
        item_id_param = request.GET.get('item_id')
        if item_id_param:
            try:
                selected_item = JewelleryItem.objects.filter(tenant=tenant, pk=item_id_param).first()
            except (ValueError, TypeError, OperationalError, ProgrammingError):
                selected_item = None

        has_api_key = bool(
            os.environ.get('GEMINI_API_KEY')
            or getattr(settings, 'AI_STUDIO_MOCK', False)
            or os.environ.get('AI_STUDIO_MOCK')
        )

        context = {
            'items': items,
            'selected_item': selected_item,
            'catalogue_presets': CATALOGUE_PRESETS,
            'model_presets': MODEL_PRESETS,
            'has_api_key': has_api_key,
            'has_image_table': has_image_table,
        }
        return render(request, 'inventory/photo_studio.html', context)
    except Exception as exc:
        logger.error("Unhandled error in photo_studio_view: %s", exc, exc_info=True)
        messages.error(request, "The Photo Studio encountered an unexpected error. Please try again or contact support.")
        return redirect('dashboard')


@login_required
@require_POST
def photo_studio_generate(request):
    """Handle generation request for either Catalogue Studio or Model Photo."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'Unauthorized: No active showroom tenant found.'}, status=403)

    raw_bytes = None
    mime_type = 'image/jpeg'

    # 1. Resolve source image with strict tenant ownership validation
    existing_image_id = request.POST.get('existing_image_id')
    item_id = request.POST.get('item_id')

    if existing_image_id:
        try:
            img_obj = get_object_or_404(JewelleryItemImage, pk=existing_image_id, tenant=tenant)
            with img_obj.image.open('rb') as f:
                raw_bytes = f.read()
            mime_type = 'image/webp' if img_obj.image.name.lower().endswith('.webp') else 'image/jpeg'
        except Http404:
            return JsonResponse({'success': False, 'error': 'The requested jewellery image does not belong to your showroom.'}, status=404)
        except Exception as exc:
            return JsonResponse({'success': False, 'error': f'Failed reading source image: {exc}'}, status=400)

    elif 'image_file' in request.FILES:
        try:
            raw_bytes, mime_type = validate_uploaded_image(request.FILES['image_file'])
        except ValidationError as val_err:
            return JsonResponse({'success': False, 'error': str(val_err.message if hasattr(val_err, 'message') else val_err)}, status=400)

    elif item_id:
        try:
            item_obj = get_object_or_404(JewelleryItem, pk=item_id, tenant=tenant)
            primary_img = item_obj.primary_image
            if not primary_img:
                return JsonResponse(
                    {'success': False, 'error': 'Selected jewellery piece has no uploaded photo. Please upload a photo to start.'},
                    status=400,
                )
            with primary_img.image.open('rb') as f:
                raw_bytes = f.read()
            mime_type = 'image/webp' if primary_img.image.name.lower().endswith('.webp') else 'image/jpeg'
        except Http404:
            return JsonResponse({'success': False, 'error': 'Selected jewellery piece does not belong to your showroom.'}, status=404)
        except Exception as exc:
            return JsonResponse({'success': False, 'error': f'Failed reading item photo: {exc}'}, status=400)

    if not raw_bytes:
        return JsonResponse({'success': False, 'error': 'Please upload a photo or select an existing piece from your inventory.'}, status=400)

    # 2. Parse generation parameters
    gen_type = (request.POST.get('generation_type') or 'catalogue').strip().lower()
    preset_key = (request.POST.get('preset') or '').strip()
    custom_prompt = (request.POST.get('custom_prompt') or '').strip()[:500]

    if gen_type == 'model':
        preset_dict = MODEL_PRESETS
        default_key = 'indian_bridal'
    else:
        gen_type = 'catalogue'
        preset_dict = CATALOGUE_PRESETS
        default_key = 'black_velvet'

    if preset_key not in preset_dict:
        preset_key = default_key

    preset_info = preset_dict[preset_key]
    preset_name = preset_info['name']
    preset_desc = preset_info['description']

    # 3. Downscale / normalize for AI processing
    normalized_bytes, norm_mime = normalize_image_for_ai(raw_bytes)

    # 4. Invoke provider
    provider = get_photo_studio_provider()
    if gen_type == 'model':
        result = provider.generate_model_photo(
            image_bytes=normalized_bytes,
            mime_type=norm_mime,
            preset_name=preset_name,
            preset_description=preset_desc,
            custom_prompt=custom_prompt,
        )
    else:
        result = provider.generate_catalogue_photo(
            image_bytes=normalized_bytes,
            mime_type=norm_mime,
            preset_name=preset_name,
            preset_description=preset_desc,
            custom_prompt=custom_prompt,
        )

    if not result.success:
        status_code = 503 if 'key' in (result.error_message or '').lower() else 400
        return JsonResponse({'success': False, 'error': result.error_message or 'AI generation failed.'}, status=status_code)

    # 5. Return browser-ready Data URL
    data_url = image_to_data_url(result.image_bytes, result.mime_type)
    mode_label = 'Model Wearing' if gen_type == 'model' else 'Studio Catalogue'
    caption = f"AI {mode_label} ({preset_name})"

    return JsonResponse({
        'success': True,
        'preview_data_url': data_url,
        'caption': caption,
        'generation_type': gen_type,
        'preset': preset_key,
        'cost_estimate_usd': result.cost_estimate_usd,
        'duration_seconds': result.metadata.get('duration_seconds', 0),
    })


@login_required
@require_POST
def photo_studio_save(request):
    """Save an approved generated photo to a JewelleryItem."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'Unauthorized: No active showroom tenant found.'}, status=403)

    item_id = request.POST.get('item_id')
    image_data = request.POST.get('image_data')
    caption = (request.POST.get('caption') or 'AI Photo Studio').strip()[:200]
    is_primary = request.POST.get('is_primary', '').lower() in ('true', '1', 'yes')

    if not item_id:
        return JsonResponse({'success': False, 'error': 'Please select a jewellery piece to save this photo to.'}, status=400)

    if not image_data:
        return JsonResponse({'success': False, 'error': 'No generated image data received.'}, status=400)

    # Validate tenant ownership of target jewellery piece
    try:
        item = get_object_or_404(JewelleryItem, pk=item_id, tenant=tenant)
    except Http404:
        return JsonResponse({'success': False, 'error': 'The selected jewellery item does not belong to your showroom.'}, status=404)

    # Decode base64 image data
    try:
        if ',' in image_data:
            _, encoded = image_data.split(',', 1)
        else:
            encoded = image_data
        raw_bytes = base64.b64decode(encoded)
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid base64 image data.'}, status=400)

    # Validate actual image bytes with Pillow
    try:
        clean_bytes, detected_mime = validate_uploaded_image(raw_bytes)
    except ValidationError as val_err:
        return JsonResponse({'success': False, 'error': str(val_err.message if hasattr(val_err, 'message') else val_err)}, status=400)

    ext = '.webp' if detected_mime == 'image/webp' else '.png' if detected_mime == 'image/png' else '.jpg'
    filename = f"ai_studio_{item.id}_{int(time.time())}{ext}"

    # Create JewelleryItemImage record with SOURCE_AI_STUDIO
    try:
        item_image = JewelleryItemImage(
            tenant=tenant,
            item=item,
            is_primary=is_primary,
            caption=caption,
            source_type=JewelleryItemImage.SOURCE_AI_STUDIO,
            created_by=request.user,
        )
        item_image.image.save(filename, ContentFile(clean_bytes), save=True)
    except (OperationalError, ProgrammingError, DatabaseError) as db_err:
        logger.error("Photo Studio save database error: %s", db_err, exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Database storage table is initializing. Please try again shortly or configure VERCEL_AUTO_MIGRATE=1.',
        }, status=503)
    except Exception as exc:
        logger.error("Photo Studio save error: %s", exc, exc_info=True)
        return JsonResponse({'success': False, 'error': f'Failed saving photo: {exc}'}, status=500)

    return JsonResponse({
        'success': True,
        'image_id': item_image.id,
        'item_id': item.id,
        'item_url': reverse('inventory_detail', args=[item.id]),
        'message': f"Studio photograph attached to {item.tag_number or item.item_code} successfully!",
    })


@login_required
def photo_studio_download(request, image_id):
    """Secure, tenant-authenticated high-res image download endpoint."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        raise Http404('Showroom tenant not found.')

    try:
        image_obj = get_object_or_404(JewelleryItemImage, pk=image_id, tenant=tenant)
    except (OperationalError, ProgrammingError, DatabaseError) as db_err:
        logger.error("Photo Studio download database error: %s", db_err, exc_info=True)
        raise Http404('Image storage table is not available.')

    try:
        file_handle = image_obj.image.open('rb')
        item_code = getattr(image_obj.item, 'tag_number', '') or getattr(image_obj.item, 'item_code', '') or 'jewellery'
        ext = image_obj.image.name.split('.')[-1].lower() if '.' in image_obj.image.name else 'webp'
        download_filename = f"{item_code}_studio.{ext}"
        return FileResponse(file_handle, as_attachment=True, filename=download_filename)
    except Exception as exc:
        logger.error("Photo Studio download file access error: %s", exc, exc_info=True)
        raise Http404(f"Unable to access image file: {exc}")
