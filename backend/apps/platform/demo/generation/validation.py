"""Stage 2A validation.

Two kinds of check live here.

The first confirms the master data is coherent: one primary department per
user, the metadata mirror agrees with it, insurers are still in sandbox,
practitioners carry honest truth labels.

The second is the more important one. It asserts that Stage 2A created **no
transactional data**. That check is written against scenario ownership rather
than raw table counts, because the tenant may legitimately contain records this
run did not create -- counting rows would either produce false failures on a
non-empty tenant or, worse, pass by accident on an empty one.
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType

from apps.insurance.models import Insurer
from apps.organizations.models import DepartmentMembership
from apps.organizations.services import DEPARTMENT_METADATA_KEY
from apps.platform.demo.models import DemoScenarioObject

#: (label, app_label, model_name). Every one of these is transactional and must
#: have zero objects owned by a Stage 2A run.
FORBIDDEN_MODELS = (
    ("purchase_orders", "procurement", "PurchaseOrder"),
    ("goods_receipts", "procurement", "GoodsReceipt"),
    ("inventory_batches", "inventory", "InventoryBatch"),
    ("inventory_ledger_entries", "inventory", "InventoryLedgerEntry"),
    ("inventory_balances", "inventory", "InventoryBalance"),
    ("inventory_reservations", "inventory", "InventoryReservation"),
    ("prescriptions", "prescription", "Prescription"),
    ("dispensing_episodes", "prescription", "DispensingEpisode"),
    ("payment_intents", "prescription", "PaymentIntent"),
    ("payment_settlements", "prescription", "PaymentSettlement"),
    ("insurance_claims", "insurance", "PrescriptionClaim"),
    ("insurance_remittances", "insurance", "InsuranceRemittance"),
    ("register_sessions", "pos_shift", "RegisterSession"),
)


class ValidationFinding:
    def __init__(self, check: str, status: str, detail: str):
        self.check = check
        self.status = status
        self.detail = detail

    def as_dict(self):
        return {"check": self.check, "status": self.status, "detail": self.detail}


class MasterDataValidator:
    """Validates one completed master-data run."""

    def __init__(self, *, run, tenant):
        self.run = run
        self.tenant = tenant
        self.findings: list[ValidationFinding] = []

    def _ok(self, check, detail=""):
        self.findings.append(ValidationFinding(check, "PASS", detail))

    def _fail(self, check, detail):
        self.findings.append(ValidationFinding(check, "FAIL", detail))

    def _skip(self, check, detail):
        self.findings.append(ValidationFinding(check, "SKIPPED", detail))

    # -- checks ------------------------------------------------------------

    def check_tenant_ownership(self):
        wrong = DemoScenarioObject.all_objects.filter(run=self.run).exclude(
            tenant=self.tenant
        ).count()
        if wrong:
            self._fail("tenant_ownership", f"{wrong} owned object(s) belong to another tenant")
        else:
            self._ok("tenant_ownership", "all owned objects belong to the scenario tenant")

    def check_primary_departments(self):
        """One active primary department per user, and the mirror agrees."""
        primaries = DepartmentMembership.all_objects.filter(
            tenant=self.tenant, is_primary=True, is_active=True
        ).select_related("user", "department")

        seen: dict[str, int] = {}
        mismatched = []
        for membership in primaries.order_by("pk"):
            seen[str(membership.user_id)] = seen.get(str(membership.user_id), 0) + 1
            mirrored = (membership.user.metadata or {}).get(DEPARTMENT_METADATA_KEY)
            if mirrored != membership.department.code:
                mismatched.append(
                    f"{membership.user.username}: mirror={mirrored!r} "
                    f"membership={membership.department.code!r}"
                )

        duplicates = [user for user, count in seen.items() if count > 1]
        if duplicates:
            self._fail("one_primary_department", f"{len(duplicates)} user(s) have more than one")
        else:
            self._ok("one_primary_department", f"{len(seen)} user(s) with exactly one primary")

        if mismatched:
            self._fail("department_metadata_mirror", "; ".join(mismatched[:5]))
        else:
            self._ok("department_metadata_mirror", "mirror agrees with membership")

    def check_abac_narrows_only(self):
        """Every demo attribute policy must DENY, never ALLOW.

        A policy that granted would make department membership a permission
        source, which is the one thing the department design forbids.
        """
        from apps.identity.models import AttributePolicy

        content_type = ContentType.objects.get_for_model(AttributePolicy)
        owned_ids = DemoScenarioObject.all_objects.filter(
            run=self.run, content_type=content_type
        ).values_list("object_id", flat=True)
        policies = AttributePolicy.all_objects.filter(pk__in=list(owned_ids))
        widening = [p.code for p in policies if p.effect != AttributePolicy.EFFECT_DENY]
        if widening:
            self._fail("abac_narrows_only", f"policies that do not deny: {', '.join(widening)}")
        else:
            self._ok("abac_narrows_only", f"{policies.count()} demo policy/policies, all DENY")

    def check_location_capabilities(self):
        from apps.inventory.models import InventoryLocation

        content_type = ContentType.objects.get_for_model(InventoryLocation)
        owned_ids = list(
            DemoScenarioObject.all_objects.filter(
                run=self.run, content_type=content_type
            ).values_list("object_id", flat=True)
        )
        locations = InventoryLocation.all_objects.filter(pk__in=owned_ids).order_by("location_code")

        expectations = {
            InventoryLocation.LocationType.QUARANTINE: "quarantine_capability",
            InventoryLocation.LocationType.COLD_ROOM: "cold_chain_capability",
            InventoryLocation.LocationType.CONTROLLED_VAULT: "controlled_drug_capability",
        }
        bad = []
        for location in locations:
            flag = expectations.get(location.location_type)
            if flag and not getattr(location, flag):
                bad.append(f"{location.location_code} missing {flag}")
        if bad:
            self._fail("location_capabilities", "; ".join(bad[:5]))
        else:
            self._ok("location_capabilities", f"{locations.count()} location(s) correct")

    def check_insurers_sandboxed(self):
        content_type = ContentType.objects.get_for_model(Insurer)
        owned_ids = list(
            DemoScenarioObject.all_objects.filter(
                run=self.run, content_type=content_type
            ).values_list("object_id", flat=True)
        )
        insurers = Insurer.all_objects.filter(pk__in=owned_ids).order_by("code")
        promoted = [
            i.code for i in insurers
            if i.environment != Insurer.Environment.SANDBOX
            or i.integration_adapter != Insurer.IntegrationAdapter.FAKE
        ]
        if promoted:
            self._fail("insurers_sandboxed", f"not sandbox/fake: {', '.join(promoted)}")
        else:
            self._ok("insurers_sandboxed", f"{insurers.count()} insurer(s) sandbox + fake adapter")

    def check_practitioner_truth_labels(self):
        from apps.practitioners.models import Practitioner

        content_type = ContentType.objects.get_for_model(Practitioner)
        owned_ids = list(
            DemoScenarioObject.all_objects.filter(
                run=self.run, content_type=content_type
            ).values_list("object_id", flat=True)
        )
        practitioners = Practitioner.all_objects.filter(pk__in=owned_ids)
        bad = [
            p.registration_number for p in practitioners
            if (p.metadata or {}).get("verification_basis") != "MANUAL_INTERNAL_VERIFICATION"
        ]
        if bad:
            self._fail("practitioner_truth_labels", f"{len(bad)} without MANUAL_INTERNAL_VERIFICATION")
        else:
            self._ok("practitioner_truth_labels", f"{practitioners.count()} correctly labelled")

    def check_patient_identifier_policy(self):
        """No synthetic patient identifier may look like a Kenyan national ID."""
        from apps.patients.models import Patient

        from .synthetic import PATIENT_IDENTIFIER_PREFIX

        content_type = ContentType.objects.get_for_model(Patient)
        owned_ids = list(
            DemoScenarioObject.all_objects.filter(
                run=self.run, content_type=content_type
            ).values_list("object_id", flat=True)
        )
        patients = Patient.all_objects.filter(pk__in=owned_ids)
        unsafe = [
            p.patient_number for p in patients
            if not str(p.patient_number).startswith(PATIENT_IDENTIFIER_PREFIX)
            or str(p.patient_number).isdigit()
        ]
        if unsafe:
            self._fail("patient_identifier_policy", f"{len(unsafe)} identifier(s) not clearly synthetic")
        else:
            self._ok("patient_identifier_policy", f"{patients.count()} synthetic identifier(s)")

    def check_manufacturer_scope(self):
        from apps.medicines.models import Manufacturer

        content_type = ContentType.objects.get_for_model(Manufacturer)
        owned_ids = list(
            DemoScenarioObject.all_objects.filter(
                run=self.run, content_type=content_type
            ).values_list("object_id", flat=True)
        )
        manufacturers = Manufacturer.all_objects.filter(pk__in=owned_ids)
        bad = [
            m.code for m in manufacturers
            if (m.is_global and m.tenant_id is not None)
            or (not m.is_global and m.tenant_id is None)
        ]
        if bad:
            self._fail("manufacturer_scope", f"scope constraint violated: {', '.join(bad)}")
        else:
            self._ok("manufacturer_scope", f"{manufacturers.count()} manufacturer(s) correctly scoped")

    def check_no_transactional_data(self):
        """The load-bearing Stage 2A assertion.

        Written against scenario ownership: if this run owns a purchase order,
        the generator created transactional data regardless of what else is in
        the tenant.
        """
        offenders = []
        checked = 0
        for label, app_label, model_name in FORBIDDEN_MODELS:
            try:
                model = django_apps.get_model(app_label, model_name)
            except LookupError:
                self._skip(f"no_{label}", f"{app_label}.{model_name} not present in this build")
                continue
            checked += 1
            content_type = ContentType.objects.get_for_model(model)
            owned = DemoScenarioObject.all_objects.filter(
                run=self.run, content_type=content_type
            ).count()
            if owned:
                offenders.append(f"{label}={owned}")

        if offenders:
            self._fail("no_transactional_data", "; ".join(offenders))
        else:
            self._ok(
                "no_transactional_data",
                f"zero objects owned across {checked} transactional model(s)",
            )

    def check_no_external_activation(self):
        """No national integration provider may have been activated."""
        try:
            model = django_apps.get_model("integrations", "ProviderConfiguration")
        except LookupError:
            self._skip("no_external_activation", "integrations app not present")
            return
        # ProviderConfiguration is platform-level, not tenant-scoped: national
        # integration providers are configured once for the deployment. So this
        # asks whether *any* provider is active, which is the right question --
        # a live PPB or SHA connection would affect this tenant regardless of
        # who configured it.
        manager = getattr(model, "all_objects", model._default_manager)
        active = list(
            manager.exclude(activation_state="INACTIVE").values_list(
                "display_name", "activation_state"
            )
        )
        if active:
            detail = ", ".join(f"{name}={state}" for name, state in active[:5])
            self._fail("no_external_activation", f"{len(active)} provider(s) not inactive: {detail}")
        else:
            self._ok("no_external_activation", "no national integration provider activated")

    # -- driver ------------------------------------------------------------

    def run_all(self) -> dict:
        checks = (
            self.check_tenant_ownership,
            self.check_primary_departments,
            self.check_abac_narrows_only,
            self.check_location_capabilities,
            self.check_insurers_sandboxed,
            self.check_practitioner_truth_labels,
            self.check_patient_identifier_policy,
            self.check_manufacturer_scope,
            self.check_no_transactional_data,
            self.check_no_external_activation,
        )
        for check in checks:
            try:
                check()
            except Exception as exc:  # a failing validator must not look like a pass
                self._fail(check.__name__, f"{type(exc).__name__}: {exc}")

        failures = [f for f in self.findings if f.status == "FAIL"]
        return {
            "run": str(self.run.pk),
            "tenant": self.tenant.slug,
            "status": "FAIL" if failures else "PASS",
            "failure_count": len(failures),
            "findings": [f.as_dict() for f in self.findings],
        }
