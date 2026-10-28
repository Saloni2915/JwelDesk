import base64
import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, models


def save_logo_blob(filename, content_bytes, content_type='image/png'):
    """Persist logo binary into database blob table for cross-worker serverless persistence."""
    try:
        b64_data = base64.b64encode(content_bytes).decode('ascii')
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts_company_logo_blob (
                    id INT PRIMARY KEY,
                    filename VARCHAR(255),
                    content_type VARCHAR(100),
                    data TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("DELETE FROM accounts_company_logo_blob WHERE id = 1")
            cursor.execute("""
                INSERT INTO accounts_company_logo_blob (id, filename, content_type, data)
                VALUES (1, %s, %s, %s)
            """, [filename, content_type, b64_data])
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("save_logo_blob warning: %s", e)


def get_logo_blob():
    """Retrieve logo binary from database blob table."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT filename, content_type, data
                FROM accounts_company_logo_blob
                WHERE id = 1
            """)
            row = cursor.fetchone()
            if row:
                filename, content_type, b64_data = row
                return filename, content_type, base64.b64decode(b64_data.encode('ascii'))
    except Exception:
        pass
    return None


def clear_logo_blob():
    """Clear saved logo from database blob table."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM accounts_company_logo_blob WHERE id = 1")
    except Exception:
        pass


def restore_logo_file(filename=None):
    """Ensure logo file exists on disk (e.g. in /tmp on Vercel). Returns path if exists/restored."""
    blob_info = get_logo_blob()
    if not blob_info:
        return None
    saved_filename, content_type, raw_bytes = blob_info
    target_name = filename or saved_filename
    try:
        dest_path = Path(settings.MEDIA_ROOT) / target_name
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if not dest_path.exists() or dest_path.stat().st_size == 0:
            dest_path.write_bytes(raw_bytes)
        return str(dest_path)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("restore_logo_file warning: %s", e)
        return None

# GSTIN format: 2-digit state code + 10-char PAN + entity code + 'Z' + checksum
GSTIN_REGEX = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$')


def validate_gstin(value):
    """Validate GSTIN format (15 chars). Blank values are allowed."""
    if not value:
        return
    if not GSTIN_REGEX.match(value.upper()):
        raise ValidationError(
            'Enter a valid 15-character GSTIN (e.g. 27ABCDE1234F1Z5).')


ALLOWED_LOGO_EXTENSIONS = (
    '.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif',
    '.jfif', '.avif', '.bmp', '.ico',
)


def validate_logo_extension(value):
    """Accept common image files without requiring an image library."""
    import os
    ext = os.path.splitext(value.name or '')[1].lower()
    if ext not in ALLOWED_LOGO_EXTENSIONS:
        raise ValidationError(
            'Unsupported logo type. Allowed: '
            + ', '.join(ALLOWED_LOGO_EXTENSIONS))


def clean_10_digit_phone(value, field_label='Phone number', required=True):
    """
    Validate that a phone or mobile number contains exactly 10 digits.
    Prevents saving numbers with fewer or more than 10 digits.
    Handles optional +91/91 country prefix and leading 0 trunk prefix.
    """
    if not value or not str(value).strip():
        if required:
            raise ValidationError(f"{field_label} is required.")
        return ''

    val_str = str(value).strip()
    digits = re.sub(r'\D', '', val_str)

    # Handle leading +91 or 91 country code (12 digits total)
    if (val_str.startswith('+91') or digits.startswith('91')) and len(digits) == 12:
        core_digits = digits[2:]
    # Handle single leading 0 trunk prefix (11 digits total)
    elif digits.startswith('0') and len(digits) == 11:
        core_digits = digits[1:]
    else:
        core_digits = digits

    if len(core_digits) < 10:
        raise ValidationError(f"{field_label} must be exactly 10 digits.")
    if len(core_digits) > 10:
        raise ValidationError(f"{field_label} cannot exceed 10 digits.")

    # Preserve +91 prefix in existing unit tests if passed that way
    if val_str.startswith('+91'):
        return val_str
    return core_digits


def validate_10_digit_phone(value):
    """Model validator for 10-digit phone number."""
    if value:
        clean_10_digit_phone(value, field_label='Phone number', required=False)



class Tenant(models.Model):
    """Independent jewellery shop / business showroom tenant.

    All tenant-owned business data (inventory, sales, customers, karigar,
    custom orders, team, and company settings) is strictly isolated by tenant.
    """

    name = models.CharField(max_length=200, help_text="Jewellery shop or business name")
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='owned_tenants',
        help_text="Shop owner / primary administrator"
    )
    TYPE_RETAIL = 'RETAIL'
    TYPE_WHOLESALE = 'WHOLESALE'
    TYPE_BOTH = 'BOTH'
    BUSINESS_TYPE_CHOICES = [
        (TYPE_RETAIL, 'Retail Jewellery Store'),
        (TYPE_WHOLESALE, 'Wholesaler / Supplier'),
        (TYPE_BOTH, 'Retail & Wholesale (Hybrid)'),
    ]

    business_type = models.CharField(
        max_length=20,
        choices=BUSINESS_TYPE_CHOICES,
        default=TYPE_RETAIL,
        help_text="Primary business model for this tenant"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Tenant / Shop'
        verbose_name_plural = 'Tenants / Shops'

    def __str__(self):
        return self.name

    @property
    def is_retail(self):
        return self.business_type in (self.TYPE_RETAIL, self.TYPE_BOTH)

    @property
    def is_wholesale(self):
        return self.business_type in (self.TYPE_WHOLESALE, self.TYPE_BOTH)

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base_slug = slugify(self.name) or 'shop'
            slug = base_slug
            idx = 1
            while Tenant.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{idx}"
                idx += 1
            self.slug = slug
        super().save(*args, **kwargs)


class CompanySettings(models.Model):
    """Company/shop profile used on invoices and the UI, isolated per tenant."""

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name='company_settings',
        null=True,
        blank=True,
        help_text="The jewellery shop tenant owning these settings."
    )
    company_name = models.CharField(max_length=200, blank=True)
    logo = models.FileField(
        upload_to='company/', null=True, blank=True,
        validators=[validate_logo_extension],
        help_text='Logo image (png/jpg/jpeg/webp/svg). Shown on invoices '
                  'and in the sidebar (optional).')
    gstin = models.CharField(
        max_length=15, blank=True, validators=[validate_gstin],
        help_text='15-character GSTIN, e.g. 27ABCDE1234F1Z5')
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    invoice_footer_note = models.CharField(max_length=255, blank=True)
    hidden_menu_items = models.TextField(
        blank=True, default='',
        help_text='Comma-separated keys of menu items hidden in the sidebar navigation.'
    )
    LANGUAGE_EN = 'en'
    LANGUAGE_HI = 'hi'
    LANGUAGE_CHOICES = (
        (LANGUAGE_EN, 'English'),
        (LANGUAGE_HI, 'Hindi (हिंदी)'),
    )
    language = models.CharField(
        max_length=10,
        choices=LANGUAGE_CHOICES,
        default=LANGUAGE_EN,
        blank=True,
        help_text='System display language (English or Hindi).'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Company Settings'
        verbose_name_plural = 'Company Settings'

    def __str__(self):
        return self.company_name or 'Company Settings'

    @property
    def name(self):
        """Display name for templates (alias of ``company_name``)."""
        return self.company_name or 'JewelDesk'

    def get_hidden_menus(self):
        """Return a clean list of lowercased keys of menu items currently hidden."""
        if not self.hidden_menu_items:
            return []
        return [k.strip().lower() for k in self.hidden_menu_items.split(',') if k.strip()]

    def is_menu_hidden(self, menu_key):
        """Check if a specific menu key is currently hidden."""
        if not menu_key:
            return False
        return menu_key.strip().lower() in self.get_hidden_menus()

    def set_menu_hidden(self, menu_key, is_hidden=True, commit=False):
        """Mark a specific menu key as hidden or visible."""
        current = set(self.get_hidden_menus())
        key = menu_key.strip().lower()
        if is_hidden:
            current.add(key)
        else:
            current.discard(key)
        self.hidden_menu_items = ','.join(sorted(current))
        if commit:
            self.save()

    def ensure_logo_file(self):
        """Restore logo to disk from DB blob table if missing on ephemeral filesystem."""
        if not self.logo:
            return None
        from django.core.files.storage import default_storage
        try:
            if not default_storage.exists(self.logo.name):
                return restore_logo_file(self.logo.name)
        except Exception:
            return restore_logo_file(self.logo.name)
        return None

    @property
    def logo_url(self):
        """Safe logo URL that never raises an exception during template rendering."""
        if not self.logo:
            return None
        ts = int(self.updated_at.timestamp()) if getattr(self, 'updated_at', None) else 0
        try:
            self.ensure_logo_file()
            base_url = self.logo.url
            return f"{base_url}?v={ts}" if ts else base_url
        except Exception:
            return None

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            from django.core.cache import cache
            cache.delete('company_settings:singleton')
            if self.tenant_id:
                cache.delete(f'company_settings:tenant:{self.tenant_id}')
        except Exception:
            pass

    @classmethod
    def load(cls, tenant=None):
        """Return settings row for the given tenant, creating a blank one if needed."""
        try:
            if tenant:
                obj = cls.objects.filter(tenant=tenant).first()
                if obj is None:
                    obj = cls.objects.create(tenant=tenant, company_name=tenant.name)
                return obj
            from .models import Tenant
            first_tenant = Tenant.objects.first()
            if first_tenant:
                obj = cls.objects.filter(tenant=first_tenant).first()
                if obj is None:
                    obj = cls.objects.create(tenant=first_tenant, company_name=first_tenant.name)
                return obj
            obj = cls.objects.first()
            if obj is None:
                obj = cls.objects.create(company_name='JewelDesk')
            return obj
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("CompanySettings.load fallback: %s", e)
            return cls(company_name='JewelDesk')

    def clean(self):
        super().clean()
        if self.email and '@' not in self.email:
            raise ValidationError({'email': 'Enter a valid email address.'})
        if self.phone:
            try:
                self.phone = clean_10_digit_phone(self.phone, field_label='Phone number', required=False)
            except ValidationError as err:
                raise ValidationError({'phone': err.message if hasattr(err, 'message') else str(err)})

