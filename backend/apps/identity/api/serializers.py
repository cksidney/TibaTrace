from rest_framework import serializers

from apps.identity.models import Role, ServiceAccount, User, UserRole
from apps.identity.services import account_status_for, user_category_label


class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "first_name", "last_name", "tenant_id", "is_platform_admin")


class RoleSerializer(serializers.ModelSerializer):
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ("id", "code", "name", "capabilities", "is_active", "is_system", "user_count")
        read_only_fields = ("id", "code", "is_system", "user_count")

    def get_user_count(self, role) -> int:
        return UserRole.all_objects.filter(
            tenant_id=role.tenant_id,
            role=role,
            is_active=True,
        ).count()


class RoleUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, max_length=160)
    capabilities = serializers.ListField(
        child=serializers.CharField(max_length=160, allow_blank=False),
        required=False,
        allow_empty=True,
    )
    is_active = serializers.BooleanField(required=False)


class RoleCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=80)
    name = serializers.CharField(max_length=160)
    capabilities = serializers.ListField(
        child=serializers.CharField(max_length=160, allow_blank=False),
        required=False,
        allow_empty=True,
        default=list,
    )
    is_active = serializers.BooleanField(required=False, default=True)


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
    account_status = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "account_status",
            "category",
            "is_platform_admin",
            "is_superuser",
            "must_change_password",
            "professional_staff_id",
            "assigned_roles",
            "effective_capabilities",
            "date_joined",
            "last_login",
        )

    def get_assigned_roles(self, user) -> list[dict]:
        assignments = UserRole.all_objects.filter(
            tenant_id=user.tenant_id,
            user=user,
            is_active=True,
        ).select_related("role")
        return [{"id": str(a.role.id), "code": a.role.code, "name": a.role.name} for a in assignments]

    def get_effective_capabilities(self, user) -> list[str]:
        tenant_id = user.tenant_id or getattr(self.context.get("request"), "tenant_id", None)
        return sorted(list(user.effective_capabilities(tenant_id=tenant_id)))

    def get_account_status(self, user) -> str:
        return account_status_for(user)

    def get_category(self, user) -> str:
        return user_category_label(user)


class UserCreateSerializer(serializers.Serializer):
    username = serializers.RegexField(
        r"^[\w.@+-]+$",
        max_length=150,
        min_length=3,
        error_messages={"invalid": "Use letters, numbers, and @/./+/-/_ characters only."},
    )
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    password = serializers.CharField(required=False, allow_blank=True, write_only=True, max_length=256)
    professional_staff_id = serializers.CharField(required=False, allow_blank=True, default="", max_length=120)
    role_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
    )
    must_change_password = serializers.BooleanField(required=False, default=True)


class UserRoleAssignmentSerializer(serializers.Serializer):
    role_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
    )


class PasswordResetAdminSerializer(serializers.Serializer):
    password = serializers.CharField(required=False, allow_blank=True, write_only=True, max_length=256)


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
