import base64
import time
from types import SimpleNamespace

import pyotp
import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity import mfa
from apps.identity.models import User

pytestmark = pytest.mark.django_db
PASSWORD = 'Mfa-Current-Pass-764315!'
SESSION = '/api/identity/session/'


@pytest.fixture(autouse=True)
def mfa_configuration(settings):
    settings.TIBATRACE_MFA_ENCRYPTION_KEYS = {'mfa-test': base64.urlsafe_b64encode(b'M' * 32).decode()}
    settings.TIBATRACE_MFA_ACTIVE_KEY_ID = 'mfa-test'
    settings.TIBATRACE_PRIVILEGED_MFA_REQUIRED = False
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def clock(monkeypatch):
    value = [int(time.time())]
    monkeypatch.setattr(mfa, 'time', SimpleNamespace(time=lambda: value[0]))
    return value


@pytest.fixture
def staff(tenant_a):
    return User.objects.create_user(username='mfa-staff', password=PASSWORD, tenant=tenant_a, is_staff=True)


def login(staff):
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get(SESSION).json()['csrf_token']
    response = client.post(SESSION, {'username': staff.username, 'password': PASSWORD}, format='json', HTTP_X_CSRFTOKEN=csrf)
    assert response.status_code == 200
    client.credentials(HTTP_X_CSRFTOKEN=response.json()['csrf_token'])
    return client


def command(client, operation, **data):
    return client.post(f'/api/identity/mfa/{operation}/', data, format='json')


def enroll(staff, clock):
    result = mfa.begin_enrollment(staff, 'test-enrollment-nonce')
    proof = mfa.verify(staff, pyotp.TOTP(result['secret']).at(clock[0]), enrollment_nonce='test-enrollment-nonce')
    assert proof and len(proof['recovery_codes']) == 10
    clock[0] += 30
    return result['secret'], proof


def test_required_password_session_cannot_read_business_or_admin(staff, settings):
    settings.TIBATRACE_PRIVILEGED_MFA_REQUIRED = True
    client = login(staff)
    assert client.get(SESSION).json()['mfa'] == {'required': True, 'enrolled': False, 'verified': False, 'reauthenticate': False}
    for path in ['/api/patients/', '/api/identity/me/', '/admin/', '/admin-shell/', '/api/hq/overview/']:
        response = client.get(path)
        assert response.status_code == 403
        assert response.json()['code'] == 'mfa_required'


def test_browser_enrollment_confidentiality_csrf_and_verified_gate(staff, settings, clock):
    settings.TIBATRACE_PRIVILEGED_MFA_REQUIRED = True
    client = login(staff)
    assert command(client, 'enroll', current_password='wrong').status_code == 400
    response = command(client, 'enroll', current_password=PASSWORD)
    assert response.status_code == 200
    assert response['Cache-Control'] == 'no-store'
    secret = response.json()['secret']
    assert '<svg' in response.json()['qr_svg']
    row = mfa.MfaCredential.objects.get(user=staff)
    assert secret not in row.protected_secret
    assert mfa._unseal(row) == secret
    other = login(staff)
    assert command(other, 'confirm', code=pyotp.TOTP(secret).at(clock[0])).status_code == 400
    code = pyotp.TOTP(secret).at(clock[0])
    response = command(client, 'confirm', code=code)
    assert response.status_code == 200
    assert response.json()['mfa']['verified'] is True
    assert len(response.json()['recovery_codes']) == 10
    assert 'recovery_codes' not in client.get(SESSION).json()
    assert client.get('/api/identity/me/').status_code == 200
    assert secret not in str(list(AuditEvent.all_objects.values_list('metadata', flat=True)))
    without_csrf = APIClient(enforce_csrf_checks=True)
    without_csrf.cookies = client.cookies
    assert command(without_csrf, 'recovery', current_password=PASSWORD, code=code).status_code == 403


def test_replay_recovery_single_use_and_throttle(staff, clock):
    secret, proof = enroll(staff, clock)
    code = pyotp.TOTP(secret).at(clock[0])
    assert mfa.verify(staff, code)
    assert mfa.verify(staff, code) is None
    row = mfa.MfaCredential.objects.get(user=staff)
    assert row.failed_attempts == 1 and row.blocked_until
    assert mfa.verify(staff, proof['recovery_codes'][0]) is None
    row.blocked_until = None
    row.save(update_fields=['blocked_until'])
    assert mfa.verify(staff, proof['recovery_codes'][0])['method'] == 'RECOVERY'
    assert mfa.verify(staff, proof['recovery_codes'][0]) is None


