from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.inventory.models import InventoryBalance, InventoryBatch, InventoryLedgerEntry
from apps.inventory.recalls.models import RegulatoryTenantImpact
from apps.inventory.recalls.services import (
    activate_alert,
    close_alert_for_tenant,
    ingest_alert,
    quarantine_tenant_stock,
    record_regulatory_action,
)
from apps.inventory.services import InventoryLedgerService

pytestmark = pytest.mark.django_db


def test_recall_hold_release_preserves_physical_stock_and_audits_zero_delta(
    tenant_a, tenant_b, branch, inventory_location, sku, inventory_batch, admin_user
):
    InventoryLedgerService.post_entry(
        tenant=tenant_a, branch=branch, location=inventory_location, sku=sku,
        inventory_batch=inventory_batch, entry_type="RECEIPT", quantity_delta=Decimal("100"),
        unit="tablet", base_quantity_delta=Decimal("100"), effective_timestamp=timezone.now(),
        source_document_type="TEST", source_document_id="RECALL-TEST", idempotency_key="recall-test-receipt",
    )
    alert = ingest_alert(
        alert_reference="PPB-TEST-RECALL", title="Synthetic recall", severity="HIGH", actor=admin_user,
    )
    alert = activate_alert(alert=alert, actor=admin_user)
    assert RegulatoryTenantImpact.all_objects.filter(alert=alert).count() == 2
    impact = quarantine_tenant_stock(
        alert=alert, tenant_id=tenant_a.pk, actor=admin_user,
        affected_batches=[inventory_batch.manufacturer_batch_number], prior_dispense_trace_required=True,
    )
    # Repeating the hold must not consume stock or append duplicate ledger entries.
    quarantine_tenant_stock(
        alert=alert, tenant_id=tenant_a.pk, actor=admin_user,
        affected_batches=[inventory_batch.manufacturer_batch_number], prior_dispense_trace_required=True,
    )
    balance = InventoryBalance.all_objects.get(tenant=tenant_a, sku=sku)
    assert balance.on_hand == Decimal("100")
    assert balance.available == 0
    assert balance.recalled == Decimal("100")
    hold = InventoryLedgerEntry.all_objects.get(tenant=tenant_a, entry_type="RECALL_HOLD")
    assert hold.quantity_delta == hold.base_quantity_delta == 0
    with pytest.raises(ValidationError, match="prior dispensing trace"):
        close_alert_for_tenant(
            impact=impact, actor=admin_user, regulator_withdrawal_reference="PPB-WITHDRAW-TEST",
            compliance_review_notes="Synthetic withdrawal reviewed.",
        )
    record_regulatory_action(
        impact=impact, actor=admin_user, action_type="PATIENT_CONTACT", notes="No prior test dispenses.",
        evidence_payload={"patient_count": 0, "reference": "TEST-TRACE-REPORT"},
    )
    close_alert_for_tenant(
        impact=impact, actor=admin_user, regulator_withdrawal_reference="PPB-WITHDRAW-TEST",
        compliance_review_notes="Synthetic withdrawal reviewed.",
    )
    balance.refresh_from_db()
    assert balance.available == 0  # Closure alone must not release stock.
    record_regulatory_action(
        impact=impact, actor=admin_user, action_type="STOCK_RELEASE", notes="Release after test clearance.",
    )
    balance.refresh_from_db()
    inventory_batch.refresh_from_db()
    assert balance.on_hand == balance.available == Decimal("100")
    assert balance.recalled == 0
    assert inventory_batch.recall_status == InventoryBatch.RecallStatus.NONE
    assert InventoryLedgerEntry.all_objects.filter(tenant=tenant_a, entry_type="RECALL_RELEASE").count() == 1
    assert not InventoryLedgerEntry.all_objects.filter(tenant=tenant_b).exists()


def test_recall_of_unknown_batch_rolls_back_without_impact_or_stock_changes(tenant_a, admin_user):
    alert = ingest_alert(
        alert_reference="PPB-TEST-MISSING", title="Unknown test batch", severity="HIGH", actor=admin_user,
    )
    alert = activate_alert(alert=alert, actor=admin_user)
    with pytest.raises(ValidationError, match="No stock batch matches"):
        quarantine_tenant_stock(
            alert=alert, tenant_id=tenant_a.pk, actor=admin_user, affected_batches=["NOT-IN-STOCK"],
        )
    impact = RegulatoryTenantImpact.all_objects.get(tenant=tenant_a, alert=alert)
    assert impact.state == "PENDING"
    assert not InventoryLedgerEntry.all_objects.filter(tenant=tenant_a).exists()
