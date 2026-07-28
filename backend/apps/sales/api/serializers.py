from rest_framework import serializers

from apps.sales.models import (
    CustomerPriceAgreement,
    DeliveryLine,
    DeliveryRecord,
    DispatchLine,
    DispatchOrder,
    DispatchPackage,
    Package,
    PackageLine,
    PackingSession,
    PickingTask,
    PickingWave,
    PriceList,
    PriceListEntry,
    PromotionRule,
    Quotation,
    QuotationLine,
    QuotationRevision,
    SalesOrder,
    SalesOrderAllocation,
    SalesOrderHold,
    SalesOrderLine,
    SalesReturnAuthorization,
    SalesReturnLine,
    SubstitutionProposal,
)


class PriceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceList
        fields = [
            "id",
            "tenant",
            "code",
            "name",
            "currency",
            "effective_from",
            "effective_to",
            "is_default",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class PriceListEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceListEntry
        fields = [
            "id",
            "tenant",
            "price_list",
            "sku",
            "unit_price",
            "minimum_quantity",
            "effective_from",
            "effective_to",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "created_at", "updated_at"]


class CustomerPriceAgreementSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.legal_name", read_only=True)

    class Meta:
        model = CustomerPriceAgreement
        fields = [
            "id",
            "tenant",
            "customer",
            "sku",
            "agreed_price",
            "discount_percentage",
            "effective_from",
            "effective_to",
            "approved_by",
            "is_active",
            "created_at",
            "updated_at",
            "customer_name",
        ]
        read_only_fields = ["id", "tenant", "created_at", "updated_at"]


class PromotionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromotionRule
        fields = [
            "id",
            "tenant",
            "code",
            "name",
            "sku",
            "discount_percentage",
            "minimum_quantity",
            "effective_from",
            "effective_to",
            "is_active",
            "approved_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "created_at", "updated_at"]


class QuotationLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotationLine
        fields = [
            "id",
            "tenant",
            "quotation",
            "sku",
            "description_snapshot",
            "requested_quantity",
            "unit",
            "package_conversion",
            "base_unit_price",
            "agreed_unit_price",
            "discount_amount",
            "discount_percentage",
            "tax_rate",
            "tax_amount",
            "line_subtotal",
            "line_total",
            "currency",
            "price_list_ref",
            "promotion_ref",
            "override_reason",
            "price_approved_by",
            "requested_delivery_date",
            "substitution_preference",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "created_at", "updated_at"]


class QuotationSerializer(serializers.ModelSerializer):
    lines = QuotationLineSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.legal_name", read_only=True)

    class Meta:
        model = Quotation
        fields = [
            "id",
            "tenant",
            "quotation_number",
            "branch",
            "customer",
            "delivery_address",
            "currency",
            "status",
            "issue_date",
            "valid_until",
            "customer_reference",
            "salesperson",
            "notes",
            "terms",
            "subtotal",
            "tax_total",
            "total",
            "revision",
            "created_by",
            "approved_by",
            "sent_at",
            "accepted_at",
            "rejected_at",
            "created_at",
            "updated_at",
            "lines",
            "customer_name",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class QuotationRevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotationRevision
        fields = [
            "id",
            "tenant",
            "quotation",
            "revision_number",
            "previous_revision",
            "changed_fields",
            "previous_values",
            "new_values",
            "reason",
            "actor",
            "approval_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "approval_status", "created_at", "updated_at"]


class SalesOrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOrderLine
        fields = [
            "id",
            "tenant",
            "sales_order",
            "sku",
            "description_snapshot",
            "requested_quantity",
            "approved_quantity",
            "cancelled_quantity",
            "reserved_quantity",
            "allocated_quantity",
            "picked_quantity",
            "packed_quantity",
            "dispatched_quantity",
            "delivered_quantity",
            "returned_quantity",
            "backordered_quantity",
            "unit",
            "package_conversion",
            "base_unit_price",
            "agreed_unit_price",
            "discount_amount",
            "discount_percentage",
            "tax_rate",
            "tax_amount",
            "line_subtotal",
            "line_total",
            "currency",
            "price_list_ref",
            "promotion_ref",
            "override_reason",
            "price_approved_by",
            "substitution_preference",
            "requested_batch_constraints",
            "minimum_shelf_life_days",
            "status",
            "reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class SalesOrderSerializer(serializers.ModelSerializer):
    lines = SalesOrderLineSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.legal_name", read_only=True)

    class Meta:
        model = SalesOrder
        fields = [
            "id",
            "tenant",
            "order_number",
            "branch",
            "source_quotation",
            "customer",
            "delivery_address",
            "customer_po_reference",
            "currency",
            "order_date",
            "requested_delivery_date",
            "priority",
            "fulfilment_policy",
            "substitution_policy",
            "invoice_policy",
            "payment_terms_snapshot",
            "subtotal",
            "tax_total",
            "total",
            "status",
            "hold_reason",
            "cancellation_reason",
            "salesperson",
            "approved_by",
            "approved_at",
            "created_at",
            "updated_at",
            "lines",
            "customer_name",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class SalesOrderHoldSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOrderHold
        fields = [
            "id",
            "tenant",
            "sales_order",
            "hold_type",
            "reason",
            "placed_by",
            "placed_at",
            "released_by",
            "released_at",
            "release_reason",
            "supporting_document",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "created_at", "updated_at"]


class SalesOrderAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOrderAllocation
        fields = [
            "id",
            "tenant",
            "sales_order_line",
            "inventory_reservation",
            "inventory_batch",
            "location",
            "quantity",
            "expiry_date",
            "allocation_timestamp",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class SubstitutionProposalSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubstitutionProposal
        fields = [
            "id",
            "tenant",
            "sales_order_line",
            "requested_sku",
            "proposed_sku",
            "substitution_group",
            "reason",
            "price_variance",
            "approver",
            "customer_consent",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class PickingWaveSerializer(serializers.ModelSerializer):
    class Meta:
        model = PickingWave
        fields = ["id", "tenant", "branch", "wave_number", "scope", "status", "created_by", "created_at", "updated_at"]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class PickingTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = PickingTask
        fields = [
            "id",
            "tenant",
            "picking_wave",
            "sales_order",
            "sales_order_line",
            "allocation",
            "source_location",
            "sku",
            "batch",
            "requested_quantity",
            "picked_quantity",
            "short_quantity",
            "status",
            "assigned_picker",
            "started_at",
            "completed_at",
            "exception_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class PackingSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackingSession
        fields = [
            "id",
            "tenant",
            "branch",
            "session_number",
            "sales_order",
            "status",
            "packer",
            "verifier",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class PackageLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackageLine
        fields = [
            "id",
            "tenant",
            "package",
            "sales_order_line",
            "picking_task",
            "sku",
            "batch",
            "quantity",
            "unit",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "created_at", "updated_at"]


class PackageSerializer(serializers.ModelSerializer):
    lines = PackageLineSerializer(many=True, read_only=True)

    class Meta:
        model = Package
        fields = [
            "id",
            "tenant",
            "packing_session",
            "package_number",
            "sales_order",
            "delivery_address",
            "temperature_zone",
            "package_type",
            "seal_number",
            "gross_weight",
            "dimensions",
            "packer",
            "verifier",
            "packed_at",
            "status",
            "created_at",
            "updated_at",
            "lines",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class DispatchLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchLine
        fields = [
            "id",
            "tenant",
            "dispatch_order",
            "sales_order_line",
            "package",
            "source_location",
            "sku",
            "batch",
            "quantity",
            "unit",
            "idempotency_key",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "created_at", "updated_at"]


class DispatchPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchPackage
        fields = ["id", "tenant", "dispatch_order", "package", "loaded_at", "loaded_by", "created_at", "updated_at"]
        read_only_fields = ["id", "tenant", "created_at", "updated_at"]


class DispatchOrderSerializer(serializers.ModelSerializer):
    lines = DispatchLineSerializer(many=True, read_only=True)
    packages = DispatchPackageSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.legal_name", read_only=True)

    class Meta:
        model = DispatchOrder
        fields = [
            "id",
            "tenant",
            "dispatch_number",
            "branch",
            "sales_order",
            "warehouse",
            "customer",
            "delivery_address",
            "carrier",
            "vehicle",
            "driver",
            "temperature_requirement",
            "dispatch_date",
            "expected_delivery_date",
            "status",
            "created_by",
            "approved_by",
            "dispatched_by",
            "created_at",
            "updated_at",
            "lines",
            "packages",
            "customer_name",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class DeliveryLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryLine
        fields = [
            "id",
            "tenant",
            "delivery_record",
            "dispatch_line",
            "sales_order_line",
            "sku",
            "batch",
            "dispatched_quantity",
            "accepted_quantity",
            "rejected_quantity",
            "damaged_quantity",
            "missing_quantity",
            "return_quantity",
            "reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "created_at", "updated_at"]


class DeliveryRecordSerializer(serializers.ModelSerializer):
    lines = DeliveryLineSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.legal_name", read_only=True)

    class Meta:
        model = DeliveryRecord
        fields = [
            "id",
            "tenant",
            "dispatch_order",
            "customer",
            "delivery_address",
            "status",
            "delivered_at",
            "recipient_name",
            "recipient_role",
            "recipient_phone",
            "proof_type",
            "signature_ref",
            "photo_ref",
            "coordinates",
            "temperature_evidence",
            "delivery_notes",
            "failure_reason",
            "idempotency_key",
            "recorded_by",
            "created_at",
            "updated_at",
            "lines",
            "customer_name",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


class SalesReturnLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesReturnLine
        fields = [
            "id",
            "tenant",
            "return_authorization",
            "sales_order_line",
            "sku",
            "batch",
            "quantity",
            "condition",
            "temperature_evidence",
            "expiry_check",
            "recall_context",
            "return_eligibility",
            "quality_disposition",
            "received_quantity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "created_at", "updated_at"]


class SalesReturnAuthorizationSerializer(serializers.ModelSerializer):
    lines = SalesReturnLineSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.legal_name", read_only=True)

    class Meta:
        model = SalesReturnAuthorization
        fields = [
            "id",
            "tenant",
            "return_number",
            "sales_order",
            "customer",
            "status",
            "reason",
            "requested_by",
            "approved_by",
            "idempotency_key",
            "created_at",
            "updated_at",
            "lines",
            "customer_name",
        ]
        read_only_fields = ["id", "tenant", "status", "created_at", "updated_at"]


# ── origination ──────────────────────────────────────────────────────────────
#
# Creating a quotation, an order or a return goes through a service. These carry
# only what the caller supplies; everything derived -- numbering, pricing,
# totals, status -- is the service's to decide.


class QuotationCreateSerializer(serializers.Serializer):
    branch = serializers.UUIDField()
    customer = serializers.UUIDField()
    currency = serializers.CharField(max_length=3, required=False, default="KES")
    customer_reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    terms = serializers.CharField(required=False, allow_blank=True, default="")
    valid_until = serializers.DateField(required=False, allow_null=True, default=None)


class SalesOrderCreateSerializer(serializers.Serializer):
    branch = serializers.UUIDField()
    customer = serializers.UUIDField()
    currency = serializers.CharField(max_length=3, required=False, default="KES")
    customer_po_reference = serializers.CharField(required=False, allow_blank=True, default="")
    requested_delivery_date = serializers.DateField(required=False, allow_null=True, default=None)
    fulfilment_policy = serializers.CharField(required=False, default="ALLOW_PARTIAL")
    #: Governs whether a dispensed item may be swapped. Not a display preference.
    substitution_policy = serializers.CharField(required=False, default="NO_SUBSTITUTION")
    invoice_policy = serializers.CharField(required=False, default="ON_DISPATCH")
    source_quotation = serializers.UUIDField(required=False, allow_null=True, default=None)


class OrderLineCreateSerializer(serializers.Serializer):
    sku = serializers.UUIDField()
    requested_quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    unit = serializers.CharField(max_length=32, required=False, default="each")


class SubstitutionProposeSerializer(serializers.Serializer):
    sales_order_line = serializers.UUIDField()
    proposed_sku = serializers.UUIDField()
    #: Required. A substitution with no stated reason cannot be reviewed.
    reason = serializers.CharField()


class SalesReturnRequestSerializer(serializers.Serializer):
    sales_order = serializers.UUIDField()
    reason = serializers.CharField()
