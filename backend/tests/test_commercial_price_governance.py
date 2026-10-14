"""Draft edit → independent exact-content review → immutable publication."""
# ruff: noqa: F811
import uuid
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient
from tests.test_pricing_authority import add_entry, world  # noqa: F401

from apps.customers.models import CustomerCommercialProfile
from apps.identity.models import Role, User, UserRole
from apps.sales.commercial_governance import fingerprint
from apps.sales.models import PriceList, PriceListEntry
from apps.sales.services import CommercialPricingService
from apps.tenancy.models import Tenant
from apps.workflows.models import DomainEvent

pytestmark = pytest.mark.django_db


def actor(world, name, capabilities):
    user = User.objects.create_user(username=name, tenant=world["tenant"])
    role = Role.all_objects.create(tenant=world["tenant"], code=name, name=name, capabilities=capabilities)
    UserRole.all_objects.create(tenant=world["tenant"], user=user, role=role)
    client = APIClient()
    client.force_authenticate(user)
    client.defaults["HTTP_X_TENANT_ID"] = str(world["tenant"].pk)
    return user, client


@pytest.fixture
def draft(world):
    _, client = actor(world, "price-maker", ["pricing.manage", "pricing.commercial.approve", "pricing.commercial.publish"])
    response = client.post("/api/sales/price-lists/", {"code": "REVIEWED", "name": "Reviewed prices", "effective_from": str(timezone.localdate()),
        "change_reason": "New commercial list"}, format="json")
    assert response.status_code == 201, response.data
    created = PriceList.all_objects.get(pk=response.data["id"])
    entry = client.post("/api/sales/price-entries/", {"price_list": str(created.pk), "sku": str(world["sku"].pk), "unit_price": "120.00",
        "minimum_quantity": "1", "effective_from": str(timezone.localdate()), "change_reason": "Source confirmed unit price"}, format="json")
    assert entry.status_code == 201, entry.data
    return created, client, entry.data["id"]


def command(client, row, operation, *, key=None, expected=None, reason="Reviewed actual commercial prices"):
    row.refresh_from_db()
    return client.post(f"/api/sales/price-lists/{row.pk}/govern/", {"operation": operation,
        "expected_content_hash": expected or fingerprint(row), "reason": reason, "idempotency_key": key or str(uuid.uuid4())}, format="json")


def approve(world, draft):
    row, maker, _ = draft
    assert command(maker, row, "submit").status_code == 200
    _, reviewer = actor(world, "independent-reviewer", ["pricing.commercial.approve"])
    assert reviewer.get(f"/api/sales/price-lists/{row.pk}/").status_code == 200
    response = command(reviewer, row, "approve")
    assert response.status_code == 200, response.data
    return reviewer


def test_draft_review_publication_is_independent_replay_safe_and_immutable(world, draft):
    row, maker, entry_id = draft
    assert command(maker, row, "publish").status_code == 400
    assert command(maker, row, "submit", key="submit-key").status_code == 200
    assert command(maker, row, "submit", key="submit-key").status_code == 200
    assert command(maker, row, "approve").status_code == 400
    _, reviewer = actor(world, "reviewer", ["pricing.commercial.approve"])
    assert command(reviewer, row, "approve").status_code == 200
    response = command(maker, row, "publish", key="publish-key")
    assert response.status_code == 200 and response.data["status"] == "ACTIVE"
    assert command(maker, row, "publish", key="publish-key").status_code == 200
    assert DomainEvent.all_objects.filter(event_type="B2B_PRICE_PUBLISHED").count() == 1
    for path in (f"/api/sales/price-lists/{row.pk}/", f"/api/sales/price-entries/{entry_id}/"):
        assert maker.patch(path, {"unit_price": "1", "name": "Alter live price", "change_reason": "Bypass"}, format="json").status_code == 400
        assert maker.delete(path, {"change_reason": "Remove history"}, format="json").status_code == 400
    assert PriceListEntry.all_objects.get(pk=entry_id).unit_price == 120


def test_edit_invalidates_approval_and_stale_publish_is_refused(world, draft):
    row, maker, entry_id = draft
    approve(world, draft)
    old = fingerprint(row)
    assert maker.patch(f"/api/sales/price-entries/{entry_id}/", {"unit_price": "121.00", "change_reason": "New supplier price"}, format="json").status_code == 200
    assert command(maker, row, "publish", expected=old).status_code == 400
    assert command(maker, row, "publish").status_code == 400
    assert maker.get(f"/api/sales/price-lists/{row.pk}/").data["governance"]["state"] == "DRAFT"


def test_revoked_approver_cannot_leave_a_usable_publication_decision(world, draft):
    reviewer = approve(world, draft)
    reviewer.handler._force_user.is_active = False
    reviewer.handler._force_user.save(update_fields=["is_active"])
    row, maker, _ = draft
    assert command(maker, row, "publish").status_code == 403


