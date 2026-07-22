from __future__ import annotations

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.core.tenant_context import reset_current_tenant_id, set_current_tenant_id
from apps.terminology.models import (
    FHIRCodeSystemRegistration,
    FHIRTerminologyVersion,
    FHIRValueSetRegistration,
)
from apps.terminology.services import TerminologyService

pytestmark = [pytest.mark.django_db, pytest.mark.terminology]


@pytest.fixture(autouse=True)
def clear_terminology_cache():
    cache.clear()


@pytest.fixture
def terminology_records(tenant_a):
    version = FHIRTerminologyVersion.all_objects.create(
        tenant=tenant_a,
        canonical_url="https://dawatrace.health/fhir/terminology/tenant-a",
        version="2026.1",
        status="ACTIVE",
        publisher="Esenai Group Ltd",
        source_name="DawaTrace non-production test terminology",
        source_version="2026.1",
        licence="Internal test fixture only",
    )
    system = FHIRCodeSystemRegistration.all_objects.create(
        tenant=tenant_a,
        version=version,
        url="https://dawatrace.health/fhir/CodeSystem/test-medicines",
        name="DawaTraceTestMedicines",
        title="DawaTrace test medicines",
        concepts_json=[
            {"code": "A", "display": "Alpha medicine"},
            {"code": "B", "display": "Beta medicine", "inactive": True},
            {"code": "C", "display": "Charlie medicine"},
        ],
    )
    value_set = FHIRValueSetRegistration.all_objects.create(
        tenant=tenant_a,
        version=version,
        url="https://dawatrace.health/fhir/ValueSet/allowed-medicines",
        name="AllowedTestMedicines",
        title="Allowed test medicines",
        compose_json={
            "include": [{"system": system.url}],
            "exclude": [{"system": system.url, "concept": [{"code": "C"}]}],
        },
    )
    imported = FHIRValueSetRegistration.all_objects.create(
        tenant=tenant_a,
        version=version,
        url="https://dawatrace.health/fhir/ValueSet/imported-medicines",
        name="ImportedTestMedicines",
        compose_json={
            "include": [
                {
                    "system": system.url,
                    "concept": [{"code": "A", "display": "Alpha medicine"}],
                }
            ]
        },
    )
    importing = FHIRValueSetRegistration.all_objects.create(
        tenant=tenant_a,
        version=version,
        url="https://dawatrace.health/fhir/ValueSet/importing-medicines",
        name="ImportingTestMedicines",
        compose_json={"include": [{"valueSet": [imported.url]}]},
    )
    return {"version": version, "system": system, "value_set": value_set, "importing": importing}


