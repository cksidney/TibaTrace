"""Attach declared IG profiles to rendered FHIR resources."""
from __future__ import annotations

from typing import Any, Sequence

from fhir.resources.meta import Meta

from apps.fhir.kenya_ig import profiles_for


def apply_declared_profiles(resource: Any, resource_type: str | None = None, extra: Sequence[str] = ()) -> Any:
    """Ensure meta.profile lists the locked Kenya eRx (or base) profiles.

    Idempotent: existing profile URIs are preserved and de-duplicated.
    """
    if resource is None:
        return resource
    rtype = resource_type or getattr(resource, "resource_type", None) or getattr(resource, "resourceType", None)
    declared = list(profiles_for(str(rtype or ""))) + list(extra or ())
    if not declared:
        return resource

    existing: list[str] = []
    if getattr(resource, "meta", None) is not None and getattr(resource.meta, "profile", None):
        existing = [str(p) for p in resource.meta.profile if p]

    merged = list(dict.fromkeys([*existing, *declared]))
    if resource.meta is None:
        resource.meta = Meta(profile=merged)
    else:
        resource.meta.profile = merged
    return resource
