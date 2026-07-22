from __future__ import annotations

from contextvars import ContextVar, Token

_current_tenant_id: ContextVar[str | None] = ContextVar("dawatrace_tenant_id", default=None)


def set_current_tenant_id(tenant_id: str | None) -> Token:
    return _current_tenant_id.set(str(tenant_id) if tenant_id else None)


def reset_current_tenant_id(token: Token) -> None:
    _current_tenant_id.reset(token)


def get_current_tenant_id() -> str | None:
    return _current_tenant_id.get()


def require_current_tenant_id() -> str:
    tenant_id = get_current_tenant_id()
    if not tenant_id:
        raise ValueError("An explicit tenant context is required.")
    return tenant_id
