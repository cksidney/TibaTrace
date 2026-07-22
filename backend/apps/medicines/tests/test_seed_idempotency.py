import pytest
from django.core.management import call_command

from apps.medicines.models import ActiveSubstance, ClinicalMedicinalProduct, CommercialSKU


@pytest.mark.django_db
def test_seed_catalogue_command_idempotency():
    # 1. Run first time
    call_command("seed_medicine_catalogue")
    sub_count_1 = ActiveSubstance.all_objects.count()
    cmp_count_1 = ClinicalMedicinalProduct.all_objects.count()
    sku_count_1 = CommercialSKU.all_objects.count()

    assert sub_count_1 >= 20
    assert cmp_count_1 >= 25
    assert sku_count_1 >= 40

    # 2. Run second time
    call_command("seed_medicine_catalogue")
    sub_count_2 = ActiveSubstance.all_objects.count()
    cmp_count_2 = ClinicalMedicinalProduct.all_objects.count()
    sku_count_2 = CommercialSKU.all_objects.count()

    # Exact equality proves zero duplicate creation
    assert sub_count_1 == sub_count_2
    assert cmp_count_1 == cmp_count_2
    assert sku_count_1 == sku_count_2
