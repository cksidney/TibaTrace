from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from django.db import transaction

from apps.medicines.models import Medicine, MedicineIdentifier

SOURCE_NAME = "Kenya eTCD Product Catalogue"
ETCD_PRODUCT_IDENTIFIER_SYSTEM = "urn:ke:etcd:product-id"
PPB_REGISTRATION_IDENTIFIER_SYSTEM = "urn:ke:ppb:registration-number"
KEML_STATUSES = {"Yes", "No"}
LEVELS_OF_USE = {"1", "2", "3", "4", "5", "6", "9"}


class GovernmentCatalogueError(ValueError):
    pass


@dataclass(frozen=True)
class GovernmentCatalogueRecord:
    source_row: int
    product: dict[str, Any]

    @property
    def etcd_product_id(self) -> str:
        return _text(self.product.get("etcd_product_id"))

    @property
    def ppb_registration_code(self) -> str:
        return _text(self.product.get("ppb_registration_code"))


@dataclass(frozen=True)
class GovernmentCataloguePlan:
    source_checksum: str
    source_version: str
    total_rows: int
    records: tuple[GovernmentCatalogueRecord, ...]
    quarantined: tuple[dict[str, Any], ...]
    duplicate_ppb_registration_codes: frozenset[str]

    def report(self) -> dict[str, Any]:
        quarantine_counts = Counter(entry["reason"] for entry in self.quarantined)
        return {
            "source": SOURCE_NAME,
            "source_checksum": self.source_checksum,
            "source_version": self.source_version,
            "total_rows": self.total_rows,
            "accepted_rows": len(self.records),
            "quarantined_rows": len(self.quarantined),
            "quarantine_counts": dict(sorted(quarantine_counts.items())),
            "duplicate_ppb_registration_code_count": len(self.duplicate_ppb_registration_codes),
            "quarantined": list(self.quarantined),
        }


@dataclass(frozen=True)
class GovernmentCatalogueImportResult:
    created: int
    updated: int
    etcd_identifiers_created: int
    ppb_identifiers_created: int
    ppb_identifiers_omitted: int

    def report(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "etcd_identifiers_created": self.etcd_identifiers_created,
            "ppb_identifiers_created": self.ppb_identifiers_created,
            "ppb_identifiers_omitted": self.ppb_identifiers_omitted,
        }


def load_government_catalogue(catalogue_path: Path) -> GovernmentCataloguePlan:
    try:
        raw_catalogue = catalogue_path.read_bytes()
    except OSError as exc:
        raise GovernmentCatalogueError(f"Unable to read catalogue: {catalogue_path}") from exc

    try:
        payload = json.loads(raw_catalogue)
    except json.JSONDecodeError as exc:
        raise GovernmentCatalogueError("Catalogue is not valid JSON.") from exc

    if not isinstance(payload, dict) or payload.get("IsSuccess") is not True:
        raise GovernmentCatalogueError("Catalogue payload must declare IsSuccess=true.")

    data = payload.get("Data")
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list):
        raise GovernmentCatalogueError("Catalogue payload must contain Data.products as an array.")

    source_checksum = hashlib.sha256(raw_catalogue).hexdigest()
    return build_government_catalogue_plan(products, source_checksum)


def build_government_catalogue_plan(
    products: list[object], source_checksum: str
) -> GovernmentCataloguePlan:
    records_by_product_id: dict[str, list[GovernmentCatalogueRecord]] = defaultdict(list)
    quarantined: list[dict[str, Any]] = []
    source_dates: list[str] = []

    for source_row, product in enumerate(products, start=1):
        if not isinstance(product, dict):
            quarantined.append({"source_row": source_row, "reason": "invalid_record"})
            continue

        record = GovernmentCatalogueRecord(source_row=source_row, product=product)
        validation_reason = _validation_reason(record)
        if validation_reason:
            quarantined.append(_quarantine_entry(record, validation_reason))
            continue

        records_by_product_id[record.etcd_product_id].append(record)
        source_dates.append(_text(product.get("updation_date")))

    accepted: list[GovernmentCatalogueRecord] = []
    for records in records_by_product_id.values():
        payload_signatures = {_payload_signature(record.product) for record in records}
        if len(payload_signatures) > 1:
            quarantined.extend(_quarantine_entry(record, "conflicting_etcd_product_id") for record in records)
            continue
        accepted.append(records[0])

    ppb_counts = Counter(record.ppb_registration_code for record in accepted if record.ppb_registration_code)
    source_date = max(source_dates, default="unknown")[:10]
    source_version = f"sha256:{source_checksum[:16]};updated:{source_date}"
    return GovernmentCataloguePlan(
        source_checksum=source_checksum,
        source_version=source_version,
        total_rows=len(products),
        records=tuple(accepted),
        quarantined=tuple(quarantined),
        duplicate_ppb_registration_codes=frozenset(
            registration_code for registration_code, count in ppb_counts.items() if count > 1
        ),
    )


