"""Exports must be real formats, scoped facts and honest about missing evidence."""
import io
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from xml.etree import ElementTree

import pytest
from rest_framework.test import APIClient
from tests.test_pos_enterprise_dispensing import domain, grant, setup_domain  # noqa: F401
from tests.test_pos_payment_ledger import cash_tender, intent  # noqa: F401

from apps.audit.models import AuditEvent
from apps.identity.models import Role, User, UserRole
from apps.platform.reporting.certification_engine import CertificationEvidenceGenerator
from apps.platform.reporting.compliance_engine import ComplianceReportEngine
from apps.platform.reporting.queries import query_report
from apps.platform.reporting.services import ReportWindow, catalogue_payload
from apps.platform.reporting.tabular import csv_bytes, xlsx_bytes
from apps.prescription.payment_services import PaymentSettlementService
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


def manager(tenant, capabilities):
    user = User.objects.create_user(username="source-report-manager", tenant=tenant)
    role = Role.all_objects.create(tenant=tenant, code="REPORTER", name="Reporter", capabilities=capabilities)
    UserRole.all_objects.create(tenant=tenant, user=user, role=role)
    return user


def test_xlsx_is_ooxml_with_literal_cells_and_csv_neutralises_formulas():
    content = xlsx_bytes([["Product", "Value"], ["A&B<\x00", "=1+1"]])
    assert content.startswith(b"PK")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            ElementTree.fromstring(archive.read(name))
        sheet = archive.read("xl/worksheets/sheet1.xml")
        assert b"<f>" not in sheet and b"=1+1" in sheet and b"A&amp;B&lt;" in sheet
    assert b"'=1+1" in csv_bytes([["=1+1"]])


def test_planned_pack_returns_501_without_fake_download_or_audit():
    tenant = Tenant.objects.create(name="Reporting scope", slug="reporting-scope")
    user = manager(tenant, ["reports.view"])
    client = APIClient()
    client.force_authenticate(user)
    response = client.post("/api/hq/reports/fin-gl/download/", {"format": "json"}, format="json", HTTP_X_TENANT_ID=str(tenant.pk))
    assert response.status_code == 501
    assert response.json()["code"] == "report_not_implemented"
    assert not AuditEvent.all_objects.filter(action="REPORT_DOWNLOAD").exists()
    packs = {pack["id"]: pack for category in catalogue_payload()["categories"] for pack in category["reports"]}
    assert packs["fin-gl"]["available"] is False
    assert packs["inv-balance"]["period_filter"] is False


def test_audit_query_applies_window_and_tenant_boundaries():
    tenant = Tenant.objects.create(name="Reporting scope", slug="reporting-scope")
    other = Tenant.objects.create(name="Other", slug="reporting-other")
    user = manager(tenant, ["reports.view", "audit.read"])
    inside = AuditEvent.all_objects.create(tenant=tenant, actor=user, action="INSIDE", model_name="identity.User", object_id="1", metadata={"private": "not exported"})
    outside = AuditEvent.all_objects.create(tenant=tenant, actor=user, action="OUTSIDE", model_name="identity.User", object_id="2")
    cross_tenant = AuditEvent.all_objects.create(tenant=other, action="CROSS_TENANT", model_name="identity.User", object_id="3")
    AuditEvent.all_objects.filter(pk__in=[inside.pk, cross_tenant.pk]).update(created_at=datetime(2026, 10, 10, tzinfo=timezone.utc))
    AuditEvent.all_objects.filter(pk=outside.pk).update(created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    window = ReportWindow("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z", "DAILY")
    report = query_report("audit-user", tenant.pk, user, window)
    assert len(report.rows) == 1 and report.rows[0][2] == "INSIDE"
    assert "private" not in str(report.rows)
    with pytest.raises(PermissionError):
        query_report("audit-user", other.pk, user, window)


def test_current_balance_rejects_historical_window():
    tenant = Tenant.objects.create(name="Reporting scope", slug="reporting-scope")
    user = manager(tenant, ["reports.view", "inventory.read"])
    with pytest.raises(ValueError, match="current-state snapshot"):
        query_report("inv-balance", tenant.pk, user, ReportWindow("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z", "DAILY"))
    assert query_report("inv-balance", tenant.pk, user, None).rows == []


def test_inventory_reports_export_actual_stock_and_item_details(domain):  # noqa: F811
    grant(domain["cashier"], domain["tenant"], ["reports.view", "inventory.read"], code="REPORTS")
    for report_id in ["inv-balance", "inv-batch", "inv-expiry", "qa-released", "inv-movements"]:
        result = query_report(report_id, domain["tenant"].pk, domain["cashier"], None)
        assert result.rows, report_id
        assert domain["sku"].sku_code in str(result.rows)
        assert domain["sku"].display_name in str(result.rows)
    assert query_report("qa-quarantine", domain["tenant"].pk, domain["cashier"], None).rows == []


def test_dispensing_collections_use_settlement_timestamp_and_exact_amounts(domain, intent):  # noqa: F811
    tender = cash_tender(domain, intent, Decimal("1000.00"))
    PaymentSettlementService.record(tender=tender, amount=Decimal("125.50"), source="CASH", idempotency_key="source-report-inside",
                                    settled_at=datetime(2026, 10, 10, tzinfo=timezone.utc))
    PaymentSettlementService.record(tender=tender, amount=Decimal("200.00"), source="CASH", idempotency_key="source-report-outside",
                                    settled_at=datetime(2026, 9, 10, tzinfo=timezone.utc))
    grant(domain["cashier"], domain["tenant"], ["reports.view", "payment.read"], code="REPORTS")
    report = query_report("sales-period", domain["tenant"].pk, domain["cashier"],
                          ReportWindow("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z", "DAILY"))
    assert len(report.rows) == 1
    assert Decimal(report.rows[0][4]) == Decimal("125.50")
    assert report.rows[0][2] == "KES"
    assert "not accrual revenue" in report.basis


@pytest.mark.parametrize("export_format, magic", [("pdf", b"%PDF"), ("xlsx", b"PK"), ("csv", b"\xef\xbb\xbf")])
def test_compliance_exports_are_real_formats(export_format, magic):
    tenant = Tenant.objects.create(name="Reporting scope", slug="reporting-scope")
    user = manager(tenant, ["reports.view"])
    result = ComplianceReportEngine.generate_report(report_type="PREMISES", format_type=export_format, tenant_id=tenant.pk, actor=user)
    assert result["content"].startswith(magic)
    assert result["filename"].endswith("." + export_format)


def test_certification_bundle_never_fabricates_passes_scores_or_provenance():
    result = CertificationEvidenceGenerator.generate_evidence_package()
    assert result["readiness_matrix"]["overall_readiness"] is None
    assert result["sbom_provenance"]["slsa_level"] == "NOT_VERIFIED"
    assert result["quality_evidence"]["backend_pytest"]["status"] == "NOT_VERIFIED"
