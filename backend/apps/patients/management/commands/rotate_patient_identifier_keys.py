"""Atomic, tenant-scoped conversion to independently versioned identity keys."""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.audit.service import log_audit
from apps.patients.identifier_crypto import PREFIX, PatientIdentifierProtector
from apps.patients.models import PatientIdentifier
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Verify/rotate patient identifiers in one explicit tenant. Read-only dry run by default; never prints identifier data."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", required=True)
        parser.add_argument("--apply", action="store_true", help="Atomically rotate this tenant after integrity and uniqueness preflight.")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.select_for_update(no_key=True).get(pk=options["tenant_id"])
            _, active, _, active_lookup, _ = PatientIdentifierProtector.configuration()
            if PatientIdentifier.all_objects.filter(tenant_id=tenant.pk).exclude(patient__tenant_id=tenant.pk).exists():
                raise ValidationError("Patient identifier tenant relationship requires review.")
            rows = list(PatientIdentifier.all_objects.select_for_update().filter(tenant_id=tenant.pk).order_by("pk"))
            seen, planned = set(), []
            for row in rows:
                plaintext = PatientIdentifierProtector.verified_plaintext(row)
                digest = PatientIdentifierProtector.digest(tenant_id=tenant.pk, identifier_type=row.identifier_type, value=plaintext, system=row.system)
                identity = (row.identifier_type, digest)
                if identity in seen:
                    raise CommandError("Preflight refused: duplicate logical identifiers require governed identity review. No records changed.")
                seen.add(identity)
                if (row.value or not row.protected_value.startswith(f"{PREFIX}{active}:") or
                        row.lookup_key_id != active_lookup or row.value_hash != digest):
                    planned.append((row, PatientIdentifierProtector.storage_fields(tenant_id=tenant.pk, identifier_type=row.identifier_type, value=plaintext, system=row.system)))
        except (ValidationError, ValueError, Tenant.DoesNotExist):
            raise CommandError("Preflight refused: tenant, historical keys or identifier integrity require review. No records changed.") from None
        if not options["apply"]:
            self.stdout.write(f"Dry run: {len(rows)} identifiers checked; {len(planned)} require rotation. No records changed.")
            return
        # Validate the complete target first. The explicit tenant lock is shared
        # by model.save so another normal writer cannot race this conversion.
        # Administrative queryset updates avoid mixed-version uniqueness checks
        # halfway through an otherwise atomic rotation. All logical collisions
        # were checked above; old keys must remain for retained backups.
        for row, fields in planned:
            changed = PatientIdentifier.all_objects.filter(pk=row.pk, tenant_id=tenant.pk).update(**fields, updated_at=timezone.now())
            if changed != 1:
                raise CommandError("Identifier rotation was interrupted and has been rolled back.")
        if planned:
            log_audit(tenant_id=tenant.pk, action="PATIENT_IDENTIFIER_KEYS_ROTATED", model_name="PatientIdentifier",
                      object_id=tenant.pk, metadata={"checked": len(rows), "rotated": len(planned),
                                                   "encryption_key_id": active, "lookup_key_id": active_lookup})
        self.stdout.write(f"Rotation complete: {len(rows)} identifiers checked; {len(planned)} rotated atomically. Retain historical keys for backups.")
