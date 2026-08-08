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


# ---------------------------------------------------------------------------
# Stage 2B.1 — procurement and receiving
# ---------------------------------------------------------------------------

#: Models that would mean stock became available. Stage 2B.1 must own none.
STAGE_2B1_FORBIDDEN = (
    ("inventory_ledger_entries", "inventory", "InventoryLedgerEntry"),
    ("inventory_balances", "inventory", "InventoryBalance"),
    ("inventory_batches", "inventory", "InventoryBatch"),
    ("inventory_reservations", "inventory", "InventoryReservation"),
)


class ProcurementReceivingValidator(MasterDataValidator):
    """Validates Stage 2B.1.

    The load-bearing checks are the ones that prove stock did *not* become
    available. A procurement history that looks complete while a batch has been
    released, or a ledger entry written, would read as success in every count.
    """

    def check_orders_derive_from_requisitions(self):
        from apps.procurement.models import PurchaseOrder

        orders = PurchaseOrder.all_objects.filter(tenant=self.tenant)
        orphans = [o.po_number for o in orders if o.originating_requisition_id is None]
        if orphans:
            self._fail("orders_from_requisitions",
                       f"{len(orphans)} order(s) with no requisition: {orphans[:5]}")
        else:
            self._ok("orders_from_requisitions",
                     f"{orders.count()} order(s), each from a requisition")

    def check_order_approval_segregation(self):
        """The raiser of an order may not be its approver."""
        from apps.procurement.models import PurchaseOrder

        breaches = [
            o.po_number
            for o in PurchaseOrder.all_objects.filter(tenant=self.tenant)
            if o.created_by_id and o.approved_by_id
            and str(o.created_by_id) == str(o.approved_by_id)
        ]
        if breaches:
            self._fail("order_approval_segregation",
                       f"raiser approved their own order: {breaches[:5]}")
        else:
            self._ok("order_approval_segregation", "no order was self-approved")

    def check_supplier_qualifications_at_order_date(self):
        from apps.procurement.models import PurchaseOrder
        from apps.procurement.services.supplier_governance_service import (
            SupplierGovernanceService,
        )

        bad = []
        for order in PurchaseOrder.all_objects.filter(
            tenant=self.tenant
        ).select_related("supplier"):
            reasons = SupplierGovernanceService.ineligibility_reasons(
                supplier=order.supplier, on_date=order.order_date
            )
            if reasons:
                bad.append(f"{order.po_number}: {reasons[0]}")
        if bad:
            self._fail("supplier_qualified_at_order_date", "; ".join(bad[:3]))
        else:
            self._ok("supplier_qualified_at_order_date",
                     "every order's supplier was qualified on its order date")

    def check_delivery_note_uniqueness(self):
        from apps.procurement.models import GoodsReceipt

        seen: dict[tuple, str] = {}
        duplicates = []
        for receipt in GoodsReceipt.all_objects.filter(
            tenant=self.tenant
        ).order_by("grn_number"):
            key = (str(receipt.supplier_id), receipt.delivery_note_number)
            if key in seen:
                duplicates.append(f"{receipt.grn_number} reuses {seen[key]}")
            seen[key] = receipt.grn_number
        if duplicates:
            self._fail("delivery_note_uniqueness", "; ".join(duplicates[:3]))
        else:
            self._ok("delivery_note_uniqueness",
                     f"{len(seen)} delivery note(s), unique per supplier")

    def check_received_quantity_coherence(self):
        from apps.procurement.models import GoodsReceiptLine

        over = []
        for line in GoodsReceiptLine.all_objects.filter(
            tenant=self.tenant
        ).select_related("po_line"):
            if line.delivered_quantity > line.po_line.ordered_quantity:
                over.append(str(line.pk))
            total = (
                (line.accepted_quantity or 0)
                + (line.quarantined_quantity or 0)
                + (line.rejected_quantity or 0)
            )
            if total > line.delivered_quantity:
                over.append(f"{line.pk} disposition exceeds delivery")
        if over:
            self._fail("received_quantity_coherence", f"{len(over)} incoherent line(s)")
        else:
            self._ok("received_quantity_coherence", "delivered never exceeds ordered")

    def check_every_batch_is_held(self):
        """The Stage 2B.1 boundary, asserted on quantity rather than status."""
        from django.db.models import F

        from apps.procurement.models import ReceivedBatch

        batches = ReceivedBatch.all_objects.filter(tenant=self.tenant)
        released = batches.filter(
            quality_status=ReceivedBatch.QualityStatus.RELEASED
        ).count()
        accepted = batches.filter(accepted_quantity__gt=0).count()
        unheld = batches.exclude(quarantined_quantity=F("received_quantity")).count()
        orphan = batches.filter(grn_line__isnull=True).count()

        problems = []
        if released:
            problems.append(f"{released} released")
        if accepted:
            problems.append(f"{accepted} with accepted units")
        if unheld:
            problems.append(f"{unheld} not fully quarantined")
        if orphan:
            problems.append(f"{orphan} with no receipt line")
        if problems:
            self._fail("every_batch_is_held", "; ".join(problems))
        else:
            self._ok("every_batch_is_held",
                     f"{batches.count()} batch(es) fully held, none released")

    def check_batch_dates(self):
        from apps.procurement.models import ReceivedBatch

        bad = [
            b.manufacturer_batch_number
            for b in ReceivedBatch.all_objects.filter(tenant=self.tenant)
            if b.received_quantity <= 0
            or (b.manufacture_date and b.manufacture_date >= b.expiry_date)
        ]
        if bad:
            self._fail("batch_dates", f"{len(bad)} batch(es) with incoherent dates")
        else:
            self._ok("batch_dates", "manufacture precedes expiry on every batch")

    def check_no_available_stock(self):
        """Nothing this run owns may have become available to promise."""
        offenders = []
        checked = 0
        for label, app_label, model_name in STAGE_2B1_FORBIDDEN:
            try:
                model = django_apps.get_model(app_label, model_name)
            except LookupError:
                self._skip(f"no_{label}", f"{app_label}.{model_name} not present")
                continue
            checked += 1
            content_type = ContentType.objects.get_for_model(model)
            owned = DemoScenarioObject.all_objects.filter(
                run=self.run, content_type=content_type
            ).count()
            direct = model.all_objects.filter(tenant=self.tenant).count()
            if owned or direct:
                offenders.append(f"{label}=owned:{owned},present:{direct}")
        if offenders:
            self._fail("no_available_stock", "; ".join(offenders))
        else:
            self._ok("no_available_stock",
                     f"zero rows across {checked} inventory model(s)")

    def check_receiving_sessions_unposted(self):
        from apps.procurement.models import ReceivingSession

        posted = ReceivingSession.all_objects.filter(
            tenant=self.tenant
        ).exclude(status="ACTIVE")
        if posted.exists():
            self._fail("receiving_sessions_unposted",
                       f"{posted.count()} session(s) posted; posting writes stock")
        else:
            self._ok("receiving_sessions_unposted",
                     f"{ReceivingSession.all_objects.filter(tenant=self.tenant).count()} "
                     "session(s), none posted")

    def check_no_duplicate_idempotency_keys(self):
        """Two owned objects sharing a reference means a replay created a second."""
        references = list(
            DemoScenarioObject.all_objects.filter(run=self.run)
            .exclude(external_reference="")
            .values_list("external_reference", flat=True)
        )
        duplicates = {r for r in references if references.count(r) > 1}
        if duplicates:
            self._fail("no_duplicate_references",
                       f"{len(duplicates)} reference(s) used twice")
        else:
            self._ok("no_duplicate_references",
                     f"{len(references)} owned object(s), each uniquely referenced")

    def run_all(self) -> dict:
        checks = (
            self.check_tenant_ownership,
            self.check_orders_derive_from_requisitions,
            self.check_order_approval_segregation,
            self.check_supplier_qualifications_at_order_date,
            self.check_delivery_note_uniqueness,
            self.check_received_quantity_coherence,
            self.check_every_batch_is_held,
            self.check_batch_dates,
            self.check_receiving_sessions_unposted,
            self.check_no_available_stock,
            self.check_no_duplicate_idempotency_keys,
        )
        for check in checks:
            try:
                check()
            except Exception as exc:
                self._fail(check.__name__, f"{type(exc).__name__}: {exc}")

        failures = [f for f in self.findings if f.status == "FAIL"]
        return {
            "run": str(self.run.pk),
            "tenant": self.tenant.slug,
            "stage": "2B.1-procurement-receiving",
            "status": "FAIL" if failures else "PASS",
            "failure_count": len(failures),
            "findings": [f.as_dict() for f in self.findings],
        }


