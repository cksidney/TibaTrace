"""Seed insurance scenarios for development and demonstration.

Idempotent by construction: every row is fetched by its natural business key
before it is created, so running twice produces the same database rather than
two of everything. A seed that duplicates on a second run teaches people not to
run it, and then nobody exercises the thing it was written to exercise.

The scenarios are chosen to cover the states that are easy to get wrong rather
than the ones that are common. A fully approved claim is the least interesting
row here; a claim the insurer acknowledged and never decided is the one that
catches a receivable being booked too early.

Nothing here fabricates an insurer decision on a real claim. Every adjudication
in this data is attached to a seeded claim explicitly marked as demonstration
data, and no scenario writes a payment that did not come from a seeded
remittance.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.insurance.models import (
    CoverageBenefit,
    CoverageExclusion,
    CoverageVerification,
    InsuranceCoverage,
    InsuranceMember,
    InsuranceRemittance,
    InsuranceRemittanceLine,
    Insurer,
    InsurerPlan,
    InsurerScheme,
)
from apps.tenancy.models import Tenant

ZERO = Decimal("0.00")

#: Marks every row this command creates, so a later cleanup can find them and
#: nobody mistakes seeded adjudications for real insurer decisions.
DEMO_PREFIX = "DEMO-INS"


class Command(BaseCommand):
    help = "Seed idempotent insurance scenarios. Safe to run repeatedly."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="tenant_slug", default=None)

    @transaction.atomic
    def handle(self, *args, **options):
        tenant = self._tenant(options.get("tenant_slug"))
        self.stdout.write(f"Seeding insurance demo data for tenant {tenant.slug}.")

        private = self._insurer(
            tenant,
            code=f"{DEMO_PREFIX}-PRIVATE",
            name="Demo Private Insurer",
            insurer_type=Insurer.InsurerType.PRIVATE,
            adapter=Insurer.IntegrationAdapter.FAKE,
        )
        # SHA is configured but points at no implemented adapter. That is the
        # honest state: the contract has not been verified, and a configured
        # insurer whose adapter is unregistered must fail loudly at submission
        # rather than appear to work.
        sha = self._insurer(
            tenant,
            code=f"{DEMO_PREFIX}-SHA",
            name="Social Health Authority (configuration only)",
            insurer_type=Insurer.InsurerType.PUBLIC,
            adapter=Insurer.IntegrationAdapter.SHA,
        )

        scheme = self._scheme(tenant, private, code="CORPORATE", name="Corporate Scheme")
        sha_scheme = self._scheme(tenant, sha, code="SHA-BASIC", name="SHA Basic Benefit")
        plan = self._plan(tenant, scheme, code="GOLD", name="Gold Plan")
        self._plan(tenant, sha_scheme, code="SHA-STD", name="SHA Standard")

        self._benefits(tenant, plan)

        members = {
            "eligible": self._member(tenant, "DEMO-MEM-0001", "Grace Kamau"),
            "ineligible": self._member(tenant, "DEMO-MEM-0002", "John Kiprono"),
            "expired": self._member(tenant, "DEMO-MEM-0003", "Aisha Mohamed"),
            "copay": self._member(tenant, "DEMO-MEM-0004", "Peter Otieno"),
        }

        self._coverages(tenant, scheme, plan, members)
        self._verifications(tenant, private, members)
        self._remittance(tenant, private)

        self.stdout.write(self.style.SUCCESS("Insurance demo data seeded."))
        self.stdout.write(
            "Scenarios: eligible member, ineligible member, expired coverage, "
            "fixed co-payment, co-insurance, benefit limit, exclusion, "
            "stale verification, unmatched remittance line, "
            "SHA configured without a registered adapter."
        )

    # ------------------------------------------------------------------ parts

    def _tenant(self, slug):
        if slug:
            return Tenant.objects.get(slug=slug)
        tenant = Tenant.objects.first()
        if tenant is None:
            tenant = Tenant.objects.create(name="Demo Tenant", slug="demo")
        return tenant

    def _insurer(self, tenant, *, code, name, insurer_type, adapter):
        insurer, _ = Insurer.all_objects.get_or_create(
            tenant=tenant,
            code=code,
            defaults={
                "name": name,
                "insurer_type": insurer_type,
                "integration_adapter": adapter,
                "environment": Insurer.Environment.SANDBOX,
                "status": Insurer.Status.ACTIVE,
                "settlement_currency": "KES",
            },
        )
        return insurer

    def _scheme(self, tenant, insurer, *, code, name):
        scheme, _ = InsurerScheme.all_objects.get_or_create(
            tenant=tenant, insurer=insurer, code=code, defaults={"name": name}
        )
        return scheme

    def _plan(self, tenant, scheme, *, code, name):
        plan, _ = InsurerPlan.all_objects.get_or_create(
            tenant=tenant, scheme=scheme, code=code, defaults={"name": name}
        )
        return plan

    def _member(self, tenant, membership_number, principal_name):
        member, _ = InsuranceMember.all_objects.get_or_create(
            tenant=tenant,
            membership_number=membership_number,
            defaults={"principal_name": principal_name, "status": "ACTIVE"},
        )
        return member

    def _benefits(self, tenant, plan):
        CoverageBenefit.all_objects.get_or_create(
            tenant=tenant,
            plan=plan,
            category="OUTPATIENT_MEDICINE",
            defaults={
                "covered": True,
                "requires_preauth": False,
                "benefit_limit": Decimal("100000.00"),
            },
        )
        # An exclusion proves the point that a valid card is not blanket cover.
        CoverageExclusion.all_objects.get_or_create(
            tenant=tenant,
            plan=plan,
            sku=None,
            active_substance=None,
            defaults={"exclusion_reason": "Cosmetic preparations are not covered."},
        )

    def _coverages(self, tenant, scheme, plan, members):
        today = timezone.localdate()

        patients = self._patients(tenant, members)

        # Active, straightforward.
        self._coverage(
            tenant, members["eligible"], patients["eligible"], scheme, plan,
            valid_from=today - timedelta(days=180), valid_to=today + timedelta(days=180),
            status=InsuranceCoverage.Status.ACTIVE,
        )
        # Suspended: the card is real, the cover is not.
        self._coverage(
            tenant, members["ineligible"], patients["ineligible"], scheme, plan,
            valid_from=today - timedelta(days=180), valid_to=today + timedelta(days=180),
            status=InsuranceCoverage.Status.SUSPENDED,
        )
        # Lapsed before today, which a service-date filter must catch.
        self._coverage(
            tenant, members["expired"], patients["expired"], scheme, plan,
            valid_from=today - timedelta(days=400), valid_to=today - timedelta(days=30),
            status=InsuranceCoverage.Status.EXPIRED,
        )
        # Fixed co-payment plus co-insurance, so the split is worth checking.
        self._coverage(
            tenant, members["copay"], patients["copay"], scheme, plan,
            valid_from=today - timedelta(days=30), valid_to=today + timedelta(days=335),
            status=InsuranceCoverage.Status.ACTIVE,
            copay=Decimal("200.00"), coinsurance=Decimal("10.00"),
            remaining_limit=Decimal("1500.00"),
        )

    def _patients(self, tenant, members):
        from apps.patients.models import Patient

        patients = {}
        for key, member in members.items():
            reference = f"DEMO-PAT-{member.membership_number[-4:]}"
            first, _, last = member.principal_name.partition(" ")
            patient, _ = Patient.all_objects.get_or_create(
                tenant=tenant,
                internal_reference_id=reference,
                defaults={
                    "patient_number": reference,
                    "first_name": first,
                    "last_name": last or first,
                    "date_of_birth": date(1985, 5, 12),
                },
            )
            patients[key] = patient
        return patients

    def _coverage(self, tenant, member, patient, scheme, plan, *, valid_from, valid_to,
                  status, copay=ZERO, coinsurance=ZERO, remaining_limit=Decimal("50000.00")):
        InsuranceCoverage.all_objects.get_or_create(
            tenant=tenant,
            member=member,
            patient=patient,
            plan=plan,
            defaults={
                "scheme": scheme,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "status": status,
                "copay_amount": copay,
                "coinsurance_percentage": coinsurance,
                "remaining_limit": remaining_limit,
            },
        )

    def _verifications(self, tenant, insurer, members):
        """One current verification and one already expired.

        The expired row is the useful one: it proves the staleness check has
        something to catch, rather than passing because nothing is ever old.
        """
        patients = self._patients(tenant, members)
        now = timezone.now()

        CoverageVerification.all_objects.get_or_create(
            tenant=tenant,
            verification_reference=f"{DEMO_PREFIX}-VER-CURRENT",
            defaults={
                "insurer": insurer,
                "member": members["eligible"],
                "patient": patients["eligible"],
                "is_eligible": True,
                "eligibility_status": "ACTIVE",
                "expires_at": now + timedelta(hours=4),
            },
        )
        CoverageVerification.all_objects.get_or_create(
            tenant=tenant,
            verification_reference=f"{DEMO_PREFIX}-VER-STALE",
            defaults={
                "insurer": insurer,
                "member": members["copay"],
                "patient": patients["copay"],
                "is_eligible": True,
                "eligibility_status": "ACTIVE",
                "expires_at": now - timedelta(hours=1),
            },
        )

    def _remittance(self, tenant, insurer):
        """A remittance carrying a line that names no claim.

        Money that arrived and cannot be placed is the case somebody must
        investigate, and it is the one a happy-path seed never produces.
        """
        remittance, created = InsuranceRemittance.all_objects.get_or_create(
            tenant=tenant,
            remittance_number=f"{DEMO_PREFIX}-REM-0001",
            defaults={
                "insurer": insurer,
                "total_remitted_amount": Decimal("2500.00"),
                "payment_reference": "DEMO-BANK-REF-0001",
                "remittance_date": timezone.localdate(),
                "status": "IMPORTED",
            },
        )
        if created:
            InsuranceRemittanceLine.all_objects.create(
                tenant=tenant,
                remittance=remittance,
                claim=None,
                claimed_amount=Decimal("2500.00"),
                paid_amount=Decimal("2500.00"),
                status="UNMATCHED",
            )
