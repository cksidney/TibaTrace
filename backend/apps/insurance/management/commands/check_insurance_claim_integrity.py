"""Detect claims that assert something the ledger does not support.

Every check corresponds to a way a provider ends up having made a false
statement to an insurer, or having booked money nobody agreed to pay.

Exits non-zero on any finding. A checker that reports problems and exits 0 is a
checker whose output nobody reads -- and this repository has been bitten by that
before.

Repair mode rebuilds projections from authoritative facts. It never fabricates
eligibility, preauthorisation, adjudication, remittance or approval; a checker
that can invent an insurer's decision is worse than no checker at all.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.insurance.models import (
    ClaimAdjudication,
    PrescriptionClaim,
    PrescriptionClaimLine,
)
from apps.insurance.services.claim_construction import ClaimConstructionService, money

ZERO = Decimal("0.00")


class Command(BaseCommand):
    help = "Check insurance claims against the authoritative supply and payment ledgers."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="tenant_id", default=None)
        parser.add_argument(
            "--repair",
            action="store_true",
            help="Rebuild derived projections. Never fabricates an insurer decision.",
        )

    def handle(self, *args, **options):
        claims = PrescriptionClaim.all_objects.all()
        if options.get("tenant_id"):
            claims = claims.filter(tenant_id=options["tenant_id"])

        findings: list[str] = []
        for claim in claims.select_related("supply", "episode"):
            findings.extend(self._check_claim(claim, repair=options.get("repair", False)))

        for finding in findings:
            self.stderr.write(self.style.ERROR(finding))

        if findings:
            # Non-zero, so a validation pipeline actually fails.
            raise CommandError(f"{len(findings)} insurance claim integrity finding(s).")

        self.stdout.write(self.style.SUCCESS("Insurance claim integrity checks passed."))

    def _check_claim(self, claim: PrescriptionClaim, *, repair: bool) -> list[str]:
        findings: list[str] = []
        prefix = f"Claim {claim.claim_number}"

        # A claim with no supply describes goods that never left the shelf.
        if claim.supply_id is None:
            findings.append(f"{prefix}: has no linked supply event.")

        # The clearest form of a false claim.
        if claim.supply_id and not ClaimConstructionService.claimed_quantity_matches_supply(
            claim=claim
        ):
            findings.append(
                f"{prefix}: claims a greater quantity than was supplied."
            )

        lines = list(
            PrescriptionClaimLine.all_objects.filter(tenant_id=claim.tenant_id, claim=claim)
        )

        if not lines:
            findings.append(f"{prefix}: has no lines.")

        # A header disagreeing with its own lines is the shape of an amount
        # edited after construction.
        line_total = money(sum((money(line.claimed_amount) for line in lines), ZERO))
        if lines and line_total != money(claim.claimed_gross_amount):
            if repair:
                claim.claimed_gross_amount = line_total
                claim.save(update_fields=["claimed_gross_amount", "updated_at"])
            else:
                findings.append(
                    f"{prefix}: gross {money(claim.claimed_gross_amount)} "
                    f"does not equal its line total {line_total}."
                )

        for line in lines:
            if not line.insurer_item_code:
                findings.append(f"{prefix}: line {line.pk} has no insurer item code.")

        # The central one. A payable may exist only where an insurer approved
        # something, and transport acceptance is not approval.
        approved_states = {
            PrescriptionClaim.AdjudicationState.APPROVED,
            PrescriptionClaim.AdjudicationState.PARTIALLY_APPROVED,
        }
        if (
            money(claim.insurer_payable_amount) > ZERO
            and claim.adjudication_state not in approved_states
        ):
            if repair:
                claim.insurer_payable_amount = ZERO
                claim.save(update_fields=["insurer_payable_amount", "updated_at"])
            else:
                findings.append(
                    f"{prefix}: carries an insurer payable of "
                    f"{money(claim.insurer_payable_amount)} while adjudication is "
                    f"{claim.adjudication_state}. Only an approval creates a payable."
                )

        # Transport acceptance recorded as an approval.
        if (
            claim.submission_state == PrescriptionClaim.SubmissionState.TRANSPORT_ACCEPTED
            and claim.adjudication_state == PrescriptionClaim.AdjudicationState.APPROVED
            and not ClaimAdjudication.all_objects.filter(
                tenant_id=claim.tenant_id, claim=claim
            ).exists()
        ):
            findings.append(
                f"{prefix}: is marked approved but has no adjudication record. "
                "Transport acceptance is not an approval."
            )

        # Paid without money having arrived.
        if (
            claim.payment_state == PrescriptionClaim.PaymentState.PAID
            and money(claim.paid_amount) <= ZERO
        ):
            findings.append(
                f"{prefix}: is marked paid but no payment has been allocated."
            )

        # Approval never widens beyond what was claimed.
        if money(claim.approved_amount) > money(claim.claimed_gross_amount):
            findings.append(
                f"{prefix}: approved {money(claim.approved_amount)} exceeds the "
                f"claimed gross {money(claim.claimed_gross_amount)}."
            )

        # Cross-tenant relationships.
        if claim.supply_id and claim.supply.tenant_id != claim.tenant_id:
            findings.append(f"{prefix}: references a supply belonging to another tenant.")
        if claim.member.tenant_id != claim.tenant_id:
            findings.append(f"{prefix}: references a member belonging to another tenant.")

        return findings
