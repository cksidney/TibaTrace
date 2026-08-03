"""Onboarding for insurers, schemes and plans.

The insurance package could construct claims, check coverage, preauthorise,
submit and reconcile remittance -- but nothing could create an insurer, so the
counterparty every one of those operations depends on was written by hand.

The rule this service holds is the one that matters most here: an insurer is
created in SANDBOX with the deterministic FAKE adapter. Moving it to PRODUCTION
is a separate, named act, because that switch is what turns an internal test
counterparty into one the platform will send real claims to.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.insurance.models import Insurer, InsurerPlan, InsurerScheme

#: Adapters that reach a real counterparty. Selecting one is not something a
#: seeder or an unattended import may do.
LIVE_ADAPTERS = frozenset(
    {
        Insurer.IntegrationAdapter.SHA,
        Insurer.IntegrationAdapter.PRIVATE_REST,
        Insurer.IntegrationAdapter.BATCH_FILE,
    }
)


class InsurerOnboardingService:
    """Creates insurers and their scheme/plan hierarchy."""

    @staticmethod
    @transaction.atomic
    def onboard_insurer(
        *,
        tenant,
        code: str,
        name: str,
        insurer_type: str = Insurer.InsurerType.PRIVATE,
        regulatory_identifier: str = "",
        actor=None,
    ) -> Insurer:
        """Register an insurer in sandbox, using the deterministic fake adapter.

        Idempotent on (tenant, code). The environment and adapter are not
        parameters: an insurer that could be created straight into PRODUCTION
        with a live adapter makes "is this counterparty real?" a question about
        who called the function.
        """
        code = str(code or "").strip()
        name = str(name or "").strip()
        if not code:
            raise ValidationError("An insurer requires a code.")
        if not name:
            raise ValidationError("An insurer requires a name.")
        if insurer_type not in Insurer.InsurerType.values:
            known = ", ".join(Insurer.InsurerType.values)
            raise ValidationError(f"Unknown insurer type {insurer_type!r}. Known: {known}")

        existing = Insurer.all_objects.filter(tenant=tenant, code=code).first()
        if existing is not None:
            return existing

        return Insurer.all_objects.create(
            tenant=tenant,
            code=code,
            name=name,
            insurer_type=insurer_type,
            regulatory_identifier=regulatory_identifier,
            integration_adapter=Insurer.IntegrationAdapter.FAKE,
            environment=Insurer.Environment.SANDBOX,
            status=Insurer.Status.ACTIVE,
        )

    @staticmethod
    @transaction.atomic
    def promote_to_production(
        *, insurer: Insurer, adapter: str, actor, reason: str
    ) -> Insurer:
        """Point an insurer at a real counterparty.

        Deliberately separate from onboarding and deliberately awkward: a named
        actor, a reason, and an adapter that must be one of the live ones. After
        this the platform will send real claims, so it is not a default.
        """
        if actor is None:
            raise PermissionDenied("Promoting an insurer to production requires a named actor.")
        if not str(reason or "").strip():
            raise ValidationError("Promoting an insurer to production requires a reason.")
        if adapter not in LIVE_ADAPTERS:
            known = ", ".join(sorted(LIVE_ADAPTERS))
            raise ValidationError(
                f"{adapter!r} is not a live adapter. Production requires one of: {known}"
            )

        insurer.integration_adapter = adapter
        insurer.environment = Insurer.Environment.PRODUCTION
        insurer.save(update_fields=["integration_adapter", "environment", "updated_at"])
        return insurer

    @staticmethod
    @transaction.atomic
    def suspend_insurer(*, insurer: Insurer, actor, reason: str) -> Insurer:
        """Stop new claims to an insurer without erasing the relationship."""
        if actor is None:
            raise PermissionDenied("Suspending an insurer requires a named actor.")
        if not str(reason or "").strip():
            raise ValidationError("Suspending an insurer requires a reason.")

        insurer.status = Insurer.Status.SUSPENDED
        insurer.save(update_fields=["status", "updated_at"])
        return insurer

    @staticmethod
    @transaction.atomic
    def add_scheme(
        *, insurer: Insurer, code: str, name: str, description: str = "", actor=None
    ) -> InsurerScheme:
        """Add a scheme under an insurer. Idempotent on (tenant, insurer, code)."""
        code = str(code or "").strip()
        name = str(name or "").strip()
        if not code:
            raise ValidationError("A scheme requires a code.")
        if not name:
            raise ValidationError("A scheme requires a name.")

        existing = InsurerScheme.all_objects.filter(
            tenant=insurer.tenant, insurer=insurer, code=code
        ).first()
        if existing is not None:
            return existing

        return InsurerScheme.all_objects.create(
            tenant=insurer.tenant,
            insurer=insurer,
            code=code,
            name=name,
            description=description,
            status="ACTIVE",
        )

    @staticmethod
    @transaction.atomic
    def add_plan(
        *,
        scheme: InsurerScheme,
        code: str,
        name: str,
        plan_class: str = "STANDARD",
        actor=None,
    ) -> InsurerPlan:
        """Add a plan under a scheme. Idempotent on (tenant, scheme, code)."""
        code = str(code or "").strip()
        name = str(name or "").strip()
        if not code:
            raise ValidationError("A plan requires a code.")
        if not name:
            raise ValidationError("A plan requires a name.")

        existing = InsurerPlan.all_objects.filter(
            tenant=scheme.tenant, scheme=scheme, code=code
        ).first()
        if existing is not None:
            return existing

        return InsurerPlan.all_objects.create(
            tenant=scheme.tenant,
            scheme=scheme,
            code=code,
            name=name,
            plan_class=plan_class,
            status="ACTIVE",
        )
