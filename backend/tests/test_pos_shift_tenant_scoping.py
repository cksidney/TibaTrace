"""Nested tenant-scoped relations must not depend on the thread-local.

`RegisterSession.operator_shifts` resolves through OperatorShift's default
manager, which is tenant-strict: it filters on a tenant id set on the thread by
middleware, and returns nothing when there is none.

The session queryset filters by tenant explicitly, so the outer list looked
correct while the nested one silently emptied. Two consequences, and the second
is the serious one:

* an open register session serialised with no accountable operator at all;
* `RegisterAuthorityService` decided readiness by looking for an active operator shift,
  found none, and told the till it was not ready to sell -- for a reason that had
  nothing to do with the till.

Both now prefetch explicitly. These tests run the queries with no tenant context
at all, which is the condition that exposed it.
"""
import pytest

from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id
from apps.identity.models import User
from apps.organizations.models import Location, Organization
from apps.pos_shift.authority import RegisterAuthorityService
from apps.pos_shift.models import (
    BusinessDay,
    OperatorShift,
    PosRegister,
    RegisterSession,
)
from apps.prescription.models import PosDeviceHealthRecord
from apps.tenancy.models import Tenant


@pytest.fixture
def world(db):
    tenant = Tenant.objects.create(name="Scoping Tenant", slug="shift-scoping")
    org = Organization.all_objects.create(tenant=tenant, code="ORG-SC", name="Group")
    branch = Location.all_objects.create(
        tenant=tenant, organization=org, code="BR-SC", name="Branch"
    )
    operator = User.objects.create_user(
        username="scoping-op", password="pw-scoping-long", tenant=tenant
    )
    register = PosRegister.all_objects.create(
        tenant=tenant, location=branch, code="TILL-SC", name="Front",
        state="OPEN", device_id="POS-SC-01",
    )
    from datetime import date

    day = BusinessDay.all_objects.create(
        tenant=tenant, location=branch, business_date=date.today(), state="OPEN"
    )
    session = RegisterSession.all_objects.create(
        tenant=tenant, register=register, business_day=day,
        opened_by=operator, state="OPEN",
    )
    shift = OperatorShift.all_objects.create(
        tenant=tenant, register_session=session, operator=operator, state="OPEN"
    )
    PosDeviceHealthRecord.all_objects.create(
        tenant=tenant, device_id="POS-SC-01", status="OK", printer_paper_level="OK"
    )
    return {
        "tenant": tenant, "operator": operator, "register": register,
        "session": session, "shift": shift,
    }


@pytest.fixture
def without_tenant_context():
    """No tenant id on the thread, which is what exposed the defect."""
    token = set_current_tenant_id(None)
    yield
    reset_current_tenant_id(token)


def test_the_bare_related_manager_really_does_return_nothing(world, without_tenant_context):
    """The premise, asserted rather than assumed.

    If this ever starts returning the shift, the strict manager has changed and
    the explicit prefetches below are guarding nothing.
    """
    assert world["session"].operator_shifts.count() == 0
    assert OperatorShift.all_objects.filter(register_session=world["session"]).count() == 1


def test_readiness_finds_the_operator_shift_without_tenant_context(
    world, without_tenant_context
):
    """The serious one.

    A till asks whether it may sell. Before the fix this answered ATTENTION
    because the operator shift could not be seen, which reads to an operator as
    "this register is not ready" with nothing on the register actually wrong.
    """
    status = RegisterAuthorityService.runtime_status(
        tenant=world["tenant"], device_id="POS-SC-01", actor=world["operator"]
    )
    assert status["readiness"] == "READY", status.get("notices")
    assert not any(
        "accountable operator shift" in notice for notice in status.get("notices", [])
    )


def test_the_session_serialises_with_its_operator_shift(world, without_tenant_context):
    """An open session with no accountable operator is not a session anybody can
    reconcile."""
    from apps.pos_shift.api.serializers import RegisterSessionSerializer

    prefetched = (
        RegisterSession.all_objects.filter(pk=world["session"].pk)
        .prefetch_related(
            __import__("django.db.models", fromlist=["Prefetch"]).Prefetch(
                "operator_shifts",
                queryset=OperatorShift.all_objects.filter(tenant=world["tenant"]),
            )
        )
        .first()
    )
    data = RegisterSessionSerializer(prefetched).data
    assert len(data["operator_shifts"]) == 1
    # The immutable id, not a username an administrator can rename while the
    # session is still open.
    assert data["operator_shifts"][0]["operator_id"] == str(world["operator"].pk)
