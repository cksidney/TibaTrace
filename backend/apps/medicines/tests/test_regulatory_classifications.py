import pytest

from apps.medicines.models import ClinicalMedicinalProduct, DoseForm, ManufacturedMedicinalProduct
from apps.tenancy.models import Tenant


@pytest.mark.django_db
def test_explicit_regulatory_classifications():
    tenant = Tenant.objects.create(name="Reg Tenant", slug="reg-tenant")
    df = DoseForm.objects.create(code="TAB", name="Tablet")

    valid_classifications = [
        "OTC",
        "PHARMACIST_ONLY",
        "PRESCRIPTION_ONLY",
        "CONTROLLED",
        "NARCOTIC",
        "PSYCHOTROPIC",
        "HOSPITAL_ONLY",
        "RESTRICTED",
        "INVESTIGATIONAL",
        "WITHDRAWN",
    ]

    for reg_cls in valid_classifications:
        cmp = ClinicalMedicinalProduct.objects.create(
            tenant=tenant,
            code=f"CMP-REG-{reg_cls}",
            canonical_name=f"Clinical Product {reg_cls}",
            dose_form=df,
            prescription_classification=reg_cls,
        )
        assert cmp.prescription_classification == reg_cls


@pytest.mark.django_db
def test_manufactured_product_licence_statuses():
    tenant = Tenant.objects.create(name="Licence Tenant", slug="licence-tenant")
    df = DoseForm.objects.create(code="CAP", name="Capsule")
    cmp = ClinicalMedicinalProduct.objects.create(
        tenant=tenant, code="CMP-LIC-01", canonical_name="Licence Test Product", dose_form=df
    )

    mp = ManufacturedMedicinalProduct.objects.create(
        tenant=tenant,
        code="MP-LIC-01",
        brand_name="Licence Brand",
        clinical_product=cmp,
        licence_status="LICENSED",
        status="REGISTERED",
    )

    assert mp.licence_status == "LICENSED"
    assert mp.status == "REGISTERED"
