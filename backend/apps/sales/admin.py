from django.contrib import admin

from .models import (
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


@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin):
    pass


@admin.register(PriceListEntry)
class PriceListEntryAdmin(admin.ModelAdmin):
    pass


@admin.register(CustomerPriceAgreement)
class CustomerPriceAgreementAdmin(admin.ModelAdmin):
    pass


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    pass


@admin.register(QuotationLine)
class QuotationLineAdmin(admin.ModelAdmin):
    pass


@admin.register(QuotationRevision)
class QuotationRevisionAdmin(admin.ModelAdmin):
    pass


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    pass


@admin.register(SalesOrderLine)
class SalesOrderLineAdmin(admin.ModelAdmin):
    pass


@admin.register(SalesOrderHold)
class SalesOrderHoldAdmin(admin.ModelAdmin):
    pass


@admin.register(SalesOrderAllocation)
class SalesOrderAllocationAdmin(admin.ModelAdmin):
    pass


@admin.register(SubstitutionProposal)
class SubstitutionProposalAdmin(admin.ModelAdmin):
    pass


@admin.register(PickingWave)
class PickingWaveAdmin(admin.ModelAdmin):
    pass


@admin.register(PickingTask)
class PickingTaskAdmin(admin.ModelAdmin):
    pass


@admin.register(PackingSession)
class PackingSessionAdmin(admin.ModelAdmin):
    pass


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    pass


@admin.register(PackageLine)
class PackageLineAdmin(admin.ModelAdmin):
    pass


@admin.register(DispatchOrder)
class DispatchOrderAdmin(admin.ModelAdmin):
    pass


@admin.register(DispatchLine)
class DispatchLineAdmin(admin.ModelAdmin):
    pass


@admin.register(DispatchPackage)
class DispatchPackageAdmin(admin.ModelAdmin):
    pass


@admin.register(DeliveryRecord)
class DeliveryRecordAdmin(admin.ModelAdmin):
    pass


@admin.register(DeliveryLine)
class DeliveryLineAdmin(admin.ModelAdmin):
    pass


@admin.register(SalesReturnAuthorization)
class SalesReturnAuthorizationAdmin(admin.ModelAdmin):
    pass


@admin.register(SalesReturnLine)
class SalesReturnLineAdmin(admin.ModelAdmin):
    pass
