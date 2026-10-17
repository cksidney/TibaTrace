"""Tests for POS shift and session served customer count metrics."""
from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.identity.models import Role, User, UserRole
from apps.inventory.models import InventoryLocation
from apps.organizations.models import Location, Organization
from apps.pos_shift.customer_metrics import (
    count_served_customers_for_session,
    count_served_customers_for_shift,
)
from apps.pos_shift.models import BusinessDay, OperatorShift, PosRegister, RegisterSession
from apps.pos_transactions.models import PosTransaction
from apps.prescription.models import DispensingEpisode
from apps.tenancy.models import Tenant


@pytest.fixture
def shift_context(db):
    tenant = Tenant.objects.create(name="Customer Count Test Tenant", slug="cust-tenant")
    org = Organization.all_objects.create(tenant=tenant, code="ORG-CC", name="Group")
    branch = Location.all_objects.create(tenant=tenant, organization=org, code="BR-CC", name="Test Branch", location_type="PHARMACY")
    store = InventoryLocation.all_objects.create(tenant=tenant, branch=branch, location_code="DISP-01", name="Dispensary Store")
    operator = User.objects.create_user(username="cashier-test", password="pw", tenant=tenant)

    role = Role.all_objects.create(
        tenant=tenant,
        code="CASHIER_ROLE",
        name="Cashier",
        capabilities=["pos.shift.manage", "pos.transaction.create", "pos.session.view"],
    )
    UserRole.all_objects.create(tenant=tenant, user=operator, role=role)

    register = PosRegister.all_objects.create(
        tenant=tenant, location=branch, code="TILL-CC", name="Counter Till", state="OPEN", device_id="DEV-CC-01"
    )
    business_day = BusinessDay.all_objects.create(
        tenant=tenant, location=branch, business_date=date.today(), state="OPEN"
    )
    session = RegisterSession.all_objects.create(
        tenant=tenant, register=register, business_day=business_day, opened_by=operator, state="OPEN"
    )
    shift = OperatorShift.all_objects.create(
        tenant=tenant, register_session=session, operator=operator, state="OPEN"
    )

    from apps.patients.models import Patient
    from apps.practitioners.models import Practitioner
    from apps.prescription.models import Prescription

    patient = Patient.all_objects.create(
        tenant=tenant,
        internal_reference_id="PAT-CC-01",
        first_name="Jane",
        last_name="Doe",
        sex="FEMALE",
        date_of_birth=date(1990, 1, 1),
    )
    practitioner = Practitioner.all_objects.create(
        tenant=tenant,
        registration_number="DOC-CC-01",
        first_name="Dr",
        last_name="Who",
        profession="DOCTOR",
    )
    rx = Prescription.all_objects.create(
        tenant=tenant,
        patient=patient,
        practitioner=practitioner,
        organization=org,
        location=branch,
        prescription_number="RX-CC-01",
    )

    return {
        "tenant": tenant,
        "branch": branch,
        "store": store,
        "operator": operator,
        "register": register,
        "business_day": business_day,
        "session": session,
        "shift": shift,
        "patient": patient,
        "prescription": rx,
    }


def test_empty_shift_served_customer_count(shift_context):
    shift = shift_context["shift"]
    session = shift_context["session"]
    assert count_served_customers_for_shift(shift) == 0
    assert count_served_customers_for_session(session) == 0


