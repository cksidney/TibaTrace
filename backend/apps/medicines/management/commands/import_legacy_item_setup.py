import json

from django.core.exceptions import ValidationError, PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from apps.identity.models import User
from apps.medicines.onboarding import import_source
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Stage a validated legacy item export for manager completion; does not create stock or saleable SKUs."

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("--tenant-slug", required=True)
        parser.add_argument("--actor-email", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(slug=options["tenant_slug"])
            actor = User.objects.get(email=options["actor_email"], is_active=True)
            with open(options["source"], encoding="utf-8") as source:
                payload = json.load(source)
            result = import_source(tenant=tenant, actor=actor, payload=payload, apply=options["apply"])
        except (OSError, ValueError, KeyError, Tenant.DoesNotExist, User.DoesNotExist, ValidationError, PermissionDenied) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result))
