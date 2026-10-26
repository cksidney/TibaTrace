"""Governed console recovery; password-reset flows never remove a second factor."""
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.identity import mfa
from apps.identity.models import User


class Command(BaseCommand):
    help = 'Dry-run MFA reset by default. Apply requires a different platform operator, approval and identity-check references.'

    def add_arguments(self, parser):
        parser.add_argument('--user-id', required=True)
        parser.add_argument('--operator-id', required=True)
        parser.add_argument('--approval-reference', required=True)
        parser.add_argument('--identity-check-reference', required=True)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            target = User.objects.select_for_update().get(pk=options['user_id'])
            operator = User.objects.get(pk=options['operator_id'], is_active=True)
        except (User.DoesNotExist, ValueError):
            raise CommandError('An existing target and active platform operator are required.') from None
        if target.pk == operator.pk or not (operator.is_platform_admin or operator.is_superuser):
            raise CommandError('A different active platform operator must perform recovery.')
        references = {key: options[key].strip() for key in ('approval_reference', 'identity_check_reference')}
        if any(not value or len(value) > 160 for value in references.values()):
            raise CommandError('Provide bounded references to the approved reset and separate identity check; no secrets.')
        credential = mfa.MfaCredential.objects.select_for_update().filter(user=target).first()
        if not options['apply']:
            self.stdout.write('Dry run: governed reset is available; no records changed. Review the actual approval/identity evidence before apply.')
            return
        if not credential:
            raise CommandError('No MFA credential exists to reset.')
        credential.version = uuid.uuid4()
        credential.enabled_at, credential.pending_expires_at, credential.blocked_until = None, None, None
        credential.protected_secret, credential.pending_nonce_hash = '', ''
        credential.recovery_hashes, credential.failed_attempts = [], 0
        credential.save()
        from apps.audit.service import log_platform_audit
        log_platform_audit(actor_id=operator.pk, action='MFA_GOVERNED_RESET', model_name='identity.MfaCredential',
            object_id=str(target.pk), metadata=references)
        self.stdout.write('MFA reset complete. Existing MFA proofs are revoked; required-policy accounts must re-enroll. Enforcement was not disabled.')
