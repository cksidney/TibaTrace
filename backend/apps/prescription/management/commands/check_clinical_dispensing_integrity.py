from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from apps.cds.models import ClinicalFinding
from apps.inventory.models import InventoryLedgerEntry
from apps.patients.models import PatientAllergy
from apps.prescription.models import (
    DispensingLine,
    DispensingReversal,
    MedicineSupply,
    MedicineSupplyLine,
    PatientMedicationHistory,
    PatientReturnLine,
    PharmacistVerification,
    Prescription,
    PrescriptionItem,
    PrescriptionValidationFinding,
)
from apps.tenancy.models import Tenant
from apps.workflows.models import DomainEvent


class Command(BaseCommand):
    help = "Validate clinical dispensing, inventory, and medication-history integrity."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=str, help="Tenant slug")
        parser.add_argument(
            "--repair",
            action="store_true",
            help="Rebuild safe derived prescription-item supply totals.",
        )

    def _record(self, issues, code, object_id, detail):
        issues.append(
            {
                "code": code,
                "object_id": str(object_id),
                "detail": detail,
            }
        )

    def _repair_totals(self, tenant):
        for item in PrescriptionItem.all_objects.filter(tenant=tenant):
            gross_total = (
                MedicineSupplyLine.all_objects.filter(
                    tenant=tenant,
                    prescription_item=item,
                ).aggregate(total=Sum("quantity"))["total"]
                or Decimal("0")
            )
            reversed_total = (
                DispensingReversal.all_objects.filter(
                    tenant=tenant,
                    original_supply_line__prescription_item=item,
                ).aggregate(total=Sum("quantity"))["total"]
                or Decimal("0")
            )
            PrescriptionItem.all_objects.filter(
                tenant=tenant,
                id=item.id,
            ).update(
                quantity_supplied_total=max(
                    Decimal("0"),
                    gross_total - reversed_total,
                )
            )

    def _check_tenant(self, tenant):
        issues = []
        active_verifications = PharmacistVerification.all_objects.filter(
            tenant=tenant,
            revoked_at__isnull=True,
        ).select_related(
            "prescription__practitioner",
            "verified_by",
        )
        active_verification_prescription_ids = set(
            active_verifications.values_list("prescription_id", flat=True)
        )
        for verification in active_verifications:
            prescription = verification.prescription
            unresolved_clinical = ClinicalFinding.all_objects.filter(
                tenant=tenant,
                prescription=prescription,
                severity__in=["BLOCK", "CRITICAL"],
                resolution_status__in=[
                    "OPEN",
                    "ACKNOWLEDGED",
                    "INTERVENTION_REQUIRED",
                ],
            ).exists()
            unresolved_legal = PrescriptionValidationFinding.all_objects.filter(
                tenant=tenant,
                prescription=prescription,
                severity__in=["HIGH", "CRITICAL"],
                status__in=["OPEN", "ACKNOWLEDGED"],
            ).exists()
            if unresolved_clinical or unresolved_legal:
                self._record(
                    issues,
                    "VERIFICATION_WITH_UNRESOLVED_CRITICAL_FINDING",
                    verification.id,
                    "Active verification has an unresolved blocking finding.",
                )
            checks = verification.verification_checks or {}
            if not checks.get("prescriber_authority_confirmed"):
                self._record(
                    issues,
                    "INVALID_PRESCRIBER_AT_VERIFICATION",
                    verification.id,
                    "Verification lacks immutable prescriber-authority evidence.",
                )
            if not checks.get("pharmacist_authority_confirmed"):
                self._record(
                    issues,
                    "PHARMACIST_AUTHORITY_EVIDENCE_MISSING",
                    verification.id,
                    "Verification lacks immutable pharmacist-authority evidence.",
                )
            if (
                prescription.is_controlled_medicine
                and not checks.get("controlled_authority_confirmed")
            ):
                self._record(
                    issues,
                    "CONTROLLED_VERIFICATION_AUTHORITY_MISSING",
                    verification.id,
                    "Controlled verification lacks authority evidence.",
                )

        for prescription in Prescription.all_objects.filter(tenant=tenant):
            has_active_verification = (
                prescription.id in active_verification_prescription_ids
            )
            state_is_verified = (
                prescription.pharmacist_verification_state == "VERIFIED"
            )
            requires_active_verification = prescription.dispensing_state in {
                "READY",
                "PARTIALLY_DISPENSED",
                "DISPENSED",
                "PARTIALLY_SUPPLIED",
                "SUPPLIED",
                "RETURNED",
            }
            if has_active_verification != state_is_verified or (
                requires_active_verification and not has_active_verification
            ):
                self._record(
                    issues,
                    "INVALID_PRESCRIPTION_STATE",
                    prescription.id,
                    "Prescription lifecycle state is inconsistent with active verification.",
                )
            if has_active_verification and prescription.legal_validation_state != "PASSED":
                self._record(
                    issues,
                    "INVALID_PRESCRIPTION_STATE",
                    prescription.id,
                    "Verified prescription does not have passed legal validation.",
                )

        supplies = MedicineSupply.all_objects.filter(tenant=tenant).select_related(
            "prescription__practitioner",
            "patient",
            "episode",
        )
        for supply in supplies:
            verification = (
                PharmacistVerification.all_objects.filter(
                    tenant=tenant,
                    prescription=supply.prescription,
                    verified_at__lte=supply.supplied_at,
                )
                .order_by("-verified_at")
                .first()
            )
            if not verification or (
                verification.revoked_at
                and verification.revoked_at <= supply.supplied_at
            ):
                self._record(
                    issues,
                    "SUPPLY_WITHOUT_VERIFICATION",
                    supply.id,
                    "Medicine supply lacks a valid pharmacist verification.",
                )
            if ClinicalFinding.all_objects.filter(
                tenant=tenant,
                prescription=supply.prescription,
                severity__in=["BLOCK", "CRITICAL"],
                resolution_status__in=[
                    "OPEN",
                    "ACKNOWLEDGED",
                    "INTERVENTION_REQUIRED",
                ],
                created_at__lte=supply.supplied_at,
            ).exists():
                self._record(
                    issues,
                    "UNRESOLVED_CRITICAL_FINDING",
                    supply.id,
                    "Supply has an unresolved critical clinical finding.",
                )
            if (
                supply.prescription.expires_at
                and supply.prescription.expires_at < supply.supplied_at
            ):
                self._record(
                    issues,
                    "EXPIRED_PRESCRIPTION_SUPPLIED",
                    supply.id,
                    "Prescription expired before medicine supply.",
                )
            practitioner = supply.prescription.practitioner
            supply_date = supply.supplied_at.date()
            if (
                practitioner.verification_state != "VERIFIED"
                or practitioner.licence_status not in {"ACTIVE", "VALID"}
                or (
                    practitioner.licence_expiry_date
                    and practitioner.licence_expiry_date < supply_date
                )
            ):
                self._record(
                    issues,
                    "INVALID_PRESCRIBER_AT_SUPPLY",
                    supply.id,
                    "Prescriber authority is invalid for the supplied prescription.",
                )
            if (
                supply.prescription.is_controlled_medicine
                and not practitioner.controlled_medicine_authority
            ):
                self._record(
                    issues,
                    "CONTROLLED_SUPPLY_WITHOUT_AUTHORITY",
                    supply.id,
                    "Controlled medicine prescriber authority is missing.",
                )
            if supply.status not in {
                "PARTIAL",
                "COMPLETE",
                "PARTIALLY_REVERSED",
                "REVERSED",
            }:
                self._record(
                    issues,
                    "INVALID_SUPPLY_STATE",
                    supply.id,
                    f"Unsupported supply state {supply.status}.",
                )

        for item in PrescriptionItem.all_objects.filter(tenant=tenant):
            gross_supplied = (
                MedicineSupplyLine.all_objects.filter(
                    tenant=tenant,
                    prescription_item=item,
                ).aggregate(total=Sum("quantity"))["total"]
                or Decimal("0")
            )
            reversed_quantity = (
                DispensingReversal.all_objects.filter(
                    tenant=tenant,
                    original_supply_line__prescription_item=item,
                ).aggregate(total=Sum("quantity"))["total"]
                or Decimal("0")
            )
            supplied = max(
                Decimal("0"),
                gross_supplied - reversed_quantity,
            )
            if supplied > item.total_authorized_quantity:
                self._record(
                    issues,
                    "AUTHORIZED_QUANTITY_EXCEEDED",
                    item.id,
                    "Cumulative supply exceeds prescription authorization.",
                )
            if item.quantity_supplied_total != supplied:
                self._record(
                    issues,
                    "PRESCRIPTION_ITEM_TOTAL_MISMATCH",
                    item.id,
                    "Derived prescription-item total differs from supply lines.",
                )
            completed_repeats = max(0, int(supplied // item.quantity) - 1)
            if completed_repeats > item.refills_authorized:
                self._record(
                    issues,
                    "REPEAT_COUNT_EXCEEDED",
                    item.id,
                    "Completed repeat supplies exceed authorization.",
                )

        for line in DispensingLine.all_objects.filter(tenant=tenant).select_related(
            "inventory_batch",
            "prescription_item",
        ):
            if not line.inventory_batch_id:
                self._record(
                    issues,
                    "DISPENSING_LINE_WITHOUT_BATCH",
                    line.id,
                    "Dispensing line lacks exact inventory batch lineage.",
                )
            if line.quantity_supplied > line.quantity_prepared:
                self._record(
                    issues,
                    "DISPENSING_QUANTITY_INVALID",
                    line.id,
                    "Supplied quantity exceeds prepared quantity.",
                )

        supply_line_issue_ids = set(
            MedicineSupplyLine.all_objects.filter(tenant=tenant).values_list(
                "inventory_issue_id",
                flat=True,
            )
        )
        for issue in InventoryLedgerEntry.all_objects.filter(
            tenant=tenant,
            entry_type=InventoryLedgerEntry.EntryType.ISSUE,
            source_document_type="MEDICINE_SUPPLY",
        ):
            if issue.id not in supply_line_issue_ids:
                self._record(
                    issues,
                    "ORPHAN_DISPENSING_INVENTORY_ISSUE",
                    issue.id,
                    "Inventory issue has no medicine-supply source line.",
                )

        for supply_line in MedicineSupplyLine.all_objects.filter(
            tenant=tenant
        ).select_related(
            "inventory_issue",
            "supply__prescription",
        ):
            issue = supply_line.inventory_issue
            if (
                issue.entry_type != InventoryLedgerEntry.EntryType.ISSUE
                or issue.source_document_type != "MEDICINE_SUPPLY"
                or issue.source_document_id != str(supply_line.supply_id)
                or abs(issue.base_quantity_delta) != supply_line.quantity
            ):
                self._record(
                    issues,
                    "DUPLICATE_OR_INVALID_SUPPLY_POSTING",
                    supply_line.id,
                    "Supply line inventory issue source or quantity is inconsistent.",
                )
            history = PatientMedicationHistory.all_objects.filter(
                tenant=tenant,
                medicine_supply_line=supply_line,
                source="MEDICINE_SUPPLY",
            ).first()
            if (
                not history
                or history.quantity != supply_line.quantity
                or history.inventory_batch_id != supply_line.inventory_batch_id
            ):
                self._record(
                    issues,
                    "MEDICATION_HISTORY_MISMATCH",
                    supply_line.id,
                    "Medication history does not match authoritative supply.",
                )
            if supply_line.supply.prescription.is_controlled_medicine and not (
                DomainEvent.all_objects.filter(
                    tenant=tenant,
                    event_type="ControlledMedicineSupplied",
                    payload__running_balance_reference=str(
                        supply_line.inventory_issue_id
                    ),
                ).exists()
            ):
                self._record(
                    issues,
                    "CONTROLLED_SUPPLY_WITHOUT_AUTHORITY",
                    supply_line.id,
                    "Controlled supply lacks immutable register authority evidence.",
                )

        for reversal in DispensingReversal.all_objects.filter(tenant=tenant):
            if not MedicineSupplyLine.all_objects.filter(
                tenant=tenant,
                id=reversal.original_supply_line_id,
                supply_id=reversal.supply_id,
            ).exists():
                self._record(
                    issues,
                    "REVERSAL_WITHOUT_ORIGINAL_SUPPLY",
                    reversal.id,
                    "Reversal does not reference its original supply line.",
                )
            total_reversed = (
                DispensingReversal.all_objects.filter(
                    tenant=tenant,
                    original_supply_line=reversal.original_supply_line,
                ).aggregate(total=Sum("quantity"))["total"]
                or Decimal("0")
            )
            if total_reversed > reversal.original_supply_line.quantity:
                self._record(
                    issues,
                    "REVERSAL_EXCEEDS_ORIGINAL_SUPPLY",
                    reversal.id,
                    "Cumulative reversal quantity exceeds original supply.",
                )

        for return_line in PatientReturnLine.all_objects.filter(tenant=tenant):
            total_returned = (
                PatientReturnLine.all_objects.filter(
                    tenant=tenant,
                    original_supply_line=return_line.original_supply_line,
                ).aggregate(total=Sum("quantity"))["total"]
                or Decimal("0")
            )
            if total_returned > return_line.original_supply_line.quantity:
                self._record(
                    issues,
                    "PATIENT_RETURN_EXCEEDS_SUPPLY",
                    return_line.id,
                    "Patient-return quantity exceeds original supply.",
                )

        for allergy in PatientAllergy.all_objects.filter(
            tenant=tenant,
            is_active=True,
            status__in=["SUSPECTED", "CONFIRMED"],
            medicinal_product__isnull=False,
        ):
            conflicting_prescriptions = Prescription.all_objects.filter(
                tenant=tenant,
                patient=allergy.patient,
                items__canonical_medicine=allergy.medicinal_product,
            ).distinct()
            for prescription in conflicting_prescriptions:
                if not ClinicalFinding.all_objects.filter(
                    tenant=tenant,
                    prescription=prescription,
                    rule_type="ALLERGY",
                ).exists():
                    self._record(
                        issues,
                        "ALLERGY_FINDING_MISSING",
                        prescription.id,
                        "Known medicine allergy lacks an allergy finding.",
                    )

        tenant_models = (
            MedicineSupply,
            MedicineSupplyLine,
            PatientMedicationHistory,
            DispensingReversal,
            PatientReturnLine,
        )
        for model in tenant_models:
            relation_fields = getattr(model, "tenant_relation_fields", ())
            for instance in model.all_objects.filter(tenant=tenant):
                for field_name in relation_fields:
                    related = getattr(instance, field_name, None)
                    if related and str(getattr(related, "tenant_id", "")) != str(
                        tenant.id
                    ):
                        self._record(
                            issues,
                            "CROSS_TENANT_REFERENCE",
                            instance.id,
                            f"{model.__name__}.{field_name} crosses tenant scope.",
                        )
        return issues

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        if options.get("tenant"):
            tenants = tenants.filter(slug=options["tenant"])
        if not tenants.exists():
            raise CommandError("No matching tenant found.")
        issues = []
        for tenant in tenants:
            if options["repair"]:
                self._repair_totals(tenant)
            tenant_issues = self._check_tenant(tenant)
            issues.extend(tenant_issues)
            self.stdout.write(
                f"{tenant.slug}: {len(tenant_issues)} clinical integrity issue(s)"
            )
        for issue in issues:
            self.stderr.write(
                f"{issue['code']} {issue['object_id']}: {issue['detail']}"
            )
        if issues:
            raise CommandError(
                f"Clinical dispensing integrity failed with {len(issues)} issue(s)."
            )
        self.stdout.write(
            self.style.SUCCESS("Clinical dispensing integrity check passed.")
        )
