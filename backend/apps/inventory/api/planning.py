from decimal import Decimal

from django.core.exceptions import ValidationError as DomainError
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.identity.models import User
from apps.inventory import replenishment, warehouse
from apps.inventory.models import InventoryLocation, ReplenishmentPolicy, ReplenishmentRecommendation, WarehouseTask
from apps.inventory.operations import scoped
from apps.medicines.models import CommercialSKU
from apps.organizations.models import Location
from apps.tenancy.models import Tenant

from .views import InventoryCapabilityPermission, TenantScopedQuerysetMixin


class PolicySerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    unit = serializers.CharField(source="sku.package_definition.unit_of_measure", read_only=True)
    destination_name = serializers.CharField(source="destination.name", read_only=True)

    class Meta:
        model = ReplenishmentPolicy
        fields = [
            "id",
            "branch",
            "sku",
            "sku_code",
            "unit",
            "destination",
            "destination_name",
            "safety_stock",
            "reorder_point",
            "target_stock",
            "order_multiple",
            "lead_days",
            "enabled",
            "configured_by",
        ]
        read_only_fields = fields


class RecommendationSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    requisition_number = serializers.CharField(source="requisition.requisition_number", read_only=True, allow_null=True)

    class Meta:
        model = ReplenishmentRecommendation
        fields = [
            "id",
            "branch",
            "sku",
            "sku_code",
            "policy",
            "recommended_quantity",
            "snapshot",
            "status",
            "reason",
            "requisition",
            "requisition_number",
            "decided_by",
            "updated_at",
        ]
        read_only_fields = fields


class TaskSerializer(serializers.ModelSerializer):
    assigned_name = serializers.CharField(source="assigned_user.username", read_only=True, allow_null=True)

    class Meta:
        model = WarehouseTask
        fields = [
            "id",
            "branch",
            "task_type",
            "status",
            "priority",
            "assigned_user",
            "assigned_name",
            "source_type",
            "source_id",
            "evidence",
            "completed_by",
            "completed_at",
            "updated_at",
        ]
        read_only_fields = fields


class PlanningView(TenantScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated, InventoryCapabilityPermission]

    def command(self, callback):
        try:
            result = callback()
        except DomainError as exc:
            raise ValidationError(exc.messages) from exc
        return Response(self.get_serializer(result).data)


class PolicyViewSet(PlanningView):
    model, serializer_class = ReplenishmentPolicy, PolicySerializer
    select_related = ["sku__package_definition", "destination"]

    def create(self, request):
        class Input(serializers.Serializer):
            branch = serializers.UUIDField()
            sku = serializers.UUIDField()
            destination = serializers.UUIDField()
            safety_stock = serializers.DecimalField(max_digits=15, decimal_places=4)
            reorder_point = serializers.DecimalField(max_digits=15, decimal_places=4)
            target_stock = serializers.DecimalField(max_digits=15, decimal_places=4)
            order_multiple = serializers.IntegerField(min_value=1, max_value=1000000)
            lead_days = serializers.IntegerField(min_value=0, max_value=3650)
            enabled = serializers.BooleanField(default=True)

        data = Input(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)

        def run():
            for key, model in [("branch", Location), ("sku", CommercialSKU), ("destination", InventoryLocation)]:
                values[key] = scoped(model, self.tenant_id(), values[key])
            return replenishment.configure(tenant=Tenant.objects.get(pk=self.tenant_id()), actor=request.user, **values)

        return self.command(run)


class RecommendationViewSet(PlanningView):
    model, serializer_class = ReplenishmentRecommendation, RecommendationSerializer
    select_related = ["sku", "requisition"]

    @action(detail=False, methods=["post"])
    def refresh(self, request):
        replenishment.refresh(Tenant.objects.get(pk=self.tenant_id()))
        return Response({"detail": "Recommendations refreshed from stock, holds and pending demand."})

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        class Input(serializers.Serializer):
            approve = serializers.BooleanField()
            reason = serializers.CharField(max_length=2000)

        data = Input(data=request.data)
        data.is_valid(raise_exception=True)
        return self.command(
            lambda: replenishment.decide(item=self.get_object(), actor=request.user, **data.validated_data)
        )


