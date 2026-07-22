# DawaTrace FHIR R4 Baseline

## Runtime Lock

- HL7 FHIR R4: 4.0.1
- `fhir.resources==6.5.0`
- `pydantic==1.10.26`
- implementation name: DawaTrace FHIR Gateway

Runtime assertions are tested. Evidence generated with `fhir.resources` 7.x is
not accepted as R4 conformance evidence.

## Resource Registry

The registry contains exactly 19 measured resource types:

Organization, Location, Practitioner, PractitionerRole, Patient, Medication,
MedicationRequest, MedicationDispense, MedicationStatement,
AllergyIntolerance, Condition, Encounter, MedicationAdministration,
Observation, DiagnosticReport, DocumentReference, CodeSystem, ValueSet, and
AuditEvent.

The 66 focused tests include 19 render/reparse cases, 19 tenant-isolated reads,
19 tenant-isolated searches, runtime/registry locks, tenant-qualified reference
and identifier resolution, transaction/batch bundles, patient write idempotency,
OperationOutcome, and unsupported-search rejection.

## Boundary Behavior

- API authentication and resource capabilities are mandatory except metadata.
- Every read/search/write requires tenant context.
- Relative, allowed absolute, contained, identifier, and `urn:uuid` bundle
  references are resolved under the active tenant.
- Transaction bundles are atomic; batch entries report independent outcomes.
- FHIR write identity and idempotency records are tenant-owned.
- Missing resources and validation failures return R4 `OperationOutcome`.
- CapabilityStatement is the authoritative contract for FHIR routes.

## Terminology

CodeSystem/$validate-code and ValueSet/$validate-code/$expand support versions,
inactive concepts, canonical displays, imports, exclusions, active-only results,
text filtering, pagination, and tenant-first/global fallback. Compose filters are
rejected explicitly because local filter semantics are not yet implemented.

## Lineage and Claims

Historical `mercato-os.com` identifier/profile URIs are retained only where
changing them would break source interoperability lineage. They are not a runtime
dependency or network destination.

Source HAPI R4 round-trip evidence is preserved under source documentation and the
copied conformance artifact. Phase 2 did not run a fresh external HAPI or Firely
suite. DawaTrace therefore does not claim Firely compatibility, `FHIR_PORTABLE`,
or production certification.
