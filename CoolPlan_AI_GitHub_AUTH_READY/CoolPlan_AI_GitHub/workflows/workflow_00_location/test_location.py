"""
Workflow 00 — deployment-ready module test.

This test does not use any real project coordinates.
It verifies the location state/confirmation behavior using test values.
"""

from core.location import LocationEngine


def test_candidate_confirmation():
    engine = LocationEngine()

    engine.set_candidate(
        name="Test Candidate",
        address="Test Address",
        lat=1.0,
        lon=2.0,
        source="Test",
    )

    confirmed = engine.confirm_candidate()
    coords = engine.get_confirmed_coordinates()

    assert confirmed.lat == 1.0
    assert confirmed.lon == 2.0
    assert engine.confirmation_type == "candidate"
    assert coords == {
        "latitude": 1.0,
        "longitude": 2.0,
    }


def test_manual_selection_confirmation():
    engine = LocationEngine()

    engine.set_candidate(
        name="Test Candidate",
        address="Test Address",
        lat=1.0,
        lon=2.0,
        source="Test",
    )

    engine.start_manual_selection()
    engine.select_manual_location(
        address="Test Project Address",
        lat=3.0,
        lon=4.0,
    )

    confirmed = engine.confirm_manual()
    coords = engine.get_confirmed_coordinates()

    assert confirmed.lat == 3.0
    assert confirmed.lon == 4.0
    assert engine.confirmation_type == "manual"
    assert coords == {
        "latitude": 3.0,
        "longitude": 4.0,
    }


def test_select_again_keeps_candidate():
    engine = LocationEngine()

    engine.set_candidate(
        name="Test Candidate",
        address="Test Address",
        lat=1.0,
        lon=2.0,
        source="Test",
    )

    engine.start_manual_selection()
    engine.select_manual_location(
        address="Test Project Address",
        lat=3.0,
        lon=4.0,
    )

    engine.select_again()

    assert engine.candidate_location is not None
    assert engine.manual_selected_location is None
    assert engine.confirmed_location is None
    assert engine.manual_mode is True


if __name__ == "__main__":
    test_candidate_confirmation()
    test_manual_selection_confirmation()
    test_select_again_keeps_candidate()
    print("✓ Workflow 00 deployment-ready module tests passed")
