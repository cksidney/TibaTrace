"""Restricted account/device review inventory; excludes credentials and metadata."""
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from apps.identity import mfa
from apps.identity.models import User
from apps.identity.pos_authentication import PosSession


class Command(BaseCommand):
    help = 'Write a restricted account/MFA review roster. Does not approve access, revoke users or export secrets.'

    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)
        parser.add_argument('--include-usernames', action='store_true')

    def handle(self, *args, **options):
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            rows = []
            for user in User.objects.all().order_by('pk').iterator():
                credential = mfa.credential_for(user)
                row = {'user_id': str(user.pk), 'tenant_id': str(user.tenant_id or ''), 'active': user.is_active,
                    'privileged': mfa.privileged(user), 'mfa_enrolled': bool(credential and credential.enabled_at),
                    'must_change_password': user.must_change_password,
                    'last_login': user.last_login.isoformat() if user.last_login else None,
                    'capabilities': sorted(user.effective_capabilities()), 'review_decision': 'PENDING',
                    'reviewer': '', 'reviewed_at': '', 'evidence_reference': ''}
                if options['include_usernames']:
                    row['username'] = user.get_username()
                rows.append(row)
            sessions = [{
                'session_id': str(row.pk), 'user_id': str(row.credential.user_id), 'tenant_id': str(row.tenant_id),
                'device_id': row.device_id, 'register_id': row.register_id,
                'started_at': row.started_at.isoformat(), 'last_seen_at': row.last_seen_at.isoformat(),
                'expires_at': row.expires_at.isoformat(), 'ended': row.ended_at is not None,
                'review_decision': 'PENDING', 'evidence_reference': '',
            } for row in PosSession.all_objects.select_related('credential').order_by('pk').iterator()]
        result = {'generated_at': timezone.now().isoformat(), 'handling': 'RESTRICTED STAFF ACCESS REVIEW',
            'approval_status': 'UNREVIEWED', 'mfa_enforcement_configured': bool(mfa.settings.TIBATRACE_PRIVILEGED_MFA_REQUIRED),
            'accounts': rows, 'pos_sessions': sessions}
        fd = os.open(Path(options['output']), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(result, output, indent=2)
            output.write('\n')
        self.stdout.write(f'Restricted review snapshot written: {len(rows)} accounts. No access decisions or changes made.')
