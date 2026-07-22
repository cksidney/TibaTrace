from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id
from apps.identity.authentication import DawaTraceTokenSerializer
from apps.identity.models import AttributePolicy, User, UserRole
from apps.patients.models import Patient

pytestmark = [pytest.mark.django_db, pytest.mark.security]


def test_tenantless_local_user_is_rejected():
    with pytest.raises(ValidationError):
        User.objects.create_user(username="unsafe", password="strong-test-password")


def test_platform_admin_may_be_tenantless():
    user = User.objects.create_user(
        username="platform", password="strong-test-password", is_platform_admin=True
    )
    assert user.tenant_id is None


def test_strict_manager_fails_closed_without_context(clinical_setup):
    assert Patient.objects.count() == 0
    assert Patient.all_objects.count() == 1


def test_strict_manager_scopes_to_context(clinical_setup):
    token = set_current_tenant_id(clinical_setup["tenant"].id)
    try:
        assert list(Patient.objects.values_list("id", flat=True)) == [clinical_setup["patient"].id]
    finally:
        reset_current_tenant_id(token)


def test_role_capability_is_tenant_qualified(clinical_user, tenant_b):
    assert clinical_user.has_capability("patients.read", tenant_id=clinical_user.tenant_id)
    assert not clinical_user.has_capability("patients.read", tenant_id=tenant_b.id)


def test_abac_deny_overrides_role_grant(clinical_user):
    AttributePolicy.all_objects.create(
        tenant_id=clinical_user.tenant_id,
        code="DENY_UNTRAINED",
        capability="cds.override",
        effect="DENY",
        conditions={"user_metadata": {"cds_training": False}},
    )
    clinical_user.metadata = {"cds_training": False}
    clinical_user.save()
    assert not clinical_user.has_capability("cds.override", tenant_id=clinical_user.tenant_id)


def test_non_matching_abac_deny_does_not_remove_grant(clinical_user):
    AttributePolicy.all_objects.create(
        tenant_id=clinical_user.tenant_id,
        code="DENY_UNTRAINED",
        capability="cds.override",
        effect="DENY",
        conditions={"user_metadata": {"cds_training": False}},
    )
    clinical_user.metadata = {"cds_training": True}
    clinical_user.save()
    assert clinical_user.has_capability("cds.override", tenant_id=clinical_user.tenant_id)


def test_duplicate_role_assignment_is_prevented(clinical_user):
    assignment = UserRole.all_objects.get(user=clinical_user)
    with pytest.raises(IntegrityError):
        UserRole.all_objects.create(
            tenant_id=clinical_user.tenant_id, user=clinical_user, role=assignment.role
        )


def test_jwt_contains_dawatrace_tenant_claim(clinical_user):
    refresh = DawaTraceTokenSerializer.get_token(clinical_user)
    assert refresh["tenant_id"] == str(clinical_user.tenant_id)
    assert refresh["product"] == "DawaTrace"


def test_patient_api_requires_authentication(clinical_setup):
    response = APIClient().get(
        "/api/patients/", HTTP_X_TENANT_ID=str(clinical_setup["tenant"].id)
    )
    assert response.status_code == 401


def test_patient_api_is_tenant_scoped(clinical_setup, clinical_user):
    client = APIClient()
    client.force_authenticate(clinical_user)
    response = client.get(
        "/api/patients/", HTTP_X_TENANT_ID=str(clinical_setup["tenant"].id)
    )
    assert response.status_code == 200
    assert response.data[0]["id"] == str(clinical_setup["patient"].id)


def test_cross_tenant_api_scope_is_forbidden(clinical_setup, clinical_user, tenant_b):
    client = APIClient()
    client.force_authenticate(clinical_user)
    response = client.get("/api/patients/", HTTP_X_TENANT_ID=str(tenant_b.id))
    assert response.status_code == 403


def test_audit_event_is_immutable(clinical_setup, clinical_user):
    event = AuditEvent.all_objects.create(
        tenant=clinical_setup["tenant"],
        actor=clinical_user,
        action="READ",
        model_name="Patient",
        object_id=str(clinical_setup["patient"].id),
    )
    event.outcome = "FAILED"
    with pytest.raises(ValidationError):
        event.save()
    with pytest.raises(ValidationError):
        event.delete()
