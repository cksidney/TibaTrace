"""Clinical capability and context-staleness enforcement.

Audit evidence. Before this, the POS clinical write endpoints relied only on
`IsAuthenticated`, `validate_basket_unchanged()` had no production caller, and
the API resolved the acting principal from a client-supplied id -- so a cashier
could nominate a pharmacist and approve their own override.

Do not relax these tests to make a future change easier.
"""
import pytest
from django.core.exceptions import PermissionDenied
from tests.test_pos_clinical_screening import (  # noqa: F401
    active_ingredient,
    active_substance,
    basket_lines,
    branch,
    cashier_user,
    clinical_product,
    commercial_sku,
    drug_drug_rule,
    patient,
    pharmacist_user,
    release,
    tenant,
)

from apps.cds.pos_screening_models import PosClinicalFinding
from apps.cds.pos_screening_services import (
    PosClinicalApprovalService,
    PosClinicalScreeningService,
    PosPharmacistReviewService,
    StaleClinicalContext,
)

pytestmark = pytest.mark.django_db

STALE = "a-hash-that-does-not-match-the-current-basket"


@pytest.fixture
def screening(tenant, basket_lines, cashier_user, drug_drug_rule):  # noqa: F811
    return PosClinicalScreeningService.evaluate(
        tenant=tenant,
        transaction_id="tx-authority",
        device_id="dev-1",
        basket_lines=basket_lines,
        cashier=cashier_user,
    )


def finding_for(screening):
    return PosClinicalFinding.all_objects.filter(screening=screening).first()


# --------------------------------------------------------------- capability


def test_service_refuses_a_call_with_no_actor(screening):
    """Guards the bypass routes: commands, jobs, future integrations.

    Enforcement lives in the service, not only at the API boundary, so an
    alternate entry point cannot become a way around it.
    """
    with pytest.raises(PermissionDenied):
        PosPharmacistReviewService.submit_decision(
            screening=screening,
            finding_id=finding_for(screening).id,
            pharmacist=None,
            decision="APPROVE_AS_WRITTEN",
            idempotency_key="k-none",
            expected_context_hash=screening.context_hash,
        )


def test_cashier_cannot_submit_a_pharmacist_decision(screening, cashier_user):  # noqa: F811
    """A till capability must never imply clinical decision authority."""
    with pytest.raises(PermissionDenied):
        PosPharmacistReviewService.submit_decision(
            screening=screening,
            finding_id=finding_for(screening).id,
            pharmacist=cashier_user,
            decision="APPROVE_AS_WRITTEN",
            idempotency_key="k-cashier",
            expected_context_hash=screening.context_hash,
        )


def test_cashier_cannot_authorise_an_override(screening, cashier_user):  # noqa: F811
    with pytest.raises(PermissionDenied):
        PosPharmacistReviewService.submit_decision(
            screening=screening,
            finding_id=finding_for(screening).id,
            pharmacist=cashier_user,
            decision="AUTHORIZED_OVERRIDE",
            clinical_justification="not permitted",
            idempotency_key="k-cashier-override",
            expected_context_hash=screening.context_hash,
        )


def test_cashier_may_still_escalate_to_a_pharmacist(screening, cashier_user):  # noqa: F811
    """Escalation must stay available to whoever is at the till.

    Gating it higher would leave a cashier stuck at a blocker with no lawful way
    forward, which is how people learn to work around the system.
    """
    audit = PosPharmacistReviewService.request_review(
        screening=screening,
        cashier=cashier_user,
        expected_context_hash=screening.context_hash,
    )
    assert audit.event_type == "PHARMACIST_REVIEW_REQUESTED"


def test_pharmacist_may_decide(screening, pharmacist_user):  # noqa: F811
    decision = PosPharmacistReviewService.submit_decision(
        screening=screening,
        finding_id=finding_for(screening).id,
        pharmacist=pharmacist_user,
        decision="APPROVE_AS_WRITTEN",
        idempotency_key="k-ok",
        expected_context_hash=screening.context_hash,
    )
    assert decision.decision == "APPROVE_AS_WRITTEN"


# --------------------------------------------------------- separation of duties


