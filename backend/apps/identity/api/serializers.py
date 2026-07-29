from rest_framework import serializers

from apps.identity.models import Role, ServiceAccount, User, UserRole


class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "first_name", "last_name", "tenant_id", "is_platform_admin")


class RoleSerializer(serializers.ModelSerializer):
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ("id", "code", "name", "capabilities", "is_active", "is_system", "user_count")

    def get_user_count(self, role) -> int:
        return UserRole.all_objects.filter(
            tenant_id=role.tenant_id,
            role=role,
            is_active=True,
        ).count()


class UserRoleSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source="user.username", read_only=True)
    role_code = serializers.CharField(source="role.code", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)

    class Meta:
        model = UserRole
        fields = ("id", "user", "user_username", "role", "role_code", "role_name", "is_active", "created_at")


class UserDetailSerializer(serializers.ModelSerializer):
    assigned_roles = serializers.SerializerMethodField()
    effective_capabilities = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "is_platform_admin",
            "is_superuser",
            "professional_staff_id",
            "assigned_roles",
            "effective_capabilities",
            "date_joined",
        )

    def get_assigned_roles(self, user) -> list[dict]:
        assignments = UserRole.all_objects.filter(
            tenant_id=user.tenant_id,
            user=user,
            is_active=True,
        ).select_related("role")
        return [
            {"id": str(a.role.id), "code": a.role.code, "name": a.role.name}
            for a in assignments
        ]

    def get_effective_capabilities(self, user) -> list[str]:
        tenant_id = user.tenant_id or getattr(self.context.get("request"), "tenant_id", None)
        return sorted(list(user.effective_capabilities(tenant_id=tenant_id)))


class ServiceAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceAccount
        fields = (
            "id",
            "code",
            "display_name",
            "capabilities",
            "is_active",
            "credential_fingerprint",
            "created_at",
        )
