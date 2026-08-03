"""Designate a tenant as a demonstration tenant.

Setting `is_demo` is what permits the engine to write fabricated trading
history, so designation is deliberately awkward: the operator must supply the
tenant's id, slug and name, all three of which must match, plus a reason and an
explicit confirmation. Getting all four wrong in a way that still matches a
different tenant is not a realistic accident.

Every designation writes an audit event. Undesignation is supported and audited
the same way.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Mark a tenant as a demonstration tenant (Platform Owner action)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", required=True, help="Exact tenant UUID.")
        parser.add_argument("--tenant-slug", required=True, help="Exact tenant slug.")
        parser.add_argument("--tenant-name", required=True, help="Exact tenant name.")
        parser.add_argument("--reason", required=True, help="Why this tenant is a demo tenant.")
        parser.add_argument("--actor-username", required=True, help="Platform Owner performing this.")
        parser.add_argument(
            "--confirm",
            required=True,
            help="Type the tenant slug again to confirm.",
        )
        parser.add_argument(
            "--undesignate",
            action="store_true",
            help="Clear is_demo instead of setting it.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        slug = options["tenant_slug"]
        if options["confirm"] != slug:
            raise CommandError("--confirm must repeat the tenant slug exactly.")

        tenant = Tenant.objects.select_for_update().filter(id=options["tenant_id"]).first()
        if tenant is None:
            raise CommandError(f"No tenant with id {options['tenant_id']}.")

        # All three identifiers must agree. Any mismatch means the operator is
        # not looking at the tenant they think they are.
        mismatches = []
        if tenant.slug != slug:
            mismatches.append(f"slug: supplied {slug!r}, actual {tenant.slug!r}")
        if tenant.name != options["tenant_name"]:
            mismatches.append(f"name: supplied {options['tenant_name']!r}, actual {tenant.name!r}")
        if mismatches:
            raise CommandError(
                "Tenant identity does not match:\n  " + "\n  ".join(mismatches)
            )

        actor = self._actor(options["actor_username"], tenant)

        target = not options["undesignate"]
        if tenant.is_demo == target:
            self.stdout.write(
                f"Tenant {tenant.slug} already has is_demo={target}. Nothing to do."
            )
            return

        previous = tenant.is_demo
        tenant.is_demo = target
        tenant.save(update_fields=["is_demo", "updated_at"])

        self._audit(tenant, actor, previous, target, options["reason"])

        verb = "designated as a demo tenant" if target else "undesignated"
        self.stdout.write(self.style.SUCCESS(f"Tenant {tenant.slug} {verb}."))
        self.stdout.write(f"  is_demo: {previous} -> {target}")
        self.stdout.write(f"  reason:  {options['reason']}")

    def _actor(self, username: str, tenant):
        from apps.identity.models import User

        actor = User.objects.filter(username=username).first()
        if actor is None:
            raise CommandError(f"No user {username!r} to attribute this action to.")
        if not (actor.is_superuser or self._has_govern_capability(actor)):
            raise CommandError(
                f"{username!r} lacks the Platform Owner capability required to "
                "designate a demo tenant."
            )
        return actor

    @staticmethod
    def _has_govern_capability(actor) -> bool:
        from apps.platform.demo.safety import PLATFORM_OWNER_CAPABILITY

        try:
            from apps.identity.models import UserRole

            roles = UserRole.all_objects.filter(user=actor).select_related("role")
            return any(
                PLATFORM_OWNER_CAPABILITY in (ur.role.capabilities or []) for ur in roles
            )
        except Exception:
            return False

    def _audit(self, tenant, actor, previous: bool, target: bool, reason: str) -> None:
        from apps.audit.models import AuditEvent

        AuditEvent.all_objects.create(
            tenant=tenant,
            actor=actor,
            action="DEMO_TENANT_DESIGNATED" if target else "DEMO_TENANT_UNDESIGNATED",
            metadata={
                "tenant_id": str(tenant.id),
                "tenant_slug": tenant.slug,
                "tenant_name": tenant.name,
                "is_demo_before": previous,
                "is_demo_after": target,
                "reason": reason,
            },
        )
