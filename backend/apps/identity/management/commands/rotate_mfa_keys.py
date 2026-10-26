from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.identity import mfa
from apps.identity.models import User


class Command(BaseCommand):
    help = 'Verify every encrypted MFA seed; rewrap with the active key only with --apply. Never displays seeds/codes.'

    def add_arguments(self, parser):
        parser.add_argument('--operator-id', required=True)
        parser.add_argument('--approval-reference', required=True)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        operator = User.objects.filter(pk=options['operator_id'], is_active=True).first()
        if not operator or not (operator.is_superuser or operator.is_platform_admin):
            raise CommandError('An active platform operator is required.')
        reference = options['approval_reference'].strip()
        if not reference or len(reference) > 160:
            raise CommandError('A bounded approval reference is required; no secrets.')
        planned = []
        try:
            _, active = mfa.configuration()
            rows = list(mfa.MfaCredential.objects.select_for_update().select_related('user').exclude(protected_secret=''))
            for row in rows:
                plaintext = mfa._unseal(row)
                planned.append((row, mfa._seal(row.user, plaintext)))
        except Exception:
            raise CommandError('MFA seed integrity or retained-key validation failed. No records changed.') from None
        if not options['apply']:
            self.stdout.write(f'Dry run: {len(planned)} protected seeds verified. No records changed.')
            return
        for row, ciphertext in planned:
            row.protected_secret = ciphertext
            row.save(update_fields=['protected_secret'])
        from apps.audit.service import log_platform_audit
        log_platform_audit(actor_id=operator.pk, action='MFA_KEYS_REWRAPPED', model_name='identity.MfaCredential',
            object_id=str(operator.pk), metadata={'count': len(planned), 'active_key_id': active, 'approval_reference': reference})
        self.stdout.write(f'Atomically rewrapped {len(planned)} protected seeds. Keep historical keys for retained backups.')
