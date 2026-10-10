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


class CompanySettings(models.Model):
    """Single-record company/shop profile used on invoices and the UI.

    There is intentionally only one row (pk=1); see save().
    """

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
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Company Settings'
        verbose_name_plural = 'Company Settings'

    def __str__(self):
        return self.company_name or 'Company Settings'

    @property
    def name(self):
        """Display name for templates (alias of ``company_name``).

        The header and sidebar render ``{{ company.name }}``. Falling back to
        the product name keeps the branding readable before the shop has been
        configured in Company Settings.
        """
        return self.company_name or 'JewelDesk'

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
        ts = int(self.updated_at.timestamp()) if getattr(self, 'updated_at', None) else 0
        if not self.logo:
            # Check if there is a logo blob stored in DB
            blob = get_logo_blob()
            if blob:
                filename, _, _ = blob
                restore_logo_file(filename)
                return f"{settings.MEDIA_URL.rstrip('/')}/{filename}?v={ts}"
            return None
        try:
            self.ensure_logo_file()
            base_url = self.logo.url
            return f"{base_url}?v={ts}" if ts else base_url
        except Exception:
            return None

    def save(self, *args, **kwargs):
        # Singleton: attach to existing record if one exists, otherwise initialize pk=1
        if not self.pk:
            try:
                existing = CompanySettings.objects.first()
                if existing:
                    self.pk = existing.pk
                    self._state.adding = False
                else:
                    self.pk = 1
            except Exception:
                self.pk = 1
        super().save(*args, **kwargs)
        try:
            from django.core.cache import cache
            cache.delete('company_settings:singleton')
        except Exception:
            pass

    @classmethod
    def load(cls):
        """Return the current settings row, creating a blank one if needed.
        
        Guaranteed to never raise an unhandled database exception that breaks page rendering.
        """
        try:
            obj = cls.objects.first()
            if obj is None:
                obj = cls.objects.create(pk=1, company_name='JewelDesk')
            return obj
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("CompanySettings.load fallback: %s", e)
            return cls(company_name='JewelDesk')

    def clean(self):
        super().clean()
        if self.email and '@' not in self.email:
            raise ValidationError({'email': 'Enter a valid email address.'})
        if self.phone and not re.match(r'^[0-9+\-\s()]{5,20}$', self.phone):
            raise ValidationError(
                {'phone': 'Enter a valid phone number (digits, spaces, + - ( ) only).'})