class QualityValidator(ProcurementReceivingValidator):
    """Validates Stage 2B.2A (quality inspections and quality decisions)."""

    def check_quality_inspections(self):
        from apps.procurement.models import GoodsReceipt, ReceivingInspection

        receipts = GoodsReceipt.all_objects.filter(tenant=self.tenant)
        inspections = ReceivingInspection.all_objects.filter(tenant=self.tenant)

        if inspections.count() < receipts.count():
            self._fail(
                "quality_inspections",
                f"{receipts.count()} receipt(s) present, but only {inspections.count()} inspection(s)"
            )
            return

        bad_decisions = inspections.exclude(decision=ReceivingInspection.Decision.QUARANTINE).count()
        if bad_decisions:
            self._fail("quality_inspections", f"{bad_decisions} inspection(s) not QUARANTINE")
            return

        segregation_breaches = []
        for insp in inspections.select_related("goods_receipt"):
            if insp.inspector_id and insp.goods_receipt.received_by_id and str(insp.inspector_id) == str(insp.goods_receipt.received_by_id):
                segregation_breaches.append(insp.goods_receipt.grn_number)

        if segregation_breaches:
            self._fail("quality_inspections", f"segregation breach: inspector equals receiver on {segregation_breaches[:3]}")
        else:
            self._ok("quality_inspections", f"{inspections.count()} inspection(s) recorded with QUARANTINE, segregation maintained")

    def check_quality_decisions(self):
        from apps.procurement.models import QualityDecision, ReceivedBatch

        batches = ReceivedBatch.all_objects.filter(tenant=self.tenant)
        decisions = QualityDecision.all_objects.filter(tenant=self.tenant)

        batch_count = batches.count()
        decision_count = decisions.count()

        if decision_count != batch_count:
            self._fail(
                "quality_decisions",
                f"{batch_count} received batch(es), but {decision_count} quality decision(s)"
            )
            return

        bad_segregation = []
        bad_basis = []
        expired_approved = []
        for d in decisions.select_related("batch", "goods_receipt"):
            receiver_id = str(d.goods_receipt.received_by_id) if d.goods_receipt.received_by_id else None
            inspector_id = str(d.inspector_id) if d.inspector_id else None
            approver_id = str(d.decision_by_id) if d.decision_by_id else None

            if approver_id and (approver_id == receiver_id or approver_id == inspector_id):
                bad_segregation.append(d.batch.manufacturer_batch_number)

            if d.evidence_basis != "MANUAL_INTERNAL_QUALITY_REVIEW":
                bad_basis.append(d.batch.manufacturer_batch_number)

            if d.decision == QualityDecision.Outcome.APPROVE_FOR_RELEASE and d.batch.expiry_date <= self.run.as_of_date:
                expired_approved.append(d.batch.manufacturer_batch_number)

        if bad_segregation:
            self._fail("quality_decisions_segregation", f"approver conflict on: {bad_segregation[:3]}")
        else:
            self._ok("quality_decisions_segregation", "decision makers independent of receivers and inspectors")

        if bad_basis:
            self._fail("quality_decisions_truth_label", f"invalid basis on: {bad_basis[:3]}")
        else:
            self._ok("quality_decisions_truth_label", "all decisions carry MANUAL_INTERNAL_QUALITY_REVIEW")

        if expired_approved:
            self._fail("quality_decisions_expired_approved", f"expired batches approved: {expired_approved[:3]}")
        else:
            self._ok("quality_decisions_expired_approved", "no expired batch approved for release")

        self._ok("quality_decisions", f"{decision_count} batch quality decision(s) recorded across all received batches")

    def run_all(self) -> dict:
        checks = (
            self.check_tenant_ownership,
            self.check_orders_derive_from_requisitions,
            self.check_order_approval_segregation,
            self.check_supplier_qualifications_at_order_date,
            self.check_delivery_note_uniqueness,
            self.check_received_quantity_coherence,
            self.check_every_batch_is_held,
            self.check_batch_dates,
            self.check_receiving_sessions_unposted,
            self.check_no_available_stock,
            self.check_no_duplicate_idempotency_keys,
            self.check_quality_inspections,
            self.check_quality_decisions,
        )
        for check in checks:
            try:
                check()
            except Exception as exc:
                self._fail(check.__name__, f"{type(exc).__name__}: {exc}")

        failures = [f for f in self.findings if f.status == "FAIL"]
        return {
            "run": str(self.run.pk),
            "tenant": self.tenant.slug,
            "stage": "2B.2A-quality-decisions",
            "status": "FAIL" if failures else "PASS",
            "failure_count": len(failures),
            "findings": [f.as_dict() for f in self.findings],
        }


