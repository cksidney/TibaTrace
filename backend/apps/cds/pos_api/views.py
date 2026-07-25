from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.cds.pos_screening_models import PosClinicalScreening, PosOfflineClinicalPackage
from apps.cds.pos_screening_services import (
    PosClinicalScreeningService,
    PosOfflinePackageService,
    PosPharmacistReviewService,
)
from apps.core.tenant_context import get_current_tenant_id

from .serializers import (
    PosClinicalAcknowledgementSerializer,
    PosClinicalOverrideSerializer,
    PosClinicalScreeningRequestSerializer,
    PosClinicalScreeningResultSerializer,
    PosPharmacistDecisionSerializer,
    PosPharmacistReviewRequestSerializer,
)

User = get_user_model()

class PosClinicalScreeningViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    lookup_field = 'screening_id'
    # Required for schema generation: without it drf-spectacular cannot infer a
    # component and silently drops these routes from the OpenAPI contract.
    serializer_class = PosClinicalScreeningRequestSerializer

    def get_queryset(self):
        tenant_id = get_current_tenant_id()
        return PosClinicalScreening.all_objects.filter(tenant_id=tenant_id)

    def _actor(self):
        """The authenticated principal.

        Never derived from a client-supplied id. Accepting `pharmacist_id` from
        the request body would let any caller nominate whose authority to act
        under, which defeats capability enforcement entirely -- a cashier could
        simply pass a pharmacist's id to approve their own override.
        """
        return self.request.user

    def _referenced_user(self, user_id):
        """Resolve a *referenced* user, such as a witness, for recording only.

        Tenant-scoped, and never used as the actor for an authorisation check.
        """
        if not user_id:
            return None
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return None
        return User.objects.filter(tenant=tenant, id=user_id).first()

    @action(detail=False, methods=['post'])
    def evaluate(self, request):
        serializer = PosClinicalScreeningRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        try:
            screening = PosClinicalScreeningService.evaluate(
                tenant=request.tenant,
                transaction_id=data['transaction_id'],
                device_id=data['device_id'],
                register_id=data.get('register_id', ''),
                patient_id=data.get('patient_id'),
                prescription_id=data.get('prescription_id'),
                dispensing_episode_id=data.get('dispensing_episode_id', ''),
                basket_lines=data['basket_lines'],
                context_hash=data.get('context_hash'),
                cashier=request.user,
                offline_state=data.get('offline_state', False)
            )
            result_serializer = PosClinicalScreeningResultSerializer(screening)
            return Response(result_serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            raise ValidationError(str(e))

    def retrieve(self, request, screening_id=None):
        screening = self.get_object()
        serializer = PosClinicalScreeningResultSerializer(screening)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='acknowledge')
    def acknowledge(self, request, screening_id=None):
        screening = self.get_object()
        serializer = PosClinicalAcknowledgementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        try:
            PosClinicalScreeningService.acknowledge_finding(
                tenant=request.tenant,
                finding_id=data['finding_id'],
                cashier=self._actor(),
                expected_context_hash=data.get('expected_context_hash'),
            )
            screening.refresh_from_db()
            return Response(PosClinicalScreeningResultSerializer(screening).data)
        except PermissionDenied:
            # Must surface as 403, not be flattened into a 400.
            raise
        except DjangoValidationError as e:
            raise ValidationError(str(e)) from e

    @action(detail=True, methods=['post'], url_path='request-pharmacist')
    def request_pharmacist(self, request, screening_id=None):
        screening = self.get_object()
        serializer = PosPharmacistReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        try:
            PosPharmacistReviewService.request_review(
                screening=screening,
                cashier=self._actor(),
                expected_context_hash=data.get('expected_context_hash'),
            )
            return Response({"status": "requested"})
        except PermissionDenied:
            raise
        except DjangoValidationError as e:
            raise ValidationError(str(e)) from e

    @action(detail=True, methods=['post'], url_path='pharmacist-review')
    def pharmacist_review(self, request, screening_id=None):
        screening = self.get_object()
        serializer = PosPharmacistDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        try:
            PosPharmacistReviewService.submit_decision(
                screening=screening,
                finding_id=data.get('finding_id'),
                pharmacist=self._actor(),
                decision=data['decision'],
                clinical_justification=data.get('clinical_justification', ''),
                counselling_notes=data.get('counselling_notes', ''),
                prescriber_contact_ref=data.get('prescriber_contact_ref', ''),
                idempotency_key=data['idempotency_key'],
                expected_context_hash=data.get('expected_context_hash'),
            )
            screening.refresh_from_db()
            return Response(PosClinicalScreeningResultSerializer(screening).data)
        except PermissionDenied:
            raise
        except DjangoValidationError as e:
            raise ValidationError(str(e)) from e

    @action(detail=True, methods=['post'], url_path='override')
    def override(self, request, screening_id=None):
        screening = self.get_object()
        serializer = PosClinicalOverrideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        try:
            PosPharmacistReviewService.submit_decision(
                screening=screening,
                finding_id=data['finding_id'],
                pharmacist=self._actor(),
                decision='AUTHORIZED_OVERRIDE',
                clinical_justification=data['clinical_justification'],
                idempotency_key=data['idempotency_key'],
                expected_context_hash=data.get('expected_context_hash'),
            )
            screening.refresh_from_db()
            return Response(PosClinicalScreeningResultSerializer(screening).data)
        except PermissionDenied:
            raise
        except DjangoValidationError as e:
            raise ValidationError(str(e)) from e

    @action(detail=True, methods=['post'], url_path='resolve')
    def resolve(self, request, screening_id=None):
        # Additional action requested. Simple implementation.
        screening = self.get_object()
        return Response(PosClinicalScreeningResultSerializer(screening).data)

    @action(detail=False, methods=['get'], url_path='ruleset-version')
    def ruleset_version(self, request):
        version = PosOfflinePackageService.get_current_version(tenant=request.tenant)
        if version:
            return Response(version)
        return Response({"version": None})

    @action(detail=False, methods=['get'], url_path='offline-package')
    def offline_package(self, request):
        package = PosOfflineClinicalPackage.all_objects.filter(tenant=request.tenant).order_by('-created_at').first()
        if package:
            return Response({
                "version": package.version,
                "package_data": package.package_data,
                "signature": package.signature
            })
        return Response({"detail": "No offline package available"}, status=404)
