"""The medicines catalogue API: does it answer, and only for one tenant?

The fault was that the viewsets declared `queryset = Model.objects.all()` as a
class attribute. `objects` is the tenant-strict manager, and a class attribute
is evaluated once at import -- when there is definitively no tenant context, so
the manager returned `.none()`. DRF's `get_queryset` clones that queryset rather
than re-consulting the manager, so it stayed empty for the life of the process:
every medicines endpoint returned nothing, for every caller, however they
authenticated.

To be accurate about what this was and was not: the strict manager fails closed.
The barcode lookup below called it at request time, when middleware has set the
context, so it was correctly scoped -- and when context was missing it returned
nothing rather than everything. This was a data-loss-shaped bug, not a leak.

What the fix changes is where the isolation lives. It is now an explicit
`filter(tenant_id=...)` visible on the line, rather than thread-local state set
by middleware that happens to run earlier. That distinction matters because the
same code is called from places middleware does not touch, and because the
failure mode of the implicit version -- a silently empty result -- is one this
repository has now been bitten by five times.

So these tests assert both halves: rows come back, and only the right ones.
"""
import pytest
from rest_framework.test import APIClient

from apps.identity.models import User
from apps.medicines.models import (
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    ManufacturedMedicinalProduct,
    Manufacturer,
    PackageDefinition,
)
from apps.tenancy.models import Tenant

PASSWORD = "catalogue-password-long-enough"

#: The same barcode in both tenants. Real GTINs are globally unique, but a
#: pharmacy's own internal barcodes are not, and the isolation must not depend on
#: the value happening to differ.
SHARED_BARCODE = "6161100000015"


def build_tenant(slug, sku_code, barcode):
    tenant = Tenant.objects.create(name=slug.title(), slug=slug)
    user = User.objects.create_user(
        username=f"{slug}-user", password=PASSWORD, tenant=tenant
    )
    manufacturer = Manufacturer.all_objects.create(
        tenant=tenant, code=f"MF-{slug[:4].upper()}", legal_name=f"{slug} Pharma"
    )
    dose = DoseForm.objects.get_or_create(code="TAB", defaults={"name": "Tablet"})[0]
    package = PackageDefinition.objects.get_or_create(
        code="PK-30", defaults={"description": "30s", "unit_of_measure": "tablet"}
    )[0]
    clinical = ClinicalMedicinalProduct.all_objects.create(
        tenant=tenant, code=f"CMP-{slug[:4].upper()}",
        canonical_name="Amoxicillin 500mg", dose_form=dose,
    )
    manufactured = ManufacturedMedicinalProduct.all_objects.create(
        tenant=tenant, code=f"MP-{slug[:4].upper()}", brand_name="Amoxil",
        clinical_product=clinical, manufacturer=manufacturer,
    )
    sku = CommercialSKU.all_objects.create(
        tenant=tenant, sku_code=sku_code, display_name="Amoxil 500mg x30",
        manufactured_product=manufactured, package_definition=package,
        default_barcode=barcode,
    )
    return {"tenant": tenant, "user": user, "sku": sku, "manufacturer": manufacturer}


@pytest.fixture
def nairobi(db):
    return build_tenant("nairobi-pharm", "SKU-NRB-001", SHARED_BARCODE)


@pytest.fixture
def mombasa(db):
    return build_tenant("mombasa-pharm", "SKU-MSA-001", SHARED_BARCODE)


