from decimal import Decimal
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.core.tenant_context import get_current_tenant_id, reset_current_tenant_id, set_current_tenant_id
from apps.identity.models import Role, User, UserRole
from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
    StocktakeCount,
    StocktakeCountRevision,
    StocktakeSession,
)
from apps.inventory.services import ExpiryControlService, InventoryLedgerService, StocktakeService
from apps.inventory.tasks import dispatch_expiry_maintenance, process_tenant_expiry
from apps.tenancy.models import Tenant


def stocktake_operator(tenant, name):
    user = User.objects.create_user(username=name, tenant=tenant)
    role = Role.all_objects.create(tenant=tenant, code=name, name=name, capabilities=["inventory.manage"])
    UserRole.all_objects.create(tenant=tenant, user=user, role=role)
    return user


@pytest.fixture
def count_world(tenant_a, branch, inventory_location, sku, inventory_batch):
    opener = stocktake_operator(tenant_a, "stocktake-opener")
    approver = stocktake_operator(tenant_a, "stocktake-independent-approver")
    recounter = stocktake_operator(tenant_a, "stocktake-recounter")
    def receive(quantity, key="initial"):
        return InventoryLedgerService.post_entry(
            tenant=tenant_a, branch=branch, location=inventory_location, sku=sku, inventory_batch=inventory_batch,
            entry_type=InventoryLedgerEntry.EntryType.RECEIPT, quantity_delta=quantity, unit="tablet", base_quantity_delta=quantity,
            effective_timestamp=timezone.now(), source_document_type="TEST", source_document_id=key, idempotency_key=key,
        )
    receive(100)
    session = StocktakeService.open_stocktake(tenant=tenant_a, branch=branch, locations=[inventory_location], scope="FULL", creator=opener)
    return {"tenant": tenant_a, "branch": branch, "location": inventory_location, "sku": sku, "batch": inventory_batch,
            "opener": opener, "approver": approver, "recounter": recounter, "session": session, "receive": receive}


def record(world, quantity=95):
    return StocktakeService.record_count(session=world["session"], location=world["location"], sku=world["sku"], batch=world["batch"], counted_quantity=quantity, counter=world["opener"])


@pytest.mark.django_db
def test_recount_preserves_first_count_and_new_movement_basis(count_world):
    world = count_world
    count = record(world)
    before = count.updated_at
    world["receive"](10, "movement-after-count")
    updated = StocktakeService.revise_count(session=world["session"], count_id=count.pk, actor=world["recounter"], reason="Independent physical recount", expected_updated_at=before, idempotency_key="recount-one", counted_quantity=108)
    assert updated.first_count == 95
    assert updated.recount == 108
    assert updated.expected_quantity == 110
    assert updated.variance == -2
    assert updated.counter_id == world["opener"].pk
    StocktakeService.post_variances(session=world["session"], approver=world["approver"])
    StocktakeService.post_variances(session=world["session"], approver=world["approver"])
    balance = InventoryBalance.all_objects.get(tenant=world["tenant"], inventory_batch=world["batch"])
    assert balance.on_hand == 108
    updated.refresh_from_db()
    assert updated.final_approved_count == 108
    revision = StocktakeCountRevision.all_objects.get(count=count)
    assert revision.previous_quantity == 95
    assert revision.previous_expected_quantity == 100
    assert revision.counted_quantity == 108
    with pytest.raises(ValidationError, match="immutable"):
        revision.save()
    with pytest.raises(ValidationError, match="immutable"):
        StocktakeCountRevision.all_objects.filter(pk=revision.pk).update(reason="Rewrite")
    with pytest.raises(ValidationError, match="immutable"):
        StocktakeCountRevision.all_objects.filter(pk=revision.pk).delete()


@pytest.mark.django_db
def test_recount_replay_is_idempotent_and_rejects_conflicting_or_stale_request(count_world):
    count = record(count_world)
    kwargs = dict(session=count_world["session"], count_id=count.pk, actor=count_world["recounter"], reason="Count correction", expected_updated_at=count.updated_at, idempotency_key="same-key", counted_quantity=94)
    StocktakeService.revise_count(**kwargs)
    StocktakeService.revise_count(**kwargs)
    assert StocktakeCountRevision.all_objects.filter(count=count).count() == 1
    with pytest.raises(ValidationError, match="different"):
        StocktakeService.revise_count(**{**kwargs, "counted_quantity": 92})
    with pytest.raises(ValidationError, match="changed"):
        StocktakeService.revise_count(**{**kwargs, "idempotency_key": "new-key"})


@pytest.mark.django_db
def test_recount_supports_an_unbatched_zero_count_without_locking_a_null_join(count_world):
    world = count_world
    count = StocktakeService.record_count(
        session=world["session"], location=world["location"], sku=world["sku"], batch=None,
        counted_quantity=0, counter=world["opener"],
    )
    revised = StocktakeService.revise_count(
        session=world["session"], count_id=count.pk, actor=world["recounter"], reason="Confirm no unbatched stock",
        expected_updated_at=count.updated_at, idempotency_key="unbatched-recount", counted_quantity=0,
    )
    assert revised.batch_id is None and revised.counted_quantity == 0 and revised.expected_quantity == 0
    assert StocktakeCountRevision.all_objects.get(count=revised).previous_quantity == 0


