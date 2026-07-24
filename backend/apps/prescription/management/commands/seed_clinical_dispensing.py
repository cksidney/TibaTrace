from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.cds.models import (
    ActiveIngredient,
    ClinicalKnowledgeRelease,
    ClinicalKnowledgeRule,
    MedicineIngredient,
)
from apps.core.tenant_context import set_current_tenant_id
from apps.identity.models import Role, User, UserRole
from apps.inventory.models import InventoryBatch, InventoryLedgerEntry, InventoryLocation
from apps.inventory.services import InventoryLedgerService
from apps.medicines.models import CommercialSKU, Medicine
from apps.organizations.models import Location, Organization
from apps.patients.models import Patient, PatientAllergy, PatientClinicalSummary
from apps.patients.services import PatientGovernanceService
from apps.practitioners.models import Practitioner
from apps.prescription.models import (
    ClinicalSubstitution,
    PatientReturn,
    PharmacistClinicalReview,
    PharmacistIntervention,
    Prescription,
    PrescriptionItem,
)
from apps.prescription.services.clinical_dispensing import (
    DispensingAllocationService,
    DispensingCheckService,
    DispensingEpisodeService,
    DispensingLabelService,
    DispensingPreparationService,
    DispensingReservationService,
    DispensingReversalService,
    MedicineSupplyService,
    PatientCounsellingService,
    PatientReturnService,
    PharmacistInterventionService,
    PharmacistReviewService,
    PharmacistVerificationService,
    PrescriptionIntakeService,
    PrescriptionValidationService,
)
from apps.tenancy.models import Tenant

CLINICAL_CAPABILITIES = [
    "patients.read",
    "patients.write",
    "patients.create",
    "patients.identity.manage",
    "patients.identity.view",
    "patients.sensitive.view",
    "patients.allergy.record",
    "patients.clinical_summary.manage",
    "practitioners.read",
    "practitioners.write",
    "prescribers.verify",
    "prescriptions.read",
    "prescriptions.write",
    "prescriptions.intake",
    "prescriptions.review",
    "prescriptions.approve",
    "prescriptions.legal_validate",
    "prescriptions.clinical_review",
    "prescriptions.intervention.create",
    "prescriptions.pharmacist_verify",
    "prescriptions.critical_override",
    "prescriptions.controlled_verify",
    "prescriptions.substitution.approve",
    "cds.override",
    "dispensing.read",
    "dispensing.prepare",
    "dispensing.complete",
    "dispensing.reverse",
    "dispensing.substitute",
    "dispensing.reserve",
    "dispensing.allocate",
    "dispensing.check",
    "dispensing.supply",
    "dispensing.counsel",
    "dispensing.repeat.authorize",
    "dispensing.return.receive",
    "dispensing.return.quality",
]


