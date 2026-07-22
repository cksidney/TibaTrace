import base64
import json

from dateutil.parser import parse
from django.utils import timezone

from apps.prescription.models import Prescription, PrescriptionItem
from apps.prescription.security.digital_signatures import SignatureFramework


class QRService:
    """
    Handles QR code generation and offline verification payloads.
    Provides verifiable metadata and signature hooks for prescription authenticity.
    """

    @staticmethod
    def generate_offline_payload(prescription: Prescription) -> str:
        """
        Generate a verifiable payload containing essential prescription metadata
        for offline POS scanning (e.g. Android POS).
        """
        payload = {
            "version": "1.0",
            "issuer": "DAWATRACE",
            "id": str(prescription.id),
            "issued_at": prescription.issued_at.isoformat() if prescription.issued_at else None,
            "expires_at": prescription.expires_at.isoformat() if prescription.expires_at else None,
            "patient_ref": prescription.patient.internal_reference_id if prescription.patient else None,
            "items_count": PrescriptionItem.all_objects.filter(
                tenant_id=prescription.tenant_id, prescription_id=prescription.id
            ).count(),
            "status": prescription.status
        }

        signature_envelope = SignatureFramework.sign_payload(payload)

        final_payload = {
            "data": payload,
            "security": signature_envelope
        }

        # Base64 encode for QR density optimization
        return base64.b64encode(json.dumps(final_payload).encode()).decode('utf-8')

    @staticmethod
    def validate_offline_payload(qr_string: str) -> bool:
        """
        Validates the QR payload's digital signature and expiration offline.
        """
        try:
            decoded = base64.b64decode(qr_string).decode('utf-8')
            payload_dict = json.loads(decoded)

            data = payload_dict.get("data")
            security = payload_dict.get("security")

            if not data or not security:
                return False

            # Verify Signature via Public Key PKI
            if not SignatureFramework.verify_signature(data, security):
                return False

            # Check Expiry
            if data.get("expires_at"):
                expires = parse(data["expires_at"])
                if expires < timezone.now():
                    return False

            return True
        except Exception:
            return False

    generate_payload = generate_offline_payload
