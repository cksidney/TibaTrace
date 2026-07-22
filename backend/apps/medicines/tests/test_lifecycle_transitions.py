import decimal

import pytest
from django.core.exceptions import ValidationError

from apps.medicines.models import (
    ActiveSubstance,
    DoseForm,
    PackageDefinition,
)
from apps.medicines.services import IngredientCompositionService, MedicineCatalogueService
from apps.tenancy.models import Tenant


@pytest.mark.django_db
def test_lifecycle_transitions_and_validations():
    tenant = Tenant.objects.create(name="Lifecycle Tenant", slug="lc-tenant")
    df = DoseForm.objects.create(code="TAB", name="Tablet")
    sub = ActiveSubstance.objects.create(is_global=True, code="SUB-PAR", canonical_name="Paracetamol")

    # 1. CMP lifecycle
    cmp = MedicineCatalogueService.create_clinical_product(
        tenant=tenant, code="CMP-PAR-500", canonical_name="Paracetamol 500 mg Tablet", dose_form=df
    )
    assert cmp.status == "DRAFT"

    with pytest.raises(ValidationError):
        MedicineCatalogueService.activate_clinical_product(product=cmp)

    IngredientCompositionService.add_ingredient(
        clinical_product=cmp, active_substance=sub, numerator_value=decimal.Decimal("500"), numerator_unit="mg"
    )

    activated_cmp = MedicineCatalogueService.activate_clinical_product(product=cmp)
    assert activated_cmp.status == "ACTIVE"

    # 2. Manufactured Product lifecycle
    mp = MedicineCatalogueService.register_manufactured_product(
        tenant=tenant, code="MP-PAN-500", brand_name="Panadol", clinical_product=activated_cmp
    )
    assert mp.status == "REGISTERED"

    # 3. SKU lifecycle
    pkg = PackageDefinition.objects.create(code="BOX100", description="Box of 100", unit_of_measure="tab")
    sku = MedicineCatalogueService.register_sku(
        tenant=tenant,
        sku_code="SKU-PAN-100",
        display_name="Panadol 500mg 100s Box",
        manufactured_product=mp,
        package_definition=pkg,
        default_barcode="600111222333",
    )
    assert sku.status == "ACTIVE"
