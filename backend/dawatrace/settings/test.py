import os

os.environ.setdefault("DAWATRACE_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DAWATRACE_REDIS_URL", "locmem://")
os.environ.setdefault("DAWATRACE_CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("DAWATRACE_SECRET_KEY", "test-only-not-a-secret")
os.environ.setdefault("DAWATRACE_OBJECT_SIGNING_KEY", "test-document-signing-key")

from .base import *

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
FHIR_WRITE_INTERACTIONS_ENABLED = True
CELERY_TASK_ALWAYS_EAGER = True
MIDDLEWARE = [entry for entry in MIDDLEWARE if entry != "whitenoise.middleware.WhiteNoiseMiddleware"]
