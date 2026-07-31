from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.identity.models import Role, User, UserRole
from apps.inventory.models import InventoryBatch, InventoryLedgerEntry, InventoryLocation, InventoryReservation
from apps.inventory.services import InventoryLedgerService
from apps.medicines.models import (
    ActiveSubstance,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.patients.models import Patient, PatientAllergy, PatientIdentifier
from apps.patients.services import PatientIdentifierProtector
from apps.fhir.kenya_hie import SYSTEM_CLIENT_REGISTRY_ID
from apps.pos_shift.models import PosRegister
from apps.practitioners.models import Practitioner
from apps.prescription.models import (
    DispensingAllocation,
    DispensingEpisode,
    DispensingLine,
    DispensingReservation,
    PosDeviceHealthRecord,
    PosShiftRecord,
    Prescription,
    PrescriptionItem,
)
from apps.core.demo_seed import (
    add_demo_seed_arguments,
    demo_password_notice,
    ensure_demo_seed_allowed,
    resolve_demo_password,
)
from apps.tenancy.models import Tenant

# Kenya-flavoured till scenarios covering every KPI bucket an operator drills.
SCENARIOS = (
    {
        "code": "8001",
        "status": "PREPARING",
        "payment_state": "PENDING",
        "patient_number": "KE-NBI-24081",
        "first_name": "Grace",
        "last_name": "Kamau",
        "preferred_name": "Grace",
        "sex": "FEMALE",
        "dob": date(1985, 5, 12),
        "phone": "+254712345001",
        "email": "grace.kamau.demo@example.co.ke",
        "county": "Nairobi",
        "cr_id": "CR-DEMO-8001",
        "allergy": ("Penicillin", "Rash / urticaria", "WARNING"),
        "sku_code": "SKU-AMOX-500",
        "med_name": "Amoxicillin 500mg Capsules",
        "substance": ("SUB-AMO", "Amoxicillin"),
        "cmp": ("CMP-AMO-500", "Amoxicillin 500mg"),
        "mmp": ("MMP-AMO-500", "Amoxil 500mg"),
        "batch": "DEMO-BATCH-AMOX-A",
        "qty": Decimal("21"),
        "dose_amount": Decimal("1"),
        "dose_unit": "capsule",
        "frequency_per_day": Decimal("3"),
        "duration_days": 7,
        "indication": "Acute bacterial sinusitis",
        "route": "ORAL",
        "instructions": "Take 1 capsule three times daily for 7 days after food",
        "line_status": "PREPARED",
        "prepared_qty": Decimal("21"),
        "supplied_qty": Decimal("0"),
        "paid_amount": Decimal("0"),
        "list_price": Decimal("450.00"),
    },
    {
        "code": "8002",
        "status": "CHECKING",
        "payment_state": "PENDING",
        "patient_number": "KE-KSM-24082",
        "first_name": "Peter",
        "last_name": "Otieno",
        "sex": "MALE",
        "dob": date(1978, 2, 3),
        "phone": "+254722345002",
        "county": "Kisumu",
        "cr_id": "CR-DEMO-8002",
        "allergy": ("Sulfa drugs", "Breathing difficulty", "HARD_STOP"),
        "sku_code": "SKU-PARA-500",
        "med_name": "Paracetamol 500mg Tablets",
        "substance": ("SUB-PARA", "Paracetamol"),
        "cmp": ("CMP-PARA-500", "Paracetamol 500mg"),
        "mmp": ("MMP-PARA-500", "Panadol Advance 500mg"),
        "batch": "DEMO-BATCH-PARA",
        "qty": Decimal("30"),
        "dose_amount": Decimal("2"),
        "dose_unit": "tablet",
        "frequency_per_day": Decimal("3"),
        "duration_days": 5,
        "indication": "Fever / mild pain",
        "route": "ORAL",
        "instructions": "Take 2 tablets every 8 hours as needed; max 8 tablets/day",
        "line_status": "PREPARED",
        "prepared_qty": Decimal("30"),
        "supplied_qty": Decimal("0"),
        "list_price": Decimal("120.00"),
        "notes": "Pharmacist final check — confirm no hepatic impairment.",
        "extra_lines": (
            {
                "sku_code": "SKU-IBU-400",
                "med_name": "Ibuprofen 400mg Tablets",
                "substance": ("SUB-IBU", "Ibuprofen"),
                "cmp": ("CMP-IBU-400", "Ibuprofen 400mg"),
                "mmp": ("MMP-IBU-400", "Brufen 400mg"),
                "batch": "DEMO-BATCH-IBU",
                "qty": Decimal("20"),
                "instructions": "Take 1 tablet after food up to 3 times daily",
                "line_status": "PREPARED",
                "prepared_qty": Decimal("20"),
                "supplied_qty": Decimal("0"),
                "indication": "Inflammatory pain",
                "route": "ORAL",
            },
        ),
    },
    {
        "code": "8003",
        "status": "READY_FOR_PAYMENT",
        "payment_state": "PENDING",
        "patient_number": "KE-MSA-24083",
        "first_name": "Amina",
        "last_name": "Hassan",
        "sex": "FEMALE",
        "dob": date(1992, 11, 20),
        "phone": "+254733345003",
        "county": "Mombasa",
        "cr_id": "CR-DEMO-8003",
        "sku_code": "SKU-METF-500",
        "med_name": "Metformin 500mg Tablets",
        "substance": ("SUB-METF", "Metformin"),
        "cmp": ("CMP-METF-500", "Metformin 500mg"),
        "mmp": ("MMP-METF-500", "Glucophage 500mg"),
        "batch": "DEMO-BATCH-METF",
        "qty": Decimal("56"),
        "dose_amount": Decimal("1"),
        "dose_unit": "tablet",
        "frequency_per_day": Decimal("2"),
        "duration_days": 28,
        "indication": "Type 2 diabetes mellitus",
        "route": "ORAL",
        "instructions": "Take 1 tablet twice daily with meals for 28 days",
        "line_status": "CHECKED",
        "prepared_qty": Decimal("56"),
        "supplied_qty": Decimal("0"),
        "list_price": Decimal("680.00"),
        "notes": "Checked OK — counsel on GI effects and adherence.",
    },
    {
        "code": "8004",
        "status": "READY_FOR_COLLECTION",
        "payment_state": "PAID",
        "patient_number": "KE-NKI-24084",
        "first_name": "John",
        "last_name": "Mwangi",
        "sex": "MALE",
        "dob": date(1969, 7, 14),
        "phone": "+254701345004",
        "county": "Nakuru",
        "cr_id": "CR-DEMO-8004",
        "sku_code": "SKU-ATOR-20",
        "med_name": "Atorvastatin 20mg Tablets",
        "substance": ("SUB-ATOR", "Atorvastatin"),
        "cmp": ("CMP-ATOR-20", "Atorvastatin 20mg"),
        "mmp": ("MMP-ATOR-20", "Lipitor 20mg"),
        "batch": "DEMO-BATCH-ATOR",
        "qty": Decimal("28"),
        "dose_amount": Decimal("1"),
        "dose_unit": "tablet",
        "frequency_per_day": Decimal("1"),
        "duration_days": 28,
        "indication": "Hyperlipidaemia / secondary prevention",
        "route": "ORAL",
        "instructions": "Take 1 tablet at night; avoid grapefruit juice",
        "line_status": "CHECKED",
        "prepared_qty": Decimal("28"),
        "supplied_qty": Decimal("0"),
        "paid_amount": Decimal("850.00"),
        "list_price": Decimal("850.00"),
        "tender_type": "MPESA",
        "notes": "Paid via M-Pesa — ready for counselling and collection.",
    },
    {
        "code": "8005",
        "status": "SUPPLIED",
        "payment_state": "PAID",
        "patient_number": "KE-NBI-24085",
        "first_name": "Faith",
        "last_name": "Wanjiku",
        "sex": "FEMALE",
        "dob": date(1999, 1, 8),
        "phone": "+254711345005",
        "county": "Nairobi",
        "cr_id": "CR-DEMO-8005",
        "sku_code": "SKU-AZITH-500",
        "med_name": "Azithromycin 500mg Tablets",
        "substance": ("SUB-AZITH", "Azithromycin"),
        "cmp": ("CMP-AZITH-500", "Azithromycin 500mg"),
        "mmp": ("MMP-AZITH-500", "Zithromax 500mg"),
        "batch": "DEMO-BATCH-AZITH",
        "qty": Decimal("3"),
        "dose_amount": Decimal("1"),
        "dose_unit": "tablet",
        "frequency_per_day": Decimal("1"),
        "duration_days": 3,
        "indication": "Community-acquired infection",
        "route": "ORAL",
        "instructions": "Take 1 tablet once daily for 3 days",
        "line_status": "SUPPLIED",
        "prepared_qty": Decimal("3"),
        "supplied_qty": Decimal("3"),
        "paid_amount": Decimal("920.00"),
        "list_price": Decimal("920.00"),
        "completed": True,
        "notes": "Supplied and counselled — complete demo episode.",
    },
    {
        "code": "8006",
        "status": "ON_HOLD",
        "payment_state": "PENDING",
        "patient_number": "KE-ELD-24086",
        "first_name": "Samuel",
        "last_name": "Kiptoo",
        "sex": "MALE",
        "dob": date(1988, 9, 30),
        "phone": "+254720345006",
        "county": "Uasin Gishu",
        "cr_id": "CR-DEMO-8006",
        "sku_code": "SKU-AMOX-500",
        "med_name": "Amoxicillin 500mg Capsules",
        "substance": ("SUB-AMO", "Amoxicillin"),
        "cmp": ("CMP-AMO-500", "Amoxicillin 500mg"),
        "mmp": ("MMP-AMO-500", "Amoxil 500mg"),
        "batch": "DEMO-BATCH-AMOX-A",
        "qty": Decimal("21"),
        "instructions": "Take 1 capsule three times daily for 7 days after food",
        "line_status": "AUTHORIZED",
        "prepared_qty": Decimal("0"),
        "supplied_qty": Decimal("0"),
        "indication": "Chest infection — SHA preauth",
        "route": "ORAL",
        "list_price": Decimal("450.00"),
        "notes": "ON HOLD — awaiting SHA / insurer pre-authorisation callback.",
    },
    {
        "code": "8007",
        "status": "PARTIALLY_SUPPLIED",
        "payment_state": "PAID",
        "patient_number": "KE-NBI-24087",
        "first_name": "Mary",
        "last_name": "Njeri",
        "sex": "FEMALE",
        "dob": date(1975, 4, 18),
        "phone": "+254713345007",
        "county": "Nairobi",
        "cr_id": "CR-DEMO-8007",
        "sku_code": "SKU-INS-NPH",
        "med_name": "Insulin NPH 100 IU/ml Vial",
        "substance": ("SUB-INS", "Insulin human"),
        "cmp": ("CMP-INS-NPH", "Insulin NPH"),
        "mmp": ("MMP-INS-NPH", "Insulatard HM"),
        "batch": "DEMO-BATCH-INS",
        "qty": Decimal("10"),
        "dose_amount": Decimal("10"),
        "dose_unit": "unit",
        "frequency_per_day": Decimal("1"),
        "duration_days": 10,
        "indication": "Diabetes mellitus — basal insulin",
        "route": "SC",
        "instructions": "Inject 10 units subcutaneously at night; refrigerate 2–8°C",
        "line_status": "PARTIALLY_SUPPLIED",
        "prepared_qty": Decimal("10"),
        "supplied_qty": Decimal("5"),
        "paid_amount": Decimal("2100.00"),
        "list_price": Decimal("2100.00"),
        "notes": "Cold-chain partial supply — 5 vials issued; remainder due tomorrow.",
    },
    {
        "code": "8008",
        "status": "CHECKING",
        "payment_state": "PENDING",
        "patient_number": "KE-KSI-24088",
        "first_name": "Daniel",
        "last_name": "Barasa",
        "sex": "MALE",
        "dob": date(1955, 12, 1),
        "phone": "+254714345008",
        "county": "Kakamega",
        "cr_id": "CR-DEMO-8008",
        "sku_code": "SKU-MORPH-10",
        "med_name": "Morphine Sulphate 10mg Tablets (CD)",
        "substance": ("SUB-MORPH", "Morphine"),
        "cmp": ("CMP-MORPH-10", "Morphine 10mg"),
        "mmp": ("MMP-MORPH-10", "MST Continus 10mg"),
        "batch": "DEMO-BATCH-CTRL",
        "qty": Decimal("14"),
        "dose_amount": Decimal("1"),
        "dose_unit": "tablet",
        "frequency_per_day": Decimal("2"),
        "duration_days": 7,
        "indication": "Severe cancer pain — palliative",
        "route": "ORAL",
        "instructions": "Take 1 tablet every 12 hours for pain (controlled drug)",
        "line_status": "PREPARED",
        "prepared_qty": Decimal("14"),
        "supplied_qty": Decimal("0"),
        "controlled": True,
        "list_price": Decimal("1850.00"),
        "notes": "Schedule II / CD register — dual witness required at collection.",
    },
    {
        "code": "8009",
        "status": "PREPARING",
        "payment_state": "PENDING",
        "patient_number": "KE-NBI-24089",
        "first_name": "Brian",
        "last_name": "Omondi",
        "sex": "MALE",
        "dob": date(2018, 3, 22),
        "phone": "+254715345009",
        "county": "Nairobi",
        "cr_id": "CR-DEMO-8009",
        "guardian": {"name": "Jane Omondi", "relationship": "Mother", "phone": "+254715345019"},
        "sku_code": "SKU-AMOX-SUSP",
        "med_name": "Amoxicillin 125mg/5ml Suspension",
        "substance": ("SUB-AMO", "Amoxicillin"),
        "cmp": ("CMP-AMO-SUSP", "Amoxicillin 125mg/5ml"),
        "mmp": ("MMP-AMO-SUSP", "Amoxil Suspension"),
        "batch": "DEMO-BATCH-SUSP",
        "qty": Decimal("100"),
        "dose_amount": Decimal("5"),
        "dose_unit": "ml",
        "frequency_per_day": Decimal("3"),
        "duration_days": 5,
        "indication": "Paediatric otitis media",
        "route": "ORAL",
        "instructions": "Give 5 ml three times daily for 5 days; shake well; refrigerate after reconstitution",
        "line_status": "AUTHORIZED",
        "prepared_qty": Decimal("0"),
        "supplied_qty": Decimal("0"),
        "list_price": Decimal("380.00"),
        "notes": "Paediatric — verify weight-based dose with caregiver present.",
    },
    {
        "code": "8010",
        "status": "READY_FOR_PAYMENT",
        "payment_state": "PENDING",
        "patient_number": "KE-NBI-24090",
        "first_name": "Mercy",
        "last_name": "Achieng",
        "sex": "FEMALE",
        "dob": date(1994, 8, 9),
        "phone": "+254716345010",
        "county": "Nairobi",
        "cr_id": "CR-DEMO-8010",
        "allergy": ("Latex", "Contact dermatitis", "INFO"),
        "sku_code": "SKU-FOLIC-5",
        "med_name": "Folic Acid 5mg Tablets",
        "substance": ("SUB-FOLIC", "Folic acid"),
        "cmp": ("CMP-FOLIC-5", "Folic acid 5mg"),
        "mmp": ("MMP-FOLIC-5", "Folic Acid 5mg"),
        "batch": "DEMO-BATCH-FOLIC",
        "qty": Decimal("30"),
        "dose_amount": Decimal("1"),
        "dose_unit": "tablet",
        "frequency_per_day": Decimal("1"),
        "duration_days": 30,
        "indication": "Antenatal supplementation",
        "route": "ORAL",
        "instructions": "Take 1 tablet once daily",
        "line_status": "CHECKED",
        "prepared_qty": Decimal("30"),
        "supplied_qty": Decimal("0"),
        "list_price": Decimal("150.00"),
        "notes": "ANC visit — pregnancy-safe counselling completed.",
        "extra_lines": (
            {
                "sku_code": "SKU-FEFOL",
                "med_name": "Ferrous Sulphate + Folic Acid Tabs",
                "substance": ("SUB-FE", "Ferrous sulphate"),
                "cmp": ("CMP-FEFOL", "Ferrous sulphate + folic acid"),
                "mmp": ("MMP-FEFOL", "Fesovit / IFAS"),
                "batch": "DEMO-BATCH-FEFOL",
                "qty": Decimal("30"),
                "instructions": "Take 1 tablet daily with food; may darken stools",
                "line_status": "CHECKED",
                "prepared_qty": Decimal("30"),
                "supplied_qty": Decimal("0"),
                "indication": "Antenatal IFAS",
                "route": "ORAL",
            },
        ),
    },
)


class Command(BaseCommand):
    help = "Seed multi-scenario POS dispensing queue data for till drill-down"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default="tibatrace-demo", help="Tenant slug to seed")
        add_demo_seed_arguments(parser)

    def handle(self, *args, **options):
        # Fail closed before touching the database: this command creates a
        # pharmacist, a cashier and a CDS approver.
        ensure_demo_seed_allowed(allow_demo_seed=options["allow_demo_seed"])
        self._password, self._password_generated = resolve_demo_password(
            allow_generated_fallback=options["allow_demo_seed"]
        )

        tenant_slug = options["tenant"]
        self.stdout.write(f"Seeding POS dispensing scenarios for tenant '{tenant_slug}'...")

        tenant, _ = Tenant.objects.get_or_create(
            slug=tenant_slug,
            defaults={"name": f"Tenant {tenant_slug}", "status": Tenant.STATUS_ACTIVE},
        )
        org, _ = Organization.all_objects.get_or_create(
            tenant=tenant, code="DEMO-ORG", defaults={"name": "Demo Pharmacy Org"}
        )
        branch, _ = Location.all_objects.get_or_create(
            tenant=tenant,
            code="DEMO-BR",
            defaults={"organization": org, "name": "Main Dispensary", "status": "ACTIVE"},
        )
        wh, _ = InventoryLocation.all_objects.get_or_create(
            tenant=tenant,
            branch=branch,
            location_code="DEMO-WH",
            defaults={"name": "Pharmacy Store"},
        )

        rph = self._user(tenant, "demo_dispensing_rph", display_name="Dr. Faith Wanjiru (Pharmacist)")
        cashier = self._user(tenant, "demo_dispensing_cashier", display_name="Amina Otieno (Cashier)")
        approver = self._user(tenant, "demo_cds_approver", display_name="James Kariuki (CDS Approver)")
        self._roles(tenant, rph, cashier, approver)

        practitioner, _ = Practitioner.all_objects.get_or_create(
            tenant=tenant,
            registration_number="A12345",
            defaults={
                "last_name": "Ochieng",
                "first_name": "David",
                "profession": "DOCTOR",
                "organization": org,
                "status": "ACTIVE",
                "verification_state": "VERIFIED",
            },
        )

        dose_form, _ = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})
        pkg, _ = PackageDefinition.objects.get_or_create(
            code="PACK-DEMO",
            defaults={
                "description": "Dispensing pack",
                "unit_of_measure": "UNIT",
                "is_dispensing_unit": True,
            },
        )

        for scenario in SCENARIOS:
            self._seed_scenario(
                tenant=tenant,
                org=org,
                branch=branch,
                wh=wh,
                rph=rph,
                practitioner=practitioner,
                dose_form=dose_form,
                pkg=pkg,
                scenario=scenario,
            )

        PosShiftRecord.all_objects.get_or_create(
            tenant=tenant,
            shift_number="DEMO-SHIFT-01",
            defaults={
                "cashier": cashier,
                "pharmacist": rph,
                "location": branch,
                "status": "OPEN",
                "controlled_stock_start_count": 100,
            },
        )

        PosDeviceHealthRecord.all_objects.update_or_create(
            tenant=tenant,
            device_id="DEMO-TERM-01",
            defaults={
                "device_type": "TERMINAL",
                "status": "OK",
                "printer_paper_level": "OK",
                "scanner_connected": True,
            },
        )

        PosRegister.all_objects.update_or_create(
            tenant=tenant,
            code="HQ-DEMO-TILL",
            defaults={
                "name": "Main Dispensary Till 01",
                "location": branch,
                "device_id": "DEMO-TERM-01",
                "expected_float": Decimal("5000.00"),
                "state": "OPEN",
            },
        )
        PosRegister.all_objects.update_or_create(
            tenant=tenant,
            code="DEMO-TILL-01",
            defaults={
                "name": "Counter Terminal 01",
                "location": branch,
                "device_id": "DEMO-TERM-01",
                "expected_float": Decimal("3000.00"),
                "state": "OPEN",
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(SCENARIOS)} Kenya POS dispensing scenarios for '{tenant_slug}'.\n"
                f"  Tenant:       {tenant_slug}\n"
                f"  Pharmacist:   demo_dispensing_rph\n"
                f"  Cashier:      demo_dispensing_cashier\n"
                f"  CDS approver: demo_cds_approver\n"
                + demo_password_notice(self._password, was_generated=self._password_generated)
            )
        )

    def _user(self, tenant, username, *, display_name):
        parts = display_name.replace("(", "").replace(")", "").split()
        first = parts[0] if parts else username
        last = " ".join(parts[1:]) if len(parts) > 1 else "Demo"
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={
                "tenant": tenant,
                "first_name": first[:150],
                "last_name": last[:150],
            },
        )
        if user.tenant_id != tenant.pk:
            user.tenant = tenant
        user.first_name = first[:150]
        user.last_name = last[:150]
        user.set_password(self._password)
        user.is_active = True
        user.save()
        return user

    def _roles(self, tenant, rph, cashier, approver=None):
        pharmacist_role, _ = Role.all_objects.get_or_create(
            tenant=tenant,
            code="DEMO_PHARMACIST",
            defaults={
                "name": "Demo pharmacist",
                "capabilities": [
                    "dispensing.prepare",
                    "dispensing.check",
                    "dispensing.supply",
                    "dispensing.counsel",
                    "dispensing.complete",
                    "dispensing.read",
                    "prescriptions.pharmacist_verify",
                    "prescriptions.controlled_verify",
                    "prescriptions.approve",
                    "prescriptions.record_payment",
                    "cds.override",
                ],
            },
        )
        cashier_role, _ = Role.all_objects.get_or_create(
            tenant=tenant,
            code="DEMO_CASHIER",
            defaults={
                "name": "Demo cashier",
                "capabilities": ["dispensing.read", "prescriptions.record_payment"],
            },
        )
        desired = [
            "dispensing.prepare",
            "dispensing.check",
            "dispensing.supply",
            "dispensing.counsel",
            "dispensing.complete",
            "dispensing.read",
            "prescriptions.pharmacist_verify",
            "prescriptions.controlled_verify",
            "prescriptions.approve",
            "prescriptions.record_payment",
            "cds.override",
        ]
        if set(pharmacist_role.capabilities or []) != set(desired):
            pharmacist_role.capabilities = desired
            pharmacist_role.save(update_fields=["capabilities", "updated_at"])
        UserRole.all_objects.get_or_create(tenant=tenant, user=rph, role=pharmacist_role)
        UserRole.all_objects.get_or_create(tenant=tenant, user=cashier, role=cashier_role)
        if approver is not None:
            UserRole.all_objects.get_or_create(tenant=tenant, user=approver, role=pharmacist_role)

    def _seed_scenario(self, *, tenant, org, branch, wh, rph, practitioner, dose_form, pkg, scenario):
        patient, _ = Patient.all_objects.update_or_create(
            tenant=tenant,
            internal_reference_id=f"PAT-REF-{scenario['code']}",
            defaults={
                "patient_number": scenario["patient_number"],
                "last_name": scenario["last_name"],
                "first_name": scenario["first_name"],
                "preferred_name": scenario.get("preferred_name", scenario["first_name"]),
                "sex": scenario["sex"],
                "date_of_birth": scenario["dob"],
                "phone": scenario.get("phone", ""),
                "email": scenario.get("email", ""),
                "address": {
                    "country": "KE",
                    "county": scenario.get("county", "Nairobi"),
                    "city": scenario.get("county", "Nairobi"),
                    "line": ["Demo Pharmacy Catchment"],
                },
                "guardian_or_caregiver": scenario.get("guardian") or {},
                "preferred_language": "en",
                "verification_status": "VERIFIED",
                "consent_status": "RECORDED",
                "external_patient_reference": scenario.get("cr_id", ""),
                "is_active": True,
                "metadata": {
                    "demo": True,
                    "scenario": scenario["code"],
                    "list_price_kes": str(scenario.get("list_price", "")),
                },
            },
        )
        cr_id = scenario.get("cr_id")
        if cr_id:
            existing = PatientIdentifier.all_objects.filter(
                tenant=tenant, patient=patient, system=SYSTEM_CLIENT_REGISTRY_ID
            ).first()
            if existing is None:
                normalized = PatientIdentifierProtector.normalize(cr_id)
                PatientIdentifier.all_objects.create(
                    tenant=tenant,
                    patient=patient,
                    system=SYSTEM_CLIENT_REGISTRY_ID,
                    value=cr_id,
                    identifier_type="OTHER",
                    value_hash=PatientIdentifierProtector.digest(
                        tenant_id=patient.tenant_id,
                        identifier_type="OTHER",
                        value=normalized,
                    ),
                    protected_value=PatientIdentifierProtector.protect(
                        tenant_id=patient.tenant_id,
                        value=normalized,
                    ),
                    last_four=normalized[-4:],
                    verification_status="VERIFIED",
                    issuing_authority="Kenya Client Registry (demo)",
                )

        allergy = scenario.get("allergy")
        if allergy:
            allergen, reaction, severity = allergy
            PatientAllergy.all_objects.update_or_create(
                tenant=tenant,
                patient=patient,
                allergen_name=allergen,
                defaults={
                    "reaction": reaction,
                    "severity": severity,
                    "status": "CONFIRMED",
                    "verification_status": "CLINICIAN_VERIFIED",
                    "source": "DEMO_SEED",
                    "is_active": True,
                    "notes": "Seeded demo allergy for till CDS / counselling",
                },
            )

        controlled = bool(scenario.get("controlled"))
        rx, _ = Prescription.all_objects.update_or_create(
            tenant=tenant,
            prescription_number=f"DEMO-RX-{scenario['code']}",
            defaults={
                "patient": patient,
                "practitioner": practitioner,
                "organization": org,
                "location": branch,
                "status": "READY_FOR_DISPENSING",
                "prescription_type": "CONTROLLED" if controlled else "ACUTE",
                "is_controlled_medicine": controlled,
                "issued_at": timezone.now() - timedelta(hours=2),
                "pharmacist_verification_state": "VERIFIED",
                "clinical_review_state": "COMPLETED",
                "legal_validation_state": "PASSED",
            },
        )

        lines = [scenario, *scenario.get("extra_lines", ())]
        for index, line in enumerate(lines):
            line_spec = scenario if index == 0 else line
            self._seed_line(
                tenant=tenant,
                branch=branch,
                wh=wh,
                rph=rph,
                dose_form=dose_form,
                pkg=pkg,
                rx=rx,
                scenario=scenario,
                line=line_spec,
                line_index=index,
                controlled=controlled and index == 0,
            )

        episode, created = DispensingEpisode.all_objects.get_or_create(
            tenant=tenant,
            dispensing_number=f"DEMO-DISP-{scenario['code']}",
            defaults={
                "prescription": rx,
                "patient": patient,
                "branch": branch,
                "pharmacy_location": wh,
                "pharmacist": rph,
                "status": scenario["status"],
                "payment_state": scenario["payment_state"],
                "paid_amount": scenario.get("paid_amount", Decimal("0")),
                "payment_reference": f"PAY-{scenario['code']}" if scenario["payment_state"] == "PAID" else "",
                "tender_type": scenario.get("tender_type", "CASH"),
                "notes": scenario.get("notes", ""),
                "idempotency_key": f"{tenant.slug}-DEMO-EPISODE-KEY-{scenario['code']}",
                "completed_at": timezone.now() if scenario.get("completed") else None,
            },
        )
        if not created:
            episode.status = scenario["status"]
            episode.payment_state = scenario["payment_state"]
            episode.paid_amount = scenario.get("paid_amount", episode.paid_amount)
            episode.tender_type = scenario.get("tender_type", episode.tender_type or "CASH")
            episode.notes = scenario.get("notes", episode.notes)
            if scenario.get("completed") and not episode.completed_at:
                episode.completed_at = timezone.now()
            episode.save()

        # Attach allocations/lines for each prescription item on this Rx.
        for index, line in enumerate(lines):
            line_spec = scenario if index == 0 else line
            sku_code = line_spec.get("sku_code", scenario["sku_code"])
            rx_item = PrescriptionItem.all_objects.filter(
                tenant=tenant, prescription=rx, prescribed_sku__sku_code=sku_code
            ).first()
            if rx_item is None:
                continue
            sku = rx_item.prescribed_sku
            batch = InventoryBatch.all_objects.filter(
                tenant=tenant,
                sku=sku,
                manufacturer_batch_number=line_spec.get("batch", scenario["batch"]),
            ).first()
            if batch is None:
                batch = InventoryBatch.all_objects.filter(tenant=tenant, sku=sku).first()
            if batch is None:
                continue
            qty = line_spec.get("qty", scenario["qty"])
            inv_key = f"{tenant.slug}-DEMO-INV-RES-{scenario['code']}-{index}"
            inv_res = InventoryReservation.all_objects.filter(idempotency_key=inv_key).first()
            if inv_res is None:
                inv_res = InventoryReservation.all_objects.create(
                    tenant=tenant,
                    idempotency_key=inv_key,
                    branch=branch,
                    source_location=wh,
                    sku=sku,
                    requested_quantity=qty,
                    unit="UNIT",
                    purpose="DEMO_DISPENSING",
                )
            disp_key = f"{tenant.slug}-DEMO-DISP-RES-{scenario['code']}-{index}"
            res = DispensingReservation.all_objects.filter(idempotency_key=disp_key).first()
            if res is None:
                res = DispensingReservation.all_objects.create(
                    tenant=tenant,
                    idempotency_key=disp_key,
                    episode=episode,
                    prescription_item=rx_item,
                    inventory_reservation=inv_res,
                    quantity=qty,
                )
            alloc, _ = DispensingAllocation.all_objects.get_or_create(
                reservation=res,
                inventory_batch=batch,
                location=wh,
                defaults={
                    "tenant": tenant,
                    "episode": episode,
                    "prescription_item": rx_item,
                    "quantity": qty,
                },
            )
            DispensingLine.all_objects.update_or_create(
                episode=episode,
                inventory_allocation=alloc,
                defaults={
                    "tenant": tenant,
                    "prescription_item": rx_item,
                    "prescribed_sku": sku,
                    "supplied_sku": sku,
                    "inventory_batch": batch,
                    "quantity_authorized": qty,
                    "quantity_prepared": line_spec.get(
                        "prepared_qty", scenario.get("prepared_qty", qty)
                    ),
                    "quantity_supplied": line_spec.get(
                        "supplied_qty", scenario.get("supplied_qty", Decimal("0"))
                    ),
                    "unit": "UNIT",
                    "package_definition": pkg,
                    "batch_number_snapshot": line_spec.get("batch", scenario["batch"]),
                    "expiry_date_snapshot": batch.expiry_date,
                    "dosage_label_instructions": line_spec.get(
                        "instructions", scenario["instructions"]
                    ),
                    "status": line_spec.get("line_status", scenario["line_status"]),
                    "prepared_by": rph,
                },
            )

    def _seed_line(self, *, tenant, branch, wh, rph, dose_form, pkg, rx, scenario, line, line_index, controlled):
        sub_code, sub_name = line["substance"]
        ActiveSubstance.all_objects.get_or_create(
            tenant=tenant,
            code=sub_code,
            defaults={
                "canonical_name": sub_name,
                "display_name": sub_name,
                "search_name": sub_name.lower(),
            },
        )
        cmp_code, cmp_name = line["cmp"]
        cmp, _ = ClinicalMedicinalProduct.all_objects.get_or_create(
            tenant=tenant,
            code=cmp_code,
            defaults={"canonical_name": cmp_name, "dose_form": dose_form},
        )
        mmp_code, brand = line["mmp"]
        mmp, _ = ManufacturedMedicinalProduct.all_objects.get_or_create(
            tenant=tenant,
            code=mmp_code,
            defaults={"brand_name": brand, "clinical_product": cmp},
        )
        sku, _ = CommercialSKU.all_objects.get_or_create(
            tenant=tenant,
            sku_code=line["sku_code"],
            defaults={
                "display_name": line["med_name"],
                "manufactured_product": mmp,
                "package_definition": pkg,
                "status": "ACTIVE",
                "is_saleable": True,
                "is_dispensable": True,
            },
        )
        batch, _ = InventoryBatch.all_objects.get_or_create(
            tenant=tenant,
            manufactured_product=mmp,
            manufacturer_batch_number=line["batch"],
            defaults={
                "sku": sku,
                "expiry_date": date.today() + timedelta(days=800),
                "quality_status": "RELEASED",
            },
        )
        ledger_key = f"{tenant.slug}-DEMO-LEDGER-{scenario['code']}-{line_index}"
        if not InventoryLedgerEntry.all_objects.filter(tenant=tenant, idempotency_key=ledger_key).exists():
            InventoryLedgerService.post_entry(
                tenant=tenant,
                branch=branch,
                location=wh,
                sku=sku,
                inventory_batch=batch,
                entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
                quantity_delta=Decimal("500"),
                unit="UNIT",
                base_quantity_delta=Decimal("500"),
                effective_timestamp=timezone.now(),
                source_document_type="DemoReceipt",
                source_document_id=f"{tenant.slug}-DEMO-REC-{scenario['code']}-{line_index}",
                idempotency_key=ledger_key,
                actor=rph,
            )

        rx_item, _ = PrescriptionItem.all_objects.update_or_create(
            tenant=tenant,
            prescription=rx,
            prescribed_sku=sku,
            defaults={
                "medication_name": line["med_name"],
                "dosage_instruction": line["instructions"],
                "quantity": line["qty"],
                "dose_amount": line.get("dose_amount"),
                "dose_unit": line.get("dose_unit", ""),
                "frequency_per_day": line.get("frequency_per_day"),
                "duration_days": line.get("duration_days"),
                "route": line.get("route", "ORAL"),
                "indication": line.get("indication", ""),
                "is_controlled": controlled,
                "status": "ACTIVE",
            },
        )
        return rx_item
