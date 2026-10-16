"""
inventory/studio/service.py
----------------------------
Business logic, validation, image normalization, and preset definitions
for the JewelDesk AI Jewellery Photo Studio.
"""

import base64
import io
import os
from typing import Dict, Tuple

from django.core.exceptions import ValidationError
from PIL import Image

# Maximum allowed upload size (10 Megabytes)
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
MIN_DIMENSION_PX = 100
MAX_DIMENSION_PX = 8192
MAX_NORMALIZED_DIMENSION = 1536

ALLOWED_MIME_TYPES = {
    'image/jpeg': '.jpg',
    'image/pjpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
}

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}

# ---------------------------------------------------------------------------
# Studio Style & Preset Catalogs
# ---------------------------------------------------------------------------

CATALOGUE_PRESETS: Dict[str, Dict[str, str]] = {
    'black_velvet': {
        'name': 'Luxury Black Velvet Riser',
        'icon': 'bi-gem',
        'description': (
            'High-contrast luxury jewellery photography on an ultra-soft black velvet display riser. '
            'Subtle gold and silver specular reflections, soft directional key lighting, and crisp contact shadows.'
        ),
    },
    'white_marble': {
        'name': 'Polished Italian White Marble',
        'icon': 'bi-square-fill',
        'description': (
            'Pristine white Italian Carrara marble surface with delicate warm gold and grey veining. '
            'Bright, even showroom studio lighting with soft diffused highlights and natural reflections.'
        ),
    },
    'luxury_box': {
        'name': 'Handcrafted Jewellery Presentation Box',
        'icon': 'bi-archive',
        'description': (
            'Open high-end jewellery gift box with rich deep-burgundy or champagne satin and velvet cushion lining. '
            'Elegant commercial advertising composition with luxury lighting.'
        ),
    },
    'minimalist_pedestal': {
        'name': 'Warm Neutral Studio Pedestal',
        'icon': 'bi-circle',
        'description': (
            'Modern minimalist architectural pedestal in warm neutral beige travertine stone with focused spotlighting, '
            'creating clean shadows and high-end luxury e-commerce aesthetic.'
        ),
    },
    'champagne_silk': {
        'name': 'Draped Champagne Silk',
        'icon': 'bi-water',
        'description': (
            'Fluid, flowing champagne silk fabric drapery with soft organic folds. Warm luminous ambient lighting '
            'highlighting fine metalwork and sparkling gemstones.'
        ),
    },
}

MODEL_PRESETS: Dict[str, Dict[str, str]] = {
    'indian_bridal': {
        'name': 'Royal Indian Bridal Elegance',
        'icon': 'bi-person-heart',
        'description': (
            'Graceful Indian bridal editorial portrait. Warm festive studio illumination; model wears rich silk attire '
            'that complements the jewellery without obscuring it. The exact piece is worn naturally on the neckline, '
            'ears, wrist, or hand with photorealistic skin and authentic details.'
        ),
    },
    'modern_chic': {
        'name': 'Contemporary Cocktail & Evening Chic',
        'icon': 'bi-person-arms-up',
        'description': (
            'Sophisticated modern cocktail / red-carpet editorial. Elegant evening styling, clean neckline, '
            'cinematic studio rim lighting highlighting the intricate jewellery craftsmanship.'
        ),
    },
    'minimalist_portrait': {
        'name': 'Minimalist Studio Portrait',
        'icon': 'bi-person-circle',
        'description': (
            'Clean neutral studio portrait. Soft natural portrait lighting, subtle makeup, and uncluttered background, '
            'placing 100% visual emphasis directly on the authentic jewellery piece.'
        ),
    },
    'traditional_saree': {
        'name': 'Traditional Festive Saree Styling',
        'icon': 'bi-person-bounding-box',
        'description': (
            'Classic Indian traditional festive styling featuring a refined silk saree with zari borders. '
            'Warm cultural jewellery showroom lighting showcasing the jewellery worn gracefully.'
        ),
    },
}


