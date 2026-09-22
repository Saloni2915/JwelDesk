from django.contrib import admin
from .models import CustomOrder


@admin.register(CustomOrder)
class CustomOrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_number', 'customer', 'category', 'metal_type',
        'estimated_price', 'advance_amount', 'status',
        'expected_delivery_date', 'created_at',
    ]
    list_filter = ['status', 'metal_type', 'category', 'created_at', 'expected_delivery_date']
    search_fields = ['order_number', 'customer__name', 'customer__mobile', 'design_description']
    readonly_fields = ['order_number', 'created_at', 'updated_at']
