from django.contrib import admin
from .models import Branch, Employee, EmployeePermission, Role


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display  = ('name', 'phone', 'is_active')
    list_filter   = ('is_active',)
    search_fields = ('name',)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display  = ('name', 'is_builtin')
    list_filter   = ('is_builtin',)


class PermissionInline(admin.TabularInline):
    model  = EmployeePermission
    extra  = 0


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display   = ('employee_id', 'full_name', 'email', 'role',
                      'department', 'status')
    list_filter    = ('role', 'status', 'department')
    search_fields  = ('full_name', 'email', 'employee_id')
    raw_id_fields  = ('user',)
    inlines        = [PermissionInline]
    readonly_fields = ('employee_id', 'created_at', 'updated_at')
