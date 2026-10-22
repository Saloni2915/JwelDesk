import os
import sys

sys.path.insert(0, os.getcwd())

SUPABASE_URL = "postgresql://postgres.dndgqdesihovfoaaosbg:Saloni%402215@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"

os.environ['DATABASE_URL'] = SUPABASE_URL
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.core.management import call_command

try:
    print("Testing remote database connection and migration status...")
    call_command('showmigrations', 'sales')
    call_command('showmigrations', 'coupons')
    print("Migrating remote database...")
    call_command('migrate', 'sales')
    call_command('migrate', 'coupons')
    print("Remote migration completed successfully!")
except Exception as e:
    print("Remote migration notice:", type(e).__name__, e)
