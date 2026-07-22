import decimal

import pytest

from apps.medicines.models import (
    ActiveSubstance,
    AdministrationRoute,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    IngredientComposition,
    ManufacturedMedicinalProduct,
    Manufacturer,
    PackageDefinition,
    ProductIdentifier,
)
from apps.tenancy.models import Tenant


@pytest.mark.django_db
def test_clinical_product_and_multi_ingredient_composition():
    tenant = Tenant.objects.create(name="Test Pharmacy", slug="test-pharmacy")
    df = DoseForm.objects.create(code="TAB", name="Tablet")
    rt = AdministrationRoute.objects.create(code="PO", name="Oral")

    sub1 = ActiveSubstance.objects.create(is_global=True, code="SUB-AMO", canonical_name="Amoxicillin")
    sub2 = ActiveSubstance.objects.create(is_global=True, code="SUB-CLA", canonical_name="Clavulanic Acid")

    cmp = ClinicalMedicinalProduct.objects.create(
        tenant=tenant,
        code="CMP-AUG-625",
        canonical_name="Amoxicillin 500 mg + Clavulanate 125 mg Tablet",
        dose_form=df,
        status="ACTIVE",
    )
    cmp.routes.add(rt)

    ing1 = IngredientComposition.objects.create(
        clinical_product=cmp,
        active_substance=sub1,
        numerator_value=decimal.Decimal("500"),
        numerator_unit="mg",
        sequence=1,
    )
    ing2 = IngredientComposition.objects.create(
        clinical_product=cmp,
        active_substance=sub2,
        numerator_value=decimal.Decimal("125"),
        numerator_unit="mg",
        sequence=2,
    )

    assert cmp.ingredients.count() == 2
    assert cmp.routes.first().code == "PO"
    assert ing1.numerator_value == decimal.Decimal("500")
    assert ing2.sequence == 2


@pytest.mark.django_db
def test_manufactured_product_and_sku_hierarchy():
    tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
    df = DoseForm.objects.create(code="CAP", name="Capsule")
    cmp = ClinicalMedicinalProduct.objects.create(
        tenant=tenant, code="CMP-AMO-500", canonical_name="Amoxicillin 500 mg Capsule", dose_form=df
    )
    mfg = Manufacturer.objects.create(is_global=True, code="GSK", legal_name="GSK PLC")
    mp = ManufacturedMedicinalProduct.objects.create(
        tenant=tenant, code="MP-AMOX", brand_name="Amoxil", clinical_product=cmp, manufacturer=mfg
    )
    pkg = PackageDefinition.objects.create(code="BOX100", description="Box of 100", unit_of_measure="capsule")

    sku = CommercialSKU.objects.create(
        tenant=tenant,
        sku_code="SKU-AMOX-100",
        display_name="Amoxil 500mg 100s Box",
        manufactured_product=mp,
        package_definition=pkg,
        default_barcode="501234567890",
        status="ACTIVE",
    )

    pid = ProductIdentifier.objects.create(
        entity_type="SKU", entity_id=sku.pk, system="GTIN", value="05012345678900", is_primary=True
    )

    assert sku.manufactured_product.brand_name == "Amoxil"
    assert pid.value == "05012345678900"
