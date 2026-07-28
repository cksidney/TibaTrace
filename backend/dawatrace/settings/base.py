from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BASE_DIR.parent


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, "true" if default else "false").strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [value.strip() for value in env(name, default).split(",") if value.strip()]


def database_config(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme == "sqlite":
        path = unquote(parsed.path or "")
        if path in {"", "/:memory:"}:
            name = ":memory:"
        elif path.startswith("/"):
            name = path
        else:
            name = str(ROOT_DIR / path)
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": name}
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("DAWATRACE_DATABASE_URL must use sqlite or postgresql.")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "localhost",
        "PORT": parsed.port or 5432,
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"sslmode": env("DAWATRACE_DATABASE_SSLMODE", "prefer")},
    }


SECRET_KEY = env("DAWATRACE_SECRET_KEY", "unsafe-development-key")
DEBUG = env_bool("DAWATRACE_DEBUG", False)
DAWATRACE_ENV = env("DAWATRACE_ENV", "development")
ALLOWED_HOSTS = env_list("DAWATRACE_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "django_filters",
    "apps.core",
    "apps.platform",
    "apps.tenancy",
    "apps.pharmacy_network",
    "apps.identity",
    "apps.pos_shift",
    "apps.pricing",
    "apps.organizations",
    "apps.medicines",
    "apps.procurement",
    "apps.inventory",
    "apps.patients",
    "apps.practitioners",
    "apps.prescription",
    "apps.clinical",
    "apps.cds",
    "apps.terminology",
    "apps.audit",
    "apps.workflows",
    "apps.notifications",
    "apps.crosswalks",
    "apps.documents",
    "apps.fhir",
    "apps.customers",
    "apps.sales",
    "apps.insurance",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.CorrelationIdMiddleware",
    "apps.core.middleware.TenantContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "dawatrace.urls"
LOGIN_URL = "/admin/login/"
WSGI_APPLICATION = "dawatrace.wsgi.application"
ASGI_APPLICATION = "dawatrace.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {
    "default": database_config(
        env("DAWATRACE_DATABASE_URL", f"sqlite:///{BASE_DIR / 'dawatrace.sqlite3'}")
    )
}

AUTH_USER_MODEL = "identity.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DAWATRACE_TIME_ZONE", "Africa/Nairobi")

# Where POS installers are stored.
#
# S3-compatible, so this is the same configuration for AWS S3 and for a
# self-hosted MinIO -- only the endpoint differs. Unset by default: with no
# credentials the download endpoint answers 503 rather than pretending, and the
# release list still renders with downloads marked unavailable.
POS_RELEASE_STORAGE = {
    "bucket": env("TIBATRACE_RELEASE_BUCKET", ""),
    "endpoint_url": env("TIBATRACE_RELEASE_ENDPOINT_URL", ""),
    "access_key": env("TIBATRACE_RELEASE_ACCESS_KEY", ""),
    "secret_key": env("TIBATRACE_RELEASE_SECRET_KEY", ""),
    "region": env("TIBATRACE_RELEASE_REGION", "us-east-1"),
}


USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = ROOT_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_ROOT = Path(env("DAWATRACE_OBJECT_STORAGE_ROOT", str(ROOT_DIR / "media")))
MEDIA_URL = "/media/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "EXCEPTION_HANDLER": "apps.core.api.exception_handler.dawatrace_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        # Bounds password guessing on the sign-in form. A password field with
        # no throttle is an offline attack conducted online.
        "signin": "10/min",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "DawaTrace API",
    "DESCRIPTION": "Independent pharmacy and healthcare clinical-core API",
    "VERSION": "0.1.0-alpha.1",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "QualityStatusEnum": "apps.procurement.models.ReceivedBatch.QualityStatus",
        "InventoryBatchQualityStatusEnum": "apps.inventory.models.InventoryBatch.QualityStatus",
        "PatientIdentifierVerificationStatusEnum": "apps.patients.models.PatientIdentifier.VERIFICATION_STATUSES",
        "ClinicalRecordVerificationStatusEnum": "apps.patients.models.PatientAllergy.VERIFICATION_CHOICES",
    },
}

