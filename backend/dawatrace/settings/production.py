from django.core.exceptions import ImproperlyConfigured

from apps.documents.encryption import DocumentEncryptionError, validate_document_keyring
from apps.patients.identifier_crypto import IdentifierProtectionError, validate_identifier_keyrings

from .base import *

if TIBATRACE_PRIVILEGED_MFA_REQUIRED or TIBATRACE_MFA_ENCRYPTION_KEYS:
    try:
        validate_document_keyring(TIBATRACE_MFA_ENCRYPTION_KEYS, TIBATRACE_MFA_ACTIVE_KEY_ID)
        from apps.documents.encryption import decode_document_key
        mfa_material = [decode_document_key(value) for value in TIBATRACE_MFA_ENCRYPTION_KEYS.values()]
        other_material = [decode_document_key(value) for ring in (
            DAWATRACE_DOCUMENT_ENCRYPTION_KEYS, DAWATRACE_PATIENT_IDENTIFIER_KEYS,
            DAWATRACE_PATIENT_IDENTIFIER_LOOKUP_KEYS) for value in ring.values()]
        if len(mfa_material) > 16 or len(set(mfa_material)) != len(mfa_material) or set(mfa_material) & set(other_material):
            raise ValueError('MFA encryption keys must be distinct and bounded.')
    except (DocumentEncryptionError, ValueError):
        raise ImproperlyConfigured('Valid separate MFA encryption keys are required before MFA enforcement.') from None

DEBUG = False

CSRF_TRUSTED_ORIGINS = env_list("DAWATRACE_CSRF_TRUSTED_ORIGINS", "")

if SECRET_KEY in {"", "unsafe-development-key"}:
    raise ImproperlyConfigured("DAWATRACE_SECRET_KEY is required in production.")
if not DAWATRACE_OBJECT_SIGNING_KEY:
    raise ImproperlyConfigured("DAWATRACE_OBJECT_SIGNING_KEY is required in production.")
try:
    validate_document_keyring(
        DAWATRACE_DOCUMENT_ENCRYPTION_KEYS,
        DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID,
    )
except DocumentEncryptionError as exc:
    raise ImproperlyConfigured(
        "A valid active clinical-document encryption keyring is required in production settings."
    ) from exc

try:
    validate_identifier_keyrings(
        DAWATRACE_PATIENT_IDENTIFIER_KEYS, DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_KEY_ID,
        DAWATRACE_PATIENT_IDENTIFIER_LOOKUP_KEYS, DAWATRACE_PATIENT_IDENTIFIER_ACTIVE_LOOKUP_KEY_ID,
        DAWATRACE_PATIENT_IDENTIFIER_LEGACY_SECRET_KEYS,
    )
except IdentifierProtectionError as exc:
    raise ImproperlyConfigured("Valid independent patient identifier encryption and lookup keyrings are required in production settings.") from exc

if DAWATRACE_ENV == "production":
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured("DAWATRACE_ALLOWED_HOSTS is required in production.")
    if not CSRF_TRUSTED_ORIGINS:
        raise ImproperlyConfigured("DAWATRACE_CSRF_TRUSTED_ORIGINS is required in production.")
    if not FHIR_PUBLIC_BASE_URL.startswith("https://"):
        raise ImproperlyConfigured("DAWATRACE_FHIR_PUBLIC_BASE_URL must use HTTPS in production.")
    if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
        sslmode = DATABASES["default"]["OPTIONS"].get("sslmode")
        if sslmode not in {"require", "verify-ca", "verify-full"}:
            raise ImproperlyConfigured("DAWATRACE_DATABASE_SSLMODE must require TLS in production.")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = env_bool("DAWATRACE_SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = int(env("DAWATRACE_SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

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
