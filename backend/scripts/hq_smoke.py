"""Exercise every HQ workspace surface an operator can reach from the cockpit.

Run with: python manage.py shell < scripts/hq_smoke.py, or
          python scripts/hq_smoke.py  (from backend/)

Reports the status of each endpoint per tenant so a blank or broken panel in the
cockpit can be traced to the request behind it.
"""
from __future__ import annotations

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dawatrace.settings.development")
django.setup()

from django.test import Client  # noqa: E402

from apps.identity.models import User  # noqa: E402
from apps.tenancy.models import Tenant  # noqa: E402

PLATFORM_PATHS = [
    "/api/health/",
    "/api/identity/session/",
    "/api/hq/overview/",
    "/api/hq/workspace/",
    "/api/tenancy/tenants/",
    "/api/hq/pos-releases/",
    "/api/medicines/substances/",
    "/api/medicines/clinical-products/",
    "/api/medicines/manufactured-products/",
    "/api/medicines/manufacturers/",
]

TENANT_PATHS = [
    "/api/hq/overview/",
    "/api/hq/workspace/",
    "/api/identity/roles-detail/",
    "/api/identity/users/?page_size=5",
    "/api/identity/user-roles/",
    "/api/identity/service-accounts/",
    "/api/identity/matrix/",
    "/api/inventory/locations/",
    "/api/inventory/balances/",
    "/api/inventory/ledger/",
    "/api/inventory/batches/",
    "/api/procurement/context/",
    "/api/procurement/suppliers/",
    "/api/procurement/requisitions/",
    "/api/procurement/purchase-orders/",
    "/api/procurement/goods-receipts/",
    "/api/procurement/received-batches/",
    "/api/procurement/inspections/",
    "/api/procurement/matching/",
    "/api/pricing/books/",
    "/api/pricing/assignments/",
    "/api/pricing/applied/",
    "/api/pricing/locks/",
    "/api/insurance/insurers/",
    "/api/insurance/claims/",
    "/api/insurance/remittances/",
    "/api/insurance/coverages/",
    "/api/pos/shift/registers/",
    "/api/pos/shift/sessions/open/",
    "/api/pos/shift/reports/variances/",
    "/api/pos/shift/reports/forced-closures/",
    "/api/pos/shift/cash-movements/",
    "/api/pos/shift/business-days/",
    "/api/pos/dispensing/devices/",
    "/api/pos/client-version/?platform=WINDOWS",
    "/api/customers/",
    "/api/medicines/skus/?page_size=5",
]


def probe(client, path, tenant_id=""):
    headers = {"HTTP_X_TENANT_ID": str(tenant_id)} if tenant_id else {}
    try:
        response = client.get(path, **headers)
    except Exception as exc:  # noqa: BLE001 - smoke script reports, never raises
        return "EXC", f"{type(exc).__name__}: {exc}"
    body = response.content[:120].decode("utf-8", "replace")
    return response.status_code, body


def main():
    admin = (
        User.objects.filter(is_platform_admin=True).first()
        or User.objects.filter(is_superuser=True).first()
    )
    if admin is None:
        print("No platform administrator exists; cannot smoke test HQ.")
        return 1

    client = Client(SERVER_NAME="127.0.0.1")
    client.force_login(admin)

    failures = []
    print(f"== platform scope (as {admin.username}) ==")
    for path in PLATFORM_PATHS:
        status, body = probe(client, path)
        flag = "ok " if status == 200 else "FAIL"
        if status != 200:
            failures.append((("platform"), path, status, body))
        print(f"  [{flag}] {status} {path}")

    for tenant in Tenant.objects.filter(status=Tenant.STATUS_ACTIVE).order_by("slug"):
        print(f"\n== tenant {tenant.slug} ==")
        for path in TENANT_PATHS:
            status, body = probe(client, path, tenant.pk)
            flag = "ok " if status == 200 else "FAIL"
            if status != 200:
                failures.append((tenant.slug, path, status, body))
            print(f"  [{flag}] {status} {path}")

    print("\n== summary ==")
    if failures:
        for scope, path, status, body in failures:
            print(f"  FAIL {scope} {path} -> {status} {body}")
        print(f"{len(failures)} endpoint(s) failed.")
        return 1
    print("All HQ endpoints responded 200.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
