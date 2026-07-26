"""API exception handling.

Two jobs: attach the request id so a support report can be traced, and translate
a domain refusal into a client error rather than a server one.

That second job matters more than it looks. Every service in this codebase
raises django.core.exceptions.ValidationError to refuse -- a supplier that is
suspended, a requisition approved by its own requester, a receipt beyond the
ordered quantity. DRF does not recognise that exception, so without translation
each of those became a 500. A refusal reported as a server fault sends somebody
looking for a bug in the platform when the platform is working exactly as
designed, and it teaches operators that the system is flaky rather than that
their action was not permitted.
"""
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def _messages(exc: DjangoValidationError) -> dict:
    """Flatten a Django ValidationError into something JSON-serialisable.

    Field errors keep their field, so a client can attach a message to the input
    that caused it rather than showing everything at the top of the form.
    """
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return {"detail": list(exc.messages) if hasattr(exc, "messages") else [str(exc)]}


def dawatrace_exception_handler(exc, context):
    request = context.get("request")

    if isinstance(exc, DjangoValidationError):
        # 400, not 500. The caller asked for something the domain refuses, and
        # that is a fact about the request rather than a failure of the server.
        response = Response(_messages(exc), status=status.HTTP_400_BAD_REQUEST)
    elif isinstance(exc, DjangoPermissionDenied):
        # Django's PermissionDenied, which services raise for authority and
        # separation-of-duties refusals. DRF only recognises its own.
        response = Response(
            {"detail": str(exc) or "You do not have permission to perform this action."},
            status=status.HTTP_403_FORBIDDEN,
        )
    else:
        response = exception_handler(exc, context)

    if response is None:
        return response
    if isinstance(response.data, dict):
        response.data.setdefault("request_id", getattr(request, "request_id", None))
    return response
