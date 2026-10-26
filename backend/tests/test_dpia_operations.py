import base64
import importlib.util
import json
import os
from io import StringIO
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import AuditEvent, PlatformAuditEvent
from apps.identity import mfa
from apps.identity.models import User

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def setup(tenant_a, settings):
    settings.TIBATRACE_MFA_ENCRYPTION_KEYS = {'old': base64.urlsafe_b64encode(b'M' * 32).decode()}
    settings.TIBATRACE_MFA_ACTIVE_KEY_ID = 'old'
    operator = User.objects.create_user(username='security-reviewer', is_platform_admin=True)
    target = User.objects.create_user(username='private-review-account', tenant=tenant_a)
    mfa.begin_enrollment(target, 'synthetic-operations-nonce')
    return operator, target


def test_governed_reset_has_no_self_service_bypass_and_dry_run_preserves_credential(setup):
    operator, target = setup
    original = mfa.MfaCredential.objects.get(user=target).protected_secret
    kwargs = dict(user_id=str(target.pk), operator_id=str(operator.pk), approval_reference='approved-ticket-12',
                  identity_check_reference='verified-identity-record-12', stdout=StringIO())
    call_command('reset_mfa', **kwargs)
    assert mfa.MfaCredential.objects.get(user=target).protected_secret == original
    with pytest.raises(CommandError):
        call_command('reset_mfa', **{**kwargs, 'operator_id': str(target.pk), 'apply': True})
    call_command('reset_mfa', apply=True, **kwargs)
    assert mfa.MfaCredential.objects.get(user=target).protected_secret == ''
    audit = PlatformAuditEvent.objects.get(action='MFA_GOVERNED_RESET')
    assert audit.metadata == {'approval_reference': 'approved-ticket-12', 'identity_check_reference': 'verified-identity-record-12'}


def test_mfa_key_rotation_validates_complete_population_and_retains_seed(setup, settings):
    operator, target = setup
    original = mfa.MfaCredential.objects.get(user=target)
    plaintext = mfa._unseal(original)
    settings.TIBATRACE_MFA_ENCRYPTION_KEYS = {**settings.TIBATRACE_MFA_ENCRYPTION_KEYS,
        'new': base64.urlsafe_b64encode(b'N' * 32).decode()}
    settings.TIBATRACE_MFA_ACTIVE_KEY_ID = 'new'
    kwargs = dict(operator_id=str(operator.pk), approval_reference='rotation-approval-12', stdout=StringIO())
    call_command('rotate_mfa_keys', **kwargs)
    assert mfa.MfaCredential.objects.get(user=target).protected_secret == original.protected_secret
    call_command('rotate_mfa_keys', apply=True, **kwargs)
    current = mfa.MfaCredential.objects.get(user=target)
    assert current.protected_secret != original.protected_secret
    settings.TIBATRACE_MFA_ENCRYPTION_KEYS = {'new': settings.TIBATRACE_MFA_ENCRYPTION_KEYS['new']}
    assert mfa._unseal(current) == plaintext
    assert current.version == original.version
    assert plaintext not in str(PlatformAuditEvent.objects.get(action='MFA_KEYS_REWRAPPED').metadata)


def test_access_snapshot_is_private_unreviewed_and_never_includes_secrets(setup, tmp_path):
    _, target = setup
    path = tmp_path/'restricted-review.json'
    call_command('access_review_snapshot', output=str(path), stdout=StringIO())
    report = json.loads(path.read_text())
    assert report['approval_status'] == 'UNREVIEWED'
    assert len(report['accounts']) == 2
    assert all(row['review_decision'] == 'PENDING' for row in report['accounts'])
    assert os.stat(path).st_mode & 0o077 == 0
    assert 'private-review-account' not in path.read_text()
    assert mfa.MfaCredential.objects.get(user=target).protected_secret not in path.read_text()
    with pytest.raises(FileExistsError):
        call_command('access_review_snapshot', output=str(path), stdout=StringIO())


def test_audit_checkpoint_rejects_modified_content_and_untrusted_key(setup, tmp_path):
    _, target = setup
    AuditEvent.all_objects.create(tenant=target.tenant, actor=target, action='SYNTHETIC', model_name='Synthetic',
        object_id='private-object-reference', metadata={'private-field':'private-clinical-content'})
    key = Ed25519PrivateKey.generate()
    private = tmp_path/'signing.key'
    private.write_bytes(base64.b64encode(key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())))
    private.chmod(0o600)
    public = tmp_path/'trusted.pub'
    public.write_bytes(base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)))
    checkpoint = tmp_path/'checkpoint.json'
    call_command('audit_checkpoint', output=str(checkpoint), signing_key_file=private, stdout=StringIO())
    assert 'private-clinical-content' not in checkpoint.read_text()
    assert 'private-object-reference' not in checkpoint.read_text()
    call_command('audit_checkpoint', verify=checkpoint, trusted_public_key_file=public, stdout=StringIO())
    payload = json.loads(checkpoint.read_text())
    payload['payload']['tables']['audit.AuditEvent']['count'] = 0
    checkpoint.write_text(json.dumps(payload))
    with pytest.raises(CommandError):
        call_command('audit_checkpoint', verify=checkpoint, trusted_public_key_file=public, stdout=StringIO())


def test_backup_authentication_fails_before_decrypt_on_wrong_key_or_changed_payload(tmp_path):
    spec = importlib.util.spec_from_file_location('backup_runtime',Path(__file__).resolve().parents[2]/'deploy/tibatrace/backup-runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import hashlib
    import hmac
    key = b'synthetic-only-random-recovery-key-which-is-not-production'
    files = {}
    for name in ['database.dump.enc','configuration.tar.gz.enc','clinical-objects.tar.gz.enc']:
        path=tmp_path/name
        path.write_bytes(b'synthetic-encrypted-fixture')
        files[name]={'bytes':path.stat().st_size,'ciphertext_hmac_sha256':module.file_auth(path,key)}
    manifest={'files':files}
    canonical=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
    manifest['manifest_hmac_sha256']=hmac.digest(hmac.digest(key,b'TibaTrace backup manifest authentication v1','sha256'),canonical,'sha256').hex()
    (tmp_path/'MANIFEST.json').write_text(json.dumps(manifest))
    assert module.verify_backup(tmp_path,key)['files']==files
    with pytest.raises(ValueError):
        module.verify_backup(tmp_path,hashlib.sha256(b'wrong key').digest())
    (tmp_path/'database.dump.enc').write_bytes(b'tampered-ciphertext-0000000')
    with pytest.raises(ValueError):
        module.verify_backup(tmp_path,key)
