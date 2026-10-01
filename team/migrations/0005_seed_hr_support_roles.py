"""
team/migrations/0005_seed_hr_support_roles.py
-----------------------------------------
Data migration: seed HR, Support, Sales, and Inventory roles.
"""

from django.db import migrations


ADDITIONAL_ROLES = [
    ('HR',        'Human resources, team management, and employee records.'),
    ('Support',   'Customer support, order tracking, and enquiry management.'),
    ('Sales',     'Handle sales counters and customer interactions.'),
    ('Inventory', 'Manage jewellery stock and inventory tracking.'),
]


def seed_additional_roles(apps, schema_editor):
    Role = apps.get_model('team', 'Role')
    for name, description in ADDITIONAL_ROLES:
        Role.objects.get_or_create(
            name=name,
            defaults={'description': description, 'is_builtin': True},
        )


def unseed_additional_roles(apps, schema_editor):
    Role = apps.get_model('team', 'Role')
    Role.objects.filter(
        name__in=[r[0] for r in ADDITIONAL_ROLES],
        is_builtin=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('team', '0004_employee_designation_employee_photo_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_additional_roles, reverse_code=unseed_additional_roles),
    ]
