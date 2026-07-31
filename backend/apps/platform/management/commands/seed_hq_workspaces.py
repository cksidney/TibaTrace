"""Populate the HQ workspaces for every operational tenant.

The command only adds rows identified by stable HQ-DEMO business keys. Existing
tenant data is reused where practical and is never deleted or rewritten.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.service import log_audit
from apps.cds.models import ClinicalKnowledgeRelease
from apps.clinical.models import ClinicalCondition, ClinicalEncounter, ClinicalObservation
from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id
from apps.fhir.models import FHIRIdempotencyRecord
from apps.identity.models import Role, ServiceAccount, User, UserRole
from apps.identity.services import UserAdministrationService
from apps.inventory.models import InventoryBatch, InventoryBalance, InventoryLedgerEntry, InventoryLocation
from apps.inventory.services import InventoryLedgerService, InventoryReceiptService
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.patients.models import Patient
from apps.platform.models import PosRelease
from apps.platform.release_storage import ensure_local_artifact
from apps.pos_shift.models import (
    BusinessDay,
    CashDeclaration,
    CashMovement,
    OperatorShift,
    PosRegister,
    RegisterSession,
)
from apps.practitioners.models import Practitioner
from apps.prescription.models import Prescription, PrescriptionItem
from apps.pricing.models import PriceAssignment, PriceBook, PriceBookEntry, PriceBookVersion
from apps.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseRequisition,
    ReceivedBatch,
    ReceivingInspection,
    Supplier,
    SupplierQualification,
    ThreeWayMatch,
)
from apps.procurement.services import (
    GoodsReceivingService,
    ProcurementService,
    QualityService,
    SupplierGovernanceService,
    ThreeWayMatchService,
)
from apps.sales.models import Quotation, SalesOrder
from apps.tenancy.models import Tenant
from apps.terminology.models import (
    FHIRCodeSystemRegistration,
    FHIRTerminologyVersion,
    FHIRValueSetRegistration,
)
from apps.workflows.models import DomainEvent


class Command(BaseCommand):
    help = "Seed cash, pricing, inventory, procurement, insurance and access data for active tenants."

    MODEL_GROUPS = {
        "cash": (PosRegister, BusinessDay, RegisterSession, CashDeclaration, CashMovement),
        "pricing": (PriceBook, PriceBookVersion, PriceBookEntry, PriceAssignment),
        "inventory": (InventoryLocation, InventoryBatch, InventoryLedgerEntry, InventoryBalance),
        "procurement": (
            Supplier,
            PurchaseRequisition,
            PurchaseOrder,
            GoodsReceipt,
            ReceivedBatch,
            ThreeWayMatch,
        ),
        "insurance": (),
        "access": (Role, UserRole, ServiceAccount),
        "clinical": (
            ClinicalKnowledgeRelease,
            ClinicalEncounter,
            ClinicalCondition,
            ClinicalObservation,
            Prescription,
            FHIRCodeSystemRegistration,
            FHIRValueSetRegistration,
            FHIRIdempotencyRecord,
        ),
        "commerce": (Quotation, SalesOrder),
        "governance": (AuditEvent, DomainEvent),
    }

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="tenant_slug", help="Seed only this active tenant slug.")

    def handle(self, *args, **options):
        tenants = Tenant.objects.filter(status=Tenant.STATUS_ACTIVE)
        tenant_slug = options.get("tenant_slug")
        if tenant_slug:
            tenants = tenants.filter(slug=tenant_slug)
        tenants = list(tenants)
        if not tenants:
            suffix = f" matching '{tenant_slug}'" if tenant_slug else ""
            raise CommandError(f"No ACTIVE tenants found{suffix}.")

        self._seed_platform_releases()
        for tenant in tenants:
            token = set_current_tenant_id(tenant.pk)
            try:
                self._seed_tenant(tenant)
            finally:
                reset_current_tenant_id(token)
        self.stdout.write(self.style.SUCCESS(f"HQ workspace seeding complete for {len(tenants)} tenant(s)."))

    @transaction.atomic
    def _seed_tenant(self, tenant):
        before = self._counts(tenant)
        self.stdout.write(f"\n[{tenant.slug}] Seeding HQ workspaces...")

        organization, branch = self._organization_and_branch(tenant)
        operator, supervisor = self._users_and_roles(tenant)
        sku = self._catalogue(tenant)
        self._cash(tenant, branch, operator, supervisor)
        self._pricing(tenant, branch, sku)
        self._inventory(tenant, branch, sku, operator)
        self._procurement(tenant, branch, sku, operator, supervisor)
        self._clinical(tenant, organization, branch, sku)
        self._governance(tenant, operator)
        call_command("seed_insurance_demo", tenant=tenant.slug, verbosity=0)
        call_command("seed_sales", tenant=tenant.slug, verbosity=0)
        call_command("seed_pos_dispensing_demo", tenant=tenant.slug, verbosity=0)

        after = self._counts(tenant)
        from apps.insurance.models import Insurer, PrescriptionClaim

        before["insurance"] = before.get("insurance", 0)
        after["insurance"] = (
            Insurer.all_objects.filter(tenant=tenant).count()
            + PrescriptionClaim.all_objects.filter(tenant=tenant).count()
        )
        self.stdout.write(f"[{tenant.slug}] Summary:")
        for group in (
            "cash",
            "pricing",
            "inventory",
            "procurement",
            "insurance",
            "access",
            "clinical",
            "commerce",
            "governance",
        ):
            created = after[group] - before[group]
            disposition = f"created {created}" if created else "skipped (already populated)"
            self.stdout.write(f"  {group:<10} {disposition}; total rows {after[group]}")
        self.stdout.write(
            self.style.SUCCESS(
                f"[{tenant.slug}] Ready using branch '{branch.code}' and organization '{organization.code}'."
            )
        )

    def _counts(self, tenant):
        counts = {}
        for group, models in self.MODEL_GROUPS.items():
            counts[group] = sum(model.all_objects.filter(tenant=tenant).count() for model in models)
        if not self.MODEL_GROUPS["insurance"]:
            from apps.insurance.models import Insurer, PrescriptionClaim

            counts["insurance"] = (
                Insurer.all_objects.filter(tenant=tenant).count()
                + PrescriptionClaim.all_objects.filter(tenant=tenant).count()
            )
        return counts

    def _seed_platform_releases(self):
        now = timezone.now()
        kits = (
            {
                "platform": PosRelease.Platform.WINDOWS,
                "version": "1.0.0",
                "build_number": 100,
                "object_key": "releases/windows/1.0.0/TibaTrace-POS-Managed-Install-1.0.0.zip",
                "minimum_os": "Windows 10",
                "operations_impact": (
                    "Aligns clinical screening and cash controls with the HQ "
                    "operating workflow."
                ),
                "release_notes": (
                    "Windows till managed install kit. Extract and run "
                    "Install-TibaTracePOS.ps1 on the counter PC (Administrator "
                    "preferred; local user install is used when elevation is unavailable)."
                ),
                "files": {
                    "Install-TibaTracePOS.ps1": (
                        "Write-Host 'Installing TibaTrace POS (Windows managed kit)…'\n"
                        "$isAdmin = ([Security.Principal.WindowsPrincipal] "
                        "[Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole("
                        "[Security.Principal.WindowsBuiltInRole]::Administrator)\n"
                        "if ($isAdmin) {\n"
                        "  $target = Join-Path $env:ProgramFiles 'TibaTrace\\POS'\n"
                        "} else {\n"
                        "  Write-Host 'Not elevated — installing for the current user.'\n"
                        "  $target = Join-Path $env:LOCALAPPDATA 'TibaTrace\\POS'\n"
                        "}\n"
                        "New-Item -ItemType Directory -Force -Path $target | Out-Null\n"
                        "Copy-Item -Force (Join-Path $PSScriptRoot 'README.txt') (Join-Path $target 'README.txt')\n"
                        "Copy-Item -Force (Join-Path $PSScriptRoot 'tibatrace-pos.cmd') (Join-Path $target 'tibatrace-pos.cmd')\n"
                        "$shortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'TibaTrace POS.lnk'\n"
                        "$shell = New-Object -ComObject WScript.Shell\n"
                        "$link = $shell.CreateShortcut($shortcut)\n"
                        "$link.TargetPath = Join-Path $target 'tibatrace-pos.cmd'\n"
                        "$link.WorkingDirectory = $target\n"
                        "$link.Save()\n"
                        "Write-Host \"Installed to $target\"\n"
                        "Write-Host 'Open the desktop shortcut to launch the till.'\n"
                    ).encode("utf-8"),
                    "tibatrace-pos.cmd": (
                        "@echo off\r\n"
                        "echo TibaTrace POS Windows counter shell\r\n"
                        "echo Point this till at http://127.0.0.1:8000/pos/\r\n"
                        "start \"\" http://127.0.0.1:8000/pos/\r\n"
                        "pause\r\n"
                    ).encode("utf-8"),
                    "README.txt": (
                        "TibaTrace POS — Windows managed install kit\n"
                        "==========================================\n"
                        "1. Right-click Install-TibaTracePOS.ps1 → Run with PowerShell.\n"
                        "   Prefer Run as Administrator for a machine-wide install.\n"
                        "2. Open the desktop shortcut or tibatrace-pos.cmd.\n"
                        "3. Sign in with your pharmacy operator account.\n"
                    ).encode("utf-8"),
                },
            },
            {
                "platform": PosRelease.Platform.ANDROID,
                "version": "0.1.0-alpha.2",
                "build_number": 2,
                "object_key": "releases/android/0.1.0-alpha.2/TibaTrace-POS-0.1.0-alpha.2-sideload.zip",
                "minimum_os": "Android 10",
                "operations_impact": (
                    "Aligns mobile clinical decisions and cash handling with HQ."
                ),
                "release_notes": (
                    "Android till sideload kit. On the device, enable install from "
                    "unknown sources, extract this zip, and open INSTALL.txt."
                ),
                "files": {
                    "INSTALL.txt": (
                        "TibaTrace POS — Android sideload kit\n"
                        "===================================\n"
                        "1. Copy this zip to the Android till.\n"
                        "2. Enable Settings → Security → Install unknown apps for Files.\n"
                        "3. Open the companion launch HTML in Chrome and pin it, or\n"
                        "   install the production APK once CI publishes one to this key.\n"
                        "4. Sign in with your pharmacy operator account against HQ.\n"
                    ).encode("utf-8"),
                    "open-pos.html": (
                        "<!doctype html><meta charset='utf-8'>"
                        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                        "<title>TibaTrace POS</title>"
                        "<body style='font-family:sans-serif;padding:24px'>"
                        "<h1>TibaTrace POS</h1>"
                        "<p>Open the pharmacy POS shell:</p>"
                        "<p><a href='http://127.0.0.1:8000/pos/'>Launch POS</a></p>"
                        "</body>"
                    ).encode("utf-8"),
                },
            },
        )
        for kit in kits:
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
                for name, payload in kit["files"].items():
                    zipped.writestr(name, payload)
            content = archive.getvalue()
            digest = hashlib.sha256(content).hexdigest()
            ensure_local_artifact(kit["object_key"], content)
            release, created = PosRelease.objects.get_or_create(
                platform=kit["platform"],
                version=kit["version"],
                defaults={
                    "build_number": kit["build_number"],
                    "object_key": kit["object_key"],
                    "size_bytes": len(content),
                    "sha256": digest,
                    "minimum_os": kit["minimum_os"],
                    "minimum_supported_build": 0,
                    "operations_impact": kit["operations_impact"],
                    "release_notes": kit["release_notes"],
                    "is_published": True,
                    "published_at": now,
                },
            )
            desired = {
                "build_number": kit["build_number"],
                "object_key": kit["object_key"],
                "size_bytes": len(content),
                "sha256": digest,
                "minimum_os": kit["minimum_os"],
                "minimum_supported_build": 0,
                "operations_impact": kit["operations_impact"],
                "release_notes": kit["release_notes"],
                "is_published": True,
                "published_at": release.published_at or now,
            }
            changed = [
                field for field, value in desired.items() if getattr(release, field) != value
            ]
            if changed:
                for field in changed:
                    setattr(release, field, desired[field])
                release.save(update_fields=[*changed, "updated_at"])
            elif created:
                pass
            self.stdout.write(
                f"  release   {kit['platform']} {kit['version']} "
                f"({'created' if created else 'updated'}; {len(content)} bytes)"
            )

    def _clinical(self, tenant, organization, branch, sku):
        ClinicalKnowledgeRelease.all_objects.get_or_create(
            tenant=tenant,
            code="HQ-DEMO-CDS",
            version="1.0",
            defaults={
                "source": "DawaTrace HQ demo clinical knowledge",
                "source_version": "1.0",
                "licence": "INTERNAL",
                "effective_date": timezone.localdate(),
                "is_active": True,
                "checksum_sha256": "c" * 64,
            },
        )
        patient, _ = Patient.all_objects.get_or_create(
            tenant=tenant,
            internal_reference_id="HQ-DEMO-PATIENT",
            defaults={
                "patient_number": "HQ-DEMO",
                "first_name": "HQ",
                "last_name": "Demo Patient",
                "verification_status": "VERIFIED",
                "consent_status": "RECORDED",
            },
        )
        practitioner, _ = Practitioner.all_objects.get_or_create(
            tenant=tenant,
            registration_number=f"HQ-DEMO-PRAC-{str(tenant.pk)[:8]}",
            defaults={
                "first_name": "Grace",
                "last_name": "Prescriber",
                "profession": "DOCTOR",
                "organization": organization,
                "status": "ACTIVE",
                "verification_state": "VERIFIED",
                "licence_status": "ACTIVE",
            },
        )
        encounter, _ = ClinicalEncounter.all_objects.get_or_create(
            tenant=tenant,
            patient=patient,
            reason_code="HQ-DEMO-ENCOUNTER",
            defaults={
                "organization": organization,
                "location": branch,
                "practitioner": practitioner,
                "status": "FINISHED",
                "encounter_class": "AMB",
                "start_time": timezone.now() - timedelta(minutes=30),
                "end_time": timezone.now(),
            },
        )
        ClinicalCondition.all_objects.get_or_create(
            tenant=tenant,
            patient=patient,
            code="HQ-DEMO-COND-HTN",
            defaults={
                "encounter": encounter,
                "clinical_status": "ACTIVE",
                "verification_status": "CONFIRMED",
                "category": "problem-list-item",
                "system": "http://snomed.info/sct",
                "display": "Essential hypertension",
                "onset_date": timezone.now() - timedelta(days=90),
            },
        )
        ClinicalObservation.all_objects.get_or_create(
            tenant=tenant,
            patient=patient,
            code="HQ-DEMO-OBS-BP",
            defaults={
                "encounter": encounter,
                "status": "FINAL",
                "category": "vital-signs",
                "system": "http://loinc.org",
                "display": "Blood pressure panel",
                "effective_time": timezone.now() - timedelta(minutes=20),
                "value_string": "128/82 mmHg",
                "interpretation": "N",
            },
        )
        # Two prescriptions, for the two halves of the clinical journey: one
        # already verified and waiting at the counter, and one still at intake
        # so the workflow actions on the cockpit have something to act on.
        prescription_specs = (
            (
                "HQ-DEMO-RX-OPEN",
                {
                    "status": "READY_FOR_DISPENSING",
                    "workflow_state": "DISPENSING",
                    "legal_validation_state": "PASSED",
                    "clinical_review_state": "COMPLETED",
                    "pharmacist_verification_state": "VERIFIED",
                    "dispensing_state": "READY",
                },
            ),
            (
                "HQ-DEMO-RX-INTAKE",
                {
                    "status": "RECEIVED",
                    "workflow_state": "DRAFT",
                    "legal_validation_state": "PENDING",
                    "clinical_review_state": "NOT_STARTED",
                    "pharmacist_verification_state": "NOT_VERIFIED",
                    "dispensing_state": "NOT_STARTED",
                },
            ),
        )
        for prescription_number, workflow in prescription_specs:
            prescription, _ = Prescription.all_objects.get_or_create(
                tenant=tenant,
                prescription_number=prescription_number,
                defaults={
                    "patient": patient,
                    "practitioner": practitioner,
                    "organization": organization,
                    "location": branch,
                    "prescription_date": timezone.localdate(),
                    "received_at": timezone.now(),
                    **workflow,
                },
            )
            if not prescription.items.exists():
                PrescriptionItem.all_objects.create(
                    tenant=tenant,
                    prescription=prescription,
                    prescribed_sku=sku,
                    medication_name=sku.display_name,
                    dosage_instruction="One tablet three times a day for five days",
                    quantity=Decimal("15"),
                    unit="TABLET",
                    route="ORAL",
                    indication="HQ demo clinical journey",
                )

        terminology, _ = FHIRTerminologyVersion.all_objects.get_or_create(
            tenant=tenant,
            canonical_url="https://dawatrace.local/fhir/terminology/hq-demo",
            version="1.0.0",
            defaults={
                "publisher": "DawaTrace HQ",
                "status": "ACTIVE",
                "is_global": False,
                "source_name": "HQ Demo Terminology",
                "source_version": "1.0.0",
                "licence": "INTERNAL",
            },
        )
        FHIRCodeSystemRegistration.all_objects.get_or_create(
            version=terminology,
            url="https://dawatrace.local/fhir/CodeSystem/hq-demo-rx-status",
            defaults={
                "tenant": tenant,
                "name": "HQDemoRxStatus",
                "title": "HQ Demo Prescription Status",
                "content_mode": "COMPLETE",
                "is_global": False,
                "concepts_json": [
                    {"code": "READY_FOR_DISPENSING", "display": "Ready for dispensing"},
                    {"code": "SUPPLIED", "display": "Supplied"},
                ],
            },
        )
        FHIRValueSetRegistration.all_objects.get_or_create(
            version=terminology,
            url="https://dawatrace.local/fhir/ValueSet/hq-demo-rx-status",
            defaults={
                "tenant": tenant,
                "name": "HQDemoRxStatusVS",
                "title": "HQ Demo Prescription Status ValueSet",
                "is_global": False,
                "compose_json": {
                    "include": [
                        {
                            "system": "https://dawatrace.local/fhir/CodeSystem/hq-demo-rx-status",
                            "concept": [
                                {"code": "READY_FOR_DISPENSING"},
                                {"code": "SUPPLIED"},
                            ],
                        }
                    ]
                },
            },
        )
        FHIRIdempotencyRecord.all_objects.get_or_create(
            tenant=tenant,
            key="HQ-DEMO-FHIR-IDEMPOTENCY",
            defaults={
                "request_hash": "d" * 64,
                "resource_type": "Patient",
                "operation": "CREATE",
                "resource_id": patient.pk,
                "state": FHIRIdempotencyRecord.STATE_COMPLETED,
                "response_status": 201,
            },
        )

    def _governance(self, tenant, actor):
        for number, action in (
            (1, "HQ_DEMO_WORKSPACE_OPENED"),
            (2, "HQ_DEMO_CONTROLS_REVIEWED"),
        ):
            object_id = f"HQ-DEMO-AUDIT-{number}"
            if not AuditEvent.all_objects.filter(
                tenant=tenant,
                action=action,
                object_id=object_id,
            ).exists():
                log_audit(
                    tenant_id=tenant.pk,
                    actor_id=actor.pk,
                    action=action,
                    model_name="HQWorkspace",
                    object_id=object_id,
                    metadata={"seed": "seed_hq_workspaces"},
                )

        DomainEvent.all_objects.get_or_create(
            tenant=tenant,
            event_type="HQ_DEMO_WORKSPACE_READY",
            correlation_id="HQ-DEMO-DOMAIN-EVENT",
            defaults={
                "aggregate_type": "HQWorkspace",
                "aggregate_id": uuid5(NAMESPACE_URL, f"dawatrace:hq-demo:{tenant.pk}"),
                "payload": {
                    "tenant_id": str(tenant.pk),
                    "source": "seed_hq_workspaces",
                },
                "status": "PROCESSED",
                "processed_at": timezone.now(),
            },
        )

    def _organization_and_branch(self, tenant):
        organization, _ = Organization.all_objects.get_or_create(
            tenant=tenant,
            code="HQ-DEMO-ORG",
            defaults={"name": f"{tenant.name} HQ Demo Organization"},
        )
        branch, _ = Location.all_objects.get_or_create(
            tenant=tenant,
            code="HQ-DEMO-BRANCH",
            defaults={
                "organization": organization,
                "name": f"{tenant.name} Main Branch",
                "location_type": "BRANCH",
            },
        )
        return organization, branch

    def _users_and_roles(self, tenant):
        profile_specs = (
            ("operator", "Amina", "Cashier", "ACTIVE", True),
            ("supervisor", "Daniel", "Supervisor", "ACTIVE", True),
            ("pharmacist", "Faith", "Pharmacist", "ACTIVE", True),
            ("inventory", "Kevin", "Storekeeper", "ACTIVE", True),
            ("suspended", "Sarah", "Suspended", "SUSPENDED", False),
            ("disabled", "Owen", "Disabled", "DISABLED", False),
        )
        users_by_label = {}
        for label, first_name, last_name, account_status, is_active in profile_specs:
            username = f"hq-demo-{label}-{tenant.slug}"[:150]
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "tenant": tenant,
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": f"{label}@{tenant.slug}.demo.local",
                    "is_active": is_active,
                    "metadata": {"account_status": account_status, "seed_profile": label},
                },
            )
            if not created:
                metadata = dict(user.metadata or {})
                metadata.setdefault("account_status", account_status)
                metadata["seed_profile"] = label
                updates = []
                if user.metadata != metadata:
                    user.metadata = metadata
                    updates.append("metadata")
                if label in {"suspended", "disabled"} and user.is_active != is_active:
                    user.is_active = is_active
                    updates.append("is_active")
                if not user.email:
                    user.email = f"{label}@{tenant.slug}.demo.local"
                    updates.append("email")
                if updates:
                    user.save(update_fields=[*updates])
            if created or not user.has_usable_password():
                user.set_password("placeholder-not-a-secret")
                user.save(update_fields=["password"])
            users_by_label[label] = user

        role_specs = (
            (
                "HQ_DEMO_OPERATOR",
                "HQ Demo Operator",
                [
                    "dispensing.read",
                    "inventory.read",
                    "pricing.read",
                    "insurance.read",
                    "pos.payment.collect",
                ],
            ),
            (
                "HQ_DEMO_MANAGER",
                "HQ Demo Manager",
                [
                    "identity.manage",
                    "inventory.read",
                    "inventory.manage",
                    "quality.release",
                    "procurement.read",
                    "procurement.write",
                    "procurement.approve",
                    "pricing.read",
                    "pricing.manage",
                    "insurance.read",
                    "insurance.manage",
                    "pos.shift.manage",
                ],
            ),
            (
                "HQ_DEMO_PHARMACIST",
                "HQ Demo Pharmacist",
                [
                    # Named exactly as the prescription and dispensing view sets
                    # gate on. A role carrying an invented capability string
                    # renders every workflow action on the cockpit as a 403.
                    "prescriptions.read",
                    "prescriptions.write",
                    "prescriptions.intake",
                    "prescriptions.legal_validate",
                    "prescriptions.clinical_review",
                    "prescriptions.pharmacist_verify",
                    "prescriptions.review",
                    "cds.read",
                    "dispensing.read",
                    "inventory.read",
                ],
            ),
            (
                "HQ_DEMO_INVENTORY",
                "HQ Demo Inventory",
                [
                    "inventory.read",
                    "inventory.manage",
                    "procurement.read",
                    "quality.release",
                ],
            ),
        )
        roles_by_code = {}
        for code, name, capabilities in role_specs:
            role, _ = Role.all_objects.get_or_create(
                tenant=tenant,
                code=code,
                defaults={"name": name, "capabilities": capabilities, "is_system": True},
            )
            merged_capabilities = list(
                dict.fromkeys([*(role.capabilities or []), *capabilities])
            )
            if role.capabilities != merged_capabilities:
                role.capabilities = merged_capabilities
                role.save(update_fields=["capabilities", "updated_at"])
            roles_by_code[code] = role

        tenant_admin = UserAdministrationService.ensure_default_tenant_roles(tenant_id=tenant.pk)
        roles_by_code["TENANT_ADMIN"] = tenant_admin

        assignments = (
            ("operator", "HQ_DEMO_OPERATOR"),
            ("supervisor", "HQ_DEMO_MANAGER"),
            ("supervisor", "TENANT_ADMIN"),
            ("pharmacist", "HQ_DEMO_PHARMACIST"),
            ("inventory", "HQ_DEMO_INVENTORY"),
            ("suspended", "HQ_DEMO_OPERATOR"),
            ("disabled", "HQ_DEMO_OPERATOR"),
        )
        for label, role_code in assignments:
            UserRole.all_objects.get_or_create(
                tenant=tenant,
                user=users_by_label[label],
                role=roles_by_code[role_code],
            )

        ServiceAccount.all_objects.get_or_create(
            tenant=tenant,
            code="HQ-DEMO-EXPORT",
            defaults={
                "display_name": "HQ Demo Export Service",
                "capabilities": ["identity.manage", "inventory.read"],
                "is_active": True,
                "credential_fingerprint": "e" * 64,
            },
        )

        return users_by_label["operator"], users_by_label["supervisor"]

    def _catalogue(self, tenant):
        sku = CommercialSKU.all_objects.filter(
            tenant=tenant,
            manufactured_product__tenant=tenant,
            status=CommercialSKU.STATUS_ACTIVE,
        ).first()
        if sku:
            return sku
        sku = CommercialSKU.all_objects.filter(
            tenant=tenant,
            manufactured_product__tenant=tenant,
        ).first()
        if sku:
            return sku
        dose_form, _ = DoseForm.objects.get_or_create(
            code="HQ-DEMO-TAB",
            defaults={"name": "HQ Demo Tablet"},
        )
        clinical, _ = ClinicalMedicinalProduct.all_objects.get_or_create(
            tenant=tenant,
            code="HQ-DEMO-CMP-PARA",
            defaults={
                "canonical_name": "Paracetamol 500mg",
                "dose_form": dose_form,
                "status": ClinicalMedicinalProduct.STATUS_ACTIVE,
            },
        )
        manufactured, _ = ManufacturedMedicinalProduct.all_objects.get_or_create(
            tenant=tenant,
            code="HQ-DEMO-MMP-PARA",
            defaults={
                "brand_name": "Demo Paracetamol 500mg",
                "clinical_product": clinical,
                "status": ManufacturedMedicinalProduct.STATUS_ACTIVE,
            },
        )
        package, _ = PackageDefinition.objects.get_or_create(
            code="HQ-DEMO-PACK-20",
            defaults={
                "description": "Demo pack of 20 tablets",
                "unit_of_measure": "TABLET",
                "quantity_in_parent": 20,
                "is_dispensing_unit": True,
            },
        )
        sku, _ = CommercialSKU.all_objects.get_or_create(
            tenant=tenant,
            sku_code="HQ-DEMO-SKU-PARA",
            defaults={
                "display_name": "Demo Paracetamol 500mg x20",
                "manufactured_product": manufactured,
                "package_definition": package,
                "status": CommercialSKU.STATUS_ACTIVE,
            },
        )
        return sku

    def _cash(self, tenant, branch, operator, supervisor):
        register, _ = PosRegister.all_objects.get_or_create(
            tenant=tenant,
            code="HQ-DEMO-TILL",
            defaults={
                "location": branch,
                "name": "HQ Demo Till",
                "state": "OPEN",
                "expected_float": Decimal("5000.00"),
                "device_id": "DEMO-TERM-01",
            },
        )
        if not register.device_id:
            register.device_id = "DEMO-TERM-01"
            register.save(update_fields=["device_id", "updated_at"])
        day, _ = BusinessDay.all_objects.get_or_create(
            tenant=tenant,
            location=register.location,
            business_date=timezone.localdate(),
            defaults={"state": "OPEN"},
        )
        session = RegisterSession.all_objects.filter(
            tenant=tenant, register=register, state="OPEN"
        ).first()
        if session is None:
            session = RegisterSession.all_objects.create(
                tenant=tenant,
                register=register,
                business_day=day,
                opened_by=operator,
                state="OPEN",
            )
        shift, _ = OperatorShift.all_objects.get_or_create(
            tenant=tenant,
            register_session=session,
            state="OPEN",
            defaults={"operator": operator},
        )
        CashDeclaration.all_objects.get_or_create(
            tenant=tenant,
            register_session=session,
            kind="OPENING",
            attempt=1,
            defaults={
                "operator_shift": shift,
                "declared_amount": Decimal("5000.00"),
                "declared_by": operator,
                "confirmed_at": timezone.now(),
            },
        )
        CashMovement.all_objects.get_or_create(
            tenant=tenant,
            register_session=session,
            reference="HQ-DEMO-CASH-IN",
            defaults={
                "operator_shift": shift,
                "kind": "CASH_IN",
                "amount": Decimal("1250.00"),
                "reason_code": "DEMO_FLOAT",
                "description": "HQ workspace sample cash movement",
                "created_by": operator,
                "approved_by": supervisor,
                "approved_at": timezone.now(),
            },
        )

    def _pricing(self, tenant, branch, sku):
        usable = PriceBookVersion.all_objects.filter(
            tenant=tenant,
            status=PriceBookVersion.Status.ACTIVE,
            entries__isnull=False,
            price_book__assignments__tenant=tenant,
            price_book__assignments__branch=branch,
            price_book__assignments__is_active=True,
        ).exists()
        if usable:
            return
        book, _ = PriceBook.all_objects.get_or_create(
            tenant=tenant,
            code="HQ-DEMO-BRANCH-RETAIL",
            defaults={
                "name": "HQ Demo Branch Retail",
                "scope_type": PriceBook.ScopeType.BRANCH,
                "price_type": PriceBook.PriceType.BRANCH_RETAIL,
                "currency": "KES",
            },
        )
        version = PriceBookVersion.all_objects.filter(
            tenant=tenant, price_book=book, status=PriceBookVersion.Status.ACTIVE
        ).first()
        if version is None:
            number = (
                PriceBookVersion.all_objects.filter(tenant=tenant, price_book=book)
                .order_by("-version_number")
                .values_list("version_number", flat=True)
                .first()
                or 0
            ) + 1
            version = PriceBookVersion.all_objects.create(
                tenant=tenant,
                price_book=book,
                version_number=number,
                status=PriceBookVersion.Status.ACTIVE,
                effective_from=timezone.localdate() - timedelta(days=30),
            )
        PriceBookEntry.all_objects.get_or_create(
            tenant=tenant,
            version=version,
            sku=sku,
            minimum_quantity=Decimal("1"),
            defaults={"unit_price": Decimal("350.00")},
        )
        PriceAssignment.all_objects.get_or_create(
            tenant=tenant,
            price_book=book,
            scope_type=PriceBook.ScopeType.BRANCH,
            branch=branch,
            defaults={"valid_from": timezone.localdate() - timedelta(days=30)},
        )

    def _inventory(self, tenant, branch, sku, actor):
        store, _ = InventoryLocation.all_objects.get_or_create(
            tenant=tenant,
            branch=branch,
            location_code="HQ-DEMO-STORE",
            defaults={
                "name": "HQ Demo Main Store",
                "location_type": InventoryLocation.LocationType.STORE,
            },
        )
        hold, _ = InventoryLocation.all_objects.get_or_create(
            tenant=tenant,
            branch=branch,
            location_code="HQ-DEMO-QUALITY-HOLD",
            defaults={
                "name": "HQ Demo Quality Hold",
                "location_type": InventoryLocation.LocationType.QUARANTINE,
                "quarantine_capability": True,
                "restricted_flag": True,
            },
        )
        expiry = timezone.localdate() + timedelta(days=730)
        released, _ = InventoryBatch.all_objects.get_or_create(
            tenant=tenant,
            manufactured_product=sku.manufactured_product,
            manufacturer_batch_number="HQ-DEMO-RELEASED-001",
            defaults={
                "sku": sku,
                "expiry_date": expiry,
                "quality_status": InventoryBatch.QualityStatus.RELEASED,
            },
        )
        quarantined, _ = InventoryBatch.all_objects.get_or_create(
            tenant=tenant,
            manufactured_product=sku.manufactured_product,
            manufacturer_batch_number="HQ-DEMO-HOLD-001",
            defaults={
                "sku": sku,
                "expiry_date": expiry,
                "quality_status": InventoryBatch.QualityStatus.QUARANTINED,
            },
        )
        for batch, location, quantity, suffix in (
            (released, store, Decimal("120"), "RELEASED"),
            (quarantined, hold, Decimal("12"), "HOLD"),
        ):
            InventoryLedgerService.post_entry(
                tenant=tenant,
                branch=branch,
                location=location,
                sku=sku,
                inventory_batch=batch,
                entry_type=InventoryLedgerEntry.EntryType.RECEIPT,
                quantity_delta=quantity,
                unit=sku.package_definition.unit_of_measure,
                base_quantity_delta=quantity,
                effective_timestamp=timezone.now(),
                source_document_type="HQDemoSeed",
                source_document_id=f"HQ-DEMO-{suffix}",
                idempotency_key=f"HQ-DEMO-INVENTORY-{suffix}-{branch.pk}",
                actor=actor,
                notes="Sample inventory for the HQ workspace.",
            )

    def _procurement(self, tenant, branch, sku, operator, supervisor):
        today = timezone.localdate()
        complete_po = PurchaseOrder.all_objects.filter(
            tenant=tenant,
            po_number="HQ-DEMO-PO-COMPLETE",
        ).first()

        supplier = SupplierGovernanceService.create_supplier(
            tenant=tenant,
            supplier_code="HQ-DEMO-SUP",
            legal_name=f"{tenant.name} Demo Supplier",
        )

        if complete_po is None:
            for qualification_type in (
                SupplierQualification.QualificationType.BUSINESS_REGISTRATION,
                SupplierQualification.QualificationType.WHOLESALE_DEALER_LICENCE,
            ):
                qualification, _ = SupplierQualification.all_objects.get_or_create(
                    tenant=tenant,
                    supplier=supplier,
                    qualification_type=qualification_type,
                    licence_number=f"HQ-DEMO-{qualification_type}",
                    defaults={
                        "issuing_authority": "Pharmacy and Poisons Board",
                        "effective_date": today - timedelta(days=30),
                        "expiry_date": today + timedelta(days=365),
                    },
                )
                SupplierGovernanceService.verify_qualification(
                    qualification=qualification,
                    verifier=supervisor,
                )

            SupplierGovernanceService.approve_supplier(
                supplier=supplier,
                approver=supervisor,
                reason="HQ demo supplier qualifications verified",
            )

            requisition = ProcurementService.create_requisition(
                tenant=tenant,
                requisition_number="HQ-DEMO-REQ-COMPLETE",
                requester=operator,
                requesting_branch=branch,
                requested_delivery_date=today + timedelta(days=7),
                lines_data=[
                    {
                        "sku": sku,
                        "requested_quantity": 20,
                        "estimated_unit_cost": Decimal("125.00"),
                    }
                ],
                priority="HIGH",
                justification="Complete HQ procurement journey demo",
            )
            ProcurementService.submit_requisition(requisition=requisition)
            ProcurementService.approve_requisition(
                requisition=requisition,
                approver=supervisor,
            )
            requisition_line = requisition.lines.get()
            complete_po = ProcurementService.create_priced_po_from_requisition(
                tenant=tenant,
                supplier=supplier,
                requisition=requisition,
                ordering_branch=branch,
                creator=supervisor,
                po_number="HQ-DEMO-PO-COMPLETE",
                expected_delivery_date=today + timedelta(days=5),
                lines_data=[
                    {
                        "requisition_line": requisition_line.pk,
                        "quantity": 20,
                        "unit_cost": Decimal("125.00"),
                    }
                ],
            )
            ProcurementService.approve_po(
                purchase_order=complete_po,
                approver=supervisor,
            )
            ProcurementService.send_po(purchase_order=complete_po)

            store = InventoryLocation.all_objects.get(
                tenant=tenant,
                branch=branch,
                location_code="HQ-DEMO-STORE",
            )
            goods_receipt = GoodsReceivingService.start_goods_receipt(
                tenant=tenant,
                grn_number="HQ-DEMO-GRN-COMPLETE",
                purchase_order=complete_po,
                receiving_branch=branch,
                receiver=operator,
                delivery_note_number="HQ-DEMO-DN-COMPLETE",
            )
            po_line = complete_po.lines.get()
            received_batch = GoodsReceivingService.receive_batch(
                goods_receipt=goods_receipt,
                po_line=po_line,
                manufacturer_batch_number="HQ-DEMO-BATCH-COMPLETE",
                expiry_date=today + timedelta(days=365),
                received_quantity=20,
                idempotency_key="HQ-DEMO-RECV-COMPLETE",
            )
            QualityService.record_inspection(
                goods_receipt=goods_receipt,
                inspector=supervisor,
                decision=ReceivingInspection.Decision.QUARANTINE,
                reason="Awaiting quality release",
            )
            GoodsReceivingService.release_batch(
                batch=received_batch,
                actor=supervisor,
                reason="Verified",
                quantity=20,
            )
            InventoryReceiptService.post_receipt(
                tenant=tenant,
                received_batch=received_batch,
                receiving_location=store,
                actor=supervisor,
            )
            GoodsReceivingService.close_goods_receipt(
                goods_receipt=goods_receipt,
            )
            ThreeWayMatchService.perform_three_way_match(
                purchase_order=complete_po,
                goods_receipt=goods_receipt,
                invoice_reference="HQ-DEMO-INV-COMPLETE",
                invoice_amount=Decimal("2500.00"),
            )

        if not PurchaseOrder.all_objects.filter(
            tenant=tenant,
            po_number="HQ-DEMO-PO-OPEN",
        ).exists():
            if supplier.status not in {
                Supplier.Status.APPROVED,
                Supplier.Status.ACTIVE,
            }:
                SupplierGovernanceService.approve_supplier(
                    supplier=supplier,
                    approver=supervisor,
                    reason="HQ demo supplier approval restored",
                )
            open_requisition = ProcurementService.create_requisition(
                tenant=tenant,
                requisition_number="HQ-DEMO-REQ-OPEN",
                requester=operator,
                requesting_branch=branch,
                requested_delivery_date=today + timedelta(days=10),
                lines_data=[
                    {
                        "sku": sku,
                        "requested_quantity": 10,
                        "estimated_unit_cost": Decimal("125.00"),
                    }
                ],
                priority="HIGH",
                justification="Open HQ receiving work queue demo",
            )
            ProcurementService.submit_requisition(requisition=open_requisition)
            ProcurementService.approve_requisition(
                requisition=open_requisition,
                approver=supervisor,
            )
            open_line = open_requisition.lines.get()
            open_po = ProcurementService.create_priced_po_from_requisition(
                tenant=tenant,
                supplier=supplier,
                requisition=open_requisition,
                ordering_branch=branch,
                creator=supervisor,
                po_number="HQ-DEMO-PO-OPEN",
                expected_delivery_date=today + timedelta(days=5),
                lines_data=[
                    {
                        "requisition_line": open_line.pk,
                        "quantity": 10,
                        "unit_cost": Decimal("125.00"),
                    }
                ],
            )
            ProcurementService.approve_po(
                purchase_order=open_po,
                approver=supervisor,
            )
            ProcurementService.send_po(purchase_order=open_po)
