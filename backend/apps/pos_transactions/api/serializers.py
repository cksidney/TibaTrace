from __future__ import annotations

from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.money import format_decimal, format_money
from apps.pos_transactions.models import (
    PosTransaction,
    PosTransactionInventoryContext,
    PosTransactionLine,
    RetailCashReceipt,
    RetailCashRefund,
    RetailRefundLine,
    RetailRefundRequest,
)


class MoneyField(serializers.Field):
    def to_representation(self, value):
        if value is None:
            return None
        return format_money(value)


class PosTransactionInventoryContextSerializer(serializers.ModelSerializer):
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = PosTransactionInventoryContext
        fields = ["store", "available_quantity", "stock_state", "policy"]

    def get_available_quantity(self, row):
        return format_decimal(row.available_quantity, places=2)


class PosTransactionLineSerializer(serializers.ModelSerializer):
    unit_price = MoneyField()
    discount_amount = MoneyField()
    tax_amount = MoneyField()
    line_total = MoneyField()
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    inventory_context = PosTransactionInventoryContextSerializer(read_only=True)
    refundable_quantity = serializers.SerializerMethodField()
    issued_batches = serializers.SerializerMethodField()

    class Meta:
        model = PosTransactionLine
        fields = [
            "id", "sku", "sku_code", "description_snapshot", "unit", "quantity",
            "unit_price", "discount_amount", "tax_amount", "line_total", "currency",
            "price_snapshot", "scan_source", "inventory_context", "refundable_quantity", "issued_batches",
        ]

    def get_refundable_quantity(self, line):
        from django.db.models import Sum
        reserved = RetailRefundLine.all_objects.filter(tenant_id=line.tenant_id, original_line=line,
            refund_request__status__in=["REQUESTED", "APPROVED", "COMPLETED"]).aggregate(q=Sum("quantity"))["q"] or 0
        return str(max(line.quantity - reserved, Decimal("0")))

    @staticmethod
    def get_issued_batches(line):
        from apps.inventory.models import InventoryLedgerEntry
        rows = InventoryLedgerEntry.all_objects.filter(tenant_id=line.tenant_id, source_document_type="POS_RETAIL_TRANSACTION",
            source_document_id=str(line.transaction_id), source_line_id=str(line.pk), entry_type="ISSUE").select_related("inventory_batch")
        return [{"batch_id": str(row.inventory_batch_id), "batch_number": row.inventory_batch.manufacturer_batch_number,
                 "expiry_date": str(row.inventory_batch.expiry_date), "quantity": str(-row.base_quantity_delta)} for row in rows if row.inventory_batch_id]


class RetailCashRefundSerializer(serializers.ModelSerializer):
    fiscal = serializers.SerializerMethodField()
    amount = MoneyField()
    original_receipt_number = serializers.CharField(source="original_receipt.receipt_number", read_only=True)
    print_job = serializers.SerializerMethodField()

    class Meta:
        model = RetailCashRefund
        fields = ["id", "refund_number", "original_receipt_number", "refund_request", "amount", "cash_amount", "payment_plan", "currency",
                  "completed_at", "register_session", "created_by", "approved_by", "lines_snapshot", "print_job", "fiscal"]

    @staticmethod
    def get_fiscal(receipt):
        from apps.prescription.fiscal import FiscalService
        return FiscalService.status(receipt)

    @staticmethod
    def get_print_job(receipt):
        from apps.prescription.pos_printing_models import PosPrintJob
        row = PosPrintJob.all_objects.filter(tenant_id=receipt.tenant_id, document__document_number=receipt.refund_number,
            copy_classification="ORIGINAL").values("id", "status", "transport").first()
        return {"id": str(row["id"]), "status": row["status"], "transport": row["transport"]} if row else None


class RetailRefundLineSerializer(serializers.ModelSerializer):
    amount = MoneyField()
    description = serializers.CharField(source="original_line.description_snapshot", read_only=True)

    class Meta:
        model = RetailRefundLine
        fields = ["id", "original_line", "description", "quantity", "amount", "return_to_stock", "inventory_batch"]


