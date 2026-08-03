"""Provisioning for storage areas inside a branch.

`InventoryLocation` models where stock physically sits -- a dispensary shelf, a
controlled vault, a cold room, a quarantine bay. The taxonomy and the
capability flags already existed; what did not exist was any service to create
one, so the flags were set by whoever happened to write the row.

That matters more than it sounds. `controlled_drug_capability` on the wrong
shelf means controlled stock can be put somewhere it should not be, and
`quarantine_capability` missing from the quarantine bay means quarantined stock
stays available to promise. These are safety flags, not labels, so this service
derives them from the location type rather than trusting the caller.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.inventory.models import InventoryLocation

LocationType = InventoryLocation.LocationType

#: Capabilities implied by each storage type. Derived, not supplied: a caller
#: that could pass these independently could create a "quarantine" bay that
#: does not quarantine.
_IMPLIED_CAPABILITIES: dict[str, dict[str, bool]] = {
    LocationType.COLD_ROOM: {"cold_chain_capability": True},
    LocationType.FREEZER: {"cold_chain_capability": True},
    LocationType.CONTROLLED_VAULT: {"controlled_drug_capability": True, "restricted_flag": True},
    LocationType.QUARANTINE: {"quarantine_capability": True, "restricted_flag": True},
    LocationType.RETURNS: {"returns_capability": True},
    LocationType.DAMAGED: {"damaged_goods_capability": True, "restricted_flag": True},
    LocationType.EXPIRED: {"expiry_hold_capability": True, "restricted_flag": True},
    LocationType.TRANSIT: {"restricted_flag": True},
}

#: Types that hold stock which must not be dispensed or promised.
NON_AVAILABLE_TYPES = frozenset(
    {
        LocationType.QUARANTINE,
        LocationType.DAMAGED,
        LocationType.EXPIRED,
        LocationType.TRANSIT,
    }
)


class InventoryLocationProvisioningService:
    """Creates the storage areas within a branch or warehouse."""

    @staticmethod
    @transaction.atomic
    def provision_location(
        *,
        tenant,
        branch,
        location_code: str,
        name: str,
        location_type: str = LocationType.STORE,
        parent_location: InventoryLocation | None = None,
        extra_capabilities: dict | None = None,
        actor=None,
    ) -> InventoryLocation:
        """Create a storage area, or return the existing one for this code.

        Idempotent on (tenant, branch, location_code), matching the unique
        constraint. Capabilities are derived from `location_type`;
        `extra_capabilities` may add to them but is applied after, so it cannot
        quietly remove a safety flag the type implies.
        """
        location_code = str(location_code or "").strip()
        name = str(name or "").strip()
        if not location_code:
            raise ValidationError("A storage location requires a code.")
        if not name:
            raise ValidationError("A storage location requires a name.")
        if branch is None:
            raise ValidationError("A storage location requires a branch.")
        if branch.tenant_id != tenant.id:
            raise ValidationError(
                "The branch belongs to a different tenant than the storage location."
            )
        if location_type not in LocationType.values:
            known = ", ".join(LocationType.values)
            raise ValidationError(f"Unknown storage type {location_type!r}. Known: {known}")

        if parent_location is not None:
            if parent_location.tenant_id != tenant.id:
                raise ValidationError("A parent storage location must share the tenant.")
            if parent_location.branch_id != branch.id:
                raise ValidationError(
                    "A storage location cannot be nested under a location in another branch."
                )

        existing = InventoryLocation.all_objects.filter(
            tenant=tenant, branch=branch, location_code=location_code
        ).first()
        if existing is not None:
            return existing

        capabilities = dict(_IMPLIED_CAPABILITIES.get(location_type, {}))
        for key, value in (extra_capabilities or {}).items():
            # Additive only. A caller may grant a capability the type does not
            # imply, but may not clear one it does.
            if capabilities.get(key) and not value:
                raise ValidationError(
                    f"{key} is implied by storage type {location_type} and cannot be cleared."
                )
            capabilities[key] = value

        return InventoryLocation.all_objects.create(
            tenant=tenant,
            branch=branch,
            parent_location=parent_location,
            location_code=location_code,
            name=name,
            location_type=location_type,
            status=InventoryLocation.Status.ACTIVE,
            **capabilities,
        )

    @staticmethod
    @transaction.atomic
    def provision_standard_layout(
        *, tenant, branch, prefix: str, include_controlled: bool = False,
        include_cold_chain: bool = False, actor=None,
    ) -> dict[str, InventoryLocation]:
        """Create the storage areas a working site needs.

        Every site that holds stock needs somewhere to receive it, somewhere to
        hold it while it is checked, and somewhere to put it when it fails --
        so those are not optional. Controlled and cold-chain areas are, because
        not every branch is licensed or equipped for them.
        """
        layout = {
            "main": (f"{prefix}-MAIN", "Main store", LocationType.STORE),
            "dispensary": (f"{prefix}-DISP", "Dispensary", LocationType.DISPENSARY),
            "receiving": (f"{prefix}-RECV", "Receiving bay", LocationType.RECEIVING),
            "quarantine": (f"{prefix}-QUAR", "Quarantine", LocationType.QUARANTINE),
            "returns": (f"{prefix}-RET", "Returns", LocationType.RETURNS),
            "damaged": (f"{prefix}-DMG", "Damaged goods", LocationType.DAMAGED),
            "expired": (f"{prefix}-EXP", "Expired stock", LocationType.EXPIRED),
        }
        if include_controlled:
            layout["controlled"] = (f"{prefix}-CTRL", "Controlled vault", LocationType.CONTROLLED_VAULT)
        if include_cold_chain:
            layout["cold_chain"] = (f"{prefix}-COLD", "Cold room", LocationType.COLD_ROOM)

        created: dict[str, InventoryLocation] = {}
        for key, (code, name, kind) in layout.items():
            created[key] = InventoryLocationProvisioningService.provision_location(
                tenant=tenant, branch=branch, location_code=code, name=name,
                location_type=kind, actor=actor,
            )
        return created

    @staticmethod
    @transaction.atomic
    def deactivate_location(*, location: InventoryLocation, actor, reason: str) -> InventoryLocation:
        """Take a storage area out of use without deleting it.

        Ledger entries reference the location, so the row stays.
        """
        if actor is None:
            raise PermissionDenied("Deactivating a storage location requires a named actor.")
        if not str(reason or "").strip():
            raise ValidationError("Deactivating a storage location requires a reason.")

        location.status = InventoryLocation.Status.INACTIVE
        location.save(update_fields=["status", "updated_at"])
        return location
