"""Security-upgrade acceptance: refusals must precede business processing."""
from unittest.mock import Mock

import pytest
from django.test import override_settings
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.renderers import AdminRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView


@pytest.mark.parametrize("content_type,body", [
    ("application/json", b'{"note":"' + b"synthetic-sensitive-value" * 20 + b'"}'),
    ("application/x-www-form-urlencoded", b"note=" + b"synthetic-sensitive-value" * 20),
])
def test_oversized_parsed_body_is_413_without_business_processing_or_body_echo(content_type, body):
    processed = Mock()

    class PayloadView(APIView):
        authentication_classes = []
        permission_classes = []
        renderer_classes = [JSONRenderer]

        def post(self, request):
            payload = request.data
            processed(payload)
            return Response({"accepted": True})

    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=128):
        response = PayloadView.as_view()(APIRequestFactory().generic("POST", "/payload-test/", body, content_type=content_type))
        response.render()
    assert response.status_code == 413
    assert response.data["code"] == "request_too_large"
    assert "request_id" in response.data
    assert b"synthetic-sensitive-value" not in response.content
    processed.assert_not_called()


def test_small_json_body_still_reaches_the_business_handler():
    processed = Mock()

    class PayloadView(APIView):
        authentication_classes = []
        permission_classes = []
        renderer_classes = [JSONRenderer]

        def post(self, request):
            processed(request.data)
            return Response({"accepted": True})

    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=128):
        response = PayloadView.as_view()(APIRequestFactory().post("/payload-test/", {"note": "confirmed"}, format="json"))
    assert response.status_code == 200
    processed.assert_called_once_with({"note": "confirmed"})


def test_invalid_write_admin_render_does_not_call_a_get_denied_by_permissions():
    get_called = Mock()

    class WritesOnly(BasePermission):
        def has_permission(self, request, view):
            return request.method == "POST"

    class Input(serializers.Serializer):
        confirmed = serializers.BooleanField(required=True)

    class WriteView(APIView):
        authentication_classes = []
        permission_classes = [WritesOnly]
        renderer_classes = [AdminRenderer]

        def get(self, request):
            get_called()
            return Response({"secret": "private-get-representation"})

        def post(self, request):
            serializer = Input(data=request.data)
            serializer.is_valid(raise_exception=True)
            return Response({"accepted": True})

    response = WriteView.as_view()(APIRequestFactory().post("/renderer-test/", {}, format="json"))
    response.render()
    assert response.status_code == 400
    assert b"private-get-representation" not in response.content
    get_called.assert_not_called()
