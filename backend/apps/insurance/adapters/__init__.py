"""Insurer adapters.

Concrete adapters are imported here so registration does not depend on import
order. Registration previously happened as a side effect of importing the module
that defines the adapter, which meant ADAPTERS was populated for code that
happened to import `fake` and empty for code that imported only `base` -- so
whether an insurer could be routed depended on what else the caller had touched.
"""
from .base import (  # noqa: F401
    ADAPTERS,
    AdapterLineOutcome,
    AdapterResult,
    BusinessState,
    InsurerAdapter,
    TransportState,
    get_adapter,
    register_adapter,
)
from .fake import FakeInsurerAdapter, Scenario  # noqa: F401
