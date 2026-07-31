"""POS payment API.

Read-only over the ledger; every mutation goes through a service action. The
serializers mark all financial fields read-only, so there is no PATCH route to
an amount or a status -- the ledger is only writable through the paths that
enforce allocation limits, idempotency and separation of duties.
"""
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.prescription.models import DispensingEpisode
from apps.prescription.payment_api.serializers import (
    AllocateTenderSerializer,
    CardConfirmSerializer,
    CashSettleSerializer,
    CreateIntentSerializer,
    InitiateProviderSerializer,
    PaymentIntentSerializer,
    PaymentTenderSerializer,
    ReverseSettlementSerializer,
)
from apps.prescription.payment_models import PaymentIntent, PaymentSettlement, PaymentTender
from apps.prescription.payment_orchestration import PaymentAttemptService, SplitTenderService
from apps.prescription.payment_services import (
    PaymentIntentService,
    PaymentReversalService,
    PaymentSettlementService,
    PaymentTenderService,
)


def _tenant(request):
    return getattr(request, "tenant", None)


def _handle(fn):
    """Run a service call, preserving the distinction between 403 and 400."""
    try:
        return fn()
    except PermissionDenied:
        # Must surface as 403; flattening it into a 400 would present an
        # authorisation failure as bad input.
        raise
    except DjangoValidationError as exc:
        raise ValidationError(str(exc)) from exc


class PaymentIntentViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentIntentSerializer

    def get_queryset(self):
        tenant = _tenant(self.request)
        if not tenant:
            return PaymentIntent.all_objects.filter(tenant_id=get_current_tenant_id())
        return PaymentIntent.all_objects.filter(tenant=tenant)

    @action(detail=False, methods=["post"])
    def create_intent(self, request):
        serializer = CreateIntentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        episode = DispensingEpisode.all_objects.filter(
            tenant=_tenant(request), pk=data["dispensing_episode_id"]
        ).first()
        if episode is None:
            # Deliberately not distinguishing "wrong tenant" from "absent": the
            # response must not confirm that another tenant's episode exists.
            raise ValidationError("Dispensing episode not found.")

        intent = _handle(
            lambda: PaymentIntentService.create(
                episode=episode,
                amount_due=data["amount_due"],
                actor=request.user,
                idempotency_key=data["idempotency_key"],
                currency=data["currency"],
                device_id=data["device_id"],
                register_id=data["register_id"],
            )
        )
        return Response(PaymentIntentSerializer(intent).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def tenders(self, request, pk=None):
        intent = self.get_object()
        serializer = AllocateTenderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tender = _handle(
            lambda: PaymentTenderService.allocate(
                intent=intent,
                tender_type=data["tender_type"],
                allocated_amount=data["allocated_amount"],
                actor=request.user,
                idempotency_key=data["idempotency_key"],
                provider=data["provider"],
            )
        )
        return Response(PaymentTenderSerializer(tender).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        """Allocation totals for the till."""
        intent = self.get_object()
        summary = SplitTenderService.summary(intent=intent)
        from apps.core.money import format_money

        return Response({key: format_money(value) for key, value in summary.items()})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        intent = self.get_object()
        result = _handle(
            lambda: PaymentIntentService.cancel(
                intent=intent, actor=request.user, reason=request.data.get("reason", "")
            )
        )
        return Response(PaymentIntentSerializer(result).data)


class PaymentTenderViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentTenderSerializer

    def get_queryset(self):
        tenant = _tenant(self.request)
        if not tenant:
            return PaymentTender.all_objects.filter(tenant_id=get_current_tenant_id())
        return PaymentTender.all_objects.filter(tenant=tenant)

    @action(detail=True, methods=["post"], url_path="cash-settle")
    def cash_settle(self, request, pk=None):
        tender = self.get_object()
        serializer = CashSettleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        _handle(
            lambda: PaymentSettlementService.settle_cash(
                tender=tender,
                cash_received=data["cash_received"],
                actor=request.user,
                idempotency_key=data["idempotency_key"],
                register_id=data["register_id"],
            )
        )
        tender.refresh_from_db()
        return Response(PaymentTenderSerializer(tender).data)

    @action(detail=True, methods=["post"], url_path="card-confirm")
    def card_confirm(self, request, pk=None):
        tender = self.get_object()
        serializer = CardConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        _handle(
            lambda: PaymentSettlementService.confirm_card(
                tender=tender,
                approval_reference=data["approval_reference"],
                approved_amount=data["approved_amount"],
                actor=request.user,
                idempotency_key=data["idempotency_key"],
            )
        )
        tender.refresh_from_db()
        return Response(PaymentTenderSerializer(tender).data)

    @action(detail=True, methods=["post"])
    def initiate(self, request, pk=None):
        """Ask a provider to collect. Records only that we asked."""
        tender = self.get_object()
        serializer = InitiateProviderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        attempt, result = _handle(
            lambda: PaymentAttemptService.initiate(
                tender=tender,
                actor=request.user,
                provider_code=serializer.validated_data["provider"],
            )
        )
        tender.refresh_from_db()
        return Response(
            {
                "tender": PaymentTenderSerializer(tender).data,
                "attempt_id": str(attempt.id),
                "request_reference": attempt.request_reference,
                "accepted": result.accepted,
                "provider_status": result.provider_status,
                "customer_message": result.customer_message,
                "retryable": result.retryable,
                "failure_code": result.failure_code,
                "failure_reason": result.failure_reason,
                # Stated explicitly so no client mistakes acceptance for payment.
                "settled": False,
            }
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        tender = self.get_object()
        result = _handle(
            lambda: PaymentTenderService.cancel(
                tender=tender, actor=request.user, reason=request.data.get("reason", "")
            )
        )
        return Response(PaymentTenderSerializer(result).data)


class PaymentSettlementViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentTenderSerializer

    def get_queryset(self):
        tenant = _tenant(self.request)
        if not tenant:
            return PaymentSettlement.all_objects.filter(tenant_id=get_current_tenant_id())
        return PaymentSettlement.all_objects.filter(tenant=tenant)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        settlement = self.get_object()
        serializer = ReverseSettlementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        reversal = _handle(
            lambda: PaymentReversalService.request(
                settlement=settlement,
                amount=data["amount"],
                reason=data["reason"],
                actor=request.user,
                idempotency_key=data["idempotency_key"],
            )
        )
        return Response(
            {
                "reversal_id": str(reversal.id),
                "status": reversal.status,
                # Requesting is not completing: a second, different person must
                # approve before value is given back.
                "requires_separate_approval": True,
            },
            status=status.HTTP_202_ACCEPTED,
        )
