from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.cds.models import (
    ActiveIngredient,
    ClinicalKnowledgeRule,
)
from apps.cds.offline_package_signing import (
    VerificationResult,
    build_payload,
    sign_payload,
    verify_package_payload,
)
from apps.cds.pos_screening_models import (
    PosClinicalAuditEvent,
    PosClinicalDecision,
    PosClinicalFinding,
    PosClinicalOverride,
    PosClinicalScreening,
    PosOfflineClinicalPackage,
)
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
)
from apps.patients.models import (
    PatientAllergy,
    PatientClinicalSummary,
)
from apps.prescription.models import DispensingLine, PrescriptionItem
from apps.prescription.services.clinical_dispensing import _require_capability
from apps.workflows.service import emit_event


class StaleClinicalContext(ValidationError):
    """Raised when a decision is attempted against a context that has moved on.

    Carries the marker string so API callers and both POS clients can classify
    it without string-matching a prose message.
    """

    def __init__(self, message="The prescription or basket changed after this screening."):
        super().__init__(f"STALE_CLINICAL_CONTEXT: {message}")


def _canonical_quantity(value):
    """Represent an equivalent decimal quantity identically at every POS edge."""
    return format(Decimal(str(value)).normalize(), 'f')


def _require_actor(actor, capability, tenant_id):
    """Every clinical write needs an authorised principal.

    Enforced in the service rather than only at the API boundary, so the same
    rule applies to management commands, background jobs and any future
    integration -- an alternate entry point must not become a way around it.
    """
    if actor is None:
        raise PermissionDenied(f"Capability {capability} is required; no actor supplied.")
    _require_capability(actor, tenant_id, capability)


def _require_current_context(screening, expected_context_hash):
    """Refuse a decision whose context has changed since screening.

    An acknowledgement or override is only meaningful for the basket it was made
    against. Letting one carry across a change is how a patient ends up supplied
    under an approval that was never given for what is in the bag.
    """
    if expected_context_hash is None:
        raise StaleClinicalContext("An expected context hash is required.")
    if not PosClinicalApprovalService.validate_basket_unchanged(
        screening=screening, current_context_hash=expected_context_hash
    ):
        PosClinicalAuditEvent.all_objects.create(
            tenant=screening.tenant,
            screening=screening,
            event_type="CLINICAL_CONTEXT_STALE",
            payload={
                "expected_context_hash": str(expected_context_hash),
                "current_context_hash": screening.context_hash,
            },
        )
        raise StaleClinicalContext()


class PosTransactionContextBuilder:
    @staticmethod
    def build_context(*, tenant, basket_lines, branch_id=None, patient_id=None, prescription_id=None):
        items = []
        ingredient_codes = set()
        for line in basket_lines:
            sku_id = line.get("sku_id")
            clinical_product_id = line.get("clinical_product_id")
            quantity = Decimal(str(line.get("quantity", 0)))
            dose_instructions = line.get("dose_instructions")
            
            clin_prod = None
            if sku_id:
                sku = CommercialSKU.all_objects.filter(tenant=tenant, pk=sku_id).select_related(
                    "manufactured_product__clinical_product"
                ).first()
                if sku and sku.manufactured_product:
                    clin_prod = sku.manufactured_product.clinical_product
            elif clinical_product_id:
                clin_prod = ClinicalMedicinalProduct.all_objects.filter(tenant=tenant, pk=clinical_product_id).first()
                
            ingredients = []
            if clin_prod:
                for comp in clin_prod.ingredients.all():
                    ingredients.append(comp.active_substance.code)
                    ingredient_codes.add(comp.active_substance.code)
            
            items.append({
                "line_id": line.get("line_id"),
                "sku_id": sku_id,
                "clinical_product_id": clin_prod.id if clin_prod else None,
                "quantity": _canonical_quantity(quantity),
                "dose_instructions": dose_instructions,
                "ingredients": ingredients,
                "is_controlled": clin_prod.controlled_classification != "NONE" if clin_prod else False,
                "therapeutic_classifications": [tc.code for tc in clin_prod.therapeutic_classifications.all()] if clin_prod else []
            })
            
        allergies = []
        clinical_summary = None
        if patient_id:
            for al in PatientAllergy.all_objects.filter(tenant=tenant, patient_id=patient_id, is_active=True):
                allergies.append({"code": al.allergen_code, "name": al.allergen_name, "severity": al.severity})
            cs = PatientClinicalSummary.all_objects.filter(tenant=tenant, patient_id=patient_id).first()
            if cs:
                clinical_summary = {
                    "pregnancy_status": cs.pregnancy_status,
                    "lactation_status": cs.lactation_status,
                    "renal_impairment": cs.renal_impairment,
                    "hepatic_impairment": cs.hepatic_impairment,
                }
                
        prescription_items = []
        if prescription_id:
            for pi in PrescriptionItem.all_objects.filter(tenant=tenant, prescription_id=prescription_id):
                prescription_items.append({
                    "item_id": str(pi.id),
                    "medicine_id": str(pi.canonical_medicine_id) if pi.canonical_medicine_id else None
                })

        return {
            "items": items,
            "ingredient_codes": list(ingredient_codes),
            "allergies": allergies,
            "clinical_summary": clinical_summary,
            "medication_history": [],
            "prescription_items": prescription_items,
            "patient_id": str(patient_id) if patient_id else None,
            "prescription_id": str(prescription_id) if prescription_id else None,
            "branch_id": str(branch_id) if branch_id else None,
        }

    @staticmethod
    def compute_context_hash(*, context):
        hashable_data = {
            "items": sorted([{"line_id": i["line_id"], "sku_id": i["sku_id"], "quantity": i["quantity"]} for i in context.get("items", [])], key=lambda x: str(x["line_id"])),
            "patient_id": context.get("patient_id"),
            "prescription_id": context.get("prescription_id"),
            "branch_id": context.get("branch_id"),
            "allergy_codes": sorted([a["code"] for a in context.get("allergies", []) if a["code"]]),
            "clinical_summary": context.get("clinical_summary"),
        }
        json_str = json.dumps(hashable_data, sort_keys=True)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


