"""Atomic re-upload of blind opening count sheets; preserves manager details."""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.medicines.onboarding import StaleSetupReview, assert_setup_access, save_review
from apps.medicines.onboarding_models import LegacyCatalogueItem


@transaction.atomic
def import_opening_counts(*, tenant_id, actor, rows, dry_run=True):
    from apps.medicines.api.onboarding import ReviewInput

    assert_setup_access(actor, tenant_id)
    if not isinstance(rows, list) or not 0 < len(rows) <= 5000:
        raise ValidationError("Upload between 1 and 5,000 completed count rows.")
    grouped = defaultdict(list)
    for index, row in enumerate(rows, 2):
        if not isinstance(row, dict):
            raise ValidationError(f"Row {index}: expected a count row.")
        try:
            key = str(UUID(row.get("item_id", "")))
        except (ValueError, TypeError, AttributeError):
            raise ValidationError(f"Row {index}: invalid item_id; use the downloaded sheet.") from None
        grouped[key].append((index, row))
    prepared = []
    for key, entries in grouped.items():
        item = LegacyCatalogueItem.all_objects.select_for_update().filter(tenant_id=tenant_id, pk=key).first()
        if item is None or item.completion or item.review.get("excluded"):
            raise ValidationError(f"Item {key} is unavailable, excluded or already staged in this tenant.")
        total = Decimal(0)
        batches = []
        batch_numbers = set()
        notes = []
        for line, row in entries:
            if parse_datetime(row.get("expected_updated_at", "")) != item.updated_at:
                raise StaleSetupReview(f"Row {line}: manager evidence changed. Download a new sheet.")
            try:
                quantity = Decimal(str(row.get("counted_quantity", "")))
                if not quantity.is_finite() or quantity < 0 or quantity.as_tuple().exponent < -4:
                    raise ValueError
                if date.fromisoformat(row.get("counted_on", "")) != timezone.localdate():
                    raise ValueError
            except (ValueError, ArithmeticError, TypeError):
                raise ValidationError(
                    f"Row {line}: enter a nonnegative physical count (up to four decimals) and today's count date."
                ) from None
            total += quantity
            batch = str(row.get("batch_number", "")).strip()
            expiry = str(row.get("expiry_date", "")).strip()
            if batch or expiry:
                if not batch or not expiry or batch.casefold() in batch_numbers or quantity <= 0:
                    raise ValidationError(
                        f"Row {line}: provide a unique actual batch, expiry and positive batch quantity."
                    )
                batch_numbers.add(batch.casefold())
                batches.append({"batch_number": batch, "expiry_date": expiry, "quantity": str(quantity)})
            elif len(entries) > 1:
                raise ValidationError(f"Row {line}: repeated items require one distinct batch per row.")
            if row.get("notes"):
                notes.append(str(row["notes"]))
        review = {
            **item.review,
            "counted_quantity": str(total),
            "counted_on": timezone.localdate().isoformat(),
            "batches": batches,
        }
        if notes:
            review["notes"] = "\n".join(notes)[:4000]
        serializer = ReviewInput(data=review)
        serializer.is_valid(raise_exception=True)
        prepared.append((item, dict(serializer.data)))
    if not dry_run:
        for item, review in prepared:
            save_review(item=item, actor=actor, review=review, expected_updated_at=item.updated_at.isoformat())
    return {
        "dry_run": dry_run,
        "items": len(prepared),
        "rows": len(rows),
        "detail": "Counts validated. Product, unit, price and quality review remain required.",
    }
