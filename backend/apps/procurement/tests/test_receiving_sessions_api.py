"""Scan-based receiving and quality decisions, over HTTP.

Both services existed with no route. A delivery could only be received by keying
quantities against order lines, and `QualityDecision` was a table nothing could
write -- so quarantined stock could only be released through the routine batch
release, which records no decision and names nobody. Quarantine exists precisely
because somebody has to decide.

Scanning catches what the keyed path cannot: goods that were never on this order,
and batches that arrive already expired.
"""
import datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.procurement.models import (
    PurchaseOrderLine,
    ReceivingSession,
    SupplierQualification,
)
from apps.procurement.services import (
    PurchaseOrderService,
    PurchaseRequisitionService,
    SupplierGovernanceService,
)
from apps.tenancy.models import Tenant

PASSWORD = "receiving-api-password"


@pytest.fixture(autouse=True)
def clear_throttle():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def world(db):
    from apps.core.tenant_context import set_current_tenant_id

    tenant = Tenant.objects.create(name="Recv Tenant", slug="recv-api-tenant")
    set_current_tenant_id(str(tenant.pk))
    today = datetime.date.today()

    receiver = User.objects.create_user(
        username="recv-user", password=PASSWORD, tenant=tenant
    )
    approver = User.objects.create_user(
        username="recv-approver", password=PASSWORD, tenant=tenant
    )
    org = Organization.all_objects.create(tenant=tenant, code="ORG-RC", name="Org")
    branch = Location.all_objects.create(
        tenant=tenant, organization=org, code="BR-RC", name="Branch"
    )
    dose = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})[0]
    pack = PackageDefinition.objects.get_or_create(
        code="PK-RC", defaults={"description": "Pack", "unit_of_measure": "tablet"}
    )[0]
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant, code="CMP-RC", canonical_name="Metformin 500mg", dose_form=dose
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant, code="MP-RC", brand_name="Glucophage", clinical_product=clinical
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="SKU-RC", display_name="Glucophage 500mg",
        manufactured_product=manufactured, package_definition=pack,
    )
    unordered_sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="SKU-RC-X", display_name="Never ordered",
        manufactured_product=manufactured, package_definition=pack,
    )

    supplier = SupplierGovernanceService.create_supplier(
        tenant=tenant, supplier_code="SUP-RC", legal_name="Receiving Supplier"
    )
    SupplierGovernanceService.approve_supplier(supplier=supplier, approver=approver)
    for kind, extra in (
        (SupplierQualification.QualificationType.BUSINESS_REGISTRATION, {}),
        (SupplierQualification.QualificationType.WHOLESALE_DEALER_LICENCE,
         {"licence_number": "WDL-RC"}),
    ):
        SupplierQualification.objects.create(
            tenant=tenant, supplier=supplier, qualification_type=kind,
            verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED,
            effective_date=today, expiry_date=today + datetime.timedelta(days=365),
            **extra,
        )

    req = PurchaseRequisitionService.create_requisition(
        tenant=tenant, requisition_number="REQ-RC", requesting_branch=branch,
        requester=receiver, requested_delivery_date=today,
    )
    PurchaseRequisitionService.add_line(requisition=req, sku=sku, requested_quantity=100)
    PurchaseRequisitionService.submit_requisition(requisition=req)
    PurchaseRequisitionService.approve_requisition(requisition=req, approver=approver)
    po = PurchaseOrderService.create_po_from_requisition(
        tenant=tenant, po_number="PO-RC", supplier=supplier, requisition=req,
        ordering_branch=branch, order_date=today, expected_delivery_date=today,
        creator=receiver,
    )
    PurchaseOrderService.approve_po(purchase_order=po, approver=approver)
    PurchaseOrderService.send_po(purchase_order=po)

    client = APIClient()
    assert client.post(
        "/api/identity/session/",
        {"username": "recv-user", "password": PASSWORD}, format="json",
    ).status_code == 200

    return {
        "tenant": tenant, "branch": branch, "sku": sku,
        "unordered_sku": unordered_sku, "po": po, "client": client,
    }


