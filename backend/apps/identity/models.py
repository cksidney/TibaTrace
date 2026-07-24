from __future__ import annotations

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class DawaTraceUserManager(UserManager):
    use_in_migrations = True


class User(AbstractUser):
    tenant = models.ForeignKey(
        "tenancy.Tenant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )
    is_platform_admin = models.BooleanField(default=False)
    professional_staff_id = models.CharField(max_length=120, blank=True)
    must_change_password = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)

    objects = DawaTraceUserManager()

    def save(self, *args, **kwargs):
        self.full_clean(exclude=("password",))
        return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.is_platform_admin and not self.tenant_id and not self.is_superuser:
            raise ValidationError({"tenant": "Non-platform users require tenant ownership."})

    def effective_capabilities(self, tenant_id=None) -> set[str]:
        if not self.is_active:
            return set()
        if self.is_superuser or self.is_platform_admin:
            return {"*"}
        effective_tenant = str(tenant_id or self.tenant_id or "")
        if not effective_tenant or str(self.tenant_id) != effective_tenant:
            return set()
        assignments = UserRole.all_objects.filter(
            tenant_id=effective_tenant,
            user_id=self.id,
            is_active=True,
            role__is_active=True,
        )
        capabilities = set()
        for granted in assignments.values_list("role__capabilities", flat=True):
            capabilities.update(granted or [])
        if not capabilities:
            return set()
        policies = AttributePolicy.all_objects.filter(
            tenant_id=effective_tenant,
            capability__in=capabilities,
            is_active=True,
        )
        for policy in policies:
            conditions = policy.conditions or {}
            required_metadata = conditions.get("user_metadata", {})
            matches = all((self.metadata or {}).get(key) == value for key, value in required_metadata.items())
            if matches and policy.effect == AttributePolicy.EFFECT_DENY:
                capabilities.discard(policy.capability)
        return capabilities

    def has_capability(self, capability: str, tenant_id=None) -> bool:
        capabilities = self.effective_capabilities(tenant_id=tenant_id)
        return "*" in capabilities or capability in capabilities


class Role(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="roles")
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    capabilities = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uq_identity_role_tenant_code")]


class UserRole(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("user", "role")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="user_roles")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="user_assignments")
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "user", "role"], name="uq_identity_user_role")]


class AttributePolicy(TimestampedModel):
    EFFECT_ALLOW = "ALLOW"
    EFFECT_DENY = "DENY"
    EFFECT_CHOICES = ((EFFECT_ALLOW, "Allow"), (EFFECT_DENY, "Deny"))

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="attribute_policies")
    code = models.CharField(max_length=120)
    capability = models.CharField(max_length=160)
    effect = models.CharField(max_length=10, choices=EFFECT_CHOICES)
    conditions = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uq_identity_abac_policy")]


class ExternalIdentityMapping(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("user",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="external_identities")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="external_identities")
    issuer = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    provider = models.CharField(max_length=80, default="OIDC")
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "issuer", "subject"], name="uq_identity_external_subject")
        ]


class ServiceAccount(TimestampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="service_accounts")
    code = models.CharField(max_length=120)
    display_name = models.CharField(max_length=200)
    capabilities = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    credential_fingerprint = models.CharField(max_length=64, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uq_identity_service_account")]
