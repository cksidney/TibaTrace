import json
import os
import subprocess
import sys
from pathlib import Path


def test_assets_build_without_runtime_keys_and_produce_the_production_manifest(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment.update(DJANGO_SETTINGS_MODULE="dawatrace.settings.build",
                       DAWATRACE_SECRET_KEY="build-only-not-a-production-secret",
                       DAWATRACE_OBJECT_SIGNING_KEY="build-only-not-a-production-secret",
                       DAWATRACE_DOCUMENT_ENCRYPTION_KEYS="{}", DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID="",
                       DAWATRACE_DATABASE_URL="sqlite:///:memory:")
    result = subprocess.run([sys.executable, "-c", """
import sys
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
assert settings.STORAGES['staticfiles']['BACKEND'] == 'whitenoise.storage.CompressedManifestStaticFilesStorage'
settings.STATIC_ROOT = sys.argv[1]
call_command('collectstatic', interactive=False, verbosity=0)
""", str(tmp_path)], cwd=backend, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "staticfiles.json").read_text())
    hashed = manifest["paths"]["admin/css/base.css"]
    assert hashed != "admin/css/base.css"
    assert (tmp_path / hashed).is_file()
