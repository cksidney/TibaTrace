from apps.organizations.models import OrganizationIdentifier
from apps.practitioners.models import PractitionerIdentifier
from apps.prescription.models import Prescription, PrescriptionVerification
from apps.prescription.providers.base import AdapterFactory


class VerificationEngine:
    """
    Provider-neutral verification engine.
    Routes requests to the correct adapter based on the prescription's source/provider.
    """

    @staticmethod
    def verify_prescription(prescription: Prescription, provider_code: str) -> bool:
        if not prescription.tenant_id:
            raise ValueError("Prescription verification requires an explicit tenant.")
        adapter = AdapterFactory.get_adapter(provider_code)

        # 1. Verify Prescription Payload
        result = adapter.verify_prescription(str(prescription.id))
        is_valid = result.get('is_valid', False)

        # 2. Validate Practitioner
        if is_valid and prescription.practitioner:
            practitioner_identifier = PractitionerIdentifier.all_objects.filter(
                tenant_id=prescription.tenant_id,
                practitioner=prescription.practitioner,
            ).first()
            if practitioner_identifier:
                is_valid = adapter.validate_practitioner(practitioner_identifier.value)

        # 3. Validate Facility
        if is_valid and prescription.organization:
            organization_identifier = OrganizationIdentifier.all_objects.filter(
                tenant_id=prescription.tenant_id,
                organization=prescription.organization,
            ).first()
            if organization_identifier:
                is_valid = adapter.validate_facility(organization_identifier.value)

        # Log Verification
        PrescriptionVerification.all_objects.create(
            tenant_id=prescription.tenant_id,
            prescription=prescription,
            verified_by_provider=provider_code,
            verification_payload=result,
            is_valid=is_valid
        )

        # Provider verification is evidence only. It never bypasses DawaTrace clinical review.
        return is_valid
