"""Whether the procurement API can move state without its services.

The viewsets expose service-routed actions -- approve, send, close -- and those
enforce separation of duties, supplier re-checks and closure preconditions. They
are also ModelViewSets, which means a generic PATCH exists alongside those
actions and writes the same columns.

These tests establish which of the two is true: that the generic write is
blocked, or that every control the services enforce can be stepped around by
sending the field directly.
"""
from datetime import date, timedelta

import pytest
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
from apps.procurement.models import PurchaseOrder, SupplierQualification
from apps.procurement.services import (
    ProcurementService,
    PurchaseRequisitionService,
    SupplierGovernanceService,
)
from apps.tenancy.models import Tenant

TODAY = date.today()
QT = SupplierQualification.QualificationType
VS = SupplierQualification.QualificationVerificationStatus


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="Bypass Tenant", slug="bypass-tenant")
    org = Organization.all_objects.create(tenant=tenant, code="ORG-BP", name="Group")
    branch = Location.all_objects.create(
        tenant=tenant, organization=org, code="BR-BP", name="Branch"
    )
    requester = User.objects.create_user(username="bp-requester", password="pw", tenant=tenant)
    approver = User.objects.create_user(username="bp-approver", password="pw", tenant=tenant)

    supplier = SupplierGovernanceService.create_supplier(
        tenant=tenant, supplier_code="SUP-BP", legal_name="Bypass Supplier"
    )
    SupplierGovernanceService.approve_supplier(supplier=supplier, approver=approver)
    for qualification in (QT.BUSINESS_REGISTRATION, QT.WHOLESALE_DEALER_LICENCE):
        SupplierQualification.all_objects.create(
            tenant=tenant, supplier=supplier, qualification_type=qualification,
            licence_number=f"L-{qualification[:6]}", verification_status=VS.VERIFIED,
            effective_date=TODAY - timedelta(days=1),
            expiry_date=TODAY + timedelta(days=365),
        )

    dose = DoseForm.objects.create(code="BP-CAP", name="Capsule")
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant, code="BP-CMP", canonical_name="Item", dose_form=dose
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant, code="BP-MP", brand_name="Brand", clinical_product=clinical
    )
    package = PackageDefinition.objects.create(
        code="BP-PK", description="Pack", unit_of_measure="unit"
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="BP-SKU", display_name="Item",
        manufactured_product=manufactured, package_definition=package,
    )

    requisition = ProcurementService.create_requisition(
        tenant=tenant, requesting_branch=branch, requester=requester,
        requested_delivery_date=TODAY, requisition_number="REQ-BP",
    )
    ProcurementService.add_line(requisition=requisition, sku=sku, requested_quantity=10)
    PurchaseRequisitionService.submit_requisition(requisition=requisition)
    PurchaseRequisitionService.approve_requisition(
        requisition=requisition, approver=approver
    )
    purchase_order = ProcurementService.create_po_from_requisition(
        tenant=tenant, supplier=supplier, requisition=requisition,
        ordering_branch=branch, creator=requester, po_number="PO-BP",
        order_date=TODAY, expected_delivery_date=TODAY,
    )

    api = APIClient()
    api.force_authenticate(user=requester)
    return {
        "tenant": tenant, "supplier": supplier, "po": purchase_order,
        "requisition": requisition, "requester": requester, "approver": approver,
        "client": api,
    }


def po_detail(world) -> str:
    return f"/api/procurement/purchase-orders/{world['po'].pk}/"


class TestTheApiIsReachableAtAll:
    def test_the_purchase_order_list_returns_rows(self, world):
        """Establishes the API works before testing what it permits.

        A 404 on every detail route would make the bypass tests pass for the
        wrong reason -- unreachable is not the same as blocked.
        """
        response = world["client"].get("/api/procurement/purchase-orders/")
        assert response.status_code == 200
        body = response.json()
        rows = body["results"] if isinstance(body, dict) and "results" in body else body
        assert len(rows) >= 1, (
            "The purchase-order list is empty for a tenant that has one. "
            "get_queryset uses the tenant-strict default manager, which returns "
            "nothing when no tenant context is set on the request."
        )


class TestGenericWriteBypass:
    """A generic write that sets state is a second path to every control.

    The service refuses to approve for a suspended supplier, refuses a
    requisition approved by its own requester, and refuses to send an unapproved
    order. None of that runs on a PATCH.
    """

    def test_a_patch_cannot_approve_a_purchase_order(self, world):
        response = world["client"].patch(
            po_detail(world), {"status": PurchaseOrder.Status.APPROVED}, format="json"
        )
        world["po"].refresh_from_db()

        assert response.status_code in (403, 405), (
            "A generic PATCH set the purchase-order status directly, skipping "
            "approve_purchase_order and with it the supplier re-check."
        )
        assert world["po"].status != PurchaseOrder.Status.APPROVED

    def test_a_patch_cannot_approve_for_a_suspended_supplier(self, world):
        """The control this bypass defeats.

        A supplier suspended between drafting and approval must not receive the
        order, and approve_purchase_order re-checks for exactly that.
        """
        SupplierGovernanceService.suspend_supplier(
            supplier=world["supplier"], reason="Compliance violation"
        )
        world["client"].patch(
            po_detail(world), {"status": PurchaseOrder.Status.APPROVED}, format="json"
        )
        world["po"].refresh_from_db()
        assert world["po"].status != PurchaseOrder.Status.APPROVED

    def test_a_patch_cannot_send_an_unapproved_order(self, world):
        world["client"].patch(
            po_detail(world), {"status": PurchaseOrder.Status.SENT}, format="json"
        )
        world["po"].refresh_from_db()
        assert world["po"].status != PurchaseOrder.Status.SENT

    def test_a_put_cannot_replace_a_purchase_order(self, world):
        response = world["client"].put(
            po_detail(world), {"status": PurchaseOrder.Status.APPROVED}, format="json"
        )
        assert response.status_code in (400, 403, 405)

    def test_a_delete_cannot_remove_a_purchase_order(self, world):
        # A purchase order is a commitment. Cancellation is a state, not a
        # deletion, and removing the row loses what was committed to.
        response = world["client"].delete(po_detail(world))
        assert response.status_code in (403, 405)
        assert PurchaseOrder.all_objects.filter(pk=world["po"].pk).exists()


class TestServiceRoutedActionsStillWork:
    """Blocking the generic write must not block the legitimate path."""

    def test_the_approve_action_works(self, world):
        world["client"].force_authenticate(user=world["approver"])
        response = world["client"].post(f"{po_detail(world)}approve/")
        assert response.status_code == 200
        world["po"].refresh_from_db()
        assert world["po"].status == PurchaseOrder.Status.APPROVED

    def test_the_approve_action_still_re_checks_the_supplier(self, world):
        SupplierGovernanceService.suspend_supplier(
            supplier=world["supplier"], reason="Licence lapsed"
        )
        world["client"].force_authenticate(user=world["approver"])
        response = world["client"].post(f"{po_detail(world)}approve/")
        assert response.status_code >= 400
        world["po"].refresh_from_db()
        assert world["po"].status != PurchaseOrder.Status.APPROVED
