from apps.prescription.providers.base import PrescriptionProviderAdapter, UnconfiguredProviderAdapter


class HospitalEMRAdapter(UnconfiguredProviderAdapter, PrescriptionProviderAdapter):
    """EMR contract placeholder. A tenant connector must implement this before use."""
