"""Operator report routes expose scoped facts, not clinical narratives or secrets."""
from datetime import timedelta

import pytest
from django.utils import timezone
from tests.test_pos_retail_transactions import world  # noqa: F401
from tests.test_retail_refunds import user

from apps.audit.models import AuditEvent
from apps.cds.pos_screening_models import PosClinicalFinding, PosClinicalScreening
from apps.identity.models import ServiceAccount
from apps.platform.reporting.operator_source_queries import OPERATOR_REPORTS, OPERATOR_SNAPSHOTS
from apps.platform.reporting.queries import availability, query_report
from apps.platform.reporting.services import ReportWindow
from apps.pos_shift.reporting import ShiftReportService

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("report_id", sorted(OPERATOR_REPORTS))
def test_operator_report_has_valid_scoped_source_contract(world, report_id):  # noqa: F811
    result = query_report(report_id, world["tenant"].pk, world["operator"], None)
    assert result.columns and result.basis
    assert availability(report_id)["available"]


def test_clinical_reports_refuse_cashier_and_keep_identity_and_narratives_out(world):  # noqa: F811
    cashier = user(world["tenant"], "cash-report-reader", ["reports.view", "pos.transaction.create"])
    with pytest.raises(PermissionError):
        query_report("clin-screening", world["tenant"].pk, cashier, None)
    screening = PosClinicalScreening.all_objects.create(tenant=world["tenant"], transaction_id="operator-report-tx",
        device_id="POS-RETAIL-01", context_hash="context", status="COMPLETE", highest_severity="HIGH", blocking_count=1,
        safe_to_proceed=False, evaluated_at=timezone.now(), branch_id=world["branch"].pk)
    PosClinicalFinding.all_objects.create(tenant=world["tenant"], screening=screening, category="DRUG_ALLERGY",
        severity="HIGH", title="Private patient reaction", summary="Private clinical narrative", blocking=True)
    result = query_report("clin-allergy", world["tenant"].pk, world["operator"], None)
    assert len(result.rows) == 1
    assert "Private" not in str(result.rows)
    holds = query_report("sales-clinical-holds", world["tenant"].pk, world["operator"], None)
    assert len(holds.rows) == 1 and str(screening.screening_id) in str(holds.rows)


def test_x_report_exports_frozen_snapshot_without_recalculation(world):  # noqa: F811
    report = ShiftReportService.generate_x(session=world["session"], actor=world["operator"])
    report.snapshot["cash"]["cash_sales"] = "123.45"
    report.save(update_fields=["snapshot", "updated_at"])
    result = query_report("hr-x-reports", world["tenant"].pk, world["operator"], None)
    assert "123.45" in result.rows[0]
    assert "never recomputed" in result.basis


def test_service_account_export_does_not_expose_credential_fingerprint(world):  # noqa: F811
    ServiceAccount.all_objects.create(tenant=world["tenant"], code="safe-source", display_name="Safe source", credential_fingerprint="secret-fingerprint")
    result = query_report("sec-service-accounts", world["tenant"].pk, world["operator"], None)
    assert result.rows and "secret-fingerprint" not in str(result.rows)


@pytest.mark.parametrize("report_id", sorted(OPERATOR_SNAPSHOTS))
def test_access_snapshot_refuses_historical_window(world, report_id):  # noqa: F811
    now = timezone.now()
    window = ReportWindow((now - timedelta(days=1)).isoformat(), now.isoformat(), "DAILY")
    with pytest.raises(ValueError, match="current-state"):
        query_report(report_id, world["tenant"].pk, world["operator"], window)


def test_unsupported_accounting_forecasts_and_certification_remain_honest():
    for report_id in ["fin-gl", "fin-vat", "an-demand-forecast", "reg-ppb", "cd-register", "sec-secret-scan"]:
        result = availability(report_id)
        assert result["available"] is False
        assert "required" in result["availability_note"]


@pytest.mark.parametrize("report_id", ["inv-valuation", "exec-inventory-value"])
def test_inventory_valuation_reports_disclose_missing_acquisition_costs(world, report_id):  # noqa: F811
    assert availability(report_id)["available"]
    result = query_report(report_id, world["tenant"].pk, world["operator"], None)
    assert result.rows
    assert all(row[-2:] == ["UNVALUED", "UNVALUED"] for row in result.rows)
    assert "unvalued lines" in result.basis
    reader = user(world["tenant"], "valuation-report-reader", ["reports.view"])
    with pytest.raises(PermissionError):
        query_report(report_id, world["tenant"].pk, reader, None)


def test_role_capability_mutations_are_audited_by_real_identity_api(world):  # noqa: F811
    tenant = world["tenant"]
    response = world["client"].post("/api/identity/roles-detail/", {"code": "REPORT-WRITER", "name": "Reporter",
        "capabilities": ["reports.view"]}, format="json", HTTP_X_TENANT_ID=str(tenant.pk))
    assert response.status_code == 201, response.data
    role_id = response.json()["id"]
    changed = world["client"].patch(f"/api/identity/roles-detail/{role_id}/", {"capabilities": ["reports.view", "audit.read"]},
        format="json", HTTP_X_TENANT_ID=str(tenant.pk))
    assert changed.status_code == 200, changed.data
    audit = AuditEvent.all_objects.get(tenant=tenant, action="IDENTITY_ROLE_UPDATED", object_id=str(role_id))
    assert audit.metadata["previous"]["capabilities"] == ["reports.view"]
    assert audit.metadata["current"]["capabilities"] == ["audit.read", "reports.view"]
    result = query_report("sec-permission-changes", tenant.pk, world["operator"], None)
    assert {row[2] for row in result.rows} >= {"IDENTITY_ROLE_CREATED", "IDENTITY_ROLE_UPDATED"}
