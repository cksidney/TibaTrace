from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.cds.models import (
    ClinicalEvaluation,
    ClinicalFinding,
    ClinicalKnowledgeRelease,
    ClinicalKnowledgeRule,
    MedicineIngredient,
)
from apps.cds.providers import ClinicalKnowledgeProvider, KnowledgeFinding
from apps.patients.models import PatientAllergy, PatientClinicalSummary
from apps.prescription.models import PrescriptionItem
from apps.prescription.services.workflow import PrescriptionWorkflowService


@dataclass(frozen=True)
class EvaluationContext:
    tenant_id: str
    patient: object
    prescription: object
    ingredient_codes: tuple[str, ...]
    medicine_by_ingredient: dict[str, object]
    item_by_ingredient: dict[str, object]
    allergies: frozenset[str]
    items: tuple[object, ...]
    clinical_summary: object | None


class LocalClinicalKnowledgeProvider(ClinicalKnowledgeProvider):
    RULE_TYPE_ALIASES = {
        "DRUG_DRUG": {"DRUG_DRUG", "DRUG_DRUG_INTERACTION"},
        "ALLERGY": {"ALLERGY"},
        "DUPLICATE_THERAPY": {
            "DUPLICATE_THERAPY",
            "THERAPEUTIC_DUPLICATION",
        },
        "CONDITION": {"CONDITION", "CONTRAINDICATION"},
        "AGE": {"AGE", "AGE_RESTRICTION"},
        "PREGNANCY": {"PREGNANCY", "PREGNANCY_WARNING"},
        "RENAL": {"RENAL", "RENAL_IMPAIRMENT"},
        "HEPATIC": {"HEPATIC", "HEPATIC_IMPAIRMENT"},
        "DOSE": {
            "DOSE",
            "DOSE_TOO_HIGH",
            "DOSE_TOO_LOW",
            "MAXIMUM_DAILY_DOSE",
        },
        "DURATION": {
            "DURATION",
            "DURATION_TOO_LONG",
            "DURATION_TOO_SHORT",
        },
        "FREQUENCY": {"FREQUENCY_TOO_HIGH", "FREQUENCY_TOO_LOW"},
        "WEIGHT": {"WEIGHT_BASED_DOSE"},
        "LACTATION": {"LACTATION_WARNING"},
        "CONTROLLED": {"CONTROLLED_MEDICINE_RULE"},
        "REPEAT": {"EARLY_REPEAT", "LATE_REPEAT"},
        "FORMULARY": {"FORMULARY_RESTRICTION"},
    }

    def __init__(self, release: ClinicalKnowledgeRelease):
        self.release = release
        self._rules = list(
            ClinicalKnowledgeRule.all_objects.filter(
                release=release,
                is_active=True,
            ).order_by("rule_id")
        )

    @staticmethod
    def _age_years(patient):
        if not patient.date_of_birth:
            return None
        today = timezone.localdate()
        return today.year - patient.date_of_birth.year - (
            (today.month, today.day)
            < (patient.date_of_birth.month, patient.date_of_birth.day)
        )

    @staticmethod
    def _affected_item(context, primary_code):
        item_id = context.item_by_ingredient.get(primary_code)
        return next((item for item in context.items if item.id == item_id), None)

    def _applies(self, *, context, rule, check_type, affected_item):
        criteria = rule.criteria or {}
        factor = rule.interacting_code
        if check_type == "DRUG_DRUG":
            return bool(factor and factor in context.ingredient_codes), rule.rule_type
        if check_type == "ALLERGY":
            return (
                rule.primary_code.casefold() in context.allergies
                or factor.casefold() in context.allergies
            ), rule.rule_type
        if check_type == "DUPLICATE_THERAPY":
            return (
                sum(
                    1
                    for code in context.ingredient_codes
                    if code == rule.primary_code
                )
                > 1
            ), rule.rule_type
        if check_type == "DOSE" and affected_item:
            daily_dose = Decimal(affected_item.dose_amount or 0) * Decimal(
                affected_item.frequency_per_day or 0
            )
            maximum = criteria.get("maximum_daily_dose")
            minimum = criteria.get("minimum_daily_dose")
            return bool(
                (maximum is not None and daily_dose > Decimal(str(maximum)))
                or (minimum is not None and daily_dose < Decimal(str(minimum)))
            ), rule.rule_type
        if check_type == "FREQUENCY" and affected_item:
            frequency = Decimal(affected_item.frequency_per_day or 0)
            maximum = criteria.get("maximum_frequency_per_day")
            minimum = criteria.get("minimum_frequency_per_day")
            return bool(
                (maximum is not None and frequency > Decimal(str(maximum)))
                or (minimum is not None and frequency < Decimal(str(minimum)))
            ), rule.rule_type
        if check_type == "DURATION" and affected_item:
            duration = affected_item.duration_days
            maximum = criteria.get("maximum_duration_days")
            minimum = criteria.get("minimum_duration_days")
            return bool(
                duration is not None
                and (
                    (maximum is not None and duration > int(maximum))
                    or (minimum is not None and duration < int(minimum))
                )
            ), rule.rule_type
        if check_type == "AGE":
            age = self._age_years(context.patient)
            if age is None and criteria.get("requires_age"):
                return True, "INSUFFICIENT_DATA"
            return bool(
                age is not None
                and (
                    (
                        criteria.get("minimum_age") is not None
                        and age < int(criteria["minimum_age"])
                    )
                    or (
                        criteria.get("maximum_age") is not None
                        and age > int(criteria["maximum_age"])
                    )
                )
            ), rule.rule_type
        if check_type == "WEIGHT":
            weight = (
                context.clinical_summary.weight_kg
                if context.clinical_summary
                else None
            )
            if weight is None and criteria.get("requires_weight"):
                return True, "INSUFFICIENT_DATA"
            return bool(criteria.get("demo_match", False)), rule.rule_type
        if check_type == "PREGNANCY":
            status = (
                context.clinical_summary.pregnancy_status
                if context.clinical_summary
                else "NOT_RECORDED"
            )
            if status == "NOT_RECORDED" and criteria.get(
                "requires_pregnancy_status"
            ):
                return True, "INSUFFICIENT_DATA"
            return status in set(
                criteria.get("pregnancy_statuses", ["PREGNANT"])
            ), rule.rule_type
        if check_type == "LACTATION":
            status = (
                context.clinical_summary.lactation_status
                if context.clinical_summary
                else "NOT_RECORDED"
            )
            if status == "NOT_RECORDED" and criteria.get(
                "requires_lactation_status"
            ):
                return True, "INSUFFICIENT_DATA"
            return status in set(
                criteria.get("lactation_statuses", ["LACTATING"])
            ), rule.rule_type
        if check_type == "RENAL":
            status = (
                context.clinical_summary.renal_impairment
                if context.clinical_summary
                else "NOT_RECORDED"
            )
            if status == "NOT_RECORDED" and criteria.get("requires_renal_status"):
                return True, "INSUFFICIENT_DATA"
            return status in set(
                criteria.get("renal_states", ["IMPAIRED"])
            ), rule.rule_type
        if check_type == "HEPATIC":
            status = (
                context.clinical_summary.hepatic_impairment
                if context.clinical_summary
                else "NOT_RECORDED"
            )
            if status == "NOT_RECORDED" and criteria.get(
                "requires_hepatic_status"
            ):
                return True, "INSUFFICIENT_DATA"
            return status in set(
                criteria.get("hepatic_states", ["IMPAIRED"])
            ), rule.rule_type
        if check_type == "CONTROLLED":
            return bool(
                context.prescription.is_controlled_medicine
                or (affected_item and affected_item.is_controlled)
            ), rule.rule_type
        if check_type == "REPEAT" and affected_item:
            today = timezone.localdate()
            return bool(
                (
                    rule.rule_type == "EARLY_REPEAT"
                    and affected_item.earliest_refill_date
                    and today < affected_item.earliest_refill_date
                )
                or (
                    rule.rule_type == "LATE_REPEAT"
                    and affected_item.latest_refill_date
                    and today > affected_item.latest_refill_date
                )
            ), rule.rule_type
        return bool(criteria.get("demo_match", False)), rule.rule_type

    def _findings(self, context: EvaluationContext, check_type: str):
        accepted_types = self.RULE_TYPE_ALIASES.get(check_type, {check_type})
        for rule in self._rules:
            if rule.rule_type not in accepted_types:
                continue
            if rule.primary_code and rule.primary_code not in context.ingredient_codes:
                continue
            affected_item = self._affected_item(context, rule.primary_code)
            applies, finding_type = self._applies(
                context=context,
                rule=rule,
                check_type=check_type,
                affected_item=affected_item,
            )
            if applies:
                yield KnowledgeFinding(
                    rule_id=rule.rule_id,
                    rule_version=rule.rule_version,
                    rule_type=finding_type,
                    source=rule.release.source,
                    source_version=rule.release.source_version,
                    effective_date=rule.effective_date,
                    severity=rule.severity,
                    evidence_summary=rule.evidence_summary,
                    explanation=rule.explanation,
                    recommended_action=rule.recommended_action,
                    override_policy=rule.override_policy,
                    affected_medicine_id=context.medicine_by_ingredient.get(
                        rule.primary_code
                    ),
                    interacting_factor=rule.interacting_code,
                    prescription_item_id=context.item_by_ingredient.get(
                        rule.primary_code
                    ),
                )

    def check_drug_drug(self, context):
        return self._findings(context, "DRUG_DRUG")

    def check_allergy(self, context):
        return self._findings(context, "ALLERGY")

    def check_duplicate_therapy(self, context):
        return self._findings(context, "DUPLICATE_THERAPY")

    def check_condition_contraindication(self, context):
        return self._findings(context, "CONDITION")

    def check_age(self, context):
        return self._findings(context, "AGE")

    def check_pregnancy(self, context):
        return self._findings(context, "PREGNANCY")

    def check_renal(self, context):
        return self._findings(context, "RENAL")

    def check_hepatic(self, context):
        return self._findings(context, "HEPATIC")

    def check_dose(self, context):
        return self._findings(context, "DOSE")

    def check_duration(self, context):
        return self._findings(context, "DURATION")

    def check_frequency(self, context):
        return self._findings(context, "FREQUENCY")

    def check_weight(self, context):
        return self._findings(context, "WEIGHT")

    def check_lactation(self, context):
        return self._findings(context, "LACTATION")

    def check_controlled_medicine(self, context):
        return self._findings(context, "CONTROLLED")

    def check_repeat_interval(self, context):
        return self._findings(context, "REPEAT")

    def check_formulary(self, context):
        return self._findings(context, "FORMULARY")


