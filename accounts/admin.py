from django.contrib import admin

from .models import CompanySettings


@admin.register(CompanySettings)
class CompanySettingsAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'gstin', 'phone', 'email', 'updated_at')

    def has_add_permission(self, request):
        # Singleton: only one settings row may exist.
        return not CompanySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