@pytest.mark.django_db
def test_every_count_contributor_is_excluded_from_approval(count_world):
    count = record(count_world)
    StocktakeService.revise_count(session=count_world["session"], count_id=count.pk, actor=count_world["recounter"], reason="Recount", expected_updated_at=count.updated_at, idempotency_key="recount-two", counted_quantity=95)
    for actor in (count_world["opener"], count_world["recounter"]):
        with pytest.raises(ValidationError, match="different authorised operator"):
            StocktakeService.post_variances(session=count_world["session"], approver=actor)


@pytest.mark.django_db
def test_full_stocktake_cannot_post_missing_opening_scope(count_world):
    assert StocktakeService.completeness(count_world["session"])["required_lines"] == 1
    with pytest.raises(ValidationError):
        StocktakeService.post_variances(session=count_world["session"], approver=count_world["approver"])
    count = record(count_world)
    StocktakeService.revise_count(session=count_world["session"], count_id=count.pk, actor=count_world["recounter"], reason="Wrong observation", expected_updated_at=count.updated_at, idempotency_key="void-one", void=True)
    assert StocktakeService.completeness(count_world["session"])["complete"] is False
    with pytest.raises(ValidationError):
        StocktakeService.post_variances(session=count_world["session"], approver=count_world["approver"])
    new_count = record(count_world, 100)
    assert new_count.pk != count.pk
    assert StocktakeService.completeness(count_world["session"])["complete"] is True
    StocktakeService.post_variances(session=count_world["session"], approver=count_world["approver"])
    assert not InventoryLedgerEntry.all_objects.filter(source_document_type="STOCKTAKE").exists()


@pytest.mark.django_db
def test_empty_full_location_needs_explicit_physical_confirmation(count_world):
    world = count_world
    empty = InventoryLocation.all_objects.create(tenant=world["tenant"], branch=world["branch"], location_code="EMPTY", name="Empty store")
    session = StocktakeService.open_stocktake(tenant=world["tenant"], branch=world["branch"], locations=[empty], scope="FULL", creator=world["opener"])
    assert StocktakeService.completeness(session)["unconfirmed_empty_location_ids"] == [str(empty.pk)]
    with pytest.raises(ValidationError):
        StocktakeService.post_variances(session=session, approver=world["approver"])
    session = StocktakeService.confirm_empty_location(session=session, location_id=empty.pk, actor=world["recounter"], reason="Shelves physically inspected; no stock")
    with pytest.raises(ValidationError, match="different authorised operator"):
        StocktakeService.post_variances(session=session, approver=world["recounter"])
    result = StocktakeService.post_variances(session=session, approver=world["approver"])
    assert result.status == StocktakeSession.Status.POSTED


@pytest.mark.django_db
def test_legacy_full_session_is_not_silently_certified(count_world):
    record(count_world)
    StocktakeSession.all_objects.filter(pk=count_world["session"].pk).update(scope_snapshot=None)
    with pytest.raises(ValidationError, match="Pre-snapshot"):
        StocktakeService.post_variances(session=count_world["session"], approver=count_world["approver"])


@pytest.mark.django_db
def test_full_stocktake_requires_new_batches_received_after_opening(count_world):
    world = count_world
    record(world, 100)
    new_batch = InventoryBatch.all_objects.create(tenant=world["tenant"], sku=world["sku"], manufactured_product=world["sku"].manufactured_product,
                                                manufacturer_batch_number="ARRIVAL-AFTER-OPENING", expiry_date=timezone.localdate() + timezone.timedelta(days=50))
    InventoryLedgerService.post_entry(tenant=world["tenant"], branch=world["branch"], location=world["location"], sku=world["sku"], inventory_batch=new_batch,
                                     entry_type="RECEIPT", quantity_delta=10, unit="tablet", base_quantity_delta=10, effective_timestamp=timezone.now(),
                                     source_document_type="TEST", source_document_id="new-batch", idempotency_key="new-batch")
    completeness = StocktakeService.completeness(world["session"])
    assert completeness["complete"] is False
    assert completeness["missing_lines"][0]["added_after_opening"] is True
    with pytest.raises(ValidationError, match="every opening-scope"):
        StocktakeService.post_variances(session=world["session"], approver=world["approver"])
    StocktakeService.record_count(session=world["session"], location=world["location"], sku=world["sku"], batch=new_batch, counted_quantity=10, counter=world["opener"])
    assert StocktakeService.completeness(world["session"])["complete"] is True


