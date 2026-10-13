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

# Run migrations on Vercel deployment if 'accounts_tenant' table is missing
# or if explicit VERCEL_AUTO_MIGRATE=1 is configured.
# Checking introspection.table_names() takes <3ms and avoids re-running migrate
# on every normal cold start once tables exist.
if os.environ.get('VERCEL'):
    try:
        from django.db import connection
        tables = connection.introspection.table_names()
        auto_requested = os.environ.get('VERCEL_AUTO_MIGRATE', '').lower() in ('1', 'true', 'yes')
        if 'accounts_tenant' not in tables or auto_requested:
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Vercel auto-migrate: applying database migrations...")
            from django.core.management import call_command
            call_command('migrate', interactive=False)
            logger.info("Vercel auto-migrate: migrations applied successfully.")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Vercel auto-migrate notice: %s", e)

