import base64
import hashlib
from decimal import Decimal

from django.core.exceptions import ValidationError as DomainError
from django.db import transaction
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.cds.models import ClinicalFinding
from apps.documents.models import StoredClinicalDocument
from apps.documents.storage import LocalClinicalObjectStorage
from apps.inventory.models import InventoryLocation
from apps.medicines.models import CommercialSKU
from apps.patients.models import Patient
from apps.platform.client_alignment import RequireAlignedPosClientMixin
from apps.practitioners.models import Practitioner
from apps.prescription.models import (
    DispensingEpisode,
    PharmacistClinicalReview,
    Prescription,
    PrescriptionItem,
    PrescriptionValidationFinding,
)
from apps.prescription.pos_permissions import can_read_clinical_details
from apps.prescription.rx_feeds import feed_adapter, feed_readiness
from apps.prescription.rx_intake import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_TOTAL_BYTES,
    PosPrescriptionIntakeService,
    decode_attachments,
    device_branch,
    source_documents,
)
from apps.prescription.rx_intake_models import PrescriptionIntakeReceipt
from apps.prescription.services.clinical_dispensing import (
    DispensingEpisodeService,
    PharmacistReviewService,
    PharmacistVerificationService,
    PrescriptionValidationService,
    _require_capability,
)
from apps.sales.models import SalesOrder, SalesOrderLine
from apps.tenancy.models import Tenant


class SourceFileSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=180)
    content_type = serializers.ChoiceField(choices=["application/pdf", "image/jpeg", "image/png"])
    content_base64 = serializers.CharField(max_length=((MAX_FILE_BYTES + 2) // 3) * 4, trim_whitespace=False)


class RxLineSerializer(serializers.Serializer):
    sku = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal("0.001"))
    directions = serializers.CharField(max_length=2000)


class RxIntakeSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    idempotency_key = serializers.CharField(max_length=180)
    patient = serializers.UUIDField()
    practitioner = serializers.UUIDField()
    prescription_number = serializers.CharField(max_length=80)
    prescription_date = serializers.DateField()
    prescription_type = serializers.ChoiceField(choices=Prescription.PRESCRIPTION_TYPES)
    notes = serializers.CharField(max_length=4000, allow_blank=True, default="")
    original_available = serializers.BooleanField(default=False)
    items = RxLineSerializer(many=True, min_length=1, max_length=50)
    attachments = SourceFileSerializer(many=True, max_length=MAX_FILES, default=list)


class FeedLineSerializer(serializers.Serializer):
    product_reference = serializers.CharField(max_length=160)
    quantity = serializers.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal("0.001"))
    directions = serializers.CharField(max_length=2000)


class FeedPrescriptionSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=120)
    patient_reference = serializers.CharField(max_length=160)
    prescriber_reference = serializers.CharField(max_length=160)
    prescription_date = serializers.DateField()
    prescription_type = serializers.ChoiceField(choices=Prescription.PRESCRIPTION_TYPES)
    items = FeedLineSerializer(many=True, min_length=1, max_length=50)


class FeedImportSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=128)
    idempotency_key = serializers.CharField(max_length=180)
    provider = serializers.ChoiceField(choices=["DHA", "HOSPITAL_EMR"])
    reference = serializers.CharField(max_length=120)
    attachments = SourceFileSerializer(many=True, max_length=MAX_FILES, default=list)


class IntakeProgressSerializer(serializers.Serializer):
    operation = serializers.ChoiceField(choices=["validate", "review", "verify", "open_episode"])
    outcome = serializers.ChoiceField(choices=PharmacistClinicalReview.OUTCOME_CHOICES, required=False)
    notes = serializers.CharField(max_length=4000, allow_blank=True, default="")
    store = serializers.UUIDField(required=False)
    order = serializers.UUIDField(required=False)


def _domain(call):
    try:
        return call()
    except DomainError as error:
        raise ValidationError(error.messages) from error


