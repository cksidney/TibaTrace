from abc import ABC, abstractmethod
from typing import Any, Dict


class ProviderUnavailable(RuntimeError):
    pass


class UnconfiguredProviderAdapter:
    """Fail-closed adapter used until an authenticated provider integration is configured."""

    def check_health(self) -> bool:
        return False

    def verify_prescription(self, prescription_reference: str) -> Dict[str, Any]:
        return {"is_valid": False, "reason": "PROVIDER_NOT_CONFIGURED"}

    def fetch_prescription(self, prescription_reference: str) -> Dict[str, Any]:
        raise ProviderUnavailable("Prescription provider is not configured.")

    def validate_practitioner(self, practitioner_reference: str) -> bool:
        return False

    def validate_facility(self, facility_reference: str) -> bool:
        return False

    def submit_dispense(self, dispense_payload: Dict[str, Any]) -> bool:
        raise ProviderUnavailable("Dispense submission provider is not configured.")

    def cancel_dispense(self, dispense_reference: str, reason: str) -> bool:
        raise ProviderUnavailable("Dispense cancellation provider is not configured.")

class PrescriptionProviderAdapter(ABC):
    """
    Interface for integrating with national/regional prescription hubs,
    EMRs, or other external prescription sources (DHA, SHA, FHIR).
    No provider-specific logic should exist outside of these adapters.
    """

    @abstractmethod
    def verify_prescription(self, prescription_reference: str) -> Dict[str, Any]:
        """Verify if a prescription is valid and fetch its cryptographic verification."""
        pass

    @abstractmethod
    def fetch_prescription(self, prescription_reference: str) -> Dict[str, Any]:
        """Fetch the full prescription payload from the external source."""
        pass

    @abstractmethod
    def validate_practitioner(self, practitioner_reference: str) -> bool:
        """Verify the practitioner's active license status against the national registry."""
        pass

    @abstractmethod
    def validate_facility(self, facility_reference: str) -> bool:
        """Verify the healthcare facility's active license status."""
        pass

    @abstractmethod
    def submit_dispense(self, dispense_payload: Dict[str, Any]) -> bool:
        """Submit a dispense event back to the provider."""
        pass

    @abstractmethod
    def cancel_dispense(self, dispense_reference: str, reason: str) -> bool:
        """Cancel an already submitted dispense event."""
        pass

    @abstractmethod
    def check_health(self) -> bool:
        """Perform a health check against the provider's API."""
        pass

    def _get_configuration(self, *, tenant_id) -> Any:
        if not tenant_id:
            raise ValueError("Provider configuration requires an explicit tenant.")
        from apps.prescription.models import ProviderConfiguration

        return ProviderConfiguration.all_objects.filter(
            tenant_id=tenant_id, provider_code=self.__class__.__name__
        ).first()

class AdapterFactory:
    @staticmethod
    def get_adapter(provider_code: str) -> PrescriptionProviderAdapter:
        from apps.prescription.providers.dha_connector import DHAAdapter
        from apps.prescription.providers.hospital_emr_connector import HospitalEMRAdapter
        from apps.prescription.providers.sha_connector import SHAAdapter

        mapping = {
            "DHA": DHAAdapter,
            "SHA": SHAAdapter,
            "HOSPITAL_EMR": HospitalEMRAdapter
        }
        adapter_class = mapping.get(provider_code)
        if not adapter_class:
            raise ValueError(f"No adapter registered for provider {provider_code}")
        return adapter_class()
