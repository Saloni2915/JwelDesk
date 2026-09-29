"""
team/migrations/0002_seed_default_roles.py
------------------------------------------
Data migration: create the six built-in roles so they are available
immediately after the first `migrate` run.
"""

from django.db import migrations


BUILTIN_ROLES = [
    ('Admin',             'Full access to all JewelDesk modules.'),
    ('Manager',           'Manage day-to-day operations across modules.'),
    ('Sales Executive',   'Handle customer interactions and sales.'),
    ('Inventory Manager', 'Manage jewellery inventory and stock.'),
    ('Accountant',        'View financial reports and sales data.'),
    ('Cashier',           'Process sales at the counter.'),
]


def seed_roles(apps, schema_editor):
    Role = apps.get_model('team', 'Role')
    for name, description in BUILTIN_ROLES:
        Role.objects.get_or_create(
            name=name,
            defaults={'description': description, 'is_builtin': True},
        )


def unseed_roles(apps, schema_editor):
    Role = apps.get_model('team', 'Role')
    Role.objects.filter(
        name__in=[r[0] for r in BUILTIN_ROLES],
        is_builtin=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('team', '0001_initial_team_models'),
    ]

    operations = [
        migrations.RunPython(seed_roles, reverse_code=unseed_roles),
    ]
