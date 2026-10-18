# POS prescription intake

The Windows POS Clinical workspace includes **Receive prescription** and
**Received prescriptions**. New intake does not require an open cash shift.
The activated device must belong to an active tenant branch and the operator
must have that branch assigned and the appropriate prescription capabilities.

## Receiving a prescription

1. Select **Clinical → Receive prescription**.
2. Select an existing confirmed patient and prescriber. Search records when
   needed; patient and practitioner registration remains in HQ.
3. Enter the original RX reference, date and actual prescription type.
4. Select each exact governed medicine/pack, authorised quantity and original
   directions. Quantities support three decimal places, matching RX records.
5. Upload a scan, photo or PDF, preview the selected source, or use **Take prescription photo**. A document
   scanner can save a JPEG/PNG/PDF for upload. Direct scanner-driver acquisition
   and OCR transcription are not included. Alternatively, confirm the genuine
   physical original is available for pharmacist review.
6. Select **Receive for review**. Open the received record to inspect its source
   documents, run legal validation, start clinical screening, record the review
   outcome and obtain pharmacist verification under the existing clinical rules.
7. After verification, select an active dispensing store and an approved priced
   order prepared in HQ. The order must have approved prescribed products in
   matching units, positive priced lines and quantities within remaining RX
   authority. An order already linked to another RX is rejected. The existing
   dispensing, stock, payment and supply controls then apply.

There is no automatic approval from an upload, an external source's verified
status, a payment or a new dispensing episode. Unresolved clinical findings use
the existing governed pharmacist workbench. Controlled medicines retain their
additional evidence, prescriber and storage requirements.

If the connection fails after submission, use **Check original intake**. A retry
uses exactly the original command and key. No raw source files are placed in
the offline journal or browser local storage. Intake requires connectivity.

## Documents and deployment

Each RX accepts at most five JPEG, PNG or PDF files: 5 MiB each, 8 MiB combined.
Filename, MIME, encoding and file signatures are checked on the server. Documents
are associated with the tenant and patient; original hashes, intake provenance
and audited document access are retained. `documents.write` is required to
upload and `documents.read` to open/download a stored original. Legal validation,
clinical review, verification and episode opening require their separate roles.

Production always requires configured document encryption. Uploads are disabled
unless `DAWATRACE_RX_SOURCE_UPLOADS_ENABLED=true`. Malware scanning is required
by default (`DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED=true`).

On 18 October 2026 the operator requested that scanning be deferred while RX
intake proceeds. With `DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED=false`, photo/PDF
uploads remain available and are recorded as `NOT_SCANNED`, with a deferred-policy
audit event and a visible POS notice. This is an explicit deployment decision;
file validation, encryption, access control and pharmacist review still apply.
It does not establish that a file is malware-free. Structured records generated
by the application use `NOT_APPLICABLE`; uploaded files cannot claim that origin.

To activate scanning later, restore `DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED=true`.
Set `DAWATRACE_MALWARE_SCANNER_HOST` and `DAWATRACE_MALWARE_SCANNER_PORT` (3310 by
default) to a private ClamAV INSTREAM service with current signatures. The port
must remain on a trusted private network: INSTREAM TCP itself provides no TLS or
authentication. An infected result, scanner error, timeout or missing production
scanner blocks new uploads when scanning is required. Existing unscanned files
remain labelled unscanned; enabling the scanner does not retrospectively certify
them. The service is not installed automatically by this change.

Apply prescription migration `0020_prescription_intake_evidence` after `0019`.
The native bridge permits 12 MiB JSON bodies only on the two intake endpoints;
Django has the same body limit. Both shipped Caddy templates allow 20 MB at the
edge. A deployment using another proxy must allow at least 12 MiB on these paths.
Source document responses retain the existing 10 MiB bridge limit. Camera access
is restricted to video in the focused main renderer; microphone and document
frames are denied. Confirm actual camera operation on the packaged Windows till.

## Tenant EMR / DHA adapter contract

Feeds are disabled by default. `TIBATRACE_RX_CONNECTIONS` is server-only JSON
keyed by tenant UUID and provider (`HOSPITAL_EMR` or `DHA`). It is separate from
payment connections. There is no global credential fallback or automatic
activation. For example:

```json
{
  "<tenant-uuid>": {
    "HOSPITAL_EMR": {
      "enabled": true,
      "validated": true,
      "adapter_code": "COMMISSIONED_EMR",
      "credentials_env": {"api_key": "TENANT_EMR_API_KEY"},
      "patient_map": {"source-patient-reference": "<local-patient-uuid>"},
      "prescriber_map": {"source-practitioner-reference": "<local-practitioner-uuid>"},
      "product_map": {"source-product-reference": "<local-sku-uuid>"}
    }
  }
}
```

Install the commissioned connector in server code and register its factory at
startup with `apps.prescription.rx_feeds.register_feed_adapter(code, factory)`.
The factory receives keyword arguments `tenant`, `provider`, `config` and
`credentials`. Credentials resolve only from server environment references.
Its interface is:

```python
class CommissionedAdapter:
    def __init__(self, *, tenant, provider, config, credentials): ...
    def validate_configuration(self, *, tenant): ...
    def fetch_prescription(self, reference): ...
```

`validate_configuration` must be a local validation, with no network request or
side effects. `fetch_prescription` is a read-only, authenticated lookup with
bounded connection/read timeouts, verified TLS and a configured allowed source.
It must never accept a renderer-supplied endpoint or credentials, and must not
log patient payloads or secrets. Adapter configuration errors and upstream
failures are returned as generic messages to the POS.

The returned normalized object is:

```json
{
  "reference": "original-source-rx-reference",
  "patient_reference": "source-patient-reference",
  "prescriber_reference": "source-practitioner-reference",
  "prescription_date": "2026-10-18",
  "prescription_type": "ACUTE",
  "items": [{
    "product_reference": "source-product-reference",
    "quantity": "2.000",
    "directions": "Original prescribed directions"
  }]
}
```

The returned reference must match the requested reference. Explicit tenant maps
resolve source identities and products; foreign-tenant, inactive or missing
records are refused. The source namespace and original reference prevent
duplicate imports. Source approval fields are ignored: every imported record
starts with legal validation pending, clinical review not started and pharmacist
verification not completed. The imported normalized RX is retained through the
existing generated intake record and immutable command hash. Optional source
images/PDFs can accompany the import.

After commissioning, choose the available source in **Receive prescription** and
enter its original reference. Readiness indicates installed configuration, not a
live upstream health check, DHA certification or permission to exchange data.
Live EMR/DHA credentials, source-specific transport, mappings and commissioning
remain per-tenant onboarding work. This seam supports on-demand reviewed import;
it does not enable unattended polling, inbound webhooks or global FHIR writes.

## API and validation evidence

All endpoints are under `/api/pos/dispensing/intake/` and require authenticated,
version-aligned POS access, tenant/device/branch alignment and capability checks:

| Operation | Endpoint |
| --- | --- |
| Manual intake | `POST /` |
| Tenant source lookup/import | `POST /import/` |
| Branch inbox and details | `GET /`, `GET /{id}/` |
| Choices and safe readiness | `GET /options/` |
| Original command recovery | `GET /reconcile/` |
| Canonical clinical actions | `POST /{id}/progress/` |
| Audited source retrieval | `POST /{id}/source-document/` |

Backend coverage is in `backend/tests/test_pos_rx_intake.py`. POS interaction
coverage is in `PrescriptionIntake.test.tsx`; native camera and request boundaries
are checked in `rxPolicy.test.ts`. These checks do not certify physical hardware
or a tenant's external connector.
