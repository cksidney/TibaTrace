"""Exercise the HQ Windows POS download journey into the user Downloads folder."""
from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dawatrace.settings.development")
django.setup()

from django.test import Client

from apps.identity.models import User
from apps.platform.models import PosRelease

DOWNLOADS = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"
DOWNLOADS.mkdir(parents=True, exist_ok=True)

admin = User.objects.filter(is_platform_admin=True).order_by("id").first()
if admin is None:
    raise SystemExit("No platform admin available to request a download.")

client = Client(SERVER_NAME="127.0.0.1")
client.force_login(admin)

listing = client.get("/api/hq/pos-releases/")
assert listing.status_code == 200, listing.content
payload = listing.json()
assert payload.get("downloads_available") is True, payload
print("catalogue_ok", payload.get("storage_backend"), "releases", len(payload["releases"]))

windows = next(
    (row for row in payload["releases"] if row["platform"] == "WINDOWS"),
    None,
)
if windows is None:
    release = (
        PosRelease.objects.filter(platform=PosRelease.Platform.WINDOWS, is_published=True)
        .order_by("-build_number")
        .first()
    )
    if release is None:
        raise SystemExit("No published Windows release.")
    windows = {"id": str(release.pk), "download_filename": f"TibaTrace-POS-windows-{release.version}.zip"}

grant = client.post(f"/api/hq/pos-releases/{windows['id']}/download/")
assert grant.status_code == 200, grant.content
grant_body = grant.json()
print("grant_ok", grant_body.get("filename"), grant_body.get("url"))

artifact = client.get(f"/api/hq/pos-releases/{windows['id']}/artifact/")
assert artifact.status_code == 200, artifact.content
blob = b"".join(artifact.streaming_content)
assert blob, "Empty installer payload"
assert len(blob) == grant_body["size_bytes"], (len(blob), grant_body["size_bytes"])

target = DOWNLOADS / grant_body["filename"]
target.write_bytes(blob)
print("saved", target, target.stat().st_size)

extract_dir = DOWNLOADS / "TibaTrace-POS-Windows-Install"
if extract_dir.exists():
    for child in extract_dir.rglob("*"):
        if child.is_file():
            child.unlink()
else:
    extract_dir.mkdir(parents=True, exist_ok=True)

with zipfile.ZipFile(target) as archive:
    archive.extractall(extract_dir)
    print("extracted", sorted(archive.namelist()))

manifest = {
    "release_id": windows["id"],
    "filename": grant_body["filename"],
    "sha256": grant_body["sha256"],
    "size_bytes": grant_body["size_bytes"],
    "saved_to": str(target),
    "extracted_to": str(extract_dir),
}
(extract_dir / "download-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print("OK")
