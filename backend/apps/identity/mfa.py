"""Password-plus-TOTP authentication with encrypted seeds and single-use recovery.

Verification and replay/throttle updates share a database row lock. Seed/key and
code values never enter audit metadata. A password reset never resets MFA.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.documents.encryption import (
    DocumentEncryptionError,
    decrypt_document_bytes,
    encrypt_document_bytes,
    validate_document_keyring,
)


class MfaCredential(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.CASCADE)
    protected_secret = models.TextField(blank=True)
    enabled_at = models.DateTimeField(null=True, blank=True)
    version = models.UUIDField(default=uuid.uuid4, editable=False)
    last_step = models.BigIntegerField(default=-1)
    recovery_hashes = models.JSONField(default=list, blank=True)
    pending_nonce_hash = models.CharField(max_length=64, blank=True)
    pending_expires_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveIntegerField(default=0)
    blocked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'identity'


def privileged(user):
    return bool(user.is_staff or user.is_platform_admin or user.is_superuser
                or user.has_capability('identity.manage', tenant_id=user.tenant_id))


def credential_for(user):
    return MfaCredential.objects.filter(user_id=user.pk).first()


def required(user, credential=None):
    credential = credential if credential is not None else credential_for(user)
    return bool((credential and credential.enabled_at) or
                (getattr(settings, 'TIBATRACE_PRIVILEGED_MFA_REQUIRED', False) and privileged(user)))


def configuration():
    keys = getattr(settings, 'TIBATRACE_MFA_ENCRYPTION_KEYS', {})
    active = getattr(settings, 'TIBATRACE_MFA_ACTIVE_KEY_ID', '')
    try:
        validate_document_keyring(keys, active)
        if len(keys) > 16:
            raise DocumentEncryptionError('MFA keyring is too large.')
    except DocumentEncryptionError:
        raise ValidationError('MFA encryption keys require secure configuration by operations.') from None
    return keys, active


def _audit(user, action, *, outcome='SUCCESS', method=''):
    from apps.audit.service import log_audit, log_platform_audit
    fields = dict(actor_id=user.pk, action=action, model_name='identity.MfaCredential',
                  object_id=str(user.pk), outcome=outcome, metadata={'method': method} if method else {})
    if user.tenant_id:
        log_audit(tenant_id=user.tenant_id, **fields)
    else:
        log_platform_audit(**fields)


def _seal(user, secret):
    keys, active = configuration()
    return base64.b64encode(encrypt_document_bytes(secret.encode(), key_id=active,
        key=keys[active], associated_data=f'TibaTrace MFA user:{user.pk}')).decode()


def _unseal(credential):
    keys, _ = configuration()
    try:
        secret, key_id = decrypt_document_bytes(base64.b64decode(credential.protected_secret, validate=True),
            keyring=keys, associated_data=f'TibaTrace MFA user:{credential.user_id}')
        if key_id is None:
            raise ValueError('Unencrypted MFA material refused.')
        return secret.decode('ascii')
    except (ValueError, DocumentEncryptionError, UnicodeError):
        raise ValidationError('MFA key recovery requires operations review.') from None


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _recovery_codes(credential):
    raw_codes = [secrets.token_hex(16) for _ in range(10)]
    codes = ['-'.join(code[i:i+8] for i in range(0, 32, 8)) for code in raw_codes]
    # Each code has 128 random bits. Only hashes are persisted.
    credential.recovery_hashes = [_digest(code.replace('-', '')) for code in codes]
    return codes


@transaction.atomic
def begin_enrollment(user, nonce):
    import pyotp

    # Lock the parent even when the credential has not yet been created.
    from django.contrib.auth import get_user_model
    get_user_model().objects.select_for_update().get(pk=user.pk)
    credential, _ = MfaCredential.objects.get_or_create(user=user)
    credential = MfaCredential.objects.select_for_update().get(pk=user.pk)
    if credential.enabled_at:
        raise ValidationError('MFA is already enrolled. Use the governed reset before replacing it.')
    if credential.blocked_until and credential.blocked_until > timezone.now():
        raise ValidationError('Too many verification attempts. Wait before restarting enrollment.')
    secret = pyotp.random_base32()
    credential.protected_secret = _seal(user, secret)
    credential.pending_nonce_hash = _digest(nonce)
    credential.pending_expires_at = timezone.now() + timedelta(minutes=10)
    credential.last_step = -1
    credential.save()
    _audit(user, 'MFA_ENROLLMENT_STARTED')
    return {'secret': secret, 'provisioning_uri': pyotp.TOTP(secret).provisioning_uri(
        name=user.get_username(), issuer_name='TibaTrace'), 'expires_in_seconds': 600}


@transaction.atomic
def verify(user, code, *, enrollment_nonce=None):
    """Returns None on refusal so throttling commits before the view denies it."""
    import pyotp
    credential = MfaCredential.objects.select_for_update().filter(user=user).first()
    now = timezone.now()
    if not credential or (credential.blocked_until and credential.blocked_until > now):
        return None
    enrolling = enrollment_nonce is not None
    if enrolling:
        if (credential.enabled_at or not credential.pending_expires_at or credential.pending_expires_at <= now
                or not hmac.compare_digest(credential.pending_nonce_hash, _digest(enrollment_nonce))):
            return None
    elif not credential.enabled_at:
        return None
    method, accepted_step, recovery_index = '', None, None
    if len(code) == 6 and code.isascii() and code.isdigit():
        totp = pyotp.TOTP(_unseal(credential))
        step = int(time.time()) // 30
        for candidate in (step + 1, step, step - 1):
            if candidate > credential.last_step and totp.verify(code, for_time=candidate * 30):
                method, accepted_step = 'TOTP', candidate
                break
    elif not enrolling:
        normalized = code.replace('-', '').lower().strip()
        digest = _digest(normalized)
        for index, expected in enumerate(credential.recovery_hashes):
            if hmac.compare_digest(expected, digest):
                method, recovery_index = 'RECOVERY', index
    if not method:
        credential.failed_attempts += 1
        credential.blocked_until = now + timedelta(seconds=min(900, 2 ** min(credential.failed_attempts, 10)))
        credential.save(update_fields=['failed_attempts', 'blocked_until'])
        _audit(user, 'MFA_VERIFICATION_REFUSED', outcome='DENIED')
        return None
    if accepted_step is not None:
        credential.last_step = accepted_step
    if recovery_index is not None:
        credential.recovery_hashes.pop(recovery_index)
    codes = None
    if enrolling:
        credential.enabled_at = now
        credential.pending_expires_at = None
        credential.pending_nonce_hash = ''
        credential.version = uuid.uuid4()
        codes = _recovery_codes(credential)
    credential.failed_attempts, credential.blocked_until = 0, None
    credential.save()
    _audit(user, 'MFA_ENROLLED' if enrolling else 'MFA_VERIFIED', method=method)
    return {'version': str(credential.version), 'method': method, 'recovery_codes': codes}


def mark_session(request, version):
    request.session.cycle_key()
    request.session['mfa_version'] = version
    request.session['mfa_verified_at'] = int(time.time())


def session_status(request):
    credential = credential_for(request.user)
    needs = required(request.user, credential)
    version = request.session.get('mfa_version')
    valid = bool(credential and credential.enabled_at and version == str(credential.version)
                 and _recent(request.session.get('mfa_verified_at')))
    stale = bool(version and (not credential or version != str(credential.version)))
    return {'required': needs or stale, 'enrolled': bool(credential and credential.enabled_at),
            'verified': valid, 'reauthenticate': stale or (needs and not valid and
                not _recent(request.session.get('mfa_password_at'), seconds=600))}


def _recent(value, *, seconds=43200):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= time.time() - value <= seconds


def token_allowed(user, token):
    credential = credential_for(user)
    if token.get('mfa_version') and (not credential or token['mfa_version'] != str(credential.version)):
        return False
    if not required(user, credential):
        return True
    return bool(credential and credential.enabled_at and token.get('mfa_version') == str(credential.version)
                and _recent(token.get('mfa_verified_at')))
