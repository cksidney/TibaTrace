"""Supplier governance and purchase eligibility.

The rule: a purchase order may only go to a supplier who is allowed to receive
one. That is not the same as a supplier who exists.

Expired licences are the normal case, not the exotic one — they lapse annually
and nobody notices until an inspector asks. So expiry is checked against the
order date, and every reason a supplier is ineligible is returned at once.
"""
from datetime import date, timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.procurement.models import Supplier, SupplierQualification
from apps.procurement.services import SupplierGovernanceService, SupplierNotQualified
from apps.procurement.services.supplier_governance_service import (
    BASELINE_QUALIFICATIONS,
    PURCHASABLE_STATUSES,
)
from apps.tenancy.models import Tenant

QT = SupplierQualification.QualificationType
VS = SupplierQualification.QualificationVerificationStatus


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Procurement Tenant", slug="proc-tenant")


@pytest.fixture
def supplier(tenant):
    return SupplierGovernanceService.create_supplier(
        tenant=tenant, supplier_code="SUP-001", legal_name="Demo Pharma Distributors"
    )


def qualify(supplier, qualification_type, *, status=VS.VERIFIED,
            valid_from=None, valid_to=None):
    return SupplierQualification.all_objects.create(
        tenant=supplier.tenant,
        supplier=supplier,
        qualification_type=qualification_type,
        licence_number=f"LIC-{qualification_type[:8]}",
        verification_status=status,
        effective_date=valid_from or date.today() - timedelta(days=30),
        expiry_date=valid_to or date.today() + timedelta(days=365),
    )


def fully_qualify(supplier, **kwargs):
    for qualification_type in BASELINE_QUALIFICATIONS:
        qualify(supplier, qualification_type, **kwargs)


# ─── creation and approval ───────────────────────────────────────────────────


class TestSupplierCreation:
    def test_a_new_supplier_starts_prospective(self, supplier):
        # A newly typed supplier is a lead, not a counterparty, and creating one
        # must not be a route to placing an order with it.
        assert supplier.status == Supplier.Status.PROSPECTIVE

    def test_creation_is_idempotent(self, tenant, supplier):
        again = SupplierGovernanceService.create_supplier(
            tenant=tenant, supplier_code="SUP-001", legal_name="Different Name"
        )
        assert again.pk == supplier.pk

    def test_a_supplier_requires_a_code_and_a_name(self, tenant):
        with pytest.raises(ValidationError):
            SupplierGovernanceService.create_supplier(
                tenant=tenant, supplier_code="  ", legal_name="X"
            )
        with pytest.raises(ValidationError):
            SupplierGovernanceService.create_supplier(
                tenant=tenant, supplier_code="SUP-9", legal_name=""
            )


class TestSupplierApproval:
    def test_approval_requires_a_named_approver(self, supplier):
        # Approval turns a lead into a counterparty the organisation will pay.
        with pytest.raises(PermissionDenied):
            SupplierGovernanceService.approve_supplier(supplier=supplier, approver=None)

    def test_approval_moves_the_supplier_to_approved(self, supplier, django_user_model):
        approver = django_user_model.objects.create_user(
            username="buyer", password="pw", tenant=supplier.tenant
        )
        SupplierGovernanceService.approve_supplier(supplier=supplier, approver=approver)
        assert supplier.status == Supplier.Status.APPROVED

    def test_a_disqualified_supplier_is_not_quietly_reapproved(self, supplier, django_user_model):
        approver = django_user_model.objects.create_user(
            username="buyer2", password="pw", tenant=supplier.tenant
        )
        supplier.status = Supplier.Status.DISQUALIFIED
        supplier.save()
        with pytest.raises(ValidationError, match="Reinstate"):
            SupplierGovernanceService.approve_supplier(supplier=supplier, approver=approver)

    def test_suspension_requires_an_approver_and_a_reason(self, supplier, django_user_model):
        approver = django_user_model.objects.create_user(
            username="buyer3", password="pw", tenant=supplier.tenant
        )
        with pytest.raises(PermissionDenied):
            SupplierGovernanceService.suspend_supplier(
                supplier=supplier, approver=None, reason="Quality failures"
            )
        with pytest.raises(ValidationError):
            SupplierGovernanceService.suspend_supplier(
                supplier=supplier, approver=approver, reason="   "
            )


# ─── the purchasing gate ─────────────────────────────────────────────────────


