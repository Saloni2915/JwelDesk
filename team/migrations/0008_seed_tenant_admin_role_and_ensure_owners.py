"""
team/migrations/0008_seed_tenant_admin_role_and_ensure_owners.py
--------------------------------------------------------------
Data migration:
  1. Seed 'Tenant Administrator' built-in role.
  2. Ensure every existing Tenant owner has an active Employee profile
     with the 'Tenant Administrator' role and full permissions across all modules.
"""

from django.db import migrations


MODULES = [
    'dashboard',
    'team',
    'customers',
    'inventory',
    'sales',
    'purchases',
    'custom_orders',
    'reports',
    'metal_prices',
    'settings',
    'karigar',
]


def seed_tenant_admin_and_ensure_owners(apps, schema_editor):
    Role = apps.get_model('team', 'Role')
    Employee = apps.get_model('team', 'Employee')
    EmployeePermission = apps.get_model('team', 'EmployeePermission')
    Tenant = apps.get_model('accounts', 'Tenant')

    # 1. Seed or get 'Tenant Administrator' role
    tenant_admin_role, _ = Role.objects.get_or_create(
        name='Tenant Administrator',
        defaults={
            'description': 'Full administrative access across all modules as Tenant Administrator.',
            'is_builtin': True,
        },
    )

    # 2. Iterate through all tenants and ensure owner has an active Employee profile
    for tenant in Tenant.objects.all():
        owner = getattr(tenant, 'owner', None)
        if not owner:
            continue

        emp = Employee.objects.filter(tenant=tenant, user=owner).first()
        if not emp and owner.email:
            emp = Employee.objects.filter(tenant=tenant, email__iexact=owner.email).first()

        if not emp:
            # Generate next employee_id for tenant
            last = Employee.objects.filter(tenant=tenant, employee_id__startswith='EMP-').order_by('-employee_id').first()
            if last and last.employee_id:
                try:
                    num = int(last.employee_id.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    num = 1
            else:
                num = 1
            cand = f'EMP-{num:04d}'
            while Employee.objects.filter(tenant=tenant, employee_id=cand).exists():
                num += 1
                cand = f'EMP-{num:04d}'

            full_name = ''
            if hasattr(owner, 'get_full_name'):
                full_name = owner.get_full_name().strip()
            if not full_name:
                full_name = (getattr(owner, 'first_name', '') or '').strip()
            if not full_name:
                full_name = owner.username

            owner_email = (getattr(owner, 'email', '') or '').strip().lower()
            if not owner_email:
                owner_email = f"{owner.username}@jeweldesk.local"

            emp = Employee.objects.create(
                user=owner,
                tenant=tenant,
                employee_id=cand,
                full_name=full_name,
                email=owner_email,
                role=tenant_admin_role,
                designation='Tenant Administrator',
                department='Administration',
                status='Active',
            )
        else:
            updates = []
            if emp.user_id != owner.id:
                emp.user = owner
                updates.append('user')
            if emp.status != 'Active':
                emp.status = 'Active'
                updates.append('status')
            if emp.role_id != tenant_admin_role.id and getattr(emp.role, 'name', '') != 'Admin':
                emp.role = tenant_admin_role
                updates.append('role')
            if updates:
                emp.save(update_fields=updates)

        # Grant full permissions for all 11 modules
        for mod in MODULES:
            EmployeePermission.objects.update_or_create(
                employee=emp,
                module=mod,
                defaults={
                    'can_view': True,
                    'can_add': True,
                    'can_edit': True,
                    'can_delete': True,
                    'can_export': True,
                },
            )


def reverse_migration(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('team', '0007_branch_tenant_employee_tenant_and_more'),
        ('accounts', '0003_tenant_companysettings_tenant'),
    ]

    operations = [
        migrations.RunPython(seed_tenant_admin_and_ensure_owners, reverse_code=reverse_migration),
    ]
