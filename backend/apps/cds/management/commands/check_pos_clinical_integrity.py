from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from apps.cds.pos_screening_models import (
    PosClinicalAuditEvent,
    PosClinicalDecision,
    PosClinicalFinding,
    PosClinicalOverride,
    PosClinicalScreening,
)
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Validate POS clinical integrity."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=str, help="Tenant slug")

    def _record(self, issues, code, object_id, detail):
        issues.append({
            "code": code,
            "object_id": str(object_id),
            "detail": detail,
        })

    def _check_tenant(self, tenant):
        issues = []
        
        # 2. A basket with an open blocking finding must never be green-lit.
        #    Note: status='COMPLETE' means the screening *evaluation* finished,
        #    not that the sale completed. A screening that found a blocker and
        #    is awaiting pharmacist action is a correct, expected state, so the
        #    invariant to enforce is the safe_to_proceed flag -- not the mere
        #    presence of an unresolved finding.
        screenings = PosClinicalScreening.all_objects.filter(tenant=tenant, status='COMPLETE')
        for screening in screenings:
            open_blocking = PosClinicalFinding.all_objects.filter(
                screening=screening,
                blocking=True,
                resolution_status='OPEN',
            ).count()
            if open_blocking and screening.safe_to_proceed:
                self._record(
                    issues,
                    "UNSAFE_SCREENING_CLEARED",
                    screening.id,
                    "Screening is marked safe to proceed despite an unresolved blocking finding.",
                )
            if open_blocking != screening.blocking_count:
                self._record(
                    issues,
                    "BLOCKING_COUNT_DESYNCHRONISED",
                    screening.id,
                    f"blocking_count={screening.blocking_count} but {open_blocking} open blocking finding(s) exist.",
                )

        # 3. Pharmacist decision without pharmacist identity
        for dec in PosClinicalDecision.all_objects.filter(tenant=tenant):
            if not dec.pharmacist_id:
                self._record(issues, "MISSING_PHARMACIST_IDENTITY", dec.id, "Decision lacks pharmacist identity.")

        # 4. Override without reason or justification
        for override in PosClinicalOverride.all_objects.filter(tenant=tenant):
            if not override.clinical_justification:
                self._record(issues, "OVERRIDE_WITHOUT_JUSTIFICATION", override.id, "Override lacks clinical justification.")

        # 6. Supply after context hash changed
        for dec in PosClinicalDecision.all_objects.filter(tenant=tenant):
            if dec.context_hash_at_decision and dec.screening.context_hash != dec.context_hash_at_decision:
                self._record(issues, "CONTEXT_HASH_MISMATCH", dec.id, "Decision context hash differs from screening.")

        # 7. Duplicate clinical decision (same idempotency_key)
        duplicate_keys = PosClinicalDecision.all_objects.filter(tenant=tenant).values('idempotency_key').annotate(key_count=Count('idempotency_key')).filter(key_count__gt=1)
        if duplicate_keys.exists():
             self._record(issues, "DUPLICATE_IDEMPOTENCY_KEY", "MULTIPLE", "Duplicate idempotency keys found in decisions.")

        # 8. Missing rule version on findings
        for finding in PosClinicalFinding.all_objects.filter(tenant=tenant):
            if not finding.rule_version:
                self._record(issues, "MISSING_RULE_VERSION", finding.id, "Finding lacks rule version.")

        # 9. Cross-tenant clinical references
        tenant_models = (
            PosClinicalScreening, PosClinicalFinding, PosClinicalDecision, PosClinicalOverride, PosClinicalAuditEvent
        )
        for model in tenant_models:
            relation_fields = getattr(model, "tenant_relation_fields", ())
            mgr = getattr(model, "all_objects", model.objects)
            for instance in mgr.filter(tenant=tenant):
                for field_name in relation_fields:
                    related = getattr(instance, field_name, None)
                    if related and str(getattr(related, "tenant_id", "")) != str(tenant.id):
                        self._record(issues, "CROSS_TENANT_REFERENCE", instance.id, f"{model.__name__}.{field_name} crosses tenant scope.")

        # 10. Clinical decision missing from audit
        for dec in PosClinicalDecision.all_objects.filter(tenant=tenant):
            # all_objects, like every other query in this checker. `objects` is
            # tenant-strict and this command sets no thread-local context, so
            # the lookup returned nothing and .exists() was always False --
            # reporting *every* clinical decision as missing its audit event.
            has_audit = PosClinicalAuditEvent.all_objects.filter(
                tenant=tenant, screening=dec.screening, event_type__in=['FINDING_RESOLVED', 'OVERRIDE_RECORDED']
            ).exists()
            if not has_audit:
                self._record(issues, "MISSING_AUDIT_EVENT", dec.id, "Decision missing from audit logs.")

        return issues

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        if options.get("tenant"):
            tenants = tenants.filter(slug=options["tenant"])
        
        issues = []
        for tenant in tenants:
            tenant_issues = self._check_tenant(tenant)
            issues.extend(tenant_issues)
            self.stdout.write(f"{tenant.slug}: {len(tenant_issues)} clinical integrity issue(s)")
            
        for issue in issues:
            self.stderr.write(f"{issue['code']} {issue['object_id']}: {issue['detail']}")
            
        if issues:
            raise CommandError(f"POS clinical integrity failed with {len(issues)} issue(s).")
            
        self.stdout.write(self.style.SUCCESS("POS clinical integrity check passed."))
