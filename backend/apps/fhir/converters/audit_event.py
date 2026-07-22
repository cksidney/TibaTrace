from typing import Any, Dict

import fhir.resources.auditevent as fhir_ae
import fhir.resources.coding as fhir_coding
import fhir.resources.reference as fhir_ref

from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult
from apps.prescription.models import PrescriptionAudit, PrescriptionItem


class AuditEventConverter(BaseFHIRConverter):
    resource_type = "AuditEvent"

    def to_fhir(self, domain_object: PrescriptionAudit, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()

        # event action (create, read, update, delete, execute)
        # We try to infer from event_type, default to 'E' (Execute)
        action_map = {
            "CREATED": "C",
            "READ": "R",
            "UPDATED": "U",
            "DELETED": "D",
            "EXECUTED": "E"
        }
        action = action_map.get(domain_object.event_type.upper(), "E")

        agent = fhir_ae.AuditEventAgent(
            requestor=True,
            who=fhir_ref.Reference(
                reference=f"Practitioner/{domain_object.user.id}" if domain_object.user else None,
                display=str(domain_object.user) if domain_object.user else "System"
            )
        )

        source = fhir_ae.AuditEventSource(
            observer=fhir_ref.Reference(
                display="DawaTrace Prescription Service"
            ),
            type=[
                fhir_coding.Coding(
                    system="http://terminology.hl7.org/CodeSystem/security-source-type",
                    code="4", # Application Server
                    display="Application Server"
                )
            ]
        )

        prescription_item = PrescriptionItem.all_objects.filter(
            tenant_id=domain_object.tenant_id,
            prescription_id=domain_object.prescription_id,
        ).order_by("id").first()
        entity = fhir_ae.AuditEventEntity(
            what=fhir_ref.Reference(
                reference=(
                    f"MedicationRequest/{prescription_item.id}"
                    if prescription_item
                    else f"Prescription/{domain_object.prescription_id}"
                )
            )
        )

        ae = fhir_ae.AuditEvent(
            id=str(domain_object.id),
            type=fhir_coding.Coding(
                system="http://dicom.nema.org/resources/ontology/DCM",
                code="110100",
                display="Application Activity"
            ),
            action=action,
            recorded=domain_object.created_at.isoformat() if domain_object.created_at else None,
            outcome="0", # Success
            agent=[agent],
            source=source,
            entity=[entity]
        )

        result.fhir_resource = ae
        return result

    def to_domain_command(self, resource: fhir_ae.AuditEvent, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        result.warnings.append("Inbound AuditEvent mapping to domain command is not supported.")
        return result
