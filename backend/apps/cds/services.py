from __future__ import annotations

from dataclasses import dataclass
from datetime import date

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
from apps.patients.models import PatientAllergy
from apps.prescription.models import PrescriptionItem
from apps.prescription.services.workflow import PrescriptionWorkflowService


@dataclass(frozen=True)
class EvaluationContext:
    tenant_id: str
    patient: object
    prescription: object
    ingredient_codes: tuple[str, ...]
    medicine_by_ingredient: dict[str, object]
    allergies: frozenset[str]


class LocalClinicalKnowledgeProvider(ClinicalKnowledgeProvider):
    def __init__(self, release: ClinicalKnowledgeRelease):
        self.release = release
        self._rules = list(
            ClinicalKnowledgeRule.all_objects.filter(release=release, is_active=True).order_by("rule_id")
        )

    def _findings(self, context: EvaluationContext, rule_type: str):
        for rule in self._rules:
            if rule.rule_type != rule_type or rule.primary_code not in context.ingredient_codes:
                continue
            applies = False
            factor = rule.interacting_code
            if rule_type == "DRUG_DRUG":
                applies = bool(factor and factor in context.ingredient_codes)
            elif rule_type == "ALLERGY":
                applies = rule.primary_code.casefold() in context.allergies or factor.casefold() in context.allergies
            elif rule_type == "DUPLICATE_THERAPY":
                applies = sum(1 for code in context.ingredient_codes if code == rule.primary_code) > 1
            else:
                applies = bool(rule.criteria.get("demo_match", False))
            if applies:
                yield KnowledgeFinding(
                    rule_id=rule.rule_id,
                    rule_version=rule.rule_version,
                    rule_type=rule.rule_type,
                    source=rule.release.source,
                    source_version=rule.release.source_version,
                    effective_date=rule.effective_date,
                    severity=rule.severity,
                    evidence_summary=rule.evidence_summary,
                    explanation=rule.explanation,
                    recommended_action=rule.recommended_action,
                    override_policy=rule.override_policy,
                    affected_medicine_id=context.medicine_by_ingredient.get(rule.primary_code),
                    interacting_factor=factor,
                )

    def check_drug_drug(self, context): return self._findings(context, "DRUG_DRUG")
    def check_allergy(self, context): return self._findings(context, "ALLERGY")
    def check_duplicate_therapy(self, context): return self._findings(context, "DUPLICATE_THERAPY")
    def check_condition_contraindication(self, context): return self._findings(context, "CONDITION")
    def check_age(self, context): return self._findings(context, "AGE")
    def check_pregnancy(self, context): return self._findings(context, "PREGNANCY")
    def check_renal(self, context): return self._findings(context, "RENAL")
    def check_hepatic(self, context): return self._findings(context, "HEPATIC")
    def check_dose(self, context): return self._findings(context, "DOSE")
    def check_duration(self, context): return self._findings(context, "DURATION")


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
    )

    @staticmethod
    def _release(tenant_id):
        now = timezone.now()
        queryset = (
            ClinicalKnowledgeRelease.all_objects.filter(is_active=True, effective_date__lte=date.today())
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        )
        ordering = ("-effective_date", "-created_at")
        return (
            queryset.filter(tenant_id=tenant_id).order_by(*ordering).first()
            or queryset.filter(tenant__isnull=True, is_global=True).order_by(*ordering).first()
        )

    @staticmethod
    def _context(prescription):
        links = list(
            MedicineIngredient.all_objects.filter(
                tenant_id=prescription.tenant_id,
                medicine_id__in=PrescriptionItem.all_objects.filter(
                    tenant_id=prescription.tenant_id,
                    prescription_id=prescription.id,
                ).exclude(canonical_medicine_id=None).values("canonical_medicine_id"),
            ).select_related("ingredient")
        )
        codes = [link.ingredient.code for link in links]
        medicine_by_ingredient = {link.ingredient.code: link.medicine_id for link in links}
        allergies = frozenset(
            value.casefold()
            for row in PatientAllergy.all_objects.filter(
                tenant_id=prescription.tenant_id,
                patient_id=prescription.patient_id,
                is_active=True,
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
            allergies=allergies,
        )

    @classmethod
    @transaction.atomic
    def evaluate(cls, *, prescription, actor=None, provider: ClinicalKnowledgeProvider | None = None):
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
            for method_name in (
                "check_drug_drug", "check_allergy", "check_duplicate_therapy",
                "check_condition_contraindication", "check_age", "check_pregnancy",
                "check_renal", "check_hepatic", "check_dose", "check_duration",
            ):
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
        severities = {finding.severity for finding in findings}
        status = "BLOCK" if "BLOCK" in severities else "WARNING" if "WARNING" in severities else "PASS"
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
                    affected_medicine_id=finding.affected_medicine_id,
                    rule_id=finding.rule_id,
                    rule_version=finding.rule_version,
                    rule_type=finding.rule_type,
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
