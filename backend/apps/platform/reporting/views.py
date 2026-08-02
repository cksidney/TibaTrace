"""Phase 15 Compliance Reporting Engine & Phase 16 Certification Evidence Engine views."""
from __future__ import annotations

from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.reporting.certification_engine import CertificationEvidenceGenerator
from apps.platform.reporting.compliance_engine import ComplianceReportEngine
from apps.platform.reporting.services import (
    catalogue_payload,
    create_download,
    validate_receipt,
)


class HQReportCatalogueView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(catalogue_payload())


class HQReportDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, report_id: str):
        export_format = request.data.get("format") or request.query_params.get("format") or "pdf"
        terminal_id = request.data.get("terminal_id") or ""
        terminal_label = request.data.get("terminal_label") or "HQ Web"
        period_start = request.data.get("start_date_time") or request.query_params.get("from_iso") or ""
        period_end = request.data.get("end_date_time") or request.query_params.get("to_iso") or ""
        granularity = request.data.get("granularity") or request.query_params.get("granularity") or ""
        try:
            spec, receipt, body, content_type = create_download(
                request=request,
                report_id=report_id,
                export_format=str(export_format),
                terminal_id=str(terminal_id),
                terminal_label=str(terminal_label),
                period_start=str(period_start),
                period_end=str(period_end),
                granularity=str(granularity),
            )
        except LookupError:
            return Response({"detail": "Unknown report."}, status=404)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)

        filename = (
            f"{spec.id}-{receipt.receipt_id[:8]}.{receipt.export_format if receipt.export_format != 'xlsx' else 'csv'}"
        )
        response = HttpResponse(body, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["X-Report-Receipt-Id"] = receipt.receipt_id
        response["X-Report-Validation-Code"] = receipt.validation_code
        response["X-Report-Checksum-SHA256"] = receipt.checksum_sha256
        response["X-Report-Validation-Url"] = receipt.validation_url
        response["Access-Control-Expose-Headers"] = (
            "Content-Disposition, X-Report-Receipt-Id, X-Report-Validation-Code, "
            "X-Report-Checksum-SHA256, X-Report-Validation-Url"
        )
        return response


class HQReportValidateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, receipt_id: str):
        payload = validate_receipt(receipt_id)
        if payload is None:
            return Response({"valid": False, "detail": "Receipt not found."}, status=404)
        return Response(payload)


class ComplianceReportView(APIView):
    """API view to generate Phase 15 Enterprise Compliance Report Packs."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        report_type = request.query_params.get("report_type", "PREMISES").upper()
        format_type = request.query_params.get("format", "json").lower()
        tenant_id = getattr(request, "tenant_id", None)

        result = ComplianceReportEngine.generate_report(
            report_type=report_type,
            format_type=format_type,
            tenant_id=tenant_id,
            actor=request.user,
        )

        if format_type in ("csv", "excel"):
            response = HttpResponse(result["content"], content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{result["filename"]}"'
            return response

        return HttpResponse(result["content"], content_type="application/json")


class CertificationEvidenceView(APIView):
    """API view to generate Phase 16 Certification Evidence Bundles (JSON/ZIP)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        format_type = request.query_params.get("format", "json").lower()

        if format_type == "zip":
            zip_bytes, filename = CertificationEvidenceGenerator.export_evidence_zip(
                operator_name=getattr(request.user, "email", "Platform Operator")
            )
            response = HttpResponse(zip_bytes, content_type="application/zip")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response

        package = CertificationEvidenceGenerator.generate_evidence_package(
            operator_name=getattr(request.user, "email", "Platform Operator")
        )
        return Response(package, status=status.HTTP_200_OK)
