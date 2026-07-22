# FHIR R4 Medication Mapping Architecture

## Overview

DawaTrace maps internal clinical products (`ClinicalMedicinalProduct`) to HL7 FHIR R4 `Medication` resources via `FHIRMedicationMapper`.

## Mapped Attributes
* `resourceType`: `"Medication"`
* `code`: Canonical clinical product coding
* `status`: `"active"` / `"inactive"`
* `form`: DoseForm coding (`http://dawatrace.esenai.com/fhir/dose-form`)
* `ingredient`: Active substance coding & decimal strength numerator/denominator
