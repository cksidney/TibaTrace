"""Management command: reconcile_premises_licences

Dry-run and live audit of all tenant pharmacy premises verification status.

Usage:
  python manage.py reconcile_premises_licences [--dry-run] [--tenant <tenant_id>]

Outputs a structured JSON report of:
- Tenants with no PharmacyProfile.
- Tenants with no verified PremisesVerificationRequest.
- Tenants with a VERIFIED request but an expired PPB licence.
- Tenants with a VERIFIED request and a licence expiring within 30 days (warning).
- Tenants fully compliant.

Truth label: MANUAL_INTERNAL_VERIFICATION
This command performs an internal reconciliation only. It does NOT contact the PPB API.
"""
from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.pharmacy_network.models import PharmacyProfile, PremisesVerificationRequest
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = (
        "Reconcile tenant pharmacy premises licence verification status. "
        "Truth label: MANUAL_INTERNAL_VERIFICATION. Does not contact PPB API."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report findings without writing any changes.",
        )
        parser.add_argument(
            "--tenant",
            type=str,
            default=None,
            help="Restrict reconciliation to a single tenant UUID.",
        )
        parser.add_argument(
            "--expiry-warning-days",
            type=int,
            default=30,
            help="Warn if licence expires within this many days (default: 30).",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        tenant_filter: str | None = options["tenant"]
        warning_days: int = options["expiry_warning_days"]
        today = timezone.localdate()
        warning_threshold = today + timedelta(days=warning_days)

        tenants_qs = Tenant.objects.all()
        if tenant_filter:
            tenants_qs = tenants_qs.filter(id=tenant_filter)

        findings = {
            "truth_label": "MANUAL_INTERNAL_VERIFICATION",
            "ppb_api_status": "ADAPTER_SCAFFOLDED_NOT_CONNECTED",
            "run_at": timezone.now().isoformat(),
            "dry_run": dry_run,
            "warning_days": warning_days,
            "results": [],
        }

        for tenant in tenants_qs.order_by("id"):
            entry = {
                "tenant_id": str(tenant.id),
                "tenant_name": str(tenant),
                "status": None,
                "detail": None,
            }

            try:
                profile = PharmacyProfile.all_objects.get(tenant_id=tenant.id)
            except PharmacyProfile.DoesNotExist:
                entry["status"] = "NO_PHARMACY_PROFILE"
                entry["detail"] = "Tenant has no PharmacyProfile record."
                findings["results"].append(entry)
                continue

            verified_request = (
                PremisesVerificationRequest.all_objects
                .filter(
                    tenant_id=tenant.id,
                    state=PremisesVerificationRequest.VerificationState.VERIFIED,
                )
                .order_by("-created_at")
                .first()
            )

            if verified_request is None:
                entry["status"] = "NOT_VERIFIED"
                entry["detail"] = "No verified PremisesVerificationRequest found."
                findings["results"].append(entry)
                continue

            if not profile.ppb_premises_licence_number:
                entry["status"] = "LICENCE_NUMBER_MISSING"
                entry["detail"] = "No PPB premises licence number recorded."
                findings["results"].append(entry)
                continue

            if not profile.ppb_licence_expiry:
                entry["status"] = "LICENCE_EXPIRY_MISSING"
                entry["detail"] = "PPB licence expiry date is not recorded."
                findings["results"].append(entry)
                continue

            if profile.ppb_licence_expiry < today:
                entry["status"] = "LICENCE_EXPIRED"
                entry["detail"] = f"Licence expired on {profile.ppb_licence_expiry}."
                findings["results"].append(entry)
                continue

            if profile.ppb_licence_expiry <= warning_threshold:
                entry["status"] = "LICENCE_EXPIRY_WARNING"
                entry["detail"] = (
                    f"Licence expires on {profile.ppb_licence_expiry} "
                    f"({(profile.ppb_licence_expiry - today).days} days remaining)."
                )
                findings["results"].append(entry)
                continue

            entry["status"] = "COMPLIANT"
            entry["detail"] = (
                f"Verified. Licence {profile.ppb_premises_licence_number} "
                f"expires {profile.ppb_licence_expiry}. "
                "Truth label: MANUAL_INTERNAL_VERIFICATION."
            )
            findings["results"].append(entry)

        summary = {
            "total": len(findings["results"]),
            "compliant": sum(1 for r in findings["results"] if r["status"] == "COMPLIANT"),
            "not_verified": sum(1 for r in findings["results"] if r["status"] == "NOT_VERIFIED"),
            "expired": sum(1 for r in findings["results"] if r["status"] == "LICENCE_EXPIRED"),
            "expiry_warning": sum(1 for r in findings["results"] if r["status"] == "LICENCE_EXPIRY_WARNING"),
            "no_profile": sum(1 for r in findings["results"] if r["status"] == "NO_PHARMACY_PROFILE"),
            "other": sum(
                1 for r in findings["results"]
                if r["status"] not in {"COMPLIANT", "NOT_VERIFIED", "LICENCE_EXPIRED", "LICENCE_EXPIRY_WARNING", "NO_PHARMACY_PROFILE"}
            ),
        }
        findings["summary"] = summary

        self.stdout.write(json.dumps(findings, indent=2, default=str))

        if not dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nNote: This command is read-only. No changes are written. "
                    "Pass --dry-run explicitly to suppress this message."
                )
            )
