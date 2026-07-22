from typing import Any, Dict

from fhir.resources.attachment import Attachment
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.documentreference import DocumentReference, DocumentReferenceContent
from fhir.resources.reference import Reference

from apps.clinical.models import ClinicalDocument
from apps.fhir.converters.base import BaseFHIRConverter, ConversionResult


class DocumentReferenceConverter(BaseFHIRConverter):
    resource_type = "DocumentReference"

    def to_fhir(self, domain_object: ClinicalDocument, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            status = domain_object.status.lower().replace("_", "-")

            attachment = Attachment(
                contentType=domain_object.content_type,
                url=domain_object.object_url,
                size=domain_object.size_bytes,
                hash=(
                    bytes.fromhex(domain_object.hash_sha256)
                    if domain_object.hash_sha256
                    else None
                ),
            )
            doc_ref = DocumentReference(
                id=str(domain_object.id),
                status=status,
                subject=Reference(reference=f"Patient/{domain_object.patient_id}"),
                content=[DocumentReferenceContent(attachment=attachment)],
            )

            if domain_object.doc_type:
                doc_ref.type = CodeableConcept(coding=[Coding(code=domain_object.doc_type)])

            if domain_object.category:
                doc_ref.category = [CodeableConcept(coding=[Coding(code=domain_object.category)])]

            if domain_object.author_id:
                doc_ref.author = [Reference(reference=f"Practitioner/{domain_object.author_id}")]

            result.fhir_resource = doc_ref
        except Exception:
            result.add_exception("Clinical document could not be rendered as DocumentReference.")

        return result

    def to_domain_command(self, resource: DocumentReference, context: Dict[str, Any]) -> ConversionResult:
        result = ConversionResult()
        try:
            patient_id = resource.subject.reference.split("/")[-1] if resource.subject and resource.subject.reference else None
            if not patient_id:
                result.add_error("Subject (Patient) reference is required.")
                return result

            status = resource.status.upper().replace("-", "_")

            doc_type = None
            if resource.type and resource.type.coding:
                doc_type = resource.type.coding[0].code

            category = None
            if resource.category and len(resource.category) > 0 and resource.category[0].coding:
                category = resource.category[0].coding[0].code

            author_id = None
            if resource.author and len(resource.author) > 0 and resource.author[0].reference:
                author_id = resource.author[0].reference.split("/")[-1]

            object_url = None
            content_type = None
            size_bytes = None
            hash_sha256 = None

            if resource.content and len(resource.content) > 0 and resource.content[0].attachment:
                attachment = resource.content[0].attachment
                object_url = attachment.url
                content_type = attachment.contentType
                size_bytes = attachment.size
                if attachment.hash:
                    hash_sha256 = (
                        attachment.hash.hex()
                        if isinstance(attachment.hash, bytes)
                        else bytes(attachment.hash).hex()
                    )

            if not object_url or not content_type:
                result.add_error("DocumentReference must include content attachment with url and contentType.")
                return result

            result.domain_command = {
                "resource_type": "DocumentReference",
                "id": resource.id,
                "patient_id": patient_id,
                "status": status,
                "doc_type": doc_type,
                "category": category,
                "author_id": author_id,
                "object_url": object_url,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "hash_sha256": hash_sha256
            }
        except Exception:
            result.add_exception("DocumentReference could not be mapped to a domain command.")

        return result
