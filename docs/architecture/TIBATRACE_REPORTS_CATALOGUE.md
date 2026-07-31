# TibaTrace HQ Reports Catalogue

HQ exposes an enterprise reporting menu at `#reports`, aligned to
`TibaTrace_Enterprise_Reporting_Catalogue.docx` and extended with security
assurance packs.

## Downloads

Every catalogue pack is downloadable as:

- PDF (professional layout with embedded validation QR)
- CSV
- Excel-friendly CSV (`xlsx` format selector)
- JSON

Each download:

1. Creates an audited receipt (`REPORT_DOWNLOAD`)
2. Stamps who / when / tenant / terminal id / terminal label / client IP / user agent
3. Embeds a unique QR (PDF) or QR payload (CSV/JSON) for validation
4. Exposes receipt headers and `/api/hq/reports/validate/<receipt_id>/`

## Categories

1. Executive
2. Sales & dispensing
3. Procurement
4. Inventory
5. Finance
6. Quality
7. Clinical
8. Controlled drugs
9. Regulatory
10. Logistics
11. CRM
12. HR & operations
13. Audit
14. Analytics
15. **Security** (extension)

## APIs

- `GET /api/hq/reports/`
- `POST /api/hq/reports/<report_id>/download/`
- `GET /api/hq/reports/validate/<receipt_id>/`

Source of truth for UI entries: `apps/hq-web/src/reportsCatalogue.ts`  
Server catalogue: `backend/apps/platform/reporting/catalogue.py`
