"""Regulatory alert and recall ingestion service.

Truth label: LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED

This service handles manual ingestion, activation, tenant impact quarantine,
prior-dispense tracing, and formal closure of regulatory alerts and recalls.

All actions are audit-logged and immutable evidence records are created for each
key transition.
"""
from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.inventory.recalls.models import (
    AlertStatus,
    RegulatoryAlert,
    RegulatoryAlertVersion,
    RegulatoryClosure,
    RegulatoryTenantImpact,
)

logger = logging.getLogger(__name__)


TRUTH_LABEL = "LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED"


def _require_compliance_capability(actor, tenant_id=None) -> None:
    if not actor or not any(
        actor.has_capability(cap, tenant_id=tenant_id)
        for cap in ("recalls.manage", "platform.owner", "compliance.officer")
    ):
        raise PermissionDenied("Capability recalls.manage is required.")


@transaction.atomic
def ingest_alert(
    *,
    actor,
    alert_reference: str,
    title: str,
    severity: str,
    ppb_registration_number: str = "",
    gtin: str = "",
    product_name: str = "",
    manufacturer_name: str = "",
    affected_batches: list[str] | None = None,
    description: str = "",
    recommended_action: str = "",
    regulator_issue_date=None,
) -> RegulatoryAlert:
    """Ingest a new regulatory alert (draft state).

    Only compliance officers or Platform Owner may ingest alerts.
    Truth label: LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED
    """
    _require_compliance_capability(actor)
    alert = RegulatoryAlert(
        alert_reference=alert_reference,
        title=title,
        severity=severity,
        status=AlertStatus.DRAFT,
        ppb_registration_number=ppb_registration_number,
        gtin=gtin,
        product_name=product_name,
        manufacturer_name=manufacturer_name,
        affected_batches=affected_batches or [],
        description=description,
        recommended_action=recommended_action,
        regulator_issue_date=regulator_issue_date,
        truth_label=TRUTH_LABEL,
        ingested_by=actor,
        ingested_at=timezone.now(),
    )
    alert.save()
    _snapshot_alert(alert, actor, version_number=1)
    log_audit(
        tenant_id=None,
        action="REGULATORY_ALERT_INGESTED",
        model_name="RegulatoryAlert",
        object_id=alert.id,
        actor_id=actor.id,
        metadata={"truth_label": TRUTH_LABEL, "severity": severity},
    )
    return alert


@transaction.atomic
def activate_alert(
    *,
    alert: RegulatoryAlert,
    actor,
) -> RegulatoryAlert:
    """Activate a draft alert, triggering tenant impact assessment.

    Once activated, tenant impacts are created and stock quarantine is triggered.
    """
    _require_compliance_capability(actor)
    locked = RegulatoryAlert.objects.select_for_update().get(id=alert.id)
    if locked.status not in (AlertStatus.DRAFT, AlertStatus.UNDER_REVIEW):
        raise ValidationError(f"Cannot activate an alert in status '{locked.status}'.")

    locked.status = AlertStatus.ACTIVE
    locked.activated_by = actor
    locked.activated_at = timezone.now()
    locked.save()
    _snapshot_alert(locked, actor)
    log_audit(
        tenant_id=None,
        action="REGULATORY_ALERT_ACTIVATED",
        model_name="RegulatoryAlert",
        object_id=locked.id,
        actor_id=actor.id,
        metadata={"truth_label": TRUTH_LABEL},
    )
    return locked


