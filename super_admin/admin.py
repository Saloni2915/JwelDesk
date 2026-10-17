from django.contrib import admin
from .models import PlatformAuditLog


@admin.register(PlatformAuditLog)
class PlatformAuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'target_tenant', 'target_user', 'ip_address')
    list_filter = ('action', 'created_at')
    search_fields = ('actor__username', 'target_tenant__name', 'target_user__username', 'reason', 'ip_address')
    readonly_fields = ('actor', 'action', 'target_tenant', 'target_user', 'reason', 'ip_address', 'user_agent', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
