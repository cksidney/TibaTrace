"""KRA eTIMS QR code and receipt verification generator.

Generates official KRA eTIMS verification URLs and SVG QR codes for 80mm
thermal POS receipts and electronic fiscal documents.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import urllib.parse

import qrcode
import qrcode.image.svg

KRA_ETIMS_VERIFY_URL_PRODUCTION = "https://etims.kra.go.ke/common/link/etims/receipt/index.html"
KRA_ETIMS_VERIFY_URL_SANDBOX = "https://etims-sbx.kra.go.ke/common/link/etims/receipt/index.html"


def get_kra_verify_base_url(environment: str = "SANDBOX") -> str:
    """Return the KRA verification portal base URL for the given environment."""
    if environment.upper() == "PRODUCTION":
        return KRA_ETIMS_VERIFY_URL_PRODUCTION
    return KRA_ETIMS_VERIFY_URL_SANDBOX


def construct_kra_qr_payload(
    *,
    tin: str,
    bhf_id: str,
    sdc_id: str,
    invoice_no: int,
    receipt_date_str: str,
    internal_data: str,
    receipt_signature: str,
) -> str:
    """Construct the raw payload parameter string encoded into the KRA QR code."""
    # Standard format: internal_data + receipt_signature or concatenated key components
    if internal_data and receipt_signature:
        return f"{internal_data}{receipt_signature}"
    components = [
        tin or "NO_TIN",
        bhf_id or "00",
        sdc_id or "SDC00000000",
        str(invoice_no),
        receipt_date_str or "",
    ]
    return "-".join(components)


def build_kra_qr_verification_url(
    *,
    payload: str,
    environment: str = "SANDBOX",
) -> str:
    """Build the full clickable/scannable KRA eTIMS verification URL."""
    base = get_kra_verify_base_url(environment)
    encoded = urllib.parse.quote(payload, safe="")
    return f"{base}?qrCode={encoded}"


def generate_qr_svg(content: str, box_size: int = 10, border: int = 2) -> str:
    """Generate an inline SVG string for the given content."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
        image_factory=qrcode.image.svg.SvgPathImage,
    )
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image()
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def generate_qr_data_uri(svg_content: str) -> str:
    """Wrap SVG content into a base64 Data URI suitable for img tags."""
    encoded = base64.b64encode(svg_content.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def compute_offline_receipt_signature(
    *,
    tin: str,
    bhf_id: str,
    invoice_no: int,
    total_amount: str,
    date_str: str,
    secret_key: str = "",
) -> tuple[str, str]:
    """Compute deterministic internal data and signature for offline/provisional receipts.

    Returns:
        tuple (internal_data, receipt_signature)
    """
    raw_str = f"{tin}|{bhf_id}|{invoice_no}|{total_amount}|{date_str}"
    key = (secret_key or tin or "tibatrace-vscu").encode("utf-8")
    mac = hmac.new(key, raw_str.encode("utf-8"), hashlib.sha256).hexdigest()
    internal_data = mac[:16].upper()
    receipt_signature = mac[16:32].upper()
    return internal_data, receipt_signature
