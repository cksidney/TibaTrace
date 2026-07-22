from rest_framework import serializers

from apps.identity.models import Role, User


class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "first_name", "last_name", "tenant_id", "is_platform_admin")


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ("id", "code", "name", "capabilities", "is_active", "is_system")
