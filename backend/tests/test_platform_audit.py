import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent, PlatformAuditEvent
from apps.audit.service import log_audit, log_platform_audit
from apps.integrations.models import ProviderConfiguration

pytestmark = pytest.mark.django_db


def test_platform_audit_is_separate_and_model_immutable(admin_user, cashier_user):
    event = log_platform_audit(
        actor_id=admin_user.pk, action="TEST_PLATFORM_DECISION", model_name="ProviderConfiguration", object_id="test",
    )
    assert event.actor_id == admin_user.pk
    assert not AuditEvent.all_objects.exists()
    event.action = "ALTERED"
    with pytest.raises(ValidationError, match="immutable"):
        event.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        event.delete()
    with pytest.raises(PermissionDenied):
        log_platform_audit(
            actor_id=cashier_user.pk, action="UNAUTHORISED", model_name="ProviderConfiguration", object_id="test",
        )
    with pytest.raises(ValidationError, match="tenant"):
        log_audit(tenant_id=None, action="NO_TENANT", model_name="Patient", object_id="test")
    assert PlatformAuditEvent.objects.count() == 1


def test_platform_audit_refuses_inactive_authority(admin_user):
    admin_user.is_active = False
    admin_user.save(update_fields=["is_active"])
    with pytest.raises(PermissionDenied):
        log_platform_audit(
            actor_id=admin_user.pk, action="INACTIVE_AUTHORITY", model_name="ProviderConfiguration", object_id="test",
        )
    assert not PlatformAuditEvent.objects.exists()


def test_platform_audit_lookup_exception_is_confined_to_writer(tmp_path):
    from apps.prescription.management.lookup_safety import find_unscoped_uuid_lookups

    source = "# tenant-safety: platform-audit-authority-check\nUser.objects.filter(pk=actor_id, is_active=True)\n"
    approved = tmp_path / "audit" / "service.py"
    approved.parent.mkdir()
    approved.write_text(source)
    assert find_unscoped_uuid_lookups(tmp_path) == []
    unrelated = tmp_path / "unrelated.py"
    unrelated.write_text(source)
    findings = find_unscoped_uuid_lookups(tmp_path)
    assert len(findings) == 1
    assert findings[0].path == "unrelated.py"


def test_platform_provider_forms_write_audit_without_tenant(admin_user):
    client = APIClient()
    client.force_login(admin_user)
    provider = ProviderConfiguration.objects.create(
        provider_type="DHA_HWR", environment="SANDBOX", display_name="Test registry template",
    )
    base = f"/api/nif/platform/providers/{provider.pk}"
    response = client.post(base + "/endpoints/", {
        "name": "Registry", "base_url": "https://registry.example.test/api/",
        "allowed_hosts": ["registry.example.test"], "is_active": True,
    }, format="json")
    assert response.status_code == 201, response.content
    response = client.patch(base + "/", {"display_name": "Reviewed registry template"}, format="json")
    assert response.status_code == 200, response.content
    assert set(PlatformAuditEvent.objects.values_list("action", flat=True)) == {
        "PROVIDER_ENDPOINT_CONFIGURED", "PROVIDER_CONFIGURATION_UPDATED",
    }
    assert not AuditEvent.all_objects.exists()
