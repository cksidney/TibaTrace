# ruff: noqa: F811 -- imported shared pytest fixture is injected by name.
import json

import pytest
from tests.test_dha_integration import world  # noqa: F401

from apps.integrations.dha_catalogue import OPERATIONS
from apps.integrations.dha_client import DhaClient, DhaError

pytestmark = pytest.mark.django_db


class Response:
    def __init__(self, body, status=200):
        self.status_code = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield json.dumps(self.body).encode()


def transport(monkeypatch, responses):
    calls = []
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            assert self.trust_env is False
            return responses.pop(0)
    monkeypatch.setattr("apps.integrations.dha_client.requests.Session", Session)
    return calls


def test_token_reuse_and_facility_headers_are_tenant_scoped(world, monkeypatch):
    calls = transport(monkeypatch, [Response({"access_token": "actual-token", "token_type": "Bearer", "expires_in": 300}), Response({}), Response({})])
    c = DhaClient(world["connection"])
    c.call(OPERATIONS["security_labels"], "/shr/security-labels", {})
    c.call(OPERATIONS["security_labels"], "/shr/security-labels", {})
    assert len(calls) == 3
    assert calls[0][2]["data"] == {"client_id": "client-test", "client_secret": "test-client-secret"}
    assert calls[1][2]["headers"]["X-Facility-Id"] == "FID-TEST-1"
    assert calls[1][2]["headers"]["Authorization"] == "Bearer actual-token"
    assert calls[0][2]["verify"] is True and calls[0][2]["allow_redirects"] is False


def test_redirect_and_invalid_tokens_fail_closed(world, monkeypatch):
    transport(monkeypatch, [Response({}, 302)])
    with pytest.raises(DhaError):
        DhaClient(world["connection"]).token()
    transport(monkeypatch, [Response({"access_token": "bad\ntoken", "expires_in": 300})])
    with pytest.raises(DhaError, match="INVALID_TOKEN_RESPONSE"):
        DhaClient(world["connection"]).token()


def test_multipart_is_encoded_without_changing_auth_or_url(world, monkeypatch):
    calls = transport(monkeypatch, [Response({"access_token": "actual-token", "expires_in": 300}), Response({})])
    c = DhaClient(world["connection"])
    c.call(OPERATIONS["preauth_create"], "/preauths", {"diagnoses": [{"code": "A"}]}, files=[("file_blob", ("rx.pdf", b"pdf", "application/pdf"))])
    kwargs = calls[-1][2]
    assert kwargs["json"] is None and kwargs["data"] is None
    assert kwargs["files"] == [("diagnoses", (None, '[{"code": "A"}]')), ("file_blob", ("rx.pdf", b"pdf", "application/pdf"))]


def test_provider_outage_opens_only_this_connections_circuit(world, monkeypatch):
    calls = transport(monkeypatch, [Response({"access_token": "actual-token", "expires_in": 300})] + [Response({}, 503) for _ in range(3)])
    client = DhaClient(world["connection"])
    for _ in range(3):
        with pytest.raises(DhaError):
            client.call(OPERATIONS["security_labels"], "/shr/security-labels", {})
    with pytest.raises(DhaError, match="CIRCUIT_OPEN"):
        client.call(OPERATIONS["security_labels"], "/shr/security-labels", {})
    assert len(calls) == 4