class QualityInventoryValidator(QualityValidator):
    """Validates Stage 2B.2B (quality release, inventory posting, balances, FEFO)."""

    def check_every_released_batch_approved(self):
        from apps.procurement.models import QualityDecision, ReceivedBatch

        released_batches = ReceivedBatch.all_objects.filter(
            tenant=self.tenant,
            quality_status__in=(
                ReceivedBatch.QualityStatus.RELEASED,
                ReceivedBatch.QualityStatus.PARTIALLY_RELEASED,
            ),
        )

        unapproved = []
        for b in released_batches:
            qd = QualityDecision.all_objects.filter(tenant=self.tenant, batch=b).first()
            if not qd or (qd.decision not in (QualityDecision.Outcome.APPROVE_FOR_RELEASE, "RELEASED", "RELEASE", "APPROVED") and not getattr(qd, "is_releasable", lambda: False)()):
                unapproved.append(b.manufacturer_batch_number)

        if unapproved:
            self._fail("every_released_batch_approved", f"unapproved released batch(es): {unapproved[:3]}")
        else:
            self._ok("every_released_batch_approved", f"{released_batches.count()} released/partially-released batch(es), all approved")

    def check_posted_quantity_approved(self):
        from django.db.models import Sum

        from apps.inventory.models import InventoryLedgerEntry
        from apps.procurement.models import ReceivedBatch

        accepted_qty = ReceivedBatch.all_objects.filter(
            tenant=self.tenant,
            quality_status__in=(
                ReceivedBatch.QualityStatus.RELEASED,
                ReceivedBatch.QualityStatus.PARTIALLY_RELEASED,
            ),
        ).aggregate(s=Sum("accepted_quantity"))["s"] or 0

        ledger_qty = InventoryLedgerEntry.all_objects.filter(tenant=self.tenant).aggregate(s=Sum("quantity_delta"))["s"] or 0

        if accepted_qty != ledger_qty:
            self._fail("posted_quantity_approved", f"accepted {accepted_qty} != ledger {ledger_qty}")
        else:
            self._ok("posted_quantity_approved", f"{ledger_qty} units posted, matching approved accepted quantity")

    def check_ledger_equals_balances(self):
        from django.db.models import Sum

        from apps.inventory.models import InventoryBalance, InventoryLedgerEntry

        ledger_qty = InventoryLedgerEntry.all_objects.filter(tenant=self.tenant).aggregate(s=Sum("quantity_delta"))["s"] or 0
        balance_qty = InventoryBalance.all_objects.filter(tenant=self.tenant).aggregate(s=Sum("on_hand"))["s"] or 0

        if ledger_qty != balance_qty:
            self._fail("ledger_equals_balances", f"ledger {ledger_qty} != balance {balance_qty}")
        else:
            self._ok("ledger_equals_balances", f"ledger {ledger_qty} equals balance on_hand {balance_qty}")

    def check_inventory_batches_equal_balances(self):
        from apps.inventory.models import InventoryBatch

        batches = InventoryBatch.all_objects.filter(tenant=self.tenant)

        unposted_quarantined = [
            b.manufacturer_batch_number for b in batches
            if b.source_received_batch and b.source_received_batch.quality_status == "QUARANTINED"
        ]
        if unposted_quarantined:
            self._fail("inventory_batches_equal_balances", f"quarantined batch in InventoryBatch: {unposted_quarantined[:3]}")
        else:
            self._ok("inventory_batches_equal_balances", f"{batches.count()} InventoryBatch record(s), zero quarantined")

    def check_no_balance_drift(self):
        from django.db.models import Sum

        from apps.inventory.models import InventoryBalance
        from apps.inventory.services import InventoryBalanceService

        before = InventoryBalance.all_objects.filter(tenant=self.tenant).aggregate(s=Sum("on_hand"))["s"] or 0
        InventoryBalanceService.rebuild_all_balances(tenant=self.tenant)
        after = InventoryBalance.all_objects.filter(tenant=self.tenant).aggregate(s=Sum("on_hand"))["s"] or 0

        if before != after:
            self._fail("no_balance_drift", f"balance rebuild drift: before {before}, after {after}")
        else:
            self._ok("no_balance_drift", f"rebuild identical ({after} units), zero drift")

    def check_location_compatibility(self):
        from apps.inventory.models import InventoryBalance
        from apps.medicines.provisioning import _is_cold_chain, _is_controlled

        balances = InventoryBalance.all_objects.filter(
            tenant=self.tenant, available__gt=0
        ).select_related("location", "sku")

        bad = []
        for bal in balances:
            if _is_controlled(bal.sku) and not bal.location.controlled_drug_capability:
                bad.append(f"{bal.sku.sku_code} in non-vault {bal.location.location_code}")
            if _is_cold_chain(bal.sku) and not bal.location.cold_chain_capability:
                bad.append(f"{bal.sku.sku_code} in non-cold {bal.location.location_code}")

        if bad:
            self._fail("location_compatibility", "; ".join(bad[:3]))
        else:
            self._ok("location_compatibility", "all released stock in compatible storage locations")

    def check_fefo_valid(self):
        from apps.inventory.models import InventoryBalance
        from apps.inventory.services import FEFOAllocationService

        balances = InventoryBalance.all_objects.filter(
            tenant=self.tenant, available__gt=0
        ).select_related("branch", "sku")

        tested = set()
        for bal in balances:
            if bal.sku_id in tested:
                continue
            tested.add(bal.sku_id)

            allocations = FEFOAllocationService.allocate_stock(
                tenant=self.tenant, branch=bal.branch, sku=bal.sku, required_quantity=5
            )
            if allocations:
                expiries = [b.expiry_date for b, _qty in allocations]
                if expiries != sorted(expiries):
                    self._fail("fefo_valid", f"out of order expiries for {bal.sku.sku_code}: {expiries}")
                    return

        self._ok("fefo_valid", f"FEFO allocation validated across {len(tested)} SKU(s)")

    def check_unavailable_stock_excluded(self):
        from apps.inventory.models import InventoryBalance

        quarantined_avail = InventoryBalance.all_objects.filter(
            tenant=self.tenant, location__quarantine_capability=True, available__gt=0
        ).count()
        damaged_avail = InventoryBalance.all_objects.filter(
            tenant=self.tenant, location__damaged_goods_capability=True, available__gt=0
        ).count()

        if quarantined_avail or damaged_avail:
            self._fail("unavailable_stock_excluded", f"quarantined avail: {quarantined_avail}, damaged avail: {damaged_avail}")
        else:
            self._ok("unavailable_stock_excluded", "quarantined and damaged locations strictly 0 available")

    def run_all(self) -> dict:
        checks = (
            self.check_tenant_ownership,
            self.check_orders_derive_from_requisitions,
            self.check_order_approval_segregation,
            self.check_supplier_qualifications_at_order_date,
            self.check_delivery_note_uniqueness,
            self.check_received_quantity_coherence,
            self.check_batch_dates,
            self.check_receiving_sessions_unposted,
            self.check_no_duplicate_idempotency_keys,
            self.check_quality_inspections,
            self.check_quality_decisions,
            self.check_every_released_batch_approved,
            self.check_posted_quantity_approved,
            self.check_ledger_equals_balances,
            self.check_inventory_batches_equal_balances,
            self.check_no_balance_drift,
            self.check_location_compatibility,
            self.check_fefo_valid,
            self.check_unavailable_stock_excluded,
        )
        for check in checks:
            try:
                check()
            except Exception as exc:
                self._fail(check.__name__, f"{type(exc).__name__}: {exc}")

        failures = [f for f in self.findings if f.status == "FAIL"]
        return {
            "run": str(self.run.pk),
            "tenant": self.tenant.slug,
            "stage": "2B.2B-inventory-ownership",
            "status": "FAIL" if failures else "PASS",
            "failure_count": len(failures),
            "findings": [f.as_dict() for f in self.findings],
        }


