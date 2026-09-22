from django.contrib import admin
from .models import Category, JewelleryItem


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'description']
    search_fields = ['name']


@admin.register(JewelleryItem)
class JewelleryItemAdmin(admin.ModelAdmin):
    list_display = ['item_code', 'design_code', 'name', 'category', 'metal_type', 'purity', 'gross_weight', 'net_weight', 'selling_price', 'status']
    list_filter = ['category', 'metal_type', 'status', 'created_at']
    search_fields = ['item_code', 'design_code', 'name']
    readonly_fields = ['created_at', 'updated_at']

