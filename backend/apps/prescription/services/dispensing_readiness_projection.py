"""Authoritative Dispensing Readiness Projection Service.

Composes independent domain state machines (Clinical, Commercial, Inventory, Register)
to project single-source-of-truth dispensing readiness without mutating domain state.

Readiness Rule:
  clinical_ready
  AND commercial_ready
  AND inventory_ready
  AND register_ready
  AND practitioner_authority_valid
  AND premises_compliant
  AND device_activation_valid
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.cds.models import PosClinicalScreening
from apps.inventory.models import InventoryReservation
from apps.pharmacy_network.verification_service import check_premises_compliance
from apps.pos_shift.authority import RegisterAuthorityService
from apps.prescription.models import Prescription
from apps.sales.models import SalesOrder


@dataclass(frozen=True)
class DispensingReadinessReport:
    tenant_id: str
    branch_id: str
    case_reference: str
    clinical_state: str
    commercial_state: str
    inventory_state: str
    register_state: str
    payment_state: str
    dispensing_state: str
    overall_readiness: str
    blocking_reasons: list[str]
    permitted_next_actions: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "branch_id": self.branch_id,
            "case_reference": self.case_reference,
            "clinical_state": self.clinical_state,
            "commercial_state": self.commercial_state,
            "inventory_state": self.inventory_state,
            "register_state": self.register_state,
            "payment_state": self.payment_state,
            "dispensing_state": self.dispensing_state,
            "overall_readiness": self.overall_readiness,
            "blocking_reasons": self.blocking_reasons,
            "permitted_next_actions": self.permitted_next_actions,
        }


class DispensingReadinessProjectionService:
    @classmethod
    def evaluate_readiness(
        cls,
        *,
        tenant,
        branch,
        case_reference: str,
        prescription: Prescription | None = None,
        sales_order: SalesOrder | None = None,
        device_id: str = "",
        actor=None,
    ) -> DispensingReadinessReport:
        blocking_reasons: list[str] = []
        permitted_actions: list[str] = []
        has_controlled = False

        # 1. Clinical State
        clinical_state = "READY"
        if prescription is not None:
            # Practitioner validation
            practitioner = prescription.practitioner
            if practitioner is None or not getattr(practitioner, "is_active", True):
                clinical_state = "PRACTITIONER_INVALID"
                blocking_reasons.append("Practitioner is inactive or missing.")
            elif getattr(practitioner, "licence_expiry_date", None) and practitioner.licence_expiry_date < timezone.localdate():
                clinical_state = "PRACTITIONER_INVALID"
                blocking_reasons.append("Practitioner licence has expired.")

            # Prescription status & review state
            if prescription.legal_validation_state not in ("VALIDATED", "PASSED"):
                clinical_state = "CLINICAL_REVIEW_REQUIRED"
                blocking_reasons.append(f"Legal validation state is '{prescription.legal_validation_state}'.")
            elif prescription.clinical_review_state in ("NOT_STARTED", "UNDER_REVIEW"):
                clinical_state = "CLINICAL_REVIEW_REQUIRED"
                blocking_reasons.append(f"Clinical review state is '{prescription.clinical_review_state}'.")
            elif prescription.clinical_review_state == "REJECTED":
                clinical_state = "BLOCKED_CLINICAL"
                blocking_reasons.append("Prescription was rejected by pharmacist review.")

            # Controlled medicine authority check
            has_controlled = any(
                getattr(line.sku, "is_controlled", False)
                for line in prescription.items.all()
            )
            if has_controlled:
                if practitioner and not getattr(practitioner, "controlled_medicine_authority", False):
                    clinical_state = "BLOCKED_CONTROLLED_MEDICINE"
                    blocking_reasons.append("Prescriber lacks controlled medicine authority.")

            # Screening findings check
            screenings = PosClinicalScreening.all_objects.filter(
                tenant=tenant, prescription_id=prescription.pk
            )
            for scr in screenings:
                for finding in scr.findings.all():
                    if finding.blocking and finding.resolution_status != "OVERRIDDEN" and not finding.overrides.exists():
                        clinical_state = "CLINICAL_REVIEW_REQUIRED"
                        blocking_reasons.append(f"Unresolved clinical finding: {finding.summary}")

        # 2. Commercial State
        commercial_state = "READY"
        if sales_order is not None:
            if sales_order.status == "DRAFT":
                commercial_state = "DRAFT"
            elif sales_order.status in ("CANCELLED", "EXPIRED"):
                commercial_state = "CANCELLED"
                blocking_reasons.append(f"Sales order is '{sales_order.status}'.")

            # Verify line totals derived from server
            if sales_order.lines.exists():
                lines_qty = sum((line.approved_quantity or line.requested_quantity for line in sales_order.lines.all()), Decimal("0"))
                if lines_qty <= 0:
                    commercial_state = "INVALID_ORDER_QUANTITY"
                    blocking_reasons.append("Order lines have zero quantity.")

        # 3. Inventory State
        inventory_state = "READY"
        reservations = InventoryReservation.all_objects.filter(
            tenant=tenant, branch=branch
        )
        if sales_order is not None:
            reservations = reservations.filter(source_document=sales_order.order_number)
        elif prescription is not None:
            reservations = reservations.filter(source_document=prescription.prescription_number)

        if reservations.exists():
            active_res = reservations.filter(status=InventoryReservation.Status.ALLOCATED)
            if not active_res.exists():
                if reservations.filter(status=InventoryReservation.Status.EXPIRED).exists():
                    inventory_state = "STOCK_UNAVAILABLE"
                    blocking_reasons.append("Inventory reservations have expired.")
                elif reservations.filter(status=InventoryReservation.Status.RELEASED).exists():
                    inventory_state = "STOCK_UNAVAILABLE"
                    blocking_reasons.append("Inventory reservations were released.")
            else:
                total_req = sum((r.requested_quantity for r in active_res), Decimal("0"))
                total_alloc = sum((r.allocated_quantity for r in active_res), Decimal("0"))
                if total_alloc < total_req:
                    inventory_state = "PARTIALLY_RESERVED"
                    blocking_reasons.append(f"Partial inventory reservation ({total_alloc}/{total_req}).")
                else:
                    inventory_state = "RESERVED"
        else:
            inventory_state = "NOT_RESERVED"

        # 4. Register State
        register_state = "READY"
        if device_id and actor is not None:
            try:
                RegisterAuthorityService.resolve_for_transaction(
                    tenant=tenant, branch=branch, actor=actor, device_id=device_id
                )
            except Exception as exc:
                register_state = "REGISTER_REQUIRED"
                blocking_reasons.append(f"Register authority check failed: {exc}")

        # Premises compliance check
        is_premises_ok, reason_code = check_premises_compliance(
            tenant_id=tenant.pk, operation="CONTROLLED_MEDICINE_DISPENSE"
        )
        if not is_premises_ok and has_controlled:
            blocking_reasons.append(f"Premises compliance check failed: {reason_code}")

        # 5. Payment & Dispensing States (Fixed boundary for Stage 2D.1)
        payment_state = "NOT_PAID"
        dispensing_state = "NOT_DISPENSED"

        # Overall Readiness Determination
        if blocking_reasons:
            if "BLOCKED_CONTROLLED_MEDICINE" in clinical_state or any("controlled" in r.lower() for r in blocking_reasons):
                overall = "BLOCKED_CONTROLLED_MEDICINE"
            elif clinical_state in ("CLINICAL_REVIEW_REQUIRED", "PRACTITIONER_INVALID"):
                overall = clinical_state
            elif inventory_state in ("STOCK_UNAVAILABLE", "PARTIALLY_RESERVED"):
                overall = inventory_state
            elif register_state == "REGISTER_REQUIRED":
                overall = "REGISTER_REQUIRED"
            else:
                overall = "CLINICAL_REVIEW_REQUIRED"
        else:
            overall = "READY_FOR_PAYMENT"
            permitted_actions.append("PROCEED_TO_PAYMENT")
            permitted_actions.append("RESERVE_STOCK")

        return DispensingReadinessReport(
            tenant_id=str(tenant.pk),
            branch_id=str(branch.pk),
            case_reference=case_reference,
            clinical_state=clinical_state,
            commercial_state=commercial_state,
            inventory_state=inventory_state,
            register_state=register_state,
            payment_state=payment_state,
            dispensing_state=dispensing_state,
            overall_readiness=overall,
            blocking_reasons=blocking_reasons,
            permitted_next_actions=permitted_actions,
        )