class PosClinicalScreeningService:
    @staticmethod
    @transaction.atomic
    def evaluate(*, tenant, transaction_id, device_id, register_id='', branch_id=None, patient_id=None, prescription_id=None, dispensing_episode_id='', basket_lines, context_hash=None, cashier=None, offline_state=False):
        context = PosTransactionContextBuilder.build_context(
            tenant=tenant,
            basket_lines=basket_lines,
            branch_id=branch_id,
            patient_id=patient_id,
            prescription_id=prescription_id
        )
        
        if not context_hash:
            context_hash = PosTransactionContextBuilder.compute_context_hash(context=context)
            
        existing = PosClinicalScreening.all_objects.filter(
            tenant=tenant,
            transaction_id=transaction_id,
            context_hash=context_hash,
            status='COMPLETE'
        ).first()
        
        if existing:
            return existing

        screening = PosClinicalScreening.all_objects.create(
            tenant=tenant,
            transaction_id=transaction_id,
            device_id=device_id,
            register_id=register_id,
            branch_id=branch_id,
            patient_id=patient_id,
            prescription_id=prescription_id,
            dispensing_episode_id=dispensing_episode_id,
            context_hash=context_hash,
            cashier=cashier,
            offline_state=offline_state,
            status='PENDING',
            screening_mode=tenant.screening_mode if hasattr(tenant, 'screening_mode') else 'STRICT'
        )

        emit_event(
            tenant_id=str(tenant.id),
            aggregate_type="PosClinicalScreening",
            aggregate_id=str(screening.screening_id),
            event_type="SCREENING_REQUESTED",
            payload={"transaction_id": transaction_id}
        )
        
        PosClinicalAuditEvent.all_objects.create(
            tenant=tenant,
            screening=screening,
            event_type='SCREENING_REQUESTED',
            cashier=cashier,
            payload={"context_hash": context_hash}
        )

        findings = []
        ingredient_codes = context["ingredient_codes"]

        # 1. Drug-Drug Interactions
        rules = ClinicalKnowledgeRule.all_objects.filter(
            tenant=tenant,
            rule_type='DRUG_DRUG',
            is_active=True
        )
        for r in rules:
            if r.primary_code in ingredient_codes and r.interacting_code in ingredient_codes:
                f = PosClinicalFinding.all_objects.create(
                    tenant=tenant,
                    screening=screening,
                    rule=r,
                    rule_version=r.rule_version,
                    category='DRUG_DRUG_INTERACTION',
                    severity=r.severity,
                    title=f"Drug-Drug Interaction: {r.primary_code} and {r.interacting_code}",
                    summary=r.explanation[:255] if r.explanation else f"Interaction between {r.primary_code} and {r.interacting_code}",
                    clinical_explanation=r.explanation,
                    recommendation=r.recommended_action,
                    affected_basket_line_ids=[i['line_id'] for i in context['items']],
                    affected_medicine_ids=[r.primary_code, r.interacting_code],
                    blocking=(r.severity in ['HIGH', 'CRITICAL']),
                    requires_pharmacist=(r.severity in ['MODERATE', 'HIGH', 'CRITICAL']),
                    override_allowed=(r.override_policy != 'PROHIBITED')
                )
                findings.append(f)

        # 2. Allergy Screening
        allergies = context["allergies"]
        for a in allergies:
            code = a["code"]
            if code in ingredient_codes:
                f = PosClinicalFinding.all_objects.create(
                    tenant=tenant,
                    screening=screening,
                    category='DRUG_ALLERGY',
                    severity='CRITICAL',
                    title=f"Allergy Alert: {a.get('name', code)}",
                    summary=f"Patient is allergic to {a.get('name', code)}",
                    patient_context_required=True,
                    blocking=True,
                    requires_pharmacist=True
                )
                findings.append(f)

        # 3. Duplicate Therapy Screening
        for item in context['items']:
            for tc in item.get('therapeutic_classifications', []):
                pass

        blocking_count = sum(1 for f in findings if f.blocking)
        highest_sev = None
        for sev in ['CRITICAL', 'HIGH', 'MODERATE', 'LOW', 'INFORMATION']:
            if any(f.severity == sev for f in findings):
                highest_sev = sev
                break

        screening.status = 'COMPLETE'
        screening.highest_severity = highest_sev
        screening.blocking_count = blocking_count
        screening.requires_pharmacist = any(f.requires_pharmacist for f in findings)
        screening.safe_to_proceed = (blocking_count == 0)
        screening.save()

        emit_event(
            tenant_id=str(tenant.id),
            aggregate_type="PosClinicalScreening",
            aggregate_id=str(screening.screening_id),
            event_type="SCREENING_COMPLETED",
            payload={"safe_to_proceed": screening.safe_to_proceed}
        )
        
        PosClinicalAuditEvent.all_objects.create(
            tenant=tenant,
            screening=screening,
            event_type='SCREENING_COMPLETED',
            cashier=cashier,
            payload={"blocking_count": blocking_count, "safe_to_proceed": screening.safe_to_proceed}
        )
        
        return screening

    @staticmethod
    def get_screening(*, tenant, screening_id):
        return PosClinicalScreening.all_objects.get(tenant=tenant, pk=screening_id)

    @staticmethod
    def acknowledge_finding(*, tenant, finding_id, cashier, expected_context_hash=None):
        finding = PosClinicalFinding.all_objects.get(tenant=tenant, pk=finding_id)
        # Checked before the transaction opens, so a refusal is still audited.
        _require_actor(cashier, "clinical.finding.acknowledge", tenant.id)
        _require_current_context(finding.screening, expected_context_hash)
        return PosClinicalScreeningService._apply_acknowledgement(
            tenant=tenant, finding=finding, cashier=cashier
        )

    @staticmethod
    @transaction.atomic
    def _apply_acknowledgement(*, tenant, finding, cashier):
        # Acknowledgement can only clear an advisory finding. It must never be
        # able to turn a blocking finding into a safe state -- that requires a
        # pharmacist decision or an authorised override.
        if finding.severity in ['INFO', 'LOW'] and not finding.blocking:
            finding.resolution_status = 'ACKNOWLEDGED'
            finding.resolved_by = cashier
            finding.resolved_at = timezone.now()
            finding.save()
            
            PosClinicalAuditEvent.all_objects.create(
                tenant=tenant,
                screening=finding.screening,
                event_type='FINDING_ACKNOWLEDGED',
                cashier=cashier,
                payload={"finding_id": str(finding.id)}
            )
            
            # Recalculate
            screening = finding.screening
            screening.blocking_count = PosClinicalFinding.all_objects.filter(
                screening=screening, 
                blocking=True, 
                resolution_status='OPEN'
            ).count()
            screening.safe_to_proceed = (screening.blocking_count == 0)
            screening.save()
            
        return finding


