from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.cds.pos_screening_models import PosClinicalOverride, PosClinicalScreening, PosOfflineClinicalPackage
from apps.cds.pos_screening_services import (
    PosClinicalOverrideService,
    PosClinicalScreeningService,
    PosOfflinePackageService,
    PosPharmacistReviewService,
)
from apps.core.tenant_context import get_current_tenant_id

from .serializers import (
    PosClinicalAcknowledgementSerializer,
    PosClinicalOverrideApprovalSerializer,
    PosClinicalOverrideHistorySerializer,
    PosClinicalOverrideRejectionSerializer,
    PosClinicalOverrideRequestSerializer,
    PosClinicalOverrideRevocationSerializer,
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
                branch_id=data.get('branch_id'),
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
                conditions=data.get('conditions', ''),
                counselling_notes=data.get('counselling_notes', ''),
                prescriber_contact_ref=data.get('prescriber_contact_ref', ''),
                follow_up_actions=data.get('follow_up_actions', ''),
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


class PosClinicalOverrideViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    lookup_field = 'pk'

    def get_queryset(self):
        return PosClinicalOverride.all_objects.filter(tenant_id=get_current_tenant_id()).select_related(
            'finding__screening',
        )

    def create(self, request):
        serializer = PosClinicalOverrideRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        screening = PosClinicalScreening.all_objects.filter(
            tenant_id=get_current_tenant_id(),
            screening_id=data['screening_id'],
        ).first()
        if not screening:
            raise ValidationError('Clinical screening was not found for this tenant.')
        try:
            override = PosClinicalOverrideService.request(
                screening=screening,
                finding_id=data['finding_id'],
                requester=request.user,
                override_reason=data['override_reason'],
                requested_reason=data['requested_reason'],
                supporting_notes=data.get('supporting_notes', ''),
                idempotency_key=data['idempotency_key'],
                expected_context_hash=data['expected_context_hash'],
            )
            return Response(PosClinicalOverrideHistorySerializer(override).data, status=status.HTTP_201_CREATED)
        except PermissionDenied:
            raise
        except DjangoValidationError as error:
            raise ValidationError(str(error)) from error

    @action(detail=True, methods=['post'], url_path='start-review')
    def start_review(self, request, pk=None):
        try:
            override = PosClinicalOverrideService.start_review(override=self.get_object(), pharmacist=request.user)
            return Response(PosClinicalOverrideHistorySerializer(override).data)
        except PermissionDenied:
            raise
        except DjangoValidationError as error:
            raise ValidationError(str(error)) from error

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        serializer = PosClinicalOverrideApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            override = PosClinicalOverrideService.approve(
                override=self.get_object(),
                pharmacist=request.user,
                clinical_justification=data['clinical_justification'],
                conditions=data.get('conditions', ''),
                expires_at=data.get('expires_at'),
                idempotency_key=data['idempotency_key'],
                expected_context_hash=data['expected_context_hash'],
            )
            return Response(PosClinicalOverrideHistorySerializer(override).data)
        except PermissionDenied:
            raise
        except DjangoValidationError as error:
            raise ValidationError(str(error)) from error

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        serializer = PosClinicalOverrideRejectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            override = PosClinicalOverrideService.reject(
                override=self.get_object(),
                pharmacist=request.user,
                rejection_reason=serializer.validated_data['rejection_reason'],
            )
            return Response(PosClinicalOverrideHistorySerializer(override).data)
        except PermissionDenied:
            raise
        except DjangoValidationError as error:
            raise ValidationError(str(error)) from error

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        serializer = PosClinicalOverrideRevocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            override = PosClinicalOverrideService.revoke(
                override=self.get_object(),
                actor=request.user,
                reason=serializer.validated_data['revocation_reason'],
            )
            return Response(PosClinicalOverrideHistorySerializer(override).data)
        except PermissionDenied:
            raise
        except DjangoValidationError as error:
            raise ValidationError(str(error)) from error
