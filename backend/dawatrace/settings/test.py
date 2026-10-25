import base64
import os

os.environ.setdefault("DAWATRACE_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DAWATRACE_REDIS_URL", "locmem://")
os.environ.setdefault("DAWATRACE_CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("DAWATRACE_SECRET_KEY", "test-only-not-a-secret")
os.environ.setdefault("DAWATRACE_OBJECT_SIGNING_KEY", "test-document-signing-key")

from .base import *

# Synthetic test-only keys are independent of the service secret and each other.
DAWATRACE_PATIENT_IDENTIFIER_KEYS = {"test-encryption": base64.urlsafe_b64encode(b"E" * 32).decode()}
DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_KEY_ID = "test-encryption"
DAWATRACE_PATIENT_IDENTIFIER_LOOKUP_KEYS = {"test-lookup": base64.urlsafe_b64encode(b"L" * 32).decode()}
DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_LOOKUP_KEY_ID = "test-lookup"
DAWATRACE_PATIENT_IDENTIFIER_LEGACY_SECRET_KEYS = []

DEBUG = False
TESTING = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
FHIR_WRITE_INTERACTIONS_ENABLED = True
CELERY_TASK_ALWAYS_EAGER = True
MIDDLEWARE = [entry for entry in MIDDLEWARE if entry != "whitenoise.middleware.WhiteNoiseMiddleware"]
