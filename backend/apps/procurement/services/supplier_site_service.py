"""Supplier sites.

A supplier is a legal entity; a site is a place goods actually come from. Large
distributors ship from several depots, and which one a delivery came from decides
who to call about a short delivery and where a return goes back to.

The table existed with no service, no route and nothing referencing it. This
gives it the two rules that make it usable: codes are unique within a supplier,
and exactly one site is primary.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.procurement.models import Supplier, SupplierSite
from apps.workflows.service import emit_event


class SupplierSiteService:
    """Registers and maintains the places a supplier ships from."""

    @staticmethod
    @transaction.atomic
    def register_site(
        *, tenant, supplier: Supplier, site_code: str, site_name: str,
        address: str = "", is_primary: bool = False, actor=None,
    ) -> SupplierSite:
        """Add a site to a supplier.

        The first site registered becomes primary whatever the caller asked for.
        A supplier with sites but no primary has no default delivery origin, and
        every downstream question -- where did this come from, where does the
        return go -- has no answer.
        """
        code = str(site_code or "").strip().upper()
        name = str(site_name or "").strip()
        if not code:
            raise ValidationError({"site_code": "A site code is required."})
        if not name:
            raise ValidationError({"site_name": "A site name is required."})

        clash = SupplierSite.all_objects.filter(
            tenant=tenant, supplier=supplier, site_code=code
        ).exists()
        if clash:
            # Two sites sharing a code make a delivery note ambiguous about
            # which depot it came from.
            raise ValidationError(
                {"site_code": f"{supplier.supplier_code} already has a site {code}."}
            )

        first = not SupplierSite.all_objects.filter(
            tenant=tenant, supplier=supplier
        ).exists()
        primary = True if first else bool(is_primary)

        if primary and not first:
            SupplierSiteService._demote_existing_primary(tenant, supplier)

        site = SupplierSite.all_objects.create(
            tenant=tenant, supplier=supplier, site_code=code, site_name=name,
            address=str(address or "").strip(), is_primary=primary,
        )
        emit_event(
            tenant_id=str(tenant.pk), aggregate_type="SupplierSite",
            aggregate_id=str(site.pk), event_type="SupplierSiteRegistered",
            payload={
                "supplier_code": supplier.supplier_code,
                "site_code": code,
                "is_primary": primary,
            },
        )
        return site

    @staticmethod
    @transaction.atomic
    def set_primary_site(*, site: SupplierSite, actor=None) -> SupplierSite:
        """Make one site the supplier's default origin.

        Demotes the previous primary in the same transaction. Two primaries is
        the same as none: nothing can answer which depot a delivery defaults to.
        """
        if site.is_primary:
            return site

        SupplierSiteService._demote_existing_primary(site.tenant, site.supplier)
        site.is_primary = True
        site.save(update_fields=["is_primary", "updated_at"])

        emit_event(
            tenant_id=str(site.tenant_id), aggregate_type="SupplierSite",
            aggregate_id=str(site.pk), event_type="SupplierPrimarySiteChanged",
            payload={
                "supplier_code": site.supplier.supplier_code,
                "site_code": site.site_code,
            },
        )
        return site

    @staticmethod
    def _demote_existing_primary(tenant, supplier) -> None:
        SupplierSite.all_objects.filter(
            tenant=tenant, supplier=supplier, is_primary=True
        ).update(is_primary=False)

    @staticmethod
    def primary_site_for(*, tenant, supplier: Supplier) -> SupplierSite | None:
        """The supplier's default origin, or None if no site is registered."""
        return SupplierSite.all_objects.filter(
            tenant=tenant, supplier=supplier, is_primary=True
        ).first()
