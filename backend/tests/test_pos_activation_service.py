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


def activate(context):
    tenant, register, manager, owner, body = context
    client, owner_client = authenticated(manager, tenant), authenticated(owner, tenant)
    record_id = client.post(TENANT_PATH, body, format="json").data["id"]
    code = owner_client.post(f"{PLATFORM_PATH}{record_id}/approve/", {"rationale": "Independent device review"}, format="json").data["challengeCode"]
    issued = client.post(f"{TENANT_PATH}{record_id}/enrol/", {"challenge_code": code, "device_id": body["device_id"], "device_fingerprint": body["device_fingerprint"]}, format="json")
    assert issued.status_code == 200
    return client, owner_client, record_id, issued.data


def test_expired_code_can_be_reissued_without_duplicate_request(context):
    from datetime import timedelta

    from django.utils import timezone

    tenant, register, manager, owner, body = context
    client, owner_client = authenticated(manager, tenant), authenticated(owner, tenant)
    record_id = client.post(TENANT_PATH, body, format="json").data["id"]
    first = owner_client.post(f"{PLATFORM_PATH}{record_id}/approve/", {"rationale": "Independent device review"}, format="json").data["challengeCode"]
    PosActivationRequest.all_objects.filter(pk=record_id).update(challenge_expires_at=timezone.now() - timedelta(seconds=1))
    assert client.post(f"{PLATFORM_PATH}{record_id}/issue-code/", {"rationale": "Recover expired enrolment code"}, format="json").status_code == 403
    result = owner_client.post(f"{PLATFORM_PATH}{record_id}/issue-code/", {"rationale": "Recover expired enrolment code"}, format="json")
    assert result.status_code == 200 and result.data["challengeCode"] != first
    assert result["Cache-Control"] == "no-store"
    enrol = {"device_id": body["device_id"], "device_fingerprint": body["device_fingerprint"], "challenge_code": first}
    assert client.post(f"{TENANT_PATH}{record_id}/enrol/", enrol, format="json").status_code == 400
    enrol["challenge_code"] = result.data["challengeCode"]
    assert client.post(f"{TENANT_PATH}{record_id}/enrol/", enrol, format="json").status_code == 200
    assert PosActivationRequest.all_objects.count() == 1


def test_renewal_recovers_lost_local_credential_and_rotates_old_token(context):
    client, owner_client, record_id, issued = activate(context)
    validation = {"signed_token": issued["signedToken"], "device_id": issued["deviceId"], "device_fingerprint": issued["deviceFingerprint"]}
    result = owner_client.post(f"{PLATFORM_PATH}{record_id}/issue-code/", {"rationale": "Renew verified original installation"}, format="json")
    assert result.status_code == 200
    # Issuing a recovery code does not interrupt an existing valid credential.
    assert client.post(TENANT_PATH + "validate/", validation, format="json").status_code == 200
    new = client.post(f"{TENANT_PATH}{record_id}/enrol/", {**validation, "challenge_code": result.data["challengeCode"]}, format="json")
    assert new.status_code == 200 and new.data["signedToken"] != issued["signedToken"]
    assert client.post(TENANT_PATH + "validate/", validation, format="json").status_code == 403
    validation["signed_token"] = new.data["signedToken"]
    assert client.post(TENANT_PATH + "validate/", validation, format="json").status_code == 200
    assert client.post(f"{TENANT_PATH}{record_id}/enrol/", {**validation, "challenge_code": result.data["challengeCode"]}, format="json").status_code == 400


def test_suspended_device_cannot_trade_or_create_replacement_and_resumes(context):
    tenant, register, manager, owner, body = context
    client, owner_client, record_id, issued = activate(context)
    validation = {"signed_token": issued["signedToken"], "device_id": issued["deviceId"], "device_fingerprint": issued["deviceFingerprint"]}
    assert owner_client.post(f"{PLATFORM_PATH}{record_id}/suspend/", {"rationale": "Temporarily stop this device"}, format="json").status_code == 200
    assert client.post(TENANT_PATH + "validate/", validation, format="json").status_code == 403
    assert client.post(TENANT_PATH, body, format="json").status_code == 400
    assert owner_client.post(f"{PLATFORM_PATH}{record_id}/issue-code/", {"rationale": "Do not bypass a suspension"}, format="json").status_code == 400
    assert owner_client.post(f"{PLATFORM_PATH}{record_id}/resume/", {"rationale": "Independent resumption review"}, format="json").status_code == 200
    assert client.post(TENANT_PATH + "validate/", validation, format="json").status_code == 200


