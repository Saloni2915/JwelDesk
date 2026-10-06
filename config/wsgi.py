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

# Auto-migration should NEVER run automatically on every serverless request/cold start.
# Running migrate during WSGI import adds 5-15 seconds of latency on every cold start
# and causes advisory lock contention with PostgreSQL poolers.
# If migrations are explicitly required on deployment, set VERCEL_AUTO_MIGRATE=1.
if os.environ.get('VERCEL') and os.environ.get('VERCEL_AUTO_MIGRATE', '').lower() in ('1', 'true', 'yes'):
    try:
        from django.core.management import call_command
        call_command('migrate', interactive=False)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Vercel auto-migrate notice: %s", e)

