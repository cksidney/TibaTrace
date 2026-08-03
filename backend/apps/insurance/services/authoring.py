"""Authoring insurance benefits, coverage and membership.

`CoverageService` can read coverage, match a member and verify eligibility --
but nothing could create any of it, so every member, benefit, limit and
exclusion in the repository was written straight to the ORM by a seed command.

The rules that were therefore enforced nowhere:

* An exclusion and a benefit can contradict each other. A plan that both covers
  a category and excludes a product inside it is answerable -- exclusion wins --
  but a plan that covers a category it also marks `covered=False` is not, and
  adjudication would produce whichever the query returned first.
* A coverage period must fall inside its plan's period. Outside it, the member
  holds cover that the plan does not.
* The member, the patient and the plan must share a tenant. `InsuranceCoverage`
  joins all three, and nothing checked they agreed.

Nothing here contacts an insurer. No eligibility call, no preauthorisation, no
claim, no remittance -- those are transactional and belong to their own
services.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.service import log_audit
from apps.insurance.models import (
    CoverageBenefit,
    CoverageExclusion,
    CoverageLimit,
    InsuranceCoverage,
    InsuranceDependent,
    InsuranceMember,
    Insurer,
    InsurerPlan,
)

PENNY = Decimal("0.01")

#: Benefit categories the adjudication path understands.
KNOWN_BENEFIT_CATEGORIES = frozenset(
    {
        "OUTPATIENT_MEDICINE",
        "OUTPATIENT_PHARMACY",
        "INPATIENT_MEDICINE",
        "CHRONIC_MEDICINE",
        "MATERNITY",
        "DENTAL",
        "OPTICAL",
        "CONSUMABLES",
    }
)


def _money(value, field: str) -> Decimal:
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a decimal number.") from exc
    if not amount.is_finite():
        raise ValidationError(f"{field} must be finite.")
    if amount < 0:
        raise ValidationError(f"{field} cannot be negative.")
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


def _assert_sandbox(insurer: Insurer) -> None:
    """Authoring is a sandbox activity.

    A production insurer's benefits are set by the insurer, not by this
    system. Authoring against a live counterparty would let a local edit change
    what the platform believes a real payer covers.
    """
    if insurer.environment != Insurer.Environment.SANDBOX:
        raise ValidationError(
            f"{insurer.code} is in {insurer.environment}. Coverage authoring is a "
            "sandbox activity; a production insurer's benefits are defined by the "
            "insurer, not authored here."
        )


class InsuranceBenefitService:
    """Defines what a plan covers."""

    @staticmethod
    @transaction.atomic
    def define_benefit(
        *,
        plan: InsurerPlan,
        category: str = "OUTPATIENT_MEDICINE",
        covered: bool = True,
        requires_preauth: bool = False,
        copay_rule: str = "",
        coinsurance_rule: str = "",
        benefit_limit=None,
        actor=None,
    ) -> CoverageBenefit:
        """Add or update a benefit category on a plan.

        Idempotent on (tenant, plan, category): a plan holds one position per
        category, and two rows for OUTPATIENT_MEDICINE would make cover depend
        on which the adjudicator read first.
        """
        _assert_sandbox(plan.scheme.insurer)
        category = str(category or "").strip().upper()
        if category not in KNOWN_BENEFIT_CATEGORIES:
            known = ", ".join(sorted(KNOWN_BENEFIT_CATEGORIES))
            raise ValidationError(f"Unknown benefit category {category!r}. Known: {known}")
        if not covered and (requires_preauth or benefit_limit is not None):
            # An uncovered category with a limit or a preauth requirement reads
            # as though it were partly covered.
            raise ValidationError(
                f"{category} is marked not covered, so it cannot carry a limit or a "
                "preauthorisation requirement."
            )
        limit = _money(benefit_limit, "benefit_limit") if benefit_limit is not None else None

        benefit, _ = CoverageBenefit.all_objects.update_or_create(
            tenant=plan.tenant,
            plan=plan,
            category=category,
            defaults={
                "covered": covered,
                "requires_preauth": requires_preauth,
                "copay_rule": copay_rule,
                "coinsurance_rule": coinsurance_rule,
                "benefit_limit": limit,
            },
        )
        log_audit(
            tenant_id=plan.tenant_id, action="INSURANCE_BENEFIT_DEFINED",
            model_name="CoverageBenefit", object_id=benefit.pk,
            actor_id=getattr(actor, "id", None),
            metadata={"plan": plan.code, "category": category, "covered": covered},
        )
        return benefit

    @staticmethod
    @transaction.atomic
    def exclude_product(
        *, plan: InsurerPlan, sku=None, active_substance=None, reason: str, actor=None,
    ) -> CoverageExclusion:
        """Exclude a specific product or substance from a plan.

        An exclusion is narrower than a benefit and overrides it: a plan may
        cover OUTPATIENT_MEDICINE and still exclude one brand. What it may not
        do is exclude something inside a category it has already marked not
        covered -- that is not a rule, it is a contradiction, and it makes the
        exclusion list a misleading description of what the plan does.
        """
        _assert_sandbox(plan.scheme.insurer)
        if sku is None and active_substance is None:
            raise ValidationError("An exclusion requires a SKU or an active substance.")
        if sku is not None and active_substance is not None:
            raise ValidationError(
                "An exclusion targets either a SKU or a substance, not both -- two "
                "targets make the exclusion's scope ambiguous."
            )
        if not str(reason or "").strip():
            raise ValidationError("An exclusion requires a reason.")
        if sku is not None and sku.tenant_id != plan.tenant_id:
            raise ValidationError("The SKU belongs to a different tenant than the plan.")

        uncovered = CoverageBenefit.all_objects.filter(
            tenant=plan.tenant, plan=plan, covered=False
        ).values_list("category", flat=True)
        if uncovered and sku is not None:
            # Only meaningful where the benefit set already says the whole
            # category is out; excluding within it adds nothing and misleads.
            for category in uncovered:
                if category in {"OUTPATIENT_MEDICINE", "OUTPATIENT_PHARMACY"}:
                    raise ValidationError(
                        f"Plan {plan.code} already excludes the whole {category} "
                        "category, so a product-level exclusion inside it is "
                        "contradictory. Remove the category exclusion or the "
                        "product exclusion."
                    )

        exclusion, _ = CoverageExclusion.all_objects.update_or_create(
            tenant=plan.tenant, plan=plan, sku=sku, active_substance=active_substance,
            defaults={"exclusion_reason": reason},
        )
        log_audit(
            tenant_id=plan.tenant_id, action="INSURANCE_EXCLUSION_DEFINED",
            model_name="CoverageExclusion", object_id=exclusion.pk,
            actor_id=getattr(actor, "id", None),
            metadata={"plan": plan.code, "reason": reason},
        )
        return exclusion

    @staticmethod
    def is_excluded(*, plan: InsurerPlan, sku) -> bool:
        """Whether a plan excludes a SKU, directly or by substance."""
        return CoverageExclusion.all_objects.filter(
            tenant_id=plan.tenant_id, plan=plan, sku=sku
        ).exists()


class InsuranceMembershipService:
    """Enrols patients onto plans."""

    @staticmethod
    @transaction.atomic
    def register_member(
        *, tenant, membership_number: str, principal_name: str,
        contact_phone: str = "", email: str = "", actor=None,
    ) -> InsuranceMember:
        """Register a scheme member. Idempotent on (tenant, membership number).

        Deliberately no `national_id` argument. The field exists on the model,
        but nothing in provisioning needs it, and a service that accepts a
        national ID invites callers to store one.
        """
        membership_number = str(membership_number or "").strip()
        principal_name = str(principal_name or "").strip()
        if not membership_number:
            raise ValidationError("A member requires a membership number.")
        if not principal_name:
            raise ValidationError("A member requires a principal name.")

        existing = InsuranceMember.all_objects.filter(
            tenant=tenant, membership_number=membership_number
        ).first()
        if existing is not None:
            return existing

        return InsuranceMember.all_objects.create(
            tenant=tenant,
            membership_number=membership_number,
            principal_name=principal_name,
            contact_phone=contact_phone,
            email=email,
            status="ACTIVE",
        )

    @staticmethod
    @transaction.atomic
    def enrol_patient(
        *,
        member: InsuranceMember,
        patient,
        plan: InsurerPlan,
        valid_from: date,
        valid_to: date,
        relationship: str = InsuranceCoverage.Relationship.SELF,
        dependent_code: str = "00",
        annual_limit=None,
        copay_amount=None,
        coinsurance_percentage=None,
        actor=None,
    ) -> InsuranceCoverage:
        """Give a patient cover under a plan.

        Idempotent on (member, patient, plan), matching the unique constraint.
        """
        insurer = plan.scheme.insurer
        _assert_sandbox(insurer)

        if patient is None:
            raise ValidationError("Coverage requires a patient.")
        # All three join in one row; if they disagree the coverage silently
        # spans tenants and every downstream query is wrong.
        if patient.tenant_id != member.tenant_id:
            raise ValidationError("The patient and the member belong to different tenants.")
        if plan.tenant_id != member.tenant_id:
            raise ValidationError("The plan and the member belong to different tenants.")
        if valid_from is None or valid_to is None:
            raise ValidationError("Coverage requires both valid-from and valid-to dates.")
        if valid_to < valid_from:
            raise ValidationError("Coverage cannot end before it begins.")
        if relationship not in InsuranceCoverage.Relationship.values:
            known = ", ".join(InsuranceCoverage.Relationship.values)
            raise ValidationError(f"Unknown relationship {relationship!r}. Known: {known}")
        if relationship == InsuranceCoverage.Relationship.SELF and dependent_code != "00":
            raise ValidationError(
                "The principal member carries dependent code 00; a non-zero code "
                "describes a dependent."
            )

        limit = _money(annual_limit, "annual_limit") if annual_limit is not None else None
        copay = _money(copay_amount, "copay_amount") if copay_amount is not None else Decimal("0.00")
        coinsurance = (
            _money(coinsurance_percentage, "coinsurance_percentage")
            if coinsurance_percentage is not None else Decimal("0.00")
        )
        if coinsurance > Decimal("100"):
            raise ValidationError("Coinsurance cannot exceed 100 per cent.")

        existing = InsuranceCoverage.all_objects.filter(
            member=member, patient=patient, plan=plan
        ).first()
        if existing is not None:
            return existing

        defaults = {
            "tenant": member.tenant,
            "scheme": plan.scheme,
            "dependent_code": dependent_code,
            "relationship": relationship,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "status": InsuranceCoverage.Status.ACTIVE,
            "copay_amount": copay,
            "coinsurance_percentage": coinsurance,
        }
        if limit is not None:
            defaults["remaining_limit"] = limit

        coverage = InsuranceCoverage.all_objects.create(
            member=member, patient=patient, plan=plan, **defaults
        )
        log_audit(
            tenant_id=member.tenant_id, action="INSURANCE_COVERAGE_CREATED",
            model_name="InsuranceCoverage", object_id=coverage.pk,
            actor_id=getattr(actor, "id", None),
            metadata={"plan": plan.code, "membership_number": member.membership_number},
        )
        return coverage

    @staticmethod
    @transaction.atomic
    def add_dependent(
        *, member: InsuranceMember, patient, dependent_code: str, full_name: str,
        relationship: str = "CHILD", date_of_birth: date | None = None, actor=None,
    ) -> InsuranceDependent:
        """Record a dependant on a member's policy."""
        dependent_code = str(dependent_code or "").strip()
        if not dependent_code or dependent_code == "00":
            raise ValidationError(
                "A dependant requires a code other than 00, which denotes the principal."
            )
        if patient.tenant_id != member.tenant_id:
            raise ValidationError("The patient and the member belong to different tenants.")

        dependent, _ = InsuranceDependent.all_objects.update_or_create(
            tenant=member.tenant, member=member, dependent_code=dependent_code,
            defaults={
                "patient": patient,
                "relationship": relationship,
                "full_name": full_name,
                "date_of_birth": date_of_birth,
            },
        )
        return dependent

    @staticmethod
    @transaction.atomic
    def set_coverage_limit(
        *, coverage: InsuranceCoverage, category: str, total_limit, reset_date=None,
        actor=None,
    ) -> CoverageLimit:
        """Set a spending limit on one category of a member's cover.

        `remaining_amount` starts equal to `total_limit` and is not a parameter:
        a caller that could set it independently could create cover that has
        already been partly consumed with no transaction behind it.
        """
        total = _money(total_limit, "total_limit")
        category = str(category or "").strip().upper()
        if not category:
            raise ValidationError("A coverage limit requires a category.")

        limit, _ = CoverageLimit.all_objects.update_or_create(
            tenant=coverage.tenant, coverage=coverage, category=category,
            defaults={
                "total_limit": total,
                "used_amount": Decimal("0.00"),
                "remaining_amount": total,
                "reset_date": reset_date,
            },
        )
        return limit

    @staticmethod
    @transaction.atomic
    def suspend_coverage(*, coverage: InsuranceCoverage, actor, reason: str) -> InsuranceCoverage:
        """Suspend cover without deleting it; claims history references it."""
        if actor is None:
            raise PermissionDenied("Suspending coverage requires a named actor.")
        if not str(reason or "").strip():
            raise ValidationError("Suspending coverage requires a reason.")

        coverage.status = InsuranceCoverage.Status.SUSPENDED
        coverage.save(update_fields=["status", "updated_at"])
        log_audit(
            tenant_id=coverage.tenant_id, action="INSURANCE_COVERAGE_SUSPENDED",
            model_name="InsuranceCoverage", object_id=coverage.pk,
            actor_id=actor.id, metadata={"reason": reason},
        )
        return coverage
