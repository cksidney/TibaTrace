# Mercato Procurement & Supplier Crosswalk Lineage

## Overview

Mercato legacy procurement, supplier, purchase order, receiving note, and supplier invoice records are linked into DawaTrace using passive `LegacyIdentifierCrosswalk` mappings in `apps/crosswalks`.

## Entity Crosswalk Mappings
* `MercatoSupplierID` -> `procurement.Supplier.id`
* `MercatoPurchaseOrderID` -> `procurement.PurchaseOrder.id`
* `MercatoGoodsReceiptID` -> `procurement.GoodsReceipt.id`

Zero foreign key dependencies or runtime Mercato imports exist in the core domain models.
