"""Build exchange resources from an actual governed medicine supply, never a sale draft."""
import uuid

from django.core.exceptions import ValidationError

from apps.prescription.models import MedicineSupply, MedicineSupplyLine


def supply_bundle(connection, visit, context, supply_id, labels):
    supply = MedicineSupply.all_objects.filter(pk=supply_id, tenant_id=connection.tenant_id,
        patient_id=visit.patient_id, episode__branch_id=connection.branch_id,
        status__in=["COMPLETE", "PARTIAL"]).select_related("prescription").first()
    if not supply:
        raise ValidationError("Select an unreversed, governed medicine supply for this patient and branch.")
    if not supply.prescription.prescription_date:
        raise ValidationError("Review and record the original prescription date before national exchange.")
    if not isinstance(labels, list) or not labels or any(not isinstance(r, dict) or not r.get("system") or not r.get("code") for r in labels):
        raise ValidationError("Review the applicable DHA security labels before sharing.")
    mappings = connection.configuration.get("product_map", {})
    units = connection.configuration.get("unit_map", {})
    subject = {"reference": f"Patient/{context['cr_id']}"}
    encounter_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"dha:{connection.pk}:{context['visit_id']}"))
    encounter = {"reference": f"Encounter/{encounter_id}"}
    meta = {"security": labels}
    resources = [{"resourceType": "Encounter", "id": encounter_id, "status": "in-progress", "meta": meta,
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
        "subject": subject, "episodeOfCare": [{"reference": f"EpisodeOfCare/{context['visit_id']}"}]}]
    lines = MedicineSupplyLine.all_objects.filter(tenant_id=connection.tenant_id, supply=supply).select_related("prescription_item")
    included = set()
    for line in lines:
        codes = [key for key, local in mappings.items() if str(local) == str(line.supplied_sku_id)]
        unit = units.get(line.unit)
        if len(codes) != 1 or "|" not in codes[0] or not isinstance(unit, dict) or not unit.get("system") or not unit.get("code"):
            raise ValidationError("Map every supplied SKU and quantity unit to an unambiguous national coding.")
        system, code = codes[0].split("|", 1)
        medication = {"coding": [{"system": system, "code": code}]}
        item = line.prescription_item
        prescriber = [external for external, local in connection.configuration.get("prescriber_map", {}).items()
            if str(local) == str(supply.prescription.practitioner_id)]
        if len(prescriber) != 1:
            raise ValidationError("Map the original prescriber to one authoritative practitioner identity.")
        # Use the original national order ID for imported DHA prescriptions.
        source = supply.prescription.external_prescription_reference or ""
        request_id = source.rsplit(":", 1)[-1] if source.startswith("DHA:") else str(item.pk)
        if request_id not in included and not source.startswith("DHA:"):
            prescribed_codes = [key for key, local in mappings.items() if str(local) == str(item.prescribed_sku_id)]
            if len(prescribed_codes) != 1 or "|" not in prescribed_codes[0]:
                raise ValidationError("Map the prescribed SKU as well as any substituted supplied SKU.")
            psystem, pcode = prescribed_codes[0].split("|", 1)
            resources.append({"resourceType": "MedicationRequest", "id": request_id, "meta": meta,
                "status": "active" if item.quantity_supplied_total < item.quantity else "completed", "intent": "order",
                "subject": subject, "encounter": encounter, "medicationCodeableConcept": {"coding": [{"system": psystem, "code": pcode}]},
                "requester": {"reference": f"Practitioner/{prescriber[0]}"},
                "authoredOn": supply.prescription.prescription_date.isoformat(), "dosageInstruction": [{"text": item.dosage_instruction}]})
        included.add(request_id)
        quantity = {"value": float(line.quantity), "unit": line.unit, "system": unit["system"], "code": unit["code"]}
        resources.append({"resourceType": "MedicationDispense", "id": str(line.pk), "meta": meta, "status": "completed",
            "subject": subject, "context": encounter, "medicationCodeableConcept": medication,
            "authorizingPrescription": [{"reference": f"MedicationRequest/{request_id}"}],
            "performer": [{"actor": {"reference": f"Practitioner/{context['practitioner_id']}"}}],
            "quantity": quantity, "whenHandedOver": supply.supplied_at.isoformat(), "dosageInstruction": [{"text": item.dosage_instruction}]})
    if not included:
        raise ValidationError("The supply contains no medicine lines.")
    return {"resourceType": "Bundle", "type": "collection", "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"dha-supply:{connection.pk}:{supply.pk}")),
        "entry": [{"resource": r} for r in resources]}