def import_government_catalogue(plan: GovernmentCataloguePlan) -> GovernmentCatalogueImportResult:
    existing_medicines = {
        medicine.code: medicine
        for medicine in Medicine.all_objects.filter(
            tenant__isnull=True,
            is_global=True,
            code__in=[record.etcd_product_id for record in plan.records],
        )
    }
    conflicting_codes = sorted(
        code for code, medicine in existing_medicines.items() if medicine.source != SOURCE_NAME
    )
    if conflicting_codes:
        raise GovernmentCatalogueError(
            "Global medicine codes already belong to another source: " + ", ".join(conflicting_codes[:10])
        )

    created = updated = etcd_identifiers_created = ppb_identifiers_created = ppb_identifiers_omitted = 0
    with transaction.atomic():
        for record in plan.records:
            medicine = existing_medicines.get(record.etcd_product_id)
            if medicine is None:
                medicine = Medicine(
                    tenant=None,
                    is_global=True,
                    code=record.etcd_product_id,
                    status=Medicine.STATUS_INACTIVE,
                )
                created += 1
            else:
                updated += 1

            _apply_catalogue_values(medicine, record, plan)
            medicine.save()
            existing_medicines[medicine.code] = medicine

            if _ensure_identifier(medicine, ETCD_PRODUCT_IDENTIFIER_SYSTEM, record.etcd_product_id):
                etcd_identifiers_created += 1

            if record.ppb_registration_code in plan.duplicate_ppb_registration_codes:
                ppb_identifiers_omitted += 1
            elif record.ppb_registration_code and _ensure_identifier(
                medicine,
                PPB_REGISTRATION_IDENTIFIER_SYSTEM,
                record.ppb_registration_code,
            ):
                ppb_identifiers_created += 1

    return GovernmentCatalogueImportResult(
        created=created,
        updated=updated,
        etcd_identifiers_created=etcd_identifiers_created,
        ppb_identifiers_created=ppb_identifiers_created,
        ppb_identifiers_omitted=ppb_identifiers_omitted,
    )


def _apply_catalogue_values(
    medicine: Medicine, record: GovernmentCatalogueRecord, plan: GovernmentCataloguePlan
) -> None:
    product = record.product
    medicine.generic_name = _text(product.get("generic_name"))
    medicine.brand_name = _text(product.get("brand_name"))
    medicine.dosage_form = _text(product.get("form_description"))
    medicine.strength = " ".join(
        value for value in (_text(product.get("strength_amount")), _text(product.get("strength_unit"))) if value
    )
    medicine.licence_identifier = record.ppb_registration_code
    medicine.source = SOURCE_NAME
    medicine.source_version = plan.source_version
    medicine.metadata = {
        "catalogue_standard": "KE-ETCD",
        "source_checksum": plan.source_checksum,
        "source_updated_at": _text(product.get("updation_date")),
        "etcd_product_id": record.etcd_product_id,
        "generic_concept": {
            "id": product.get("generic_concept_id"),
            "code": _text(product.get("generic_concept_code")),
            "display_name": _text(product.get("generic_display_name")),
        },
        "active_component": {
            "id": product.get("active_component_id"),
            "code": _text(product.get("active_component_code")),
        },
        "route": {
            "id": product.get("route_id"),
            "code": _text(product.get("route_code")),
            "display_name": _text(product.get("route_description")),
        },
        "dose_form": {
            "id": product.get("form_id"),
            "code": _text(product.get("form_code")),
            "display_name": _text(product.get("form_description")),
        },
        "keml": {
            "status": _text(product.get("keml_status")) or "UNKNOWN",
            "level_of_use": _text(product.get("level_of_use")),
        },
        "manufacturer_name": _text(product.get("manufacture_name")),
        "source_record": product,
    }


def _ensure_identifier(medicine: Medicine, system: str, value: str) -> bool:
    identifier = MedicineIdentifier.objects.filter(system=system, value=value).first()
    if identifier is not None:
        if identifier.medicine_id != medicine.id:
            raise GovernmentCatalogueError(f"Identifier collision for {system}:{value}.")
        return False
    MedicineIdentifier.objects.create(medicine=medicine, system=system, value=value)
    return True


def _validation_reason(record: GovernmentCatalogueRecord) -> str:
    if not record.etcd_product_id:
        return "missing_etcd_product_id"
    if len(record.etcd_product_id) > 120:
        return "etcd_product_id_too_long"

    keml_status = _text(record.product.get("keml_status"))
    if keml_status and keml_status not in KEML_STATUSES:
        return "invalid_keml_status"

    level_of_use = _text(record.product.get("level_of_use"))
    if level_of_use not in LEVELS_OF_USE:
        return "invalid_level_of_use"

    update_date = _text(record.product.get("updation_date"))
    try:
        datetime.fromisoformat(update_date.replace("Z", "+00:00"))
    except ValueError:
        return "invalid_updation_date"
    return ""


def _quarantine_entry(record: GovernmentCatalogueRecord, reason: str) -> dict[str, Any]:
    return {
        "source_row": record.source_row,
        "reason": reason,
        "etcd_product_id": record.etcd_product_id,
        "ppb_registration_code": record.ppb_registration_code,
        "brand_display_name": _text(record.product.get("brand_display_name")),
    }


def _payload_signature(product: dict[str, Any]) -> str:
    return json.dumps(product, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""
