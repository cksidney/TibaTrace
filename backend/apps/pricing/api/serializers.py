"""Read serialisers for the pricing workbench.

Read-only. Publishing a price version, approving an override and recording an
applied price each run through a service that enforces immutability, authority
and the floor. A writable viewset would reach the same columns without any of
that -- and a price book is the one table where an unguarded write changes what
every till charges.

Cost never appears. Confidential cost must not reach a POS operator, and an API
that serves both HQ and a till cannot be trusted to remember which caller it is
answering.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.pricing.models import (
    AppliedPriceSnapshot,
    ManualPriceOverride,
    PriceAssignment,
    PriceBook,
    PriceBookEntry,
    PriceBookVersion,
    PriceLock,
)


class PriceBookSerializer(serializers.ModelSerializer):
    live_version = serializers.SerializerMethodField()

    class Meta:
        model = PriceBook
        fields = [
            "id", "code", "name", "currency", "price_type", "scope_type",
            "priority", "tax_inclusive", "is_active", "live_version",
        ]

    def get_live_version(self, book) -> int | None:
        """The version a till would charge from today, if any.

        A book with no live version is configured but inert, and that is worth
        seeing on the list rather than discovering when nothing prices.
        """
        version = (
            PriceBookVersion.all_objects.filter(
                tenant_id=book.tenant_id, price_book=book, status="ACTIVE"
            )
            .order_by("-version_number")
            .first()
        )
        return version.version_number if version else None


class PriceBookVersionSerializer(serializers.ModelSerializer):
    price_book_code = serializers.CharField(source="price_book.code", read_only=True)
    entry_count = serializers.SerializerMethodField()
    is_published = serializers.BooleanField(read_only=True)

    class Meta:
        model = PriceBookVersion
        fields = [
            "id", "price_book_code", "version_number", "status", "is_published",
            "effective_from", "effective_to", "approved_at", "published_at",
            "entry_count",
        ]

    def get_entry_count(self, version) -> int:
        return PriceBookEntry.all_objects.filter(
            tenant_id=version.tenant_id,
            version=version,
        ).count()


class PriceBookEntrySerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    version_number = serializers.IntegerField(source="version.version_number", read_only=True)

    class Meta:
        model = PriceBookEntry
        fields = [
            "id", "sku_code", "version_number", "unit_price", "minimum_quantity",
            "maximum_quantity", "minimum_allowed_price", "tax_inclusive",
        ]


class PriceAssignmentSerializer(serializers.ModelSerializer):
    price_book_code = serializers.CharField(source="price_book.code", read_only=True)

    class Meta:
        model = PriceAssignment
        fields = [
            "id", "price_book_code", "scope_type", "branch", "branch_group",
            "region", "customer_segment", "priority", "valid_from", "valid_to",
            "is_active",
        ]


class AppliedPriceSnapshotSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)

    class Meta:
        model = AppliedPriceSnapshot
        fields = [
            "id", "line_reference", "line_type", "sku_code", "quantity", "currency",
            "unit_price", "line_total", "discount_amount", "tax_amount",
            "source", "source_reference",
            # The trace is the point. Without it "why was this 650" is
            # unanswerable once the price has moved on.
            "resolution_trace", "context_hash", "resolved_at",
        ]


class ManualPriceOverrideSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    requested_by_username = serializers.CharField(
        source="requested_by.username", read_only=True
    )
    approved_by_username = serializers.SerializerMethodField()
    difference = serializers.SerializerMethodField()

    class Meta:
        model = ManualPriceOverride
        fields = [
            "id", "sku_code", "transaction_reference", "resolved_price",
            "override_price", "difference", "reason_code", "reason", "status",
            # Both parties, always. An override showing only who approved it
            # cannot be checked for self-approval.
            "requested_by_username", "approved_by_username",
            "approved_at", "expires_at", "created_at",
        ]

    def get_approved_by_username(self, override) -> str:
        return getattr(override.approved_by, "username", "") or ""

    def get_difference(self, override) -> str:
        return str(override.difference)


class PriceLockSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = PriceLock
        fields = [
            "id", "basket_reference", "line_reference", "sku_code",
            "locked_unit_price", "quantity", "currency", "source",
            "locked_at", "expires_at", "status", "is_live", "invalidation_reason",
        ]