def test_expired_activation_renewal_requires_new_enrolment(context):
    from datetime import timedelta

    from django.utils import timezone

    client, owner_client, record_id, issued = activate(context)
    PosActivationRequest.all_objects.filter(pk=record_id).update(activation_expires_at=timezone.now() - timedelta(seconds=1))
    result = owner_client.post(f"{PLATFORM_PATH}{record_id}/issue-code/", {"rationale": "Renew expired original installation"}, format="json")
    assert result.status_code == 200
    validation = {"signed_token": issued["signedToken"], "device_id": issued["deviceId"], "device_fingerprint": issued["deviceFingerprint"]}
    assert client.post(TENANT_PATH + "validate/", validation, format="json").status_code == 403
    assert client.post(f"{TENANT_PATH}{record_id}/enrol/", {**validation, "challenge_code": result.data["challengeCode"]}, format="json").status_code == 200


def test_register_is_reserved_before_first_device_enrols(context):
    tenant, register, manager, owner, body = context
    client = authenticated(manager, tenant)
    assert client.post(TENANT_PATH, body, format="json").status_code == 201
    body["device_id"] = "SECOND-DEVICE"
    assert client.post(TENANT_PATH, body, format="json").status_code == 400
    assert PosActivationRequest.all_objects.count() == 1


def test_setup_options_are_scoped_and_reservations_are_visible(context):
    tenant, register, manager, owner, body = context
    client = authenticated(manager, tenant)
    result = client.get(TENANT_PATH + "options/")
    assert result.status_code == 200
    assert len(result.data["branches"]) == 1 and result.data["registers"][0]["available"]
    assert "device_id" not in result.data["registers"][0]
    assert client.post(TENANT_PATH, body, format="json").status_code == 201
    assert not client.get(TENANT_PATH + "options/").data["registers"][0]["available"]
    assert client.get(TENANT_PATH + "?device_id=other-device").data == []
    other = Tenant.objects.create(name="Other", slug="other-activation-options")
    assert authenticated(manager, other).get(TENANT_PATH + "options/").status_code == 403


def test_inactive_branches_and_open_registers_are_not_available_for_activation(context):
    tenant, register, manager, owner, body = context
    client = authenticated(manager, tenant)
    register.location.status = "INACTIVE"
    register.location.save(update_fields=["status", "updated_at"])
    result = client.get(TENANT_PATH + "options/")
    assert result.status_code == 200
    assert result.data["branches"] == []
    assert result.data["registers"][0]["available"] is False
    assert client.post(TENANT_PATH, body, format="json").status_code == 400
    register.location.status = "ACTIVE"
    register.location.save(update_fields=["status", "updated_at"])
    register.state = "OPEN"
    register.save(update_fields=["state", "updated_at"])
    assert client.get(TENANT_PATH + "options/").data["registers"][0]["available"] is False
    assert client.post(TENANT_PATH, body, format="json").status_code == 400


def test_approval_and_first_enrolment_recheck_register_readiness(context):
    from django.utils import timezone

    from apps.pos_shift.models import BusinessDay, RegisterSession

    tenant, register, manager, owner, body = context
    client, owner_client = authenticated(manager, tenant), authenticated(owner, tenant)
    record_id = client.post(TENANT_PATH, body, format="json").data["id"]
    register.state = "OPEN"
    register.save(update_fields=["state", "updated_at"])
    day = BusinessDay.all_objects.create(tenant=tenant, location=register.location, business_date=timezone.localdate())
    RegisterSession.all_objects.create(tenant=tenant, register=register, business_day=day, opened_by=manager, state="OPEN")
    refused = owner_client.post(f"{PLATFORM_PATH}{record_id}/approve/", {"rationale": "Independent device review"}, format="json")
    assert refused.status_code == 400 and "Close and reconcile" in str(refused.data)
    assert PosActivationRequest.all_objects.get(pk=record_id).state == "SUBMITTED"
    RegisterSession.all_objects.filter(register=register).update(state="CLOSED")
    register.state = "AVAILABLE"
    register.save(update_fields=["state", "updated_at"])
    # A closed session still needs its fiscal Z report before first enrolment.
    refused = owner_client.post(f"{PLATFORM_PATH}{record_id}/approve/", {"rationale": "Independent device review"}, format="json")
    assert refused.status_code == 400 and "final Z report" in str(refused.data)


def test_approved_installation_cannot_enrol_after_register_opens(context):
    from django.utils import timezone

    from apps.pos_shift.models import BusinessDay, RegisterSession

    tenant, register, manager, owner, body = context
    client, owner_client = authenticated(manager, tenant), authenticated(owner, tenant)
    record_id = client.post(TENANT_PATH, body, format="json").data["id"]
    code = owner_client.post(f"{PLATFORM_PATH}{record_id}/approve/", {"rationale": "Independent device review"}, format="json").data["challengeCode"]
    register.state = "OPEN"
    register.save(update_fields=["state", "updated_at"])
    day = BusinessDay.all_objects.create(tenant=tenant, location=register.location, business_date=timezone.localdate())
    RegisterSession.all_objects.create(tenant=tenant, register=register, business_day=day, opened_by=manager, state="OPEN")
    result = client.post(f"{TENANT_PATH}{record_id}/enrol/", {"challenge_code": code, "device_id": body["device_id"], "device_fingerprint": body["device_fingerprint"]}, format="json")
    assert result.status_code == 400 and "Close and reconcile" in str(result.data)
    assert PosActivationRequest.all_objects.get(pk=record_id).state == "APPROVED"


