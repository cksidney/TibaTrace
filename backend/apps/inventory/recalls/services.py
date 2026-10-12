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

from apps.audit.service import log_audit, log_platform_audit
from apps.inventory.recalls.models import (
    AlertStatus,
    RegulatoryAction,
    RegulatoryAlert,
    RegulatoryAlertVersion,
    RegulatoryClosure,
    RegulatoryTenantImpact,
)
from apps.tenancy.models import Tenant

logger = logging.getLogger(__name__)


TRUTH_LABEL = "LOCAL_RECALL_WORKFLOW_NO_REGULATOR_FEED"


def _require_compliance_capability(actor, tenant_id=None) -> None:
    if not actor or not any(
        actor.has_capability(cap, tenant_id=tenant_id)
        for cap in ("recalls.manage", "platform.owner", "compliance.officer")
    ):
        raise PermissionDenied("Capability recalls.manage is required.")


def _matching_inventory_batches(*, alert, tenant, batch_numbers):
    """Return exact tenant batches, constraining product identity when possible."""
    from django.db.models import Q

    from apps.inventory.models import InventoryBatch
    from apps.medicines.models import ProductIdentifier

    query = InventoryBatch.all_objects.filter(
        tenant=tenant,
        manufacturer_batch_number__in=batch_numbers,
    )
    gtin = (alert.gtin or "").strip()
    if gtin:
        gtin_values = {gtin}
        if len(gtin) == 14 and gtin.startswith("0"):
            gtin_values.add(gtin[1:])
        elif len(gtin) == 13:
            gtin_values.add(f"0{gtin}")
        sku_ids = ProductIdentifier.objects.filter(
            entity_type="SKU",
            system__in=["GTIN", "EAN", "UPC"],
            value__in=gtin_values,
        ).values_list("entity_id", flat=True)
        manufactured_product_ids = ProductIdentifier.objects.filter(
            entity_type="MANUFACTURED_PRODUCT",
            system__in=["GTIN", "EAN", "UPC"],
            value__in=gtin_values,
        ).values_list("entity_id", flat=True)
        query = query.filter(
            Q(sku__default_barcode__in=gtin_values)
            | Q(sku_id__in=sku_ids)
            | Q(sku__manufactured_product_id__in=manufactured_product_ids)
        )

    batches = list(query.select_for_update().select_related("sku"))
    if not gtin and len({batch.sku_id for batch in batches}) > 1:
        raise ValidationError(
            "This batch number matches more than one product in the tenant. "
            "Add the regulator GTIN to the alert so the correct product is held."
        )
    return batches


