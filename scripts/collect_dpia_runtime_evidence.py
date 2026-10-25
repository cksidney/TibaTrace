#!/usr/bin/env python3
"""Collect aggregate DPIA evidence without secrets, identifiers or record exports.

Run in the deployed backend environment. PostgreSQL collection uses a read-only,
repeatable-read transaction. Optional object verification decrypts in memory and
emits counts only. This is technical evidence, never a DPIA approval decision.
"""
import argparse
import hashlib
import importlib
import json
import os
from collections import Counter
from datetime import date


def _state_counts(queryset, field, allowed):
    from django.db.models import Count

    counts = Counter()
    for row in queryset.values(field).annotate(total=Count("pk")):
        value = row[field] if row[field] in allowed else "UNRECOGNIZED"
        counts[value] += row["total"]
    return dict(sorted(counts.items()))


def _configured_connections(name):
    """Count explicit enabled flags; never serialize configuration or keys."""
    try:
        payload = json.loads(os.environ.get(name, "{}"))
    except (ValueError, TypeError):
        return {"valid_json": False, "enabled_flags": None}

    def enabled(value):
        if isinstance(value, dict):
            return int(value.get("enabled") is True) + sum(enabled(v) for v in value.values())
        if isinstance(value, list):
            return sum(enabled(v) for v in value)
        return 0

    return {"valid_json": isinstance(payload, dict), "enabled_flags": enabled(payload)}


def _identifier_controls(identifiers):
    """Support rc71 and the new source without exporting key IDs or contents."""
    from django.core.exceptions import ValidationError
    from django.db.models import Q

    result = {
        "records": identifiers.count(),
        "plaintext_values_present": identifiers.exclude(value="").count(),
        "missing_ciphertext": identifiers.filter(protected_value="").count(),
    }
    try:
        crypto = importlib.import_module("apps.patients.identifier_crypto")
    except ModuleNotFoundError as exc:
        if exc.name != "apps.patients.identifier_crypto":
            raise
        return result | {"key_lifecycle": "DJANGO_SECRET_KEY_DERIVED", "independent_keyrings_valid": False}
    result.update(key_lifecycle="INDEPENDENT_VERSIONED_ENCRYPTION_AND_LOOKUP", independent_keyrings_valid=False)
    try:
        encryption, active, lookup, active_lookup, legacy = crypto.PatientIdentifierProtector.configuration()
    except ValidationError:
        return result
    known_ciphertext = Q(protected_value="")
    for key_id in encryption:
        known_ciphertext |= Q(protected_value__startswith=f"{crypto.PREFIX}{key_id}:")
    result.update({
        "independent_keyrings_valid": True,
        "encryption_key_count": len(encryption),
        "lookup_key_count": len(lookup),
        "legacy_secret_count": len(legacy),
        "legacy_ciphertext_records": identifiers.exclude(protected_value="").exclude(protected_value__startswith=crypto.PREFIX).count(),
        "unknown_ciphertext_version_records": identifiers.filter(protected_value__startswith=crypto.PREFIX).exclude(known_ciphertext).count(),
        "unknown_lookup_version_records": identifiers.exclude(lookup_key_id__in=[*lookup, *([""] if legacy else [])]).count(),
        "nonactive_encryption_records": identifiers.exclude(protected_value__startswith=f"{crypto.PREFIX}{active}:").count(),
        "nonactive_lookup_records": identifiers.exclude(lookup_key_id=active_lookup).count(),
        "ciphertext_integrity": "NOT_DECRYPTED_BY_AGGREGATE_COLLECTOR; use tenant rotation preflight",
    })
    return result


