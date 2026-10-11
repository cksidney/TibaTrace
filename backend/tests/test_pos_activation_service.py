import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.identity.models import Role, User, UserRole
from apps.organizations.models import Location, Organization
from apps.platform.pos_activation import PosActivationRequest
from apps.pos_shift.models import PosRegister
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db
TENANT_PATH = "/api/v1/tenant/pos-activations/requests/"
PLATFORM_PATH = "/api/v1/platform/pos-activations/requests/"


def authenticated(user, tenant):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer " + str(AccessToken.for_user(user)), HTTP_X_TENANT_ID=str(tenant.pk))
    return client


@pytest.fixture
def context():
    tenant = Tenant.objects.create(name="Activation tenant", slug="activation-test")
    org = Organization.all_objects.create(tenant=tenant, code="ORG", name="Organisation")
    branch = Location.all_objects.create(tenant=tenant, organization=org, code="BR", name="Branch")
    register = PosRegister.all_objects.create(tenant=tenant, location=branch, code="REG1", name="Till", state="AVAILABLE")
    manager = User.objects.create_user(username="activation-manager", tenant=tenant)
    owner = User.objects.create_user(username="activation-owner", is_platform_admin=True)
    role = Role.all_objects.create(tenant=tenant, code="MANAGER", name="Manager", capabilities=["identity.manage"])
    UserRole.all_objects.create(tenant=tenant, role=role, user=manager)
    body = {"tenant_id": str(tenant.pk), "branch_id": str(branch.pk), "requested_register": register.code,
            "device_id": "TEST-DEVICE-001", "device_fingerprint": "stable-fingerprint-test-001",
            "device_name": "Counter One", "device_type": "DESKTOP_WINDOWS",
            "app_version": "1.0.3", "business_justification": "Primary supervised retail counter"}
    return tenant, register, manager, owner, body


def test_independent_approval_and_single_use_bound_enrolment(context):
    tenant, register, manager, owner, body = context
    user_client = authenticated(manager, tenant)
    owner_client = authenticated(owner, tenant)
    result = user_client.post(TENANT_PATH, body, format="json")
    assert result.status_code == 201, result.data
    record_id = result.data["id"]
    assert user_client.post(f"{PLATFORM_PATH}{record_id}/approve/", {"rationale": "Reviewed device identity"}, format="json").status_code == 403
    result = owner_client.post(f"{PLATFORM_PATH}{record_id}/approve/", {"rationale": "Reviewed device identity"}, format="json")
    assert result.status_code == 200, result.data
    code = result.data["challengeCode"]
    record = PosActivationRequest.all_objects.get(pk=record_id)
    assert code != record.challenge_hash
    assert "challengeCode" not in owner_client.get(PLATFORM_PATH).json()[0]
    enrol = {"challenge_code": code, "device_id": body["device_id"], "device_fingerprint": "wrong-identity"}
    assert user_client.post(f"{TENANT_PATH}{record_id}/enrol/", enrol, format="json").status_code == 403
    enrol["device_fingerprint"] = body["device_fingerprint"]
    issued = user_client.post(f"{TENANT_PATH}{record_id}/enrol/", enrol, format="json")
    assert issued.status_code == 200, issued.data
    assert issued.data["state"] == "ACTIVATED"
    record.refresh_from_db()
    register.refresh_from_db()
    assert record.challenge_hash == ""
    assert record.credential_hash != issued.data["signedToken"]
    assert register.device_id == body["device_id"]
    assert user_client.post(f"{TENANT_PATH}{record_id}/enrol/", enrol, format="json").status_code == 400
    validation = {"signed_token": issued.data["signedToken"], "device_id": body["device_id"],
                  "device_fingerprint": body["device_fingerprint"]}
    assert user_client.post(f"{TENANT_PATH}validate/", validation, format="json").status_code == 200
    assert owner_client.post(f"{PLATFORM_PATH}{record_id}/revoke/", {"rationale": "Device retired by manager"}, format="json").status_code == 200
    record.refresh_from_db()
    assert record.credential_hash == ""
    assert user_client.post(f"{TENANT_PATH}validate/", validation, format="json").status_code == 403


