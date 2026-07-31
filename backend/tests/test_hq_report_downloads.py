import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity.models import Role, User, UserRole
from apps.platform.reporting.catalogue import list_reports
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


def _manager(tenant):
    user = User.objects.create_user(
        username="report-manager",
        password="report-test-password",
        tenant=tenant,
    )
    role = Role.all_objects.create(
        tenant=tenant,
        code="REPORT_MANAGER",
        name="Report manager",
        capabilities=["identity.manage", "inventory.read"],
    )
    UserRole.all_objects.create(tenant=tenant, user=user, role=role)
    return user


def test_report_catalogue_lists_enterprise_packs():
    assert len(list_reports()) >= 80
    assert any(spec.id == "exec-dashboard" for spec in list_reports())
    assert any(spec.category == "security" for spec in list_reports())


def test_report_pdf_download_issues_unique_validation_receipt():
    tenant = Tenant.objects.create(name="Report Tenant", slug="report-tenant")
    user = _manager(tenant)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/hq/reports/exec-dashboard/download/",
        {"format": "pdf", "terminal_id": "HQ-TERM-1", "terminal_label": "HQ Web · test"},
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"
    receipt_id = response["X-Report-Receipt-Id"]
    assert receipt_id
    assert response["X-Report-Validation-Code"]
    assert response["X-Report-Checksum-SHA256"]

    event = AuditEvent.all_objects.get(object_id=receipt_id, action="REPORT_DOWNLOAD")
    assert event.metadata["terminal_id"] == "HQ-TERM-1"
    assert event.metadata["downloaded_by"] == user.username

    validation = client.get(
        f"/api/hq/reports/validate/{receipt_id}/",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert validation.status_code == 200
    body = validation.json()
    assert body["valid"] is True
    assert body["report_id"] == "exec-dashboard"
    assert body["terminal_label"] == "HQ Web · test"
