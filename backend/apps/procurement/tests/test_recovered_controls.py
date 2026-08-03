"""Two controls that existed but could not be called.

`apps/procurement/services.py` and `apps/procurement/services/` both existed.
Python resolves the package, so the module was dead: 23 KB of service code that
no import could reach. Anyone editing it would have seen no effect.

Almost all of it was duplicated in the package. Two things were not, and both are
guards rather than conveniences:

* `SupplierProductAgreementService` -- refuses to contract with a supplier
  governance has not approved. Its model was routed read-only in the API, so the
  agreement table was visible with no way to write a row at all.
* `SupplierReturnService.add_return_line` -- refuses to return more than the
  receipt actually rejected or quarantined.

Both are now in the package, and the shadowed module is deleted.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.procurement.models import (
    Supplier,
    SupplierProductAgreement,
    SupplierReturn,
)
from apps.procurement.services import (
    SupplierProductAgreementService,
    SupplierReturnService,
)
from apps.tenancy.models import Tenant


@pytest.fixture
def world(db):
    # Receiving locks the PO line through the tenant-strict manager, which is
    # correct in production because middleware sets tenant context per request.
    # A test calling the service directly has to supply it.
    from apps.core.tenant_context import set_current_tenant_id

    tenant = Tenant.objects.create(name="Proc Tenant", slug="proc-recovered")
    set_current_tenant_id(str(tenant.pk))
    org = Organization.all_objects.create(tenant=tenant, code="ORG-R", name="Org")
    branch = Location.all_objects.create(
        tenant=tenant, organization=org, code="BR-R", name="Branch"
    )
    dose = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})[0]
    pack = PackageDefinition.objects.get_or_create(
        code="PK-R", defaults={"description": "Pack", "unit_of_measure": "tablet"}
    )[0]
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant, code="CMP-R", canonical_name="Amoxicillin 500mg", dose_form=dose
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant, code="MP-R", brand_name="Amoxil", clinical_product=clinical
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code="SKU-R", display_name="Amoxil 500mg",
        manufactured_product=manufactured, package_definition=pack,
        # Explicitly ACTIVE. CommercialSKU defaults to DRAFT, and agreements now
        # refuse a SKU that is not active -- these tests are about *supplier*
        # status, so the product needs to be one a buyer could really contract
        # for rather than relying on an unset default.
        status=CommercialSKU.STATUS_ACTIVE,
    )
    return {"tenant": tenant, "branch": branch, "sku": sku}


def supplier(world, code="SUP-R", status=Supplier.Status.APPROVED):
    return Supplier.all_objects.create(
        tenant=world["tenant"], supplier_code=code,
        legal_name=f"{code} Distributors", status=status,
    )


class TestAgreementsRequireAnApprovedSupplier:
    def test_an_approved_supplier_can_be_contracted_with(self, world):
        agreement = SupplierProductAgreementService.register_agreement(
            tenant=world["tenant"], supplier=supplier(world), sku=world["sku"],
            agreed_unit_price=Decimal("240.00"),
        )
        assert agreement.agreed_unit_price == Decimal("240.00")
        assert agreement.status == SupplierProductAgreement.Status.ACTIVE

    def test_a_prospective_supplier_cannot_be_contracted_with(self, world):
        """An agreement is what a purchase order prices from.

        Contracting with a supplier governance has not cleared commits money to
        an unvetted party.
        """
        prospective = supplier(world, "SUP-PROSPECT", Supplier.Status.PROSPECTIVE)
        with pytest.raises(ValidationError, match="cannot be contracted with"):
            SupplierProductAgreementService.register_agreement(
                tenant=world["tenant"], supplier=prospective, sku=world["sku"],
                agreed_unit_price=Decimal("240.00"),
            )

    def test_a_suspended_supplier_cannot_be_contracted_with(self, world):
        # Suspension exists precisely to stop new commitments.
        suspended = supplier(world, "SUP-SUSP", Supplier.Status.SUSPENDED)
        with pytest.raises(ValidationError, match="cannot be contracted with"):
            SupplierProductAgreementService.register_agreement(
                tenant=world["tenant"], supplier=suspended, sku=world["sku"],
                agreed_unit_price=Decimal("240.00"),
            )

    def test_a_zero_price_is_refused(self, world):
        # It would make every order priced from it free.
        with pytest.raises(ValidationError, match="above zero"):
            SupplierProductAgreementService.register_agreement(
                tenant=world["tenant"], supplier=supplier(world, "SUP-ZERO"),
                sku=world["sku"], agreed_unit_price=Decimal("0.00"),
            )

    def test_registering_twice_is_refused_rather_than_silently_ignored(self, world):
        """The original used get_or_create and returned the existing row.

        A caller repricing an agreement would have been handed back the old
        price and told it had worked.
        """
        supp = supplier(world, "SUP-DUP")
        SupplierProductAgreementService.register_agreement(
            tenant=world["tenant"], supplier=supp, sku=world["sku"],
            agreed_unit_price=Decimal("240.00"),
        )
        with pytest.raises(ValidationError, match="Reprice it"):
            SupplierProductAgreementService.register_agreement(
                tenant=world["tenant"], supplier=supp, sku=world["sku"],
                agreed_unit_price=Decimal("300.00"),
            )

    def test_repricing_keeps_the_previous_price_in_the_event_trail(self, world):
        from apps.workflows.models import DomainEvent

        supp = supplier(world, "SUP-REPRICE")
        agreement = SupplierProductAgreementService.register_agreement(
            tenant=world["tenant"], supplier=supp, sku=world["sku"],
            agreed_unit_price=Decimal("240.00"),
        )
        SupplierProductAgreementService.reprice_agreement(
            agreement=agreement, agreed_unit_price=Decimal("310.00")
        )
        agreement.refresh_from_db()
        assert agreement.agreed_unit_price == Decimal("310.00")

        event = DomainEvent.all_objects.filter(
            event_type="SupplierProductAgreementRepriced"
        ).first()
        assert event is not None
        # What it was matters as much as what it is: a price rise nobody can
        # evidence is a price rise nobody can query.
        assert event.payload["previous_unit_price"] == "240.00"


class TestReturnsCannotExceedWhatWasRejected:
    """Built through the services, not by hand.

    A hand-made GoodsReceipt can skip required relations, and then the guard is
    tested against a receipt the domain could never produce.
    """

    def _requested_return(self, world, *, rejected=0, quarantined=0):
        import datetime

        from apps.identity.models import User
        from apps.procurement.models import SupplierQualification
        from apps.procurement.services import (
            GoodsReceivingService,
            PurchaseOrderService,
            PurchaseRequisitionService,
            SupplierGovernanceService,
        )

        tenant = world["tenant"]
        today = datetime.date.today()
        # Two people: procurement enforces segregation of duties, so the
        # requester may not approve their own requisition.
        user = User.objects.create_user(
            username=f"rec-{rejected}-{quarantined}", password="password123", tenant=tenant
        )
        approver = User.objects.create_user(
            username=f"rec-app-{rejected}-{quarantined}", password="password123", tenant=tenant
        )
        supp = SupplierGovernanceService.create_supplier(
            tenant=tenant, supplier_code=f"SUP-R{rejected}{quarantined}",
            legal_name="Recovered Supplier",
        )
        SupplierGovernanceService.approve_supplier(supplier=supp, approver=approver)
        for kind, extra in (
            (SupplierQualification.QualificationType.BUSINESS_REGISTRATION, {}),
            (SupplierQualification.QualificationType.WHOLESALE_DEALER_LICENCE,
             {"licence_number": "WDL-REC"}),
        ):
            SupplierQualification.objects.create(
                tenant=tenant, supplier=supp, qualification_type=kind,
                verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED,
                effective_date=today, expiry_date=today + datetime.timedelta(days=365),
                **extra,
            )

        req = PurchaseRequisitionService.create_requisition(
            tenant=tenant, requisition_number=f"REQ-R{rejected}{quarantined}",
            requesting_branch=world["branch"], requester=user,
            requested_delivery_date=today,
        )
        PurchaseRequisitionService.add_line(
            requisition=req, sku=world["sku"], requested_quantity=100
        )
        PurchaseRequisitionService.submit_requisition(requisition=req)
        PurchaseRequisitionService.approve_requisition(requisition=req, approver=approver)

        po = PurchaseOrderService.create_po_from_requisition(
            tenant=tenant, po_number=f"PO-R{rejected}{quarantined}", supplier=supp,
            requisition=req, ordering_branch=world["branch"], order_date=today,
            expected_delivery_date=today, creator=user,
        )
        PurchaseOrderService.approve_po(purchase_order=po, approver=approver)
        PurchaseOrderService.send_po(purchase_order=po)

        grn = GoodsReceivingService.start_goods_receipt(
            tenant=tenant, grn_number=f"GRN-R{rejected}{quarantined}",
            purchase_order=po, receiving_branch=world["branch"], receiver=user,
            delivery_note_number="DN-REC",
        )
        # all_objects: `po.lines` goes through the tenant-strict manager, which
        # returns nothing when no tenant context is set on the thread -- as here.
        from apps.procurement.models import PurchaseOrderLine

        po_line = PurchaseOrderLine.all_objects.filter(purchase_order=po).first()
        assert po_line is not None, "the requisition should have produced a PO line" 
        GoodsReceivingService.receive_line(
            goods_receipt=grn, po_line=po_line, delivered_quantity=100,
            accepted_quantity=100 - rejected - quarantined,
            rejected_quantity=rejected, quarantined_quantity=quarantined,
            # Receiving requires a reason for anything not accepted -- the same
            # discipline the return itself is held to.
            discrepancy_reason="Damaged in transit." if (rejected or quarantined) else "",
        )
        return SupplierReturnService.request_return(
            tenant=tenant, return_number=f"RET-R{rejected}{quarantined}",
            goods_receipt=grn, reason="Damaged in transit.",
        )

    def test_a_line_within_the_rejected_quantity_is_allowed(self, world):
        supplier_return = self._requested_return(world, rejected=10)
        line = SupplierReturnService.add_return_line(
            supplier_return=supplier_return, sku=world["sku"], quantity=10
        )
        assert line.quantity == 10

    def test_returning_more_than_was_rejected_is_refused(self, world):
        """The financial control.

        A return claiming more than was refused produces a credit claim the
        supplier will not honour and a stock position that never reconciles.
        """
        supplier_return = self._requested_return(world, rejected=10)
        with pytest.raises(ValidationError, match="remains eligible"):
            SupplierReturnService.add_return_line(
                supplier_return=supplier_return, sku=world["sku"], quantity=11
            )

    def test_the_allowance_is_cumulative_across_lines(self, world):
        """The version recovered from the dead module checked each line alone.

        Ten lines of ten against a ten-unit rejection would each have passed.
        """
        supplier_return = self._requested_return(world, rejected=10)
        SupplierReturnService.add_return_line(
            supplier_return=supplier_return, sku=world["sku"], quantity=6
        )
        with pytest.raises(ValidationError, match="remains eligible"):
            SupplierReturnService.add_return_line(
                supplier_return=supplier_return, sku=world["sku"], quantity=6
            )

    def test_quarantined_stock_counts_toward_the_allowance(self, world):
        supplier_return = self._requested_return(world, rejected=4, quarantined=6)
        line = SupplierReturnService.add_return_line(
            supplier_return=supplier_return, sku=world["sku"], quantity=10
        )
        assert line.quantity == 10

    def test_nothing_rejected_means_nothing_to_return(self, world):
        supplier_return = self._requested_return(world)
        with pytest.raises(ValidationError, match="nothing to return"):
            SupplierReturnService.add_return_line(
                supplier_return=supplier_return, sku=world["sku"], quantity=1
            )

    def test_lines_cannot_be_added_once_the_return_leaves_requested(self, world):
        # Past REQUESTED the quantities have been agreed with the supplier, and
        # adding to them silently changes what was agreed.
        supplier_return = self._requested_return(world, rejected=10)
        supplier_return.status = SupplierReturn.Status.APPROVED
        supplier_return.save(update_fields=["status"])
        with pytest.raises(ValidationError, match="still requested"):
            SupplierReturnService.add_return_line(
                supplier_return=supplier_return, sku=world["sku"], quantity=1
            )
