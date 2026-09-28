from django.contrib import admin
from .models import Category, JewelleryItem, StockMovement, ItemSequence


@admin.register(ItemSequence)
class ItemSequenceAdmin(admin.ModelAdmin):
    list_display = ['name', 'last_number']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'description']
    search_fields = ['name']


@admin.register(JewelleryItem)
class JewelleryItemAdmin(admin.ModelAdmin):
    list_display = [
        'tag_number', 'item_code', 'design_code', 'name', 'category',
        'metal_type', 'purity', 'gross_weight', 'stone_weight', 'net_weight',
        'huid', 'huid_status', 'hallmark_status', 'quantity', 'selling_price', 'status'
    ]
    list_filter = ['category', 'metal_type', 'huid_status', 'hallmark_status', 'status', 'created_at']
    search_fields = ['tag_number', 'item_code', 'design_code', 'name', 'huid']

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ['tag_number', 'created_at', 'updated_at']
        return ['created_at', 'updated_at']


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """Read-only view of the stock ledger (movements must never be edited)."""

    list_display = ['created_at', 'item', 'movement_type', 'quantity_change',
                    'stock_before', 'stock_after', 'reason', 'created_by']
    list_filter = ['movement_type', 'reason', 'created_at']
    search_fields = ['item__tag_number', 'item__item_code', 'item__name', 'notes']
    date_hierarchy = 'created_at'
    readonly_fields = ['item', 'movement_type', 'quantity_change', 'stock_before',
                       'stock_after', 'reason', 'notes', 'sale', 'created_by',
                       'created_at']

    def has_add_permission(self, request):
        # Stock is only ever changed through the stock adjustment flow.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


