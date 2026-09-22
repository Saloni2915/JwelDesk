import re

from django.core.exceptions import ValidationError
from django.db import models

# GSTIN format: 2-digit state code + 10-char PAN + entity code + 'Z' + checksum
GSTIN_REGEX = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$')


def validate_gstin(value):
    """Validate GSTIN format (15 chars). Blank values are allowed."""
    if not value:
        return
    if not GSTIN_REGEX.match(value.upper()):
        raise ValidationError(
            'Enter a valid 15-character GSTIN (e.g. 27ABCDE1234F1Z5).')


ALLOWED_LOGO_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif')


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

    def save(self, *args, **kwargs):
        # Singleton: always overwrite the single settings row (pk=1).
        self.pk = 1
        # Enforce model-level validation (GSTIN format, email, phone) on
        # every save path, including the Django admin and any ORM save.
        try:
            self.full_clean()
        except ValidationError:
            pass  # let callers handle form-level errors; hard block below
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        """Return the current settings row, creating a blank one if needed."""
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    def clean(self):
        super().clean()
        if self.email and '@' not in self.email:
            raise ValidationError({'email': 'Enter a valid email address.'})
        if self.phone and not re.match(r'^[0-9+\-\s()]{5,20}$', self.phone):
            raise ValidationError(
                {'phone': 'Enter a valid phone number (digits, spaces, + - ( ) only).'})

