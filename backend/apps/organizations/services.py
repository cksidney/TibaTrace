"""Provisioning services for organisations and their sites.

`apps.pharmacy_network` owns tenant onboarding, and creates the *first*
organisation and branch as part of moving a tenant into ONBOARDING. Everything
after that -- a second branch, a distribution warehouse, a site closing -- had
no service, so callers reached for the ORM directly and the rules below were
enforced nowhere.

What the rules are:

* A site belongs to exactly one organisation, and both to the same tenant. The
  model's TenantConsistencyMixin enforces it on save; doing the check here as
  well turns a database-level integrity error into a message that names the
  problem.
* Codes are unique per tenant, so provisioning is idempotent on code. Calling
  twice with the same code returns the same row rather than raising, which is
  what makes a seeder or a retried request safe.
* Closing a site is not deleting it. Stock, shifts and dispensing history point
  at it, so status changes and the row stays.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.organizations.models import (
    Location,
    LocationIdentifier,
    Organization,
    OrganizationIdentifier,
)

#: Site kinds this service understands. `Location.location_type` is a free
#: CharField, so this list is guidance rather than a database constraint --
#: but a typo like "WAREHOSE" silently creating a new kind of site is worth
#: catching, so unknown values must be passed deliberately.
KNOWN_SITE_TYPES = frozenset(
    {
        "PHARMACY",
        "BRANCH",
        "WAREHOUSE",
        "DISTRIBUTION_CENTRE",
        "HEAD_OFFICE",
        "CLINIC",
        "HOSPITAL",
    }
)

STATUS_ACTIVE = "ACTIVE"
STATUS_CLOSED = "CLOSED"
STATUS_SUSPENDED = "SUSPENDED"


class OrganizationProvisioningService:
    """Creates and maintains the legal entities inside a tenant."""

    @staticmethod
    @transaction.atomic
    def provision_organization(
        *,
        tenant,
        code: str,
        name: str,
        organization_type: str = Organization.TYPE_PHARMACY,
        metadata: dict | None = None,
        actor=None,
    ) -> Organization:
        """Create an organisation, or return the existing one for this code.

        Idempotent on (tenant, code), which matches the unique constraint. A
        retried provisioning call must not raise, and must not create a second
        organisation under a slightly different name.
        """
        code = str(code or "").strip()
        name = str(name or "").strip()
        if not code:
            raise ValidationError("An organisation requires a code.")
        if not name:
            raise ValidationError("An organisation requires a name.")

        existing = Organization.all_objects.filter(tenant=tenant, code=code).first()
        if existing is not None:
            return existing

        return Organization.all_objects.create(
            tenant=tenant,
            code=code,
            name=name,
            organization_type=organization_type,
            status=STATUS_ACTIVE,
            metadata=metadata or {},
        )

    @staticmethod
    @transaction.atomic
    def add_identifier(*, organization: Organization, system: str, value: str) -> OrganizationIdentifier:
        """Attach a registry identifier to an organisation.

        Idempotent on (tenant, system, value) to match the unique constraint.
        """
        system = str(system or "").strip()
        value = str(value or "").strip()
        if not system or not value:
            raise ValidationError("An organisation identifier requires a system and a value.")

        existing = OrganizationIdentifier.all_objects.filter(
            tenant=organization.tenant, system=system, value=value
        ).first()
        if existing is not None:
            return existing

        return OrganizationIdentifier.all_objects.create(
            tenant=organization.tenant, organization=organization, system=system, value=value
        )


class SiteProvisioningService:
    """Creates and maintains the physical sites an organisation operates.

    A "site" is a branch, warehouse or head office -- somewhere with an address
    that staff report to. Storage areas *within* a site (vault, cold room,
    quarantine) are `inventory.InventoryLocation`, provisioned separately;
    conflating the two is what makes a quarantine shelf look like a pharmacy.
    """

    @staticmethod
    @transaction.atomic
    def provision_site(
        *,
        tenant,
        organization: Organization,
        code: str,
        name: str,
        site_type: str = "PHARMACY",
        address: dict | None = None,
        metadata: dict | None = None,
        allow_unknown_type: bool = False,
        actor=None,
    ) -> Location:
        """Create a site under an organisation, or return the existing one.

        Idempotent on (tenant, code). Refuses to attach a site to an
        organisation belonging to a different tenant: the model would reject it
        on save, but by then the error names a constraint rather than the
        mistake.
        """
        code = str(code or "").strip()
        name = str(name or "").strip()
        if not code:
            raise ValidationError("A site requires a code.")
        if not name:
            raise ValidationError("A site requires a name.")
        if organization is None:
            raise ValidationError("A site requires an organisation.")
        if organization.tenant_id != tenant.id:
            raise ValidationError(
                "The organisation belongs to a different tenant than the site being "
                "provisioned. A site cannot cross a tenant boundary."
            )
        if site_type not in KNOWN_SITE_TYPES and not allow_unknown_type:
            known = ", ".join(sorted(KNOWN_SITE_TYPES))
            raise ValidationError(
                f"Unrecognised site type {site_type!r}. Known types: {known}. "
                "Pass allow_unknown_type=True to introduce a new one deliberately."
            )

        existing = Location.all_objects.filter(tenant=tenant, code=code).first()
        if existing is not None:
            return existing

        return Location.all_objects.create(
            tenant=tenant,
            organization=organization,
            code=code,
            name=name,
            location_type=site_type,
            status=STATUS_ACTIVE,
            address=address or {},
            metadata=metadata or {},
        )

    @staticmethod
    @transaction.atomic
    def set_contact_details(
        *,
        site: Location,
        phone: str = "",
        email: str = "",
        operating_hours: dict | None = None,
        manager=None,
    ) -> Location:
        """Record how to reach a site and when it is open.

        These live in `metadata` because the model has no columns for them.
        Written through a service so the keys are consistent -- a demo writing
        `phone` and an importer writing `telephone` produce a site whose contact
        details cannot be read by one query.
        """
        metadata = dict(site.metadata or {})
        contact = dict(metadata.get("contact") or {})
        if phone:
            contact["phone"] = str(phone).strip()
        if email:
            contact["email"] = str(email).strip()
        if contact:
            metadata["contact"] = contact
        if operating_hours is not None:
            metadata["operating_hours"] = operating_hours
        if manager is not None:
            if getattr(manager, "tenant_id", None) not in (None, site.tenant_id):
                raise ValidationError("A site manager must belong to the site's tenant.")
            metadata["manager"] = {
                "user_id": str(manager.pk),
                "username": getattr(manager, "username", ""),
            }
        site.metadata = metadata
        site.save(update_fields=["metadata", "updated_at"])
        return site

    @staticmethod
    @transaction.atomic
    def link_supplying_warehouse(*, site: Location, warehouse: Location) -> Location:
        """Record which warehouse replenishes a branch.

        Both must be in the same tenant, and a site cannot supply itself --
        which would make a replenishment loop look valid.
        """
        if warehouse.tenant_id != site.tenant_id:
            raise ValidationError("A branch and its supplying warehouse must share a tenant.")
        if warehouse.pk == site.pk:
            raise ValidationError("A site cannot be its own supplying warehouse.")

        metadata = dict(site.metadata or {})
        metadata["supplying_warehouse"] = {"id": str(warehouse.pk), "code": warehouse.code}
        site.metadata = metadata
        site.save(update_fields=["metadata", "updated_at"])
        return site

    @staticmethod
    @transaction.atomic
    def close_site(*, site: Location, actor, reason: str) -> Location:
        """Close a site without deleting it.

        Stock movements, shifts and dispensing episodes reference the site. The
        row stays so that history remains readable; only the status changes.
        """
        if actor is None:
            raise PermissionDenied("Closing a site requires a named actor.")
        if not str(reason or "").strip():
            raise ValidationError("Closing a site requires a reason.")

        metadata = dict(site.metadata or {})
        metadata["closure"] = {"reason": reason, "closed_by": getattr(actor, "username", "")}
        site.status = STATUS_CLOSED
        site.metadata = metadata
        site.save(update_fields=["status", "metadata", "updated_at"])
        return site

    @staticmethod
    @transaction.atomic
    def add_identifier(*, site: Location, system: str, value: str) -> LocationIdentifier:
        """Attach a registry identifier (premises licence, GLN) to a site."""
        system = str(system or "").strip()
        value = str(value or "").strip()
        if not system or not value:
            raise ValidationError("A site identifier requires a system and a value.")

        existing = LocationIdentifier.all_objects.filter(
            tenant=site.tenant, system=system, value=value
        ).first()
        if existing is not None:
            return existing

        return LocationIdentifier.all_objects.create(
            tenant=site.tenant, location=site, system=system, value=value
        )