SIMPLE_JWT = {
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

CORS_ALLOWED_ORIGINS = env_list("DAWATRACE_CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

REDIS_URL = env("DAWATRACE_REDIS_URL", "redis://localhost:6380/0")
if REDIS_URL.startswith("locmem://"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
else:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        }
    }

CELERY_BROKER_URL = env("DAWATRACE_CELERY_BROKER_URL", "redis://localhost:6380/1")
CELERY_RESULT_BACKEND = env("DAWATRACE_CELERY_RESULT_BACKEND", "redis://localhost:6380/2")
CELERY_TASK_ALWAYS_EAGER = env_bool("DAWATRACE_CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BEAT_SCHEDULE = {}
CELERY_TASK_ROUTES = {"apps.*": {"queue": "dawatrace-clinical"}}

#: The product version, in one place. The POS shell renders this rather than a
#: hardcoded badge -- it read "ENTERPRISE DISPENSING v2.5" on the busiest screen
#: in the product while every app in the repository was 0.1.0-alpha.1.
DAWATRACE_VERSION = "0.1.0-alpha.1"

FHIR_VERSION = "4.0.1"
FHIR_IMPLEMENTATION_NAME = "DawaTrace FHIR Gateway"
FHIR_PUBLIC_BASE_URL = env("DAWATRACE_FHIR_PUBLIC_BASE_URL", "http://localhost:8000/api/fhir/r4/")
FHIR_WRITE_INTERACTIONS_ENABLED = env_bool("DAWATRACE_FHIR_WRITE_INTERACTIONS_ENABLED", False)
FHIR_SEARCH_MAX_COUNT = int(env("DAWATRACE_FHIR_SEARCH_MAX_COUNT", "100"))
FHIR_BUNDLE_MAX_ENTRIES = int(env("DAWATRACE_FHIR_BUNDLE_MAX_ENTRIES", "100"))
FHIR_TERMINOLOGY_EXPANSION_MAX = int(env("DAWATRACE_FHIR_TERMINOLOGY_EXPANSION_MAX", "200"))
FHIR_TERMINOLOGY_EXPANSION_ABSOLUTE_MAX = int(
    env("DAWATRACE_FHIR_TERMINOLOGY_EXPANSION_ABSOLUTE_MAX", "10000")
)
FHIR_TERMINOLOGY_EXPANSION_TIMEOUT_SECONDS = float(
    env("DAWATRACE_FHIR_TERMINOLOGY_EXPANSION_TIMEOUT_SECONDS", "5")
)
FHIR_TERMINOLOGY_EXPANSION_CACHE_SECONDS = int(
    env("DAWATRACE_FHIR_TERMINOLOGY_EXPANSION_CACHE_SECONDS", "300")
)
FHIR_ALLOWED_ABSOLUTE_REFERENCE_HOSTS = env_list(
    "DAWATRACE_FHIR_ALLOWED_ABSOLUTE_REFERENCE_HOSTS", "localhost,127.0.0.1"
)

DAWATRACE_PRODUCT_NAME = "DawaTrace"
DAWATRACE_VENDOR = "Esenai Group Ltd"
DAWATRACE_CDS_SERVICE_NAME = "DawaTrace Clinical Decision Support"
DAWATRACE_OBJECT_STORAGE_BACKEND = env("DAWATRACE_OBJECT_STORAGE_BACKEND", "local")
DAWATRACE_OBJECT_SIGNING_KEY = env("DAWATRACE_OBJECT_SIGNING_KEY", "")
DAWATRACE_DOCUMENT_MAX_BYTES = int(env("DAWATRACE_DOCUMENT_MAX_BYTES", str(20 * 1024 * 1024)))
DAWATRACE_DOCUMENT_ALLOWED_CONTENT_TYPES = env_list(
    "DAWATRACE_DOCUMENT_ALLOWED_CONTENT_TYPES",
    "application/pdf,image/jpeg,image/png,text/plain",
)

SESSION_COOKIE_SECURE = env_bool("DAWATRACE_SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("DAWATRACE_CSRF_COOKIE_SECURE", False)
SECURE_SSL_REDIRECT = env_bool("DAWATRACE_SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = int(env("DAWATRACE_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DAWATRACE_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("DAWATRACE_SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": '{{"level":"{levelname}","logger":"{name}","message":"{message}"}}',
            "style": "{",
        }
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": env("DAWATRACE_LOG_LEVEL", "INFO")},
}