class RetailRefundRequestSerializer(serializers.ModelSerializer):
    amount = MoneyField()
    lines = serializers.SerializerMethodField()
    receipt = RetailCashRefundSerializer(read_only=True)

    class Meta:
        model = RetailRefundRequest
        fields = ["id", "status", "reason", "amount", "currency", "return_location", "requested_by", "approved_by",
                  "reviewed_at", "review_reason", "created_at", "lines", "receipt", "payment_plan"]

    @staticmethod
    def get_lines(request):
        rows = RetailRefundLine.all_objects.filter(tenant_id=request.tenant_id, refund_request=request).select_related("original_line")
        return RetailRefundLineSerializer(rows, many=True).data


class RetailCashReceiptSerializer(serializers.ModelSerializer):
    # The persisted receipt is cash-only. Emit a scalar here instead of a
    # one-value generated enum so it cannot rename the existing shared
    # PaymentTender.tender_type enum in the OpenAPI contract.
    tender_type = serializers.CharField(
        read_only=True,
        help_text="Cash-only receipt; this value is always CASH.",
    )
    amount = MoneyField()
    cash_received = MoneyField()
    change_due = MoneyField()
    disclaimer = serializers.SerializerMethodField()
    print_job = serializers.SerializerMethodField()
    fiscal_receipt = serializers.SerializerMethodField()

    class Meta:
        model = RetailCashReceipt
        fields = [
            "receipt_number", "tender_type", "amount", "cash_received", "change_due", "currency",
            "lines_snapshot", "totals_snapshot", "settled_at", "disclaimer", "print_job", "fiscal_receipt",
        ]

    @staticmethod
    def get_fiscal_receipt(receipt):
        from apps.taxation.models import FiscalReceipt

        fiscal = FiscalReceipt.all_objects.filter(
            tenant_id=receipt.tenant_id,
            retail_cash_receipt=receipt,
        ).first()
        if fiscal is None:
            return None
        return {
            "invoice_number": fiscal.invoice_number,
            "receipt_signature": fiscal.receipt_signature,
            "internal_data": fiscal.internal_data,
            "qr_code_url": fiscal.qr_code_url,
            "qr_code_svg": fiscal.qr_code_image_data,
            "submission_status": fiscal.submission_status,
        }

    @staticmethod
    def get_disclaimer(receipt):
        from apps.taxation.models import FiscalReceipt

        fiscal = FiscalReceipt.all_objects.filter(
            tenant_id=receipt.tenant_id,
            retail_cash_receipt=receipt,
        ).first()
        if fiscal and fiscal.submission_status in {"SUBMITTED", "OFFLINE_GENERATED"}:
            return "KRA eTIMS FISCAL RECEIPT"
        if fiscal and fiscal.submission_status in {"PENDING", "FAILED"}:
            return "Internal sales receipt — pending eTIMS fiscalization."
        return "Internal sales receipt — not a fiscal/eTIMS receipt."

    @staticmethod
    def get_print_job(receipt):
        from apps.prescription.pos_printing_models import PosPrintDocument, PosPrintJob

        job = PosPrintJob.all_objects.filter(
            tenant_id=receipt.tenant_id,
            document__document_number=receipt.receipt_number,
            document__document_type=PosPrintDocument.DocumentType.RETAIL_RECEIPT,
            copy_classification=PosPrintJob.CopyClassification.ORIGINAL,
        ).values("id", "status", "transport").first()
        if job is None:
            return None
        return {"id": str(job["id"]), "status": job["status"], "transport": job["transport"]}