def test_any_draft_contributor_is_excluded_from_approval(world, draft):
    row, maker, entry_id = draft
    _, editor = actor(world, "second-editor", ["pricing.manage", "pricing.commercial.approve"])
    assert editor.patch(f"/api/sales/price-entries/{entry_id}/", {"unit_price": "122", "change_reason": "Edit draft"}, format="json").status_code == 200
    assert command(maker, row, "submit").status_code == 200
    assert command(editor, row, "approve").status_code == 400


def test_retry_key_binds_operation_details_and_actor(world, draft):
    row, maker, _ = draft
    assert command(maker, row, "submit", key="bound").status_code == 200
    assert command(maker, row, "submit", key="bound", reason="Different reason").status_code == 400
    _, other = actor(world, "other-maker", ["pricing.manage"])
    assert command(other, row, "submit", key="bound").status_code == 400


def test_duplicate_default_publication_is_refused(world, draft):
    row, maker, _ = draft
    assert maker.patch(f"/api/sales/price-lists/{row.pk}/", {"is_default": True, "change_reason": "Choose default"}, format="json").status_code == 200
    approve(world, draft)
    assert command(maker, row, "publish").status_code == 400
    assert maker.post(f"/api/sales/price-lists/{world['price_list'].pk}/archive/", {"reason": "Replace conflicting default"}, format="json").status_code == 200
    assert command(maker, row, "publish").status_code == 200


def test_existing_assigned_inactive_list_does_not_fall_back_to_default(world):
    add_entry(world, unit_price="240")
    inactive = PriceList.all_objects.create(tenant=world["tenant"], code="NOT-APPROVED", name="Draft", effective_from=timezone.localdate())
    CustomerCommercialProfile.all_objects.create(tenant=world["tenant"], customer=world["customer"], price_list=inactive)
    with pytest.raises(ValidationError, match="assigned price list"):
        CommercialPricingService.resolve_price(tenant=world["tenant"], customer=world["customer"], sku=world["sku"])


def test_ambiguous_live_defaults_and_currency_mismatch_fail_closed(world):
    add_entry(world, unit_price="240")
    with pytest.raises(ValidationError, match="currency"):
        CommercialPricingService.resolve_price(tenant=world["tenant"], customer=world["customer"], sku=world["sku"], currency="USD")
    PriceList.all_objects.create(tenant=world["tenant"], code="AMBIGUOUS", name="Ambiguous", status="ACTIVE", is_default=True, effective_from=timezone.localdate())
    with pytest.raises(ValidationError, match="Multiple active"):
        CommercialPricingService.resolve_price(tenant=world["tenant"], customer=world["customer"], sku=world["sku"])


def test_active_list_can_be_cloned_without_editing_original_or_claiming_approval(world, draft):
    add_entry(world, unit_price="240")
    row, maker, _ = draft
    source = world["price_list"]
    body = {"code": "COPY", "name": "New draft copy", "effective_from": str(timezone.localdate()), "reason": "Review next prices", "idempotency_key": "clone-key"}
    first = maker.post(f"/api/sales/price-lists/{source.pk}/new-draft/", body, format="json")
    second = maker.post(f"/api/sales/price-lists/{source.pk}/new-draft/", body, format="json")
    assert first.status_code == second.status_code == 201, first.data
    assert first.data["id"] == second.data["id"]
    assert first.data["status"] == "DRAFT" and first.data["governance"]["state"] == "DRAFT"
    assert PriceListEntry.all_objects.get(price_list_id=first.data["id"]).unit_price == 240
    source.refresh_from_db()
    assert source.status == "ACTIVE"


def test_workspace_options_expose_actual_unit_and_scope(world, draft):
    _, maker, _ = draft
    response = maker.get("/api/sales/price-lists/workspace-options/?q=Tenormin")
    assert response.status_code == 200, response.data
    assert response.data["skus"][0]["sales_unit"] == "tablet"
    assert response.data["can_edit"] and response.data["can_approve"] and response.data["can_publish"]


def test_quantity_breaks_can_share_the_same_start_date(world, draft):
    row, maker, _ = draft
    response = maker.post("/api/sales/price-entries/", {"price_list": str(row.pk), "sku": str(world["sku"].pk), "unit_price": "110.00",
        "minimum_quantity": "50", "effective_from": str(timezone.localdate()), "change_reason": "Confirmed bulk quantity break"}, format="json")
    assert response.status_code == 201, response.data
    approve(world, draft)
    assert command(maker, row, "publish").status_code == 200
    CustomerCommercialProfile.all_objects.create(tenant=world["tenant"], customer=world["customer"], price_list=row)
    assert CommercialPricingService.resolve_price(tenant=world["tenant"], customer=world["customer"], sku=world["sku"], quantity=50)["base_unit_price"] == 110