@pytest.mark.django_db
def test_cancel_keeps_counts_and_never_posts_inventory(count_world):
    count = record(count_world)
    session = StocktakeService.cancel(session=count_world["session"], actor=count_world["opener"], reason="Incorrect scope; reopen with full store")
    StocktakeService.cancel(session=session, actor=count_world["opener"], reason="Retry")
    assert session.status == StocktakeSession.Status.CANCELLED
    assert StocktakeCount.all_objects.filter(tenant_id=session.tenant_id, session=session, pk=count.pk).exists()
    assert AuditEvent.all_objects.filter(action="INVENTORY_STOCKTAKE_CANCELLED", object_id=str(session.pk)).count() == 1
    assert not InventoryLedgerEntry.all_objects.filter(source_document_type="STOCKTAKE").exists()
    with pytest.raises(ValidationError):
        record(count_world)


@pytest.mark.django_db
def test_stocktake_requires_capability_and_rejects_cross_session_revision(count_world):
    world = count_world
    no_authority = User.objects.create_user(username="unauthorised-count", tenant=world["tenant"])
    with pytest.raises(ValidationError, match="inventory.manage"):
        StocktakeService.cancel(session=world["session"], actor=no_authority, reason="No authority")
    count = record(world)
    other = StocktakeService.open_stocktake(tenant=world["tenant"], branch=world["branch"], locations=[world["location"]], scope="PARTIAL", creator=world["opener"])
    with pytest.raises(ValidationError, match="from this stocktake"):
        StocktakeService.revise_count(session=other, count_id=count.pk, actor=world["recounter"], reason="Wrong session", expected_updated_at=count.updated_at, idempotency_key="wrong-session", counted_quantity=100)
    client = APIClient()
    client.force_login(no_authority)
    assert client.get(f"/api/inventory/stocktakes/{world['session'].pk}/").status_code == 403


@pytest.mark.django_db
def test_stocktake_api_recount_void_and_cancel(count_world):
    world = count_world
    count = record(world)
    client = APIClient()
    client.force_login(world["opener"])
    path = f"/api/inventory/stocktakes/{world['session'].pk}/"
    response = client.post(path + "recount/", {"count_id": str(count.pk), "counted_quantity": "94", "reason": "Physical recheck", "expected_updated_at": count.updated_at.isoformat(), "idempotency_key": "api-recount"}, format="json")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["counts"][0]["first_count"] == "95.0000"
    assert body["counts"][0]["recount"] == "94.0000"
    assert body["completeness"]["complete"] is True
    response = client.post(path + "void-count/", {"count_id": str(count.pk), "reason": "Wrong count", "expected_updated_at": body["counts"][0]["updated_at"], "idempotency_key": "api-void"}, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["completeness"]["complete"] is False
    response = client.post(path + "cancel/", {"reason": "Reopen the right scope"}, format="json")
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


@pytest.mark.django_db
def test_expiry_task_is_idempotent_tenant_explicit_and_preserves_custody(count_world, tenant_b):
    world = count_world
    batch = world["batch"]
    batch.expiry_date = timezone.localdate() - timezone.timedelta(days=1)
    batch.save()
    with pytest.raises(ValueError, match="Explicit tenant"):
        process_tenant_expiry.run("")
    assert process_tenant_expiry.run(str(tenant_b.pk))["processed_batches"] == 0
    batch.refresh_from_db()
    assert batch.quality_status == InventoryBatch.QualityStatus.RELEASED
    old_token = set_current_tenant_id(tenant_b.pk)
    try:
        assert process_tenant_expiry.run(str(world["tenant"].pk))["processed_batches"] == 1
        assert get_current_tenant_id() == str(tenant_b.pk)
    finally:
        reset_current_tenant_id(old_token)
    assert process_tenant_expiry.run(str(world["tenant"].pk))["processed_batches"] == 0
    balance = InventoryBalance.all_objects.get(tenant=world["tenant"], inventory_batch=batch)
    assert balance.on_hand == Decimal("100")
    assert balance.expired == Decimal("100")
    assert balance.available == 0
    assert AuditEvent.all_objects.filter(action="INVENTORY_BATCH_EXPIRED", object_id=str(batch.pk)).count() == 1
    assert InventoryLedgerEntry.all_objects.filter(tenant=world["tenant"]).count() == 1


@pytest.mark.django_db
def test_expiry_on_date_remains_valid_and_dispatch_excludes_terminated(count_world, tenant_b):
    world = count_world
    batch = world["batch"]
    batch.expiry_date = timezone.localdate()
    batch.save()
    assert ExpiryControlService.process_expired_batches(world["tenant"]) == 0
    tenant_b.status = Tenant.STATUS_TERMINATED
    tenant_b.save()
    with patch("apps.inventory.tasks.process_tenant_expiry.delay") as dispatch:
        result = dispatch_expiry_maintenance.run()
    assert result == {"dispatched_tenants": 1}
    dispatch.assert_called_once_with(str(world["tenant"].pk))
    assert process_tenant_expiry.run(str(tenant_b.pk))["skipped"] == "TERMINATED"
    schedule = settings.CELERY_BEAT_SCHEDULE["inventory-expiry-maintenance-hourly"]
    assert schedule["task"] == "apps.inventory.tasks.dispatch_expiry_maintenance"
    assert schedule["schedule"] == 3600.0
