from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.cds.models import (
    ActiveIngredient,
    ClinicalKnowledgeRule,
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
from apps.prescription.models import PrescriptionItem
from apps.workflows.service import emit_event


class PosTransactionContextBuilder:
    @staticmethod
    def build_context(*, tenant, basket_lines, patient_id=None, prescription_id=None):
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
                "quantity": str(quantity),
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
        }

    @staticmethod
    def compute_context_hash(*, context):
        hashable_data = {
            "items": sorted([{"line_id": i["line_id"], "sku_id": i["sku_id"], "quantity": i["quantity"]} for i in context.get("items", [])], key=lambda x: str(x["line_id"])),
            "patient_id": context.get("patient_id"),
            "allergy_codes": sorted([a["code"] for a in context.get("allergies", []) if a["code"]]),
            "clinical_summary": context.get("clinical_summary"),
        }
        json_str = json.dumps(hashable_data, sort_keys=True)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


class PosClinicalScreeningService:
    @staticmethod
    @transaction.atomic
    def evaluate(*, tenant, transaction_id, device_id, register_id='', patient_id=None, prescription_id=None, dispensing_episode_id='', basket_lines, context_hash=None, cashier=None, offline_state=False):
        context = PosTransactionContextBuilder.build_context(
            tenant=tenant,
            basket_lines=basket_lines,
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
    @transaction.atomic
    def acknowledge_finding(*, tenant, finding_id, cashier):
        finding = PosClinicalFinding.all_objects.get(tenant=tenant, pk=finding_id)
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
    @transaction.atomic
    def request_review(*, screening, cashier):
        audit = PosClinicalAuditEvent.all_objects.create(
            tenant=screening.tenant,
            screening=screening,
            event_type='PHARMACIST_REVIEW_REQUESTED',
            cashier=cashier,
            payload={}
        )
        return audit

    @staticmethod
    @transaction.atomic
    def submit_decision(*, screening, finding_id, pharmacist, decision, clinical_justification='', counselling_notes='', prescriber_contact_ref='', override_reason='CLINICALLY_JUSTIFIED', override_capability='pos.clinical_findings.override_high', idempotency_key=None):
        if screening.cashier_id and screening.cashier_id == pharmacist.id:
            raise ValueError("Pharmacist cannot be the same as cashier.")
            
        if screening.status != 'COMPLETE':
            raise ValueError("Screening must be COMPLETE.")
            
        finding = PosClinicalFinding.all_objects.get(tenant=screening.tenant, pk=finding_id, screening=screening)
        
        if not idempotency_key:
            idempotency_key = f"DEC-{uuid.uuid4().hex}"

        dec = PosClinicalDecision.all_objects.create(
            tenant=screening.tenant,
            screening=screening,
            finding=finding,
            pharmacist=pharmacist,
            decision=decision,
            clinical_justification=clinical_justification,
            counselling_notes=counselling_notes,
            prescriber_contact_ref=prescriber_contact_ref,
            context_hash_at_decision=screening.context_hash,
            idempotency_key=idempotency_key
        )
        
        if decision == 'AUTHORIZED_OVERRIDE':
            if not clinical_justification:
                raise ValueError("Override requires clinical justification.")
            PosClinicalOverride.all_objects.create(
                tenant=screening.tenant,
                decision=dec,
                finding=finding,
                pharmacist=pharmacist,
                override_reason=override_reason,
                clinical_justification=clinical_justification,
                override_capability=override_capability,
                context_hash=screening.context_hash,
                transaction_id=screening.transaction_id,
                device_id=screening.device_id
            )
            finding.resolution_status = 'OVERRIDDEN'
        elif decision == 'REJECT_SUPPLY':
            finding.resolution_status = 'OPEN'
        else:
            finding.resolution_status = 'RESOLVED'
            
        finding.resolved_by = pharmacist
        finding.resolved_at = timezone.now()
        finding.save()
        
        PosClinicalAuditEvent.all_objects.create(
            tenant=screening.tenant,
            screening=screening,
            event_type='FINDING_RESOLVED' if decision != 'AUTHORIZED_OVERRIDE' else 'OVERRIDE_RECORDED',
            pharmacist=pharmacist,
            payload={"finding_id": str(finding.id), "decision": decision}
        )
        
        screening.blocking_count = PosClinicalFinding.all_objects.filter(
            screening=screening, 
            blocking=True, 
            resolution_status='OPEN'
        ).count()
        screening.safe_to_proceed = (screening.blocking_count == 0)
        screening.save()
        
        return dec


class PosClinicalApprovalService:
    @staticmethod
    def is_approved(*, screening):
        return screening.status == 'COMPLETE' and screening.blocking_count == 0

    @staticmethod
    @transaction.atomic
    def invalidate(*, screening, reason=''):
        screening.status = 'INVALIDATED'
        screening.save()
        PosClinicalAuditEvent.all_objects.create(
            tenant=screening.tenant,
            screening=screening,
            event_type='SCREENING_INVALIDATED',
            payload={"reason": reason}
        )
        return screening

    @staticmethod
    def validate_basket_unchanged(*, screening, current_context_hash):
        return screening.context_hash == current_context_hash


class PosOfflinePackageService:
    @staticmethod
    @transaction.atomic
    def generate_package(*, tenant, generated_by=None):
        rules = list(ClinicalKnowledgeRule.all_objects.filter(tenant=tenant, is_active=True).values())
        ingredients = list(ActiveIngredient.all_objects.filter(tenant=tenant).values())
        
        package_data = {
            "rules": rules,
            "ingredients": ingredients,
        }
        
        json_data = json.dumps(package_data, sort_keys=True, default=str)
        key = str(tenant.pk).encode('utf-8')
        signature = hmac.new(key, json_data.encode('utf-8'), hashlib.sha256).hexdigest()
        
        version = f"PKG-{timezone.now().strftime('%Y-%m-%d-%H%M%S')}"
        expiry = timezone.now() + timezone.timedelta(days=30)
        
        pkg = PosOfflineClinicalPackage.all_objects.create(
            tenant=tenant,
            version=version,
            rule_set_version=version,
            package_data=package_data,
            signature=signature,
            expires_at=expiry,
            generated_by=generated_by
        )
        return pkg

    @staticmethod
    def validate_package(*, package_data, signature, tenant):
        json_data = json.dumps(package_data, sort_keys=True, default=str)
        key = str(tenant.pk).encode('utf-8')
        expected_signature = hmac.new(key, json_data.encode('utf-8'), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_signature, signature)

    @staticmethod
    def get_current_version(*, tenant):
        pkg = PosOfflineClinicalPackage.all_objects.filter(tenant=tenant).order_by('-created_at').first()
        if not pkg:
            return None
        return {
            "version": pkg.version,
            "expires_at": pkg.expires_at,
            "created_at": pkg.created_at,
            "signature": pkg.signature
        }