class TestPurchaseEligibility:
    def test_a_prospective_supplier_cannot_receive_an_order(self, supplier):
        fully_qualify(supplier)
        # Qualified but not approved is still not purchasable.
        assert SupplierGovernanceService.can_receive_purchase_order(supplier=supplier) is False

    def test_an_approved_and_qualified_supplier_can(self, supplier):
        supplier.status = Supplier.Status.APPROVED
        supplier.save()
        fully_qualify(supplier)
        assert SupplierGovernanceService.can_receive_purchase_order(supplier=supplier) is True

    def test_a_suspended_supplier_cannot(self, supplier):
        supplier.status = Supplier.Status.SUSPENDED
        supplier.save()
        fully_qualify(supplier)
        assert SupplierGovernanceService.can_receive_purchase_order(supplier=supplier) is False

    def test_an_approved_supplier_without_qualifications_cannot(self, supplier):
        supplier.status = Supplier.Status.APPROVED
        supplier.save()
        # Approval is a commercial decision; it does not conjure a licence.
        assert SupplierGovernanceService.can_receive_purchase_order(supplier=supplier) is False

    def test_only_approved_and_active_may_purchase(self):
        assert PURCHASABLE_STATUSES == {Supplier.Status.APPROVED, Supplier.Status.ACTIVE}


class TestExpiry:
    def test_an_expired_licence_blocks_purchasing(self, supplier):
        """The normal failure, not the exotic one.

        Licences lapse annually and nobody notices until an inspector asks.
        """
        supplier.status = Supplier.Status.APPROVED
        supplier.save()
        fully_qualify(
            supplier,
            valid_from=date.today() - timedelta(days=400),
            valid_to=date.today() - timedelta(days=1),
        )
        assert SupplierGovernanceService.can_receive_purchase_order(supplier=supplier) is False

    def test_expiry_is_measured_against_the_order_date(self, supplier):
        supplier.status = Supplier.Status.APPROVED
        supplier.save()
        fully_qualify(
            supplier,
            valid_from=date.today() - timedelta(days=30),
            valid_to=date.today() + timedelta(days=10),
        )
        # Valid today.
        assert SupplierGovernanceService.can_receive_purchase_order(supplier=supplier) is True
        # Not valid for an order dated after the licence lapses.
        assert (
            SupplierGovernanceService.can_receive_purchase_order(
                supplier=supplier, on_date=date.today() + timedelta(days=60)
            )
            is False
        )

    def test_a_not_yet_valid_qualification_does_not_count(self, supplier):
        supplier.status = Supplier.Status.APPROVED
        supplier.save()
        fully_qualify(
            supplier,
            valid_from=date.today() + timedelta(days=10),
            valid_to=date.today() + timedelta(days=400),
        )
        assert SupplierGovernanceService.can_receive_purchase_order(supplier=supplier) is False

    def test_an_unverified_qualification_does_not_count(self, supplier):
        supplier.status = Supplier.Status.APPROVED
        supplier.save()
        fully_qualify(supplier, status=VS.PENDING)
        # An uploaded document is not a verified one.
        assert SupplierGovernanceService.can_receive_purchase_order(supplier=supplier) is False


class TestScopedQualifications:
    def test_controlled_medicines_need_a_controlled_licence(self, supplier):
        supplier.status = Supplier.Status.APPROVED
        supplier.save()
        fully_qualify(supplier)

        assert SupplierGovernanceService.can_receive_purchase_order(supplier=supplier) is True
        assert (
            SupplierGovernanceService.can_receive_purchase_order(
                supplier=supplier, controlled=True
            )
            is False
        )

        qualify(supplier, QT.CONTROLLED_DRUG_LICENCE)
        assert (
            SupplierGovernanceService.can_receive_purchase_order(
                supplier=supplier, controlled=True
            )
            is True
        )

    def test_cold_chain_needs_a_cold_chain_authorisation(self, supplier):
        supplier.status = Supplier.Status.APPROVED
        supplier.save()
        fully_qualify(supplier)

        assert (
            SupplierGovernanceService.can_receive_purchase_order(
                supplier=supplier, cold_chain=True
            )
            is False
        )
        qualify(supplier, QT.COLD_CHAIN_AUTHORIZATION)
        assert (
            SupplierGovernanceService.can_receive_purchase_order(
                supplier=supplier, cold_chain=True
            )
            is True
        )


class TestReasonReporting:
    def test_every_reason_is_returned_at_once(self, supplier):
        """A buyer told one problem at a time chases one document at a time."""
        reasons = SupplierGovernanceService.ineligibility_reasons(
            supplier=supplier, controlled=True, cold_chain=True
        )
        # Status, plus each missing qualification.
        assert len(reasons) >= 4
        assert any("status" in reason.lower() for reason in reasons)
        assert any("CONTROLLED_DRUG_LICENCE" in reason for reason in reasons)
        assert any("COLD_CHAIN_AUTHORIZATION" in reason for reason in reasons)

    def test_the_gate_raises_with_all_reasons(self, supplier):
        with pytest.raises(SupplierNotQualified) as refused:
            SupplierGovernanceService.assert_can_receive_purchase_order(supplier=supplier)
        assert "SUP-001" in str(refused.value)

    def test_the_gate_is_silent_when_eligible(self, supplier):
        supplier.status = Supplier.Status.APPROVED
        supplier.save()
        fully_qualify(supplier)
        SupplierGovernanceService.assert_can_receive_purchase_order(supplier=supplier)
