"""Customer metrics for POS shifts and register sessions."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import OperatorShift, RegisterSession


def count_served_customers_for_shift(shift: OperatorShift) -> int:
    """Return the total number of customers served during an operator's shift.

    Counts completed/paid retail transactions and paid/supplied dispensing episodes
    attributed to this operator shift.
    """
    from apps.pos_transactions.models import PosTransaction
    from apps.prescription.models import DispensingEpisode

    retail_count = PosTransaction.all_objects.filter(
        tenant_id=shift.tenant_id, operator_shift_id=shift.pk,
        state__in=[PosTransaction.State.PAID, PosTransaction.State.COMPLETED],
    ).count()

    dispensing_count = DispensingEpisode.all_objects.filter(
        tenant_id=shift.tenant_id, payment_operator_shift_id=shift.pk,
        status__in=[
            "PAID",
            "READY_FOR_COLLECTION",
            "READY_FOR_SUPPLY",
            "PARTIALLY_SUPPLIED",
            "SUPPLIED",
            "CLOSED",
        ],
    ).count()

    return retail_count + dispensing_count


def count_served_customers_for_session(session: RegisterSession) -> int:
    """Return the total number of customers served across a register session."""
    from apps.pos_transactions.models import PosTransaction
    from apps.prescription.models import DispensingEpisode

    retail_count = PosTransaction.all_objects.filter(
        tenant_id=session.tenant_id, register_session_id=session.pk,
        state__in=[PosTransaction.State.PAID, PosTransaction.State.COMPLETED],
    ).count()

    dispensing_count = DispensingEpisode.all_objects.filter(
        tenant_id=session.tenant_id, payment_register_session_id=session.pk,
        status__in=[
            "PAID",
            "READY_FOR_COLLECTION",
            "READY_FOR_SUPPLY",
            "PARTIALLY_SUPPLIED",
            "SUPPLIED",
            "CLOSED",
        ],
    ).count()

    return retail_count + dispensing_count
