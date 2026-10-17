"""KRA eTIMS VSCU (Virtual Sales Control Unit) Client.

Implements the official KRA eTIMS VSCU API protocol:
  - selectServerTime: Clock synchronization
  - selectInitInfo: Device initialization / handshake
  - saveTrnsSalesOsdc: Fiscal sales invoice & credit note transmission
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests
from django.utils import timezone

from apps.taxation.models import FiscalReceipt, FiscalSubmissionLog, TenantEtimsProfile

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10
CONNECT_TIMEOUT_SECONDS = 3


class VscuApiError(Exception):
    """Raised when KRA VSCU returns a business error code."""


class VscuClient:
    """Client for KRA eTIMS Virtual Sales Control Unit API."""

    def __init__(self, profile: TenantEtimsProfile) -> None:
        self.profile = profile
        self.base_url = (profile.base_url or "https://etims-sbx.kra.go.ke").rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "tin": self.profile.tin or "",
            "bhfId": self.profile.bhf_id or "00",
            "dvcSrlNo": self.profile.dvc_srl_no or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = self._headers()
        start = time.monotonic()
        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=(CONNECT_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS),
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            try:
                body = resp.json()
            except ValueError:
                body = {"raw_text": resp.text}

            success = resp.status_code == 200 and body.get("resultCd") == "000"
            return {
                "success": success,
                "status_code": resp.status_code,
                "response_time_ms": elapsed_ms,
                "data": body.get("data") or body.get("info") or {},
                "result_code": body.get("resultCd", str(resp.status_code)),
                "result_message": body.get("resultMsg", ""),
                "raw_response": body,
                "error": "" if success else (body.get("resultMsg") or f"HTTP {resp.status_code}"),
            }
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning("KRA VSCU connection error to %s: %s", url, exc)
            return {
                "success": False,
                "status_code": None,
                "response_time_ms": elapsed_ms,
                "data": {},
                "result_code": "CONN_ERROR",
                "result_message": str(exc),
                "raw_response": {},
                "error": f"Connection error: {type(exc).__name__} - {exc}",
            }

    def check_server_time(self) -> dict[str, Any]:
        """Call /selectServerTime to verify API connectivity and sync clocks."""
        res = self._post("/selectServerTime", {})
        if res["success"]:
            self.profile.last_sync_at = timezone.now()
            self.profile.save(update_fields=["last_sync_at", "updated_at"])
        return res

    def initialize_device(self) -> dict[str, Any]:
        """Perform VSCU device initialization handshake (/selectInitInfo)."""
        payload = {
            "tin": self.profile.tin,
            "bhfId": self.profile.bhf_id,
            "dvcSrlNo": self.profile.dvc_srl_no,
        }
        res = self._post("/selectInitInfo", payload)
        if res["success"]:
            info = res.get("raw_response", {}).get("info") or res["data"]
            self.profile.cm_key = info.get("cmKey") or self.profile.cm_key
            self.profile.sdc_id = info.get("sdcId") or info.get("dvcId") or self.profile.sdc_id
            self.profile.mrc_no = info.get("mrcNo") or self.profile.mrc_no
            self.profile.taxpayer_name = info.get("taxprNm") or self.profile.taxpayer_name
            self.profile.branch_name = info.get("bhfNm") or self.profile.branch_name
            self.profile.is_initialized = True
            self.profile.last_sync_at = timezone.now()
            self.profile.save(
                update_fields=[
                    "cm_key",
                    "sdc_id",
                    "mrc_no",
                    "taxpayer_name",
                    "branch_name",
                    "is_initialized",
                    "last_sync_at",
                    "updated_at",
                ]
            )
        return res

    def transmit_sales(self, fiscal_receipt: FiscalReceipt) -> dict[str, Any]:
        """Transmit sales transaction or credit note to KRA VSCU (/saveTrnsSalesOsdc)."""
        payload = fiscal_receipt.raw_request_payload
        res = self._post("/saveTrnsSalesOsdc", payload)

        # Log transmission attempt
        FiscalSubmissionLog.all_objects.create(
            tenant=fiscal_receipt.tenant,
            fiscal_receipt=fiscal_receipt,
            endpoint="/saveTrnsSalesOsdc",
            status_code=res.get("status_code"),
            success=res["success"],
            response_time_ms=res.get("response_time_ms"),
            error_message=res.get("error", ""),
            response_payload=res.get("raw_response", {}),
        )

        return res
