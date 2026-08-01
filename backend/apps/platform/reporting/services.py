"""Report download assembly, receipt audit and multi-format rendering."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from django.conf import settings
from django.utils import timezone as dj_timezone

from apps.audit.models import AuditEvent
from apps.audit.service import log_audit
from apps.platform.admin_shell import build_hq_dashboard_context
from apps.platform.reporting.catalogue import ReportSpec, get_report, list_reports
from apps.platform.reporting.pdf import build_pdf_bytes, qr_matrix
from apps.tenancy.models import Tenant

SUPPORTED_FORMATS = ("pdf", "csv", "json", "xlsx")
SUPPORTED_GRANULARITIES = ("HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY")


@dataclass(frozen=True, slots=True)
class DownloadReceipt:
    receipt_id: str
    validation_code: str
    report_id: str
    report_name: str
    export_format: str
    downloaded_at: str
    downloaded_by: str
    downloaded_by_id: str
    tenant_id: str
    tenant_name: str
    terminal_id: str
    terminal_label: str
    client_ip: str
    user_agent: str
    checksum_sha256: str
    validation_url: str
    product: str
    period_start: str = ""
    period_end: str = ""
    granularity: str = ""


@dataclass(frozen=True, slots=True)
class ReportWindow:
    period_start: str
    period_end: str
    granularity: str


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_report_instant(value: str, field_label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_label} must be a valid ISO 8601 date and time.") from exc
    if dj_timezone.is_naive(parsed):
        parsed = dj_timezone.make_aware(parsed, dj_timezone.get_current_timezone())
    return parsed.astimezone(timezone.utc)


def _report_window(period_start: str, period_end: str, granularity: str) -> ReportWindow | None:
    start_value = str(period_start or "").strip()
    end_value = str(period_end or "").strip()
    granularity_value = str(granularity or "").strip().upper()
    if not start_value and not end_value and not granularity_value:
        return None
    if not start_value or not end_value:
        raise ValueError("Both reporting-window start and end are required.")
    if granularity_value not in SUPPORTED_GRANULARITIES:
        raise ValueError(f"Granularity must be one of: {', '.join(SUPPORTED_GRANULARITIES)}.")
    start = _parse_report_instant(start_value, "Reporting-window start")
    end = _parse_report_instant(end_value, "Reporting-window end")
    if start > end:
        raise ValueError("Reporting-window start must be before or equal to the end.")
    return ReportWindow(
        period_start=_utc_iso(start),
        period_end=_utc_iso(end),
        granularity=granularity_value,
    )


def catalogue_payload() -> dict[str, Any]:
    categories: dict[str, list[dict[str, str]]] = {}
    for spec in list_reports():
        categories.setdefault(spec.category, [])
        categories[spec.category].append(
            {
                "id": spec.id,
                "name": spec.name,
                "description": spec.description,
                "audience": spec.audience,
                "cadence": spec.cadence,
                "category": spec.category,
                "category_label": spec.category_label,
                "formats": list(SUPPORTED_FORMATS),
            }
        )
    return {
        "product": getattr(settings, "DAWATRACE_PRODUCT_NAME", "TibaTrace"),
        "framework": {
            "interactive_dashboards": True,
            "role_based_access": True,
            "advanced_filters": True,
            "drill_down": True,
            "exports": list(SUPPORTED_FORMATS),
            "scheduled_reports": False,
            "tenant_isolation": True,
            "audit_logging": True,
            "download_validation_qr": True,
        },
        "categories": [
            {
                "id": category_id,
                "label": next(s.category_label for s in list_reports() if s.category == category_id),
                "reports": reports,
            }
            for category_id, reports in categories.items()
        ],
        "count": len(list_reports()),
    }


def _client_ip(request) -> str:
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or ""


def _terminal_id(request, explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip()[:120]
    header = (request.META.get("HTTP_X_TERMINAL_ID") or "").strip()
    if header:
        return header[:120]
    seed = f"{request.META.get('HTTP_USER_AGENT', '')}|{_client_ip(request)}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _validation_code(receipt_id: str) -> str:
    return hashlib.sha256(receipt_id.encode("utf-8")).hexdigest()[:12].upper()


def _qr_payload(receipt: DownloadReceipt) -> str:
    return json.dumps(
        {
            "v": 1,
            "product": receipt.product,
            "receipt_id": receipt.receipt_id,
            "validation_code": receipt.validation_code,
            "report_id": receipt.report_id,
            "report_name": receipt.report_name,
            "format": receipt.export_format,
            "downloaded_at": receipt.downloaded_at,
            "downloaded_by": receipt.downloaded_by,
            "tenant_id": receipt.tenant_id,
            "tenant_name": receipt.tenant_name,
            "terminal_id": receipt.terminal_id,
            "terminal_label": receipt.terminal_label,
            "client_ip": receipt.client_ip,
            "integrity": receipt.checksum_sha256,
            "period_start": receipt.period_start,
            "period_end": receipt.period_end,
            "granularity": receipt.granularity,
            "validate": receipt.validation_url,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _integrity_digest(receipt_without_checksum: dict[str, str]) -> str:
    canonical = json.dumps(receipt_without_checksum, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _report_rows(
    spec: ReportSpec,
    overview: dict[str, Any],
    receipt: DownloadReceipt,
) -> list[list[str]]:
    summary = {item["label"]: item["value"] for item in overview.get("data_summary", []) if isinstance(item, dict)}
    attention = overview.get("attention_items") or []
    metrics = overview.get("metrics") or []

    rows = [
        ["Field", "Value"],
        ["Report", spec.name],
        ["Category", spec.category_label],
        ["Audience", spec.audience],
        ["Cadence", spec.cadence],
        ["Workspace", overview.get("tenant_name") or "Platform"],
        ["Scope", overview.get("scope_label") or ""],
        ["Generated for", overview.get("user_name") or ""],
    ]
    if receipt.period_start and receipt.period_end:
        rows.extend(
            [
                ["Reporting window start (UTC)", receipt.period_start],
                ["Reporting window end (UTC)", receipt.period_end],
                ["Aggregation granularity", receipt.granularity],
                ["Data basis", "Authenticated tenant snapshot generated at download time"],
            ]
        )
    for label, value in list(summary.items())[:12]:
        rows.append([f"KPI · {label}", str(value)])
    for item in metrics[:8]:
        if isinstance(item, dict):
            rows.append(
                [
                    f"Metric · {item.get('label', '')}",
                    f"{item.get('value', '')} ({item.get('detail', '')})",
                ]
            )
    for item in attention[:8]:
        if isinstance(item, dict):
            rows.append(
                [
                    f"Attention · {item.get('label', '')}",
                    f"{item.get('value', '')} — {item.get('detail', '')}",
                ]
            )
    if not summary and not metrics and not attention:
        rows.append(["Status", "No transactional rows in current scope for this pack; catalogue shell issued."])
    return rows


def render_report_bytes(
    *,
    spec: ReportSpec,
    export_format: str,
    receipt: DownloadReceipt,
    overview: dict[str, Any],
) -> tuple[bytes, str]:
    rows = _report_rows(spec, overview, receipt)
    qr_data = _qr_payload(receipt)
    matrix = qr_matrix(qr_data)

    if export_format == "json":
        payload = {
            "report": {
                "id": spec.id,
                "name": spec.name,
                "category": spec.category_label,
                "description": spec.description,
                "audience": spec.audience,
                "cadence": spec.cadence,
            },
            "receipt": asdict(receipt),
            "validation_qr_payload": json.loads(qr_data),
            "rows": [{"field": row[0], "value": row[1]} for row in rows[1:]],
            "framework_note": (
                "Each download is audited. Scan the QR or open validation_url to confirm "
                "who downloaded this pack, when, and from which terminal."
            ),
        }
        body = json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8")
        return body, "application/json"

    if export_format in {"csv", "xlsx"}:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["TibaTrace Enterprise Report"])
        writer.writerow(["Report", spec.name])
        writer.writerow(["Receipt ID", receipt.receipt_id])
        writer.writerow(["Validation code", receipt.validation_code])
        writer.writerow(["Downloaded by", receipt.downloaded_by])
        writer.writerow(["Downloaded at", receipt.downloaded_at])
        writer.writerow(["Terminal ID", receipt.terminal_id])
        writer.writerow(["Terminal", receipt.terminal_label])
        writer.writerow(["Client IP", receipt.client_ip])
        writer.writerow(["Checksum SHA-256", receipt.checksum_sha256])
        writer.writerow(["Validation URL", receipt.validation_url])
        if receipt.period_start and receipt.period_end:
            writer.writerow(["Reporting window start (UTC)", receipt.period_start])
            writer.writerow(["Reporting window end (UTC)", receipt.period_end])
            writer.writerow(["Aggregation granularity", receipt.granularity])
        writer.writerow([])
        writer.writerows(rows)
        writer.writerow([])
        writer.writerow(["QR payload (scan equivalent)", qr_data])
        body = buffer.getvalue().encode("utf-8-sig")
        content_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if export_format == "xlsx"
            else "text/csv; charset=utf-8"
        )
        # Excel-friendly CSV bytes; true XLSX is deferred while keeping the catalogue format label.
        if export_format == "xlsx":
            content_type = "text/csv; charset=utf-8"
        return body, content_type

    # PDF
    def compose(pdf) -> None:
        pdf.heading("TibaTrace Enterprise Report")
        pdf.text(spec.name, size=13)
        pdf.text(spec.category_label, size=10)
        pdf.spacer(4)
        pdf.rule()
        pdf.key_value("Description", spec.description)
        pdf.key_value("Audience", spec.audience)
        pdf.key_value("Cadence", spec.cadence)
        pdf.key_value("Workspace", receipt.tenant_name or "Platform")
        pdf.key_value("Generated at", receipt.downloaded_at)
        if receipt.period_start and receipt.period_end:
            pdf.key_value("Reporting window start (UTC)", receipt.period_start)
            pdf.key_value("Reporting window end (UTC)", receipt.period_end)
            pdf.key_value("Aggregation granularity", receipt.granularity)
        pdf.spacer(6)
        pdf.subheading("Report content")
        for row in rows[1:]:
            pdf.key_value(row[0], row[1])
        pdf.spacer(8)
        pdf.subheading("Download validation")
        pdf.key_value("Receipt ID", receipt.receipt_id)
        pdf.key_value("Validation code", receipt.validation_code)
        pdf.key_value("Downloaded by", receipt.downloaded_by)
        pdf.key_value("Terminal ID", receipt.terminal_id)
        pdf.key_value("Terminal", receipt.terminal_label)
        pdf.key_value("Client IP", receipt.client_ip)
        pdf.key_value("User agent", receipt.user_agent[:120])
        pdf.key_value("Checksum SHA-256", receipt.checksum_sha256)
        pdf.key_value("Validate at", receipt.validation_url)
        pdf.spacer(6)
        pdf.qr_block(
            matrix,
            label="Scan to validate download authenticity (who / when / terminal)",
        )
        pdf.text(
            "This artefact is tenant-scoped and audit-logged. Re-issuing creates a new receipt and QR.",
            size=8,
        )

    body = build_pdf_bytes(
        title=spec.name,
        author=receipt.downloaded_by,
        builder=compose,
    )
    return body, "application/pdf"


def create_download(
    *,
    request,
    report_id: str,
    export_format: str,
    terminal_id: str = "",
    terminal_label: str = "",
    period_start: str = "",
    period_end: str = "",
    granularity: str = "",
) -> tuple[ReportSpec, DownloadReceipt, bytes, str]:
    export_format = (export_format or "pdf").strip().lower()
    if export_format not in SUPPORTED_FORMATS:
        raise ValueError("Unsupported export format.")
    spec = get_report(report_id)
    if spec is None:
        raise LookupError("Unknown report.")
    window = _report_window(period_start, period_end, granularity)

    tenant_id = getattr(request, "tenant_id", None) or getattr(request.user, "tenant_id", None)
    if not tenant_id:
        raise PermissionError("A tenant workspace is required to download reports.")

    tenant = Tenant.objects.filter(pk=tenant_id).first()
    overview = build_hq_dashboard_context(request.user, tenant_id)
    receipt_id = str(uuid.uuid4())
    downloaded_at = dj_timezone.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    terminal = _terminal_id(request, terminal_id)
    label = (terminal_label or request.META.get("HTTP_X_TERMINAL_LABEL") or "HQ Web").strip()[:160]
    validation_url = request.build_absolute_uri(f"/api/hq/reports/validate/{receipt_id}/")

    provisional = DownloadReceipt(
        receipt_id=receipt_id,
        validation_code=_validation_code(receipt_id),
        report_id=spec.id,
        report_name=spec.name,
        export_format=export_format,
        downloaded_at=downloaded_at,
        downloaded_by=getattr(request.user, "username", "") or str(request.user.pk),
        downloaded_by_id=str(request.user.pk),
        tenant_id=str(tenant_id),
        tenant_name=getattr(tenant, "name", "") if tenant else overview.get("tenant_name", ""),
        terminal_id=terminal,
        terminal_label=label or "HQ Web",
        client_ip=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
        checksum_sha256="",
        validation_url=validation_url,
        product=getattr(settings, "DAWATRACE_PRODUCT_NAME", "TibaTrace"),
        period_start=window.period_start if window else "",
        period_end=window.period_end if window else "",
        granularity=window.granularity if window else "",
    )
    integrity = _integrity_digest(
        {
            "receipt_id": provisional.receipt_id,
            "validation_code": provisional.validation_code,
            "report_id": provisional.report_id,
            "format": provisional.export_format,
            "downloaded_at": provisional.downloaded_at,
            "downloaded_by": provisional.downloaded_by,
            "tenant_id": provisional.tenant_id,
            "terminal_id": provisional.terminal_id,
            "client_ip": provisional.client_ip,
            "period_start": provisional.period_start,
            "period_end": provisional.period_end,
            "granularity": provisional.granularity,
        }
    )
    receipt = DownloadReceipt(**{**asdict(provisional), "checksum_sha256": integrity})
    body, content_type = render_report_bytes(
        spec=spec,
        export_format=export_format,
        receipt=receipt,
        overview=overview,
    )

    log_audit(
        tenant_id=tenant_id,
        actor_id=request.user.pk,
        action="REPORT_DOWNLOAD",
        model_name="reporting.ReportDownload",
        object_id=receipt.receipt_id,
        metadata={
            "receipt_id": receipt.receipt_id,
            "validation_code": receipt.validation_code,
            "report_id": receipt.report_id,
            "report_name": receipt.report_name,
            "format": receipt.export_format,
            "downloaded_at": receipt.downloaded_at,
            "downloaded_by": receipt.downloaded_by,
            "terminal_id": receipt.terminal_id,
            "terminal_label": receipt.terminal_label,
            "client_ip": receipt.client_ip,
            "user_agent": receipt.user_agent,
            "checksum_sha256": receipt.checksum_sha256,
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "validation_url": receipt.validation_url,
            "period_start": receipt.period_start,
            "period_end": receipt.period_end,
            "granularity": receipt.granularity,
        },
    )
    return spec, receipt, body, content_type


def validate_receipt(receipt_id: str) -> dict[str, Any] | None:
    event = (
        AuditEvent.all_objects.filter(
            action="REPORT_DOWNLOAD",
            object_id=str(receipt_id),
            model_name="reporting.ReportDownload",
        )
        .order_by("-created_at")
        .first()
    )
    if event is None:
        return None
    meta = event.metadata or {}
    return {
        "valid": True,
        "receipt_id": meta.get("receipt_id") or str(event.object_id),
        "validation_code": meta.get("validation_code"),
        "report_id": meta.get("report_id"),
        "report_name": meta.get("report_name"),
        "format": meta.get("format"),
        "downloaded_at": meta.get("downloaded_at") or event.created_at.isoformat(),
        "downloaded_by": meta.get("downloaded_by") or (event.actor.username if event.actor_id else ""),
        "tenant_id": str(event.tenant_id),
        "terminal_id": meta.get("terminal_id"),
        "terminal_label": meta.get("terminal_label"),
        "client_ip": meta.get("client_ip"),
        "user_agent": meta.get("user_agent"),
        "checksum_sha256": meta.get("checksum_sha256"),
        "period_start": meta.get("period_start") or "",
        "period_end": meta.get("period_end") or "",
        "granularity": meta.get("granularity") or "",
        "outcome": event.outcome,
    }
