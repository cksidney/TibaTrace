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


def test_report_download_validates_and_audits_the_reporting_window():
    tenant = Tenant.objects.create(name="Window Report Tenant", slug="window-report-tenant")
    user = _manager(tenant)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/hq/reports/sales-period/download/?from_iso=2026-07-01T00%3A00%3A00%2B03%3A00&to_iso=2026-07-31T23%3A59%3A00%2B03%3A00&granularity=DAILY",
        {"format": "json", "terminal_id": "HQ-WINDOW-1"},
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["receipt"]["period_start"] == "2026-06-30T21:00:00Z"
    assert payload["receipt"]["period_end"] == "2026-07-31T20:59:00Z"
    assert payload["receipt"]["granularity"] == "DAILY"
    assert any(
        row == {"field": "Reporting window start (UTC)", "value": "2026-06-30T21:00:00Z"} for row in payload["rows"]
    )

    receipt_id = response["X-Report-Receipt-Id"]
    event = AuditEvent.all_objects.get(object_id=receipt_id, action="REPORT_DOWNLOAD")
    assert event.metadata["period_start"] == "2026-06-30T21:00:00Z"
    assert event.metadata["period_end"] == "2026-07-31T20:59:00Z"
    assert event.metadata["granularity"] == "DAILY"

    validation = client.get(
        f"/api/hq/reports/validate/{receipt_id}/",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )
    assert validation.status_code == 200
    assert validation.json()["period_start"] == "2026-06-30T21:00:00Z"
    assert validation.json()["granularity"] == "DAILY"


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        (
            {
                "format": "json",
                "start_date_time": "2026-08-02T00:00:00+03:00",
                "end_date_time": "2026-08-01T00:00:00+03:00",
                "granularity": "DAILY",
            },
            "Reporting-window start must be before or equal to the end.",
        ),
        (
            {
                "format": "json",
                "start_date_time": "2026-08-01T00:00:00+03:00",
                "end_date_time": "2026-08-02T00:00:00+03:00",
                "granularity": "SECONDLY",
            },
            "Granularity must be one of: HOURLY, DAILY, WEEKLY, MONTHLY, YEARLY.",
        ),
        (
            {
                "format": "json",
                "start_date_time": "2026-08-01T00:00:00+03:00",
                "granularity": "DAILY",
            },
            "Both reporting-window start and end are required.",
        ),
    ],
)
def test_report_download_rejects_invalid_reporting_windows(payload, detail):
    tenant = Tenant.objects.create(name="Invalid Window Tenant", slug=f"invalid-{payload['granularity'].lower()}")
    user = _manager(tenant)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/hq/reports/sales-period/download/",
        payload,
        format="json",
        HTTP_X_TENANT_ID=str(tenant.pk),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == detail
    assert not AuditEvent.all_objects.filter(tenant=tenant, action="REPORT_DOWNLOAD").exists()