def test_retail_transactions_counted_when_paid_or_completed(shift_context):
    ctx = shift_context
    shift = ctx["shift"]
    session = ctx["session"]

    # Draft transaction: should not be counted
    PosTransaction.all_objects.create(
        tenant=ctx["tenant"],
        branch=ctx["branch"],
        store=ctx["store"],
        register=ctx["register"],
        register_session=session,
        operator_shift=shift,
        business_day=ctx["business_day"],
        operator=ctx["operator"],
        device_id="DEV-CC-01",
        state=PosTransaction.State.DRAFT,
        transaction_number="TX-DRAFT-01",
    )
    assert count_served_customers_for_shift(shift) == 0

    # Completed transaction: must be counted
    PosTransaction.all_objects.create(
        tenant=ctx["tenant"],
        branch=ctx["branch"],
        store=ctx["store"],
        register=ctx["register"],
        register_session=session,
        operator_shift=shift,
        business_day=ctx["business_day"],
        operator=ctx["operator"],
        device_id="DEV-CC-01",
        state=PosTransaction.State.COMPLETED,
        transaction_number="TX-COMPLETED-01",
        total=Decimal("250.00"),
    )
    assert count_served_customers_for_shift(shift) == 1
    assert count_served_customers_for_session(session) == 1

    # Paid transaction: must be counted
    PosTransaction.all_objects.create(
        tenant=ctx["tenant"],
        branch=ctx["branch"],
        store=ctx["store"],
        register=ctx["register"],
        register_session=session,
        operator_shift=shift,
        business_day=ctx["business_day"],
        operator=ctx["operator"],
        device_id="DEV-CC-01",
        state=PosTransaction.State.PAID,
        transaction_number="TX-PAID-01",
        total=Decimal("500.00"),
    )
    assert count_served_customers_for_shift(shift) == 2
    assert count_served_customers_for_session(session) == 2


def test_dispensing_episodes_counted_when_paid_or_supplied(shift_context):
    ctx = shift_context
    shift = ctx["shift"]
    session = ctx["session"]

    # Draft episode: should not count
    DispensingEpisode.all_objects.create(
        tenant=ctx["tenant"],
        branch=ctx["branch"],
        prescription=ctx["prescription"],
        patient=ctx["patient"],
        pharmacy_location=ctx["store"],
        pharmacist=ctx["operator"],
        idempotency_key="IDEMP-EP-01",
        dispensing_number="EP-DRAFT-01",
        status="DRAFT",
        payment_register_session=session,
        payment_operator_shift=shift,
    )
    assert count_served_customers_for_shift(shift) == 0

    # Paid episode: must count
    DispensingEpisode.all_objects.create(
        tenant=ctx["tenant"],
        branch=ctx["branch"],
        prescription=ctx["prescription"],
        patient=ctx["patient"],
        pharmacy_location=ctx["store"],
        pharmacist=ctx["operator"],
        idempotency_key="IDEMP-EP-02",
        dispensing_number="EP-PAID-01",
        status="PAID",
        payment_register_session=session,
        payment_operator_shift=shift,
    )
    assert count_served_customers_for_shift(shift) == 1

    # Supplied episode: must count
    DispensingEpisode.all_objects.create(
        tenant=ctx["tenant"],
        branch=ctx["branch"],
        prescription=ctx["prescription"],
        patient=ctx["patient"],
        pharmacy_location=ctx["store"],
        pharmacist=ctx["operator"],
        idempotency_key="IDEMP-EP-03",
        dispensing_number="EP-SUPPLIED-01",
        status="SUPPLIED",
        payment_register_session=session,
        payment_operator_shift=shift,
    )
    assert count_served_customers_for_shift(shift) == 2
    assert count_served_customers_for_session(session) == 2


def test_serializer_surfaces_served_customer_count(shift_context):
    from apps.pos_shift.api.serializers import OperatorShiftSerializer, RegisterSessionSerializer

    ctx = shift_context
    shift = ctx["shift"]
    session = ctx["session"]

    PosTransaction.all_objects.create(
        tenant=ctx["tenant"],
        branch=ctx["branch"],
        store=ctx["store"],
        register=ctx["register"],
        register_session=session,
        operator_shift=shift,
        business_day=ctx["business_day"],
        operator=ctx["operator"],
        device_id="DEV-CC-01",
        state=PosTransaction.State.COMPLETED,
        transaction_number="TX-SER-01",
    )

    shift_data = OperatorShiftSerializer(shift).data
    assert shift_data["served_customer_count"] == 1

    session_data = RegisterSessionSerializer(session).data
    assert session_data["served_customer_count"] == 1
