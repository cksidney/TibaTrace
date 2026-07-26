# Kenya eTCD Product Catalogue Alignment

TibaTrace treats the Kenya eTCD product catalogue as an auditable national
reference source. It does not treat a catalogue row alone as proof that a
medicine is currently authorised, clinically appropriate, stocked, or safe to
dispense.

The source fields align with the [Kenya Essential Medicines List
2023](https://kemsa.go.ke/download/file/8e7d9c438ecc1a468d9d7615a87688df.pdf)
and PPB registration context. KEMSA publishes the KEML list, while the Pharmacy
and Poisons Board operates the public [pharmaceutical product
register](https://prims.pharmacyboardkenya.org/pharma_register_public/).

## Mapping

| eTCD field | TibaTrace representation |
| --- | --- |
| `etcd_product_id` | Global `Medicine.code` and `urn:ke:etcd:product-id` identifier |
| `ppb_registration_code` | `Medicine.licence_identifier`; a PPB identifier is added only when unique in the source snapshot |
| Generic concept, active component, route and form IDs/codes | Preserved in `Medicine.metadata` with their display names |
| Brand, generic name, dose form and strength | `Medicine` display fields |
| `keml_status`, `level_of_use` | Preserved in `Medicine.metadata.keml` |
| `manufacture_name`, `updation_date` | Preserved in metadata and source provenance |

The source does not provide enough structured ingredient or pack information to
build a clinical composition or commercial SKU safely. Clinical ingredients,
controlled-medicine status, pack sizes, barcodes, stock, formulary policy, and
dispensing activation remain separately governed.

## Safe Import

Run the dry run first. It makes no database changes and writes every rejected row
to a reviewable quarantine report.

```bash
cd backend
../.venv/bin/python manage.py import_ke_etcd_catalogue \
  "/path/to/product_catalogue.json" \
  --report /secure/reports/ke-etcd-dry-run.json
```

After reviewing the report in staging, apply the accepted records:

```bash
../.venv/bin/python manage.py import_ke_etcd_catalogue \
  "/path/to/product_catalogue.json" \
  --apply \
  --report /secure/reports/ke-etcd-import.json
```

Imported medicines are deliberately `INACTIVE`. An authorised catalogue steward
must verify current PPB status, clinical composition, controlled-medicine rules,
and local formulary approval before activating or dispensing a record.

## Quarantine Rules

The importer rejects rows without an eTCD product ID, invalid KEML or level-of-use
vocabularies, invalid update timestamps, and every row in a group where one eTCD
product ID maps to conflicting product payloads. It preserves ambiguous PPB
registration values as source metadata but does not create a globally unique PPB
identifier for them.
