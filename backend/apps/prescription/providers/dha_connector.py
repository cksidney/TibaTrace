from apps.prescription.providers.base import PrescriptionProviderAdapter, UnconfiguredProviderAdapter


class DHAAdapter(UnconfiguredProviderAdapter, PrescriptionProviderAdapter):
    """DHA contract placeholder. No network call or positive verification is simulated."""