def test_token_password_only_old_refresh_and_stale_access_cannot_bypass(staff, clock, settings):
    client = APIClient()
    old = client.post('/api/identity/token/', {'username': staff.username, 'password': PASSWORD}, format='json').json()
    secret, _ = enroll(staff, clock)
    assert client.post('/api/identity/token/refresh/', {'refresh': old['refresh']}, format='json').status_code == 401
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + old['access'])
    assert client.get('/api/identity/me/').status_code == 401
    client.credentials()
    assert client.post('/api/identity/token/', {'username': staff.username, 'password': PASSWORD}, format='json').status_code == 401
    row = mfa.MfaCredential.objects.get(user=staff)
    row.blocked_until = None
    row.save(update_fields=['blocked_until'])
    response = client.post('/api/identity/token/', {'username': staff.username, 'password': PASSWORD,
        'otp_code': pyotp.TOTP(secret).at(clock[0])}, format='json')
    assert response.status_code == 200
    tokens = response.json()
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + tokens['access'])
    assert client.get('/api/identity/me/').status_code == 200
    row.version = __import__('uuid').uuid4()
    row.save(update_fields=['version'])
    assert client.get('/api/identity/me/').status_code == 401
    client.credentials()
    assert client.post('/api/identity/token/refresh/', {'refresh': tokens['refresh']}, format='json').status_code == 401


def test_reset_requires_both_factors_revokes_other_sessions_and_keeps_enforcement(staff, clock, settings):
    settings.TIBATRACE_PRIVILEGED_MFA_REQUIRED = True
    secret, proof = enroll(staff, clock)
    one, two = login(staff), login(staff)
    assert command(one, 'verify', code=proof['recovery_codes'][0]).status_code == 200
    assert command(two, 'verify', code=proof['recovery_codes'][1]).status_code == 200
    assert command(one, 'reset', current_password='wrong', code=proof['recovery_codes'][2]).status_code == 400
    response = command(one, 'reset', current_password=PASSWORD, code=proof['recovery_codes'][2])
    assert response.status_code == 200
    assert response.json()['mfa']['required'] and not response.json()['mfa']['enrolled']
    assert two.get('/api/identity/me/').status_code == 403
    assert not mfa.MfaCredential.objects.get(user=staff).protected_secret


def test_missing_key_wrong_user_expiry_and_audit_refusal_fail_closed(staff, clock, settings, monkeypatch):
    secret, proof = enroll(staff, clock)
    row = mfa.MfaCredential.objects.get(user=staff)
    row.user_id = staff.pk + 5000
    with pytest.raises(ValidationError):
        mfa._unseal(row)
    settings.TIBATRACE_MFA_ENCRYPTION_KEYS = {}
    with pytest.raises(ValidationError):
        mfa.verify(staff, pyotp.TOTP(secret).at(clock[0]))
    settings.TIBATRACE_MFA_ENCRYPTION_KEYS = {'mfa-test': base64.urlsafe_b64encode(b'M' * 32).decode()}
    def deny(*args, **kwargs):
        raise RuntimeError('audit unavailable')
    monkeypatch.setattr(mfa, '_audit', deny)
    with pytest.raises(RuntimeError):
        mfa.verify(staff, proof['recovery_codes'][0])
    assert len(mfa.MfaCredential.objects.get(user=staff).recovery_hashes) == 10


def test_expired_pending_enrollment_and_unenrolled_token_are_rejected(staff, clock, settings):
    from datetime import timedelta

    from django.utils import timezone
    pending = mfa.begin_enrollment(staff, 'pending-nonce')
    mfa.MfaCredential.objects.filter(user=staff).update(pending_expires_at=timezone.now()-timedelta(seconds=1))
    assert mfa.verify(staff, pyotp.TOTP(pending['secret']).at(clock[0]), enrollment_nonce='pending-nonce') is None
    settings.TIBATRACE_PRIVILEGED_MFA_REQUIRED = True
    assert not mfa.token_allowed(staff, {})


@pytest.mark.django_db(transaction=True)
def test_postgresql_concurrent_verification_consumes_code_once(tenant_a, settings):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connection

    if connection.vendor != 'postgresql':
        pytest.skip('PostgreSQL row-lock concurrency check')
    user = User.objects.create_user(username='mfa-concurrent', tenant=tenant_a, password=PASSWORD)
    setup = mfa.begin_enrollment(user, 'concurrent-nonce')
    enrolled = mfa.verify(user, pyotp.TOTP(setup['secret']).now(), enrollment_nonce='concurrent-nonce')
    code = enrolled['recovery_codes'][0]
    barrier = Barrier(2)
    def attempt():
        close_old_connections()
        try:
            actor = User.objects.get(pk=user.pk)
            barrier.wait(timeout=10)
            return mfa.verify(actor, code) is not None
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(attempt) for _ in range(2)]
        assert sorted(future.result(timeout=30) for future in futures) == [False, True]
