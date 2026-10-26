from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.identity import mfa


class MfaJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not mfa.token_allowed(user, validated_token):
            raise AuthenticationFailed('Complete MFA sign-in again before using this token.')
        return user


class MfaTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        from apps.identity.models import User
        token = RefreshToken(attrs['refresh'])
        try:
            user = User.objects.filter(pk=token.get('user_id'), tenant_id=token.get('tenant_id') or None,
                                       is_active=True).first()
        except (TypeError, ValueError):
            raise AuthenticationFailed('A valid current sign-in is required.') from None
        if not user or not mfa.token_allowed(user, token):
            raise AuthenticationFailed('Complete MFA sign-in again before refreshing this token.')
        return super().validate(attrs)


class DawaTraceTokenSerializer(TokenObtainPairSerializer):
    otp_code = serializers.CharField(required=False, write_only=True, max_length=80)
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
        if mfa.required(self.user):
            import time

            from django.core.exceptions import ValidationError
            try:
                proof = mfa.verify(self.user, attrs.get('otp_code', ''))
            except ValidationError:
                raise AuthenticationFailed('MFA configuration requires operations review.') from None
            if proof is None:
                raise AuthenticationFailed('An authenticator or unused recovery code is required. Enroll in HQ first.')
            token = RefreshToken(data['refresh'])
            token['mfa_version'] = proof['version']
            token['mfa_verified_at'] = int(time.time())
            data['refresh'], data['access'] = str(token), str(token.access_token)
        data["tenant_id"] = str(self.user.tenant_id or "")
        data["user_id"] = str(self.user.id)
        # The till shows who is dispensing. Without this the POS header rendered
        # `Operator ${userId.slice(0, 8)}` -- a truncated primary key, which
        # names nobody on a screen where the operator's identity is part of the
        # clinical record.
        data["username"] = self.user.get_username()
        data["must_change_password"] = self.user.must_change_password
        return data