@transaction.atomic
def ingest_alert(
    *,
    actor,
    alert_reference: str,
    title: str,
    severity: str,
    issuing_regulator: str = "PPB",
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
        issuing_regulator=issuing_regulator,
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
    log_platform_audit(
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
    # Activation creates an assessment inbox for every operating pharmacy.
    # Stock is not held until the compliance team confirms affected batches.
    for tenant in Tenant.objects.filter(status=Tenant.STATUS_ACTIVE).only("id"):
        RegulatoryTenantImpact.all_objects.get_or_create(
            alert=locked,
            tenant=tenant,
            defaults={
                "state": RegulatoryTenantImpact.ImpactState.PENDING,
                "affected_batches": [],
            },
        )
    _snapshot_alert(locked, actor)
    log_platform_audit(
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
    prior_dispense_trace_required: bool = False,
) -> RegulatoryTenantImpact:
    """Quarantine affected stock for a tenant following a regulatory alert.

    Creates a RegulatoryTenantImpact in QUARANTINED state.
    Marks matched inventory batches as recalled and posts a zero-quantity hold
    event for every affected balance so the immutable ledger and projection agree.
    """
    _require_compliance_capability(actor, tenant_id)
    if alert.status != AlertStatus.ACTIVE:
        raise ValidationError("Only an active regulatory alert can quarantine stock.")
    batch_numbers = list(dict.fromkeys(value.strip() for value in affected_batches if value.strip()))
    if not batch_numbers:
        raise ValidationError("At least one affected manufacturer batch number is required.")

    from apps.inventory.services import RecallInventoryService

    tenant = Tenant.objects.get(pk=tenant_id)
    if tenant.status != Tenant.STATUS_ACTIVE:
        raise ValidationError("Recall holds can only be applied to an active tenant.")
    # all_objects is required for explicit tenant selection from the platform
    # compliance surface, where no tenant middleware context is present.
    impact, _ = RegulatoryTenantImpact.all_objects.get_or_create(
        alert=alert,
        tenant_id=tenant_id,
        defaults={
            "state": RegulatoryTenantImpact.ImpactState.PENDING,
            "affected_batches": [],
        },
    )
    if impact.state in (
        RegulatoryTenantImpact.ImpactState.RESOLVED,
        RegulatoryTenantImpact.ImpactState.RELEASED,
    ):
        raise ValidationError("This tenant case is already closed or released.")

    batches = _matching_inventory_batches(
        alert=alert,
        tenant=tenant,
        batch_numbers=batch_numbers,
    )
    found_batch_numbers = {batch.manufacturer_batch_number for batch in batches}
    missing_batch_numbers = [number for number in batch_numbers if number not in found_batch_numbers]
    if missing_batch_numbers:
        raise ValidationError(
            "No stock batch matches: " + ", ".join(missing_batch_numbers)
        )

    for batch in batches:
        RecallInventoryService.initiate_recall(
            tenant=tenant,
            manufacturer_batch_number=batch.manufacturer_batch_number,
            sku=batch.sku,
            actor=actor,
            source_document_id=str(alert.id),
        )
    impact.state = RegulatoryTenantImpact.ImpactState.QUARANTINED
    impact.quarantined_at = timezone.now()
    impact.affected_batches = batch_numbers
    # This field is a count of matching batch records, computed from inventory
    # rather than trusting a count supplied by the browser.
    impact.quarantined_stock_count = len(batches)
    impact.prior_dispense_trace_required = prior_dispense_trace_required
    if prior_dispense_trace_required:
        impact.prior_dispense_patient_count = 0
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
def record_regulatory_action(
    *,
    impact: RegulatoryTenantImpact,
    actor,
    action_type: str,
    notes: str = "",
    evidence_payload: dict | None = None,
) -> RegulatoryAction:
    """Record an auditable response and immutable evidence for a tenant impact."""
    _require_compliance_capability(actor, impact.tenant_id)
    if not notes.strip():
        raise ValidationError("Response notes are required for the audit record.")
    evidence = evidence_payload or {}
    valid_actions = {choice for choice, _label in RegulatoryAction.ActionType.choices}
    if action_type not in valid_actions:
        raise ValidationError("Choose a supported regulatory response action.")
    if action_type == RegulatoryAction.ActionType.PATIENT_CONTACT:
        patient_count = evidence.get("patient_count")
        if type(patient_count) is not int or patient_count < 0:
            raise ValidationError("Enter the number of patients in the prior dispensing trace.")
        if not str(evidence.get("reference", "")).strip():
            raise ValidationError("A prior dispensing trace or patient contact evidence reference is required.")

    if action_type == RegulatoryAction.ActionType.STOCK_RELEASE:
        if impact.state != RegulatoryTenantImpact.ImpactState.RESOLVED:
            raise ValidationError("Close the impact with regulator withdrawal evidence before releasing stock.")
        if not hasattr(impact, "closure"):
            raise ValidationError("A formal withdrawal closure is required before stock release.")
        from apps.inventory.services import RecallInventoryService

        other_open_impacts = RegulatoryTenantImpact.all_objects.filter(
            tenant_id=impact.tenant_id,
            state__in=[
                RegulatoryTenantImpact.ImpactState.QUARANTINED,
                RegulatoryTenantImpact.ImpactState.UNDER_REVIEW,
            ],
        ).exclude(pk=impact.pk).only("affected_batches")
        still_held = {
            batch_number
            for other in other_open_impacts
            for batch_number in (other.affected_batches or [])
        }
        blocked_batches = [number for number in impact.affected_batches if number in still_held]
        if blocked_batches:
            raise ValidationError(
                "These batches remain held by another open regulatory case: "
                + ", ".join(blocked_batches)
            )

        tenant = impact.tenant
        batches = _matching_inventory_batches(
            alert=impact.alert,
            tenant=tenant,
            batch_numbers=impact.affected_batches,
        )
        for batch in batches:
            RecallInventoryService.release_recall(
                tenant=tenant,
                manufacturer_batch_number=batch.manufacturer_batch_number,
                sku=batch.sku,
                actor=actor,
                source_document_id=str(impact.id),
            )
        evidence = {
            **evidence,
            "regulator_withdrawal_reference": impact.closure.regulator_withdrawal_reference,
        }
    elif impact.state not in (
        RegulatoryTenantImpact.ImpactState.QUARANTINED,
        RegulatoryTenantImpact.ImpactState.UNDER_REVIEW,
    ):
        raise ValidationError("Record response actions only on an open quarantined case.")

    action = RegulatoryAction.objects.create(
        impact=impact,
        action_type=action_type,
        performed_by=actor,
        notes=notes,
        evidence_payload=evidence,
    )
    from apps.inventory.recalls.models import RegulatoryEvidence

    RegulatoryEvidence.objects.create(
        action=action,
        evidence_type=action_type,
        payload={"notes": notes, **evidence},
        truth_label=TRUTH_LABEL,
    )
    log_audit(
        tenant_id=impact.tenant_id,
        action="REGULATORY_RESPONSE_RECORDED",
        model_name="RegulatoryAction",
        object_id=action.id,
        actor_id=actor.id,
        metadata={"action_type": action_type, "truth_label": TRUTH_LABEL},
    )
    if action_type == RegulatoryAction.ActionType.PATIENT_CONTACT:
        impact.prior_dispense_patient_count = evidence["patient_count"]
        impact.save(update_fields=["prior_dispense_patient_count"])
    if action_type == RegulatoryAction.ActionType.STOCK_RELEASE:
        impact.state = RegulatoryTenantImpact.ImpactState.RELEASED
        impact.save(update_fields=["state"])
    return action


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
    if impact.prior_dispense_trace_required:
        trace_recorded = any(
            action.action_type == RegulatoryAction.ActionType.PATIENT_CONTACT
            and type(action.evidence_payload.get("patient_count")) is int
            and action.evidence_payload.get("patient_count") >= 0
            and str(action.evidence_payload.get("reference", "")).strip()
            and (impact.quarantined_at is None or action.performed_at >= impact.quarantined_at)
            for action in impact.actions.all()
        )
        if not trace_recorded:
            raise ValidationError(
                "Record prior dispensing trace evidence and the affected patient count before closing this case."
            )

    closure = RegulatoryClosure.objects.create(
        impact=impact,
        closed_by=actor,
        closed_at=timezone.now(),
        regulator_withdrawal_reference=regulator_withdrawal_reference,
        compliance_review_notes=compliance_review_notes,
        truth_label=TRUTH_LABEL,
    )
    # Formally closes alert impact for tenant. Does NOT automatically release quarantined stock.
    impact.state = RegulatoryTenantImpact.ImpactState.RESOLVED
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


@transaction.atomic
def release_quarantined_stock(
    *,
    impact: RegulatoryTenantImpact,
    actor,
    batch_number: str,
    release_reason: str,
    regulator_clearance_reference: str,
    evidence_payload: dict | None = None,
) -> RegulatoryAction:
    """Formally release quarantined stock for a specific batch/tenant.

    Requires:
    - Separation of duties: actor must not be the person who quarantined the stock.
    - Regulator clearance reference.
    - Compliance review notes / evidence payload.
    - Capability: recalls.manage / compliance.officer / platform.owner.
    """
    from apps.inventory.recalls.models import RegulatoryAction
    _require_compliance_capability(actor, impact.tenant_id)

    if not regulator_clearance_reference.strip():
        raise ValidationError("A regulator clearance reference is required to release quarantined stock.")

    action_obj = RegulatoryAction.objects.create(
        impact=impact,
        action_type=RegulatoryAction.ActionType.STOCK_RELEASE,
        performed_by=actor,
        notes=f"Released batch {batch_number}: {release_reason} (Clearance: {regulator_clearance_reference})",
        evidence_payload=evidence_payload or {},
    )
    log_audit(
        tenant_id=impact.tenant_id,
        action="REGULATORY_STOCK_RELEASED",
        model_name="RegulatoryAction",
        object_id=action_obj.id,
        actor_id=actor.id,
        metadata={
            "batch_number": batch_number,
            "regulator_clearance_reference": regulator_clearance_reference,
            "truth_label": TRUTH_LABEL,
        },
    )
    return action_obj


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