def validate_uploaded_image(file_obj) -> Tuple[bytes, str]:
    """Validate uploaded image file size, format, dimensions, and actual content using Pillow.

    Returns:
        Tuple of (clean_bytes, detected_mime_type)

    Raises:
        ValidationError: If the file is too large, corrupted, or unsupported.
    """
    if not file_obj:
        raise ValidationError('No image file was provided.')

    # 1. Size check
    file_size = getattr(file_obj, 'size', None)
    if file_size and file_size > MAX_UPLOAD_SIZE_BYTES:
        max_mb = MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
        raise ValidationError(f'File size ({file_size / (1024*1024):.1f} MB) exceeds maximum allowed {max_mb} MB.')

    # Read bytes
    if hasattr(file_obj, 'read'):
        raw_bytes = file_obj.read()
    elif isinstance(file_obj, bytes):
        raw_bytes = file_obj
    else:
        raise ValidationError('Unsupported file payload.')

    if not raw_bytes:
        raise ValidationError('Uploaded image file is empty.')

    if len(raw_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise ValidationError(f'File size exceeds maximum allowed 10 MB.')

    # 2. Extension check
    filename = getattr(file_obj, 'name', '') or ''
    if filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext and ext not in ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"Unsupported file extension '{ext}'. Allowed extensions: "
                + ', '.join(ALLOWED_EXTENSIONS)
            )

    # 3. Content and format verification with Pillow
    try:
        stream = io.BytesIO(raw_bytes)
        img = Image.open(stream)
        img.verify()  # Verifies integrity without decoding fully
    except Exception as exc:
        raise ValidationError(
            'The uploaded file is not a valid or readable image. Please upload a genuine JPEG, PNG, or WEBP image.'
        )

    # Re-open after verify() to inspect properties and dimensions
    stream.seek(0)
    img = Image.open(stream)

    format_upper = (img.format or '').upper()
    format_map = {
        'JPEG': 'image/jpeg',
        'JPG': 'image/jpeg',
        'PNG': 'image/png',
        'WEBP': 'image/webp',
    }

    if format_upper not in format_map:
        raise ValidationError(
            f"Unsupported image format '{format_upper}'. Please upload a JPEG, PNG, or WEBP image."
        )

    detected_mime = format_map[format_upper]
    w, h = img.size

    if w < MIN_DIMENSION_PX or h < MIN_DIMENSION_PX:
        raise ValidationError(f'Image dimensions ({w}x{h}px) are too small. Minimum required: {MIN_DIMENSION_PX}x{MIN_DIMENSION_PX}px.')

    if w > MAX_DIMENSION_PX or h > MAX_DIMENSION_PX:
        raise ValidationError(f'Image dimensions ({w}x{h}px) exceed maximum allowed {MAX_DIMENSION_PX}x{MAX_DIMENSION_PX}px.')

    return raw_bytes, detected_mime


def normalize_image_for_ai(image_bytes: bytes) -> Tuple[bytes, str]:
    """Ensure image is appropriately sized for AI processing (max 1536px),

    reducing upload latency, token costs, and server memory consumption.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        # If image dimensions exceed MAX_NORMALIZED_DIMENSION, downscale with high-quality resampling
        if w > MAX_NORMALIZED_DIMENSION or h > MAX_NORMALIZED_DIMENSION:
            img.thumbnail((MAX_NORMALIZED_DIMENSION, MAX_NORMALIZED_DIMENSION), Image.Resampling.LANCZOS)

        # Ensure correct mode
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        buf = io.BytesIO()
        img.save(buf, format='WEBP', quality=90)
        return buf.getvalue(), 'image/webp'
    except Exception:
        # If Pillow normalization fails, fall back to original bytes safely
        return image_bytes, 'image/jpeg'


def image_to_data_url(image_bytes: bytes, mime_type: str = 'image/webp') -> str:
    """Encode binary image bytes into a browser-safe Data URL."""
    encoded = base64.b64encode(image_bytes).decode('ascii')
    return f"data:{mime_type};base64,{encoded}"