class PosPrescriptionIntakeViewSet(RequireAlignedPosClientMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def context(self, request):
        tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
        tenant = Tenant.objects.filter(pk=tenant_id).first()
        if not tenant:
            raise ValidationError("Select an active tenant.")
        device = request.data.get("device_id", "") if request.method == "POST" else request.query_params.get("device_id", "")
        if request.headers.get("X-POS-Device-ID") and request.headers["X-POS-Device-ID"] != device:
            raise ValidationError("Intake device differs from the activated POS device.")
        branch = _domain(lambda: device_branch(tenant=tenant, actor=request.user, device_id=device))
        return tenant, branch, device

    def prescription(self, request, pk):
        tenant, branch, _device = self.context(request)
        pk = serializers.UUIDField().run_validation(pk)
        rx = Prescription.all_objects.filter(tenant=tenant, location=branch, pk=pk).select_related(
            "patient", "practitioner", "original_document"
        ).first()
        if not rx:
            raise NotFound("Prescription not found in this branch.")
        return rx

    def representation(self, rx, request, *, detail=False):
        result = {"id": str(rx.pk), "reference": rx.prescription_number, "patient_name": rx.patient.full_name,
                  "patient_number": rx.patient.patient_number, "prescriber_name": rx.practitioner.professional_name or f"{rx.practitioner.first_name} {rx.practitioner.last_name}",
                  "prescription_date": str(rx.prescription_date), "status": rx.status, "source_channel": rx.source_channel,
                  "legal_state": rx.legal_validation_state, "clinical_state": rx.clinical_review_state,
                  "verification_state": rx.pharmacist_verification_state}
        if detail:
            result.update({"documents": source_documents(rx),
                "items": [{"medicine": row.medication_name, "quantity": str(row.quantity), "unit": row.unit, "directions": row.dosage_instruction}
                          for row in PrescriptionItem.all_objects.filter(tenant_id=rx.tenant_id, prescription=rx)],
                "legal_findings": [{"code": row.finding_code, "message": row.message} for row in PrescriptionValidationFinding.all_objects.filter(tenant_id=rx.tenant_id, prescription=rx)],
                "clinical_findings": list(ClinicalFinding.all_objects.filter(tenant_id=rx.tenant_id, prescription=rx).values(
                    "id", "severity", "explanation", "resolution_status")) if can_read_clinical_details(request, rx.tenant_id) else [],
            })
        return result

    def list(self, request):
        tenant, branch, _device = self.context(request)
        rows = Prescription.all_objects.filter(tenant=tenant, location=branch).select_related("patient", "practitioner")
        term = str(request.query_params.get("q", "")).strip()[:100]
        if term:
            from django.db.models import Q
            rows = rows.filter(Q(prescription_number__icontains=term) | Q(patient__patient_number__icontains=term) | Q(patient__first_name__icontains=term) | Q(patient__last_name__icontains=term))
        return Response([self.representation(row, request) for row in rows.order_by("-created_at")[:50]])

    def retrieve(self, request, pk=None):
        return Response(self.representation(self.prescription(request, pk), request, detail=True))

    def create(self, request):
        tenant, branch, device = self.context(request)
        data = RxIntakeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        rx = _domain(lambda: PosPrescriptionIntakeService.receive(tenant=tenant, branch=branch, actor=request.user,
                     device_id=device, command=data.validated_data))
        return Response(self.representation(rx, request, detail=True), status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def options(self, request):
        tenant, branch, _device = self.context(request)
        from django.db.models import Q
        term = str(request.query_params.get("q", "")).strip()[:100]
        patients = Patient.all_objects.filter(tenant=tenant, is_active=True, is_deceased=False)
        practitioners = Practitioner.all_objects.filter(tenant=tenant, status="ACTIVE")
        products = CommercialSKU.all_objects.filter(tenant=tenant, status="ACTIVE")
        if term:
            patients = patients.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term) | Q(patient_number__icontains=term))
            practitioners = practitioners.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term) | Q(registration_number__icontains=term))
            products = products.filter(Q(display_name__icontains=term) | Q(sku_code__icontains=term))
        capabilities = {name: request.user.has_capability(cap, tenant_id=tenant.pk) for name, cap in {
            "receive": "prescriptions.intake", "upload": "documents.write", "read_documents": "documents.read",
            "validate": "prescriptions.legal_validate", "review": "prescriptions.clinical_review",
            "verify": "prescriptions.pharmacist_verify", "open_episode": "dispensing.reserve"}.items()}
        return Response({"branch": {"id": str(branch.pk), "name": branch.name}, "capabilities": capabilities,
            "patients": [{"id": str(row.pk), "name": f"{row.full_name} · {row.patient_number}"} for row in patients.order_by("patient_number")[:50]],
            "practitioners": [{"id": str(row.pk), "name": row.professional_name or f"{row.first_name} {row.last_name}"} for row in practitioners.order_by("registration_number")[:50]],
            "products": [{"id": str(row.pk), "name": row.display_name, "unit": row.package_definition.unit_of_measure} for row in products.select_related("package_definition").order_by("sku_code")[:50]],
            "stores": list(InventoryLocation.all_objects.filter(tenant=tenant, branch=branch, status="ACTIVE", quarantine_capability=False,
                damaged_goods_capability=False, expiry_hold_capability=False, returns_capability=False, location_type__in=["STORE", "PHARMACY"]).values("id", "name")),
            "orders": list(SalesOrder.all_objects.filter(tenant=tenant, branch=branch, status="APPROVED", total__gt=0).order_by("-created_at").values("id", "order_number", "total")[:50]),
            "feeds": feed_readiness(tenant), "max_file_bytes": MAX_FILE_BYTES, "max_total_bytes": MAX_TOTAL_BYTES, "max_files": MAX_FILES})

    @action(detail=False, methods=["get"])
    def reconcile(self, request):
        tenant, branch, device = self.context(request)
        receipt = PrescriptionIntakeReceipt.all_objects.filter(tenant=tenant, branch=branch, device_id=device,
            actor=request.user, idempotency_key=request.query_params.get("idempotency_key", "")).select_related("prescription").first()
        return Response({"found": bool(receipt), "prescription": self.representation(receipt.prescription, request, detail=True) if receipt else None})

    @action(detail=False, methods=["post"], url_path="import")
    def import_feed(self, request):
        tenant, branch, device = self.context(request)
        _require_capability(request.user, tenant.pk, "prescriptions.intake")
        submitted = FeedImportSerializer(data=request.data)
        submitted.is_valid(raise_exception=True)
        provider, reference = submitted.validated_data["provider"], submitted.validated_data["reference"]
        key = submitted.validated_data["idempotency_key"]
        original = PrescriptionIntakeReceipt.all_objects.filter(tenant=tenant, idempotency_key=key).select_related("prescription").first()
        if original:
            files = _domain(lambda: decode_attachments(submitted.validated_data["attachments"]))
            saved_files = source_documents(original.prescription)
            if (original.provider_code != provider or original.source_key != f"{provider}:{reference}"
                or original.actor_id != request.user.pk or original.device_id != device or original.branch_id != branch.pk
                or sorted((row["name"], row["hash"]) for row in files) != sorted((row["name"], row["sha256"]) for row in saved_files)):
                raise ValidationError("This import retry key belongs to a different command.")
            return Response(self.representation(original.prescription, request, detail=True), status=200)
        adapter, config = _domain(lambda: feed_adapter(tenant=tenant, provider=provider))
        try:
            payload = adapter.fetch_prescription(reference)
        except Exception:
            return Response({"detail": "The tenant's prescription source is unavailable. No clinical approval was created."}, status=503)
        normalized = FeedPrescriptionSerializer(data=payload)
        normalized.is_valid(raise_exception=True)
        data = normalized.validated_data
        if data["reference"] != reference:
            raise ValidationError("The provider returned a different prescription reference.")
        def mapped(mapping, value):
            result = (config.get(mapping) or {}).get(value)
            if not result:
                raise ValidationError(f"The tenant's {mapping} mapping is incomplete. Review the source identity before import.")
            return result
        command = {"device_id": device, "idempotency_key": key,
            "patient": mapped("patient_map", data["patient_reference"]), "practitioner": mapped("prescriber_map", data["prescriber_reference"]),
            "prescription_number": f"RX-{provider[:3]}-{hashlib.sha256((str(tenant.pk) + reference).encode()).hexdigest()[:16].upper()}",
            "prescription_date": data["prescription_date"], "prescription_type": data["prescription_type"], "original_available": True,
            "items": [{"sku": mapped("product_map", row["product_reference"]), "quantity": row["quantity"], "directions": row["directions"]} for row in data["items"]],
            "attachments": submitted.validated_data["attachments"], "notes": ""}
        checked = RxIntakeSerializer(data=command)
        checked.is_valid(raise_exception=True)
        rx = _domain(lambda: PosPrescriptionIntakeService.receive(tenant=tenant, branch=branch, actor=request.user,
            device_id=device, command=checked.validated_data, provider_code=provider, external_reference=reference))
        return Response(self.representation(rx, request, detail=True), status=201)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def progress(self, request, pk=None):
        rx = self.prescription(request, pk)
        submitted = IntakeProgressSerializer(data=request.data)
        submitted.is_valid(raise_exception=True)
        command = submitted.validated_data
        operation = command["operation"]
        if operation == "validate":
            _domain(lambda: PrescriptionValidationService.validate(prescription=rx, actor=request.user))
        elif operation == "review":
            outcome = command.get("outcome")
            if outcome:
                if not command["notes"].strip():
                    raise ValidationError("Select a review outcome and record the pharmacist's rationale.")
            review = _domain(lambda: PharmacistReviewService.start(prescription=rx, actor=request.user, run_cds=True))
            if outcome:
                _domain(lambda: PharmacistReviewService.complete(review=review, actor=request.user, outcome=outcome, notes=command["notes"]))
        elif operation == "verify":
            _domain(lambda: PharmacistVerificationService.verify(prescription=rx, actor=request.user,
                idempotency_key=f"pos-rx-verify:{rx.pk}", decision="VERIFIED", clinical_justification=command["notes"]))
        elif operation == "open_episode":
            _require_capability(request.user, rx.tenant_id, "dispensing.reserve")
            store_id = serializers.UUIDField().run_validation(command.get("store"))
            order_id = serializers.UUIDField().run_validation(command.get("order"))
            store = InventoryLocation.all_objects.filter(tenant_id=rx.tenant_id, branch=rx.location, pk=store_id,
                status="ACTIVE", quarantine_capability=False, damaged_goods_capability=False, expiry_hold_capability=False,
                returns_capability=False, location_type__in=["STORE", "PHARMACY"]).first()
            order = SalesOrder.all_objects.select_for_update().filter(tenant_id=rx.tenant_id, branch=rx.location, pk=order_id, status="APPROVED", total__gt=0).first()
            if not store or not order:
                raise ValidationError("Select an active dispensing store and approved same-branch priced order.")
            self.validate_order(rx, order)
            episode = _domain(lambda: DispensingEpisodeService.create(prescription=rx, branch=rx.location, pharmacy_location=store,
                actor=request.user, idempotency_key=f"pos-rx-episode:{rx.pk}", sales_order=order, payment_state="PENDING"))
            return Response({"episode_id": str(episode.pk)})
        else:
            raise ValidationError("Unsupported prescription intake action.")
        rx.refresh_from_db()
        return Response(self.representation(rx, request, detail=True))

    @staticmethod
    def validate_order(rx, order):
        if DispensingEpisode.all_objects.filter(tenant_id=rx.tenant_id, sales_order=order).exclude(prescription=rx).exists():
            raise ValidationError("This priced order is already attached to another prescription.")
        authorised = {}
        for item in PrescriptionItem.all_objects.filter(tenant_id=rx.tenant_id, prescription=rx):
            key = (item.prescribed_sku_id, item.unit)
            authorised[key] = authorised.get(key, Decimal("0")) + max(Decimal("0"), item.total_authorized_quantity - item.quantity_supplied_total)
        ordered = {}
        lines = list(SalesOrderLine.all_objects.filter(tenant_id=rx.tenant_id, sales_order=order))
        for line in lines:
            key = (line.sku_id, line.unit)
            quantity = line.approved_quantity - line.cancelled_quantity
            if key not in authorised or quantity <= 0 or line.line_total <= 0:
                raise ValidationError("The priced order must contain approved prescribed products in their authorised units.")
            ordered[key] = ordered.get(key, Decimal("0")) + quantity
        if not lines or any(quantity > authorised[key] for key, quantity in ordered.items()):
            raise ValidationError("The priced order exceeds the remaining prescribed quantity or has no approved lines.")

    @action(detail=True, methods=["post"], url_path="source-document")
    def source_document(self, request, pk=None):
        rx = self.prescription(request, pk)
        document_id = request.data.get("document_id")
        if document_id not in [row["id"] for row in source_documents(rx)]:
            raise NotFound("Source document not found for this prescription.")
        document = StoredClinicalDocument.all_objects.get(tenant_id=rx.tenant_id, patient=rx.patient, pk=document_id)
        if document.content_type not in {"application/pdf", "image/jpeg", "image/png"} or document.size_bytes > MAX_FILE_BYTES:
            raise ValidationError("This source format or size requires the HQ document workspace.")
        content = _domain(lambda: LocalClinicalObjectStorage.read(tenant_id=str(rx.tenant_id), actor=request.user,
            token=LocalClinicalObjectStorage.signed_token(document=document, actor=request.user)))
        return Response({"name": document.original_name, "content_type": document.content_type,
                         "content_base64": base64.b64encode(content).decode()})
