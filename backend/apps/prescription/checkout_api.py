from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DomainError
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.prescription.checkout import CheckoutService
from apps.prescription.payment_api.serializers import CheckoutCommandSerializer
from apps.prescription.services.clinical_dispensing import _require_capability


def checkout_response(request, source):
    # Source is obtained through the caller's tenant/branch-scoped queryset.
    if request.method == "GET":
        caps = (
            "prescriptions.record_payment",
            "pos.payment.status.view",
            "pos.transaction.create",
            "pos.payment.cash.accept",
        )
        if not any(request.user.has_capability(c, tenant_id=source.tenant_id) for c in caps):
            raise PermissionDenied("Payment read authority is required.")
        return Response(CheckoutService.snapshot(source=source, actor=request.user))
    serializer = CheckoutCommandSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        if data["operation"] in {"request_void", "complete_void"}:
            from apps.prescription.checkout_void import CheckoutVoidService
            result = CheckoutVoidService.run(source=source, actor=request.user, device_id=data["device_id"], approve=data["operation"] == "complete_void", reason=data["reason"], references=data["payment_references"])
        elif data["operation"] == "finish":
            result = CheckoutService.finish_paid(source=source, actor=request.user, device_id=data["device_id"])
        elif data["operation"] == "query":
            result = CheckoutService.query_provider(source=source, actor=request.user)
        elif data["operation"] == "fiscal":
            from apps.prescription.fiscal import FiscalService

            _require_capability(request.user, source.tenant_id, "pos.document.print")
            row = FiscalService.enqueue(source=source)
            if row:
                FiscalService.submit(row)
            result = CheckoutService.snapshot(source=source, actor=request.user)
        elif data["operation"] == "initiate":
            result = CheckoutService.initiate(
                source=source,
                actor=request.user,
                device_id=data["device_id"],
                tender_type=data["tender_type"],
                amount=data["amount"],
                phone_number=data["phone_number"],
                idempotency_key=data["idempotency_key"],
            )
        else:
            result = CheckoutService.collect(
                source=source,
                actor=request.user,
                device_id=data["device_id"],
                tender_type=data["tender_type"],
                amount=data["amount"],
                cash_received=data["cash_received"],
                reference=data["reference"],
                idempotency_key=data["idempotency_key"],
            )
    except (DomainError, ValueError) as exc:
        raise ValidationError(exc.messages if isinstance(exc, DomainError) else str(exc)) from exc
    return Response(result)


from rest_framework.decorators import api_view, authentication_classes, permission_classes  # noqa: E402
from rest_framework.permissions import AllowAny  # noqa: E402


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def mpesa_callback(request):
    # Daraja callbacks do not carry a provider signature. Acknowledgement never
    # records money, trusts callback fields, queries an arbitrary reference or
    # triggers external I/O. The bounded scheduled worker queries only attempts
    # TibaTrace itself created, with that branch's authenticated Daraja account.
    return Response({"ResultCode": 0, "ResultDesc": "Received; settlement requires authenticated status verification."})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def provider_callback(request, provider_code):
    """Handle a provider-authenticated callback for an installed card adapter.

    The provider must echo TibaTrace's request reference. It is used only to
    locate the tenant-scoped attempt; the adapter must authenticate and parse
    the payload before the payment ledger can change.
    """
    from apps.prescription.payment_connections import provider_adapter
    from apps.prescription.payment_models import PaymentAttempt
    from apps.prescription.payment_orchestration import PaymentEventService
    from apps.prescription.payment_providers import normalize_provider_code

    try:
        code = normalize_provider_code(provider_code)
    except ValueError:
        return Response({"accepted": True}, status=202)
    if code in {"MANUAL", "FAKE", "MPESA"}:
        return Response({"accepted": True}, status=202)
    # Signature schemes commonly cover the exact wire bytes, not re-encoded
    # JSON. Capture them before DRF consumes its parser stream.
    raw_body = request.body
    payload = request.data
    if not isinstance(payload, dict):
        return Response({"accepted": True}, status=202)
    request_reference = str(payload.get("request_reference") or "").strip()
    if not request_reference or len(request_reference) > 255:
        return Response({"accepted": True}, status=202)
    attempts = list(
        PaymentAttempt.all_objects.filter(provider=code, request_reference=request_reference)
        .select_related(
            "tenant",
            "payment_tender__payment_intent__branch",
        )[:2]
    )
    if len(attempts) != 1:
        return Response({"accepted": True}, status=202)
    attempt = attempts[0]
    intent = attempt.payment_tender.payment_intent
    try:
        adapter = provider_adapter(tenant=attempt.tenant, branch=intent.branch, provider_code=code)
    except Exception:  # noqa: BLE001 - preserve provider retry when tenant configuration is unavailable
        return Response({"accepted": False}, status=503)
    try:
        headers = {str(key): str(value) for key, value in request.headers.items()}
        event = adapter.parse_event(headers=headers, payload=payload)
        # Reject a provider event that parses to another attempt. The request
        # reference used to route the request is not itself trusted as evidence.
        if event.request_reference != attempt.request_reference:
            return Response({"accepted": True}, status=202)
        authenticated = bool(adapter.authenticate_event(headers=headers, payload=payload, raw_body=raw_body))
    except Exception:  # noqa: BLE001 - never expose adapter or tenant details at public callback ingress
        return Response({"accepted": True}, status=202)
    try:
        PaymentEventService.apply(
            tenant=attempt.tenant,
            provider_code=code,
            event=event,
            raw_payload=payload,
            authenticated=authenticated,
        )
    except Exception:  # noqa: BLE001 - request provider retry without exposing internal state
        return Response({"accepted": False}, status=503)
    return Response({"accepted": True}, status=202)
