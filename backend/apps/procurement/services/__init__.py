from .procurement_service import ProcurementService
from .quality_service import QualityService
from .receiving_service import ReceivingService
from .returns_service import SupplierReturnService
from .supplier_governance_service import SupplierGovernanceService, SupplierNotQualified
from .three_way_match_service import ProcurementMatchingService, ThreeWayMatchService

# Service aliases for viewsets and existing callers
BatchReceivingService = ReceivingService
GoodsReceivingService = ReceivingService
PurchaseOrderService = ProcurementService
PurchaseRequisitionService = ProcurementService
SupplierQualificationService = ProcurementService
# Inspection is quality work; the name follows the workflow it is called from.
ReceivingInspectionService = QualityService

__all__ = [
    "ProcurementService",
    "ReceivingService",
    "QualityService",
    "ThreeWayMatchService",
    "BatchReceivingService",
    "GoodsReceivingService",
    "PurchaseOrderService",
    "PurchaseRequisitionService",
    "SupplierGovernanceService",
    "SupplierNotQualified",
    "SupplierQualificationService",
    "ReceivingInspectionService",
    "SupplierReturnService",
    "ProcurementMatchingService",
]