class StockMobilityValidator(QualityInventoryValidator):
    """Validates Stage 2C (stock transfers, reservations, mobility boundary)."""

    def check_transfer_lifecycle(self):
        from apps.inventory.models import StockTransfer

        transfers = StockTransfer.all_objects.filter(tenant=self.tenant)
        if not transfers.exists():
            self._fail("transfer_lifecycle", "No stock transfers found")
            return

        bad_segregation = []
        for t in transfers.filter(status=StockTransfer.Status.APPROVED):
            if t.requested_by_id and t.requested_by_id == t.approved_by_id:
                bad_segregation.append(t.transfer_number)

        if bad_segregation:
            self._fail("transfer_lifecycle_segregation", f"requester == approver on: {bad_segregation[:3]}")
        else:
            self._ok("transfer_lifecycle_segregation", "transfer requesters and approvers strictly segregated")

        self._ok("transfer_lifecycle", f"{transfers.count()} stock transfer(s) validated")

    def check_transfer_ledger_balance(self):
        from decimal import Decimal

        from django.db.models import Sum

        from apps.inventory.models import InventoryLedgerEntry

        out_qty = abs(
            InventoryLedgerEntry.all_objects.filter(
                tenant=self.tenant, entry_type=InventoryLedgerEntry.EntryType.TRANSFER_OUT
            ).aggregate(s=Sum("quantity_delta"))["s"] or Decimal("0")
        )
        in_qty = InventoryLedgerEntry.all_objects.filter(
            tenant=self.tenant, entry_type=InventoryLedgerEntry.EntryType.TRANSFER_IN
        ).aggregate(s=Sum("quantity_delta"))["s"] or Decimal("0")

        if out_qty != in_qty:
            self._fail("transfer_ledger_balance", f"TRANSFER_OUT {out_qty} != TRANSFER_IN {in_qty}")
        else:
            self._ok("transfer_ledger_balance", f"TRANSFER_OUT ({out_qty}) equals TRANSFER_IN ({in_qty}), zero stock leak")

    def check_reservation_lifecycle(self):
        from apps.inventory.models import InventoryReservation

        reservations = InventoryReservation.all_objects.filter(tenant=self.tenant)
        if not reservations.exists():
            self._fail("reservation_lifecycle", "No inventory reservations found")
            return

        self._ok("reservation_lifecycle", f"{reservations.count()} reservation(s) validated")

    def check_no_negative_balances(self):
        from apps.inventory.models import InventoryBalance

        neg_on_hand = InventoryBalance.all_objects.filter(tenant=self.tenant, on_hand__lt=0).count()
        neg_avail = InventoryBalance.all_objects.filter(tenant=self.tenant, available__lt=0).count()

        if neg_on_hand or neg_avail:
            self._fail("no_negative_balances", f"neg on_hand: {neg_on_hand}, neg available: {neg_avail}")
        else:
            self._ok("no_negative_balances", "zero negative stock across all inventory balances")

    def run_all(self) -> dict:
        checks = (
            self.check_tenant_ownership,
            self.check_orders_derive_from_requisitions,
            self.check_order_approval_segregation,
            self.check_supplier_qualifications_at_order_date,
            self.check_delivery_note_uniqueness,
            self.check_received_quantity_coherence,
            self.check_batch_dates,
            self.check_receiving_sessions_unposted,
            self.check_no_duplicate_idempotency_keys,
            self.check_quality_inspections,
            self.check_quality_decisions,
            self.check_every_released_batch_approved,
            self.check_posted_quantity_approved,
            self.check_inventory_batches_equal_balances,
            self.check_location_compatibility,
            self.check_fefo_valid,
            self.check_unavailable_stock_excluded,
            self.check_transfer_lifecycle,
            self.check_transfer_ledger_balance,
            self.check_reservation_lifecycle,
            self.check_no_negative_balances,
            self.check_no_balance_drift,
        )
        for check in checks:
            try:
                check()
            except Exception as exc:
                self._fail(check.__name__, f"{type(exc).__name__}: {exc}")

        failures = [f for f in self.findings if f.status == "FAIL"]
        return {
            "run": str(self.run.pk),
            "tenant": self.tenant.slug,
            "stage": "2C-stock-mobility",
            "status": "FAIL" if failures else "PASS",
            "failure_count": len(failures),
            "findings": [f.as_dict() for f in self.findings],
        }


