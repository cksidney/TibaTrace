"""DRF renderer that emits application/fhir+json (DHA wire convention)."""
from __future__ import annotations

from rest_framework.renderers import JSONRenderer

from apps.fhir.kenya_hie import CONTENT_TYPE_FHIR_JSON


class FHIRJSONRenderer(JSONRenderer):
    media_type = CONTENT_TYPE_FHIR_JSON
    format = "fhir+json"
