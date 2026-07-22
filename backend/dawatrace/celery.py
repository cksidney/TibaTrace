import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dawatrace.settings.production")

app = Celery("dawatrace")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