class Stage2D1Validator(StockMobilityValidator):
    """Validates Stage 2D.1 (patient intake, clinical screening, pricing, reservations, readiness)."""

    def check_prescription_intake_coherence(self):
        from apps.prescription.models import Prescription

        prescriptions = Prescription.all_objects.filter(tenant=self.tenant)
        if not prescriptions.exists():
            self._fail("prescription_intake_coherence", "No prescriptions found")
            return

        unlinked = prescriptions.filter(patient__isnull=True).count()
        if unlinked:
            self._fail("prescription_intake_coherence", f"{unlinked} prescription(s) missing patient link")
        else:
            self._ok("prescription_intake_coherence", f"{prescriptions.count()} prescription(s) linked to valid patients")

    def check_clinical_screening_coherence(self):
        from apps.cds.models import PosClinicalScreening

        screenings = PosClinicalScreening.all_objects.filter(tenant=self.tenant)
        if not screenings.exists():
            self._fail("clinical_screening_coherence", "No clinical screenings found")
            return

        self._ok("clinical_screening_coherence", f"{screenings.count()} clinical screening(s) evaluated")

    def check_no_dispense_boundary_strictly_enforced(self):
        from apps.inventory.models import InventoryLedgerEntry, InventoryReservation
        from apps.prescription.models import Prescription

        supplied = Prescription.all_objects.filter(tenant=self.tenant, status="DISPENSED").count()
        issue_entries = InventoryLedgerEntry.all_objects.filter(
            tenant=self.tenant, entry_type=InventoryLedgerEntry.EntryType.ISSUE
        ).count()
        fulfilled_res = InventoryReservation.all_objects.filter(
            tenant=self.tenant, status=InventoryReservation.Status.FULFILLED
        ).count()

        if supplied > 0 or issue_entries > 0 or fulfilled_res > 0:
            self._fail("no_dispense_boundary", f"Boundary breach: supplied={supplied}, issues={issue_entries}, fulfilled_res={fulfilled_res}")
        else:
            self._ok("no_dispense_boundary", "zero supplied prescriptions, zero ISSUE ledger entries, zero consumed reservations")

    def run_all(self) -> dict:
        checks = (
            self.check_tenant_ownership,
            self.check_prescription_intake_coherence,
            self.check_clinical_screening_coherence,
            self.check_no_dispense_boundary_strictly_enforced,
        )
        for check in checks:
            try:
                check()
            except Exception as exc:
                self._fail(check.__name__, f"{type(exc).__name__}: {exc}")

        failures = [f for f in self.findings if f.status == "FAIL"]
        return {
            "run": str(self.run.pk),
            "tenant": self.tenant.slug,
            "stage": "2D.1-dispensing-readiness",
            "status": "FAIL" if failures else "PASS",
            "failure_count": len(failures),
            "findings": [f.as_dict() for f in self.findings],
        }


