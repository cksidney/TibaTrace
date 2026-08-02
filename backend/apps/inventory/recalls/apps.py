from django.apps import AppConfig


class RecallsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory.recalls"
    label = "recalls"
    verbose_name = "Regulatory Recalls"
