import pytest

from apps.core.tenant_context import set_current_tenant_id


@pytest.fixture(autouse=True)
def enable_tenant_context(tenant_a):
    set_current_tenant_id(tenant_a.id)
    yield
    set_current_tenant_id(None)
