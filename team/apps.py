from django.apps import AppConfig


class TeamConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'team'
    label = 'team'
    verbose_name = 'Team Management'

    def ready(self):
        # Trigger signal connections (none yet, placeholder for future use)
        pass
