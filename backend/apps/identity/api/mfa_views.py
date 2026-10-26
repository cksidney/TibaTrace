import secrets
import time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.middleware.csrf import get_token
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.identity import mfa


class MfaInput(serializers.Serializer):
    current_password = serializers.CharField(required=False, write_only=True, max_length=256, trim_whitespace=False)
    code = serializers.CharField(required=False, write_only=True, max_length=80, trim_whitespace=True)


class MfaThrottle(UserRateThrottle):
    scope = 'mfa'


class MfaView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [MfaThrottle]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        response['Pragma'] = 'no-cache'
        return response

    def get(self, request, operation):
        return Response({'mfa': mfa.session_status(request)})

    @transaction.atomic
    def post(self, request, operation):
        from django.contrib.auth import get_user_model
        request.user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        payload = MfaInput(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        if operation in ('enroll', 'reset', 'recovery'):
            if not request.user.check_password(data.get('current_password', '')):
                return Response({'detail': 'Current password is incorrect.'}, status=400)
        if operation == 'enroll':
            nonce = secrets.token_urlsafe(32)
            try:
                enrollment = mfa.begin_enrollment(request.user, nonce)
            except ValidationError as exc:
                return Response({'detail': exc.messages[0]}, status=400)
            request.session['mfa_enrollment_nonce'] = nonce
            request.session['mfa_password_at'] = int(time.time())
            import io

            import qrcode
            from qrcode.image.svg import SvgPathImage
            svg = io.BytesIO()
            qrcode.make(enrollment['provisioning_uri'], image_factory=SvgPathImage).save(svg)
            enrollment['qr_svg'] = svg.getvalue().decode()
            return Response(enrollment)
        if operation not in ('confirm', 'verify', 'reset', 'recovery'):
            return Response({'detail': 'Unknown MFA operation.'}, status=404)
        if operation in ('confirm', 'verify') and not (0 <= time.time() - request.session.get('mfa_password_at', 0) <= 600):
            return Response({'detail': 'Sign in again to continue MFA verification.', 'code': 'reauthentication_required'}, status=401)
        nonce = request.session.get('mfa_enrollment_nonce') if operation == 'confirm' else None
        if operation == 'confirm' and not nonce:
            return Response({'detail': 'Start authenticator enrollment in this browser first.'}, status=400)
        try:
            result = mfa.verify(request.user, data.get('code', ''), enrollment_nonce=nonce)
        except ValidationError as exc:
            return Response({'detail': exc.messages[0]}, status=503)
        if result is None:
            return Response({'detail': 'Code is invalid, already used, expired, or temporarily blocked.'}, status=400)
        if operation in ('reset', 'recovery'):
            credential = mfa.MfaCredential.objects.select_for_update().get(user=request.user)
            import uuid
            credential.version = uuid.uuid4()
            if operation == 'reset':
                credential.enabled_at, credential.pending_expires_at = None, None
                credential.protected_secret, credential.pending_nonce_hash = '', ''
                credential.recovery_hashes = []
                result['recovery_codes'] = None
            else:
                result['recovery_codes'] = mfa._recovery_codes(credential)
            credential.save()
            result['version'] = str(credential.version)
            mfa._audit(request.user, 'MFA_RESET' if operation == 'reset' else 'MFA_RECOVERY_REGENERATED')
        request.session.pop('mfa_enrollment_nonce', None)
        if operation == 'reset':
            request.session.pop('mfa_version', None)
            request.session.pop('mfa_verified_at', None)
            request.session.cycle_key()
        else:
            mfa.mark_session(request, result['version'])
        return Response({'mfa': mfa.session_status(request), 'recovery_codes': result['recovery_codes'],
                         'csrf_token': get_token(request)})