class PosPharmacistReviewService:
    @staticmethod
    def request_review(*, screening, cashier, expected_context_hash=None):
        _require_actor(cashier, "clinical.pharmacist_review.request", screening.tenant_id)
        _require_current_context(screening, expected_context_hash)
        audit = PosClinicalAuditEvent.all_objects.create(
            tenant=screening.tenant,
            screening=screening,
            event_type='PHARMACIST_REVIEW_REQUESTED',
            cashier=cashier,
            payload={}
        )
        return audit

    @staticmethod
    def submit_decision(*, screening, finding_id, pharmacist, decision, clinical_justification='', conditions='', counselling_notes='', prescriber_contact_ref='', follow_up_actions='', idempotency_key=None, expected_context_hash=None):
        if decision == PosClinicalDecision.Decision.AUTHORIZED_OVERRIDE:
            raise ValidationError(
                'Use the governed override request and approval workflow; direct overrides are not allowed.'
            )
        _require_actor(pharmacist, "clinical.pharmacist_review.decide", screening.tenant_id)
        _require_current_context(screening, expected_context_hash)
        # Separation of duties: whoever rang the basket cannot also clear it.
        if screening.cashier_id and screening.cashier_id == pharmacist.id:
            raise ValidationError("The pharmacist deciding must differ from the cashier.")
        return PosPharmacistReviewService._apply_decision(
            screening=screening,
            finding_id=finding_id,
            pharmacist=pharmacist,
            decision=decision,
            clinical_justification=clinical_justification,
            conditions=conditions,
            counselling_notes=counselling_notes,
            prescriber_contact_ref=prescriber_contact_ref,
            follow_up_actions=follow_up_actions,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    @transaction.atomic
    def _apply_decision(*, screening, finding_id, pharmacist, decision, clinical_justification='', conditions='', counselling_notes='', prescriber_contact_ref='', follow_up_actions='', idempotency_key=None):
        if screening.status != 'COMPLETE':
            raise ValueError("Screening must be COMPLETE.")

        valid_decisions = {choice for choice, _ in PosClinicalDecision.Decision.choices}
        if decision not in valid_decisions:
            raise ValidationError("Unsupported pharmacist review decision.")
        if decision == PosClinicalDecision.Decision.AUTHORIZED_OVERRIDE:
            raise ValidationError(
                'Use the governed override request and approval workflow; direct overrides are not allowed.'
            )
        if not finding_id:
            raise ValidationError("A pharmacist review must identify the finding being decided.")
        if not clinical_justification or not clinical_justification.strip():
            raise ValidationError("Every pharmacist review requires a clinical justification.")
        if decision == PosClinicalDecision.Decision.APPROVE_WITH_CONDITIONS and not conditions.strip():
            raise ValidationError("Approval with conditions requires the conditions to be recorded.")

        if not idempotency_key:
            idempotency_key = f"DEC-{uuid.uuid4().hex}"

        existing = PosClinicalDecision.all_objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if (
                existing.tenant_id == screening.tenant_id
                and existing.screening_id == screening.id
                and str(existing.finding_id) == str(finding_id)
                and existing.decision == decision
            ):
                return existing
            raise ValidationError("This idempotency key was already used for a different clinical decision.")

        finding = PosClinicalFinding.all_objects.get(
            tenant=screening.tenant,
            pk=finding_id,
            screening=screening,
        )
        if finding.resolution_status != PosClinicalFinding.ResolutionStatus.OPEN:
            raise ValidationError("This finding already has a final clinical decision.")

        dec = PosClinicalDecision.all_objects.create(
            tenant=screening.tenant,
            screening=screening,
            finding=finding,
            pharmacist=pharmacist,
            decision=decision,
            clinical_justification=clinical_justification.strip(),
            conditions=conditions.strip(),
            counselling_notes=counselling_notes,
            prescriber_contact_ref=prescriber_contact_ref,
            follow_up_actions=follow_up_actions.strip(),
            context_hash_at_decision=screening.context_hash,
            rule_version_at_decision=finding.rule_version or screening.rule_set_version,
            branch_id=screening.branch_id,
            transaction_id=screening.transaction_id,
            register_id=screening.register_id,
            patient_ref=str(screening.patient_id or ''),
            prescription_ref=str(screening.prescription_id or ''),
            idempotency_key=idempotency_key
        )

        if decision in {
            PosClinicalDecision.Decision.APPROVE,
            PosClinicalDecision.Decision.APPROVE_AS_WRITTEN,
        }:
            finding.resolution_status = PosClinicalFinding.ResolutionStatus.PHARMACIST_REVIEWED
            event_type = 'FINDING_RESOLVED'
        else:
            # A conditioned approval is not complete until its conditions are
            # fulfilled and a new screening proves the changed workflow safe.
            # The same rule applies to correction, clarification, rejection,
            # and alternative decisions.
            finding.resolution_status = PosClinicalFinding.ResolutionStatus.OPEN
            event_type = 'FINDING_RESOLVED'

        if finding.resolution_status == PosClinicalFinding.ResolutionStatus.OPEN:
            finding.resolved_by = None
            finding.resolved_at = None
        else:
            finding.resolved_by = pharmacist
            finding.resolved_at = timezone.now()
        finding.save()

        PosClinicalAuditEvent.all_objects.create(
            tenant=screening.tenant,
            screening=screening,
            finding=finding,
            event_type=event_type,
            pharmacist=pharmacist,
            branch_id=screening.branch_id,
            device_id=screening.device_id,
            register_id=screening.register_id,
            transaction_id=screening.transaction_id,
            patient_ref=str(screening.patient_id or ''),
            prescription_ref=str(screening.prescription_id or ''),
            severity=finding.severity,
            rule_version=finding.rule_version or screening.rule_set_version,
            context_hash=screening.context_hash,
            payload={
                "decision_id": str(dec.id),
                "finding_id": str(finding.id),
                "decision": decision,
                "conditions": dec.conditions,
                "follow_up_actions": dec.follow_up_actions,
            },
        )
        
        screening.blocking_count = PosClinicalFinding.all_objects.filter(
            screening=screening, 
            blocking=True, 
            resolution_status='OPEN'
        ).count()
        screening.safe_to_proceed = (screening.blocking_count == 0)
        screening.save()
        
        return dec


class PosClinicalOverrideService:
    DEFAULT_VALIDITY = timedelta(minutes=30)

    @staticmethod
    def scope_for(*, screening, finding):
        return {
            'tenant_id': str(screening.tenant_id),
            'branch_id': str(screening.branch_id or ''),
            'patient_id': str(screening.patient_id or ''),
            'prescription_id': str(screening.prescription_id or ''),
            'transaction_id': screening.transaction_id,
            'screening_id': str(screening.screening_id),
            'finding_id': str(finding.id),
            'affected_basket_line_ids': list(finding.affected_basket_line_ids),
            'affected_medicine_ids': list(finding.affected_medicine_ids),
            'context_hash': screening.context_hash,
        }

    @staticmethod
    def _refresh_screening(screening):
        screening.blocking_count = PosClinicalFinding.all_objects.filter(
            screening=screening,
            blocking=True,
            resolution_status=PosClinicalFinding.ResolutionStatus.OPEN,
        ).count()
        screening.safe_to_proceed = screening.status == PosClinicalScreening.Status.COMPLETE and screening.blocking_count == 0
        screening.save(update_fields=['blocking_count', 'safe_to_proceed', 'updated_at'])

    @staticmethod
    def _audit(*, override, event_type, actor=None, payload=None):
        screening = override.finding.screening
        PosClinicalAuditEvent.all_objects.create(
            tenant=override.tenant,
            screening=screening,
            finding=override.finding,
            event_type=event_type,
            cashier=actor if event_type == PosClinicalAuditEvent.EventType.OVERRIDE_REQUESTED else None,
            pharmacist=actor if event_type != PosClinicalAuditEvent.EventType.OVERRIDE_REQUESTED else None,
            branch_id=screening.branch_id,
            device_id=screening.device_id,
            register_id=screening.register_id,
            transaction_id=screening.transaction_id,
            patient_ref=str(screening.patient_id or ''),
            prescription_ref=str(screening.prescription_id or ''),
            severity=override.finding.severity,
            rule_version=override.finding.rule_version or screening.rule_set_version,
            context_hash=screening.context_hash,
            payload={'override_id': str(override.id), **(payload or {})},
        )

    @classmethod
    @transaction.atomic
    def request(cls, *, screening, finding_id, requester, override_reason, requested_reason, supporting_notes='', idempotency_key, expected_context_hash):
        _require_actor(requester, 'clinical.override.request', screening.tenant_id)
        _require_current_context(screening, expected_context_hash)
        if screening.status != PosClinicalScreening.Status.COMPLETE:
            raise ValidationError('Only a complete clinical screening may be escalated for override.')
        if screening.expires_at and screening.expires_at <= timezone.now():
            raise ValidationError('The clinical screening has expired and must be repeated.')
        if not requested_reason or not requested_reason.strip():
            raise ValidationError('An override request requires a clinical reason.')
        existing = PosClinicalOverride.all_objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if (
                existing.tenant_id == screening.tenant_id
                and existing.finding.screening_id == screening.id
                and existing.finding_id == finding_id
                and existing.requested_by_id == requester.id
                and existing.override_reason == override_reason
                and existing.requested_reason == requested_reason.strip()
            ):
                return existing
            raise ValidationError('This idempotency key was already used for a different override request.')
        finding = PosClinicalFinding.all_objects.select_for_update().get(
            tenant=screening.tenant,
            screening=screening,
            pk=finding_id,
        )
        if not finding.override_allowed:
            raise ValidationError('This clinical finding cannot be overridden.')
        if finding.resolution_status != PosClinicalFinding.ResolutionStatus.OPEN:
            raise ValidationError('An override can be requested only for an open finding.')
        if PosClinicalOverride.all_objects.filter(
            finding=finding,
            status__in=[
                PosClinicalOverride.Status.REQUESTED,
                PosClinicalOverride.Status.UNDER_REVIEW,
                PosClinicalOverride.Status.APPROVED,
                PosClinicalOverride.Status.APPROVED_WITH_CONDITIONS,
            ],
        ).exists():
            raise ValidationError('An active override request already exists for this finding.')
        override = PosClinicalOverride.all_objects.create(
            tenant=screening.tenant,
            finding=finding,
            requested_by=requester,
            override_reason=override_reason,
            requested_reason=requested_reason.strip(),
            supporting_notes=supporting_notes.strip(),
            context_hash=screening.context_hash,
            rule_version=finding.rule_version or screening.rule_set_version,
            transaction_id=screening.transaction_id,
            device_id=screening.device_id,
            scope=cls.scope_for(screening=screening, finding=finding),
            idempotency_key=idempotency_key,
        )
        cls._audit(override=override, event_type=PosClinicalAuditEvent.EventType.OVERRIDE_REQUESTED, actor=requester)
        return override

    @classmethod
    @transaction.atomic
    def start_review(cls, *, override, pharmacist):
        _require_actor(pharmacist, 'clinical.override.approve', override.tenant_id)
        override = PosClinicalOverride.all_objects.select_for_update().select_related('finding__screening').get(pk=override.pk)
        if override.status == PosClinicalOverride.Status.REQUESTED:
            override.status = PosClinicalOverride.Status.UNDER_REVIEW
            override.save(update_fields=['status', 'updated_at'])
            cls._audit(override=override, event_type=PosClinicalAuditEvent.EventType.PHARMACIST_AUTHENTICATED, actor=pharmacist)
        elif override.status != PosClinicalOverride.Status.UNDER_REVIEW:
            raise ValidationError('Only a requested override may enter review.')
        return override

    @classmethod
    @transaction.atomic
    def approve(cls, *, override, pharmacist, clinical_justification, conditions='', expires_at=None, idempotency_key='', expected_context_hash=None):
        _require_actor(pharmacist, 'clinical.override.approve', override.tenant_id)
        override = PosClinicalOverride.all_objects.select_for_update().select_related('finding__screening').get(pk=override.pk)
        screening = override.finding.screening
        _require_current_context(screening, expected_context_hash)
        approval_key = idempotency_key or f'override-approval:{override.id}'
        existing = PosClinicalDecision.all_objects.filter(idempotency_key=approval_key).first()
        if existing:
            if (
                existing.id == override.decision_id
                and override.status in [
                    PosClinicalOverride.Status.APPROVED,
                    PosClinicalOverride.Status.APPROVED_WITH_CONDITIONS,
                ]
            ):
                return override
            raise ValidationError('This idempotency key was already used for a different override approval.')
        if screening.status != PosClinicalScreening.Status.COMPLETE:
            raise ValidationError('Only a complete clinical screening may be approved for override.')
        if screening.expires_at and screening.expires_at <= timezone.now():
            raise ValidationError('The clinical screening has expired and must be repeated.')
        if override.status not in [PosClinicalOverride.Status.REQUESTED, PosClinicalOverride.Status.UNDER_REVIEW]:
            raise ValidationError('Only a requested override may be approved.')
        if override.requested_by_id == pharmacist.id:
            raise ValidationError('The override approver must differ from the requesting operator.')
        if not clinical_justification or not clinical_justification.strip():
            raise ValidationError('Override approval requires a clinical rationale.')
        if expires_at is None:
            expires_at = timezone.now() + cls.DEFAULT_VALIDITY
        if expires_at <= timezone.now():
            raise ValidationError('Override expiry must be in the future.')
        if screening.expires_at and expires_at > screening.expires_at:
            raise ValidationError('Override expiry cannot outlast its clinical screening.')
        decision = existing or PosClinicalDecision.all_objects.create(
            tenant=override.tenant,
            screening=screening,
            finding=override.finding,
            pharmacist=pharmacist,
            decision=PosClinicalDecision.Decision.AUTHORIZED_OVERRIDE,
            clinical_justification=clinical_justification.strip(),
            conditions=conditions.strip(),
            context_hash_at_decision=screening.context_hash,
            rule_version_at_decision=override.rule_version,
            branch_id=screening.branch_id,
            transaction_id=screening.transaction_id,
            register_id=screening.register_id,
            patient_ref=str(screening.patient_id or ''),
            prescription_ref=str(screening.prescription_id or ''),
            idempotency_key=approval_key,
        )
        override.decision = decision
        override.pharmacist = pharmacist
        override.clinical_justification = clinical_justification.strip()
        override.conditions = conditions.strip()
        override.expires_at = expires_at
        override.approved_at = timezone.now()
        override.status = PosClinicalOverride.Status.APPROVED_WITH_CONDITIONS if override.conditions else PosClinicalOverride.Status.APPROVED
        override.override_capability = 'clinical.override.approve'
        override.save()
        if override.status == PosClinicalOverride.Status.APPROVED:
            override.finding.resolution_status = PosClinicalFinding.ResolutionStatus.OVERRIDDEN
            override.finding.resolved_by = pharmacist
            override.finding.resolved_at = timezone.now()
        else:
            override.finding.resolution_status = PosClinicalFinding.ResolutionStatus.OPEN
            override.finding.resolved_by = None
            override.finding.resolved_at = None
        override.finding.save(update_fields=['resolution_status', 'resolved_by', 'resolved_at', 'updated_at'])
        cls._refresh_screening(screening)
        cls._audit(override=override, event_type=PosClinicalAuditEvent.EventType.OVERRIDE_RECORDED, actor=pharmacist)
        return override

    @classmethod
    @transaction.atomic
    def reject(cls, *, override, pharmacist, rejection_reason):
        _require_actor(pharmacist, 'clinical.override.approve', override.tenant_id)
        override = PosClinicalOverride.all_objects.select_for_update().select_related('finding__screening').get(pk=override.pk)
        if override.status not in [PosClinicalOverride.Status.REQUESTED, PosClinicalOverride.Status.UNDER_REVIEW]:
            raise ValidationError('Only a requested override may be rejected.')
        if not rejection_reason or not rejection_reason.strip():
            raise ValidationError('Override rejection requires a reason.')
        override.status = PosClinicalOverride.Status.REJECTED
        override.rejected_by = pharmacist
        override.rejected_at = timezone.now()
        override.rejection_reason = rejection_reason.strip()
        override.save()
        cls._audit(override=override, event_type=PosClinicalAuditEvent.EventType.OVERRIDE_REJECTED, actor=pharmacist)
        return override

    @classmethod
    @transaction.atomic
    def revoke(cls, *, override, actor, reason):
        _require_actor(actor, 'clinical.override.approve', override.tenant_id)
        override = PosClinicalOverride.all_objects.select_for_update().select_related('finding__screening').get(pk=override.pk)
        if override.status not in [PosClinicalOverride.Status.APPROVED, PosClinicalOverride.Status.APPROVED_WITH_CONDITIONS]:
            raise ValidationError('Only an approved override may be revoked.')
        if not reason or not reason.strip():
            raise ValidationError('Override revocation requires a reason.')
        override.status = PosClinicalOverride.Status.REVOKED
        override.revoked_by = actor
        override.revoked_at = timezone.now()
        override.revocation_reason = reason.strip()
        override.save()
        override.finding.resolution_status = PosClinicalFinding.ResolutionStatus.OPEN
        override.finding.resolved_by = None
        override.finding.resolved_at = None
        override.finding.save(update_fields=['resolution_status', 'resolved_by', 'resolved_at', 'updated_at'])
        cls._refresh_screening(override.finding.screening)
        cls._audit(override=override, event_type=PosClinicalAuditEvent.EventType.OVERRIDE_REVOKED, actor=actor)
        return override

    @classmethod
    @transaction.atomic
    def expire_active(cls, *, screening):
        now = timezone.now()
        overrides = list(PosClinicalOverride.all_objects.select_for_update().filter(
            finding__screening=screening,
            status__in=[PosClinicalOverride.Status.APPROVED, PosClinicalOverride.Status.APPROVED_WITH_CONDITIONS],
            expires_at__lte=now,
        ).select_related('finding'))
        for override in overrides:
            override.status = PosClinicalOverride.Status.EXPIRED
            override.save(update_fields=['status', 'updated_at'])
            override.finding.resolution_status = PosClinicalFinding.ResolutionStatus.OPEN
            override.finding.resolved_by = None
            override.finding.resolved_at = None
            override.finding.save(update_fields=['resolution_status', 'resolved_by', 'resolved_at', 'updated_at'])
            cls._audit(override=override, event_type=PosClinicalAuditEvent.EventType.OVERRIDE_EXPIRED)
        if overrides:
            cls._refresh_screening(screening)
        return overrides

    @classmethod
    @transaction.atomic
    def consume_for_event(cls, *, screening, actor, event):
        cls.expire_active(screening=screening)
        overrides = list(PosClinicalOverride.all_objects.select_for_update().filter(
            finding__screening=screening,
            status=PosClinicalOverride.Status.APPROVED,
        ).select_related('finding'))
        for override in overrides:
            override.status = PosClinicalOverride.Status.CONSUMED
            override.consumed_by = actor
            override.consumed_at = timezone.now()
            override.consumed_event = event
            override.save()
            cls._audit(override=override, event_type=PosClinicalAuditEvent.EventType.OVERRIDE_CONSUMED, actor=actor, payload={'event': event})
        return overrides


class PosClinicalApprovalService:
    @staticmethod
    def is_approved(*, screening):
        return screening.status == 'COMPLETE' and screening.blocking_count == 0

    @staticmethod
    @transaction.atomic
    def invalidate(*, screening, reason='', actor=None):
        screening.status = 'INVALIDATED'
        # An invalidated screening can never be safe to proceed: the approval it
        # carried no longer applies to what is in the basket.
        screening.safe_to_proceed = False
        screening.save()
        PosClinicalAuditEvent.all_objects.create(
            tenant=screening.tenant,
            screening=screening,
            event_type='SCREENING_INVALIDATED',
            payload={"reason": reason, "actor_id": str(actor.id) if actor else ""},
        )
        return screening

    @staticmethod
    def assert_current_and_safe(*, screening, expected_context_hash):
        """Gate used before payment progression and supply.

        Both the freshness of the context and the authoritative safe_to_proceed
        flag are checked; neither alone is sufficient.
        """
        PosClinicalOverrideService.expire_active(screening=screening)
        screening.refresh_from_db()
        _require_current_context(screening, expected_context_hash)
        if screening.status != 'COMPLETE':
            raise ValidationError(f"Clinical screening is {screening.status}; it must be COMPLETE.")
        if not screening.safe_to_proceed:
            raise ValidationError(
                "Clinical screening does not permit progression: unresolved blocking findings."
            )
        return True

    @classmethod
    def assert_dispensing_episode_safe(cls, *, episode):
        """Require a safe CDS result for the exact persisted dispensing basket."""
        lines = list(
            DispensingLine.all_objects.filter(
                tenant_id=episode.tenant_id,
                episode_id=episode.id,
            ).only(
                'id',
                'supplied_sku_id',
                'prescribed_sku_id',
                'quantity_authorized',
                'dosage_label_instructions',
            )
        )
        if not lines:
            raise ValidationError("Clinical screening cannot be verified without dispensing lines.")

        context = PosTransactionContextBuilder.build_context(
            tenant=episode.tenant,
            patient_id=episode.patient_id,
            prescription_id=episode.prescription_id,
            basket_lines=[
                {
                    'line_id': str(line.id),
                    'sku_id': str(line.supplied_sku_id or line.prescribed_sku_id),
                    'quantity': str(line.quantity_authorized),
                    'dose_instructions': line.dosage_label_instructions,
                }
                for line in lines
            ],
        )
        expected_context_hash = PosTransactionContextBuilder.compute_context_hash(context=context)
        screening = (
            PosClinicalScreening.all_objects.filter(
                tenant_id=episode.tenant_id,
                dispensing_episode_id=str(episode.id),
                context_hash=expected_context_hash,
            )
            .order_by('-evaluated_at', '-created_at')
            .first()
        )
        if not screening:
            raise ValidationError(
                "A current POS clinical screening is required before payment or supply."
            )
        if screening.expires_at and screening.expires_at <= timezone.now():
            raise ValidationError("The POS clinical screening has expired and must be repeated.")
        cls.assert_current_and_safe(
            screening=screening,
            expected_context_hash=expected_context_hash,
        )
        return screening

    @staticmethod
    def validate_basket_unchanged(*, screening, current_context_hash):
        return screening.context_hash == current_context_hash


class PosOfflinePackageService:
    """Issue, verify and revoke offline clinical packages.

    Signing lives in apps/cds/offline_package_signing.py. This service owns the
    surrounding policy: what may be issued, what may be handed out, and what
    counts as still valid.
    """

    #: How long a freshly issued package remains usable offline.
    DEFAULT_VALIDITY = timezone.timedelta(days=30)

    @staticmethod
    @transaction.atomic
    def generate_package(
        *,
        tenant,
        generated_by=None,
        branch=None,
        device_id="",
        screening=None,
        context_hash="",
        permitted_actions=None,
    ):
        """Issue a package bound to the context it was created for.

        A package must never be issued over an unsafe clinical state: doing so
        would hand a terminal an offline authorisation for a basket the server
        itself would refuse.
        """
        if screening is not None:
            if not screening.safe_to_proceed:
                raise ValidationError(
                    "Cannot issue an offline package while the screening is not safe to proceed."
                )
            if context_hash and screening.context_hash != context_hash:
                raise ValidationError("STALE_CLINICAL_CONTEXT: screening context has changed.")
            context_hash = context_hash or screening.context_hash

        rules = list(
            ClinicalKnowledgeRule.all_objects.filter(tenant=tenant, is_active=True).values()
        )
        ingredients = list(ActiveIngredient.all_objects.filter(tenant=tenant).values())

        package_id = uuid.uuid4()
        nonce = uuid.uuid4()
        issued_at = timezone.now()
        expires_at = issued_at + PosOfflinePackageService.DEFAULT_VALIDITY
        version = f"PKG-{issued_at.strftime('%Y-%m-%d-%H%M%S')}-{str(package_id)[:8]}"

        payload = build_payload(
            package_id=package_id,
            signing_version=PosOfflineClinicalPackage.SigningVersion.OBJECT_SIGNING_KEY_V1,
            tenant_id=tenant.pk,
            branch_id=branch.pk if branch else None,
            device_id=device_id,
            patient_ref=str(getattr(screening, "patient_id", "") or ""),
            prescription_ref=str(getattr(screening, "prescription_id", "") or ""),
            episode_ref=str(getattr(screening, "dispensing_episode_id", "") or ""),
            screening_ref=str(getattr(screening, "pk", "") or ""),
            context_hash=context_hash,
            findings=rules,
            permitted_actions=permitted_actions or [],
            issued_at=issued_at,
            expires_at=expires_at,
            package_version=version,
            nonce=nonce,
        )
        # The clinical content travels alongside the signed envelope; the
        # envelope is what authenticates it.
        payload["rules"] = rules
        payload["ingredients"] = ingredients

        pkg = PosOfflineClinicalPackage.all_objects.create(
            id=package_id,
            tenant=tenant,
            version=version,
            rule_set_version=version,
            package_data=payload,
            signature=sign_payload(payload),
            signing_version=PosOfflineClinicalPackage.SigningVersion.OBJECT_SIGNING_KEY_V1,
            expires_at=expires_at,
            generated_by=generated_by,
            branch=branch,
            device_id=device_id,
            context_hash=context_hash,
            nonce=nonce,
            is_active=True,
        )
        emit_event(
            tenant_id=str(tenant.pk),
            aggregate_type="PosOfflineClinicalPackage",
            aggregate_id=str(pkg.pk),
            event_type="OfflineClinicalPackageIssued",
            payload={
                "package_id": str(pkg.pk),
                "signing_version": pkg.signing_version,
                "branch_id": str(branch.pk) if branch else "",
                "device_id": device_id,
                "context_hash": context_hash,
                "expires_at": expires_at.isoformat(),
            },
        )
        return pkg

    @staticmethod
    def verify(
        *,
        tenant,
        package_data,
        signature,
        signing_version,
        package=None,
        expected_branch_id=None,
        expected_device_id=None,
        expected_context_hash=None,
    ):
        """Authoritative verification. Returns a typed result; never raises."""
        if package is not None:
            if not package.is_active or package.revoked_at is not None:
                return VerificationResult.failure(
                    "OFFLINE_PACKAGE_REVOKED", "Package has been revoked."
                )
            # The signed payload carries its own expires_at, which is what stops
            # a device extending its own package. The column is checked as well
            # so that an operator can expire a package server-side without
            # needing to re-sign anything.
            if package.expires_at is not None and package.expires_at <= timezone.now():
                return VerificationResult.failure(
                    "OFFLINE_PACKAGE_EXPIRED", "Package has expired."
                )
        return verify_package_payload(
            payload=package_data,
            signature=signature,
            signing_version=signing_version,
            now=timezone.now(),
            expected_tenant_id=tenant.pk,
            expected_branch_id=expected_branch_id,
            expected_device_id=expected_device_id,
            expected_context_hash=expected_context_hash,
        )

    @staticmethod
    def validate_package(*, package_data, signature, tenant, signing_version=None):
        """Backwards-compatible boolean wrapper.

        Retained because existing callers expect a boolean. It now defaults to
        the legacy signing version, which always fails -- a caller that has not
        been updated to pass a real version gets a refusal, not a pass.
        """
        result = PosOfflinePackageService.verify(
            tenant=tenant,
            package_data=package_data,
            signature=signature,
            signing_version=signing_version
            or PosOfflineClinicalPackage.SigningVersion.LEGACY_TENANT_UUID_HMAC,
        )
        return result.valid

    @staticmethod
    def get_valid_package(*, tenant, branch=None, device_id=None, context_hash=None):
        """Return the newest package that actually verifies, or None.

        Deliberately not "the newest package": the previous implementation
        returned whatever was most recent, expired or not.
        """
        candidates = PosOfflineClinicalPackage.all_objects.filter(
            tenant=tenant,
            is_active=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).order_by("-created_at")
        if branch is not None:
            candidates = candidates.filter(branch=branch)
        if device_id:
            candidates = candidates.filter(device_id=device_id)

        for pkg in candidates[:20]:
            result = PosOfflinePackageService.verify(
                tenant=tenant,
                package_data=pkg.package_data,
                signature=pkg.signature,
                signing_version=pkg.signing_version,
                package=pkg,
                expected_context_hash=context_hash,
            )
            if result.valid:
                return pkg
        return None

    @staticmethod
    @transaction.atomic
    def revoke(*, package, reason, actor=None):
        package.is_active = False
        package.revoked_at = timezone.now()
        package.revocation_reason = reason
        package.save(update_fields=["is_active", "revoked_at", "revocation_reason"])
        emit_event(
            tenant_id=str(package.tenant_id),
            aggregate_type="PosOfflineClinicalPackage",
            aggregate_id=str(package.pk),
            event_type="OfflineClinicalPackageRevoked",
            payload={
                "package_id": str(package.pk),
                "reason": reason,
                "actor_id": str(actor.pk) if actor else "",
            },
        )
        return package

    @staticmethod
    def get_current_version(*, tenant):
        pkg = PosOfflinePackageService.get_valid_package(tenant=tenant)
        if not pkg:
            return None
        return {
            "version": pkg.version,
            "signing_version": pkg.signing_version,
            "expires_at": pkg.expires_at,
            "created_at": pkg.created_at,
            "signature": pkg.signature,
        }
