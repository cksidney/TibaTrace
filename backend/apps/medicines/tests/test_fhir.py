import decimal

import pytest

from apps.fhir.mappers.medication_mapper import FHIRMedicationMapper
from apps.medicines.models import ActiveSubstance, ClinicalMedicinalProduct, DoseForm, IngredientComposition


@pytest.mark.django_db
def test_fhir_medication_mapper_rendering():
    df = DoseForm.objects.create(code="TAB", name="Tablet")
    sub = ActiveSubstance.objects.create(is_global=True, code="SUB-PAR", canonical_name="Paracetamol")

    cmp = ClinicalMedicinalProduct.objects.create(
        is_global=True,
        code="CMP-PAR-500",
        canonical_name="Paracetamol 500 mg Tablet",
        dose_form=df,
        status="ACTIVE",
    )
    IngredientComposition.objects.create(
        clinical_product=cmp,
        active_substance=sub,
        numerator_value=decimal.Decimal("500"),
        numerator_unit="mg",
    )

    fhir_dict = FHIRMedicationMapper.clinical_product_to_fhir(cmp)

    assert fhir_dict["resourceType"] == "Medication"
    assert fhir_dict["status"] == "active"
    assert fhir_dict["code"]["text"] == "Paracetamol 500 mg Tablet"
    assert fhir_dict["form"]["text"] == "Tablet"
    assert len(fhir_dict["ingredient"]) == 1
    assert fhir_dict["ingredient"][0]["itemCodeableConcept"]["text"] == "Paracetamol"
