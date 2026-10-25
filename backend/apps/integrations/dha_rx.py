"""DHA SHR prescription intake through the existing reviewed POS intake service."""
import re
import uuid
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ValidationError

from apps.integrations.dha_client import DhaClient
from apps.integrations.dha_models import DhaConnection, DhaVisit
from apps.integrations.dha_workflows import audit, operational, prepare


class DhaPrescriptionFeed:
    def __init__(self, connection, actor):
        self.connection, self.actor = connection, actor

    def fetch_prescription(self, reference):
        try:
            visit_id, rx_id = reference.split(":", 1)
            if not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", rx_id):
                raise ValueError
            visit = DhaVisit.all_objects.get(connection=self.connection, tenant_id=self.connection.tenant_id, pk=uuid.UUID(visit_id))
        except (ValueError, DhaVisit.DoesNotExist):
            raise ValidationError("Use the local DHA visit ID and prescription ID separated by a colon.") from None
        op, path, data, context = prepare(self.connection, self.actor, "patient_records",
            {"resources": "MedicationRequest", "_id": rx_id}, visit)
        body, _ = DhaClient(self.connection).call(op, path, data, consent_token=context["consent_token"], practitioner_id=context["practitioner_id"])
        resources = [row.get("resource", {}) for row in body.get("entry", [])]
        matches = [r for r in resources if r.get("resourceType") == "MedicationRequest" and r.get("id") == rx_id]
        if len(matches) != 1:
            raise ValidationError("The prescription was not uniquely resolved in this consented visit.")
        rx = matches[0]
        subject = rx.get("subject", {}).get("reference", "").rstrip("/").rsplit("/", 1)[-1]
        if subject != context["cr_id"] or rx.get("status") != "active" or rx.get("intent") != "order":
            raise ValidationError("This is not an active order for the consented patient.")
        medication = rx.get("medicationCodeableConcept", {})
        if not medication and rx.get("medicationReference"):
            medication_id = rx["medicationReference"].get("reference", "").rstrip("/").rsplit("/", 1)[-1]
            med_op, med_path, med_data, _ = prepare(self.connection, self.actor, "patient_records",
                {"resources": "Medication", "_id": medication_id}, visit)
            meds, _ = DhaClient(self.connection).call(med_op, med_path, med_data,
                consent_token=context["consent_token"], practitioner_id=context["practitioner_id"])
            matches = [e.get("resource", {}) for e in meds.get("entry", []) if e.get("resource", {}).get("resourceType") == "Medication" and e.get("resource", {}).get("id") == medication_id]
            if len(matches) != 1:
                raise ValidationError("Resolve the prescribed national medication before intake.")
            medication = matches[0].get("code", {})
        product = None
        for coding in medication.get("coding", []):
            # Qualify by system AND code. Identical strings from different dictionaries must not collide.
            key = f"{coding.get('system', '')}|{coding.get('code', '')}"
            if key in self.connection.configuration.get("product_map", {}):
                product = key
                break
        if not product:
            raise ValidationError("Map the national medication coding to a governed tenant SKU before intake.")
        requester = rx.get("requester", {}).get("reference", "").rstrip("/").rsplit("/", 1)[-1]
        if requester not in self.connection.configuration.get("prescriber_map", {}):
            raise ValidationError("Map and review this national prescriber before intake.")
        request = rx.get("dispenseRequest", {})
        quantity = request.get("quantity", {})
        # Import of partial/refill prescriptions needs an authoritative outstanding balance.
        if request.get("numberOfRepeatsAllowed", 0) or rx.get("priorPrescription"):
            raise ValidationError("Refill orders require authoritative remaining-fill reconciliation before intake.")
        directions = "; ".join(row.get("text", "") for row in rx.get("dosageInstruction", []) if row.get("text"))
        if not directions or not quantity.get("value") or not quantity.get("unit") or not rx.get("authoredOn"):
            raise ValidationError("The prescription needs quantity, unit, directions and authored date.")
        # Deduct national completed fills before receiving a partially supplied order.
        # Incomplete history cannot establish a safe remaining quantity.
        supplied, seen, pages = Decimal("0"), set(), set()
        page = None
        for _ in range(100):
            params = {"resources": "MedicationDispense"}
            if page:
                params["page_token"] = page
            history_op, history_path, history_data, _ = prepare(self.connection, self.actor, "patient_records", params, visit)
            history, _ = DhaClient(self.connection).call(history_op, history_path, history_data,
                consent_token=context["consent_token"], practitioner_id=context["practitioner_id"])
            if history.get("resourceType") != "Bundle":
                raise ValidationError("DHA dispensing history could not be reconciled.")
            for entry in history.get("entry", []):
                fill = entry.get("resource", {})
                if fill.get("resourceType") != "MedicationDispense" or fill.get("status") != "completed":
                    continue
                orders = [r.get("reference", "").rstrip("/").rsplit("/", 1)[-1] for r in fill.get("authorizingPrescription", [])]
                if rx_id not in orders or fill.get("id") in seen:
                    continue
                if not fill.get("id") or fill.get("quantity", {}).get("unit") != quantity["unit"]:
                    raise ValidationError("Review historical dispensing identifiers and units before intake.")
                try:
                    amount = Decimal(str(fill.get("quantity", {}).get("value")))
                    if not amount.is_finite() or amount < 0:
                        raise ValueError
                except (InvalidOperation, ValueError):
                    raise ValidationError("The national dispensing balance is invalid.") from None
                supplied += amount
                seen.add(fill["id"])
            links = [r.get("url", "") for r in history.get("link", []) if r.get("relation") == "next"]
            if not links:
                break
            next_page = parse_qs(urlsplit(links[0]).query).get("page_token", [])
            if len(next_page) != 1 or next_page[0] in pages:
                raise ValidationError("Complete dispensing-history pagination is required before intake.")
            page = next_page[0]
            pages.add(page)
        else:
            raise ValidationError("The dispensing history requires supervised reconciliation.")
        try:
            remaining = Decimal(str(quantity["value"])) - supplied
            if not remaining.is_finite() or remaining <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValidationError("This prescription has no confirmed outstanding quantity.") from None
        from apps.medicines.models import CommercialSKU
        sku_id = self.connection.configuration["product_map"][product]
        sku = CommercialSKU.all_objects.filter(pk=sku_id, tenant_id=self.connection.tenant_id, status="ACTIVE").select_related("package_definition").first()
        local_unit = sku.package_definition.unit_of_measure if sku else ""
        mapped_unit = self.connection.configuration.get("unit_map", {}).get(local_unit, {})
        coded_match = bool(quantity.get("system") and quantity.get("code") and quantity["system"] == mapped_unit.get("system") and quantity["code"] == mapped_unit.get("code"))
        if not sku or (local_unit != quantity["unit"] and not coded_match):
            raise ValidationError("Review the source prescription unit against the tenant SKU before intake.")
        self.patient_map = {context["cr_id"]: str(visit.patient_id)}
        self.source_reference = rx_id
        audit(self.connection, self.actor, "PRESCRIPTION_FETCHED", visit.pk)
        return {"reference": reference, "patient_reference": context["cr_id"], "prescriber_reference": requester,
            "prescription_date": rx["authoredOn"][:10], "prescription_type": "ACUTE",
            "items": [{"product_reference": product, "quantity": str(remaining), "directions": directions}]}


