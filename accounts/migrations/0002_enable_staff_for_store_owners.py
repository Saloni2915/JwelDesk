from django.db import migrations


def make_store_owners_staff(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Employee = apps.get_model('team', 'Employee')
    # All users who are not subordinate employees are store owners/administrators
    employee_user_ids = Employee.objects.filter(user__isnull=False).values_list('user_id', flat=True)
    User.objects.exclude(id__in=employee_user_ids).update(is_staff=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('team', '0001_initial_team_models'),
    ]

    operations = [
        migrations.RunPython(make_store_owners_staff, noop),
    ]
