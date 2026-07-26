import decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.core.tenant_context import set_current_tenant_id
from apps.fhir.mappers.medication_mapper import FHIRMedicationMapper
from apps.medicines.models import (
    ActiveSubstance,
    ClinicalMedicinalProduct,
    DoseForm,
    IngredientComposition,
)
from apps.tenancy.models import Tenant

User = get_user_model()


def add_products(tenant, start=0, count=5):
    """Clinical products carrying the two relations the serialiser reads."""
    dose_form = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})[0]
    substance = ActiveSubstance.objects.get_or_create(
        code="SUB-PAR", defaults={"is_global": True, "canonical_name": "Paracetamol"}
    )[0]
    for index in range(start, start + count):
        product = ClinicalMedicinalProduct.objects.create(
            tenant=tenant, code=f"CMP-PERF-{index}",
            canonical_name=f"Perf Product #{index}", dose_form=dose_form,
        )
        IngredientComposition.objects.create(
            clinical_product=product, active_substance=substance,
            numerator_value=decimal.Decimal("500"), numerator_unit="mg",
        )


def build_products(product_count=5):
    tenant = Tenant.objects.create(name="Perf Tenant", slug="perf-tenant")
    user = User.objects.create_user(  # nosec B106
        username="perfuser", email="perf@test.com", password="password123",
        tenant=tenant,
    )
    set_current_tenant_id(str(tenant.pk))
    add_products(tenant, start=0, count=product_count)
    return tenant, user


@pytest.mark.django_db
def test_query_count_performance_assertions(django_assert_num_queries):
    tenant, _user = build_products(product_count=5)

    # FHIR Medication mapper should render in bounded queries
    cmp_sample = ClinicalMedicinalProduct.objects.filter(tenant=tenant).prefetch_related("ingredients__active_substance", "dose_form").first()
    assert cmp_sample is not None

    with django_assert_num_queries(0):  # Prefetched data requires 0 additional queries
        fhir_res = FHIRMedicationMapper.clinical_product_to_fhir(cmp_sample)
        assert fhir_res["resourceType"] == "Medication"


@pytest.mark.django_db
def test_the_clinical_product_list_does_not_issue_a_query_per_row(
    django_assert_num_queries,
):
    """The list must cost the same number of queries whatever the row count.

    This replaces an assertion of `django_assert_num_queries(1)` on the same
    endpoint. That passed, but vacuously: the viewset declared its queryset as a
    class attribute built from the tenant-strict manager, which is evaluated at
    import when there is no tenant context, so it was frozen empty. One query
    returning no rows satisfies any bound, and the N+1 underneath it -- a query
    per row for `dose_form_name`, and one per ingredient for the substance name
    -- was invisible.

    Counting queries at a fixed row count would reintroduce the same weakness in
    a different form, since the number would still need updating whenever the
    serialiser changed and nothing would say why. Comparing two row counts tests
    the property directly: bounded means it does not grow.
    """
    tenant, user = build_products(product_count=2)
    client = APIClient()
    client.force_authenticate(user=user)

    def list_products():
        with CaptureQueriesContext(connection) as captured:
            response = client.get(
                "/api/medicines/clinical-products/", HTTP_X_TENANT_ID=str(tenant.pk)
            )
            assert response.status_code == 200
        body = response.json()
        rows = body["results"] if isinstance(body, dict) and "results" in body else body
        return rows, len(captured)

    rows_for_two, queries_for_two = list_products()

    # The assertion the old test was missing. Without it everything below is
    # true of an endpoint that returns nothing.
    assert len(rows_for_two) == 2, (
        "The clinical-product list returned no rows for a tenant that has them, "
        "so the query count below would be measuring an empty response."
    )
    assert rows_for_two[0]["dose_form_name"] == "Tablet"
    assert rows_for_two[0]["ingredients"][0]["active_substance_name"] == "Paracetamol"

    add_products(tenant, start=2, count=8)
    rows_for_ten, queries_for_ten = list_products()
    assert len(rows_for_ten) == 10

    assert queries_for_ten == queries_for_two, (
        f"Five times the rows cost {queries_for_ten} queries against "
        f"{queries_for_two}. The list is issuing a query per row: check that "
        "every relation the serialiser reads is in select_related or "
        "prefetch_related on the viewset."
    )
