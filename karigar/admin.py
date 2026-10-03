from django.contrib import admin
from .models import Karigar, KarigarWorkAssignment, KarigarSettlement


@admin.register(Karigar)
class KarigarAdmin(admin.ModelAdmin):
    list_display = ('karigar_code', 'name', 'mobile', 'specialization', 'status', 'joining_date')
    list_filter = ('status', 'specialization', 'joining_date')
    search_fields = ('karigar_code', 'name', 'mobile', 'email', 'pan_or_id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(KarigarWorkAssignment)
class KarigarWorkAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        'assignment_number', 'karigar', 'work_type', 'metal_type',
        'net_weight_issued', 'net_weight_received', 'total_charge',
        'status', 'payment_status', 'expected_completion_date'
    )
    list_filter = ('status', 'payment_status', 'work_type', 'metal_type', 'priority')
    search_fields = ('assignment_number', 'karigar__name', 'customer__name', 'description')
    readonly_fields = (
        'assignment_number', 'net_weight_issued', 'net_weight_received',
        'wastage_weight_allowed', 'actual_wastage_weight', 'weight_difference',
        'labour_charge', 'total_charge', 'paid_amount', 'payment_status',
        'created_at', 'updated_at'
    )


@admin.register(KarigarSettlement)
class KarigarSettlementAdmin(admin.ModelAdmin):
    list_display = ('settlement_number', 'karigar', 'payment_date', 'amount', 'payment_method', 'status')
    list_filter = ('status', 'payment_method', 'payment_date')
    search_fields = ('settlement_number', 'karigar__name', 'payment_reference')
    readonly_fields = ('settlement_number', 'created_at', 'updated_at', 'cancelled_at')
