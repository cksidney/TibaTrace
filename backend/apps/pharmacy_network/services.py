"""Onboarding a pharmacy, and moving it through its lifecycle.

Every transition here is guarded, attributed to an actor, recorded as a
`TenantLifecycleEvent` and written to the audit log. Before this module,
suspending a pharmacy wrote a key into a JSON blob -- overwritten by the next
suspension -- recorded nobody, and, as a probe confirmed, did not stop that
pharmacy signing in or reading the API. The status was decorative.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.pharmacy_network.models import PharmacyProfile, TenantLifecycleEvent
from apps.tenancy.models import Tenant

#: The only moves permitted. Anything absent is refused, so a new state cannot
#: quietly become reachable from everywhere by being added to the model.
#:
#: TERMINATED has no outgoing edges on purpose: bringing a pharmacy back is a new
#: tenant, so the terminated one's audit trail is never reopened and rewritten.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    Tenant.STATUS_PROSPECT: frozenset({Tenant.STATUS_ONBOARDING, Tenant.STATUS_TERMINATED}),
    Tenant.STATUS_ONBOARDING: frozenset({Tenant.STATUS_ACTIVE, Tenant.STATUS_TERMINATED}),
    Tenant.STATUS_ACTIVE: frozenset({Tenant.STATUS_SUSPENDED, Tenant.STATUS_TERMINATED}),
    Tenant.STATUS_SUSPENDED: frozenset({Tenant.STATUS_ACTIVE, Tenant.STATUS_TERMINATED}),
    Tenant.STATUS_TERMINATED: frozenset(),
}


def _audit(*, tenant, actor, action, context):
    from apps.audit.models import AuditEvent

    AuditEvent.all_objects.create(
        tenant_id=tenant.pk,
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        model_name="Tenant",
        object_id=str(tenant.pk),
        outcome="SUCCESS",
        metadata=context,
    )


class TenantLifecycleService:
    """Transitions. Nothing else may assign `Tenant.status`."""

    @staticmethod
    @transaction.atomic
    def transition(
        *,
        tenant: Tenant,
        to_state: str,
        actor=None,
        reason: str = "",
        context: dict | None = None,
    ) -> Tenant:
        from_state = tenant.status
        if to_state not in dict(Tenant.STATUS_CHOICES):
            raise ValidationError({"to_state": f"{to_state} is not a tenant state."})

        permitted = ALLOWED_TRANSITIONS.get(from_state, frozenset())
        if to_state not in permitted:
            if from_state == Tenant.STATUS_TERMINATED:
                raise ValidationError(
                    "A terminated pharmacy cannot be reinstated. Register a new "
                    "tenant so the terminated record keeps its history."
                )
            raise ValidationError(
                f"A pharmacy cannot move from {from_state} to {to_state}."
            )

        # Every state that stops a pharmacy trading needs a stated reason. An
        # unexplained suspension is indistinguishable from an accident.
        if to_state in {Tenant.STATUS_SUSPENDED, Tenant.STATUS_TERMINATED} and not (
            reason or ""
        ).strip():
            raise ValidationError(
                {"reason": f"Moving a pharmacy to {to_state} requires a reason."}
            )

        tenant.status = to_state
        tenant.save(update_fields=["status", "updated_at"])

        payload = dict(context or {})
        TenantLifecycleEvent.all_objects.create(
            tenant=tenant,
            from_state=from_state,
            to_state=to_state,
            actor=actor if getattr(actor, "pk", None) else None,
            reason=(reason or "").strip(),
            context=payload,
        )
        _audit(
            tenant=tenant,
            actor=actor,
            action=f"TENANT_{to_state}",
            context={"from_state": from_state, "to_state": to_state, "reason": reason, **payload},
        )
        return tenant

    @staticmethod
    def suspend(*, tenant: Tenant, actor=None, reason: str) -> Tenant:
        return TenantLifecycleService.transition(
            tenant=tenant, to_state=Tenant.STATUS_SUSPENDED, actor=actor, reason=reason
        )

    @staticmethod
    def reinstate(*, tenant: Tenant, actor=None, reason: str = "") -> Tenant:
        """Suspended back to trading.

        Re-checks the licence: a pharmacy is often suspended precisely because
        its licence lapsed, and reinstating without looking would put it back on
        the counter unlicensed.
        """
        profile = getattr(tenant, "pharmacy_profile", None)
        if profile is not None and not profile.licence_is_current:
            raise ValidationError(
                "This pharmacy has no current premises licence, so it cannot be "
                "reinstated. Record a valid licence first."
            )
        return TenantLifecycleService.transition(
            tenant=tenant, to_state=Tenant.STATUS_ACTIVE, actor=actor, reason=reason
        )

    @staticmethod
    @transaction.atomic
    def terminate(*, tenant: Tenant, actor=None, reason: str) -> Tenant:
        tenant = TenantLifecycleService.transition(
            tenant=tenant, to_state=Tenant.STATUS_TERMINATED, actor=actor, reason=reason
        )
        profile = getattr(tenant, "pharmacy_profile", None)
        if profile is not None:
            profile.terminated_at = timezone.now()
            profile.save(update_fields=["terminated_at", "updated_at"])
        return tenant


class PharmacyOnboardingService:
    """Registering a pharmacy and getting it to the point where it can trade."""

    @staticmethod
    @transaction.atomic
    def register_prospect(
        *,
        name: str,
        slug: str,
        legal_name: str,
        country_code: str = "KE",
        time_zone: str = "Africa/Nairobi",
        actor=None,
        **profile_fields,
    ) -> Tenant:
        """Create the pharmacy as a PROSPECT.

        Deliberately not ACTIVE. Creation used to produce a row that was live
        immediately and yet could not do anything -- no organization, no branch,
        nobody who could sign in.
        """
        name = (name or "").strip()
        slug = (slug or "").strip().lower()
        if not name:
            raise ValidationError({"name": "A pharmacy requires a name."})
        if not slug:
            raise ValidationError({"slug": "A pharmacy requires a slug."})
        if Tenant.objects.filter(slug=slug).exists():
            raise ValidationError({"slug": "A pharmacy with this slug already exists."})

        tenant = Tenant.objects.create(
            name=name,
            slug=slug,
            status=Tenant.STATUS_PROSPECT,
            country_code=(country_code or "KE").strip().upper(),
            time_zone=(time_zone or "Africa/Nairobi").strip(),
        )
        profile = PharmacyProfile(
            tenant=tenant, legal_name=(legal_name or name).strip(), **profile_fields
        )
        profile.full_clean()
        profile.save()

        TenantLifecycleEvent.all_objects.create(
            tenant=tenant,
            from_state="",
            to_state=Tenant.STATUS_PROSPECT,
            actor=actor if getattr(actor, "pk", None) else None,
            reason="Registered.",
        )
        _audit(
            tenant=tenant, actor=actor, action="TENANT_REGISTERED",
            context={"slug": slug, "legal_name": profile.legal_name},
        )
        return tenant

    @staticmethod
    @transaction.atomic
    def begin_onboarding(
        *,
        tenant: Tenant,
        organization_name: str,
        organization_code: str,
        branch_name: str,
        branch_code: str,
        actor=None,
    ) -> Tenant:
        """Provision the structure a pharmacy needs before it can trade.

        A tenant row on its own is inert: every operational record hangs off an
        Organization and a Location, so without them there is nothing to dispense
        from. Until now only the demo seed created these, which meant real
        onboarding had no path at all.
        """
        from apps.organizations.models import Location, Organization

        if tenant.status != Tenant.STATUS_PROSPECT:
            raise ValidationError(
                f"Onboarding starts from PROSPECT; this pharmacy is {tenant.status}."
            )
        for field, value in (
            ("organization_name", organization_name),
            ("organization_code", organization_code),
            ("branch_name", branch_name),
            ("branch_code", branch_code),
        ):
            if not (value or "").strip():
                raise ValidationError({field: "This is required to provision a pharmacy."})

        organization = Organization.all_objects.create(
            tenant=tenant, code=organization_code.strip().upper(), name=organization_name.strip()
        )
        branch = Location.all_objects.create(
            tenant=tenant, organization=organization,
            code=branch_code.strip().upper(), name=branch_name.strip(),
        )

        profile = getattr(tenant, "pharmacy_profile", None)
        if profile is not None:
            profile.onboarding_started_at = timezone.now()
            profile.save(update_fields=["onboarding_started_at", "updated_at"])

        return TenantLifecycleService.transition(
            tenant=tenant,
            to_state=Tenant.STATUS_ONBOARDING,
            actor=actor,
            reason="Provisioned.",
            context={
                "organization_code": organization.code,
                "branch_code": branch.code,
            },
        )

    @staticmethod
    @transaction.atomic
    def activate(*, tenant: Tenant, actor=None, reason: str = "") -> Tenant:
        """Onboarding to trading, gated on the premises licence.

        This is the compliance gate. A pharmacy without a current Pharmacy and
        Poisons Board premises licence may not dispense, so it may not be made
        active here -- an absent licence counts as no licence, not as an
        unknown to be waved through.
        """
        from apps.organizations.models import Location

        if tenant.status != Tenant.STATUS_ONBOARDING:
            raise ValidationError(
                f"Activation runs from ONBOARDING; this pharmacy is {tenant.status}."
            )

        profile = getattr(tenant, "pharmacy_profile", None)
        if profile is None or not profile.licence_is_current:
            raise ValidationError(
                "A current PPB premises licence is required before a pharmacy can "
                "trade. Record the licence number and expiry first."
            )
        if not (profile.superintendent_name or "").strip():
            raise ValidationError(
                "A named superintendent pharmacist is required before a pharmacy "
                "can trade."
            )
        if not Location.all_objects.filter(tenant=tenant).exists():
            raise ValidationError(
                "A pharmacy needs at least one branch before it can trade."
            )

        profile.activated_at = timezone.now()
        profile.save(update_fields=["activated_at", "updated_at"])

        return TenantLifecycleService.transition(
            tenant=tenant,
            to_state=Tenant.STATUS_ACTIVE,
            actor=actor,
            reason=reason or "Activated.",
            context={
                "ppb_licence": profile.ppb_premises_licence_number,
                "licence_expiry": profile.ppb_licence_expiry.isoformat(),
                "superintendent": profile.superintendent_name,
            },
        )
