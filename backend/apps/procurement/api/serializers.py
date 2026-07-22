from rest_framework import serializers

from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    PurchaseRequisitionLine,
    ReceivedBatch,
    ReceivingInspection,
    Supplier,
    SupplierProductAgreement,
    SupplierQualification,
    SupplierReturn,
    ThreeWayMatch,
)


class SupplierSerializer(serializers.ModelSerializer):
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
            "approved_at",
            "approved_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "approved_at", "approved_by", "created_at", "updated_at"]


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
    class Meta:
        model = SupplierReturn
        fields = ["id", "return_number", "goods_receipt", "supplier", "status", "reason", "created_at"]
        read_only_fields = ["id", "status", "created_at"]


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