class Command(BaseCommand):
    help = "Idempotently seed prescription safety and clinical dispensing scenarios."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default="tenant-a", help="Tenant slug")

    def _user(self, tenant, username, role):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "tenant": tenant,
                "email": f"{username}@example.invalid",
                "is_active": True,
                "metadata": {"seed_role": username},
            },
        )
        if created:
            user.set_unusable_password()
            user.save()
        UserRole.all_objects.get_or_create(
            tenant=tenant,
            user=user,
            role=role,
        )
        return user

    def _patient(self, tenant, number, **defaults):
        values = {
            "first_name": "Seed",
            "last_name": number,
            "date_of_birth": date(1990, 1, 1),
            "verification_status": "VERIFIED",
            "consent_status": "GRANTED",
            **defaults,
        }
        patient, _ = Patient.all_objects.update_or_create(
            tenant=tenant,
            patient_number=number,
            defaults={
                "internal_reference_id": number,
                **values,
            },
        )
        return patient

    def _prescriber(
        self,
        tenant,
        registration_number,
        *,
        controlled=False,
        expired=False,
        organization=None,
    ):
        practitioner, _ = Practitioner.all_objects.update_or_create(
            tenant=tenant,
            registration_number=registration_number,
            defaults={
                "first_name": "Dr",
                "last_name": registration_number,
                "professional_name": f"Dr {registration_number}",
                "profession": "DOCTOR",
                "licensing_body": "Configured demonstration authority",
                "licence_status": "VALID",
                "licence_issue_date": date.today() - timedelta(days=365),
                "licence_expiry_date": (
                    date.today() - timedelta(days=1)
                    if expired
                    else date.today() + timedelta(days=365)
                ),
                "prescribing_scope": ["GENERAL", "CONTROLLED"]
                if controlled
                else ["GENERAL"],
                "controlled_medicine_authority": controlled,
                "organization": organization,
                "verification_state": "VERIFIED",
                "verified_at": timezone.now(),
                "status": "ACTIVE",
            },
        )
        return practitioner

    def _prescription_data(
        self,
        *,
        number,
        patient,
        practitioner,
        organization,
        branch,
        controlled,
        prescription_type,
    ):
        return {
            "prescription_number": number,
            "external_prescription_reference": f"EXT-{number}",
            "patient": patient,
            "practitioner": practitioner,
            "organization": organization,
            "location": branch,
            "prescribing_organization": organization,
            "prescription_date": date.today(),
            "prescription_type": prescription_type,
            "source_channel": "ELECTRONIC",
            "issued_at": timezone.now(),
            "expires_at": timezone.now() + timedelta(days=30),
            "is_controlled_medicine": controlled,
            "repeat_authorization": prescription_type == "REPEAT",
            "repeats_allowed": 2 if prescription_type == "REPEAT" else 0,
            "metadata": {
                "signature_evidence": "SEED-ELECTRONIC-SIGNATURE",
                "controlled_register_category": "DEMONSTRATION",
            },
        }

    def _workflow(
        self,
        *,
        tenant,
        number,
        patient,
        practitioner,
        organization,
        branch,
        pharmacy_location,
        sku,
        medicine,
        pharmacist,
        checker,
        quantity,
        supply_quantity,
        controlled=False,
        prescription_type="ACUTE",
    ):
        prescription = Prescription.all_objects.filter(
            tenant=tenant,
            prescription_number=number,
        ).first()
        if not prescription:
            prescription = PrescriptionIntakeService.receive(
                tenant=tenant,
                actor=pharmacist,
                items=[
                    {
                        "canonical_medicine": medicine,
                        "prescribed_sku": sku,
                        "medication_name": sku.display_name,
                        "prescribed_description_snapshot": sku.display_name,
                        "strength_snapshot": "500 mg",
                        "dosage_form_snapshot": "Tablet",
                        "dosage_instruction": "Take one unit once daily as directed",
                        "dose_amount": Decimal("1"),
                        "dose_unit": "unit",
                        "frequency_per_day": Decimal("1"),
                        "duration_days": int(quantity),
                        "quantity": Decimal(str(quantity)),
                        "unit": sku.package_definition.unit_of_measure,
                        "refills_authorized": 2
                        if prescription_type == "REPEAT"
                        else 0,
                        "is_controlled": controlled,
                        "route": "ORAL",
                        "substitution_policy": "GENERIC_ALLOWED",
                    }
                ],
                **self._prescription_data(
                    number=number,
                    patient=patient,
                    practitioner=practitioner,
                    organization=organization,
                    branch=branch,
                    controlled=controlled,
                    prescription_type=prescription_type,
                ),
            )
        if prescription.supplies.exists():
            return prescription, prescription.supplies.order_by("created_at").first()
        PrescriptionValidationService.validate(
            prescription=prescription,
            actor=pharmacist,
        )
        review = PharmacistReviewService.start(
            prescription=prescription,
            actor=pharmacist,
        )
        if not review.review_completed_at:
            PharmacistReviewService.complete(
                review=review,
                actor=pharmacist,
                outcome="APPROVED_WITH_COUNSELLING",
                notes="Seed clinical review completed.",
            )
        PharmacistVerificationService.verify(
            prescription=prescription,
            actor=pharmacist,
            idempotency_key=f"seed-verify:{number}",
            decision="VERIFIED_WITH_COUNSELLING",
            clinical_justification="Seed review found no unresolved blocking risks.",
        )
        episode = DispensingEpisodeService.create(
            prescription=prescription,
            branch=branch,
            pharmacy_location=pharmacy_location,
            actor=pharmacist,
            idempotency_key=f"seed-episode:{number}",
        )
        item = prescription.items.get()
        DispensingReservationService.reserve(
            episode=episode,
            prescription_item=item,
            quantity=quantity,
            actor=pharmacist,
            idempotency_key=f"seed-reservation:{number}",
            minimum_shelf_life_days=30,
        )
        DispensingAllocationService.allocate(episode=episode, actor=pharmacist)
        lines = DispensingPreparationService.prepare(
            episode=episode,
            actor=pharmacist,
        )
        for line in lines:
            DispensingLabelService.generate(
                dispensing_line=line,
                actor=pharmacist,
            )
        DispensingCheckService.check(
            episode=episode,
            actor=checker,
            checklist={
                "patient": True,
                "medicine": True,
                "strength": True,
                "dosage_form": True,
                "quantity": True,
                "batch": True,
                "expiry": True,
                "instructions": True,
                "warnings": True,
                "package_integrity": True,
            },
            notes="Independent seed final check.",
        )
        PatientCounsellingService.record(
            episode=episode,
            actor=pharmacist,
            counselling_required=True,
            counselling_completed=True,
            topics=["DOSAGE", "ADMINISTRATION", "STORAGE", "ADHERENCE"],
            warnings_explained="Configured warnings reviewed.",
            administration_instructions="Use exactly as directed.",
            storage_guidance="Store according to the product label.",
            adherence_advice="Complete the prescribed course.",
            side_effect_guidance="Seek professional advice for concerning effects.",
            missed_dose_guidance="Follow the approved patient information.",
            language=patient.preferred_language or "en",
        )
        line_quantities = {}
        remaining = Decimal(str(supply_quantity))
        for line in lines:
            if remaining <= 0:
                break
            line_quantity = min(line.quantity_prepared, remaining)
            line_quantities[str(line.id)] = line_quantity
            remaining -= line_quantity
        supply = MedicineSupplyService.supply(
            episode=episode,
            actor=pharmacist,
            idempotency_key=f"seed-supply:{number}",
            line_quantities=line_quantities,
            partial_reason=(
                "INSUFFICIENT_STOCK"
                if Decimal(str(supply_quantity)) < Decimal(str(quantity))
                else ""
            ),
            next_eligible_date=(
                date.today() + timedelta(days=7)
                if Decimal(str(supply_quantity)) < Decimal(str(quantity))
                else None
            ),
        )
        return prescription, supply

    def _clinical_scenario(
        self,
        *,
        tenant,
        number,
        patient,
        practitioner,
        organization,
        branch,
        pharmacist,
        items,
    ):
        prescription = Prescription.all_objects.filter(
            tenant=tenant,
            prescription_number=number,
        ).first()
        if not prescription:
            prescription = PrescriptionIntakeService.receive(
                tenant=tenant,
                actor=pharmacist,
                items=items,
                **self._prescription_data(
                    number=number,
                    patient=patient,
                    practitioner=practitioner,
                    organization=organization,
                    branch=branch,
                    controlled=False,
                    prescription_type="ACUTE",
                ),
            )
        if prescription.legal_validation_state == "PENDING":
            PrescriptionValidationService.validate(
                prescription=prescription,
                actor=pharmacist,
            )
            prescription.refresh_from_db()
        if (
            prescription.legal_validation_state == "PASSED"
            and not prescription.pharmacist_reviews.exists()
        ):
            PharmacistReviewService.start(
                prescription=prescription,
                actor=pharmacist,
            )
        return prescription

    def _repeat_supply(
        self,
        *,
        prescription,
        branch,
        pharmacy_location,
        pharmacist,
        checker,
    ):
        idempotency_key = f"seed-repeat-supply:{prescription.prescription_number}:1"
        existing = prescription.supplies.filter(
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing
        episode = DispensingEpisodeService.create(
            prescription=prescription,
            branch=branch,
            pharmacy_location=pharmacy_location,
            actor=pharmacist,
            idempotency_key=(
                f"seed-repeat-episode:{prescription.prescription_number}:1"
            ),
        )
        item = prescription.items.get()
        DispensingReservationService.reserve(
            episode=episode,
            prescription_item=item,
            quantity=item.quantity,
            actor=pharmacist,
            idempotency_key=(
                f"seed-repeat-reservation:{prescription.prescription_number}:1"
            ),
        )
        DispensingAllocationService.allocate(
            episode=episode,
            actor=pharmacist,
        )
        lines = DispensingPreparationService.prepare(
            episode=episode,
            actor=pharmacist,
        )
        for line in lines:
            DispensingLabelService.generate(
                dispensing_line=line,
                actor=pharmacist,
            )
        DispensingCheckService.check(
            episode=episode,
            actor=checker,
            checklist={
                "patient": True,
                "medicine": True,
                "strength": True,
                "dosage_form": True,
                "quantity": True,
                "batch": True,
                "expiry": True,
                "instructions": True,
                "warnings": True,
                "package_integrity": True,
            },
            notes="Independent repeat-dispensing seed check.",
        )
        PatientCounsellingService.record(
            episode=episode,
            actor=pharmacist,
            counselling_required=True,
            counselling_completed=True,
            topics=["REPEAT_INTERVAL", "ADHERENCE"],
            administration_instructions="Continue exactly as directed.",
        )
        return MedicineSupplyService.supply(
            episode=episode,
            actor=pharmacist,
            idempotency_key=idempotency_key,
            line_quantities={
                str(line.id): line.quantity_prepared for line in lines
            },
        )

    @transaction.atomic
    def handle(self, *args, **options):
        tenant_slug = options["tenant"]
        call_command("seed_sales", tenant=tenant_slug, verbosity=0)
        tenant = Tenant.objects.get(slug=tenant_slug)
        set_current_tenant_id(tenant.id)
        organization = Organization.all_objects.get(tenant=tenant, code="ORG-MAIN")
        branch = Location.all_objects.get(tenant=tenant, code="BR-MAIN-01")
        sku = CommercialSKU.all_objects.get(tenant=tenant, sku_code="SKU-PARA-500")
        batch = InventoryBatch.all_objects.get(
            tenant=tenant,
            manufacturer_batch_number="B-PARA-001",
        )
        vault, _ = InventoryLocation.all_objects.get_or_create(
            tenant=tenant,
            branch=branch,
            location_code="CLINICAL-VAULT",
            defaults={
                "name": "Clinical Dispensing Vault",
                "location_type": InventoryLocation.LocationType.CONTROLLED_VAULT,
                "controlled_drug_capability": True,
            },
        )
        quarantine, _ = InventoryLocation.all_objects.get_or_create(
            tenant=tenant,
            branch=branch,
            location_code="PATIENT-RETURNS",
            defaults={
                "name": "Patient Returns Quarantine",
                "location_type": InventoryLocation.LocationType.QUARANTINE,
                "quarantine_capability": True,
                "returns_capability": True,
            },
        )
        if not InventoryLedgerEntry.all_objects.filter(
            tenant=tenant,
            idempotency_key="seed-clinical-stock-v1",
        ).exists():
            InventoryLedgerService.post_entry(
                tenant=tenant,
                branch=branch,
                location=vault,
                sku=sku,
                inventory_batch=batch,
                entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
                quantity_delta=Decimal("500"),
                unit=sku.package_definition.unit_of_measure,
                base_quantity_delta=Decimal("500"),
                effective_timestamp=timezone.now(),
                source_document_type="CLINICAL_SEED",
                source_document_id="CLINICAL-SEED-STOCK",
                idempotency_key="seed-clinical-stock-v1",
                reason_code="PHASE_5_SEED",
            )
        role, _ = Role.all_objects.update_or_create(
            tenant=tenant,
            code="SEED_CLINICAL_PHARMACIST",
            defaults={
                "name": "Seed Clinical Pharmacist",
                "capabilities": CLINICAL_CAPABILITIES,
                "is_active": True,
                "is_system": True,
            },
        )
        pharmacist = self._user(tenant, "seed-pharmacist", role)
        checker = self._user(tenant, "seed-checking-pharmacist", role)
        patient_nka = self._patient(
            tenant,
            "PAT-NKA",
            preferred_language="en",
        )
        patient_allergy = self._patient(tenant, "PAT-ALLERGY")
        patient_pediatric = self._patient(
            tenant,
            "PAT-PEDIATRIC",
            date_of_birth=date.today() - timedelta(days=365 * 8),
        )
        patient_renal = self._patient(tenant, "PAT-RENAL")
        patient_pregnant = self._patient(tenant, "PAT-PREGNANT", sex="FEMALE")
        PatientClinicalSummary.all_objects.update_or_create(
            tenant=tenant,
            patient=patient_renal,
            defaults={
                "renal_impairment": "IMPAIRED",
                "source": "PHASE_5_SEED",
                "verification_status": "CLINICIAN_VERIFIED",
                "verified_by": pharmacist,
                "verified_at": timezone.now(),
            },
        )
        PatientClinicalSummary.all_objects.update_or_create(
            tenant=tenant,
            patient=patient_pregnant,
            defaults={
                "pregnancy_status": "PREGNANT",
                "source": "PHASE_5_SEED",
                "verification_status": "CLINICIAN_VERIFIED",
                "verified_by": pharmacist,
                "verified_at": timezone.now(),
            },
        )
        PatientClinicalSummary.all_objects.update_or_create(
            tenant=tenant,
            patient=patient_pediatric,
            defaults={
                "weight_kg": Decimal("25"),
                "source": "PHASE_5_SEED",
                "verification_status": "CLINICIAN_VERIFIED",
                "verified_by": pharmacist,
                "verified_at": timezone.now(),
            },
        )
        medicine, _ = Medicine.all_objects.get_or_create(
            tenant=tenant,
            code="MED-SEED-SAFE",
            defaults={
                "generic_name": "Seed demonstration medicine",
                "dosage_form": "Tablet",
                "strength": "500 mg",
                "source": "PHASE_5_SEED",
                "source_version": "1",
            },
        )
        PatientAllergy.all_objects.get_or_create(
            tenant=tenant,
            patient=patient_allergy,
            allergen_code="SEED-INGREDIENT",
            defaults={
                "allergen_name": "Seed ingredient",
                "medicinal_product": medicine,
                "reaction": "Seed confirmed reaction",
                "severity": "HARD_STOP",
                "verification_status": "CLINICIAN_VERIFIED",
                "source": "PHASE_5_SEED",
                "recorded_by": pharmacist,
                "reviewed_by": checker,
                "status": "CONFIRMED",
            },
        )
        if not patient_nka.identifiers.exists():
            PatientGovernanceService.add_identifier(
                patient=patient_nka,
                actor=pharmacist,
                identifier_type="HOSPITAL_NUMBER",
                value="SEED-HOSPITAL-0001",
                verification_status="VERIFIED",
                issuing_authority="DawaTrace demonstration facility",
            )
        active_prescriber = self._prescriber(
            tenant,
            "REG-ACTIVE",
            organization=organization,
        )
        expired_prescriber = self._prescriber(
            tenant,
            "REG-EXPIRED",
            expired=True,
            organization=organization,
        )
        controlled_prescriber = self._prescriber(
            tenant,
            "REG-CONTROLLED",
            controlled=True,
            organization=organization,
        )
        release, _ = ClinicalKnowledgeRelease.all_objects.get_or_create(
            tenant=tenant,
            code="PHASE5-SEED-RULES",
            version="1",
            defaults={
                "source": "DawaTrace demonstration clinical content",
                "source_version": "1",
                "licence": "Internal demonstration only",
                "effective_date": date.today(),
                "is_active": True,
                "content_classification": "DEMONSTRATION",
                "checksum_sha256": "5" * 64,
            },
        )
        ingredient, _ = ActiveIngredient.all_objects.get_or_create(
            tenant=tenant,
            code="SEED-INGREDIENT",
            defaults={"name": "Seed demonstration ingredient"},
        )
        MedicineIngredient.all_objects.get_or_create(
            tenant=tenant,
            medicine=medicine,
            ingredient=ingredient,
        )
        interacting_medicine, _ = Medicine.all_objects.get_or_create(
            tenant=tenant,
            code="MED-SEED-INTERACTOR",
            defaults={
                "generic_name": "Seed interacting demonstration medicine",
                "dosage_form": "Tablet",
                "strength": "100 mg",
                "source": "PHASE_5_SEED",
                "source_version": "1",
            },
        )
        interacting_ingredient, _ = ActiveIngredient.all_objects.get_or_create(
            tenant=tenant,
            code="SEED-INTERACTOR",
            defaults={"name": "Seed interacting ingredient"},
        )
        MedicineIngredient.all_objects.get_or_create(
            tenant=tenant,
            medicine=interacting_medicine,
            ingredient=interacting_ingredient,
        )
        for rule_type, criteria in (
            ("DRUG_DRUG", {"demo_match": False}),
            ("DUPLICATE_THERAPY", {"demo_match": False}),
            ("ALLERGY", {"demo_match": False}),
            ("DOSE_TOO_HIGH", {"maximum_daily_dose": "4"}),
        ):
            ClinicalKnowledgeRule.all_objects.update_or_create(
                release=release,
                rule_id=f"SEED-{rule_type}",
                rule_version="1",
                defaults={
                    "tenant": tenant,
                    "rule_type": rule_type,
                    "primary_code": "SEED-INGREDIENT",
                    "interacting_code": (
                        "SEED-INTERACTOR"
                        if rule_type == "DRUG_DRUG"
                        else ""
                    ),
                    "severity": "HIGH",
                    "evidence_summary": "Demonstration content only.",
                    "explanation": f"Seed {rule_type} finding.",
                    "recommended_action": "Complete pharmacist review.",
                    "override_policy": "PHARMACIST",
                    "criteria": criteria,
                    "effective_date": date.today(),
                },
            )
        base_item = {
            "canonical_medicine": medicine,
            "medication_name": "Seed demonstration medicine",
            "prescribed_description_snapshot": "Seed demonstration medicine",
            "active_ingredient_snapshot": [
                {"code": "SEED-INGREDIENT", "name": ingredient.name}
            ],
            "strength_snapshot": "500 mg",
            "dosage_form_snapshot": "Tablet",
            "dosage_instruction": "Take one tablet once daily",
            "dose_amount": Decimal("1"),
            "dose_unit": "tablet",
            "frequency_per_day": Decimal("1"),
            "duration_days": 5,
            "quantity": Decimal("5"),
            "unit": "TABLET",
            "route": "ORAL",
        }
        interacting_item = {
            **base_item,
            "canonical_medicine": interacting_medicine,
            "medication_name": "Seed interacting demonstration medicine",
            "prescribed_description_snapshot": (
                "Seed interacting demonstration medicine"
            ),
            "active_ingredient_snapshot": [
                {
                    "code": "SEED-INTERACTOR",
                    "name": interacting_ingredient.name,
                }
            ],
            "strength_snapshot": "100 mg",
        }
        self._clinical_scenario(
            tenant=tenant,
            number="RX-SEED-INTERACTION",
            patient=patient_nka,
            practitioner=active_prescriber,
            organization=organization,
            branch=branch,
            pharmacist=pharmacist,
            items=[base_item, interacting_item],
        )
        self._clinical_scenario(
            tenant=tenant,
            number="RX-SEED-DUPLICATE",
            patient=patient_nka,
            practitioner=active_prescriber,
            organization=organization,
            branch=branch,
            pharmacist=pharmacist,
            items=[
                base_item,
                {
                    **base_item,
                    "medication_name": "Seed duplicate therapy item",
                    "prescribed_description_snapshot": (
                        "Seed duplicate therapy item"
                    ),
                },
            ],
        )
        self._clinical_scenario(
            tenant=tenant,
            number="RX-SEED-ALLERGY",
            patient=patient_allergy,
            practitioner=active_prescriber,
            organization=organization,
            branch=branch,
            pharmacist=pharmacist,
            items=[base_item],
        )
        self._clinical_scenario(
            tenant=tenant,
            number="RX-SEED-HIGH-DOSE",
            patient=patient_nka,
            practitioner=active_prescriber,
            organization=organization,
            branch=branch,
            pharmacist=pharmacist,
            items=[
                {
                    **base_item,
                    "dose_amount": Decimal("5"),
                    "dosage_instruction": (
                        "Take five tablets once daily for demonstration"
                    ),
                }
            ],
        )
        invalid_prescription = Prescription.all_objects.filter(
            tenant=tenant,
            prescription_number="RX-SEED-INVALID",
        ).first()
        if not invalid_prescription:
            invalid_prescription = PrescriptionIntakeService.receive(
                tenant=tenant,
                actor=pharmacist,
                items=[base_item],
                **self._prescription_data(
                    number="RX-SEED-INVALID",
                    patient=patient_nka,
                    practitioner=expired_prescriber,
                    organization=organization,
                    branch=branch,
                    controlled=False,
                    prescription_type="ACUTE",
                ),
            )
        if invalid_prescription.legal_validation_state == "PENDING":
            PrescriptionValidationService.validate(
                prescription=invalid_prescription,
                actor=pharmacist,
            )
        controlled_prescription, controlled_supply = self._workflow(
            tenant=tenant,
            number="RX-SEED-CONTROLLED",
            patient=patient_nka,
            practitioner=controlled_prescriber,
            organization=organization,
            branch=branch,
            pharmacy_location=vault,
            sku=sku,
            medicine=medicine,
            pharmacist=pharmacist,
            checker=checker,
            quantity=Decimal("10"),
            supply_quantity=Decimal("5"),
            controlled=True,
            prescription_type="CONTROLLED",
        )
        acute_prescription, acute_supply = self._workflow(
            tenant=tenant,
            number="RX-SEED-ACUTE",
            patient=patient_nka,
            practitioner=active_prescriber,
            organization=organization,
            branch=branch,
            pharmacy_location=vault,
            sku=sku,
            medicine=medicine,
            pharmacist=pharmacist,
            checker=checker,
            quantity=Decimal("2"),
            supply_quantity=Decimal("2"),
        )
        repeat_dispensed_prescription, _ = self._workflow(
            tenant=tenant,
            number="RX-SEED-REPEAT-DISPENSED",
            patient=patient_renal,
            practitioner=active_prescriber,
            organization=organization,
            branch=branch,
            pharmacy_location=vault,
            sku=sku,
            medicine=medicine,
            pharmacist=pharmacist,
            checker=checker,
            quantity=Decimal("2"),
            supply_quantity=Decimal("2"),
            prescription_type="REPEAT",
        )
        self._repeat_supply(
            prescription=repeat_dispensed_prescription,
            branch=branch,
            pharmacy_location=vault,
            pharmacist=pharmacist,
            checker=checker,
        )
        acute_item = acute_prescription.items.get()
        substitute_sku, _ = CommercialSKU.all_objects.get_or_create(
            tenant=tenant,
            sku_code="SKU-PARA-500-SUBSTITUTE",
            defaults={
                "display_name": "Paracetamol 500 mg approved substitute",
                "manufactured_product": sku.manufactured_product,
                "package_definition": sku.package_definition,
                "status": "ACTIVE",
            },
        )
        ClinicalSubstitution.all_objects.get_or_create(
            tenant=tenant,
            prescription=acute_prescription,
            prescription_item=acute_item,
            proposed_sku=substitute_sku,
            defaults={
                "prescribed_sku": sku,
                "equivalence_basis": (
                    "Same configured clinical product and package definition."
                ),
                "prescriber_approved": True,
                "patient_consented": True,
                "pharmacist_approved": True,
                "approved_by": pharmacist,
                "status": "APPROVED",
                "reason": "Seed substitution approval.",
            },
        )
        acute_supply_line = acute_supply.lines.first()
        if acute_supply_line and not acute_supply.reversals.exists():
            DispensingReversalService.reverse(
                supply_line=acute_supply_line,
                actor=pharmacist,
                reason="Seed correction reversal.",
                idempotency_key="seed-reversal:RX-SEED-ACUTE",
                quantity=Decimal("1"),
                physically_returned=True,
                return_condition="UNOPENED",
            )
        patient_return = PatientReturn.all_objects.filter(
            tenant=tenant,
            idempotency_key="seed-return:RX-SEED-ACUTE",
        ).first()
        if not patient_return and acute_supply_line:
            patient_return = PatientReturnService.receive(
                supply=acute_supply,
                actor=pharmacist,
                quarantine_location=quarantine,
                reason="Seed patient return.",
                lines=[
                    {
                        "supply_line_id": acute_supply_line.id,
                        "quantity": Decimal("1"),
                        "condition": "UNOPENED",
                    }
                ],
                idempotency_key="seed-return:RX-SEED-ACUTE",
            )
        if patient_return and patient_return.status != "INSPECTED":
            PatientReturnService.inspect(
                patient_return=patient_return,
                actor=checker,
                quality_decision="RETAIN_IN_QUARANTINE",
                refund_eligibility="PENDING_COMMERCIAL_REVIEW",
            )
        repeat, _ = Prescription.all_objects.get_or_create(
            tenant=tenant,
            prescription_number="RX-SEED-REPEAT",
            defaults={
                **self._prescription_data(
                    number="RX-SEED-REPEAT",
                    patient=patient_renal,
                    practitioner=active_prescriber,
                    organization=organization,
                    branch=branch,
                    controlled=False,
                    prescription_type="REPEAT",
                ),
                "received_at": timezone.now(),
                "created_by": pharmacist,
                "status": "RECEIVED",
                "repeats_remaining": 2,
            },
        )
        if not repeat.items.exists():
            PrescriptionItem.all_objects.create(
                tenant=tenant,
                prescription=repeat,
                canonical_medicine=medicine,
                prescribed_sku=sku,
                prescribed_description_snapshot=sku.display_name,
                strength_snapshot="500 mg",
                dosage_form_snapshot="Tablet",
                medication_name=sku.display_name,
                dosage_instruction="Take one daily",
                dose_amount=1,
                dose_unit="unit",
                frequency_per_day=1,
                duration_days=30,
                quantity=30,
                unit=sku.package_definition.unit_of_measure,
                refills_authorized=2,
                repeats_remaining=2,
                minimum_repeat_interval_days=28,
                route="ORAL",
            )
        clarification_review = PharmacistClinicalReview.all_objects.filter(
            tenant=tenant,
            prescription=repeat,
        ).first()
        if not clarification_review:
            repeat.legal_validation_state = "PASSED"
            repeat.save()
            clarification_review = PharmacistClinicalReview.all_objects.create(
                tenant=tenant,
                prescription=repeat,
                reviewing_pharmacist=pharmacist,
                outcome="INTERVENTION_REQUIRED",
                context_hash="seed-clarification-context",
                version=1,
            )
        intervention = PharmacistIntervention.all_objects.filter(
            tenant=tenant,
            review=clarification_review,
        ).first()
        if not intervention:
            intervention = PharmacistInterventionService.create(
                review=clarification_review,
                actor=pharmacist,
                intervention_type="CLARIFICATION",
                intervention_request="Confirm repeat interval.",
            )
            PharmacistInterventionService.resolve(
                intervention=intervention,
                actor=pharmacist,
                response="Prescriber confirmed the interval.",
                outcome="ACCEPTED",
            )
        self.stdout.write(
            self.style.SUCCESS(
                "Clinical dispensing seed complete: "
                f"{Patient.all_objects.filter(tenant=tenant).count()} patients, "
                f"{Prescription.all_objects.filter(tenant=tenant).count()} prescriptions, "
                f"{controlled_supply.lines.count() + acute_supply.lines.count()} supply lines."
            )
        )
