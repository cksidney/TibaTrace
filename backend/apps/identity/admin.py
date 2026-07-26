from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.identity.models import (
    AttributePolicy,
    ExternalIdentityMapping,
    Role,
    ServiceAccount,
    User,
    UserRole,
)


@admin.register(User)
class TibaTraceUserAdmin(UserAdmin):
    list_display = (
        "username",
        "email",
        "tenant",
        "is_platform_admin",
        "is_staff",
        "is_active",
    )
    list_filter = (
        "is_platform_admin",
        "is_staff",
        "is_active",
        "tenant",
    )
    fieldsets = UserAdmin.fieldsets + (
        (
            "TibaTrace access",
            {
                "fields": (
                    "tenant",
                    "is_platform_admin",
                    "professional_staff_id",
                    "must_change_password",
                    "metadata",
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "TibaTrace access",
            {
                "fields": (
                    "email",
                    "tenant",
                    "is_platform_admin",
                    "is_staff",
                    "is_active",
                )
            },
        ),
    )


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "tenant", "is_active", "is_system")
    list_filter = ("is_active", "is_system", "tenant")
    search_fields = ("code", "name")


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "tenant", "is_active")
    list_filter = ("is_active", "tenant")
    search_fields = ("user__username", "role__code", "role__name")


@admin.register(AttributePolicy)
class AttributePolicyAdmin(admin.ModelAdmin):
    list_display = ("code", "capability", "effect", "tenant", "is_active")
    list_filter = ("effect", "is_active", "tenant")
    search_fields = ("code", "capability")


@admin.register(ExternalIdentityMapping)
class ExternalIdentityMappingAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "issuer", "tenant")
    list_filter = ("provider", "tenant")
    search_fields = ("user__username", "issuer", "subject")


@admin.register(ServiceAccount)
class ServiceAccountAdmin(admin.ModelAdmin):
    list_display = ("code", "display_name", "tenant", "is_active")
    list_filter = ("is_active", "tenant")
    search_fields = ("code", "display_name")