class ClinicalDecisionSupportService:
    CHECKS = (
        "check_drug_drug",
        "check_allergy",
        "check_duplicate_therapy",
        "check_condition_contraindication",
        "check_age",
        "check_pregnancy",
        "check_renal",
        "check_hepatic",
        "check_dose",
        "check_duration",
        "check_frequency",
        "check_weight",
        "check_lactation",
        "check_controlled_medicine",
        "check_repeat_interval",
        "check_formulary",
    )

    @staticmethod
    def _release(tenant_id):
        now = timezone.now()
        queryset = ClinicalKnowledgeRelease.all_objects.filter(
            is_active=True,
            effective_date__lte=date.today(),
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        ordering = ("-effective_date", "-created_at")
        return (
            queryset.filter(tenant_id=tenant_id).order_by(*ordering).first()
            or queryset.filter(tenant__isnull=True, is_global=True)
            .order_by(*ordering)
            .first()
        )

    @staticmethod
    def _context(prescription):
        items = tuple(
            PrescriptionItem.all_objects.filter(
                tenant_id=prescription.tenant_id,
                prescription_id=prescription.id,
            )
        )
        links = list(
            MedicineIngredient.all_objects.filter(
                tenant_id=prescription.tenant_id,
                medicine_id__in=[
                    item.canonical_medicine_id
                    for item in items
                    if item.canonical_medicine_id
                ],
            ).select_related("ingredient")
        )
        links_by_medicine = {}
        for link in links:
            links_by_medicine.setdefault(link.medicine_id, []).append(link)
        codes = []
        medicine_by_ingredient = {}
        item_by_ingredient = {}
        for item in items:
            for link in links_by_medicine.get(item.canonical_medicine_id, []):
                code = link.ingredient.code
                codes.append(code)
                medicine_by_ingredient.setdefault(code, link.medicine_id)
                item_by_ingredient.setdefault(code, item.id)
        allergies = frozenset(
            value.casefold()
            for row in PatientAllergy.all_objects.filter(
                tenant_id=prescription.tenant_id,
                patient_id=prescription.patient_id,
                is_active=True,
                status__in=["SUSPECTED", "CONFIRMED"],
            )
            for value in (row.allergen_code, row.allergen_name)
            if value
        )
        return EvaluationContext(
            tenant_id=str(prescription.tenant_id),
            patient=prescription.patient,
            prescription=prescription,
            ingredient_codes=tuple(codes),
            medicine_by_ingredient=medicine_by_ingredient,
            item_by_ingredient=item_by_ingredient,
            allergies=allergies,
            items=items,
            clinical_summary=PatientClinicalSummary.all_objects.filter(
                tenant_id=prescription.tenant_id,
                patient_id=prescription.patient_id,
            ).first(),
        )

    @classmethod
    @transaction.atomic
    def evaluate(
        cls,
        *,
        prescription,
        actor=None,
        provider: ClinicalKnowledgeProvider | None = None,
    ):
        release = cls._release(prescription.tenant_id)
        context_hash = PrescriptionWorkflowService.context_hash(prescription)
        if not release:
            return ClinicalEvaluation.all_objects.create(
                tenant_id=prescription.tenant_id,
                patient=prescription.patient,
                prescription=prescription,
                status="KNOWLEDGE_UNAVAILABLE",
                context_hash=context_hash,
                evaluated_by=actor,
                error_code="NO_ACTIVE_KNOWLEDGE_RELEASE",
                error_detail="No active, in-date clinical knowledge release is available.",
            )
        provider = provider or LocalClinicalKnowledgeProvider(release)
        context = cls._context(prescription)
        try:
            findings = []
            for method_name in cls.CHECKS:
                findings.extend(list(getattr(provider, method_name)(context)))
        except Exception:
            return ClinicalEvaluation.all_objects.create(
                tenant_id=prescription.tenant_id,
                patient=prescription.patient,
                prescription=prescription,
                knowledge_release=release,
                status="ERROR",
                context_hash=context_hash,
                evaluated_by=actor,
                error_code="PROVIDER_FAILURE",
                error_detail="Clinical knowledge provider evaluation failed.",
            )
        deduplicated = {}
        for finding in findings:
            key = (
                finding.rule_id,
                finding.rule_version,
                finding.prescription_item_id,
                finding.interacting_factor,
            )
            deduplicated[key] = finding
        findings = list(deduplicated.values())
        severities = {finding.severity for finding in findings}
        status = (
            "BLOCK"
            if severities.intersection({"BLOCK", "CRITICAL"})
            else "WARNING"
            if severities.intersection({"WARNING", "LOW", "MODERATE", "HIGH"})
            else "PASS"
        )
        evaluation = ClinicalEvaluation.all_objects.create(
            tenant_id=prescription.tenant_id,
            patient=prescription.patient,
            prescription=prescription,
            knowledge_release=release,
            status=status,
            context_hash=context_hash,
            evaluated_by=actor,
        )
        ClinicalFinding.all_objects.bulk_create(
            [
                ClinicalFinding(
                    tenant_id=prescription.tenant_id,
                    evaluation=evaluation,
                    patient=prescription.patient,
                    prescription=prescription,
                    prescription_item_id=finding.prescription_item_id,
                    affected_medicine_id=finding.affected_medicine_id,
                    rule_id=finding.rule_id,
                    rule_version=finding.rule_version,
                    rule_type=finding.rule_type,
                    clinical_category=finding.rule_type,
                    source=finding.source,
                    source_version=finding.source_version,
                    effective_date=finding.effective_date,
                    severity=finding.severity,
                    evidence_summary=finding.evidence_summary,
                    explanation=finding.explanation,
                    recommended_action=finding.recommended_action,
                    override_policy=finding.override_policy,
                    interacting_factor=finding.interacting_factor,
                )
                for finding in findings
            ]
        )
        return evaluation
