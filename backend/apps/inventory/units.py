"""Barcode quantities are converted once into the SKU's stock/selling unit."""

from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.inventory.models import BarcodeMaster


def normalize_barcode_quantity(*, tenant, sku, barcode, quantity, whole=False):
    quantity = Decimal(str(quantity))
    mapping = (
        BarcodeMaster.all_objects.filter(tenant=tenant, barcode=barcode, is_active=True).first() if barcode else None
    )
    if mapping and mapping.sku_id != sku.pk:
        raise ValidationError("The barcode belongs to a different SKU.")
    if (
        barcode
        and not mapping
        and BarcodeMaster.all_objects.filter(tenant=tenant, barcode=barcode, is_active=False).exists()
    ):
        raise ValidationError("This barcode mapping has been deactivated.")
    conversion = mapping.pack_conversion if mapping else Decimal(1)
    normalized = quantity * conversion
    if (
        any(not value.is_finite() or value <= 0 for value in (quantity, conversion, normalized))
        or normalized >= Decimal("100000000000")
        or normalized.normalize().as_tuple().exponent < -4
    ):
        raise ValidationError("Barcode quantity/conversion must be positive, finite and fit the stock unit precision.")
    if whole and (normalized != normalized.to_integral_value() or normalized > 2147483647):
        raise ValidationError("Receiving requires a whole number of confirmed base units; correct the pack conversion.")
    normalized = normalized.quantize(Decimal("0.0001"))
    return normalized, {
        "barcode": barcode,
        "scanned_quantity": str(quantity),
        "pack_conversion": str(conversion),
        "base_quantity": str(normalized),
        "base_unit": sku.package_definition.unit_of_measure,
    }
