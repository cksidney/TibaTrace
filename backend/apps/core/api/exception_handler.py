from rest_framework.views import exception_handler


def dawatrace_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response
    request = context.get("request")
    if isinstance(response.data, dict):
        response.data.setdefault("request_id", getattr(request, "request_id", None))
    return response
