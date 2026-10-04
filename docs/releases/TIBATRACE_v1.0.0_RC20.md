# TibaTrace v1.0.0-rc20

RC20 introduces governed bulk imports for tenant catalogue selection and
tenant retail-price drafts.

## Included

- Upload a CSV of existing national eTCD master catalogue codes to add valid
  medicines to a tenant catalogue in one operation.
- Upload a CSV of existing saleable tenant SKU prices into the tenant's retail
  **DRAFT** price book.
- Dry-run validation, physical spreadsheet row numbers, duplicate detection,
  and all-or-nothing apply behaviour for both imports.
- CSV templates and import feedback in HQ, plus user-guide instructions.
- Price imports retain the established governance flow: a draft must still be
  submitted, independently approved, and published before it affects sales.

## Migration and compatibility

No Django migrations are included. Catalogue imports only select established
master catalogue records; they do not create products, packages, or tenant
SKUs. Price imports require established saleable tenant SKUs and do not modify
published price versions.
