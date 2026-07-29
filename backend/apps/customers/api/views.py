from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError as APIValidationError
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


class BaseCustomerViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only, with state changes routed through the service actions below.

    This was a ModelViewSet, so a generic PATCH sat alongside approve/suspend and
    wrote the same columns without their checks. The HQ client only ever calls
    the actions -- /approve/ is the one write it makes -- so nothing legitimate
    depended on the generic path.
    """

    permission_classes = [permissions.IsAuthenticated]

    #: Set by each subclass to the model it serves, so the queryset is built
    #: per request rather than captured once at class-definition time.
    model = None

    def tenant_id(self):
        tenant_id = (
            get_current_tenant_id()
            or getattr(self.request, "tenant_id", None)
            or getattr(self.request.user, "tenant_id", None)
        )
        user_tenant_id = getattr(self.request.user, "tenant_id", None)
        if (
            tenant_id
            and user_tenant_id
            and str(tenant_id) != str(user_tenant_id)
            and not self.request.user.is_platform_admin
            and not self.request.user.is_superuser
        ):
            raise PermissionDenied("Requested tenant is outside the authenticated identity.")
        return tenant_id

    def get_queryset(self):
        tenant_id = self.tenant_id()
        if tenant_id is None:
            # No tenant, no rows. An unscoped read is how one customer list
            # shows another organisation's customers.
            return self.model.all_objects.none()
        return self.model.all_objects.filter(tenant_id=tenant_id)

    def perform_create(self, serializer):
        tenant_id = self.tenant_id()
        serializer.save(tenant_id=tenant_id)


class CustomerViewSet(mixins.CreateModelMixin, BaseCustomerViewSet):
    model = Customer
    serializer_class = CustomerSerializer

    def perform_create(self, serializer):
        tenant_id = self.tenant_id()
        if tenant_id is None:
            raise APIValidationError({"tenant": "Select a tenant before registering a customer."})
        validated = dict(serializer.validated_data)
        try:
            tenant = Tenant.objects.get(pk=tenant_id)
        except Tenant.DoesNotExist as error:
            raise APIValidationError({"tenant": "The selected tenant does not exist."}) from error
        try:
            customer = CustomerGovernanceService.create_customer(
                tenant=tenant,
                customer_number=validated.pop("customer_number"),
                legal_name=validated.pop("legal_name"),
                customer_type=validated.pop("customer_type"),
                created_by=self.request.user,
                **validated,
            )
        except IntegrityError as error:
            raise APIValidationError(
                {"customer_number": "This customer number already exists for the selected tenant."}
            ) from error
        if str(customer.tenant_id) != str(tenant_id):
            raise APIValidationError("Customer tenant context mismatch.")
        serializer.instance = customer

    @staticmethod
    def required_reason(request):
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            raise APIValidationError({"reason": "A business reason is required."})
        return reason

    @action(detail=True, methods=["post"], url_path="begin-review")
    def begin_review(self, request, pk=None):
        customer = self.get_object()
        try:
            CustomerGovernanceService.begin_review_customer(
                customer=customer,
                actor=request.user,
                reason=self.required_reason(request),
            )
            return Response({"status": "under_review"})
        except DjangoValidationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        customer = self.get_object()
        try:
            CustomerGovernanceService.approve_customer(
                customer=customer,
                approver=request.user,
                reason=self.required_reason(request),
            )
            return Response({"status": "approved"})
        except DjangoValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        customer = self.get_object()
        try:
            CustomerGovernanceService.activate_customer(
                customer=customer,
                actor=request.user,
                reason=self.required_reason(request),
            )
            return Response({"status": "active"})
        except DjangoValidationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        customer = self.get_object()
        try:
            CustomerGovernanceService.suspend_customer(
                customer=customer,
                actor=request.user,
                reason=self.required_reason(request),
            )
            return Response({"status": "suspended"})
        except DjangoValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        customer = self.get_object()
        try:
            CustomerGovernanceService.reactivate_customer(
                customer=customer,
                actor=request.user,
                reason=self.required_reason(request),
            )
            return Response({"status": "active"})
        except DjangoValidationError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class CustomerDeliveryAddressViewSet(BaseCustomerViewSet):
    model = CustomerDeliveryAddress
    serializer_class = CustomerDeliveryAddressSerializer


class CustomerCommercialProfileViewSet(BaseCustomerViewSet):
    model = CustomerCommercialProfile
    serializer_class = CustomerCommercialProfileSerializer
