# Medicine, Product, SKU, and Batch Identity Separation

## Core Domain Principles

1. **A Medicine is NOT a Product:** Clinical formulation (`ClinicalMedicinalProduct`) represents therapeutic identity. Branded product (`ManufacturedMedicinalProduct`) represents manufacturer identity.
2. **A Product is NOT a SKU:** Commercial SKU (`CommercialSKU`) represents sellable/purchasable packaging and pricing identity.
3. **A SKU is NOT a Batch:** Inventory stock batches (`StockBatch`) represent physical physical lots, expiries, and serials.
4. **No Overloaded Product Tables:** Clinical attributes, commercial packaging, and inventory lots must not be merged into one single model.
