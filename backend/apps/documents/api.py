from django.http import HttpResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import TenantCapabilityPermission
from apps.documents.models import StoredClinicalDocument
from apps.documents.storage import LocalClinicalObjectStorage


class StoredClinicalDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoredClinicalDocument
        fields = (
            "id", "tenant", "patient", "original_name", "content_type", "size_bytes", "hash_sha256",
            "uploaded_by", "malware_scan_status", "metadata", "created_at", "updated_at",
        )
        read_only_fields = fields


class StoredClinicalDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StoredClinicalDocumentSerializer
    permission_classes = [IsAuthenticated, TenantCapabilityPermission]
    read_capability = "documents.read"
    write_capability = "documents.write"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return StoredClinicalDocument.all_objects.none()
        return StoredClinicalDocument.all_objects.filter(tenant_id=self.request.tenant_id)

    @action(detail=True, methods=["post"], url_path="signed-token")
    def signed_token(self, request, pk=None):
        document = self.get_object()
        return Response({"token": LocalClinicalObjectStorage.signed_token(document=document, actor=request.user)})

    @action(detail=False, methods=["post"], url_path="download")
    def download(self, request):
        content = LocalClinicalObjectStorage.read(
            token=request.data.get("token", ""), actor=request.user, tenant_id=request.tenant_id
        )
        return HttpResponse(content, content_type="application/octet-stream")
