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
