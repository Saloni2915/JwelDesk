from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=150)
    mobile = models.CharField(max_length=15)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.mobile})"

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


