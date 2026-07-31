"""Tenant identity administration — create, status, password reset, role grants."""
from __future__ import annotations

import secrets
import string

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.identity.models import Role, User, UserRole
from apps.tenancy.models import Tenant

ACCOUNT_STATUS_ACTIVE = "ACTIVE"
ACCOUNT_STATUS_SUSPENDED = "SUSPENDED"
ACCOUNT_STATUS_DISABLED = "DISABLED"


def account_status_for(user: User) -> str:
    metadata = user.metadata or {}
    stored = str(metadata.get("account_status") or "").upper()
    if stored in {ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_SUSPENDED, ACCOUNT_STATUS_DISABLED}:
        if user.is_active and stored != ACCOUNT_STATUS_ACTIVE:
            return ACCOUNT_STATUS_ACTIVE
        if not user.is_active and stored == ACCOUNT_STATUS_ACTIVE:
            return ACCOUNT_STATUS_DISABLED
        return stored
    return ACCOUNT_STATUS_ACTIVE if user.is_active else ACCOUNT_STATUS_DISABLED


class UserAdministrationService:
    @staticmethod
    def _tenant(tenant_id) -> Tenant:
        try:
            return Tenant.objects.get(pk=tenant_id)
        except Tenant.DoesNotExist as exc:
            raise ValidationError({"tenant": "The selected tenant does not exist."}) from exc

    @staticmethod
    def _set_status(user: User, status: str) -> User:
        status = status.upper()
        if status not in {
            ACCOUNT_STATUS_ACTIVE,
            ACCOUNT_STATUS_SUSPENDED,
            ACCOUNT_STATUS_DISABLED,
        }:
            raise ValidationError({"status": "Unsupported account status."})
        metadata = dict(user.metadata or {})
        metadata["account_status"] = status
        user.metadata = metadata
        user.is_active = status == ACCOUNT_STATUS_ACTIVE
        user.save(update_fields=["metadata", "is_active"])
        return user

    @classmethod
    @transaction.atomic
    def create_user(
        cls,
        *,
        tenant_id,
        username: str,
        email: str = "",
        first_name: str = "",
        last_name: str = "",
        password: str | None = None,
        role_ids: list | None = None,
        professional_staff_id: str = "",
        must_change_password: bool = True,
    ) -> tuple[User, str]:
        tenant = cls._tenant(tenant_id)
        username = (username or "").strip()
        if not username:
            raise ValidationError({"username": "Username is required."})
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError({"username": "That username is already in use."})

        temporary_password = password or cls.generate_temporary_password()
        user = User(
            username=username,
            email=(email or "").strip(),
            first_name=(first_name or "").strip(),
            last_name=(last_name or "").strip(),
            tenant=tenant,
            professional_staff_id=(professional_staff_id or "").strip(),
            must_change_password=must_change_password,
            is_active=True,
            metadata={"account_status": ACCOUNT_STATUS_ACTIVE},
        )
        validate_password(temporary_password, user=user)
        user.set_password(temporary_password)
        user.save()

        if role_ids:
            cls.set_roles(user=user, tenant_id=tenant.pk, role_ids=role_ids)
        return user, temporary_password

    @classmethod
    def activate(cls, *, user: User) -> User:
        return cls._set_status(user, ACCOUNT_STATUS_ACTIVE)

    @classmethod
    def suspend(cls, *, user: User) -> User:
        return cls._set_status(user, ACCOUNT_STATUS_SUSPENDED)

    @classmethod
    def disable(cls, *, user: User) -> User:
        return cls._set_status(user, ACCOUNT_STATUS_DISABLED)

    @classmethod
    @transaction.atomic
    def reset_password(cls, *, user: User, password: str | None = None) -> tuple[User, str]:
        temporary_password = password or cls.generate_temporary_password()
        validate_password(temporary_password, user=user)
        user.set_password(temporary_password)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        return user, temporary_password

    @classmethod
    @transaction.atomic
    def set_roles(cls, *, user: User, tenant_id, role_ids: list) -> list[UserRole]:
        tenant = cls._tenant(tenant_id)
        if str(user.tenant_id) != str(tenant.pk):
            raise ValidationError({"user": "User is outside this tenant."})

        desired = {str(role_id) for role_id in (role_ids or [])}
        roles = list(Role.all_objects.filter(tenant=tenant, pk__in=desired, is_active=True))
        if len(roles) != len(desired):
            raise ValidationError({"role_ids": "One or more roles are invalid for this tenant."})

        existing = {
            str(grant.role_id): grant
            for grant in UserRole.all_objects.filter(tenant=tenant, user=user)
        }
        kept: list[UserRole] = []
        for role in roles:
            grant = existing.get(str(role.pk))
            if grant is None:
                grant = UserRole.all_objects.create(
                    tenant=tenant,
                    user=user,
                    role=role,
                    is_active=True,
                )
            elif not grant.is_active:
                grant.is_active = True
                grant.save(update_fields=["is_active", "updated_at"])
            kept.append(grant)

        for role_id, grant in existing.items():
            if role_id not in desired and grant.is_active:
                grant.is_active = False
                grant.save(update_fields=["is_active", "updated_at"])

        return kept

    @classmethod
    def _clean_capabilities(cls, capabilities: list[str] | None) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for capability in capabilities or []:
            code = str(capability or "").strip()
            if not code or code in seen:
                continue
            if len(code) > 160:
                raise ValidationError({"capabilities": f"Capability exceeds 160 characters: {code[:32]}…"})
            seen.add(code)
            cleaned.append(code)
        return cleaned

    @classmethod
    @transaction.atomic
    def create_role(
        cls,
        *,
        tenant_id,
        code: str,
        name: str,
        capabilities: list[str] | None = None,
        is_active: bool = True,
    ) -> Role:
        tenant = cls._tenant(tenant_id)
        cleaned_code = (code or "").strip().upper().replace(" ", "_")
        cleaned_name = (name or "").strip()
        if not cleaned_code:
            raise ValidationError({"code": "Role code is required."})
        if len(cleaned_code) > 80:
            raise ValidationError({"code": "Role code must be 80 characters or fewer."})
        if not cleaned_name:
            raise ValidationError({"name": "Role name is required."})
        if Role.all_objects.filter(tenant=tenant, code__iexact=cleaned_code).exists():
            raise ValidationError({"code": "A role with this code already exists for the tenant."})

        return Role.all_objects.create(
            tenant=tenant,
            code=cleaned_code,
            name=cleaned_name,
            capabilities=cls._clean_capabilities(capabilities),
            is_active=bool(is_active),
            is_system=False,
        )

    @classmethod
    @transaction.atomic
    def ensure_default_tenant_roles(cls, *, tenant_id) -> Role:
        """Ensure the tenant has an admin role that can manage users and rights."""
        tenant = cls._tenant(tenant_id)
        role, created = Role.all_objects.get_or_create(
            tenant=tenant,
            code="TENANT_ADMIN",
            defaults={
                "name": "Tenant administrator",
                "capabilities": [
                    "identity.manage",
                    "inventory.read",
                    "inventory.manage",
                    "procurement.read",
                    "pricing.read",
                    "insurance.read",
                    "dispensing.read",
                    "prescriptions.read",
                    "pos.shift.manage",
                ],
                "is_active": True,
                "is_system": True,
            },
        )
        if not created:
            desired = {
                *(role.capabilities or []),
                "identity.manage",
            }
            merged = sorted(desired)
            if role.capabilities != merged or not role.is_active:
                role.capabilities = merged
                role.is_active = True
                role.save(update_fields=["capabilities", "is_active", "updated_at"])
        return role

    @classmethod
    @transaction.atomic
    def update_role(
        cls,
        *,
        role: Role,
        name: str | None = None,
        capabilities: list[str] | None = None,
        is_active: bool | None = None,
    ) -> Role:
        updates: list[str] = []
        if name is not None:
            cleaned = name.strip()
            if not cleaned:
                raise ValidationError({"name": "Role name is required."})
            if role.name != cleaned:
                role.name = cleaned
                updates.append("name")
        if capabilities is not None:
            cleaned_capabilities = cls._clean_capabilities(capabilities)
            if role.capabilities != cleaned_capabilities:
                role.capabilities = cleaned_capabilities
                updates.append("capabilities")
        if is_active is not None and role.is_active != is_active:
            # Keep the bootstrap admin role usable.
            if role.is_system and role.code == "TENANT_ADMIN" and not is_active:
                raise ValidationError({"is_active": "The tenant administrator role cannot be deactivated."})
            role.is_active = is_active
            updates.append("is_active")
        if updates:
            role.save(update_fields=[*updates, "updated_at"])
        return role

    @staticmethod
    def generate_temporary_password(length: int = 14) -> str:
        alphabet = string.ascii_letters + string.digits
        # Ensure mixed classes for common validators.
        parts = [
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.digits),
            "!",
        ]
        parts.extend(secrets.choice(alphabet) for _ in range(max(length - 4, 8)))
        secrets.SystemRandom().shuffle(parts)
        return "".join(parts)


def user_category_label(user: User) -> str:
    if user.is_superuser:
        return "Superuser"
    if user.is_platform_admin:
        return "Platform admin"
    status = account_status_for(user)
    if status == ACCOUNT_STATUS_SUSPENDED:
        return "Suspended"
    if status == ACCOUNT_STATUS_DISABLED or not user.is_active:
        return "Disabled"
    return "Standard"
