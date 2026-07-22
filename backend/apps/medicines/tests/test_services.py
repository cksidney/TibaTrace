import decimal

import pytest
from django.core.exceptions import ValidationError

from apps.medicines.models import ActiveSubstance, DoseForm, PackageDefinition
from apps.medicines.services import (
    BranchAssortmentService,
    IngredientCompositionService,
    MedicineCatalogueService,
)
from apps.organizations.models import Location, Organization
from apps.tenancy.models import Tenant


@pytest.mark.django_db
def test_medicine_catalogue_service_lifecycle():
    tenant = Tenant.objects.create(name="Service Tenant", slug="service-tenant")
    df = DoseForm.objects.create(code="TAB", name="Tablet")
    sub = ActiveSubstance.objects.create(is_global=True, code="SUB-PAR", canonical_name="Paracetamol")

    # 1. Create clinical product in DRAFT
    cmp = MedicineCatalogueService.create_clinical_product(
        tenant=tenant,
        code="CMP-PAR-500",
        canonical_name="Paracetamol 500 mg Tablet",
        dose_form=df,
    )
    assert cmp.status == "DRAFT"

    # 2. Activation fails without ingredients
    with pytest.raises(ValidationError):
        MedicineCatalogueService.activate_clinical_product(product=cmp)

    # 3. Add ingredient & activate
    IngredientCompositionService.add_ingredient(
        clinical_product=cmp,
        active_substance=sub,
        numerator_value=decimal.Decimal("500"),
        numerator_unit="mg",
    )
    activated = MedicineCatalogueService.activate_clinical_product(product=cmp)
    assert activated.status == "ACTIVE"

    # 4. Register Manufactured Product & SKU
    mp = MedicineCatalogueService.register_manufactured_product(
        tenant=tenant,
        code="MP-PAN-500",
        brand_name="Panadol",
        clinical_product=activated,
    )
    pkg = PackageDefinition.objects.create(code="BOX100", description="Box of 100", unit_of_measure="tab")
    sku = MedicineCatalogueService.register_sku(
        tenant=tenant,
        sku_code="SKU-PAN-100",
        display_name="Panadol 500mg 100s Box",
        manufactured_product=mp,
        package_definition=pkg,
        default_barcode="600111222333",
    )

    assert sku.sku_code == "SKU-PAN-100"
    assert sku.default_barcode == "600111222333"

    # 5. Enable Branch Assortment
    org = Organization.objects.create(tenant=tenant, code="MAIN-ORG", name="Main Org")
    loc = Location.objects.create(tenant=tenant, organization=org, code="MAIN-BRANCH", name="Main Branch")
    assortment = BranchAssortmentService.enable_sku_for_branch(tenant=tenant, location=loc, sku=sku)
    assert assortment.is_sellable is True
