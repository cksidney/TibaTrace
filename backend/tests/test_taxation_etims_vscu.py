"""The fiscal workspace shares the payment outbox and fails closed."""
import uuid
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.identity.models import Role, User, UserRole
from apps.organizations.models import Location, Organization
from apps.prescription.fiscal import FiscalService
from apps.prescription.fiscal_models import FiscalSubmission
from apps.tenancy.models import Tenant


@pytest.fixture
def fiscal_world(db):
    tenant = Tenant.objects.create(name="Fiscal workspace", slug="fiscal-workspace")
    org = Organization.all_objects.create(tenant=tenant, code="FISC", name="Fiscal")
    branch = Location.all_objects.create(tenant=tenant, organization=org, code="MAIN", name="Main")
    owner = User.objects.create_user(username="fiscal-owner", tenant=tenant, is_superuser=True)
    reader = User.objects.create_user(username="fiscal-reader", tenant=tenant)
    role = Role.all_objects.create(tenant=tenant, code="FISCAL_READ", name="Fiscal read", capabilities=["pos.report.read"])
    UserRole.all_objects.create(tenant=tenant, user=reader, role=role)
    client = APIClient()
    client.force_authenticate(user=owner)
    return tenant, branch, owner, reader, client


def make_row(world, **values):
    tenant, branch, *_ = world
    return FiscalSubmission.all_objects.create(tenant=tenant, branch=branch, source_kind="RETAIL", source_id=uuid.uuid4(), **values)


def test_profile_get_never_creates_configuration_or_exposes_secrets(fiscal_world, monkeypatch):
    tenant, branch, _, _, client = fiscal_world
    import json
    monkeypatch.setenv("TIBATRACE_CHECKOUT_CONNECTIONS", json.dumps({f"{tenant.pk}/{branch.pk}": {"VSCU": {"base_url": "https://private-service.example", "token": "secret-must-stay-server-side"}}}))
    before = FiscalSubmission.all_objects.count()
    response = client.get('/api/taxation/profile/')
    assert response.status_code == 200
    assert response.json()['branches'][0]['enabled'] is False
    assert response.json()['configuration_mode'] == 'SERVER_MANAGED'
    assert 'secret-must-stay-server-side' not in str(response.data)
    assert 'private-service' not in str(response.data)
    assert FiscalSubmission.all_objects.count() == before
    assert client.patch('/api/taxation/profile/', {'is_enabled': True}, format='json').status_code == 405


def test_lists_existing_outbox_and_only_accepted_evidence(fiscal_world):
    client = fiscal_world[-1]
    unknown = make_row(fiscal_world, status='UNKNOWN', response={'rcptSign': 'unverified'})
    accepted = make_row(fiscal_world, status='ACCEPTED', response={'rcptSign': 'accepted-signature'})
    body = client.get('/api/taxation/receipts/').json()
    rows = {row['id']: row for row in body['results']}
    assert body['count'] == 2
    assert rows[str(unknown.pk)]['receipt'] is None
    assert rows[str(accepted.pk)]['receipt'] == {'rcptSign': 'accepted-signature'}


@pytest.mark.parametrize('state', ['QUEUED', 'SENDING', 'UNKNOWN', 'ACCEPTED', 'REJECTED'])
def test_existing_invoice_never_retransmitted_by_workspace(fiscal_world, state):
    row = make_row(fiscal_world, status=state)
    with patch('apps.taxation.api.views.FiscalService.prepare') as prepare:
        response = fiscal_world[-1].post(f'/api/taxation/receipts/{row.pk}/retry/', {}, format='json')
    assert response.status_code == 409
    prepare.assert_not_called()
    row.refresh_from_db()
    assert row.status == state and row.attempts == 0


def test_reader_cannot_prepare_invoice(fiscal_world):
    reader, client = fiscal_world[-2:]
    row = make_row(fiscal_world)
    client.force_authenticate(user=reader)
    assert client.get('/api/taxation/receipts/').status_code == 200
    assert client.post(f'/api/taxation/receipts/{row.pk}/retry/', {}, format='json').status_code == 403


def test_foreign_tenant_receipt_is_hidden(fiscal_world):
    row = make_row(fiscal_world)
    other = Tenant.objects.create(name='Other', slug='fiscal-other')
    user = User.objects.create_user(username='other-fiscal-owner', tenant=other, is_superuser=True)
    client = fiscal_world[-1]
    client.force_authenticate(user=user)
    assert client.get('/api/taxation/receipts/').json()['count'] == 0
    assert client.get(f'/api/taxation/receipts/{row.pk}/').status_code == 404
    assert client.post(f'/api/taxation/receipts/{row.pk}/retry/', {}, format='json').status_code == 404


def test_missing_configuration_cannot_prepare_invoice(fiscal_world, monkeypatch):
    monkeypatch.setenv('TIBATRACE_CHECKOUT_CONNECTIONS', '{}')
    row = make_row(fiscal_world)
    assert fiscal_world[-1].post(f'/api/taxation/receipts/{row.pk}/retry/', {}, format='json').status_code == 400
    row.refresh_from_db()
    assert row.status == 'NOT_CONFIGURED' and row.invoice_number is None and row.payload == {}


def test_bad_branch_filter_is_validation_error(fiscal_world):
    assert fiscal_world[-1].get('/api/taxation/receipts/?branch_id=invalid').status_code == 400


def test_no_capability_cannot_read_fiscal_queue(fiscal_world):
    tenant, _, _, _, client = fiscal_world
    client.force_authenticate(user=User.objects.create_user(username='unprivileged', tenant=tenant))
    assert client.get('/api/taxation/receipts/').status_code == 403


def test_vscu_redirect_is_not_followed_and_invoice_stays_unknown(fiscal_world):
    class RedirectResponse:
        status_code = 302

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_content(self, chunk_size):  # noqa: ARG002
            return iter(())

        def raise_for_status(self):
            raise AssertionError("redirect must be rejected before status handling")

    class FakeSession:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, **kwargs):
            self.url = url
            self.kwargs = kwargs
            return RedirectResponse()

    session = FakeSession()
    row = make_row(fiscal_world, status="QUEUED", payload={"invoice": "immutable"})
    with patch("apps.prescription.fiscal.FiscalService.prepare", return_value=row), patch(
        "apps.prescription.fiscal.vscu_config", return_value={"base_url": "https://vscu.example.test"}
    ), patch("requests.Session", return_value=session):
        FiscalService.submit(row)

    row.refresh_from_db()
    assert row.status == "UNKNOWN"
    assert session.trust_env is False
    assert session.kwargs["allow_redirects"] is False
    assert session.kwargs["timeout"] == 25
    assert session.kwargs["stream"] is True
    assert session.url == "https://vscu.example.test/trnsSales/saveSales"
