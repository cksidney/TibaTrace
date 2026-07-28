from rest_framework import serializers

from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    PurchaseRequisitionLine,
    QualityDecision,
    ReceivedBatch,
    ReceivingInspection,
    ReceivingScan,
    ReceivingSession,
    RequestForQuotation,
    RFQLine,
    Supplier,
    SupplierProductAgreement,
    SupplierQualification,
    SupplierQuotation,
    SupplierQuotationLine,
    SupplierReturn,
    SupplierReturnLine,
    ThreeWayMatch,
)


class SupplierSerializer(serializers.ModelSerializer):
    eligibility_reasons = serializers.SerializerMethodField()
    purchase_eligible = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = [
            "id",
            "supplier_code",
            "legal_name",
            "trading_name",
            "registration_number",
            "tax_identifier",
            "country",
            "address",
            "contact_email",
            "contact_phone",
            "payment_terms",
            "default_currency",
            "status",
            "risk_category",
            "suspension_reason",
            "purchase_eligible",
            "eligibility_reasons",
            "approved_at",
            "approved_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "approved_at", "approved_by", "created_at", "updated_at"]

    def get_eligibility_reasons(self, supplier):
        from apps.procurement.services import SupplierGovernanceService

        cache_name = "_purchase_eligibility_reasons"
        cached = getattr(supplier, cache_name, None)
        if cached is not None:
            return cached

        held_qualifications = None
        annotated_fields = {
            SupplierQualification.QualificationType.BUSINESS_REGISTRATION:
                "has_valid_business_registration",
            SupplierQualification.QualificationType.WHOLESALE_DEALER_LICENCE:
                "has_valid_wholesale_dealer_licence",
        }
        if all(hasattr(supplier, field) for field in annotated_fields.values()):
            held_qualifications = {
                qualification_type
                for qualification_type, field in annotated_fields.items()
                if getattr(supplier, field)
            }

        reasons = SupplierGovernanceService.ineligibility_reasons(
            supplier=supplier,
            held_qualifications=held_qualifications,
        )
        setattr(supplier, cache_name, reasons)
        return reasons

    def get_purchase_eligible(self, supplier):
        return not self.get_eligibility_reasons(supplier)


class SupplierQualificationSerializer(serializers.ModelSerializer):
    supplier_code = serializers.CharField(source="supplier.supplier_code", read_only=True)

    class Meta:
        model = SupplierQualification
        fields = [
            "id",
            "supplier",
            "supplier_code",
            "qualification_type",
            "licence_number",
            "issuing_authority",
            "effective_date",
            "expiry_date",
            "verification_status",
            "document_reference",
            "verified_at",
            "verified_by",
            "created_at",
        ]
        read_only_fields = ["id", "verification_status", "verified_at", "verified_by", "created_at"]


class SupplierProductAgreementSerializer(serializers.ModelSerializer):
    supplier_code = serializers.CharField(source="supplier.supplier_code", read_only=True)
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)

    class Meta:
        model = SupplierProductAgreement
        fields = [
            "id",
            "supplier",
            "supplier_code",
            "sku",
            "sku_code",
            "supplier_catalogue_number",
            "purchase_unit",
            "agreed_unit_price",
            "currency",
            "minimum_order_quantity",
            "lead_time_days",
            "is_preferred",
            "requires_cold_chain",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "status", "created_at"]


class PurchaseRequisitionLineSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)

    class Meta:
        model = PurchaseRequisitionLine
        fields = [
            "id",
            "sku",
            "sku_code",
            "requested_quantity",
            "approved_quantity",
            "outstanding_quantity",
            "purchase_unit",
            "status",
        ]


class PurchaseRequisitionSerializer(serializers.ModelSerializer):
    lines = PurchaseRequisitionLineSerializer(many=True, read_only=True)
    requesting_branch_name = serializers.CharField(source="requesting_branch.name", read_only=True)

    class Meta:
        model = PurchaseRequisition
        fields = [
            "id",
            "requisition_number",
            "requesting_branch",
            "requesting_branch_name",
            "requester",
            "requested_delivery_date",
            "priority",
            "justification",
            "status",
            "approved_at",
            "approved_by",
            "lines",
            "created_at",
        ]
        read_only_fields = ["id", "status", "approved_at", "approved_by", "created_at"]


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = [
            "id",
            "sku",
            "sku_code",
            "ordered_quantity",
            "received_quantity",
            "rejected_quantity",
            "unit_price",
            "total_price",
            "purchase_unit",
            "requires_cold_chain",
        ]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.legal_name", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "po_number",
            "supplier",
            "supplier_name",
            "originating_requisition",
            "ordering_branch",
            "order_date",
            "expected_delivery_date",
            "currency",
            "total_net",
            "total_tax",
            "total_gross",
            "revision_number",
            "status",
            "approved_at",
            "approved_by",
            "lines",
            "created_at",
        ]
        read_only_fields = ["id", "status", "approved_at", "approved_by", "created_at"]


class GoodsReceiptLineSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)

    class Meta:
        model = GoodsReceiptLine
        fields = [
            "id",
            "po_line",
            "sku",
            "sku_code",
            "delivered_quantity",
            "accepted_quantity",
            "quarantined_quantity",
            "rejected_quantity",
            "discrepancy_reason",
        ]


class GoodsReceiptSerializer(serializers.ModelSerializer):
    lines = GoodsReceiptLineSerializer(many=True, read_only=True)

    class Meta:
        model = GoodsReceipt
        fields = [
            "id",
            "grn_number",
            "purchase_order",
            "supplier",
            "receiving_branch",
            "received_by",
            "delivery_note_number",
            "arrival_time",
            "status",
            "discrepancy_summary",
            "lines",
            "created_at",
        ]
        read_only_fields = ["id", "status", "created_at"]


class ReceivedBatchSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)

    class Meta:
        model = ReceivedBatch
        fields = [
            "id",
            "grn_line",
            "sku",
            "sku_code",
            "manufacturer_batch_number",
            "manufacture_date",
            "expiry_date",
            "received_quantity",
            "accepted_quantity",
            "quarantined_quantity",
            "rejected_quantity",
            "quality_status",
            "temperature_excursion",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class ReceivingInspectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceivingInspection
        fields = ["id", "goods_receipt", "inspector", "decision", "reason", "inspected_at"]
        read_only_fields = ["id", "inspected_at"]


class SupplierReturnSerializer(serializers.ModelSerializer):
    lines = serializers.SerializerMethodField()

    class Meta:
        model = SupplierReturn
        fields = [
            "id",
            "return_number",
            "goods_receipt",
            "supplier",
            "status",
            "reason",
            "lines",
            "created_at",
        ]
        read_only_fields = ["id", "status", "created_at"]

    def get_lines(self, supplier_return):
        return [
            {
                "id": str(line.pk),
                "sku": str(line.sku_id),
                "sku_code": line.sku.sku_code,
                "quantity": line.quantity,
            }
            for line in SupplierReturnLine.all_objects.filter(
                tenant_id=supplier_return.tenant_id,
                supplier_return=supplier_return,
            ).select_related("sku")
        ]


class ThreeWayMatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = ThreeWayMatch
        fields = [
            "id",
            "purchase_order",
            "goods_receipt",
            "invoice_reference",
            "matching_status",
            "quantity_variance",
            "price_variance",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class ProcurementLineInputSerializer(serializers.Serializer):
    sku = serializers.UUIDField(required=False)
    requisition_line = serializers.UUIDField(required=False)
    requested_quantity = serializers.IntegerField(min_value=1, required=False)
    quantity = serializers.IntegerField(min_value=1, required=False)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    purchase_unit = serializers.CharField(max_length=64, default="pack")
    requires_cold_chain = serializers.BooleanField(default=False)


class PurchaseRequisitionCreateSerializer(serializers.Serializer):
    requesting_branch = serializers.UUIDField()
    requested_delivery_date = serializers.DateField()
    priority = serializers.ChoiceField(
        choices=["LOW", "NORMAL", "HIGH", "URGENT"],
        default="NORMAL",
    )
    justification = serializers.CharField(max_length=2000)
    lines = ProcurementLineInputSerializer(many=True, allow_empty=False)

    def validate_lines(self, value):
        if any("sku" not in line or "requested_quantity" not in line for line in value):
            raise serializers.ValidationError(
                "Each requisition line requires a SKU and requested quantity."
            )
        return value


class PurchaseOrderCreateSerializer(serializers.Serializer):
    supplier = serializers.UUIDField()
    originating_requisition = serializers.UUIDField(required=False, allow_null=True)
    ordering_branch = serializers.UUIDField()
    order_date = serializers.DateField(required=False)
    expected_delivery_date = serializers.DateField()
    currency = serializers.CharField(max_length=3, default="KES")
    lines = ProcurementLineInputSerializer(many=True, allow_empty=False)

    def validate_lines(self, value):
        for line in value:
            if "unit_cost" not in line:
                raise serializers.ValidationError(
                    "Each purchase-order line requires a unit cost."
                )
            if "requisition_line" not in line and (
                "sku" not in line or "quantity" not in line
            ):
                raise serializers.ValidationError(
                    "Manual purchase-order lines require a SKU and quantity."
                )
        return value


class GoodsReceiptCreateSerializer(serializers.Serializer):
    purchase_order = serializers.UUIDField()
    receiving_branch = serializers.UUIDField()
    delivery_note_number = serializers.CharField(max_length=128)


class ReceiveBatchSerializer(serializers.Serializer):
    po_line = serializers.UUIDField()
    manufacturer_batch_number = serializers.CharField(max_length=128)
    manufacture_date = serializers.DateField(required=False, allow_null=True)
    expiry_date = serializers.DateField()
    received_quantity = serializers.IntegerField(min_value=1)
    discrepancy_reason = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        default="",
    )
    idempotency_key = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        default="",
    )


class ReceivingInspectionCreateSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=["RELEASE", "QUARANTINE", "REJECT", "HOLD_FOR_INVESTIGATION", "DESTROY"]
    )
    reason = serializers.CharField(max_length=2000)
    temperature_excursion = serializers.BooleanField(default=False)


class BatchReleaseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000)
    quantity = serializers.IntegerField(min_value=1, required=False)
    inventory_location = serializers.UUIDField(required=False)


class SupplierReturnCreateSerializer(serializers.Serializer):
    return_number = serializers.CharField(max_length=64)
    goods_receipt = serializers.UUIDField()
    reason = serializers.CharField(max_length=2000)
    lines = ProcurementLineInputSerializer(many=True, allow_empty=False)

    def validate_lines(self, value):
        if any("sku" not in line or "quantity" not in line for line in value):
            raise serializers.ValidationError("Each return line requires a SKU and quantity.")
        return value


class ThreeWayMatchCreateSerializer(serializers.Serializer):
    purchase_order = serializers.UUIDField()
    goods_receipt = serializers.UUIDField()
    invoice_reference = serializers.CharField(max_length=128)
    invoice_amount = serializers.DecimalField(max_digits=14, decimal_places=2)

# ── competitive sourcing ─────────────────────────────────────────────────────


class RFQLineSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)

    class Meta:
        model = RFQLine
        fields = ("id", "sku", "sku_code", "requested_quantity")


class RequestForQuotationSerializer(serializers.ModelSerializer):
    lines = RFQLineSerializer(many=True, read_only=True)
    quotation_count = serializers.SerializerMethodField()

    class Meta:
        model = RequestForQuotation
        fields = (
            "id", "rfq_number", "title", "issue_date", "closing_date",
            "status", "lines", "quotation_count",
        )
        read_only_fields = fields

    def get_quotation_count(self, rfq) -> int:
        return SupplierQuotation.all_objects.filter(rfq=rfq).count()


class SupplierQuotationLineSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)

    class Meta:
        model = SupplierQuotationLine
        fields = ("id", "sku", "sku_code", "quoted_quantity", "quoted_unit_cost")


class SupplierQuotationSerializer(serializers.ModelSerializer):
    lines = SupplierQuotationLineSerializer(many=True, read_only=True)
    supplier_code = serializers.CharField(source="supplier.supplier_code", read_only=True)

    class Meta:
        model = SupplierQuotation
        fields = (
            "id", "rfq", "supplier", "supplier_code", "quotation_reference",
            "total_quoted_cost", "valid_until", "status", "lines",
        )
        read_only_fields = fields


class RFQCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    closing_date = serializers.DateField()
    lines = serializers.ListField(child=serializers.DictField(), allow_empty=False)


class QuotationSubmitSerializer(serializers.Serializer):
    supplier_id = serializers.UUIDField()
    quotation_reference = serializers.CharField(max_length=120)
    #: Required. A quoted price with no expiry is one the supplier can disown.
    valid_until = serializers.DateField()
    lines = serializers.ListField(child=serializers.DictField(), allow_empty=False)


class QuotationAwardSerializer(serializers.Serializer):
    quotation_id = serializers.UUIDField()
    #: Required by the service when the award is above the lowest quotation.
    justification = serializers.CharField(required=False, allow_blank=True, default="")


# ── scan-based receiving and quality decisions ───────────────────────────────


class ReceivingScanSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)

    class Meta:
        model = ReceivingScan
        fields = (
            "id", "sku", "sku_code", "scanned_barcode", "batch_number",
            "expiry_date", "scanned_quantity",
        )


class ReceivingSessionSerializer(serializers.ModelSerializer):
    scans = ReceivingScanSerializer(many=True, read_only=True)
    supplier_code = serializers.CharField(source="supplier.supplier_code", read_only=True)
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True)

    class Meta:
        model = ReceivingSession
        fields = (
            "id", "session_number", "purchase_order", "po_number", "supplier",
            "supplier_code", "branch", "delivery_note_number", "status", "scans",
        )
        read_only_fields = fields


class ReceivingSessionOpenSerializer(serializers.Serializer):
    purchase_order = serializers.UUIDField()
    branch = serializers.UUIDField()
    delivery_note_number = serializers.CharField(max_length=120)


class ReceivingScanCreateSerializer(serializers.Serializer):
    sku_id = serializers.UUIDField()
    scanned_barcode = serializers.CharField(max_length=120, allow_blank=True, default="")
    batch_number = serializers.CharField(max_length=120)
    #: Required. The service refuses a batch that has already expired.
    expiry_date = serializers.DateField()
    scanned_quantity = serializers.DecimalField(max_digits=14, decimal_places=2)


class PostGoodsReceiptSerializer(serializers.Serializer):
    destination_location = serializers.UUIDField()


class QualityDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QualityDecision
        fields = "__all__"


class QuarantineReleaseSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField()
    #: Releasing quarantined stock is a decision somebody owns, so it is stated.
    decision_notes = serializers.CharField()
