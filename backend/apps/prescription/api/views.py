from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.cds.services import ClinicalDecisionSupportService
from apps.core.api.viewsets import TenantModelViewSet
from apps.core.permissions import TenantCapabilityPermission
from apps.organizations.models import Location
from apps.prescription.api.serializers import PrescriptionDispenseSerializer, PrescriptionSerializer
from apps.prescription.models import Prescription, PrescriptionDispense
from apps.prescription.services.dispensing_engine import DispensingEngine
from apps.prescription.services.qr_service import QRService
from apps.prescription.services.workflow import PrescriptionWorkflowService


class PrescriptionViewSet(TenantModelViewSet):
    queryset = Prescription.all_objects.select_related("patient", "practitioner", "organization", "location")
    serializer_class = PrescriptionSerializer
    read_capability = "prescriptions.read"
    write_capability = "prescriptions.write"
    search_fields = ("prescription_number", "patient__internal_reference_id", "patient__first_name", "patient__last_name")

    @action(detail=True, methods=["post"])
    def evaluate(self, request, pk=None):
        if not request.user.has_capability("prescriptions.review", tenant_id=request.tenant_id):
            return Response({"detail": "Prescription review capability is required."}, status=403)
        prescription = self.get_object()
        evaluation = ClinicalDecisionSupportService.evaluate(prescription=prescription, actor=request.user)
        return Response({"id": str(evaluation.id), "status": evaluation.status, "context_hash": evaluation.context_hash})

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        prescription = PrescriptionWorkflowService.transition(
            prescription_id=pk,
            tenant_id=request.tenant_id,
            actor=request.user,
            target_state=request.data.get("target_state"),
            reason=request.data.get("reason", ""),
            clinical_evaluation_id=request.data.get("clinical_evaluation_id"),
            payment_reference=request.data.get("payment_reference", ""),
        )
        return Response(self.get_serializer(prescription).data)

    @action(detail=True, methods=["post"])
    def dispense(self, request, pk=None):
        location = Location.all_objects.filter(id=request.data.get("location_id"), tenant_id=request.tenant_id).first()
        if not location:
            return Response({"detail": "Location is unavailable in the active tenant."}, status=404)
        key = str(request.headers.get("Idempotency-Key") or request.data.get("idempotency_key") or "").strip()
        if not key:
            return Response({"detail": "Idempotency-Key is required."}, status=400)
        dispense = DispensingEngine.execute_dispense(
            prescription=self.get_object(),
            location=location,
            items_to_dispense=request.data.get("items") or [],
            user=request.user,
            idempotency_key=key,
        )
        return Response(PrescriptionDispenseSerializer(dispense).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def qr(self, request, pk=None):
        return Response({"payload": QRService.generate_payload(self.get_object())})


class DispensingViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PrescriptionDispenseSerializer
    permission_classes = [IsAuthenticated, TenantCapabilityPermission]
    read_capability = "dispensing.read"
    write_capability = "dispensing.complete"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PrescriptionDispense.all_objects.none()
        return PrescriptionDispense.all_objects.filter(tenant_id=self.request.tenant_id).select_related(
            "prescription", "location", "dispensed_by"
        )