def test_empty_invalid_dated_and_expired_only_drafts_are_not_reviewable(world, draft):
    row, maker, entry_id = draft
    assert maker.patch(f"/api/sales/price-lists/{row.pk}/", {"effective_to": "2000-01-01", "change_reason": "Bad dates"}, format="json").status_code == 400
    assert maker.patch(f"/api/sales/price-entries/{entry_id}/", {"unit_price": "0", "change_reason": "No free item"}, format="json").status_code == 400
    assert maker.patch(f"/api/sales/price-entries/{entry_id}/", {"is_active": False, "change_reason": "Disable price"}, format="json").status_code == 200
    assert command(maker, row, "submit").status_code == 400
    PriceListEntry.all_objects.filter(pk=entry_id).update(is_active=True, effective_from=timezone.localdate() - timedelta(days=2), effective_to=timezone.localdate() - timedelta(days=1))
    assert command(maker, row, "submit").status_code == 400


def test_overlapping_same_quantity_break_is_not_reviewable(world, draft):
    row, maker, _ = draft
    PriceListEntry.all_objects.create(tenant=world["tenant"], price_list=row, sku=world["sku"], unit_price=111, minimum_quantity=1,
        effective_from=timezone.localdate() + timedelta(days=1))
    assert command(maker, row, "submit").status_code == 400


def test_draft_create_retry_is_bound_and_cannot_duplicate_or_change_price(world, draft):
    _, maker, _ = draft
    body = {"code": "RETRY-DRAFT", "name": "Retry draft", "effective_from": str(timezone.localdate()), "change_reason": "Confirmed draft", "idempotency_key": "create-retry"}
    first = maker.post("/api/sales/price-lists/", body, format="json")
    second = maker.post("/api/sales/price-lists/", body, format="json")
    assert first.status_code == second.status_code == 201, second.data
    assert first.data["id"] == second.data["id"]
    assert maker.post("/api/sales/price-lists/", {**body, "name": "Changed payload"}, format="json").status_code == 400


def test_legacy_overlapping_live_entries_and_zero_price_fail_closed(world):
    first = add_entry(world, unit_price="240")
    PriceListEntry.all_objects.create(tenant=world["tenant"], price_list=world["price_list"], sku=world["sku"], unit_price=241,
        effective_from=timezone.localdate() - timedelta(days=1))
    with pytest.raises(ValidationError, match="Overlapping effective"):
        CommercialPricingService.resolve_price(tenant=world["tenant"], customer=world["customer"], sku=world["sku"])
    PriceListEntry.all_objects.filter(price_list=world["price_list"]).exclude(pk=first.pk).delete()
    first.unit_price = 0
    first.save(update_fields=["unit_price"])
    with pytest.raises(ValidationError, match="must be positive"):
        CommercialPricingService.resolve_price(tenant=world["tenant"], customer=world["customer"], sku=world["sku"])


def test_assigned_state_is_fresh_and_foreign_assignment_never_falls_back(world):
    add_entry(world, unit_price="240")
    profile = CustomerCommercialProfile.all_objects.create(tenant=world["tenant"], customer=world["customer"], price_list=world["price_list"])
    assert CommercialPricingService.resolve_price(tenant=world["tenant"], customer=world["customer"], sku=world["sku"])["base_unit_price"] == 240
    PriceList.all_objects.filter(pk=world["price_list"].pk).update(status="ARCHIVED")
    with pytest.raises(ValidationError, match="assigned price list"):
        CommercialPricingService.resolve_price(tenant=world["tenant"], customer=world["customer"], sku=world["sku"])
    other = Tenant.objects.create(name="Other pricing tenant", slug="other-pricing-tenant")
    foreign = PriceList.all_objects.create(tenant=other, code="FOREIGN", name="Foreign prices", status="ACTIVE", effective_from=timezone.localdate())
    CustomerCommercialProfile.all_objects.filter(pk=profile.pk).update(price_list=foreign)
    with pytest.raises(ValidationError, match="assigned price list"):
        CommercialPricingService.resolve_price(tenant=world["tenant"], customer=world["customer"], sku=world["sku"])


def test_malformed_pricing_commands_are_client_errors_not_server_errors(world, draft):
    row, maker, _ = draft
    for payload in ([], {"operation": ["publish"]}, {"operation": "publish", "reason": "x", "idempotency_key": "x", "expected_content_hash": "not-a-hash"}):
        assert maker.post(f"/api/sales/price-lists/{row.pk}/govern/", payload, format="json").status_code == 400
    assert maker.post(f"/api/sales/price-lists/{row.pk}/archive/", [], format="json").status_code == 400
