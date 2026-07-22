from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.cds.models import ClinicalEvaluation, ClinicalFinding, ClinicalKnowledgeRelease
from apps.core.permissions import TenantCapabilityPermission


class KnowledgeReleaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicalKnowledgeRelease
        fields = (
            "id", "code", "version", "source", "source_version", "licence", "effective_date", "expires_at",
            "is_global", "is_active", "content_classification", "checksum_sha256",
        )


class ClinicalFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicalFinding
        fields = (
            "id", "rule_id", "rule_version", "rule_type", "source", "source_version", "effective_date",
            "severity", "evidence_summary", "explanation", "recommended_action", "override_policy",
            "affected_medicine", "interacting_factor", "created_at",
        )


class ClinicalEvaluationSerializer(serializers.ModelSerializer):
    findings = ClinicalFindingSerializer(many=True, read_only=True)

    class Meta:
        model = ClinicalEvaluation
        fields = (
            "id", "patient", "prescription", "knowledge_release", "status", "context_hash", "evaluated_by",
            "completed_at", "error_code", "error_detail", "findings",
        )


class ClinicalEvaluationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClinicalEvaluationSerializer
    permission_classes = [IsAuthenticated, TenantCapabilityPermission]
    read_capability = "cds.read"
    write_capability = "cds.configure"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ClinicalEvaluation.all_objects.none()
        return ClinicalEvaluation.all_objects.filter(tenant_id=self.request.tenant_id).prefetch_related("findings")


class KnowledgeReleaseViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = KnowledgeReleaseSerializer
    permission_classes = [IsAuthenticated, TenantCapabilityPermission]
    read_capability = "cds.configure.read"
    write_capability = "cds.configure"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ClinicalKnowledgeRelease.all_objects.none()
        return ClinicalKnowledgeRelease.all_objects.filter(tenant_id=self.request.tenant_id)