def canonical_source_reference(tenant, branch, provider, reference):
    if provider != "DHA" or not DhaConnection.all_objects.filter(tenant=tenant, branch=branch).exists():
        return reference
    try:
        visit_id, rx_id = reference.split(":", 1)
        uuid.UUID(visit_id)
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", rx_id):
            raise ValueError
        return rx_id
    except ValueError:
        raise ValidationError("Use local-visit-uuid:MedicationRequest-id for DHA intake.") from None


def tenant_feed(tenant, branch, actor):
    if not branch or not actor:
        raise ValidationError("DHA intake requires the active branch and operator.")
    connections = list(DhaConnection.all_objects.filter(tenant=tenant, branch=branch,
        environment="PRODUCTION", state="ACTIVE").select_related("tenant", "branch"))
    if len(connections) != 1:
        raise ValidationError("Activate one DHA production connection for this branch first.")
    connection = connections[0]
    operational(connection)
    from apps.integrations.dha_workflows import authorize
    authorize(connection, actor, "dha.exchange")
    if not connection.configuration.get("prescriber_map") or not connection.configuration.get("product_map"):
        raise ValidationError("Complete the DHA prescriber and product mappings first.")
    adapter = DhaPrescriptionFeed(connection, actor)
    # patient_map is populated after the consent-bound fetch, never accepted from a source claim.
    config = {"patient_map": {}, "prescriber_map": connection.configuration["prescriber_map"], "product_map": connection.configuration["product_map"]}
    return adapter, config
