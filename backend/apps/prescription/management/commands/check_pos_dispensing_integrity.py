from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F, Q, Sum

from apps.prescription.models import (
    DispensingCheck,
    DispensingEpisode,
    DispensingLine,
    MedicineSupply,
    PatientCounselling,
    PosDeviceHealthRecord,
    PosShiftRecord,
)
from apps.prescription.payment_models import (
    PaymentIntent,
    PaymentProviderEvent,
    PaymentReversal,
    PaymentSettlement,
    PaymentTender,
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

        # ------------------------------------------------------------------
        # Payment ledger. The episode's payment_state is a projection of these
        # rows, so a disagreement between them means the projection is lying.
        # ------------------------------------------------------------------
        intents = PaymentIntent.all_objects.filter(dispensing_episode__in=episodes)
        tenders = PaymentTender.all_objects.filter(payment_intent__in=intents)

        # 9. One episode must never have two intents collecting at once, or two
        #    terminals could each collect the full amount.
        duplicate_intents = (
            intents.filter(status__in=PaymentIntent.ACTIVE_STATUSES)
            .values("dispensing_episode_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        record("episodes with more than one active payment intent", list(duplicate_intents))

        # 10. A tender marked settled with no settlement row is a claim with no
        #     evidence behind it.
        settled_tender_ids = set(
            PaymentSettlement.all_objects.filter(payment_tender__in=tenders).values_list(
                "payment_tender_id", flat=True
            )
        )
        record(
            "tenders marked settled with no settlement record",
            [
                t
                for t in tenders.filter(status=PaymentTender.Status.SETTLED)
                if t.id not in settled_tender_ids
            ],
        )

        # 11. Money recorded against a tender that no longer counts toward the
        #     intent leaves the totals unexplainable.
        record(
            "settlements attached to a cancelled tender",
            PaymentSettlement.all_objects.filter(
                payment_tender__in=tenders.filter(status=PaymentTender.Status.CANCELLED)
            ),
        )

        # 12. One real-world payment counted twice.
        duplicate_reference = (
            tenders.exclude(external_reference="")
            .values("tenant_id", "provider", "external_reference")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        record("provider references used by more than one tender", list(duplicate_reference))

        # 13. The same provider event applied more than once.
        duplicate_events = (
            PaymentProviderEvent.all_objects.filter(
                tenant_id__in=tenant_ids,
                processing_status=PaymentProviderEvent.ProcessingStatus.PROCESSED,
            )
            .exclude(event_id="")
            .values("tenant_id", "provider", "event_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        record("provider events applied more than once", list(duplicate_events))

        # 14. A reversal cannot give back more than was taken.
        over_reversed = []
        for settlement in PaymentSettlement.all_objects.filter(payment_tender__in=tenders):
            reversed_total = PaymentReversal.all_objects.filter(
                settlement=settlement, status=PaymentReversal.Status.COMPLETED
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            if reversed_total > settlement.amount:
                over_reversed.append(settlement)
        record("settlements reversed by more than their value", over_reversed)

        # 15. The central projection check: an episode reported PAID must have
        #     the settled value to back it, and one reported PARTIALLY_PAID must
        #     not already be covered.
        mismatched = []
        for intent in intents.select_related("dispensing_episode"):
            episode = intent.dispensing_episode
            effective = intent.amount_settled - intent.amount_reversed
            if episode.payment_state == "PAID" and effective < intent.amount_due:
                mismatched.append(intent)
            elif (
                episode.payment_state == "PARTIALLY_PAID"
                and intent.amount_due > 0
                and effective >= intent.amount_due
            ):
                mismatched.append(intent)
        record("episodes whose payment state disagrees with the ledger", mismatched)

        # 16. Allocation across live tenders must not exceed what is owed.
        over_allocated = []
        for intent in intents:
            allocated = (
                PaymentTender.all_objects.filter(
                    payment_intent=intent, status__in=PaymentTender.LIVE_STATUSES
                ).aggregate(total=Sum("allocated_amount"))["total"]
                or Decimal("0")
            )
            if allocated > intent.amount_due:
                over_allocated.append(intent)
        record("payment intents allocated beyond the amount due", over_allocated)

        # 17. Cross-tenant references anywhere in the payment ledger.
        record(
            "tenders whose tenant differs from their intent",
            tenders.exclude(tenant_id=F("payment_intent__tenant_id")),
        )
        record(
            "settlements whose tenant differs from their tender",
            PaymentSettlement.all_objects.filter(payment_tender__in=tenders).exclude(
                tenant_id=F("payment_tender__tenant_id")
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
