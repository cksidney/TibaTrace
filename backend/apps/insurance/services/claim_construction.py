"""Build a claim from what was actually supplied.

The rule this module exists to enforce: **a claim describes medicine that left
the shelf, not medicine that was prescribed.**

Those differ constantly. A prescription for 60 tablets that was part-supplied
at 30 must claim 30. A line the pharmacist refused must not appear at all. A
claim built from the basket rather than the supply is a claim for goods the
patient never received, which is not a data-quality problem -- it is a false
statement to an insurer with the provider's name on it.

So construction reads MedicineSupplyLine, never PrescriptionItem and never the
POS basket. If nothing was supplied, no claim exists to build.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.prescription.models import MedicineSupplyLine

from ..models import (
    InsuranceCoverage,
    MedicineClaimCodeMap,
    PrescriptionClaim,
    PrescriptionClaimLine,
    UnmappedClaimItem,
)

PENNY = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value) -> Decimal:
    if isinstance(value, Decimal):
        amount = value
    elif value is None:
        amount = ZERO
    else:
        amount = Decimal(str(value))
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


class NothingSupplied(ValidationError):
    """No supply lines exist, so there is nothing to claim for."""


class UnmappedItem(ValidationError):
    """A mandatory insurer item code is missing.

    Blocking rather than a warning. A claim submitted with a guessed code is
    either rejected weeks later or -- worse -- paid against the wrong product.
    """


class ClaimConstructionService:
    """Derives a claim from authoritative supply, coverage and pricing facts."""

    @staticmethod
    def supplied_lines(*, supply):
        """The authoritative record of what physically left the shelf."""
        return list(
            MedicineSupplyLine.all_objects.filter(
                tenant_id=supply.tenant_id, supply=supply
            ).select_related("supplied_sku", "dispensing_line")
        )

    @staticmethod
    def insurer_item_code(*, tenant_id, insurer, sku) -> str:
        mapping = MedicineClaimCodeMap.all_objects.filter(
            tenant_id=tenant_id, insurer=insurer, sku=sku
        ).first()
        return getattr(mapping, "insurer_item_code", "") or ""

    @classmethod
    def patient_liability(cls, *, coverage: InsuranceCoverage, gross: Decimal) -> tuple[Decimal, Decimal]:
        """Split a gross amount into (patient co-payment, insurer portion).

        Fixed co-payment first, then co-insurance on what remains. The patient
        never pays more than the gross, and the insurer portion is never
        negative -- both would otherwise be reachable with a co-payment larger
        than the line.
        """
        gross = money(gross)
        copay = min(money(coverage.copay_amount), gross)
        remainder = gross - copay

        coinsurance_rate = money(coverage.coinsurance_percentage) / Decimal("100")
        coinsurance = money(remainder * coinsurance_rate)

        patient = money(copay + coinsurance)
        insurer = money(gross - patient)
        return patient, max(ZERO, insurer)

    @classmethod
    @transaction.atomic
    def build(cls, *, supply, coverage: InsuranceCoverage, insurer, scheme, claim_number: str,
              unit_prices: dict | None = None, preauthorisation=None) -> PrescriptionClaim:
        """Construct a DRAFT claim from a completed supply.

        Deliberately returns a DRAFT. Construction is not submission, and a
        claim that exists is not a claim anybody has agreed to pay.
        """
        lines = cls.supplied_lines(supply=supply)
        if not lines:
            raise NothingSupplied(
                "No medicine was supplied against this episode, so there is nothing to claim."
            )

        unit_prices = unit_prices or {}
        tenant_id = supply.tenant_id

        claim = PrescriptionClaim.all_objects.create(
            tenant_id=tenant_id,
            claim_number=claim_number,
            episode=supply.episode,
            prescription=supply.episode.prescription,
            supply=supply,
            patient=coverage.patient,
            member=coverage.member,
            insurer=insurer,
            scheme=scheme,
            preauthorisation=preauthorisation,
            submission_state=PrescriptionClaim.SubmissionState.DRAFT,
            adjudication_state=PrescriptionClaim.AdjudicationState.PENDING,
        )

        gross_total = ZERO
        patient_total = ZERO
        insurer_total = ZERO
        unmapped: list[str] = []

        for supply_line in lines:
            sku = supply_line.supplied_sku
            # The quantity that physically left the shelf. Not the prescribed
            # quantity, and not the basket quantity.
            quantity = Decimal(str(supply_line.quantity))
            unit_price = money(unit_prices.get(str(sku.pk), ZERO))
            line_gross = money(quantity * unit_price)

            item_code = cls.insurer_item_code(tenant_id=tenant_id, insurer=insurer, sku=sku)
            if not item_code:
                unmapped.append(str(sku.pk))
                UnmappedClaimItem.all_objects.get_or_create(
                    tenant_id=tenant_id,
                    insurer=insurer,
                    sku=sku,
                    defaults={"status": "PENDING_MAPPING"},
                )

            patient_share, insurer_share = cls.patient_liability(coverage=coverage, gross=line_gross)

            PrescriptionClaimLine.all_objects.create(
                tenant_id=tenant_id,
                claim=claim,
                prescription_line=supply_line.dispensing_line,
                sku=sku,
                insurer_item_code=item_code,
                quantity=quantity,
                unit_price=unit_price,
                claimed_amount=line_gross,
                status="DRAFT",
            )

            gross_total += line_gross
            patient_total += patient_share
            insurer_total += insurer_share

        claim.claimed_gross_amount = money(gross_total)
        claim.claimed_net_amount = money(insurer_total)
        claim.patient_copay_amount = money(patient_total)
        # Deliberately zero. An insurer payable is what the insurer agreed to
        # pay, and at DRAFT they have not been asked.
        claim.insurer_payable_amount = ZERO
        claim.save(
            update_fields=[
                "claimed_gross_amount", "claimed_net_amount",
                "patient_copay_amount", "insurer_payable_amount", "updated_at",
            ]
        )

        if unmapped:
            raise UnmappedItem(
                {
                    "lines": [
                        f"{len(unmapped)} supplied item(s) have no {insurer.code} item code. "
                        "Map them before submitting; a guessed code is either rejected later "
                        "or paid against the wrong product."
                    ]
                }
            )

        return claim

    @staticmethod
    def validate_for_submission(*, claim: PrescriptionClaim) -> list[dict]:
        """Everything blocking submission, returned together.

        All of them, not the first: a claims clerk told one problem at a time
        resubmits once per problem.
        """
        problems: list[dict] = []
        lines = list(PrescriptionClaimLine.all_objects.filter(tenant_id=claim.tenant_id, claim=claim))

        if not lines:
            problems.append({"code": "NO_LINES", "message": "The claim has no lines."})

        for line in lines:
            if not line.insurer_item_code:
                problems.append(
                    {
                        "code": "UNMAPPED_ITEM",
                        "message": f"Line {line.pk} has no insurer item code.",
                        "line": str(line.pk),
                    }
                )
            if Decimal(str(line.quantity)) <= 0:
                problems.append(
                    {
                        "code": "NON_POSITIVE_QUANTITY",
                        "message": f"Line {line.pk} claims a non-positive quantity.",
                        "line": str(line.pk),
                    }
                )

        # Totals must reconcile to the lines. A header that disagrees with its
        # own lines is the shape of an amount edited after construction.
        line_total = money(sum((money(line.claimed_amount) for line in lines), ZERO))
        if lines and line_total != money(claim.claimed_gross_amount):
            problems.append(
                {
                    "code": "TOTALS_UNBALANCED",
                    "message": (
                        f"Claim gross {money(claim.claimed_gross_amount)} does not equal "
                        f"the sum of its lines {line_total}."
                    ),
                }
            )

        if claim.supply_id is None:
            problems.append(
                {
                    "code": "NO_SUPPLY",
                    "message": "The claim is not linked to a supply event.",
                }
            )

        return problems

    @staticmethod
    def claimed_quantity_matches_supply(*, claim: PrescriptionClaim) -> bool:
        """Whether every claimed quantity is backed by an equal supplied quantity.

        Used by the integrity checker. Claiming more than was supplied is the
        single clearest form of a false claim.
        """
        supplied: dict[str, Decimal] = {}
        for supply_line in MedicineSupplyLine.all_objects.filter(
            tenant_id=claim.tenant_id, supply_id=claim.supply_id
        ):
            key = str(supply_line.dispensing_line_id)
            supplied[key] = supplied.get(key, ZERO) + Decimal(str(supply_line.quantity))

        for line in PrescriptionClaimLine.all_objects.filter(
            tenant_id=claim.tenant_id, claim=claim
        ):
            key = str(line.prescription_line_id)
            if Decimal(str(line.quantity)) > supplied.get(key, ZERO):
                return False
        return True
