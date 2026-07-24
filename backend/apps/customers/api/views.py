from django.core.exceptions import ValidationError
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.tenant_context import get_current_tenant_id
from apps.customers.api.serializers import (
    CustomerCommercialProfileSerializer,
    CustomerDeliveryAddressSerializer,
    CustomerSerializer,
)
from apps.customers.models import Customer, CustomerCommercialProfile, CustomerDeliveryAddress
from apps.customers.services import CustomerGovernanceService
from apps.tenancy.models import Tenant


class BaseCustomerViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        tenant_id = (
            get_current_tenant_id()
            or getattr(self.request, "tenant_id", None)
            or getattr(self.request.user, "tenant_id", None)
        )
        return self.queryset.filter(tenant_id=tenant_id)

    def perform_create(self, serializer):
        tenant_id = get_current_tenant_id()
        serializer.save(tenant_id=tenant_id)


class CustomerViewSet(BaseCustomerViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer

    def perform_create(self, serializer):
        tenant_id = (
            get_current_tenant_id()
            or getattr(self.request, "tenant_id", None)
            or getattr(self.request.user, "tenant_id", None)
        )
        validated = dict(serializer.validated_data)
        tenant = Tenant.objects.get(pk=tenant_id)
        customer = CustomerGovernanceService.create_customer(
            tenant=tenant,
            customer_number=validated.pop("customer_number"),
            legal_name=validated.pop("legal_name"),
            customer_type=validated.pop("customer_type"),
            created_by=self.request.user,
            **validated,
        )
        if str(customer.tenant_id) != str(tenant_id):
            raise ValidationError("Customer tenant context mismatch.")
        serializer.instance = customer

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        customer = self.get_object()
        reason = request.data.get("reason", "")
        try:
            CustomerGovernanceService.approve_customer(customer=customer, approver=request.user, reason=reason)
            return Response({"status": "approved"})
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        customer = self.get_object()
        reason = request.data.get("reason", "")
        try:
            CustomerGovernanceService.suspend_customer(customer=customer, reason=reason)
            return Response({"status": "suspended"})
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class CustomerDeliveryAddressViewSet(BaseCustomerViewSet):
    queryset = CustomerDeliveryAddress.objects.all()
    serializer_class = CustomerDeliveryAddressSerializer


class CustomerCommercialProfileViewSet(BaseCustomerViewSet):
    queryset = CustomerCommercialProfile.objects.all()
    serializer_class = CustomerCommercialProfileSerializer
