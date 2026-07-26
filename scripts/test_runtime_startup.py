#!/usr/bin/env bash
""":"
exec "${PYTHON:-python}" "$0" "$@"
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Environment variables for production-like startup smoke test
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dawatrace.settings.production")
os.environ.setdefault("DAWATRACE_ENV", "production")
os.environ.setdefault("DAWATRACE_SECRET_KEY", "smoke-test-secret-key-must-be-sufficiently-long")
os.environ.setdefault("DAWATRACE_OBJECT_SIGNING_KEY", "smoke-test-object-signing-key")
os.environ.setdefault("DAWATRACE_ALLOWED_HOSTS", "tibatrace.example.test")
os.environ.setdefault("DAWATRACE_CSRF_TRUSTED_ORIGINS", "https://tibatrace.example.test")
os.environ.setdefault("DAWATRACE_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DAWATRACE_REDIS_URL", "locmem://")
os.environ.setdefault("DAWATRACE_SECURE_SSL_REDIRECT", "false")
os.environ.setdefault("DAWATRACE_FHIR_PUBLIC_BASE_URL", "https://tibatrace.example.test/api/fhir/r4/")
os.environ.setdefault("DAWATRACE_OBJECT_STORAGE_BACKEND", "local")
os.environ.setdefault("DAWATRACE_OBJECT_STORAGE_ROOT", str(ROOT / "artifacts" / "generated" / "smoke_storage"))

(ROOT / "staticfiles").mkdir(parents=True, exist_ok=True)

def run_runtime_startup_checks():
    print("=== DawaTrace Production Runtime Startup Smoke Test ===")

    try:
        import django
        django.setup()
        print(" [1/6] Django setup & production settings loading: OK")
    except Exception as e:
        print(f"❌ Failed Django setup: {e}", file=sys.stderr)
        return 1

    try:
        from dawatrace.wsgi import application as wsgi_app
        assert wsgi_app is not None
        print(" [2/6] WSGI application import & initialization: OK")
    except Exception as e:
        print(f"❌ Failed WSGI application import: {e}", file=sys.stderr)
        return 1

    try:
        from dawatrace.asgi import application as asgi_app
        assert asgi_app is not None
        print(" [3/6] ASGI application import & initialization: OK")
    except Exception as e:
        print(f"❌ Failed ASGI application import: {e}", file=sys.stderr)
        return 1

    try:
        from dawatrace.celery import app as celery_app
        assert celery_app is not None
        print(" [4/6] Celery worker application import: OK")
    except Exception as e:
        print(f"❌ Failed Celery application import: {e}", file=sys.stderr)
        return 1

    try:
        from django.urls import resolve, reverse
        health_url = reverse("health")
        resolved = resolve(health_url)
        assert resolved.func is not None
        print(f" [5/6] URL routing & endpoint resolution ('{health_url}'): OK")
    except Exception as e:
        print(f"❌ Failed URL routing check: {e}", file=sys.stderr)
        return 1

    try:
        from django.conf import settings
        storage_backend = getattr(settings, "DAWATRACE_OBJECT_STORAGE_BACKEND", "local")
        assert storage_backend in ["local", "s3", "gcs"]
        print(" [6/6] Object storage adapter configuration: OK")
    except Exception as e:
        print(f"❌ Failed Storage configuration check: {e}", file=sys.stderr)
        return 1

    print("✅ Runtime startup smoke test PASSED successfully!")
    return 0

if __name__ == "__main__":
    sys.exit(run_runtime_startup_checks())