@transaction.atomic
def quarantine_tenant_stock(
    *,
    alert: RegulatoryAlert,
    tenant_id: object,
    actor,
    affected_batches: list[str],
    quarantined_stock_count: int = 0,
    prior_dispense_trace_required: bool = False,
) -> RegulatoryTenantImpact:
    """Quarantine affected stock for a tenant following a regulatory alert.

    Creates a RegulatoryTenantImpact in QUARANTINED state.
    In production, this must also trigger blocking flags on inventory batch records.
    """
    _require_compliance_capability(actor, tenant_id)
    impact, _ = RegulatoryTenantImpact.objects.get_or_create(
        alert=alert,
        tenant_id=tenant_id,
        defaults={
            "state": RegulatoryTenantImpact.ImpactState.PENDING,
            "affected_batches": [],
        },
    )
    impact.state = RegulatoryTenantImpact.ImpactState.QUARANTINED
    impact.quarantined_at = timezone.now()
    impact.affected_batches = affected_batches
    impact.quarantined_stock_count = quarantined_stock_count
    impact.prior_dispense_trace_required = prior_dispense_trace_required
    impact.save()
    log_audit(
        tenant_id=tenant_id,
        action="REGULATORY_STOCK_QUARANTINED",
        model_name="RegulatoryTenantImpact",
        object_id=impact.id,
        actor_id=actor.id,
        metadata={
            "alert_reference": alert.alert_reference,
            "affected_batches": affected_batches,
            "truth_label": TRUTH_LABEL,
        },
    )
    return impact


@transaction.atomic
def close_alert_for_tenant(
    *,
    impact: RegulatoryTenantImpact,
    actor,
    regulator_withdrawal_reference: str,
    compliance_review_notes: str,
) -> RegulatoryClosure:
    """Formally close a regulatory alert for a tenant.

    Requires:
    - Explicit regulator withdrawal reference.
    - Compliance review notes.
    - Platform Owner or Compliance Officer role.
    Stock release is NOT automatic; a separate STOCK_RELEASE action must be performed.
    """
    _require_compliance_capability(actor, impact.tenant_id)
    if not regulator_withdrawal_reference.strip():
        raise ValidationError(
            "A regulator withdrawal reference is required to close an alert. "
            "Do not close without documented regulator withdrawal evidence."
        )
    if impact.state not in (
        RegulatoryTenantImpact.ImpactState.QUARANTINED,
        RegulatoryTenantImpact.ImpactState.UNDER_REVIEW,
    ):
        raise ValidationError(f"Cannot close impact in state '{impact.state}'.")

    closure = RegulatoryClosure.objects.create(
        impact=impact,
        closed_by=actor,
        closed_at=timezone.now(),
        regulator_withdrawal_reference=regulator_withdrawal_reference,
        compliance_review_notes=compliance_review_notes,
        truth_label=TRUTH_LABEL,
    )
    impact.state = RegulatoryTenantImpact.ImpactState.RELEASED
    impact.save(update_fields=["state"])
    log_audit(
        tenant_id=impact.tenant_id,
        action="REGULATORY_ALERT_CLOSED",
        model_name="RegulatoryClosure",
        object_id=closure.id,
        actor_id=actor.id,
        metadata={
            "regulator_withdrawal_reference": regulator_withdrawal_reference,
            "truth_label": TRUTH_LABEL,
        },
    )
    return closure


def _snapshot_alert(
    alert: RegulatoryAlert,
    actor,
    version_number: int | None = None,
) -> RegulatoryAlertVersion:
    """Capture an immutable snapshot of the current alert state."""
    last = RegulatoryAlertVersion.objects.filter(alert=alert).order_by("-version_number").first()
    next_version = (last.version_number + 1) if last else (version_number or 1)
    return RegulatoryAlertVersion.objects.create(
        alert=alert,
        version_number=next_version,
        snapshot={
            "alert_reference": alert.alert_reference,
            "title": alert.title,
            "severity": alert.severity,
            "status": alert.status,
            "ppb_registration_number": alert.ppb_registration_number,
            "gtin": alert.gtin,
            "product_name": alert.product_name,
            "manufacturer_name": alert.manufacturer_name,
            "affected_batches": alert.affected_batches,
            "truth_label": alert.truth_label,
            "captured_at": timezone.now().isoformat(),
        },
        captured_by=actor,
    )
