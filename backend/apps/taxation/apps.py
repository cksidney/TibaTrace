from django.apps import AppConfig


class TaxationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.taxation"
    label = "taxation"
    verbose_name = "Taxation & KRA eTIMS Fiscalization"