class PosTransactionSerializer(serializers.ModelSerializer):
    subtotal = MoneyField()
    discount_total = MoneyField()
    tax_total = MoneyField()
    total = MoneyField()
    branch_code = serializers.CharField(source="branch.code", read_only=True)
    register_code = serializers.CharField(source="register.code", read_only=True)
    operator_username = serializers.CharField(source="operator.username", read_only=True)
    lines = serializers.SerializerMethodField()
    receipt = RetailCashReceiptSerializer(source="cash_receipt", read_only=True)
    refund_requests = serializers.SerializerMethodField()
    refunded_total = serializers.SerializerMethodField()

    class Meta:
        model = PosTransaction
        fields = [
            "id", "transaction_number", "state", "channel", "branch", "branch_code",
            "store", "register", "register_code", "register_session", "operator_shift",
            "business_day", "operator", "operator_username", "device_id", "customer", "patient",
            "currency", "subtotal", "discount_total", "tax_total", "total", "hold_reason",
            "held_at", "cancelled_at", "cancellation_reason", "created_at", "updated_at", "lines", "receipt", "refund_requests", "refunded_total",
        ]

    @staticmethod
    @extend_schema_field(PosTransactionLineSerializer(many=True))
    def get_lines(sale):
        # POST responses are sometimes serialized after tenant context has been
        # cleared (and direct service callers have none). Never rely on an
        # implicit tenant-strict reverse manager for an authoritative receipt.
        rows = PosTransactionLine.all_objects.filter(tenant_id=sale.tenant_id, transaction=sale).select_related("sku", "inventory_context").order_by("created_at", "pk")
        return PosTransactionLineSerializer(rows, many=True).data

    @staticmethod
    def get_refund_requests(sale):
        rows = RetailRefundRequest.all_objects.filter(tenant_id=sale.tenant_id, transaction=sale).order_by("created_at")
        return RetailRefundRequestSerializer(rows, many=True).data

    @staticmethod
    def get_refunded_total(sale):
        from django.db.models import Sum
        amount = RetailCashRefund.all_objects.filter(tenant_id=sale.tenant_id, original_receipt__transaction=sale).aggregate(a=Sum("amount"))["a"] or 0
        return format_money(amount)


class CreateDraftRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    store_id = serializers.UUIDField()
    customer_id = serializers.UUIDField(required=False, allow_null=True)
    patient_id = serializers.UUIDField(required=False, allow_null=True)


class CatalogueSearchRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    store_id = serializers.UUIDField()
    query = serializers.CharField(max_length=255)
    customer_id = serializers.UUIDField(required=False, allow_null=True)


class AddLineRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    sku_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=Decimal("0.0001"))


class ScanRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    barcode = serializers.CharField(max_length=255)
    quantity = serializers.DecimalField(
        max_digits=15, decimal_places=4, min_value=Decimal("0.0001"), default=Decimal("1")
    )


class SetQuantityRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    line_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=Decimal("0.0001"))


class RemoveLineRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    line_id = serializers.UUIDField()


class DeviceActionRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)


class CashSettlementRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    cash_received = serializers.DecimalField(max_digits=15, decimal_places=2, min_value=Decimal("0.01"))
    idempotency_key = serializers.CharField(max_length=255, allow_blank=False, trim_whitespace=True)
    tender_type = serializers.ChoiceField(choices=(("CASH", "Cash"),), default="CASH")


class HoldRequestSerializer(DeviceActionRequestSerializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class CancelRequestSerializer(DeviceActionRequestSerializer):
    reason = serializers.CharField()


class RefundLineRequestSerializer(serializers.Serializer):
    line_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=Decimal("0.0001"))
    return_to_stock = serializers.BooleanField(default=False)
    inventory_batch_id = serializers.UUIDField(required=False, allow_null=True)


class RefundRequestSerializer(DeviceActionRequestSerializer):
    reason = serializers.CharField(allow_blank=False)
    idempotency_key = serializers.CharField(max_length=255, allow_blank=False)
    return_location_id = serializers.UUIDField(required=False, allow_null=True)
    lines = RefundLineRequestSerializer(many=True, allow_empty=False)


class RefundReviewSerializer(serializers.Serializer):
    refund_request_id = serializers.UUIDField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class CashRefundRequestSerializer(DeviceActionRequestSerializer):
    payment_references = serializers.DictField(child=serializers.CharField(max_length=128, allow_blank=False), default=dict)
    refund_request_id = serializers.UUIDField()
    idempotency_key = serializers.CharField(max_length=255, allow_blank=False)


class RetailCatalogueItemSerializer(serializers.Serializer):
    sku_id = serializers.UUIDField(source="sku.pk")
    sku_code = serializers.CharField(source="sku.sku_code")
    display_name = serializers.CharField(source="sku.display_name")
    unit = serializers.CharField(source="sku.package_definition.unit_of_measure")
    stock_tracking_required = serializers.BooleanField(source="sku.stock_tracking_required")
    available_quantity = serializers.DecimalField(max_digits=15, decimal_places=4)
    stock_state = serializers.CharField()
    unit_price = serializers.DecimalField(source="resolved_price.unit_price", max_digits=15, decimal_places=2)
    currency = serializers.CharField(source="resolved_price.currency")
    price_source = serializers.CharField(source="resolved_price.source")
    price_reference = serializers.CharField(source="resolved_price.reference")
