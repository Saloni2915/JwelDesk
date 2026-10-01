"""
team/management/commands/seed_roles.py
---------------------------------------
Management command to seed (or re-seed) the built-in JewelDesk roles.

Usage:
    python manage.py seed_roles

This is safe to run multiple times (idempotent).  Use this when deploying to a
new database or after wiping test data to restore the expected role set.

The same data is seeded by migrations 0002 and 0005, but this command provides
a convenient way to re-seed without rolling back migrations.
"""

from django.core.management.base import BaseCommand

from team.models import Role


BUILTIN_ROLES = [
    (Role.ROLE_ADMIN,             'Full access to all JewelDesk modules.'),
    (Role.ROLE_HR,                'Human resources, team management, and employee records.'),
    (Role.ROLE_MANAGER,           'Manage day-to-day operations across modules.'),
    (Role.ROLE_SALES,             'Handle sales counters and customer interactions.'),
    (Role.ROLE_SALES_EXECUTIVE,   'Handle customer interactions and advanced sales.'),
    (Role.ROLE_INVENTORY,         'Manage jewellery stock and inventory tracking.'),
    (Role.ROLE_INVENTORY_MANAGER, 'Manage jewellery inventory and stock in full.'),
    (Role.ROLE_ACCOUNTANT,        'View financial reports and sales data.'),
    (Role.ROLE_SUPPORT,           'Customer support, order tracking, and enquiry management.'),
    (Role.ROLE_CASHIER,           'Process sales at the counter.'),
]


class Command(BaseCommand):
    help = 'Seed or re-seed the built-in JewelDesk roles (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Update description of existing built-in roles (default: skip if exists).',
        )

    def handle(self, *args, **options):
        force = options['force']
        created_count = 0
        updated_count = 0

        for name, description in BUILTIN_ROLES:
            role, created = Role.objects.get_or_create(
                name=name,
                defaults={'description': description, 'is_builtin': True},
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  Created role: {name}'))
            elif force:
                role.description = description
                role.is_builtin = True
                role.save(update_fields=['description', 'is_builtin'])
                updated_count += 1
                self.stdout.write(f'  Updated role: {name}')
            else:
                self.stdout.write(f'  Exists (skipped): {name}')

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone. Created {created_count} role(s), updated {updated_count} role(s).'
            )
        )