def test_the_cashier_who_rang_the_basket_cannot_clear_it(tenant, basket_lines, pharmacist_user, drug_drug_rule):  # noqa: F811
    """Whoever rang the sale must not also be the clinical authority on it."""
    screening = PosClinicalScreeningService.evaluate(
        tenant=tenant,
        transaction_id="tx-sod",
        device_id="dev-1",
        basket_lines=basket_lines,
        cashier=pharmacist_user,
    )
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError, match="differ from the cashier"):
        PosPharmacistReviewService.submit_decision(
            screening=screening,
            finding_id=finding_for(screening).id,
            pharmacist=pharmacist_user,
            decision="APPROVE_AS_WRITTEN",
            idempotency_key="k-sod",
            expected_context_hash=screening.context_hash,
        )


# --------------------------------------------------------------- staleness


def test_stale_context_blocks_a_pharmacist_decision(screening, pharmacist_user):  # noqa: F811
    """An approval is only meaningful for the basket it was given against."""
    with pytest.raises(StaleClinicalContext):
        PosPharmacistReviewService.submit_decision(
            screening=screening,
            finding_id=finding_for(screening).id,
            pharmacist=pharmacist_user,
            decision="APPROVE_AS_WRITTEN",
            idempotency_key="k-stale",
            expected_context_hash=STALE,
        )


def test_stale_context_blocks_an_override(screening, pharmacist_user):  # noqa: F811
    with pytest.raises(StaleClinicalContext):
        PosPharmacistReviewService.submit_decision(
            screening=screening,
            finding_id=finding_for(screening).id,
            pharmacist=pharmacist_user,
            decision="AUTHORIZED_OVERRIDE",
            clinical_justification="stale",
            idempotency_key="k-stale-override",
            expected_context_hash=STALE,
        )


def test_stale_context_blocks_acknowledgement(tenant, screening, cashier_user):  # noqa: F811
    with pytest.raises(StaleClinicalContext):
        PosClinicalScreeningService.acknowledge_finding(
            tenant=tenant,
            finding_id=finding_for(screening).id,
            cashier=cashier_user,
            expected_context_hash=STALE,
        )


def test_a_missing_context_hash_is_not_treated_as_current(screening, pharmacist_user):  # noqa: F811
    """Omitting the hash must fail closed, not skip the check."""
    with pytest.raises(StaleClinicalContext):
        PosPharmacistReviewService.submit_decision(
            screening=screening,
            finding_id=finding_for(screening).id,
            pharmacist=pharmacist_user,
            decision="APPROVE_AS_WRITTEN",
            idempotency_key="k-missing",
            expected_context_hash=None,
        )


def test_a_stale_attempt_is_audited(screening, pharmacist_user):  # noqa: F811
    from apps.cds.pos_screening_models import PosClinicalAuditEvent

    with pytest.raises(StaleClinicalContext):
        PosPharmacistReviewService.submit_decision(
            screening=screening,
            finding_id=finding_for(screening).id,
            pharmacist=pharmacist_user,
            decision="APPROVE_AS_WRITTEN",
            idempotency_key="k-audit",
            expected_context_hash=STALE,
        )
    assert PosClinicalAuditEvent.all_objects.filter(
        screening=screening, event_type="CLINICAL_CONTEXT_STALE"
    ).exists()


def test_a_stale_attempt_leaves_the_screening_untouched(screening, pharmacist_user):  # noqa: F811
    before = screening.safe_to_proceed
    with pytest.raises(StaleClinicalContext):
        PosPharmacistReviewService.submit_decision(
            screening=screening,
            finding_id=finding_for(screening).id,
            pharmacist=pharmacist_user,
            decision="APPROVE_AS_WRITTEN",
            idempotency_key="k-untouched",
            expected_context_hash=STALE,
        )
    screening.refresh_from_db()
    assert screening.safe_to_proceed == before


# ------------------------------------------------------------ progression gate


def test_invalidated_screening_can_never_be_safe(screening):
    PosClinicalApprovalService.invalidate(screening=screening, reason="basket changed")
    screening.refresh_from_db()
    assert screening.safe_to_proceed is False


def test_progression_gate_rejects_a_stale_context(screening):
    from django.core.exceptions import ValidationError

    with pytest.raises((StaleClinicalContext, ValidationError)):
        PosClinicalApprovalService.assert_current_and_safe(
            screening=screening, expected_context_hash=STALE
        )


def test_progression_gate_rejects_unresolved_blocking_findings(screening):
    from django.core.exceptions import ValidationError

    # The drug-drug rule leaves a blocking finding open.
    with pytest.raises(ValidationError, match="unresolved blocking findings"):
        PosClinicalApprovalService.assert_current_and_safe(
            screening=screening, expected_context_hash=screening.context_hash
        )
