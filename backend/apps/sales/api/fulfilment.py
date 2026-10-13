"""Missing operator commands on top of the authoritative fulfilment services.

The command journal uses the locked order/package as its serialization anchor.
It binds retry keys to their payload; a retry never creates a second wave,
package, packed line or dispatch after a network timeout.
"""
import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from rest_framework.exceptions import ValidationError as APIValidationError
from rest_framework.response import Response

from apps.workflows.models import DomainEvent
from apps.workflows.service import emit_event


@transaction.atomic
def command(request, anchor, name, callback):
    anchor = type(anchor).all_objects.select_for_update().get(pk=anchor.pk, tenant_id=anchor.tenant_id)
    key = str(request.data.get("idempotency_key", "")).strip()
    if not key or len(key) > 120:
        raise APIValidationError({"idempotency_key": "A retry-safe command key is required (maximum 120 characters)."})
    def validate_quantities(value):
        if isinstance(value, dict):
            for field, child in value.items():
                if field == "quantity" or field.endswith("_quantity"):
                    try:
                        number = Decimal(str(child))
                        if not number.is_finite() or number < 0 or number > Decimal("999999999999.9999"):
                            raise ValueError()
                    except (InvalidOperation, ValueError, TypeError):
                        raise APIValidationError({field: "Enter a finite non-negative quantity within supported precision."})
                else:
                    validate_quantities(child)
        elif isinstance(value, list):
            for child in value:
                validate_quantities(child)
    validate_quantities(dict(request.data))
    digest = hashlib.sha256(json.dumps(dict(request.data), sort_keys=True, default=str).encode()).hexdigest()
    previous = DomainEvent.all_objects.filter(tenant_id=anchor.tenant_id, aggregate_type="HQ_FULFILMENT_COMMAND",
        aggregate_id=str(anchor.pk), event_type=name, payload__idempotency_key=key).first()
    if previous:
        if previous.payload["request_hash"] != digest:
            raise APIValidationError("This retry key belongs to different command details.")
        return Response(previous.payload["response"])
    try:
        response = callback(anchor)
    except ValidationError as exc:
        raise APIValidationError(getattr(exc, "message_dict", None) or exc.messages) from exc
    except (ObjectDoesNotExist, InvalidOperation, ValueError, TypeError) as exc:
        raise APIValidationError("Invalid fulfilment details. Confirm the selected records and quantities.") from exc
    emit_event(tenant_id=anchor.tenant_id, aggregate_type="HQ_FULFILMENT_COMMAND", aggregate_id=str(anchor.pk), event_type=name,
        payload={"actor_id":str(request.user.pk), "idempotency_key":key, "request_hash":digest, "response":response})
    return Response(response, status=201)
