"""The clinical section of the HQ workspace payload.

`cds`, `terminology` and `clinical` had models, endpoints and rows, and no
surface anywhere in the app. The clinical view offered three cards -- Encounters,
Decision support, Terminology -- that linked to `#clinical`, the view they were
already on, so they read as navigation to a management screen that did not
exist.

The rows come through this aggregate rather than /api/cds/, /api/terminology/
and /api/clinical/ because those carry TenantCapabilityPermission, which returns
False whenever the request has no tenant, and then filter on `request.tenant_id`.
A platform administrator has no tenant, so they get a 403 and, past it, an empty
list. `_scope` returns every tenant's rows when none is selected, which is what
"All tenants" means in the scope picker.
"""
from datetime import date, timedelta

import pytest

from apps.cds.models import ClinicalKnowledgeRelease
from apps.clinical.models import ClinicalEncounter
from apps.organizations.models import Location, Organization
from apps.patients.models import Patient
from apps.platform.admin_shell import build_hq_workspace_context
from apps.tenancy.models import Tenant
from apps.terminology.models import FHIRCodeSystemRegistration, FHIRTerminologyVersion


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name="Clin Tenant", slug="clin-tenant")


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name="Other Tenant", slug="other-tenant")


def add_release(tenant, code, *, active=True):
    return ClinicalKnowledgeRelease.all_objects.create(
        tenant=tenant, code=code, version="2.1", source="BNF",
        source_version="2026.07", licence="INTERNAL",
        effective_date=date.today() - timedelta(days=3), is_active=active,
        checksum_sha256="a" * 64,
    )


class TestTheSectionExists:
    def test_the_payload_carries_a_clinical_section(self, tenant):
        add_release(tenant, "REL-1")
        context = build_hq_workspace_context(str(tenant.pk))
        assert "clinical" in context
        assert context["clinical"]["counts"]["knowledge_releases"] == 1
        assert "substitutions" in context["clinical"]["counts"]
        assert "dispensing_labels" in context["clinical"]["counts"]
        assert "conditions" in context["clinical"]["counts"]
        assert "observations" in context["clinical"]["counts"]
        assert "fhir_idempotency_records" in context["clinical"]["counts"]
        assert context["clinical"]["conditions"] == []
        assert context["clinical"]["observations"] == []
        assert context["clinical"]["fhir_idempotency_records"] == []

    def test_a_release_is_reported_with_its_real_fields(self, tenant):
        add_release(tenant, "REL-BNF")
        row = build_hq_workspace_context(str(tenant.pk))["clinical"]["knowledge_releases"][0]
        assert row["code"] == "REL-BNF"
        assert row["version"] == "2.1"
        assert row["source"] == "BNF"
        assert row["is_active"] is True

    def test_the_checksum_is_truncated_rather_than_dropped(self, tenant):
        """The digest ties a screening decision to the rules that produced it.

        Twelve characters is enough to compare against a published digest by eye
        without turning the row into a wall of hex.
        """
        add_release(tenant, "REL-SUM")
        row = build_hq_workspace_context(str(tenant.pk))["clinical"]["knowledge_releases"][0]
        assert row["checksum"] == "a" * 12
        assert row["checksum_full"] == "a" * 64

    def test_an_inactive_release_is_listed_but_counted_separately(self, tenant):
        # It still has to be visible: knowing a release was retired is the point
        # of showing the list at all.
        add_release(tenant, "REL-OLD", active=False)
        clinical = build_hq_workspace_context(str(tenant.pk))["clinical"]
        assert clinical["counts"]["knowledge_releases"] == 1
        assert clinical["counts"]["active_knowledge_releases"] == 0
        assert clinical["knowledge_releases"][0]["is_active"] is False


class TestScope:
    def test_a_tenant_sees_only_its_own_encounters(self, tenant, other_tenant):
        for owner, number in ((tenant, "PAT-A"), (other_tenant, "PAT-B")):
            org = Organization.all_objects.create(
                tenant=owner, code=f"O-{number}", name="Org"
            )
            location = Location.all_objects.create(
                tenant=owner, organization=org, code=f"L-{number}", name="Site"
            )
            patient = Patient.all_objects.create(
                tenant=owner, internal_reference_id=f"INT-{number}",
                patient_number=number, first_name="Test", last_name=number,
            )
            ClinicalEncounter.all_objects.create(
                tenant=owner, patient=patient, organization=org, location=location,
                status="FINISHED", encounter_class="AMB",
            )

        names = {
            e["patient_name"]
            for e in build_hq_workspace_context(str(tenant.pk))["clinical"]["encounters"]
        }
        assert names == {"Test PAT-A"}

    def test_no_tenant_means_every_tenant(self, tenant, other_tenant):
        """What "All tenants" means for a platform administrator.

        The per-app collections cannot answer this: they filter on the request's
        tenant, so with none set they return nothing rather than everything.
        """
        add_release(tenant, "REL-ONE")
        add_release(other_tenant, "REL-TWO")
        codes = {
            r["code"]
            for r in build_hq_workspace_context(None)["clinical"]["knowledge_releases"]
        }
        assert codes == {"REL-ONE", "REL-TWO"}


class TestTerminology:
    def test_a_code_system_is_reported_with_its_concept_count(self, tenant):
        version = FHIRTerminologyVersion.all_objects.create(
            tenant=tenant, canonical_url="http://tibatrace.test/cs", version="1.0",
            publisher="TibaTrace", status="active",
            source_name="TibaTrace", source_version="1.0", licence="INTERNAL",
        )
        FHIRCodeSystemRegistration.all_objects.create(
            tenant=tenant, version=version, url="http://tibatrace.test/cs",
            name="TibaCodes", title="TibaTrace codes", content_mode="complete",
            concepts_json=[{"code": "A"}, {"code": "B"}, {"code": "C"}],
        )
        row = build_hq_workspace_context(str(tenant.pk))["clinical"]["code_systems"][0]
        assert row["name"] == "TibaCodes"
        assert row["concept_count"] == 3

    def test_nothing_registered_reports_an_empty_list_not_a_placeholder(self, tenant):
        clinical = build_hq_workspace_context(str(tenant.pk))["clinical"]
        assert clinical["code_systems"] == []
        assert clinical["value_sets"] == []
        assert clinical["counts"]["code_systems"] == 0
