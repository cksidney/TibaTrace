"""Canonical payment-state model: migration mapping and transition legality."""
import pytest

pytestmark = pytest.mark.django_db


# Migration modules are not importable by their numeric name, so load it by path.
def _load_migration():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "apps/prescription/migrations/0010_canonical_payment_state.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0010", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mig = _load_migration()


@pytest.mark.parametrize(
    ("gate", "status", "expected"),
    [
        # Settlement recorded only by the POS mirror must not be lost.
        ("NOT_REQUIRED", "PAID", "PAID"),
        ("PENDING", "PAID", "PAID"),
        # The gate was authoritative everywhere else.
        ("PAID", "PENDING", "PAID"),
        ("PENDING", "PENDING", "PENDING"),
        ("WAIVED", "PENDING", "WAIVED"),
        ("FAILED", "PENDING", "FAILED"),
        ("AUTHORIZED", "PENDING", "AUTHORIZED"),
        ("NOT_REQUIRED", "PENDING", "NOT_REQUIRED"),
        # Defensive: empty/None legacy values.
        ("", "", "NOT_REQUIRED"),
        (None, None, "NOT_REQUIRED"),
    ],
)
def test_migration_maps_legacy_pair_to_canonical_state(gate, status, expected):
    assert mig.canonical_state(gate, status) == expected


@pytest.mark.parametrize(
    ("state", "expected_gate", "expected_status"),
    [
        ("PAID", "PAID", "PAID"),
        ("PENDING", "PENDING", "PENDING"),
        ("WAIVED", "WAIVED", "PENDING"),
        # States with no legacy equivalent fall back to a coherent old value.
        ("PARTIALLY_PAID", "PENDING", "PENDING"),
        ("CANCELLED", "FAILED", "PENDING"),
        ("REVERSED", "FAILED", "PENDING"),
        ("REFUNDED", "FAILED", "PENDING"),
    ],
)
def test_migration_reverse_restores_coherent_legacy_values(state, expected_gate, expected_status):
    assert mig.legacy_states(state) == (expected_gate, expected_status)


def test_states_surviving_a_round_trip_are_stable():
    """Any state that existed before the migration must round-trip exactly."""
    for state in ["NOT_REQUIRED", "PENDING", "AUTHORIZED", "PAID", "WAIVED", "FAILED"]:
        gate, status = mig.legacy_states(state)
        assert mig.canonical_state(gate, status) == state, state


def test_supply_gate_and_lifecycle_cannot_drift():
    """The supply gate must be defined by the model, not a hand-copied literal."""
    from apps.prescription.models import DispensingEpisode
    from apps.prescription.services.clinical_dispensing import MedicineSupplyService

    assert (
        MedicineSupplyService.ALLOWED_PAYMENT_STATES
        is DispensingEpisode.PAYMENT_STATES_PERMITTING_SUPPLY
    )


def test_partial_payment_does_not_permit_supply():
    from apps.prescription.models import DispensingEpisode

    assert "PARTIALLY_PAID" not in DispensingEpisode.PAYMENT_STATES_PERMITTING_SUPPLY
    assert "PENDING" not in DispensingEpisode.PAYMENT_STATES_PERMITTING_SUPPLY
    assert "FAILED" not in DispensingEpisode.PAYMENT_STATES_PERMITTING_SUPPLY


def test_episode_cannot_be_created_already_settled():
    from apps.prescription.models import DispensingEpisode

    for settled in ["PAID", "PARTIALLY_PAID", "AUTHORIZED", "REFUNDED"]:
        assert settled not in DispensingEpisode.PAYMENT_STATES_AT_CREATION


def test_every_declared_state_appears_in_the_transition_map():
    from apps.prescription.models import DispensingEpisode

    declared = {code for code, _ in DispensingEpisode.PAYMENT_STATES}
    assert set(DispensingEpisode.PAYMENT_TRANSITIONS) == declared
    # No transition may point at a state that does not exist.
    for source, targets in DispensingEpisode.PAYMENT_TRANSITIONS.items():
        unknown = targets - declared
        assert not unknown, f"{source} -> {unknown}"


def test_terminal_states_have_no_outgoing_transitions():
    from apps.prescription.models import DispensingEpisode

    for terminal in ["CANCELLED", "REFUNDED"]:
        assert DispensingEpisode.PAYMENT_TRANSITIONS[terminal] == set()


def test_only_one_canonical_payment_field_exists():
    """Guards against reintroducing a second authoritative payment state."""
    from apps.prescription.models import DispensingEpisode

    payment_choice_fields = [
        f.name
        for f in DispensingEpisode._meta.get_fields()
        if getattr(f, "attname", None)
        and f.name.startswith("payment_")
        and getattr(f, "choices", None)
        and {c[0] for c in f.choices} & {"PAID", "NOT_REQUIRED"}
    ]
    assert payment_choice_fields == ["payment_state"], payment_choice_fields
