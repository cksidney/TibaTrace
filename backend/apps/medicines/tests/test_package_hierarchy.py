import decimal

import pytest
from django.core.exceptions import ValidationError

from apps.medicines.models import PackageDefinition
from apps.medicines.services import PackageHierarchyService


@pytest.mark.django_db
def test_package_hierarchy_conversions_and_cycle_prevention():
    pkg_base = PackageDefinition.objects.create(
        code="TAB-BASE", description="1 Tablet", unit_of_measure="tab", pack_level="BASE", is_dispensing_unit=True
    )
    pkg_blister = PackageDefinition.objects.create(
        code="BLISTER-10",
        description="Blister of 10 Tablets",
        parent_package=pkg_base,
        quantity_in_parent=decimal.Decimal("10"),
        unit_of_measure="tab",
        pack_level="INNER",
    )
    pkg_box = PackageDefinition.objects.create(
        code="BOX-10",
        description="Box of 10 Blisters",
        parent_package=pkg_blister,
        quantity_in_parent=decimal.Decimal("10"),
        unit_of_measure="blister",
        pack_level="OUTER",
    )

    assert pkg_box.parent_package == pkg_blister
    assert pkg_blister.parent_package == pkg_base

    # Direct cycle validation test
    with pytest.raises(ValidationError):
        PackageHierarchyService.validate_no_cycles(pkg_base, pkg_base)

    # Indirect cycle validation test (pkg_base -> pkg_box -> pkg_blister -> pkg_base)
    with pytest.raises(ValidationError):
        PackageHierarchyService.validate_no_cycles(pkg_base, pkg_box)
