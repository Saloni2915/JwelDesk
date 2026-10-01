"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()
app = application

# On Vercel serverless functions with ephemeral /tmp/db.sqlite3, ensure SQLite tables exist.
# For production PostgreSQL (Supabase/Neon), migrations should be applied directly
# to the database (bypassing pooler advisory lock limits and avoiding cold-start latency).
if os.environ.get('VERCEL') and (not os.environ.get('DATABASE_URL') or os.environ.get('VERCEL_AUTO_MIGRATE')):
    try:
        from django.core.management import call_command
        call_command('migrate', interactive=False)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Vercel auto-migrate notice: %s", e)

