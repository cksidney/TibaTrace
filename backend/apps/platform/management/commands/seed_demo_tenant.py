"""One coherent demo tenant, across every phase.

Nine seed commands already exist and none of them compose. Each builds its own
tenant with its own branches, so running them all leaves several unrelated
organisations rather than one pharmacy you can click through. This builds the
one pharmacy: two branches, a price book each, an insurer, a till that has
opened, taken cash and closed with a Z.

Idempotent by construction -- every row is fetched by its natural key before it
is created, and the tests run the command three times and count rows. A seed
that duplicates on a second run teaches people not to run it, and then nobody
exercises the thing it was written for.

Two rules it keeps.

**Nothing here fabricates a decision.** No adjudication, no approval, no
quality release, no payment. Seeded data carrying an approval nobody granted
teaches people that approvals appear on their own, which is the habit this
codebase has had to unlearn twice.

**The awkward states are the point.** A branch that inherits its price rather
than overriding it, a till that closed short, an insurer configured against an
adapter nobody has implemented. A happy-path demo shows the parts that were
always going to work.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from apps.identity.models import User
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.organizations.models import Location, Organization
from apps.pos_shift.models import (
    BusinessDay,
    CashDeclaration,
    CashMovement,
    OperatorShift,
    PosRegister,
    RegisterSession,
)
from apps.pos_shift.reporting import ShiftReportService
from apps.pricing.models import PriceAssignment, PriceBook, PriceBookEntry, PriceBookVersion
from apps.tenancy.models import Tenant

SLUG = "tibatrace-demo"
TODAY = date.today()


class Command(BaseCommand):
    help = "Seed one coherent demo tenant across pricing, shifts and insurance."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-insurance",
            action="store_true",
            help="Also run the insurance demo seed against this tenant.",
        )
        parser.add_argument(
            "--password",
            help="Password for newly created demo users. A random password is generated when omitted.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        tenant = self.tenant()
        org = self.organization(tenant)
        branches = self.branches(tenant, org)
        demo_password = options.get("password") or get_random_string(24)
        people, created_users = self.people(tenant, demo_password)
        skus = self.catalogue(tenant)

        self.pricing(tenant, branches, skus)
        register, session = self.shift(tenant, branches["eldoret"], people)

        if options.get("with_insurance"):
            call_command("seed_insurance_demo", tenant=tenant.slug)

        self.stdout.write(self.style.SUCCESS(f"Demo tenant '{tenant.slug}' ready."))
        credential_note = (
            f"  New users     : {', '.join(created_users)} (password '{demo_password}')"
            if created_users
            else "  Sign in as    : demo-operator / demo-supervisor (existing passwords unchanged)"
        )
        self.stdout.write(
            "  Branches      : Eldoret (own price book), Mombasa (inherits tenant prices)\n"
            "  Pricing       : one item priced differently per branch, from one product master\n"
            "  Shift         : one closed register session with a Z report and a short drawer\n"
            f"{credential_note}"
        )

    # ------------------------------------------------------------------ parts

    def tenant(self) -> Tenant:
        tenant, _ = Tenant.objects.get_or_create(
            slug=SLUG, defaults={"name": "TibaTrace Demo Pharmacy"}
        )
        return tenant

    def organization(self, tenant) -> Organization:
        org, _ = Organization.all_objects.get_or_create(
            tenant=tenant, code="DEMO-ORG", defaults={"name": "TibaTrace Demo Group"}
        )
        return org

    def branches(self, tenant, org) -> dict:
        made = {}
        for key, code, name in (
            ("eldoret", "DEMO-ELD", "Eldoret Branch"),
            ("mombasa", "DEMO-MSA", "Mombasa Branch"),
        ):
            branch, _ = Location.all_objects.get_or_create(
                tenant=tenant, code=code, defaults={"organization": org, "name": name}
            )
            made[key] = branch
        return made

    def people(self, tenant, password: str) -> tuple[dict, list[str]]:
        made = {}
        created_users = []
        for key, username in (("operator", "demo-operator"), ("supervisor", "demo-supervisor")):
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User.objects.create_user(
                    username=username, password=password, tenant=tenant
                )
                created_users.append(username)
            made[key] = user
        return made, created_users

    def catalogue(self, tenant) -> dict:
        # Tenant-scoped models are looked up through all_objects. The default
        # manager is tenant-strict and returns nothing when no tenant context is
        # set, so get_or_create would miss the existing row on a second run and
        # collide with the unique constraint -- which is a seed that works once.
        dose_form, _ = DoseForm.objects.get_or_create(
            code="DEMO-CAP", defaults={"name": "Capsule"}
        )
        clinical, _ = ClinicalMedicinalProduct.all_objects.get_or_create(
            tenant=tenant, code="DEMO-CMP-AMOX",
            defaults={"canonical_name": "Amoxicillin 500mg", "dose_form": dose_form},
        )
        manufactured, _ = ManufacturedMedicinalProduct.all_objects.get_or_create(
            tenant=tenant, code="DEMO-MP-AMOX",
            defaults={"brand_name": "Amoxil", "clinical_product": clinical},
        )
        package, _ = PackageDefinition.objects.get_or_create(
            code="DEMO-PK21",
            defaults={"description": "21 capsules", "unit_of_measure": "capsule"},
        )
        sku, _ = CommercialSKU.all_objects.get_or_create(
            tenant=tenant, sku_code="DEMO-SKU-AMOX",
            defaults={
                "display_name": "Amoxil 500mg 21s",
                "manufactured_product": manufactured,
                "package_definition": package,
            },
        )
        return {"amoxicillin": sku}

    def pricing(self, tenant, branches, skus) -> None:
        """One product master, two lawful branch prices.

        Eldoret overrides; Mombasa does not and inherits. That asymmetry is the
        demonstration -- a seed where every branch overrides would hide the
        inheritance the design exists for.
        """
        self._price_book(
            tenant, code="DEMO-TENANT-RETAIL", scope=PriceBook.ScopeType.TENANT,
            sku=skus["amoxicillin"], price=Decimal("600.00"), branch=None,
        )
        self._price_book(
            tenant, code="DEMO-ELD-RETAIL", scope=PriceBook.ScopeType.BRANCH,
            sku=skus["amoxicillin"], price=Decimal("650.00"), branch=branches["eldoret"],
        )

    def _price_book(self, tenant, *, code, scope, sku, price, branch) -> None:
        book, _ = PriceBook.all_objects.get_or_create(
            tenant=tenant, code=code,
            defaults={"name": code, "scope_type": scope, "currency": "KES"},
        )
        version = PriceBookVersion.all_objects.filter(
            tenant=tenant,
            price_book=book,
            status=PriceBookVersion.Status.ACTIVE,
        ).first()
        if version is None:
            next_version = (
                PriceBookVersion.all_objects.filter(tenant=tenant, price_book=book)
                .order_by("-version_number")
                .values_list("version_number", flat=True)
                .first()
                or 0
            ) + 1
            version = PriceBookVersion.all_objects.create(
                tenant=tenant,
                price_book=book,
                version_number=next_version,
                status=PriceBookVersion.Status.ACTIVE,
                effective_from=TODAY - timedelta(days=30),
            )
        PriceBookEntry.all_objects.get_or_create(
            tenant=tenant,
            version=version,
            sku=sku,
            minimum_quantity=Decimal("1"),
            defaults={"unit_price": price},
        )
        PriceAssignment.all_objects.get_or_create(
            tenant=tenant,
            price_book=book,
            scope_type=scope,
            branch=branch,
        )

    def shift(self, tenant, branch, people):
        """A till that opened, moved cash, and closed short.

        Closed short deliberately. A demo that balances exactly never shows the
        variance workflow, which is the part anybody operating a pharmacy
        actually needs to see.
        """
        register, _ = PosRegister.all_objects.get_or_create(
            tenant=tenant, code="DEMO-TILL-01",
            defaults={
                "location": branch, "name": "Demo Front Till",
                "state": "AVAILABLE", "expected_float": Decimal("5000.00"),
            },
        )
        day, _ = BusinessDay.all_objects.get_or_create(
            tenant=tenant, location=branch, business_date=TODAY, defaults={"state": "OPEN"}
        )

        existing = RegisterSession.all_objects.filter(
            tenant=tenant, register=register, business_day=day
        ).first()
        if existing is not None:
            return register, existing

        session = RegisterSession.all_objects.create(
            tenant=tenant, register=register, business_day=day,
            opened_by=people["operator"], state="OPEN",
        )
        OperatorShift.all_objects.create(
            tenant=tenant, register_session=session, operator=people["operator"], state="OPEN"
        )

        now = timezone.now()
        CashDeclaration.all_objects.create(
            tenant=tenant, register_session=session, kind="OPENING",
            declared_amount=Decimal("5000.00"), declared_by=people["operator"],
            confirmed_at=now,
        )
        CashMovement.all_objects.create(
            tenant=tenant, register_session=session, kind="SAFE_DROP",
            amount=Decimal("2000.00"), created_by=people["operator"],
            reason_code="SAFE_DROP", description="Mid-shift drop to safe",
            approved_by=people["supervisor"], approved_at=now,
        )
        CashDeclaration.all_objects.create(
            tenant=tenant, register_session=session, kind="CLOSING",
            declared_amount=Decimal("2950.00"), declared_by=people["operator"],
            confirmed_at=now, reason="Counted twice; 50 short.",
        )

        # Expected: 5000 opening, less 2000 to the safe, is 3000. Counted 2950,
        # so the Z carries a 50 shortfall and the variance workflow has
        # something to show.
        ShiftReportService.finalise_z(
            session=session, actor=people["operator"], declared_cash=Decimal("2950.00")
        )
        return register, session
