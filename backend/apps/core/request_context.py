from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("dawatrace_request_id", default=None)


def set_current_request_id(request_id: str | None) -> Token:
    return _request_id.set(request_id)


def reset_current_request_id(token: Token) -> None:
    _request_id.reset(token)


def get_current_request_id() -> str | None:
    return _request_id.get()