class WarehouseTaskViewSet(PlanningView):
    model, serializer_class = WarehouseTask, TaskSerializer
    select_related = ["assigned_user"]

    @action(detail=False, methods=["get"])
    def context(self, request):
        sources = {}
        for kind, (model, _) in warehouse.SOURCES.items():
            records = model.all_objects.filter(tenant_id=self.tenant_id()).order_by("-updated_at")[:200]
            sources[kind] = [
                {
                    "id": str(row.pk),
                    "label": next(
                        (
                            str(getattr(row, key))
                            for key in (
                                "grn_number",
                                "manufacturer_batch_number",
                                "task_number",
                                "session_number",
                                "dispatch_number",
                                "transfer_number",
                                "document_number",
                            )
                            if getattr(row, key, None)
                        ),
                        str(row.pk),
                    ),
                    "status": getattr(row, "status", getattr(row, "quality_status", "")),
                }
                for row in records
            ]
        users = User.objects.filter(tenant_id=self.tenant_id(), is_active=True)
        return Response(
            {
                "sources": sources,
                "operators": [
                    {"id": str(user.pk), "name": user.username}
                    for user in users
                    if user.has_capability("inventory.manage", tenant_id=self.tenant_id())
                ],
                "skus": [
                    {
                        "id": str(row.pk),
                        "code": row.sku_code,
                        "name": row.display_name,
                        "unit": row.package_definition.unit_of_measure,
                    }
                    for row in CommercialSKU.all_objects.filter(
                        tenant_id=self.tenant_id(), status="ACTIVE", stock_tracking_required=True
                    )
                    .select_related("package_definition")
                    .order_by("sku_code")
                ],
            }
        )

    def create(self, request):
        class Input(serializers.Serializer):
            task_type = serializers.ChoiceField(choices=WarehouseTask.TaskType.choices)
            source_id = serializers.UUIDField()
            priority = serializers.IntegerField(min_value=1, max_value=5, default=1)

        data = Input(data=request.data)
        data.is_valid(raise_exception=True)
        return self.command(
            lambda: warehouse.create(
                tenant=Tenant.objects.get(pk=self.tenant_id()), actor=request.user, **data.validated_data
            )
        )

    @action(detail=True, methods=["post"], url_path="transition")
    def transition(self, request, pk=None):
        class Input(serializers.Serializer):
            action = serializers.ChoiceField(choices=["assign", "start", "complete", "cancel", "reopen"])
            evidence = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
            assignee = serializers.UUIDField(required=False, allow_null=True)

        data = Input(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        assignee = values.pop("assignee", None)

        def run():
            person = User.objects.filter(pk=assignee, tenant_id=self.tenant_id()).first() if assignee else None
            return warehouse.transition(item=self.get_object(), actor=request.user, assignee=person, **values)

        return self.command(run)


class BarcodeSerializer(serializers.ModelSerializer):
    class Meta:
        from apps.inventory.models import BarcodeMaster

        model = BarcodeMaster
        fields = ["id", "sku", "barcode", "barcode_type", "pack_conversion", "is_active"]
        read_only_fields = fields


class BarcodeViewSet(PlanningView):
    from apps.inventory.models import BarcodeMaster

    model, serializer_class = BarcodeMaster, BarcodeSerializer

    def create(self, request):
        class Input(serializers.Serializer):
            sku = serializers.UUIDField()
            barcode = serializers.CharField(max_length=128)
            barcode_type = serializers.CharField(max_length=64, default="GS1_128")
            pack_conversion = serializers.DecimalField(max_digits=10, decimal_places=4, min_value=Decimal("0.0001"))
            is_active = serializers.BooleanField(default=True)

        data = Input(data=request.data)
        data.is_valid(raise_exception=True)

        def run():
            from django.db import transaction

            from apps.audit.service import log_audit
            from apps.inventory.models import BarcodeMaster

            with transaction.atomic():
                tenant = Tenant.objects.select_for_update().get(pk=self.tenant_id())
                sku = scoped(CommercialSKU, tenant.pk, data.validated_data["sku"])
                values = dict(data.validated_data)
                values["sku"] = sku
                old = (
                    BarcodeMaster.all_objects.select_for_update()
                    .filter(tenant=tenant, barcode=values["barcode"])
                    .first()
                )
                if old and old.sku_id != sku.pk:
                    raise DomainError(
                        "This barcode already belongs to another SKU; deactivate it and reconcile catalogue identity."
                    )
                item, _ = BarcodeMaster.all_objects.update_or_create(
                    tenant=tenant, barcode=values.pop("barcode"), defaults=values
                )
                log_audit(
                    tenant_id=tenant.pk,
                    actor_id=request.user.pk,
                    action="BARCODE_PACK_CONFIGURED",
                    model_name="BarcodeMaster",
                    object_id=item.pk,
                    metadata={
                        "sku_id": str(sku.pk),
                        "barcode": item.barcode,
                        "pack_conversion": str(item.pack_conversion),
                        "is_active": item.is_active,
                    },
                )
                return item

        return self.command(run)
