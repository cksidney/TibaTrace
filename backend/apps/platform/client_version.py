"""POS client ↔ HQ release alignment.

Tills (Windows, Android, browser terminal) must know when HQ has published a
build that changes operational behaviour. The check is intentionally cheap and
idempotent: clients call it on Sync Centre open and at most once per day, then
surface update_required before stock, cash or clinical work continues.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from apps.platform.models import PosRelease


@dataclass(frozen=True)
class ClientVersionStatus:
    platform: str
    client_version: str
    client_build: int
    latest_version: str
    latest_build: int
    update_available: bool
    update_required: bool
    operations_impact: str
    release_notes: str
    checked_at: str
    next_check_after_hours: int = 24

    def as_dict(self) -> dict:
        return {
            "platform": self.platform,
            "client_version": self.client_version,
            "client_build": self.client_build,
            "latest_version": self.latest_version,
            "latest_build": self.latest_build,
            "update_available": self.update_available,
            "update_required": self.update_required,
            "operations_impact": self.operations_impact,
            "release_notes": self.release_notes,
            "checked_at": self.checked_at,
            "next_check_after_hours": self.next_check_after_hours,
        }


def normalize_platform(raw: str) -> str:
    value = (raw or "").strip().upper()
    if value in {PosRelease.Platform.WINDOWS, "WIN", "ELECTRON", "DESKTOP"}:
        return PosRelease.Platform.WINDOWS
    if value in {PosRelease.Platform.ANDROID, "RN", "MOBILE"}:
        return PosRelease.Platform.ANDROID
    if value in {"WEB", "BROWSER", "TERMINAL", "POS_WEB"}:
        # Browser tills track the Windows catalogue until a dedicated web
        # channel exists; operational gates still apply.
        return PosRelease.Platform.WINDOWS
    return value


def evaluate_client_version(
    *,
    platform: str,
    client_version: str = "",
    client_build: int = 0,
) -> ClientVersionStatus:
    resolved = normalize_platform(platform)
    latest = (
        PosRelease.objects.filter(platform=resolved, is_published=True)
        .order_by("-build_number")
        .first()
    )
    now = timezone.now().isoformat()
    if latest is None:
        return ClientVersionStatus(
            platform=resolved or platform,
            client_version=client_version or "",
            client_build=max(0, int(client_build or 0)),
            latest_version="",
            latest_build=0,
            update_available=False,
            update_required=False,
            operations_impact="",
            release_notes="",
            checked_at=now,
        )

    build = max(0, int(client_build or 0))
    update_available = build < latest.build_number
    floor = int(latest.minimum_supported_build or 0)
    update_required = bool(floor and build < floor)
    return ClientVersionStatus(
        platform=resolved,
        client_version=client_version or "",
        client_build=build,
        latest_version=latest.version,
        latest_build=latest.build_number,
        update_available=update_available,
        update_required=update_required,
        operations_impact=latest.operations_impact or "",
        release_notes=latest.release_notes or "",
        checked_at=now,
    )


def client_build_from_request(request) -> tuple[str, str, int]:
    """Read platform / version / build from query params or POS headers."""
    headers = request.headers
    platform = (
        request.query_params.get("platform")
        or headers.get("X-POS-Client-Platform")
        or ""
    )
    version = (
        request.query_params.get("version")
        or headers.get("X-POS-Client-Version")
        or ""
    )
    raw_build = (
        request.query_params.get("build_number")
        or headers.get("X-POS-Client-Build")
        or "0"
    )
    try:
        build = int(raw_build)
    except (TypeError, ValueError):
        build = 0
    return platform, version, build


def reject_if_client_blocked(request) -> dict | None:
    """Return an error payload when a mutating POS call must be refused."""
    platform, version, build = client_build_from_request(request)
    if not platform:
        return None
    status = evaluate_client_version(
        platform=platform, client_version=version, client_build=build
    )
    if not status.update_required:
        return None
    return {
        "detail": (
            f"This till is on build {status.client_build}; HQ requires build "
            f"{status.latest_build} ({status.latest_version}) or newer before "
            "dispensing, cash or clinical operations continue."
        ),
        "code": "POS_CLIENT_UPDATE_REQUIRED",
        "client_version": status.as_dict(),
    }
