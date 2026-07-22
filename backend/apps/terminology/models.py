from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import TimestampedModel
from apps.core.tenant_context import get_current_tenant_id


class TerminologyManager(models.Manager):
    def get_queryset(self):
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            return super().get_queryset().none()
        return super().get_queryset().filter(Q(tenant_id=tenant_id) | Q(tenant__isnull=True, is_global=True))

    def for_tenant(self, tenant):
        tenant_id = getattr(tenant, "pk", tenant)
        if not tenant_id:
            raise ValueError("A tenant is required for terminology access.")
        return super().get_queryset().filter(Q(tenant_id=tenant_id) | Q(tenant__isnull=True, is_global=True))


class FHIRTerminologyVersion(TimestampedModel):
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="terminology_versions"
    )
    canonical_url = models.CharField(max_length=255)
    version = models.CharField(max_length=50)
    publisher = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=50, default="ACTIVE")
    is_global = models.BooleanField(default=False)
    effective_period_start = models.DateTimeField(null=True, blank=True)
    effective_period_end = models.DateTimeField(null=True, blank=True)
    source_name = models.CharField(max_length=160)
    source_version = models.CharField(max_length=80)
    licence = models.CharField(max_length=160)

    objects = TerminologyManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "canonical_url", "version"],
                condition=Q(tenant__isnull=False),
                name="uq_term_version_tenant",
            ),
            models.UniqueConstraint(
                fields=["canonical_url", "version"],
                condition=Q(tenant__isnull=True, is_global=True),
                name="uq_term_version_global",
            ),
            models.CheckConstraint(
                condition=Q(tenant__isnull=False, is_global=False) | Q(tenant__isnull=True, is_global=True),
                name="ck_term_explicit_scope",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "status"], name="ix_term_version_scope")]

    def clean(self):
        super().clean()
        if self.is_global == bool(self.tenant_id):
            raise ValidationError("Terminology scope must be one tenant or explicitly global.")
        if self.effective_period_start and self.effective_period_end:
            if self.effective_period_end < self.effective_period_start:
                raise ValidationError({"effective_period_end": "Effective end cannot precede start."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class FHIRCodeSystemRegistration(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    version = models.ForeignKey(FHIRTerminologyVersion, on_delete=models.CASCADE, related_name="code_systems")
    url = models.CharField(max_length=255)
    name = models.CharField(max_length=150)
    title = models.CharField(max_length=255, blank=True)
    content_mode = models.CharField(max_length=50, default="COMPLETE")
    concepts_json = models.JSONField(default=list)
    is_global = models.BooleanField(default=False)

    objects = TerminologyManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "url"], name="uq_code_system_version")]

    def clean(self):
        super().clean()
        if self.version_id:
            if self.tenant_id != self.version.tenant_id or self.is_global != self.version.is_global:
                raise ValidationError({"tenant": "CodeSystem scope must match its terminology version."})
        mode = self.content_mode.upper().replace("-", "_")
        if mode not in {"NOT_PRESENT", "EXAMPLE", "FRAGMENT", "COMPLETE", "SUPPLEMENT"}:
            raise ValidationError({"content_mode": "Unsupported FHIR R4 CodeSystem content mode."})
        if not isinstance(self.concepts_json, list) or any(not isinstance(row, dict) for row in self.concepts_json):
            raise ValidationError({"concepts_json": "CodeSystem concepts must be a list of objects."})
        codes = [str(row.get("code") or "").strip() for row in self.concepts_json]
        if any(not code for code in codes) or len(codes) != len(set(codes)):
            raise ValidationError({"concepts_json": "Concept codes are required and unique."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class FHIRValueSetRegistration(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    version = models.ForeignKey(FHIRTerminologyVersion, on_delete=models.CASCADE, related_name="value_sets")
    url = models.CharField(max_length=255)
    name = models.CharField(max_length=150)
    title = models.CharField(max_length=255, blank=True)
    compose_json = models.JSONField(default=dict)
    is_global = models.BooleanField(default=False)

    objects = TerminologyManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "url"], name="uq_value_set_version")]

    def clean(self):
        super().clean()
        if self.version_id:
            if self.tenant_id != self.version.tenant_id or self.is_global != self.version.is_global:
                raise ValidationError({"tenant": "ValueSet scope must match its terminology version."})
        compose = self.compose_json or {}
        if not isinstance(compose, dict):
            raise ValidationError({"compose_json": "ValueSet compose must be an object."})
        for group_name in ("include", "exclude"):
            groups = compose.get(group_name, [])
            if not isinstance(groups, list):
                raise ValidationError({"compose_json": f"ValueSet {group_name} must be a list."})
            for group in groups:
                if not isinstance(group, dict) or (not group.get("system") and not group.get("valueSet")):
                    raise ValidationError({"compose_json": f"Each {group_name} requires system or valueSet."})
                concepts = group.get("concept", [])
                if not isinstance(concepts, list) or any(
                    not isinstance(concept, dict) or not str(concept.get("code") or "").strip()
                    for concept in concepts
                ):
                    raise ValidationError({"compose_json": f"Invalid {group_name} concepts."})
                filters = group.get("filter", [])
                if not isinstance(filters, list) or any(
                    not isinstance(item, dict)
                    or not item.get("property")
                    or not item.get("op")
                    or "value" not in item
                    for item in filters
                ):
                    raise ValidationError({"compose_json": f"Invalid {group_name} filters."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
