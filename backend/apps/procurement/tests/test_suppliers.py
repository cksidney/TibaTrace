import pytest

from apps.procurement.models import Supplier
from apps.procurement.services import SupplierGovernanceService
from apps.tenancy.models import Tenant


@pytest.mark.django_db
def test_supplier_governance_lifecycle():
    tenant = Tenant.objects.create(name="Supplier Tenant", slug="supplier-tenant")

    # 1. Create supplier
    supplier = SupplierGovernanceService.create_supplier(
        tenant=tenant,
        supplier_code="SUP-TEST-001",
        legal_name="Test Pharma Wholesalers Ltd",
        registration_number="REG12345",
    )
    assert supplier.status == Supplier.Status.PROSPECTIVE

    # 2. Approve supplier
    from django.contrib.auth import get_user_model
    User = get_user_model()
    approver = User.objects.create_user(username="approver", email="app@test.com", password="password123", tenant=tenant)  # nosec B106

    approved_supplier = SupplierGovernanceService.approve_supplier(
        supplier=supplier, approver=approver, reason="Qualified wholesale dealer"
    )
    assert approved_supplier.status == Supplier.Status.APPROVED
    assert approved_supplier.approved_by == approver

    # 3. Suspend supplier
    suspended_supplier = SupplierGovernanceService.suspend_supplier(supplier=approved_supplier, reason="Licence audit pending")
    assert suspended_supplier.status == Supplier.Status.SUSPENDED
    assert suspended_supplier.suspension_reason == "Licence audit pending"
