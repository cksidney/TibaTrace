"""Phase 14B–17 Comprehensive Test Suite.

Tests:
  1. Phase 14B Notification Engine & Regulatory Expiry Engine
  2. Phase 15 Enterprise Compliance Reporting Engine (CSV, Excel, PDF, JSON)
  3. Phase 16 Certification Evidence Engine (Package generation & ZIP export)
  4. Phase 17 Production Activation Governance & National Integration Gateway
"""
import json
import zipfile
from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.integrations.gateway import NationalIntegrationGateway
from apps.integrations.models import (
    ActivationState,
    ProviderConfiguration,
    ProviderEnvironment,
    ProviderType,
)
from apps.notifications.models import (
    IntegrationNotification,
    NotificationEventCategory,
    NotificationSeverity,
    RegulatoryExpiryTrack,
)
from apps.notifications.service import (
    emit_integration_notification,
    evaluate_regulatory_expiries,
)
from apps.platform.reporting.certification_engine import CertificationEvidenceGenerator
from apps.platform.reporting.compliance_engine import (
    ComplianceReportEngine,
    ComplianceReportType,
)
from apps.tenancy.models import Tenant

User = get_user_model()


class Phase14bNotificationAndExpiryEngineTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Notification Test Pharmacy", slug="notif-pharm")
        self.user = User.objects.create_user(username="notif_admin", email="notif@test.com", password="password", tenant=self.tenant)

    def test_emit_integration_notification(self):
        notif = emit_integration_notification(
            category=NotificationEventCategory.DHA_UNAVAILABLE,
            severity=NotificationSeverity.HIGH,
            title="DHA Endpoint Downtime",
            summary="DHA endpoint returned 503 Service Unavailable.",
            tenant_id=self.tenant.id,
        )
        self.assertIsNotNone(notif.id)
        self.assertEqual(notif.category, NotificationEventCategory.DHA_UNAVAILABLE)
        self.assertEqual(notif.severity, NotificationSeverity.HIGH)
        self.assertEqual(notif.truth_label, "MANUAL_INTERNAL_VERIFICATION")

    def test_regulatory_expiry_engine_evaluation(self):
        today = timezone.localdate()

        # Track expiring in 5 days (Crosses 180, 90, 60, 30, 14, 7 thresholds -> CRITICAL severity)
        track = RegulatoryExpiryTrack.all_objects.create(
            entity_type=RegulatoryExpiryTrack.EntityType.PREMISES_LICENCE,
            entity_id="PREM-EXP-123",
            tenant=self.tenant,
            display_name="Main Branch Premises Licence",
            expires_at=today + timedelta(days=5),
        )

        notified = evaluate_regulatory_expiries(tenant_id=self.tenant.id)
        self.assertEqual(len(notified), 1)
        track.refresh_from_db()
        self.assertEqual(track.last_notified_interval_days, 7)

        # Ensure notification record created
        notif = IntegrationNotification.all_objects.filter(tenant=self.tenant).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.severity, NotificationSeverity.CRITICAL)


class Phase15ComplianceReportingEngineTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Reporting Test Pharmacy", slug="report-pharm")

    def test_generate_json_compliance_report(self):
        result = ComplianceReportEngine.generate_report(
            report_type=ComplianceReportType.PREMISES,
            format_type="json",
            tenant_id=self.tenant.id,
        )
        self.assertEqual(result["content_type"], "application/json")
        data = json.loads(result["content"])
        self.assertIn("title", data)
        self.assertEqual(data["truth_label"], "MANUAL_INTERNAL_VERIFICATION")

    def test_generate_csv_compliance_report(self):
        result = ComplianceReportEngine.generate_report(
            report_type=ComplianceReportType.PRACTITIONERS,
            format_type="csv",
            tenant_id=self.tenant.id,
        )
        self.assertEqual(result["content_type"], "text/csv")
        self.assertIn("Practitioner Verification", result["content"])

    def test_generate_readiness_scorecard(self):
        result = ComplianceReportEngine.generate_report(
            report_type=ComplianceReportType.COMPLIANCE_READINESS,
            format_type="json",
        )
        data = json.loads(result["content"])
        self.assertEqual(data["readiness"]["dha_readiness_score"], "81.5%")


class Phase16CertificationEvidenceEngineTests(TestCase):
    def test_generate_evidence_package(self):
        package = CertificationEvidenceGenerator.generate_evidence_package("Test Auditor")
        self.assertEqual(package["metadata"]["operator"], "Test Auditor")
        self.assertEqual(package["metadata"]["truth_label"], "MANUAL_INTERNAL_VERIFICATION")
        self.assertIn("openapi_checksum", package)
        self.assertIn("quality_evidence", package)

    def test_export_evidence_zip(self):
        zip_bytes, filename = CertificationEvidenceGenerator.export_evidence_zip("Test Auditor")
        self.assertTrue(filename.endswith(".zip"))

        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            self.assertIn("manifest.json", names)
            self.assertIn("evidence_package.json", names)
            self.assertIn("readiness_matrix.json", names)


class DummyGateway(NationalIntegrationGateway):
    def send_payload(self, message_type: str, payload: dict, tenant_id: object | None = None) -> dict:
        self.verify_activation_gate()
        return {"status": "SUCCESS"}


class Phase17ActivationGovernanceAndGatewayTests(TestCase):
    def setUp(self):
        self.provider = ProviderConfiguration.all_objects.create(
            provider_type=ProviderType.DHA_HIE,
            environment=ProviderEnvironment.SANDBOX,
            display_name="DHA HIE Sandbox",
            activation_state=ActivationState.REQUESTED,
        )

    def test_unactivated_gateway_fails_closed(self):
        gw = DummyGateway(ProviderType.DHA_HIE, ProviderEnvironment.SANDBOX)
        self.assertFalse(gw.is_operational)
        with self.assertRaises(Exception):  # PermissionDenied
            gw.send_payload("TEST_MSG", {})

    def test_full_activation_lifecycle_transitions(self):
        self.assertEqual(self.provider.activation_state, ActivationState.REQUESTED)
        # Advance through stages
        self.provider.activation_state = ActivationState.UNDER_REVIEW
        self.provider.save()
        self.provider.activation_state = ActivationState.SECURITY_REVIEW
        self.provider.save()
        self.provider.activation_state = ActivationState.SANDBOX_CONFIGURED
        self.provider.save()
        self.provider.activation_state = ActivationState.SANDBOX_TESTING
        self.provider.save()
        self.provider.activation_state = ActivationState.SANDBOX_PASSED
        self.provider.save()
        self.provider.activation_state = ActivationState.CERTIFICATION_REVIEW
        self.provider.save()
        self.provider.activation_state = ActivationState.SECURITY_APPROVED
        self.provider.save()
        self.provider.activation_state = ActivationState.PRODUCTION_APPROVED
        self.provider.save()
        self.provider.activation_state = ActivationState.ACTIVE
        self.provider.save()

        gw = DummyGateway(ProviderType.DHA_HIE, ProviderEnvironment.SANDBOX)
        self.assertTrue(gw.is_operational)
        res = gw.send_payload("TEST_MSG", {})
        self.assertEqual(res["status"], "SUCCESS")
