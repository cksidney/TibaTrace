from django.core.exceptions import ImproperlyConfigured

from .base import *

DEBUG = False

if SECRET_KEY in {"", "unsafe-development-key"}:
    raise ImproperlyConfigured("DAWATRACE_SECRET_KEY is required in production.")
if not DAWATRACE_OBJECT_SIGNING_KEY:
    raise ImproperlyConfigured("DAWATRACE_OBJECT_SIGNING_KEY is required in production.")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = env_bool("DAWATRACE_SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = int(env("DAWATRACE_SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
