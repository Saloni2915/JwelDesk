from django.db import models
from accounts.models import validate_email_address, validate_proper_email


class Customer(models.Model):
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='customers',
        null=True,
        blank=True,
        help_text="Tenant shop owning this customer record"
    )
    name = models.CharField(max_length=150)
    mobile = models.CharField(max_length=15)
    email = models.EmailField(blank=True, null=True, validators=[validate_email_address])
    address = models.TextField(blank=True)
    branch = models.ForeignKey(
        'team.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customers',
        help_text="Showroom branch where this customer was registered"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.mobile})"

    def clean(self):
        super().clean()
        if self.email:
            self.email = validate_proper_email(self.email, field_label='Customer email', required=False)

    @property
    def total_purchases_count(self):
        return self.sales.count()

    @property
    def total_purchases_amount(self):
        total = self.sales.aggregate(total=models.Sum('sale_price'))['total']
        return total or 0

    # ---- Outstanding (calculated from actual Sale + Payment rows) ----
    @property
    def total_paid_amount(self):
        """Sum of all payments received across this customer's sales."""
        from sales.models import Payment
        total = Payment.objects.filter(
            sale__customer=self).aggregate(total=models.Sum('amount'))['total']
        return total or 0

    @property
    def outstanding_amount(self):
        """Total Sales - Total Paid (never stored, always derived)."""
        due = self.total_purchases_amount - self.total_paid_amount
        return due if due > 0 else 0


