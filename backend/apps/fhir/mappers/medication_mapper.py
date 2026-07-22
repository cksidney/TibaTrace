from __future__ import annotations

from typing import Any, Dict

from fhir.resources.medication import Medication

from apps.medicines.models import ClinicalMedicinalProduct


class FHIRMedicationMapper:
    @staticmethod
    def clinical_product_to_fhir(product: ClinicalMedicinalProduct) -> Dict[str, Any]:
        ingredients_fhir = []
        for item in product.ingredients.select_related("active_substance").all():
            ingredients_fhir.append({
                "itemCodeableConcept": {
                    "coding": [{
                        "system": "http://dawatrace.esenai.com/fhir/substance",
                        "code": item.active_substance.code,
                        "display": item.active_substance.canonical_name,
                    }],
                    "text": item.active_substance.canonical_name,
                },
                "strength": {
                    "numerator": {
                        "value": float(item.numerator_value),
                        "unit": item.numerator_unit,
                    },
                    "denominator": {
                        "value": float(item.denominator_value),
                        "unit": item.denominator_unit,
                    }
                }
            })

        med_dict = {
            "resourceType": "Medication",
            "id": str(product.pk),
            "code": {
                "coding": [{
                    "system": "http://dawatrace.esenai.com/fhir/clinical-product",
                    "code": product.code,
                    "display": product.canonical_name,
                }],
                "text": product.canonical_name,
            },
            "status": "active" if product.status == "ACTIVE" else "inactive",
            "form": {
                "coding": [{
                    "system": "http://dawatrace.esenai.com/fhir/dose-form",
                    "code": product.dose_form.code,
                    "display": product.dose_form.name,
                }],
                "text": product.dose_form.name,
            },
            "ingredient": ingredients_fhir,
        }

        # Validate with fhir.resources
        return Medication.parse_obj(med_dict).dict()
