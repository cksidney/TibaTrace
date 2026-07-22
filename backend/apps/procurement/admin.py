from django.contrib import admin

from apps.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderRevision,
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


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["supplier_code", "legal_name", "country", "status", "risk_category", "tenant"]
    list_filter = ["status", "risk_category", "country"]
    search_fields = ["supplier_code", "legal_name", "registration_number"]


@admin.register(SupplierQualification)
class SupplierQualificationAdmin(admin.ModelAdmin):
    list_display = ["supplier", "qualification_type", "licence_number", "expiry_date", "verification_status"]
    list_filter = ["verification_status", "qualification_type"]


@admin.register(SupplierProductAgreement)
class SupplierProductAgreementAdmin(admin.ModelAdmin):
    list_display = ["supplier", "sku", "agreed_unit_price", "currency", "status"]
    list_filter = ["status", "currency"]


class PurchaseRequisitionLineInline(admin.TabularInline):
    model = PurchaseRequisitionLine
    extra = 1


@admin.register(PurchaseRequisition)
class PurchaseRequisitionAdmin(admin.ModelAdmin):
    list_display = ["requisition_number", "requesting_branch", "requester", "priority", "status"]
    list_filter = ["status", "priority"]
    inlines = [PurchaseRequisitionLineInline]


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 1


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ["po_number", "supplier", "ordering_branch", "total_gross", "status", "revision_number"]
    list_filter = ["status", "currency"]
    inlines = [PurchaseOrderLineInline]


@admin.register(PurchaseOrderRevision)
class PurchaseOrderRevisionAdmin(admin.ModelAdmin):
    list_display = ["purchase_order", "revision_number", "actor", "created_at"]


class GoodsReceiptLineInline(admin.TabularInline):
    model = GoodsReceiptLine
    extra = 1


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(admin.ModelAdmin):
    list_display = ["grn_number", "purchase_order", "supplier", "receiving_branch", "status", "arrival_time"]
    list_filter = ["status"]
    inlines = [GoodsReceiptLineInline]


@admin.register(ReceivedBatch)
class ReceivedBatchAdmin(admin.ModelAdmin):
    list_display = ["manufacturer_batch_number", "sku", "expiry_date", "received_quantity", "quality_status"]
    list_filter = ["quality_status", "temperature_excursion"]
    search_fields = ["manufacturer_batch_number", "sku__sku_code"]


@admin.register(ReceivingInspection)
class ReceivingInspectionAdmin(admin.ModelAdmin):
    list_display = ["goods_receipt", "inspector", "decision", "inspected_at"]
    list_filter = ["decision"]


@admin.register(SupplierReturn)
class SupplierReturnAdmin(admin.ModelAdmin):
    list_display = ["return_number", "supplier", "goods_receipt", "status"]
    list_filter = ["status"]


@admin.register(ThreeWayMatch)
class ThreeWayMatchAdmin(admin.ModelAdmin):
    list_display = ["purchase_order", "goods_receipt", "invoice_reference", "matching_status"]
    list_filter = ["matching_status"]
