from apps.prescription.providers.base import PrescriptionProviderAdapter, UnconfiguredProviderAdapter


class SHAAdapter(UnconfiguredProviderAdapter, PrescriptionProviderAdapter):
    """SHA contract placeholder. No network call or positive verification is simulated."""

    def check_eligibility(self, patient_reference: str) -> bool:
        return False