def test_missing_device_identity_and_cross_tenant_request_are_denied(context):
    tenant, register, manager, owner, body = context
    client = authenticated(manager, tenant)
    body["device_id"] = ""
    assert client.post(TENANT_PATH, body, format="json").status_code == 400
    body["device_id"] = "TILL1"
    body["tenant_id"] = str(Tenant.objects.create(name="Other", slug="activation-other").pk)
    assert client.post(TENANT_PATH, body, format="json").status_code == 403
    assert PosActivationRequest.all_objects.count() == 0


def test_expired_challenge_stays_blocked(context):
    from datetime import timedelta

    from django.utils import timezone

    tenant, register, manager, owner, body = context
    user_client = authenticated(manager, tenant)
    record_id = user_client.post(TENANT_PATH, body, format="json").data["id"]
    code = authenticated(owner, tenant).post(f"{PLATFORM_PATH}{record_id}/approve/", {"rationale": "Independent device review"}, format="json").data["challengeCode"]
    PosActivationRequest.all_objects.filter(pk=record_id).update(challenge_expires_at=timezone.now() - timedelta(seconds=1))
    result = user_client.post(f"{TENANT_PATH}{record_id}/enrol/", {
        "challenge_code": code, "device_id": body["device_id"], "device_fingerprint": body["device_fingerprint"],
    }, format="json")
    assert result.status_code == 400


def test_duplicate_device_and_malformed_identifiers_fail_cleanly(context):
    tenant, register, manager, owner, body = context
    client = authenticated(manager, tenant)
    assert client.post(TENANT_PATH, body, format="json").status_code == 201
    assert client.post(TENANT_PATH, body, format="json").status_code == 400
    assert client.post(f"{TENANT_PATH}not-a-uuid/enrol/", {}, format="json").status_code == 404
    assert authenticated(owner, tenant).get(PLATFORM_PATH + "?tenant_id=not-a-uuid").status_code == 400
    assert client.post(f"{TENANT_PATH}validate/", {"signed_token": "tampered"}, format="json").status_code == 403


def test_production_operations_require_bound_non_revoked_credential(context, settings):
    settings.DEBUG = False
    settings.TESTING = False
    tenant, register, manager, owner, body = context
    client = authenticated(manager, tenant)
    blocked = client.post("/api/pos/retail/transactions/draft/", {}, format="json")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "pos_activation_required"
    record_id = client.post(TENANT_PATH, body, format="json").data["id"]
    owner_client = authenticated(owner, tenant)
    challenge = owner_client.post(f"{PLATFORM_PATH}{record_id}/approve/", {"rationale": "Independent production review"}, format="json").data["challengeCode"]
    issued = client.post(f"{TENANT_PATH}{record_id}/enrol/", {"challenge_code": challenge, "device_id": body["device_id"],
        "device_fingerprint": body["device_fingerprint"]}, format="json").data
    headers = {"HTTP_X_POS_ACTIVATION": issued["signedToken"], "HTTP_X_POS_DEVICE_ID": body["device_id"],
               "HTTP_X_POS_FINGERPRINT": body["device_fingerprint"]}
    # A valid credential reaches ordinary request validation, rather than being treated as activated by the UI.
    assert client.post("/api/pos/retail/transactions/draft/", {}, format="json", **headers).status_code == 400
    assert client.post("/api/pos/retail/transactions/draft/", {"device_id": "other-device"}, format="json", **headers).status_code == 403
    owner_client.post(f"{PLATFORM_PATH}{record_id}/revoke/", {"rationale": "Production device retired"}, format="json")
    assert client.post("/api/pos/retail/transactions/draft/", {}, format="json", **headers).status_code == 403
