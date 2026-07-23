from django.contrib import admin

from apps.inventory.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryReservation,
    StocktakeSession,
    StockTransfer,
)


@admin.register(InventoryLocation)
class InventoryLocationAdmin(admin.ModelAdmin):
    list_display = ("name", "location_code", "branch", "location_type", "status")
    search_fields = ("name", "location_code")
    list_filter = ("location_type", "status", "tenant")

@admin.register(InventoryBatch)
class InventoryBatchAdmin(admin.ModelAdmin):
    list_display = ("manufacturer_batch_number", "sku", "expiry_date", "quality_status")
    search_fields = ("manufacturer_batch_number",)
    list_filter = ("quality_status", "recall_status", "tenant")

@admin.register(InventoryLedgerEntry)
class InventoryLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("transaction_timestamp", "entry_type", "location", "sku", "quantity_delta", "unit")
    list_filter = ("entry_type", "tenant", "branch")
    search_fields = ("source_document_id", "idempotency_key", "sku__display_name")
    
    def has_add_permission(self, request):
        return False
        
    def has_change_permission(self, request, obj=None):
        return False
        
    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(InventoryBalance)
class InventoryBalanceAdmin(admin.ModelAdmin):
    list_display = ("location", "sku", "inventory_batch", "on_hand", "available")
    list_filter = ("quality_status", "expiry_status", "tenant", "branch")
    search_fields = ("sku__display_name",)
    
    def has_add_permission(self, request):
        return False
        
    def has_change_permission(self, request, obj=None):
        return False
        
    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(InventoryReservation)
class InventoryReservationAdmin(admin.ModelAdmin):
    list_display = ("sku", "source_location", "requested_quantity", "allocated_quantity", "status")
    list_filter = ("status", "tenant")

@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = ("transfer_number", "source_location", "destination_location", "status")
    list_filter = ("status", "tenant")

@admin.register(StocktakeSession)
class StocktakeSessionAdmin(admin.ModelAdmin):
    list_display = ("branch", "scope", "status", "start_time")
    list_filter = ("status", "tenant")