def open_session(world):
    response = world["client"].post(
        "/api/procurement/receiving-sessions/",
        {
            "purchase_order": str(world["po"].pk),
            "branch": str(world["branch"].pk),
            "delivery_note_number": "DN-RC-1",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return response.json()


def scan(world, session, sku, *, expiry_days=180, quantity="50.00", batch="B-1"):
    return world["client"].post(
        f"/api/procurement/receiving-sessions/{session['id']}/scan/",
        {
            "sku_id": str(sku.pk),
            "scanned_barcode": "6161100000001",
            "batch_number": batch,
            "expiry_date": (
                timezone.localdate() + datetime.timedelta(days=expiry_days)
            ).isoformat(),
            "scanned_quantity": quantity,
        },
        format="json",
    )


class TestScanBasedReceiving:
    def test_a_session_opens_against_a_sent_order(self, world):
        session = open_session(world)
        assert session["status"] == "ACTIVE"
        assert session["po_number"] == "PO-RC"
        assert session["session_number"].startswith("RCV-")

    def test_a_scan_is_recorded_against_the_session(self, world):
        session = open_session(world)
        response = scan(world, session, world["sku"])
        assert response.status_code == 201, response.content
        assert response.json()["batch_number"] == "B-1"

    def test_goods_not_on_the_order_are_refused(self, world):
        """What the keyed path cannot catch.

        Keying quantities against order lines cannot notice a pallet that was
        never ordered, because there is no line to key it against.
        """
        session = open_session(world)
        response = scan(world, session, world["unordered_sku"])
        assert response.status_code == 400
        assert "not included in Purchase Order" in str(response.json())

    def test_a_batch_that_has_already_expired_is_refused(self, world):
        session = open_session(world)
        response = scan(world, session, world["sku"], expiry_days=-1)
        assert response.status_code == 400
        assert "already expired" in str(response.json())

    def test_session_numbers_do_not_repeat(self, world):
        """They came from a row count.

        Remove one session and the next reuses a number already in the audit
        trail against different goods.
        """
        first = open_session(world)
        second = open_session(world)
        assert first["session_number"] != second["session_number"]

        ReceivingSession.all_objects.filter(pk=first["id"]).delete()
        third = open_session(world)
        assert third["session_number"] != second["session_number"]


class TestTheSurfaceStaysGoverned:
    def test_a_session_cannot_be_closed_by_patching_status(self, world):
        session = open_session(world)
        response = world["client"].patch(
            f"/api/procurement/receiving-sessions/{session['id']}/",
            {"status": "CLOSED"}, format="json",
        )
        assert response.status_code in (403, 405)

    def test_an_anonymous_caller_cannot_open_a_session(self, world):
        response = APIClient().post(
            "/api/procurement/receiving-sessions/",
            {
                "purchase_order": str(world["po"].pk),
                "branch": str(world["branch"].pk),
                "delivery_note_number": "DN-X",
            },
            format="json",
        )
        assert response.status_code in (401, 403)

    def test_releasing_quarantine_requires_a_stated_decision(self, world):
        """Quarantine exists because somebody has to decide.

        The routine batch release records no decision and names nobody, which is
        why the quality path is separate.
        """
        session = open_session(world)
        response = world["client"].post(
            f"/api/procurement/receiving-sessions/{session['id']}/release-quarantine/",
            {"batch_id": str(world["sku"].pk)}, format="json",
        )
        # Refused for the missing decision notes, before any batch lookup.
        assert response.status_code == 400
        assert "decision_notes" in str(response.json())


class TestOrderStateIsRespected:
    def test_a_draft_order_cannot_be_received_against(self, world):
        from apps.procurement.models import PurchaseOrder

        draft = PurchaseOrder.all_objects.filter(pk=world["po"].pk).first()
        draft.status = PurchaseOrder.Status.DRAFT
        draft.save(update_fields=["status"])

        response = world["client"].post(
            "/api/procurement/receiving-sessions/",
            {
                "purchase_order": str(draft.pk),
                "branch": str(world["branch"].pk),
                "delivery_note_number": "DN-DRAFT",
            },
            format="json",
        )
        assert response.status_code == 400
        assert "Cannot receive goods" in str(response.json())

    def test_the_order_line_lookup_uses_an_explicit_tenant_filter(self, world):
        """Guards a fix the service already carries.

        `session.purchase_order.lines` goes through the tenant-strict manager and
        returns nothing without tenant context, which made a legitimate delivery
        read as the wrong goods arriving.
        """
        session = open_session(world)
        assert PurchaseOrderLine.all_objects.filter(
            purchase_order=world["po"]
        ).exists()
        assert scan(world, session, world["sku"]).status_code == 201
