"""Offline dispensing eligibility and synchronisation.

When a terminal cannot reach the server it is working from a snapshot. That
snapshot cannot be re-screened, cannot see stock moving elsewhere, and cannot
consult a pharmacist. So the question this module answers is not "can we make
this work offline" but "which supplies are still safe when nobody can check".

The default answer is no. Every permission is granted explicitly and narrowly,
because the failure mode of guessing wrong is a patient receiving medicine that
a current screening would have refused.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.prescription.models import DispensingEpisode

#: Actions a device may perform without a server. Deliberately short.
OFFLINE_ACTION_DISPENSE = "DISPENSE"
OFFLINE_ACTION_PRINT_LABEL = "PRINT_LABEL"
OFFLINE_ACTION_RECORD_COLLECTION = "RECORD_COLLECTION"
OFFLINE_ACTION_ACCEPT_CASH = "ACCEPT_CASH"

ALL_OFFLINE_ACTIONS = frozenset(
    {
        OFFLINE_ACTION_DISPENSE,
        OFFLINE_ACTION_PRINT_LABEL,
        OFFLINE_ACTION_RECORD_COLLECTION,
        OFFLINE_ACTION_ACCEPT_CASH,
    }
)

#: How stale a stock snapshot may be before offline supply is refused. Beyond
#: this the terminal cannot reasonably claim to know what is on the shelf.
MAX_STOCK_SNAPSHOT_AGE = timedelta(hours=12)


@dataclass(frozen=True)
class OfflineEligibility:
    permitted: bool
    #: ONLINE | OFFLINE_ALLOWED | OFFLINE_LIMITED | OFFLINE_BLOCKED
    state: str
    reasons: list[str] = field(default_factory=list)
    permitted_actions: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return not self.permitted


class OfflineDispensingPolicy:
    """Decides what a disconnected terminal may do for one episode."""

    @staticmethod
    def evaluate(
        *,
        episode,
        screening=None,
        stock_snapshot_at=None,
        tenant_allows_offline: bool = True,
        device_authorised: bool = True,
        now=None,
    ) -> OfflineEligibility:
        """Assess one episode for offline supply.

        Returns every reason it is blocked rather than the first, so an operator
        sees the whole picture instead of fixing one problem and discovering
        another.
        """
        now = now or timezone.now()
        reasons: list[str] = []

        if not tenant_allows_offline:
            reasons.append("Offline dispensing is disabled for this tenant.")
        if not device_authorised:
            reasons.append("This device is not authorised for offline dispensing.")

        # Controlled medicines are never dispensed offline. The register, the
        # witness requirement and the custody checks all depend on the server,
        # and a controlled supply that cannot be registered at the time it
        # happens is not one worth making.
        prescription = getattr(episode, "prescription", None)
        if prescription is not None and getattr(prescription, "is_controlled_medicine", False):
            reasons.append("Controlled medicines cannot be dispensed offline.")

        if screening is None:
            reasons.append("No clinical screening is available for this episode.")
        else:
            if getattr(screening, "status", "") != "COMPLETE":
                reasons.append(
                    f"Clinical screening is {getattr(screening, 'status', 'missing')}; "
                    "it must be complete."
                )
            if not getattr(screening, "safe_to_proceed", False):
                reasons.append("Clinical screening does not permit progression.")
            expires_at = getattr(screening, "expires_at", None)
            if expires_at and expires_at <= now:
                reasons.append("The clinical screening has expired.")

        # A payment state the server has not settled cannot be resolved by a
        # disconnected till.
        if episode.payment_state not in DispensingEpisode.PAYMENT_STATES_PERMITTING_SUPPLY:
            reasons.append(
                f"Payment state is {episode.payment_state}; supply is not permitted."
            )

        if stock_snapshot_at is None:
            reasons.append("No stock snapshot is available.")
        elif now - stock_snapshot_at > MAX_STOCK_SNAPSHOT_AGE:
            reasons.append("The stock snapshot is too old to rely on.")

        if reasons:
            return OfflineEligibility(
                permitted=False, state="OFFLINE_BLOCKED", reasons=reasons, permitted_actions=[]
            )

        # Payment is deliberately limited to cash. A provider tender cannot be
        # confirmed without the provider, and recording one offline would be
        # asserting money arrived that nobody has seen.
        actions = [
            OFFLINE_ACTION_DISPENSE,
            OFFLINE_ACTION_PRINT_LABEL,
            OFFLINE_ACTION_RECORD_COLLECTION,
            OFFLINE_ACTION_ACCEPT_CASH,
        ]
        return OfflineEligibility(
            permitted=True,
            state="OFFLINE_ALLOWED",
            reasons=[],
            permitted_actions=actions,
        )


@dataclass(frozen=True)
class SyncOutcome:
    accepted: bool
    #: RECONCILED | DUPLICATE | CONFLICT | REJECTED
    status: str
    message: str = ""
    conflict_code: str = ""


class OfflineSyncService:
    """Applies work a terminal performed while disconnected."""

    @staticmethod
    @transaction.atomic
    def submit_supply(
        *,
        episode,
        actor,
        idempotency_key,
        performed_at,
        context_hash,
        package_verification=None,
    ) -> SyncOutcome:
        """Replay one offline supply.

        Ordering matters here: the checks run before any write, and the whole
        thing is idempotent on the client's key, so a terminal that retries a
        sync it never saw acknowledged cannot supply twice.
        """
        from apps.prescription.models import MedicineSupply
        from apps.prescription.services.clinical_dispensing import MedicineSupplyService

        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "Idempotency key is required."})

        # Replay of an already-applied supply is a success, not a conflict: the
        # device simply never received the acknowledgement.
        existing = MedicineSupply.all_objects.filter(
            tenant_id=episode.tenant_id, idempotency_key=idempotency_key
        ).first()
        if existing:
            return SyncOutcome(
                accepted=True,
                status="DUPLICATE",
                message="This supply was already recorded.",
            )

        # A package that no longer verifies means the device acted on something
        # we cannot vouch for. The record is kept for reconciliation, but it is
        # not silently accepted.
        if package_verification is not None and not package_verification.valid:
            return SyncOutcome(
                accepted=False,
                status="CONFLICT",
                message="The offline clinical package could not be verified at sync time.",
                conflict_code=package_verification.code,
            )

        episode = DispensingEpisode.all_objects.select_for_update().get(
            pk=episode.pk, tenant_id=episode.tenant_id
        )

        # The world may have moved while the device was away: a batch recalled,
        # a prescription amended, an approval revoked. Supply goes through the
        # same authoritative path as an online one, so those checks all apply.
        try:
            MedicineSupplyService.supply(
                episode=episode,
                actor=actor,
                idempotency_key=idempotency_key,
            )
        except ValidationError as exc:
            return SyncOutcome(
                accepted=False,
                status="CONFLICT",
                message=str(exc),
                conflict_code="SERVER_REFUSED_OFFLINE_SUPPLY",
            )

        return SyncOutcome(
            accepted=True,
            status="RECONCILED",
            message=f"Offline supply performed at {performed_at} has been reconciled.",
        )

    @staticmethod
    def classify_conflict(*, outcome: SyncOutcome) -> str:
        """Route a sync outcome to its operational disposition."""
        if outcome.status == "CONFLICT":
            return "REQUIRES_REVIEW"
        if outcome.status == "REJECTED":
            return "REQUIRES_REVIEW"
        return "RESOLVED"
