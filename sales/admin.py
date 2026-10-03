from django.contrib import admin
from .models import Sale, Payment, Enquiry, OldGoldTransaction


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'jewellery_item', 'sale_price', 'payment_method', 'sale_date']
    list_filter = ['payment_method', 'sale_date']
    search_fields = ['customer__name', 'jewellery_item__name', 'jewellery_item__item_code']
    readonly_fields = ['sale_date']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'sale', 'amount', 'payment_method', 'payment_date', 'reference']
    list_filter = ['payment_method', 'payment_date']
    search_fields = ['sale__id', 'sale__customer__name', 'reference']
    readonly_fields = ['payment_date']


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'interested_item', 'category', 'budget', 'status', 'next_followup_date', 'created_at']
    list_filter = ['status', 'category', 'next_followup_date', 'created_at']
    search_fields = ['customer__name', 'customer__mobile', 'interested_item']
    readonly_fields = ['created_at']


@admin.register(OldGoldTransaction)
class OldGoldTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'transaction_number', 'transaction_type', 'customer',
        'purity', 'gross_weight', 'net_weight', 'effective_rate',
        'final_value', 'status', 'created_at'
    ]
    list_filter = ['transaction_type', 'status', 'metal_type', 'purity', 'created_at']
    search_fields = ['transaction_number', 'customer__name', 'customer__mobile', 'item_description']
    readonly_fields = ['created_at', 'pure_weight', 'gross_valuation', 'deduction_amount', 'final_value']