def test_replacement_requires_revocation_and_closed_register_then_new_review(context):
    tenant, register, manager, owner, body = context
    client, owner_client, record_id, issued = activate(context)
    endpoint = f"{PLATFORM_PATH}{record_id}/release-register/"
    assert owner_client.post(endpoint, {"rationale": "Replace retired installation"}, format="json").status_code == 400
    assert owner_client.post(f"{PLATFORM_PATH}{record_id}/revoke/", {"rationale": "Retire the original device"}, format="json").status_code == 200
    register.refresh_from_db()
    register.state = "OPEN"
    register.save()
    assert owner_client.post(endpoint, {"rationale": "Replace retired installation"}, format="json").status_code == 400
    register.state = "AVAILABLE"
    register.save()
    assert owner_client.post(endpoint, {"rationale": "Replace retired installation"}, format="json").status_code == 200
    register.refresh_from_db()
    assert register.device_id == ""
    body["device_id"] = "NEW-INSTALLATION"
    new = client.post(TENANT_PATH, body, format="json")
    assert new.status_code == 201 and new.data["state"] == "SUBMITTED"
    old = {"signed_token": issued["signedToken"], "device_id": issued["deviceId"], "device_fingerprint": issued["deviceFingerprint"]}
    assert client.post(TENANT_PATH + "validate/", old, format="json").status_code == 403


def test_governance_actions_require_reason_and_independent_positive_review(context):
    tenant, register, manager, owner, body = context
    client, owner_client, record_id, issued = activate(context)
    assert owner_client.post(f"{PLATFORM_PATH}{record_id}/issue-code/", {"rationale": "short"}, format="json").status_code == 400
    assert client.post(f"{PLATFORM_PATH}{record_id}/resume/", {"rationale": "Tenant cannot resume devices"}, format="json").status_code == 403
    manager.is_platform_admin = True
    manager.save()
    assert client.post(f"{PLATFORM_PATH}{record_id}/issue-code/", {"rationale": "Requester cannot review own device"}, format="json").status_code == 403
    assert "challengeCode" not in owner_client.get(PLATFORM_PATH).data[0]


def test_request_only_manager_can_track_and_enrol_but_view_only_cannot(context):
    tenant, register, manager, owner, body = context
    role = Role.all_objects.get(tenant=tenant, code="MANAGER")
    role.capabilities = ["tenant.pos_activation.request"]
    role.save()
    client, owner_client, record_id, issued = activate(context)
    assert client.get(TENANT_PATH).status_code == 200
    role.capabilities = ["tenant.pos_activation.view"]
    role.save()
    result = owner_client.post(f"{PLATFORM_PATH}{record_id}/issue-code/", {"rationale": "Recover original installation credential"}, format="json")
    assert client.post(f"{TENANT_PATH}{record_id}/enrol/", {"challenge_code": result.data["challengeCode"], "device_id": body["device_id"], "device_fingerprint": body["device_fingerprint"]}, format="json").status_code == 403


def test_changed_register_branch_refuses_validation_and_enrolment(context):
    from apps.organizations.models import Location

    tenant, register, manager, owner, body = context
    client, owner_client, record_id, issued = activate(context)
    branch = Location.all_objects.create(tenant=tenant, organization=register.location.organization, code="BR2", name="Second branch")
    register.location = branch
    register.save()
    validation = {"signed_token": issued["signedToken"], "device_id": body["device_id"], "device_fingerprint": body["device_fingerprint"]}
    assert client.post(TENANT_PATH + "validate/", validation, format="json").status_code == 403
    assert owner_client.post(f"{PLATFORM_PATH}{record_id}/issue-code/", {"rationale": "Do not allow a changed branch"}, format="json").status_code == 400


def test_register_with_unreconciled_closed_session_cannot_be_released(context):
    from django.utils import timezone

    from apps.pos_shift.models import BusinessDay, RegisterSession

    tenant, register, manager, owner, body = context
    client, owner_client, record_id, issued = activate(context)
    owner_client.post(f"{PLATFORM_PATH}{record_id}/revoke/", {"rationale": "Replace original installation"}, format="json")
    day = BusinessDay.all_objects.create(tenant=tenant, location=register.location, business_date=timezone.localdate())
    RegisterSession.all_objects.create(tenant=tenant, register=register, business_day=day, opened_by=manager, state="CLOSED")
    result = owner_client.post(f"{PLATFORM_PATH}{record_id}/release-register/", {"rationale": "Missing Z must block replacement"}, format="json")
    assert result.status_code == 400 and "Z report" in str(result.data)
    register.refresh_from_db()
    assert register.device_id == body["device_id"]
