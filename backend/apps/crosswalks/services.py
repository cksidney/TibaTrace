from apps.crosswalks.models import LegacyIdentifierCrosswalk


class CrosswalkService:
    @staticmethod
    def resolve(*, tenant_id, source_system_code, source_entity_type, source_identifier):
        if not tenant_id:
            raise ValueError("Tenant is required for crosswalk resolution.")
        return LegacyIdentifierCrosswalk.all_objects.filter(
            tenant_id=tenant_id,
            source_system__code=source_system_code,
            source_entity_type=source_entity_type,
            source_identifier=source_identifier,
        ).first()
