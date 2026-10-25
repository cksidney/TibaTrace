"""DHA middleware contracts, relative to the tenant's approved /api/v1 base.

No caller may choose an HTTP method, destination URL or arbitrary path.
Source: https://hie-docs.dha.go.ke/catalog (reviewed 2026-10-24).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    capability: str = "dha.exchange"
    required: tuple = ()
    visit: bool = False
    claims: bool = False
    multipart: bool = False


OPERATIONS = {
    "patient_search": Operation("GET", "/patients", "dha.identity", ("identification_type", "identification_number")),
    "facility_search": Operation("GET", "/facilities/search", "dha.identity"),
    "practitioner_search": Operation("GET", "/professionals", "dha.identity", ("identification_type", "identification_number")),
    "concept_search": Operation("GET", "/clinical/concepts", "dha.terminology", ("owner", "source")),
    "concept_mappings": Operation("GET", "/clinical/concepts/mappings", "dha.terminology", ("owner", "source", "from_concept")),
    "open_visits": Operation("GET", "/shr/open-visits", required=("patient_id",)),
    "consent_request": Operation("POST", "/shr/consents", required=("visit_type",), visit=True),
    "consent_verify": Operation("POST", "/shr/consents/{consent_id}/verify", visit=True),
    "consent_status": Operation("GET", "/shr/consents/{consent_id}/status", visit=True),
    "consent_resend": Operation("POST", "/shr/consents/{consent_id}/resend-otp", visit=True),
    "visit_refresh": Operation("POST", "/shr/visits/{visit_id}/refresh", visit=True),
    "visit_close": Operation("POST", "/shr/visits/{visit_id}/close", visit=True),
    "patient_records": Operation("GET", "/shr/patient-records", required=("resources",), visit=True),
    "observations": Operation("GET", "/shr/Observation", visit=True),
    "referrals": Operation("GET", "/shr/ServiceRequest"),
    "resource_labels": Operation("GET", "/shr/resource-labels"),
    "security_labels": Operation("GET", "/shr/security-labels"),
    "bundle_submit": Operation("POST", "/shr/bundles", visit=True),
    "eligibility": Operation("GET", "/patients/eligibility", "dha.claims", ("identification_type", "identification_number"), claims=True),
    "benefits": Operation("GET", "/patients/benefits", "dha.claims", ("patient_id",), claims=True),
    "sub_benefits": Operation("GET", "/patients/sub-benefits", "dha.claims", ("patient_id",), claims=True),
    "interventions": Operation("GET", "/patients/benefits/interventions", "dha.claims", ("patient_id", "sub_benefit_code"), claims=True),
    "patient_contacts": Operation("GET", "/patients/contacts", "dha.claims", claims=True),
    "claims_otp": Operation("POST", "/claims/otp", "dha.claims", claims=True),
    "claims_authorize": Operation("POST", "/claims/authorize", "dha.claims", claims=True),
    "claims_visit": Operation("POST", "/claims/visit", "dha.claims", claims=True),
    "claim_add_line": Operation("POST", "/claims/lines", "dha.claims", ("consent_token", "intervention_code", "unit_price", "quantity"), claims=True),
    "claim_add_diagnosis": Operation("POST", "/claims/diagnoses", "dha.claims", ("consent_token", "icd_code", "intervention_code"), claims=True),
    "claim_attachment": Operation("POST", "/claims/attachments", "dha.claims", ("consent_token", "document_type", "intervention_code"), claims=True, multipart=True),
    "claim_remove_attachment": Operation("PATCH", "/claims/attachments", "dha.claims", ("consent_token", "attachment_id", "intervention_code"), claims=True),
    "claim_remove_diagnosis": Operation("PATCH", "/claims/diagnoses", "dha.claims", ("consent_token", "icd_code", "intervention_code"), claims=True),
    "claim_remove_line": Operation("PATCH", "/claims/lines", "dha.claims", ("consent_token", "line_guid"), claims=True),
    "claim_edit_line": Operation("PATCH", "/claims/lines/edit", "dha.claims", ("consent_token", "line_id"), claims=True),
    "claim_submit": Operation("POST", "/claims/submit", "dha.claims", ("consent_token",), claims=True),
    "claim_close": Operation("POST", "/claims/close", "dha.claims", ("consent_token", "cancel_reason_text", "cancel_reason_type"), claims=True),
    "claim_discharge": Operation("POST", "/claims/discharge", "dha.claims", ("consent_token",), claims=True),
    "coverage_select": Operation("POST", "/authorizations/covers", "dha.claims", ("consent_token", "policy_number", "principal_cr_id"), claims=True),
    "tariffs": Operation("POST", "/benefits/pmf-tariffs/resolve", "dha.claims", ("fr_code", "intervention_codes"), claims=True),
    "claim_preview": Operation("POST", "/claims/preview", "dha.claims", ("consent_token",), claims=True),
    "payer_claim_preview": Operation("GET", "/claims/preview/payer", "dha.claims", claims=True),
    "claim_resubmit": Operation("POST", "/claims/lines/resubmit", "dha.claims", ("consent_token",), claims=True),
    "preauth_create": Operation("POST", "/preauths", "dha.claims", ("consent_token", "intervention_code"), claims=True, multipart=True),
    "preauth_cancel": Operation("POST", "/preauths/cancel", "dha.claims", ("consent_token", "intervention_code"), claims=True),
    "preauth_preview": Operation("GET", "/preauths", "dha.claims", claims=True),
    # DHA publishes the remittance workflow but its current catalog omits the routes.
    # Bind these reads to the assigned tenant contract instead of inventing a URL.
    "remittances": Operation("GET", "", "dha.claims", claims=True),
    "remittance_claims": Operation("GET", "", "dha.claims", ("bank_reference",), claims=True),
    "callback_register": Operation("POST", "/tenants/{hie_tenant_id}/endpoints", "dha.configure"),
    "callback_operation": Operation("POST", "/tenants/{facility_id}/endpoints/{endpoint_id}/operations", "dha.configure"),
    "callback_list": Operation("GET", "/tenants/{hie_tenant_id}/endpoints", "dha.configure"),
}

SHR_RESOURCES = frozenset(("Encounter", "EpisodeOfCare", "Observation", "Condition", "Procedure", "Medication",
    "MedicationRequest", "MedicationDispense", "MedicationAdministration", "Immunization", "ServiceRequest", "AllergyIntolerance"))
