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

# TLS is terminated at the reverse proxy, so Django sees plain HTTP on the
# internal network. Without this, SECURE_SSL_REDIRECT above would redirect every
# already-HTTPS request back to itself forever.
#
# This is only safe because the proxy always overwrites X-Forwarded-Proto on
# inbound requests. Never enable it for a deployment where the app port is
# reachable directly -- a client could then forge the header and defeat the
# redirect entirely.
if env_bool("DAWATRACE_BEHIND_TLS_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

# Django requires the full origin (scheme included) for unsafe requests such as
# admin logins once the site is served over HTTPS.
CSRF_TRUSTED_ORIGINS = env_list("DAWATRACE_CSRF_TRUSTED_ORIGINS", "")