def collect(*, verify_objects=False):
    from django.conf import settings
    from django.core.exceptions import ValidationError
    from django.db import connection, transaction
    from django.db.models import Q
    from django.utils import timezone

    from apps.documents.encryption import DocumentEncryptionError, validate_document_keyring
    from apps.documents.models import StoredClinicalDocument
    from apps.documents.storage import LocalClinicalObjectStorage
    from apps.identity.models import User
    from apps.integrations.dha_models import DhaCallback, DhaConnection, DhaExchange, DhaVisit
    from apps.integrations.models import ActivationState, ProviderConfiguration, ProviderType
    from apps.patients.models import Patient, PatientIdentifier
    from apps.tenancy.models import Tenant

    with transaction.atomic():
        postgres = connection.vendor == "postgresql"
        db_tls = {"checked": False}
        if postgres:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cursor.execute("SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
                row = cursor.fetchone()
                db_tls = {"checked": True, "tls": bool(row and row[0]), "protocol": row[1] if row else None}
        keys = getattr(settings, "DAWATRACE_DOCUMENT_ENCRYPTION_KEYS", {})
        active_key = getattr(settings, "DAWATRACE_DOCUMENT_ENCRYPTION_ACTIVE_KEY_ID", "")
        try:
            validate_document_keyring(keys, active_key)
            keyring_valid = True
        except DocumentEncryptionError:
            keyring_valid = False
        documents = StoredClinicalDocument.all_objects.all()
        object_checks = Counter()
        if verify_objects:
            for document in documents.iterator(chunk_size=100):
                try:
                    path = LocalClinicalObjectStorage._path(document.object_key)
                    if not path.is_file():
                        object_checks["missing"] += 1
                        continue
                    plaintext, key_id = LocalClinicalObjectStorage._decrypt_path(path, object_key=document.object_key)
                    valid = len(plaintext) == document.size_bytes and hashlib.sha256(plaintext).hexdigest() == document.hash_sha256
                    object_checks["integrity_valid" if valid else "integrity_invalid"] += 1
                    object_checks["encrypted" if key_id else "legacy_plaintext"] += 1
                except (OSError, ValueError, ValidationError) as exc:
                    # Exception strings can contain paths/record details. Only
                    # an aggregate failure count may leave this collector.
                    del exc
                    object_checks["unreadable_or_invalid"] += 1
        today = timezone.localdate()
        try:
            adult = date(today.year - 18, today.month, today.day)
        except ValueError:
            adult = date(today.year - 18, today.month, 28)
        patients = Patient.all_objects.all()
        identifiers = PatientIdentifier.all_objects.all()
        required_scan = bool(getattr(settings, "DAWATRACE_DOCUMENT_MALWARE_SCAN_REQUIRED", True))
        scanner_configured = bool(getattr(settings, "DAWATRACE_MALWARE_SCANNER_HOST", ""))
        privileged = User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(is_platform_admin=True) | Q(is_staff=True))
        tls_policy = settings.DATABASES["default"].get("OPTIONS", {}).get("sslmode")
        report = {
            "schema_version": 1,
            "collected_at": timezone.now().isoformat(),
            "application_version": settings.DAWATRACE_VERSION,
            "environment": settings.DAWATRACE_ENV,
            "handling": "RESTRICTED: aggregate operational evidence; keep outside public source control",
            "approval_decision": "NOT_DETERMINED_BY_TECHNICAL_COLLECTOR",
            "collection": {"database_read_only_enforced": postgres, "provider_requests": 0, "record_exports": 0},
            "transport_configuration": {
                "debug_disabled": not settings.DEBUG,
                "ssl_redirect": settings.SECURE_SSL_REDIRECT,
                "secure_session_cookie": settings.SESSION_COOKIE_SECURE,
                "secure_csrf_cookie": settings.CSRF_COOKIE_SECURE,
                "hsts_seconds": settings.SECURE_HSTS_SECONDS,
                "database_tls": db_tls,
                "database_sslmode": tls_policy,
                "database_hostname_verification_required": tls_policy == "verify-full",
            },
            "clinical_documents": {
                "keyring_valid": keyring_valid,
                "key_count": len(keys) if isinstance(keys, dict) else 0,
                "records": documents.count(),
                "scan_required": required_scan,
                "scanner_endpoint_configured": scanner_configured,
                "scanner_live_test": "NOT_PERFORMED",
                "scan_states": _state_counts(documents, "malware_scan_status", {"CLEAN", "INFECTED", "ERROR", "NOT_CONFIGURED", "PENDING", "NOT_SCANNED", "NOT_APPLICABLE"}),
                "object_verification_requested": verify_objects,
                "object_checks": dict(object_checks),
            },
            "patient_identifiers": _identifier_controls(identifiers),
            "aggregate_scale": {
                "tenants": Tenant.objects.count(),
                "designated_demo_tenants": Tenant.objects.filter(is_demo=True).count(),
                "tenant_states": _state_counts(Tenant.objects.all(), "status", dict(Tenant.STATUS_CHOICES)),
                "patients": patients.count(),
                "patients_in_designated_demo_tenants": patients.filter(tenant__is_demo=True).count(),
                "patients_under_18_from_recorded_dob": patients.filter(date_of_birth__gt=adult, date_of_birth__lte=today).count(),
                "patients_with_unknown_dob": patients.filter(date_of_birth__isnull=True).count(),
                "patients_with_future_dob": patients.filter(date_of_birth__gt=today).count(),
                "active_accounts": User.objects.filter(is_active=True).count(),
                "active_privileged_accounts_including_staff": privileged.count(),
                "forecast_and_vulnerable_population_assessment": "OWNER_EVIDENCE_REQUIRED",
            },
            "integration_configuration": {
                "national_provider_states": _state_counts(ProviderConfiguration.all_objects.all(), "activation_state", ActivationState.values),
                "active_national_dha_providers": ProviderConfiguration.all_objects.filter(provider_type__in=[ProviderType.DHA_HIE, ProviderType.DHA_HWR], activation_state=ActivationState.ACTIVE).count(),
                "dha_connection_states": _state_counts(DhaConnection.all_objects.all(), "state", {"DISABLED", "SANDBOX", "ACTIVE", "SUSPENDED"}),
                "dha_journal_records": sum(model.all_objects.count() for model in (DhaVisit, DhaExchange, DhaCallback)),
                "rx_environment_connections": _configured_connections("TIBATRACE_RX_CONNECTIONS"),
                "checkout_environment_connections": _configured_connections("TIBATRACE_CHECKOUT_CONNECTIONS"),
                "actual_disclosures_and_provider_countries": "OPERATIONS_AND_CONTRACT_EVIDENCE_REQUIRED",
            },
            "requires_separate_assessment": [
                "Verified legal operator, ODPC role/registration, privacy contact and approvers",
                "Purpose/role/lawful-basis or processor-instruction register, notices and contracts",
                "Hosting/support countries, subprocessor register and transfer safeguards",
                "Signed retention triggers/exceptions, legal holds, purge/return/restore lifecycle",
                "Privileged MFA, enrolment/recovery and recurring access-review evidence",
                "Independent database/host encryption and separate key-custody/rotation evidence",
                "Coordinated off-host backup restore exercise and approved RPO/RTO/retention",
                "Independent VAPT/retest, audit protection and incident exercise",
                "DHA status, stakeholder consultation and signed residual-risk decision",
            ],
        }
        failures = []
        if not required_scan or not scanner_configured:
            failures.append("MALWARE_SCAN_DEFERRED_OR_NOT_CONFIGURED")
        if not keyring_valid:
            failures.append("CLINICAL_OBJECT_KEYRING_INVALID")
        if report["patient_identifiers"]["plaintext_values_present"]:
            failures.append("PLAINTEXT_PATIENT_IDENTIFIERS")
        if report["patient_identifiers"]["missing_ciphertext"]:
            failures.append("PATIENT_IDENTIFIER_CIPHERTEXT_MISSING")
        identity = report["patient_identifiers"]
        if not identity["independent_keyrings_valid"]:
            failures.append("IDENTIFIER_INDEPENDENT_KEYRINGS_UNAVAILABLE")
        if identity.get("legacy_ciphertext_records"):
            failures.append("PATIENT_IDENTIFIER_LEGACY_ROTATION_REQUIRED")
        if identity.get("unknown_ciphertext_version_records") or identity.get("unknown_lookup_version_records"):
            failures.append("PATIENT_IDENTIFIER_HISTORICAL_KEYS_UNAVAILABLE")
        if any(object_checks[k] for k in ("legacy_plaintext", "missing", "integrity_invalid", "unreadable_or_invalid")):
            failures.append("CLINICAL_OBJECT_VERIFICATION_GAPS")
        if postgres and not db_tls["tls"]:
            failures.append("DATABASE_CONNECTION_NOT_ENCRYPTED")
        report["observed_control_failures"] = failures
        report["technical_control_status"] = "OBSERVED_GAPS" if failures else "NO_FAILURE_IN_MEASURED_CONTROLS"
        report["submission_readiness"] = "ACCOUNTABLE_REVIEW_REQUIRED; measured controls do not cover the complete DPIA"
        return report


def main():
    import django

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-objects", action="store_true", help="Read/decrypt objects in memory and emit integrity counts only.")
    parser.add_argument("--fail-on-gaps", action="store_true", help="Exit 2 for observed automatic control failures. Manual DPIA approval is always separate.")
    args = parser.parse_args()
    django.setup()
    report = collect(verify_objects=args.verify_objects)
    print(json.dumps(report, sort_keys=True, indent=2))
    return 2 if args.fail_on_gaps and report["observed_control_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
