from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.inventory.models import InventoryChangeRequest
from apps.inventory.operations import decide_change, request_change, valuation
from apps.tenancy.models import Tenant

from .views import InventoryCapabilityPermission, TenantScopedQuerysetMixin


class ChangeSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.CharField(source="requested_by.username", read_only=True)
    decided_by_name = serializers.CharField(source="decided_by.username", read_only=True, allow_null=True)

    class Meta:
        model = InventoryChangeRequest
        fields = [
            "id",
            "kind",
            "status",
            "payload",
            "reason",
            "requested_by",
            "requested_by_name",
            "decided_by_name",
            "decision_reason",
            "decided_at",
            "created_at",
            "ledger_entry",
        ]
        read_only_fields = fields


class ChangeInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=InventoryChangeRequest._meta.get_field("kind").choices)
    payload = serializers.JSONField()
    reason = serializers.CharField(max_length=2000)
    idempotency_key = serializers.CharField(max_length=160)

    def validate_payload(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("An operation payload is required.")
        return value


class InventoryChangeViewSet(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    model = InventoryChangeRequest
    serializer_class = ChangeSerializer
    permission_classes = [permissions.IsAuthenticated, InventoryCapabilityPermission]

    def get_queryset(self):
        return super().get_queryset().select_related("requested_by", "decided_by").order_by("-created_at")

    def create(self, request):
        payload = ChangeInput(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            item = request_change(
                tenant=Tenant.objects.get(pk=self.tenant_id()), actor=request.user, **payload.validated_data
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return Response(self.get_serializer(item).data, status=201)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        class Decision(serializers.Serializer):
            approve = serializers.BooleanField()
            reason = serializers.CharField(max_length=2000)

        payload = Decision(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            item = decide_change(change=self.get_object(), actor=request.user, **payload.validated_data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return Response(self.get_serializer(item).data)

    @action(detail=False, methods=["get"])
    def valuation(self, request):
        return Response(valuation(self.tenant_id()), headers={"Cache-Control": "no-store"})
