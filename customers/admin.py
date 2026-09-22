from django.contrib import admin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name', 'mobile', 'email', 'created_at']
    search_fields = ['name', 'mobile', 'email']
    list_filter = ['created_at']
    readonly_fields = ['created_at']

