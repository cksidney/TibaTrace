"""Provision non-operational provider onboarding records; never send traffic."""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.integrations.models import (
    ActivationState,
    ProviderConfiguration,
    ProviderCredentialReference,
    ProviderEnvironment,
    ProviderType,
)


class Command(BaseCommand):
    help = "Provision disabled DHA, PPB, insurer and M-PESA onboarding templates without secrets."

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        for provider_type, label in ProviderType.choices:
            for environment in ProviderEnvironment.values:
                provider, is_new = ProviderConfiguration.all_objects.get_or_create(
                    provider_type=provider_type, environment=environment,
                    defaults={
                        "display_name": f"{label} — {environment.lower()} onboarding",
                        "activation_state": ActivationState.REQUESTED,
                        "truth_label": "NOT_CONFIGURED",
                        "description": "Disabled onboarding template. No approved endpoint, credentials or live adapter acceptance.",
                        "configuration": {
                            "template_version": 1,
                            "traffic_enabled": False,
                            "approved_endpoint": "",
                            "approved_contact": "",
                            "callback_signature_method": "",
                            "adapter_acceptance": "NOT_IMPLEMENTED_OR_VALIDATED",
                            "required_evidence": [
                                "Official endpoint and permitted data-use agreement",
                                "TLS allow-list and secret-manager references",
                                "Sandbox authentication and contract tests",
                                "Replay, timeout, idempotency and signed callback tests",
                                "Independent security review and platform-owner approval",
                            ],
                        },
                    },
                )
                created += int(is_new)
                # Existing provider state/configuration is deliberately preserved.
                if not is_new:
                    continue
                for credential_type in ("CLIENT_ID", "CLIENT_SECRET", "CALLBACK_VERIFICATION_KEY"):
                    ProviderCredentialReference.objects.get_or_create(
                        provider=provider, credential_type=credential_type,
                        defaults={"reference": f"TIBATRACE_{provider_type}_{environment}_{credential_type}",
                                  "is_configured": False},
                    )
        self.stdout.write(self.style.SUCCESS(
            f"Created {created} disabled templates; existing configurations preserved. No endpoints activated or traffic sent."
        ))
