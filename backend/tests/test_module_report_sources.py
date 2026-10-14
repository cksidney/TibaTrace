"""Source-specific authority, row facts, time windows and sensitive-field limits."""
# ruff: noqa: F811
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from tests.test_pos_enterprise_dispensing import (  # noqa: F401
    advance_to_ready_for_supply,
    grant,
    make_clinically_ready,
    setup_domain,
)
from tests.test_pos_enterprise_dispensing import domain as clinical_domain  # noqa: F401
from tests.test_pos_retail_transactions import world  # noqa: F401
from tests.test_retail_refunds import user

from apps.audit.models import AuditEvent
from apps.customers.models import Customer
from apps.fhir.models import FHIRIdempotencyRecord
from apps.platform.reporting.module_source_queries import MODULE_REPORTS
from apps.platform.reporting.queries import availability, query_report
from apps.platform.reporting.services import ReportWindow
from apps.prescription.pos_dispensing_services import PosPartialRepeatService
from apps.sales.models import SalesOrder
from apps.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("report_id", sorted(MODULE_REPORTS))
def test_module_reports_have_source_contract_and_available_route(world, report_id):
    result = query_report(report_id, world["tenant"].pk, world["operator"], None)
    assert result.basis and result.columns
    assert all(len(row) == len(result.columns) for row in result.rows)
    assert availability(report_id)["available"]


def test_cash_position_is_expected_drawer_snapshot_with_branch_scope(world):
    result = query_report("exec-cash-position", world["tenant"].pk, world["operator"], None)
    assert len(result.rows) == 1 and result.rows[0][0] == str(world["session"].pk)
    assert "not a physical count" in result.basis
    now = timezone.now()
    with pytest.raises(ValueError, match="current-state"):
        query_report("exec-cash-position", world["tenant"].pk, world["operator"], ReportWindow((now - timedelta(days=1)).isoformat(), now.isoformat(), "DAILY"))
    world["operator"].metadata = {"branch_ids": []}
    assert query_report("exec-cash-position", world["tenant"].pk, world["operator"], None).rows == []
    world["operator"].metadata = {"branch_ids": ["not-a-branch"]}
    with pytest.raises(PermissionError, match="Invalid branch scope"):
        query_report("exec-cash-position", world["tenant"].pk, world["operator"], None)


def test_customer_cohorts_and_orders_preserve_totals_without_contact_details(world):
    tenant = world["tenant"]
    customer = Customer.all_objects.create(tenant=tenant, customer_number="REPORT-CUSTOMER", legal_name="Private Legal Name", contact_email="private@example.test", customer_type="WHOLESALE")
    SalesOrder.all_objects.create(tenant=tenant, branch=world["branch"], customer=customer, order_number="OBSERVED-ORDER", currency="USD", subtotal=100, tax_total=10, total=110)
    customer_report = query_report("crm-growth", tenant.pk, world["operator"], None)
    orders = query_report("sales-by-customer", tenant.pk, world["operator"], None)
    assert "REPORT-CUSTOMER" in str(customer_report.rows)
    assert orders.rows[0][6:] == ["USD", "100.00", "10.00", "110.00"]
    assert "Private" not in str(customer_report.rows + orders.rows) and "private@example" not in str(customer_report.rows + orders.rows)
    world["operator"].metadata = {"branch_ids": [str(uuid.uuid4())]}
    assert query_report("sales-by-customer", tenant.pk, world["operator"], None).rows == []


def test_fhir_observations_exclude_keys_hashes_and_other_tenant_records(world):
    tenant = world["tenant"]
    other = Tenant.objects.create(name="Other FHIR", slug="other-fhir-report")
    FHIRIdempotencyRecord.all_objects.create(tenant=tenant, key="private-retry-key", request_hash="a" * 64, resource_type="Patient", operation="CREATE", actor=world["operator"])
    FHIRIdempotencyRecord.all_objects.create(tenant=other, key="cross-tenant", request_hash="b" * 64, resource_type="PrivateOtherResource", operation="CREATE")
    result = query_report("sec-fhir-idempotency", tenant.pk, world["operator"], None)
    assert len(result.rows) == 1 and result.rows[0][3] == "Patient"
    assert "private-retry-key" not in str(result.rows) and "a" * 64 not in str(result.rows) and "PrivateOther" not in str(result.rows)
    window = ReportWindow((timezone.now() + timedelta(days=1)).isoformat(), (timezone.now() + timedelta(days=2)).isoformat(), "DAILY")
    assert query_report("sec-fhir-idempotency", tenant.pk, world["operator"], window).rows == []


def test_sensitive_sources_require_both_clinical_and_patient_authority(world):
    viewer = user(world["tenant"], "report-only", ["reports.view"])
    for report in MODULE_REPORTS:
        with pytest.raises(PermissionError):
            query_report(report, world["tenant"].pk, viewer, None)
    clinical_only = user(world["tenant"], "clinical-only-report", ["reports.view", "clinical.read"])
    with pytest.raises(PermissionError):
        query_report("crm-patient-history", world["tenant"].pk, clinical_only, None)
    with pytest.raises(PermissionError):
        query_report("crm-growth", Tenant.objects.create(name="Other", slug="other-source-report").pk, viewer, None)


def test_patient_history_and_activity_are_real_supply_facts_not_patient_narratives(clinical_domain):
    data = clinical_domain
    grant(data["pharmacist"], data["tenant"], ["reports.view", "patients.read", "pos.shift.manage", "clinical.read"], code="MODULE-REPORTS")
    make_clinically_ready(data)
    episode = advance_to_ready_for_supply(data)
    PosPartialRepeatService.dispense_partial(episode=episode, dispensing_line_id=data["line"].pk, quantity_supplied=10,
        reason="Patient requested actual partial supply", actor=data["pharmacist"], idempotency_key="observed-module-supply")
    history = query_report("crm-patient-history", data["tenant"].pk, data["pharmacist"], None)
    assert len(history.rows) == 1 and "PAT-001" in str(history.rows)
    assert "John" not in str(history.rows) and "Doe" not in str(history.rows)
    assert history.rows[0][6] == "10.0000" and history.rows[0][8] == "B12345"
    activity = query_report("hr-productivity", data["tenant"].pk, data["pharmacist"], None)
    assert len(activity.rows) == 1 and activity.rows[0][0] == "CLINICAL_SUPPLY" and activity.rows[0][-1] == "1"
    data["pharmacist"].metadata = {"branch_ids": []}
    assert query_report("crm-patient-history", data["tenant"].pk, data["pharmacist"], None).rows == []
    assert query_report("hr-productivity", data["tenant"].pk, data["pharmacist"], None).rows == []


def test_module_download_records_access_and_never_silently_truncates(world, monkeypatch):
    tenant = world["tenant"]
    response = world["client"].post("/api/hq/reports/exec-cash-position/download/", {"format": "json"}, format="json", HTTP_X_TENANT_ID=str(tenant.pk))
    assert response.status_code == 200
    assert len(response.json()["data"]["rows"]) == 1
    assert AuditEvent.all_objects.filter(tenant=tenant, action="REPORT_DOWNLOAD").exists()
    for number in range(2):
        Customer.all_objects.create(tenant=tenant, customer_number=f"BOUNDED-{number}", legal_name="Not exported", customer_type="WHOLESALE")
    monkeypatch.setattr("apps.platform.reporting.queries.MAX_ROWS", 1)
    with pytest.raises(ValueError, match="nothing was truncated"):
        query_report("crm-growth", tenant.pk, world["operator"], None)
