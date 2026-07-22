from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q

from apps.terminology.models import FHIRCodeSystemRegistration, FHIRValueSetRegistration


@dataclass(frozen=True)
class CodeValidationResult:
    result: bool
    display: str = ""
    message: str = ""


class TerminologyService:
    @staticmethod
    def _prefer_tenant(queryset, tenant_id: str):
        ordering = ("-version__effective_period_start", "-created_at")
        return (
            queryset.filter(tenant_id=tenant_id).order_by(*ordering).first()
            or queryset.filter(tenant__isnull=True, version__is_global=True).order_by(*ordering).first()
        )

    @staticmethod
    def code_system(url: str, tenant_id: str, version: str | None = None):
        if not tenant_id:
            raise ValueError("Tenant is required for terminology access.")
        queryset = FHIRCodeSystemRegistration.all_objects.filter(
            Q(tenant_id=tenant_id) | Q(tenant__isnull=True, version__is_global=True),
            version__status__iexact="ACTIVE",
            url=url,
        ).select_related("version")
        if version:
            queryset = queryset.filter(version__version=version)
        return TerminologyService._prefer_tenant(queryset, tenant_id)

    @classmethod
    def validate_code(
        cls, *, system: str, code: str, tenant_id: str, version: str | None = None, display: str | None = None
    ) -> CodeValidationResult:
        registration = cls.code_system(system, tenant_id, version)
        if not registration:
            return CodeValidationResult(False, message="CodeSystem is unavailable in the active tenant scope.")
        concept = next((row for row in registration.concepts_json if str(row.get("code")) == str(code)), None)
        if not concept:
            return CodeValidationResult(False, message="Code is not present or is inactive.")
        if concept.get("inactive") is True:
            return CodeValidationResult(False, message="Code is inactive.")
        expected = str(concept.get("display") or "")
        if display is not None and expected and str(display) != expected:
            return CodeValidationResult(False, expected, "Display does not match the registered concept.")
        return CodeValidationResult(True, expected)

    @classmethod
    def expand(cls, *, url: str, tenant_id: str, offset: int = 0, count: int = 100) -> list[dict]:
        if not tenant_id:
            raise ValueError("Tenant is required for terminology access.")
        queryset = FHIRValueSetRegistration.all_objects.filter(
            Q(tenant_id=tenant_id) | Q(tenant__isnull=True, version__is_global=True),
            version__status__iexact="ACTIVE",
            url=url,
        ).select_related("version")
        value_set = cls._prefer_tenant(queryset, tenant_id)
        if not value_set:
            return []
        included: dict[tuple[str, str], dict] = {}
        for group in value_set.compose_json.get("include", []):
            system = group.get("system")
            if group.get("valueSet"):
                nested = cls.expand(url=group["valueSet"][0] if isinstance(group["valueSet"], list) else group["valueSet"], tenant_id=tenant_id)
                for row in nested:
                    included[(row.get("system", ""), row["code"])] = row
            for concept in group.get("concept", []):
                included[(system or "", str(concept["code"]))] = {
                    "system": system,
                    "code": str(concept["code"]),
                    "display": concept.get("display", ""),
                }
            if system and not group.get("concept") and not group.get("filter"):
                code_system = cls.code_system(system, tenant_id)
                if code_system:
                    for concept in code_system.concepts_json:
                        if not concept.get("inactive"):
                            included[(system, str(concept["code"]))] = {
                                "system": system,
                                "code": str(concept["code"]),
                                "display": concept.get("display", ""),
                            }
        for group in value_set.compose_json.get("exclude", []):
            system = group.get("system") or ""
            for concept in group.get("concept", []):
                included.pop((system, str(concept["code"])), None)
        rows = sorted(included.values(), key=lambda row: (row.get("system") or "", row["code"]))
        safe_offset = max(0, int(offset))
        safe_count = min(max(1, int(count)), 1000)
        return rows[safe_offset : safe_offset + safe_count]
