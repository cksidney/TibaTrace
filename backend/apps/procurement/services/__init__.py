"""Procurement domain services.

Some names here are genuine aliases -- one implementation reached from two
workflows -- and some are distinct services. The difference matters: aliasing a
name to the wrong class produces an AttributeError at the first real call, which
is what happened when SupplierGovernanceService was pointed at ProcurementService
and every supplier test failed on a missing create_supplier.

PurchaseOrderLine is re-exported because the concurrency tests patch
select_for_update through this module's namespace.
"""
from apps.procurement.models import PurchaseOrderLine

from .procurement_service import ProcurementService
from .quality_service import QualityService
from .receiving_service import GoodsReceivingService, ReceivingService
from .returns_service import SupplierReturnService
from .sourcing_service import SourcingService
from .supplier_agreement_service import SupplierProductAgreementService
from .supplier_governance_service import SupplierGovernanceService, SupplierNotQualified
from .supplier_site_service import SupplierSiteService
from .three_way_match_service import ProcurementMatchingService, ThreeWayMatchService

# Genuine aliases: the same implementation reached from a differently-named
# workflow. Batch receiving and goods receiving are the same document flow.
BatchReceivingService = GoodsReceivingService
# Requisitions and purchase orders are both ProcurementService's responsibility.
PurchaseOrderService = ProcurementService
PurchaseRequisitionService = ProcurementService
# Inspection is quality work, named for the workflow it is called from.
ReceivingInspectionService = QualityService
# Qualification is part of supplier governance, not of ordering.
SupplierQualificationService = SupplierGovernanceService

__all__ = [
    "BatchReceivingService",
    "GoodsReceivingService",
    "ProcurementMatchingService",
    "ProcurementService",
    "PurchaseOrderLine",
    "PurchaseOrderService",
    "PurchaseRequisitionService",
    "QualityService",
    "ReceivingInspectionService",
    "ReceivingService",
    "SupplierGovernanceService",
    "SourcingService",
    "SupplierNotQualified",
    "SupplierProductAgreementService",
    "SupplierSiteService",
    "SupplierQualificationService",
    "SupplierReturnService",
    "ThreeWayMatchService",
]
