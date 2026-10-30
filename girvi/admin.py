from django.contrib import admin
from .models import (
    GirviSetting,
    GirviSequence,
    GirviLoan,
    GirviItem,
    GirviPayment,
    GirviWaiver,
    GirviAuditLog,
)


class GirviItemInline(admin.TabularInline):
    model = GirviItem
    extra = 0
    fields = ('item_name', 'metal_type', 'purity', 'quantity', 'gross_weight', 'stone_weight', 'net_weight', 'market_value', 'loan_value', 'custody_status')


class GirviPaymentInline(admin.TabularInline):
    model = GirviPayment
    extra = 0
    fields = ('receipt_number', 'payment_date', 'total_amount_received', 'interest_portion', 'principal_portion', 'payment_method', 'is_reversal')
    readonly_fields = ('receipt_number', 'payment_date', 'total_amount_received', 'interest_portion', 'principal_portion', 'payment_method', 'is_reversal')


class GirviWaiverInline(admin.TabularInline):
    model = GirviWaiver
    extra = 0
    fields = ('waiver_type', 'amount', 'reason', 'authorized_by', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(GirviLoan)
class GirviLoanAdmin(admin.ModelAdmin):
    list_display = ('loan_number', 'tenant', 'branch', 'customer', 'principal_amount', 'interest_rate_percent', 'interest_period', 'status', 'loan_date', 'maturity_date')
    list_filter = ('status', 'interest_period', 'interest_calculation_type', 'tenant', 'branch')
    search_fields = ('loan_number', 'customer__name', 'customer__mobile', 'notes')
    inlines = [GirviItemInline, GirviPaymentInline, GirviWaiverInline]


@admin.register(GirviItem)
class GirviItemAdmin(admin.ModelAdmin):
    list_display = ('item_name', 'loan', 'metal_type', 'purity', 'gross_weight', 'net_weight', 'loan_value', 'custody_status')
    list_filter = ('metal_type', 'purity', 'custody_status')
    search_fields = ('item_name', 'loan__loan_number', 'huid')


@admin.register(GirviPayment)
class GirviPaymentAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'loan', 'payment_date', 'total_amount_received', 'interest_portion', 'principal_portion', 'payment_method', 'is_reversal')
    list_filter = ('payment_method', 'is_reversal', 'payment_date')
    search_fields = ('receipt_number', 'loan__loan_number', 'reference_number')


@admin.register(GirviWaiver)
class GirviWaiverAdmin(admin.ModelAdmin):
    list_display = ('loan', 'waiver_type', 'amount', 'authorized_by', 'created_at')
    list_filter = ('waiver_type', 'created_at')
    search_fields = ('loan__loan_number', 'reason')


@admin.register(GirviSetting)
class GirviSettingAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'loan_number_prefix', 'payment_number_prefix', 'default_interest_rate_monthly', 'default_interest_period')


@admin.register(GirviSequence)
class GirviSequenceAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'sequence_type', 'last_number')
    list_filter = ('sequence_type', 'tenant')


@admin.register(GirviAuditLog)
class GirviAuditLogAdmin(admin.ModelAdmin):
    list_display = ('loan', 'action', 'user', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('loan__loan_number', 'details')

