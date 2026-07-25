from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F, Q

from apps.prescription.models import (
    DispensingCheck,
    DispensingEpisode,
    DispensingLine,
    MedicineSupply,
    PatientCounselling,
    PosDeviceHealthRecord,
    PosShiftRecord,
)
from apps.prescription.services.clinical_dispensing import MedicineSupplyService

SUPPLIED_STATES = ["SUPPLIED", "PARTIALLY_SUPPLIED"]


class Command(BaseCommand):
    help = "Verify POS Enterprise Dispensing data integrity and tenant isolation"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="tenant", default=None)

    def handle(self, *args, **options):
        self.stdout.write("Running POS Enterprise Dispensing Integrity Check...")

        episodes = DispensingEpisode.all_objects.all()
        if options.get("tenant"):
            episodes = episodes.filter(tenant__slug=options["tenant"])
        tenant_ids = set(episodes.values_list("tenant_id", flat=True))

        self.stdout.write(f"Dispensing episodes:  {episodes.count()}")
        self.stdout.write(f"Dispensing lines:     {DispensingLine.all_objects.filter(episode__in=episodes).count()}")
        self.stdout.write(f"POS shift records:    {PosShiftRecord.all_objects.filter(tenant_id__in=tenant_ids).count()}")
        self.stdout.write(f"Device health:        {PosDeviceHealthRecord.all_objects.filter(tenant_id__in=tenant_ids).count()}")

        issues = []
        supplied = episodes.filter(status__in=SUPPLIED_STATES)

        def record(label, queryset):
            # len() works for both querysets and materialised lists; list.count()
            # means something else entirely, so do not branch on hasattr.
            count = len(queryset)
            if count:
                issues.append(f"{label}: {count}")
                self.stderr.write(self.style.ERROR(f"  FAIL {label}: {count}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"  ok   {label}"))

        # 1. Supply must never precede a payment state that permits it.
        record(
            "supplied episodes whose payment state did not permit supply",
            supplied.exclude(payment_state__in=MedicineSupplyService.ALLOWED_PAYMENT_STATES),
        )

        # 1b. Structural guard: payment settlement must be expressed by exactly
        #     one field. A second one reintroduces the divergence this model was
        #     collapsed to remove, so fail the build rather than let it ship.
        rogue = sorted(
            f.name
            for f in DispensingEpisode._meta.get_fields()
            if getattr(f, "attname", None)
            and f.name != "payment_state"
            and f.name.startswith("payment_")
            and getattr(f, "choices", None)
            and {c[0] for c in f.choices} & {"PAID", "NOT_REQUIRED"}
        )
        if rogue:
            issues.append(f"second authoritative payment state field: {rogue}")
            self.stderr.write(self.style.ERROR(f"  FAIL second payment-state field present: {rogue}"))
        else:
            self.stdout.write(self.style.SUCCESS("  ok   exactly one canonical payment-state field"))

        # 2. Supply must never precede an independent final check.
        checked_ids = DispensingCheck.all_objects.filter(
            outcome="PASSED", episode__in=supplied
        ).values_list("episode_id", flat=True)
        record(
            "supplied episodes without a passed final check",
            supplied.exclude(id__in=checked_ids),
        )

        # 3. Supply must never precede recorded counselling.
        counselled_ids = PatientCounselling.all_objects.filter(
            episode__in=supplied
        ).values_list("episode_id", flat=True)
        record(
            "supplied episodes without counselling recorded",
            supplied.exclude(id__in=counselled_ids),
        )

        # 4. Duplicate supply for one episode indicates a defeated idempotency key.
        duplicate_supply = (
            MedicineSupply.all_objects.filter(episode__in=episodes)
            .values("episode_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        record("episodes with duplicate MedicineSupply records", list(duplicate_supply))

        # 5. Oversupply beyond what was authorised.
        record(
            "dispensing lines supplied beyond authorisation",
            DispensingLine.all_objects.filter(
                episode__in=episodes, quantity_supplied__gt=F("quantity_authorized")
            ),
        )

        # 6. Controlled medicine handed over at the POS must carry collector
        #    identity and an authority check. Scoped to episodes actually
        #    collected through the POS (collected_at set): the clinical
        #    dispensing path enforces controlled custody by its own capability
        #    and separation-of-duties rules and does not populate these
        #    POS-specific fields.
        record(
            "POS-collected controlled supplies without authority or collector identity",
            supplied.filter(
                prescription__is_controlled_medicine=True, collected_at__isnull=False
            ).filter(Q(controlled_authority_checked=False) | Q(collector_id_number="")),
        )

        # 7. Collected episodes must name a collector.
        record(
            "collected episodes without a recorded collector",
            supplied.filter(collected_at__isnull=False, collector_name=""),
        )

        # 8. Cross-tenant references between an episode and its lines.
        record(
            "dispensing lines whose tenant differs from their episode",
            DispensingLine.all_objects.filter(episode__in=episodes).exclude(
                tenant_id=F("episode__tenant_id")
            ),
        )

        if issues:
            raise CommandError(
                f"POS dispensing integrity failed with {len(issues)} issue type(s): "
                + "; ".join(issues)
            )

        self.stdout.write(
            self.style.SUCCESS("POS Enterprise Dispensing Integrity Check passed.")
        )