@pytest.fixture(autouse=True)
def clear_throttle():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def signed_in_client(world):
    """Sign in for real rather than force_authenticate.

    Tenant context is established by middleware from the session, so a forced
    authentication produces a request with no tenant -- which is the very state
    these tests are about. Using it here would make them pass or fail for a
    reason unrelated to the code under test.
    """
    client = APIClient()
    response = client.post(
        "/api/identity/session/",
        {"username": world["user"].username, "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200, response.content
    return client


def rows(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


# ─── the endpoints answer at all ─────────────────────────────────────────────


class TestTheCatalogueIsReadable:
    """Before the fix every one of these returned zero rows for data that was
    plainly in the database."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/medicines/manufacturers/",
            "/api/medicines/clinical-products/",
            "/api/medicines/manufactured-products/",
            "/api/medicines/skus/",
        ],
    )
    def test_a_collection_returns_the_tenants_rows(self, nairobi, path):
        response = signed_in_client(nairobi).get(path)
        assert response.status_code == 200
        assert len(rows(response)) >= 1, (
            f"{path} is empty for a tenant that has rows. The class-attribute "
            "queryset was frozen empty at import, when no tenant context exists."
        )

    def test_a_detail_route_resolves(self, nairobi):
        response = signed_in_client(nairobi).get(
            f"/api/medicines/skus/{nairobi['sku'].pk}/"
        )
        assert response.status_code == 200
        assert response.json()["sku_code"] == "SKU-NRB-001"


# ─── and answer for one tenant only ──────────────────────────────────────────


class TestTenantIsolation:
    def test_a_collection_excludes_another_tenants_rows(self, nairobi, mombasa):
        response = signed_in_client(nairobi).get("/api/medicines/skus/")
        codes = {row["sku_code"] for row in rows(response)}
        assert "SKU-NRB-001" in codes
        assert "SKU-MSA-001" not in codes

    def test_another_tenants_detail_route_is_not_readable(self, nairobi, mombasa):
        response = signed_in_client(nairobi).get(
            f"/api/medicines/skus/{mombasa['sku'].pk}/"
        )
        assert response.status_code == 404

    def test_an_anonymous_caller_gets_nothing(self, nairobi):
        response = APIClient().get("/api/medicines/skus/")
        assert response.status_code in (401, 403) or len(rows(response)) == 0


# ─── the barcode scan ────────────────────────────────────────────────────────


class TestBarcodeLookupIsScoped:
    """The lookup a till calls on every scan.

    A cross-tenant resolution here does not read as a permissions error to the
    person at the counter -- it reads as the right drug. They would dispense it.
    """

    def test_a_scan_resolves_the_tenants_own_product(self, nairobi):
        response = signed_in_client(nairobi).get(
            f"/api/medicines/skus/lookup/?barcode={SHARED_BARCODE}"
        )
        assert response.status_code == 200, response.content
        assert response.json()["sku_code"] == "SKU-NRB-001"

    def test_a_scan_never_resolves_another_tenants_product(self, nairobi, mombasa):
        """Both tenants carry this barcode. Nairobi must get Nairobi's.

        Without an explicit tenant filter the lookup returns whichever row the
        database happens to order first, so this can only be trusted if the
        filter is there.
        """
        body = signed_in_client(nairobi).get(
            f"/api/medicines/skus/lookup/?barcode={SHARED_BARCODE}"
        ).json()
        assert body["sku_code"] != "SKU-MSA-001"
        assert body["id"] != str(mombasa["sku"].pk)

    def test_a_scan_for_a_barcode_only_another_tenant_has_finds_nothing(
        self, nairobi, mombasa
    ):
        mombasa["sku"].default_barcode = "6161100099999"
        mombasa["sku"].save(update_fields=["default_barcode"])

        response = signed_in_client(nairobi).get(
            "/api/medicines/skus/lookup/?barcode=6161100099999"
        )
        assert response.status_code == 404, (
            "A barcode belonging only to another tenant resolved. This is the "
            "leak the missing tenant filter would have opened."
        )

    def test_a_lookup_by_sku_code_is_scoped_too(self, nairobi, mombasa):
        response = signed_in_client(nairobi).get(
            "/api/medicines/skus/lookup/?sku_code=SKU-MSA-001"
        )
        assert response.status_code == 404

    def test_a_lookup_without_tenant_context_is_refused_not_answered(self, nairobi):
        # Anonymous, so middleware sets no tenant. Returning a product here
        # would be an unauthenticated read of the catalogue.
        response = APIClient().get(
            f"/api/medicines/skus/lookup/?barcode={SHARED_BARCODE}"
        )
        assert response.status_code in (401, 403, 404)
        assert "SKU-NRB-001" not in response.content.decode()
