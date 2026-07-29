from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.medicines.models import CommercialSKU
from apps.tenancy.models import Tenant

from .models import PriceAssignment, PriceBook, PriceBookEntry, PriceBookVersion

MANAGE_CAPABILITY = "pricing.price_book.manage"
APPROVE_CAPABILITY = "pricing.price_book.approve"
PUBLISH_CAPABILITY = "pricing.price_book.publish"


def _holds(actor, capability: str, tenant_id) -> bool:
    if actor is None:
        return False
    if getattr(actor, "is_platform_admin", False) or getattr(actor, "is_superuser", False):
        return True
    checker = getattr(actor, "has_capability", None)
    return bool(callable(checker) and checker(capability, tenant_id=tenant_id))


def _require(actor, capability: str, tenant_id) -> None:
    if not _holds(actor, capability, tenant_id):
        raise PermissionDenied(f"{capability} capability is required.")


class PriceBookVersionService:
    @classmethod
    @transaction.atomic
    def save_tenant_retail_draft(
        cls,
        *,
        tenant_id,
        sku_code: str,
        unit_price,
        minimum_allowed_price=None,
        tax_inclusive: bool = True,
        actor,
    ) -> tuple[PriceBookEntry, bool]:
        _require(actor, MANAGE_CAPABILITY, tenant_id)
        tenant = Tenant.objects.filter(pk=tenant_id, status=Tenant.STATUS_ACTIVE).first()
        if tenant is None:
            raise ValidationError("An active tenant workspace is required.")

        try:
            price = Decimal(str(unit_price))
            floor = (
                Decimal(str(minimum_allowed_price))
                if minimum_allowed_price not in (None, "")
                else None
            )
        except Exception as exc:
            raise ValidationError("Prices must be valid decimal numbers.") from exc

        if not price.is_finite() or (floor is not None and not floor.is_finite()):
            raise ValidationError("Prices must be finite decimal numbers.")
        if price < 0:
            raise ValidationError("Unit price cannot be negative.")
        if floor is not None and floor < 0:
            raise ValidationError("Minimum allowed price cannot be negative.")
        if floor is not None and floor > price:
            raise ValidationError("Minimum allowed price cannot exceed the unit price.")
        if not isinstance(tax_inclusive, bool):
            raise ValidationError("tax_inclusive must be true or false.")

        sku = CommercialSKU.all_objects.filter(
            tenant_id=tenant.pk,
            sku_code=str(sku_code or "").strip(),
        ).first()
        if sku is None:
            raise ValidationError(
                "Select an existing tenant commercial SKU. Package and product governance "
                "must be completed before an item can be priced."
            )
        if not sku.is_saleable or sku.status in {
            CommercialSKU.STATUS_DISCONTINUED,
            CommercialSKU.STATUS_RECALLED,
        }:
            raise ValidationError("The selected SKU is not eligible for retail pricing.")

        price_book = (
            PriceBook.all_objects.select_for_update()
            .filter(tenant=tenant, code="DEFAULT-RETAIL")
            .first()
        )
        if price_book is None:
            price_book = PriceBook.all_objects.create(
                tenant=tenant,
                code="DEFAULT-RETAIL",
                name="Default Tenant Retail Book",
                price_type=PriceBook.PriceType.RETAIL,
                scope_type=PriceBook.ScopeType.TENANT,
                currency="KES",
                is_active=True,
            )
        PriceAssignment.all_objects.get_or_create(
            tenant=tenant,
            price_book=price_book,
            scope_type=PriceBook.ScopeType.TENANT,
            defaults={"is_active": True},
        )

        draft = (
            PriceBookVersion.all_objects.select_for_update()
            .filter(
                tenant=tenant,
                price_book=price_book,
                status=PriceBookVersion.Status.DRAFT,
            )
            .order_by("-version_number")
            .first()
        )
        if draft is None:
            latest_number = (
                PriceBookVersion.all_objects.filter(
                    tenant=tenant,
                    price_book=price_book,
                ).aggregate(number=Max("version_number"))["number"]
                or 0
            )
            source = (
                PriceBookVersion.all_objects.filter(
                    tenant=tenant,
                    price_book=price_book,
                    status__in=PriceBookVersion.PUBLISHED_STATES,
                )
                .order_by("-version_number")
                .first()
            )
            draft = PriceBookVersion.all_objects.create(
                tenant=tenant,
                price_book=price_book,
                version_number=latest_number + 1,
                status=PriceBookVersion.Status.DRAFT,
                effective_from=date.today(),
                created_by=actor,
            )
            if source is not None:
                PriceBookEntry.all_objects.bulk_create(
                    [
                        PriceBookEntry(
                            tenant=tenant,
                            version=draft,
                            sku=entry.sku,
                            unit_price=entry.unit_price,
                            minimum_quantity=entry.minimum_quantity,
                            maximum_quantity=entry.maximum_quantity,
                            minimum_allowed_price=entry.minimum_allowed_price,
                            tax_inclusive=entry.tax_inclusive,
                        )
                        for entry in PriceBookEntry.all_objects.filter(
                            tenant=tenant,
                            version=source,
                        ).select_related("sku")
                    ]
                )

        entry, created = PriceBookEntry.all_objects.update_or_create(
            tenant=tenant,
            version=draft,
            sku=sku,
            minimum_quantity=Decimal("1"),
            defaults={
                "unit_price": price,
                "minimum_allowed_price": floor,
                "tax_inclusive": bool(tax_inclusive),
            },
        )
        return entry, created

    @classmethod
    @transaction.atomic
    def submit(cls, *, version: PriceBookVersion, actor) -> PriceBookVersion:
        _require(actor, MANAGE_CAPABILITY, version.tenant_id)
        if version.status != PriceBookVersion.Status.DRAFT:
            raise ValidationError("Only a draft price-book version can be submitted.")
        if not PriceBookEntry.all_objects.filter(
            tenant_id=version.tenant_id,
            version=version,
        ).exists():
            raise ValidationError("A price-book version must contain at least one price.")
        version.status = PriceBookVersion.Status.UNDER_REVIEW
        version.save(update_fields=["status", "updated_at"])
        return version

    @classmethod
    @transaction.atomic
    def approve(cls, *, version: PriceBookVersion, actor) -> PriceBookVersion:
        _require(actor, APPROVE_CAPABILITY, version.tenant_id)
        if version.status != PriceBookVersion.Status.UNDER_REVIEW:
            raise ValidationError("Only a version under review can be approved.")
        if version.created_by_id == getattr(actor, "pk", None):
            raise PermissionDenied(
                "The person who prepared a price-book version cannot approve it."
            )
        version.status = PriceBookVersion.Status.APPROVED
        version.approved_by = actor
        version.approved_at = timezone.now()
        version.save(
            update_fields=["status", "approved_by", "approved_at", "updated_at"]
        )
        return version

    @classmethod
    @transaction.atomic
    def publish(cls, *, version: PriceBookVersion, actor) -> PriceBookVersion:
        _require(actor, PUBLISH_CAPABILITY, version.tenant_id)
        if version.status != PriceBookVersion.Status.APPROVED:
            raise ValidationError("Only an approved price-book version can be published.")

        today = date.today()
        if version.effective_from <= today:
            PriceBookVersion.all_objects.filter(
                tenant_id=version.tenant_id,
                price_book_id=version.price_book_id,
                status=PriceBookVersion.Status.ACTIVE,
            ).exclude(pk=version.pk).update(
                status=PriceBookVersion.Status.SUPERSEDED,
                updated_at=timezone.now(),
            )
            version.status = PriceBookVersion.Status.ACTIVE
        else:
            version.status = PriceBookVersion.Status.SCHEDULED
        version.published_at = timezone.now()
        version.save(update_fields=["status", "published_at", "updated_at"])
        return version
