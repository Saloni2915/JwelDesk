from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from customers.models import Customer
from inventory.models import Category


def default_expected_delivery_date():
    """Default the expected delivery to 30 days from today."""
    return timezone.localdate() + timezone.timedelta(days=30)


class CustomOrder(models.Model):
    """An order to make a custom jewellery piece for an existing customer."""

    METAL_CHOICES = [
        ('Gold', 'Gold'),
        ('Silver', 'Silver'),
        ('Diamond', 'Diamond'),
        ('Platinum', 'Platinum'),
    ]

    STATUS_ENQUIRY = 'Enquiry'
    STATUS_ESTIMATE = 'Estimate'
    STATUS_CONFIRMED = 'Confirmed'
    STATUS_IN_MAKING = 'In Making'
    STATUS_READY = 'Ready'
    STATUS_DELIVERED = 'Delivered'
    STATUS_CANCELLED = 'Cancelled'

    STATUS_CHOICES = [
        (STATUS_ENQUIRY, 'Enquiry'),
        (STATUS_ESTIMATE, 'Estimate'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_IN_MAKING, 'In Making'),
        (STATUS_READY, 'Ready'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    # Forward-only shop workflow plus cancellation; terminal states never reopen.
    ALLOWED_STATUS_TRANSITIONS = {
        STATUS_ENQUIRY: {STATUS_ESTIMATE, STATUS_CANCELLED},
        STATUS_ESTIMATE: {STATUS_CONFIRMED, STATUS_ENQUIRY, STATUS_CANCELLED},
        STATUS_CONFIRMED: {STATUS_IN_MAKING, STATUS_CANCELLED},
        STATUS_IN_MAKING: {STATUS_READY, STATUS_CANCELLED},
        STATUS_READY: {STATUS_DELIVERED, STATUS_CANCELLED},
        STATUS_DELIVERED: set(),
        STATUS_CANCELLED: set(),
    }

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='custom_orders')
    order_number = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        editable=False,
        help_text="Auto-generated reference, e.g. CO-2026-0001.",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='custom_orders',
        verbose_name='Jewellery type',
    )
    design_description = models.TextField(help_text="What the customer wants made.")
    reference_image = models.FileField(
        upload_to='custom_orders/references/%Y/%m/',
        blank=True,
        null=True,
        help_text="Reference photo/design brought by the customer (JPG, PNG, GIF or PDF).",
    )

    metal_type = models.CharField(max_length=20, choices=METAL_CHOICES)
    purity = models.CharField(max_length=50, help_text="e.g. 22K, 18K, 925 Silver")
    approx_gross_weight = models.DecimalField(
        max_digits=10, decimal_places=3, help_text="Approximate weight in grams")
    approx_net_weight = models.DecimalField(
        max_digits=10, decimal_places=3, help_text="Approximate weight in grams (excluding stones)")
    making_charge = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text="Estimated making charge in ₹")
    estimated_price = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="Estimated total price in ₹")
    customer_budget = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Customer budget in ₹ (optional)")
    advance_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        help_text="Advance received in ₹")
    expected_delivery_date = models.DateField(default=default_expected_delivery_date)
    actual_delivery_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ENQUIRY)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order_number or 'Unsaved'} - {self.customer} ({self.status})"

    @property
    def remaining_amount(self):
        """Amount still due: estimated price minus advance (never negative)."""
        estimated = self.estimated_price or Decimal('0.00')
        advance = self.advance_amount or Decimal('0.00')
        remaining = estimated - advance
        return remaining if remaining > 0 else Decimal('0.00')

    def get_allowed_statuses(self):
        """Statuses this order may move to from its current status."""
        return sorted(self.ALLOWED_STATUS_TRANSITIONS.get(self.status, set()))

    def can_transition_to(self, new_status):
        return new_status in self.ALLOWED_STATUS_TRANSITIONS.get(self.status, set())

    def set_status(self, new_status):
        """
        Move the order to a new status, enforcing the shop workflow.
        Stamps the actual delivery date when an order is delivered.
        """
        if new_status == self.status:
            return False
        if new_status not in dict(self.STATUS_CHOICES).keys():
            raise ValidationError({'status': f"Unknown status '{new_status}'."})
        if not self.can_transition_to(new_status):
            raise ValidationError({
                'status': f"Cannot change status from '{self.status}' to '{new_status}'."
            })
        self.status = new_status
        if new_status == self.STATUS_DELIVERED and not self.actual_delivery_date:
            self.actual_delivery_date = timezone.localdate()
        self.full_clean()
        self.save(update_fields=['status', 'actual_delivery_date', 'updated_at'])
        return True

    def update_status(self, new_status):
        """Public helper to move the order to another allowed status."""
        return self.set_status(new_status)

    def clean(self):
        super().clean()
        errors = {}

        if self.approx_gross_weight is not None and self.approx_gross_weight < 0:
            errors['approx_gross_weight'] = 'Approximate gross weight cannot be negative.'
        if self.approx_net_weight is not None and self.approx_net_weight < 0:
            errors['approx_net_weight'] = 'Approximate net weight cannot be negative.'
        if (
            self.approx_gross_weight is not None
            and self.approx_net_weight is not None
            and self.approx_gross_weight >= 0
            and self.approx_net_weight >= 0
            and self.approx_net_weight > self.approx_gross_weight
        ):
            errors['approx_net_weight'] = (
                'Approximate net weight cannot be greater than gross weight.')
        if self.making_charge is not None and self.making_charge < 0:
            errors['making_charge'] = 'Making charge cannot be negative.'
        if self.estimated_price is not None and self.estimated_price <= 0:
            errors['estimated_price'] = 'Estimated total price must be greater than 0.'
        if self.customer_budget is not None and self.customer_budget < 0:
            errors['customer_budget'] = 'Customer budget cannot be negative.'
        if self.advance_amount is not None and self.advance_amount < 0:
            errors['advance_amount'] = 'Advance amount cannot be negative.'
        if (
            self.advance_amount is not None
            and self.estimated_price is not None
            and self.estimated_price > 0
            and self.advance_amount > self.estimated_price
        ):
            errors['advance_amount'] = (
                'Advance amount cannot be greater than the estimated total price.')

        order_date = None
        if self.created_at is not None:
            order_date = self.created_at.date() if hasattr(self.created_at, 'date') else self.created_at
        else:
            # Unsaved instance: validate against today as the order date.
            order_date = timezone.localdate()
        if self.expected_delivery_date and order_date and self.expected_delivery_date < order_date:
            errors['expected_delivery_date'] = (
                'Expected delivery date cannot be earlier than the order date. '
                'Explain the reason in Notes and pick today or a future date.')
        if self.actual_delivery_date and order_date and self.actual_delivery_date < order_date:
            errors['actual_delivery_date'] = (
                'Actual delivery date cannot be earlier than the order date.')

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """Validate, then auto-generate the unique order number on first save."""
        retrying = kwargs.pop('_retry_order_number', False)
        self.full_clean()
        if self.order_number:
            super().save(*args, **kwargs)
            return
        year = timezone.localdate().year
        # First insert the row to claim the pk, then stamp a readable reference.
        super().save(*args, **kwargs)
        candidate = f"CO-{year}-{self.pk:04d}"
        updated = CustomOrder.objects.filter(pk=self.pk, order_number='').update(
            order_number=candidate)
        if updated:
            self.order_number = candidate
            return
        try:
            with transaction.atomic():
                locked = CustomOrder.objects.select_for_update().get(pk=self.pk)
                if not locked.order_number:
                    locked.order_number = candidate
                    locked.save(update_fields=['order_number', 'updated_at'])
                self.order_number = locked.order_number
        except IntegrityError:
            if retrying:
                raise
            self.refresh_from_db()
            return self.save(*args, _retry_order_number=True, **kwargs)