def _parameter(response, name):
    return next(
        value
        for parameter in response.data.get("parameter", [])
        if parameter.get("name") == name
        for key, value in parameter.items()
        if key.startswith("value")
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_terminology_manager_fails_closed_without_context(terminology_records):
    assert FHIRCodeSystemRegistration.objects.count() == 0
    token = set_current_tenant_id(terminology_records["version"].tenant_id)
    try:
        assert FHIRCodeSystemRegistration.objects.count() == 1
    finally:
        reset_current_tenant_id(token)


def test_terminology_version_requires_explicit_scope(tenant_a):
    with pytest.raises(ValidationError):
        FHIRTerminologyVersion.all_objects.create(
            tenant=tenant_a,
            is_global=True,
            canonical_url="https://example.test/invalid-scope",
            version="1",
            source_name="test",
            source_version="1",
            licence="test only",
        )


def test_code_system_rejects_duplicate_or_blank_concept_codes(terminology_records):
    registration = FHIRCodeSystemRegistration(
        tenant=terminology_records["version"].tenant,
        version=terminology_records["version"],
        url="https://example.test/duplicate-codes",
        name="DuplicateCodes",
        concepts_json=[{"code": "A"}, {"code": "A"}],
    )
    with pytest.raises(ValidationError):
        registration.full_clean()


def test_value_set_rejects_invalid_compose(terminology_records):
    registration = FHIRValueSetRegistration(
        tenant=terminology_records["version"].tenant,
        version=terminology_records["version"],
        url="https://example.test/invalid-value-set",
        name="InvalidValueSet",
        compose_json={"include": [{"concept": [{"code": "A"}]}]},
    )
    with pytest.raises(ValidationError):
        registration.full_clean()


@pytest.mark.parametrize(
    ("code", "display", "expected", "message"),
    [
        ("A", None, True, ""),
        ("UNKNOWN", None, False, "not present"),
        ("B", None, False, "inactive"),
        ("A", "Wrong display", False, "Display does not match"),
    ],
)
def test_validate_code_service_handles_known_unknown_inactive_and_display(
    terminology_records, code, display, expected, message
):
    result = TerminologyService.validate_code(
        system=terminology_records["system"].url,
        code=code,
        display=display,
        tenant_id=str(terminology_records["version"].tenant_id),
    )
    assert result.result is expected
    assert message.casefold() in result.message.casefold()


def test_validate_code_rejects_unknown_version(terminology_records):
    result = TerminologyService.validate_code(
        system=terminology_records["system"].url,
        code="A",
        version="missing",
        tenant_id=str(terminology_records["version"].tenant_id),
    )
    assert result.result is False
    assert "unavailable" in result.message


def test_tenant_registration_precedes_global_registration(terminology_records):
    global_version = FHIRTerminologyVersion.all_objects.create(
        tenant=None,
        is_global=True,
        canonical_url=terminology_records["system"].url,
        version="9999",
        status="ACTIVE",
        source_name="Global test terminology",
        source_version="9999",
        licence="Internal test fixture only",
    )
    FHIRCodeSystemRegistration.all_objects.create(
        tenant=None,
        is_global=True,
        version=global_version,
        url=terminology_records["system"].url,
        name="GlobalFallback",
        concepts_json=[{"code": "GLOBAL", "display": "Global"}],
    )
    selected = TerminologyService.code_system(
        terminology_records["system"].url,
        str(terminology_records["version"].tenant_id),
    )
    assert selected.id == terminology_records["system"].id


def test_global_terminology_is_visible_but_private_tenant_terminology_is_not(
    terminology_records, tenant_b
):
    global_version = FHIRTerminologyVersion.all_objects.create(
        tenant=None,
        is_global=True,
        canonical_url="https://dawatrace.health/fhir/CodeSystem/global-test",
        version="1",
        status="ACTIVE",
        source_name="Global test terminology",
        source_version="1",
        licence="Internal test fixture only",
    )
    global_system = FHIRCodeSystemRegistration.all_objects.create(
        tenant=None,
        is_global=True,
        version=global_version,
        url=global_version.canonical_url,
        name="GlobalTest",
        concepts_json=[{"code": "G", "display": "Global concept"}],
    )
    assert TerminologyService.code_system(global_system.url, str(tenant_b.id)).id == global_system.id
    assert TerminologyService.code_system(terminology_records["system"].url, str(tenant_b.id)) is None


def test_simple_expansion_applies_exclusion_and_paging(terminology_records):
    tenant_id = str(terminology_records["version"].tenant_id)
    rows = TerminologyService.expand(
        url=terminology_records["value_set"].url, tenant_id=tenant_id, offset=0, count=1
    )
    assert rows == [{"system": terminology_records["system"].url, "code": "A", "display": "Alpha medicine"}]


def test_fhir_code_system_validate_code_operation(terminology_records, clinical_user):
    response = _client(clinical_user).get(
        "/api/fhir/r4/CodeSystem/$validate-code",
        {
            "url": terminology_records["system"].url,
            "code": "A",
            "display": "Alpha medicine",
        },
        HTTP_X_TENANT_ID=str(terminology_records["version"].tenant_id),
    )
    assert response.status_code == 200
    assert response.data["resourceType"] == "Parameters"
    assert _parameter(response, "result") is True


@pytest.mark.parametrize(
    ("code", "display", "expected_message"),
    [
        ("UNKNOWN", None, "unknown"),
        ("B", None, "inactive"),
        ("A", "Wrong display", "Display does not match"),
    ],
)
def test_fhir_code_system_validate_code_failures_are_explicit(
    terminology_records, clinical_user, code, display, expected_message
):
    params = {"url": terminology_records["system"].url, "code": code}
    if display:
        params["display"] = display
    response = _client(clinical_user).get(
        "/api/fhir/r4/CodeSystem/$validate-code",
        params,
        HTTP_X_TENANT_ID=str(terminology_records["version"].tenant_id),
    )
    assert response.status_code == 200
    assert _parameter(response, "result") is False
    assert expected_message.casefold() in _parameter(response, "message").casefold()


def test_fhir_value_set_expand_applies_exclusion_active_filter_and_paging(
    terminology_records, clinical_user
):
    response = _client(clinical_user).get(
        "/api/fhir/r4/ValueSet/$expand",
        {
            "url": terminology_records["value_set"].url,
            "activeOnly": "true",
            "filter": "alpha",
            "offset": "0",
            "count": "1",
        },
        HTTP_X_TENANT_ID=str(terminology_records["version"].tenant_id),
    )
    assert response.status_code == 200
    assert response.data["resourceType"] == "ValueSet"
    assert response.data["expansion"]["total"] == 1
    assert response.data["expansion"]["contains"][0]["code"] == "A"


def test_fhir_value_set_expands_imports(terminology_records, clinical_user):
    response = _client(clinical_user).get(
        "/api/fhir/r4/ValueSet/$expand",
        {"url": terminology_records["importing"].url},
        HTTP_X_TENANT_ID=str(terminology_records["version"].tenant_id),
    )
    assert response.status_code == 200
    assert [row["code"] for row in response.data["expansion"]["contains"]] == ["A"]


def test_fhir_value_set_validate_code(terminology_records, clinical_user):
    response = _client(clinical_user).get(
        "/api/fhir/r4/ValueSet/$validate-code",
        {"url": terminology_records["value_set"].url, "code": "A", "system": terminology_records["system"].url},
        HTTP_X_TENANT_ID=str(terminology_records["version"].tenant_id),
    )
    assert response.status_code == 200
    assert _parameter(response, "result") is True


def test_fhir_terminology_operation_requires_capability(terminology_records, cashier_user):
    response = _client(cashier_user).get(
        "/api/fhir/r4/ValueSet/$expand",
        {"url": terminology_records["value_set"].url},
        HTTP_X_TENANT_ID=str(terminology_records["version"].tenant_id),
    )
    assert response.status_code == 403


def test_fhir_terminology_operation_is_tenant_isolated(terminology_records, clinical_user, tenant_b):
    clinical_user.is_platform_admin = True
    clinical_user.save(update_fields=["is_platform_admin"])
    response = _client(clinical_user).get(
        "/api/fhir/r4/ValueSet/$expand",
        {"url": terminology_records["value_set"].url},
        HTTP_X_TENANT_ID=str(tenant_b.id),
    )
    assert response.status_code == 400
    assert response.data["resourceType"] == "OperationOutcome"


def test_compose_filter_fails_closed_until_supported(terminology_records, clinical_user):
    filtered = FHIRValueSetRegistration.all_objects.create(
        tenant=terminology_records["version"].tenant,
        version=terminology_records["version"],
        url="https://dawatrace.health/fhir/ValueSet/filter-test",
        name="FilterTest",
        compose_json={
            "include": [
                {
                    "system": terminology_records["system"].url,
                    "filter": [{"property": "code", "op": "=", "value": "A"}],
                }
            ]
        },
    )
    response = _client(clinical_user).get(
        "/api/fhir/r4/ValueSet/$expand",
        {"url": filtered.url},
        HTTP_X_TENANT_ID=str(terminology_records["version"].tenant_id),
    )
    assert response.status_code == 400
    assert response.data["resourceType"] == "OperationOutcome"
    assert "filters are not supported" in response.data["issue"][0]["diagnostics"]
