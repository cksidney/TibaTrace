from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class DawaTraceTokenSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["tenant_id"] = str(user.tenant_id or "")
        token["platform_admin"] = bool(user.is_platform_admin)
        token["product"] = "DawaTrace"
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        if not self.user.is_active:
            self.fail("no_active_account")
        if not self.user.tenant_id and not (self.user.is_platform_admin or self.user.is_superuser):
            self.fail("no_active_account")
        data["tenant_id"] = str(self.user.tenant_id or "")
        data["user_id"] = str(self.user.id)
        return data
