from django.contrib import admin
from .models import Sale, Enquiry


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'jewellery_item', 'sale_price', 'payment_method', 'sale_date']
    list_filter = ['payment_method', 'sale_date']
    search_fields = ['customer__name', 'jewellery_item__name', 'jewellery_item__item_code']
    readonly_fields = ['sale_date']


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'interested_item', 'category', 'budget', 'status', 'next_followup_date', 'created_at']
    list_filter = ['status', 'category', 'next_followup_date', 'created_at']
    search_fields = ['customer__name', 'customer__mobile', 'interested_item']
    readonly_fields = ['created_at']

