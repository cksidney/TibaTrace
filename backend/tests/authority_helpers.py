"""Explicit role grants for authorized business-workflow test setup."""

from apps.identity.models import Role, UserRole


def grant_capabilities(actor, *capabilities):
    if actor.is_platform_admin or actor.is_superuser:
        return actor
    role, _ = Role.all_objects.get_or_create(
        tenant_id=actor.tenant_id,
        code=f"TEST-AUTH-{actor.pk}",
        defaults={"name": "Test business authority", "capabilities": []},
    )
    role.capabilities = sorted(set(role.capabilities) | set(capabilities))
    role.save(update_fields=["capabilities"])
    UserRole.all_objects.get_or_create(tenant_id=actor.tenant_id, user=actor, role=role)
    return actor
