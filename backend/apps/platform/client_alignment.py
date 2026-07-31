"""Refuse mutating POS work when HQ has forced a client upgrade."""
from __future__ import annotations

from rest_framework.exceptions import APIException

from apps.platform.client_version import reject_if_client_blocked

SAFE = frozenset({"GET", "HEAD", "OPTIONS"})


class PosClientUpdateRequired(APIException):
    status_code = 426
    default_detail = "POS client update required."
    default_code = "pos_client_update_required"


class RequireAlignedPosClientMixin:
    """Apply to POS viewsets that mutate stock, cash or clinical state."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method in SAFE:
            return
        blocked = reject_if_client_blocked(request)
        if blocked:
            raise PosClientUpdateRequired(detail=blocked)