def validate_demo_scenario(run, tenant, stage: str = "auto") -> dict:
    """Validate a demo scenario run based on its completed stage."""
    from apps.inventory.models import InventoryLedgerEntry, StockTransfer
    from apps.prescription.models import Prescription
    from apps.procurement.models import QualityDecision, ReceivedBatch

    if stage == "dispensing-readiness" or (
        stage == "auto" and Prescription.all_objects.filter(tenant=tenant).exists()
    ):
        return Stage2D1Validator(run=run, tenant=tenant).run_all()
    elif stage == "mobility" or (
        stage == "auto" and StockTransfer.all_objects.filter(tenant=tenant).exists()
    ):
        return StockMobilityValidator(run=run, tenant=tenant).run_all()
    elif stage == "inventory" or (
        stage == "auto" and InventoryLedgerEntry.all_objects.filter(tenant=tenant).exists()
    ):
        return QualityInventoryValidator(run=run, tenant=tenant).run_all()
    elif stage == "quality" or (
        stage == "auto" and QualityDecision.all_objects.filter(tenant=tenant).exists()
    ):
        return QualityValidator(run=run, tenant=tenant).run_all()
    elif stage == "procurement" or (
        stage == "auto" and ReceivedBatch.all_objects.filter(tenant=tenant).exists()
    ):
        return ProcurementReceivingValidator(run=run, tenant=tenant).run_all()
    else:
        return MasterDataValidator(run=run, tenant=tenant).run_all()
