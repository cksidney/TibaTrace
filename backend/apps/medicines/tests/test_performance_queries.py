import decimal

import pytest
from django.contrib.auth import get_user_model
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


@pytest.mark.django_db
def test_query_count_performance_assertions(django_assert_num_queries):
    tenant = Tenant.objects.create(name="Perf Tenant", slug="perf-tenant")
    user = User.objects.create_user(username="perfuser", email="perf@test.com", password="password123", tenant=tenant)  # nosec B106
    set_current_tenant_id(str(tenant.pk))

    df = DoseForm.objects.create(code="TAB", name="Tablet")
    sub = ActiveSubstance.objects.create(is_global=True, code="SUB-PAR", canonical_name="Paracetamol")

    # Create 5 clinical products with ingredients
    for i in range(5):
        cmp = ClinicalMedicinalProduct.objects.create(
            tenant=tenant, code=f"CMP-PERF-{i}", canonical_name=f"Perf Product #{i}", dose_form=df
        )
        IngredientComposition.objects.create(
            clinical_product=cmp,
            active_substance=sub,
            numerator_value=decimal.Decimal("500"),
            numerator_unit="mg",
        )

    # FHIR Medication mapper should render in bounded queries
    cmp_sample = ClinicalMedicinalProduct.objects.filter(tenant=tenant).prefetch_related("ingredients__active_substance", "dose_form").first()
    assert cmp_sample is not None

    with django_assert_num_queries(0):  # Prefetched data requires 0 additional queries
        fhir_res = FHIRMedicationMapper.clinical_product_to_fhir(cmp_sample)
        assert fhir_res["resourceType"] == "Medication"

    # API List view uses select_related / prefetch_related
    client = APIClient()
    client.force_authenticate(user=user)
    with django_assert_num_queries(1):  # Single query fetching list + related prefetched data
        res = client.get("/api/medicines/clinical-products/", HTTP_X_TENANT_ID=str(tenant.pk))
        assert res.status_code == 200
