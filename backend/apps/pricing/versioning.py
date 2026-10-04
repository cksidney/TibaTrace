from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

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


@dataclass(frozen=True)
class PriceImportIssue:
    """An actionable spreadsheet-row problem for a price draft import."""

    row: int
    field: str
    value: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "field": self.field,
            "value": self.value,
            "message": self.message,
        }


@dataclass(frozen=True)
class ValidatedPriceImportRow:
    row: int
    sku: CommercialSKU
    unit_price: Decimal
    minimum_allowed_price: Decimal | None
    tax_inclusive: bool


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
    """Author price-book drafts without ever changing a live price.

    Both the one-item form and CSV import call the same draft helper.  This
    avoids the historic split where a page visit created ``RETAIL-DEFAULT`` but
    a price save created a second ``DEFAULT-RETAIL`` book for the same tenant.
    ``RETAIL-DEFAULT`` remains supported for tenants created by that older
    read path; new books retain the established write-path code.
    """

    MAX_IMPORT_ROWS = 5_000
    DEFAULT_RETAIL_CODE = "DEFAULT-RETAIL"
    ALTERNATE_DEFAULT_RETAIL_CODE = "RETAIL-DEFAULT"

    @classmethod
    def _active_tenant(cls, tenant_id):
        tenant = Tenant.objects.filter(pk=tenant_id, status=Tenant.STATUS_ACTIVE).first()
        if tenant is None:
            raise ValidationError("An active tenant workspace is required.")
        return tenant

    @classmethod
    def _find_retail_book(cls, *, tenant, lock: bool = False):
        queryset = PriceBook.all_objects.filter(
            tenant=tenant,
            code__in=(cls.DEFAULT_RETAIL_CODE, cls.ALTERNATE_DEFAULT_RETAIL_CODE),
        )
        if lock:
            queryset = queryset.select_for_update()
        # Prefer the established write-path code if both exist.  This avoids
        # creating another tenant-scope assignment for installations that used
        # the original single-price API before the workbench was introduced.
        return queryset.order_by("code").first()

    @classmethod
    def _get_or_create_tenant_retail_draft(cls, *, tenant, actor) -> tuple[PriceBook, PriceBookVersion]:
        """Return the one editable tenant retail draft, copying a live version once."""
        price_book = cls._find_retail_book(tenant=tenant, lock=True)
        if price_book is None:
            price_book = PriceBook.all_objects.create(
                tenant=tenant,
                code=cls.DEFAULT_RETAIL_CODE,
                name="Standard Tenant Retail Price Book",
                price_type=PriceBook.PriceType.RETAIL,
                scope_type=PriceBook.ScopeType.TENANT,
                currency="KES",
                priority=100,
                is_active=True,
            )
        PriceAssignment.all_objects.get_or_create(
            tenant=tenant,
            price_book=price_book,
            scope_type=PriceBook.ScopeType.TENANT,
            defaults={"priority": 100, "is_active": True},
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
        if draft is not None:
            return price_book, draft

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
        return price_book, draft

    @classmethod
    def _parse_tax_inclusive(cls, value) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "1"}:
                return True
            if normalized in {"false", "no", "0"}:
                return False
        return None

    @classmethod
    def _validate_import_rows(
        cls,
        *,
        tenant,
        rows,
    ) -> tuple[list[ValidatedPriceImportRow], list[PriceImportIssue]]:
        """Validate every row before a price book or draft can be written."""
        if not isinstance(rows, list):
            return [], [PriceImportIssue(0, "rows", "", "rows must be a list of price records.")]
        if not rows:
            return [], [PriceImportIssue(0, "rows", "", "The import contains no data rows.")]
        if len(rows) > cls.MAX_IMPORT_ROWS:
            return [], [PriceImportIssue(
                0,
                "rows",
                str(len(rows)),
                f"A single import may contain at most {cls.MAX_IMPORT_ROWS} rows.",
            )]

        issues: list[PriceImportIssue] = []
        parsed: list[tuple[int, str, Decimal | None, Decimal | None, bool | None]] = []
        first_seen: dict[str, int] = {}
        for row_number, payload in enumerate(rows, start=2):
            values = payload if isinstance(payload, dict) else {}
            if isinstance(payload, dict):
                try:
                    candidate = int(payload.get("_source_row", row_number))
                    if candidate >= 2:
                        row_number = candidate
                except (TypeError, ValueError):
                    pass
            sku_code = str(values.get("sku_code") or "").strip()
            if not sku_code:
                issues.append(PriceImportIssue(row_number, "sku_code", "", "A tenant SKU code is required."))
                continue
            if len(sku_code) > 100:
                issues.append(PriceImportIssue(
                    row_number, "sku_code", sku_code, "The SKU code is longer than 100 characters."
                ))
                continue
            if sku_code in first_seen:
                issues.append(PriceImportIssue(
                    row_number,
                    "sku_code",
                    sku_code,
                    f"Duplicate of row {first_seen[sku_code]}.",
                ))
                continue
            first_seen[sku_code] = row_number

            raw_price = values.get("unit_price")
            raw_floor = values.get("minimum_allowed_price")
            try:
                price = Decimal(str(raw_price).strip())
            except Exception:
                price = None
            try:
                floor = (
                    Decimal(str(raw_floor).strip())
                    if raw_floor not in (None, "")
                    else None
                )
            except Exception:
                floor = None

            if price is None or not price.is_finite():
                issues.append(PriceImportIssue(
                    row_number, "unit_price", str(raw_price or ""), "Unit price must be a finite decimal number."
                ))
                continue
            if price < 0:
                issues.append(PriceImportIssue(
                    row_number, "unit_price", str(raw_price), "Unit price cannot be negative."
                ))
                continue
            if price.as_tuple().exponent < -2 or price.adjusted() > 12:
                issues.append(PriceImportIssue(
                    row_number, "unit_price", str(raw_price), "Unit price must fit a two-decimal KES amount."
                ))
                continue
            if raw_floor not in (None, "") and (floor is None or not floor.is_finite()):
                issues.append(PriceImportIssue(
                    row_number,
                    "minimum_allowed_price",
                    str(raw_floor or ""),
                    "Minimum allowed price must be a finite decimal number.",
                ))
                continue
            if floor is not None and floor < 0:
                issues.append(PriceImportIssue(
                    row_number, "minimum_allowed_price", str(raw_floor), "Minimum allowed price cannot be negative."
                ))
                continue
            if floor is not None and (floor.as_tuple().exponent < -2 or floor.adjusted() > 12):
                issues.append(PriceImportIssue(
                    row_number,
                    "minimum_allowed_price",
                    str(raw_floor),
                    "Minimum allowed price must fit a two-decimal KES amount.",
                ))
                continue
            if floor is not None and floor > price:
                issues.append(PriceImportIssue(
                    row_number,
                    "minimum_allowed_price",
                    str(raw_floor),
                    "Minimum allowed price cannot exceed the unit price.",
                ))
                continue

            tax_inclusive = cls._parse_tax_inclusive(values.get("tax_inclusive", True))
            if tax_inclusive is None:
                issues.append(PriceImportIssue(
                    row_number,
                    "tax_inclusive",
                    str(values.get("tax_inclusive", "")),
                    "tax_inclusive must be true or false.",
                ))
                continue
            parsed.append((row_number, sku_code, price, floor, tax_inclusive))

        sku_by_code = {
            sku.sku_code: sku
            for sku in CommercialSKU.all_objects.filter(
                tenant=tenant,
                sku_code__in=[sku_code for _, sku_code, _, _, _ in parsed],
            )
        }
        validated: list[ValidatedPriceImportRow] = []
        for row_number, sku_code, price, floor, tax_inclusive in parsed:
            sku = sku_by_code.get(sku_code)
            if sku is None:
                issues.append(PriceImportIssue(
                    row_number,
                    "sku_code",
                    sku_code,
                    "No tenant commercial SKU matches this code. Complete product and package governance first.",
                ))
                continue
            if not sku.is_saleable or sku.status in {
                CommercialSKU.STATUS_DISCONTINUED,
                CommercialSKU.STATUS_RECALLED,
            }:
                issues.append(PriceImportIssue(
                    row_number,
                    "sku_code",
                    sku_code,
                    "This SKU is not eligible for retail pricing.",
                ))
                continue
            validated.append(ValidatedPriceImportRow(
                row=row_number,
                sku=sku,
                unit_price=price,
                minimum_allowed_price=floor,
                tax_inclusive=tax_inclusive,
            ))
        return validated, issues

    @classmethod
    def import_tenant_retail_draft(
        cls,
        *,
        tenant_id,
        rows,
        actor,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Preview or atomically save a CSV into the tenant's editable draft.

        This never submits, approves or publishes a version.  Bulk speed does
        not weaken separation of duties: the normal independent review and
        publication actions still decide what tills can charge.
        """
        _require(actor, MANAGE_CAPABILITY, tenant_id)
        tenant = cls._active_tenant(tenant_id)
        valid_rows, issues = cls._validate_import_rows(tenant=tenant, rows=rows)
        price_book = cls._find_retail_book(tenant=tenant)
        draft = None
        if price_book is not None:
            draft = PriceBookVersion.all_objects.filter(
                tenant=tenant,
                price_book=price_book,
                status=PriceBookVersion.Status.DRAFT,
            ).order_by("-version_number").first()
        existing_sku_ids = set()
        if draft is not None:
            existing_sku_ids = set(
                PriceBookEntry.all_objects.filter(
                    tenant=tenant,
                    version=draft,
                    sku_id__in=[item.sku.pk for item in valid_rows],
                    minimum_quantity=Decimal("1"),
                ).values_list("sku_id", flat=True)
            )
        to_update = sum(1 for item in valid_rows if item.sku.pk in existing_sku_ids)
        result: dict[str, Any] = {
            "dry_run": bool(dry_run),
            "received": len(rows) if isinstance(rows, list) else 0,
            "valid": not issues,
            "ready_to_create": len(valid_rows) - to_update,
            "ready_to_update": to_update,
            "saved": 0,
            "price_book": price_book.code if price_book else cls.DEFAULT_RETAIL_CODE,
            "version_id": str(draft.pk) if draft else None,
            "version_number": draft.version_number if draft else None,
            "errors": [issue.as_dict() for issue in issues],
        }
        if issues or dry_run:
            return result

        with transaction.atomic():
            price_book, draft = cls._get_or_create_tenant_retail_draft(tenant=tenant, actor=actor)
            for item in valid_rows:
                PriceBookEntry.all_objects.update_or_create(
                    tenant=tenant,
                    version=draft,
                    sku=item.sku,
                    minimum_quantity=Decimal("1"),
                    defaults={
                        "unit_price": item.unit_price,
                        "minimum_allowed_price": item.minimum_allowed_price,
                        "tax_inclusive": item.tax_inclusive,
                    },
                )
        result.update({
            "saved": len(valid_rows),
            "price_book": price_book.code,
            "version_id": str(draft.pk),
            "version_number": draft.version_number,
        })
        return result

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
        tenant = cls._active_tenant(tenant_id)

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

        price_book, draft = cls._get_or_create_tenant_retail_draft(tenant=tenant, actor=actor)

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
