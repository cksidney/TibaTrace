"""Sign a content-minimized audit checkpoint for separate custody.

This detects later checkpoint modification. A separately retained prior
checkpoint and protected DB/log delivery are still needed to detect source
deletion or changes before checkpoint generation.
"""
import base64
import hashlib
import json
import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent, PlatformAuditEvent
from apps.documents.models import DocumentAccessEvent


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()


class Command(BaseCommand):
    help = 'Create a restricted Ed25519 audit checkpoint, or verify one using an independently trusted public key.'

    def add_arguments(self, parser):
        parser.add_argument('--output')
        parser.add_argument('--signing-key-file', type=Path)
        parser.add_argument('--verify', type=Path)
        parser.add_argument('--trusted-public-key-file', type=Path)
        parser.add_argument('--previous-checkpoint', type=Path)

    def handle(self, *args, **options):
        if options['verify']:
            try:
                document = json.loads(options['verify'].read_text())
                public = Ed25519PublicKey.from_public_bytes(base64.b64decode(options['trusted_public_key_file'].read_text().strip(), validate=True))
                public.verify(base64.b64decode(document['signature'], validate=True), canonical(document['payload']))
            except Exception:
                raise CommandError('Checkpoint verification failed. Use the separately trusted public key; do not trust a key bundled by the sender.') from None
            self.stdout.write('Checkpoint signature verified. Source completeness and approved custody require separate evidence.')
            return
        if not options['signing_key_file'] or not options['output']:
            raise CommandError('Creation requires --output and --signing-key-file; secret key values must never be command arguments.')
        try:
            key_file = options['signing_key_file']
            info = key_file.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
                raise ValueError('Private key file must be owner-only and owned by the operator.')
            private = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key_file.read_text().strip(), validate=True))
            previous = options['previous_checkpoint']
            previous_hash = hashlib.sha256(previous.read_bytes()).hexdigest() if previous else None
            public = base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        except Exception:
            raise CommandError('Read a valid operator-owned 0600 base64 Ed25519 seed file. No secret contents were displayed.') from None
        chains = {}
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            for model in (AuditEvent, PlatformAuditEvent, DocumentAccessEvent):
                digest, count = bytes(32), 0
                # A hash binds full source fields without exporting clinical
                # metadata, object references, actors or correlation contents.
                fields = [field.attname for field in model._meta.concrete_fields]
                for row in model._base_manager.order_by('created_at', 'pk').values(*fields).iterator(chunk_size=1000):
                    digest = hashlib.sha256(digest + canonical(row)).digest()
                    count += 1
                chains[model._meta.label] = {'count': count, 'ordered_content_hash': digest.hex()}
        payload = {'schema_version': 1, 'created_at': timezone.now().isoformat(),
            'source_git_sha': os.environ.get('SOURCE_REVISION', 'RECORD_DEPLOYED_IMAGE_SEPARATELY'),
            'tables': chains, 'previous_checkpoint_sha256': previous_hash,
            'assurance_scope': 'Snapshot signature only. Separate custody, continuity and source deletion controls required.'}
        document = {'payload': payload, 'signer_public_key': public,
            'signature': base64.b64encode(private.sign(canonical(payload))).decode()}
        fd = os.open(options['output'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(document, output, indent=2)
            output.write('\n')
        self.stdout.write('Signed audit checkpoint written. Transfer it to the approved separate append-only destination and record delivery evidence.')
