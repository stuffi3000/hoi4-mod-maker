"""Domain manager unit test - basic operations of addition, deletion and modification."""

import pytest


# ──────────────── ContinentManager ────────────────

def test_continent_manager_defaults():
    from domain.managers.continent import ContinentManager
    m = ContinentManager()
    assert m.count() == 1
    assert m.names == ["default_continent"]


def test_continent_add_rename_remove():
    from domain.managers.continent import ContinentManager
    m = ContinentManager()
    m.add_continent("africa")
    m.add_continent("asia")
    assert m.count() == 3

    m.rename_continent(1, "AfricaNew")
    assert m.get_name(1) == "AfricaNew"

    m.remove_continent(1)
    assert m.count() == 2
    assert "AfricaNew" not in m.names


def test_continent_cannot_delete_last():
    from domain.managers.continent import ContinentManager
    m = ContinentManager()
    with pytest.raises(ValueError):
        m.remove_continent(0)


def test_continent_assign_province_and_hoi4_id():
    from domain.managers.continent import ContinentManager
    m = ContinentManager()
    m.add_continent("asia")  # index 1
    m.assign_province(5, 1)
    # HOI4 id is 1-based
    assert m.get_province_continent_hoi4_id(5, True) == 2
    # Hai Province Forever 0
    assert m.get_province_continent_hoi4_id(5, False) == 0
    # No land assigned Default 1
    assert m.get_province_continent_hoi4_id(999, True) == 1


def test_continent_serialize_roundtrip():
    from domain.managers.continent import ContinentManager
    m = ContinentManager()
    m.add_continent("europe")
    m.assign_province(3, 1)
    m.assign_province(4, 0)
    data = m.to_dict()

    m2 = ContinentManager()
    m2.from_dict(data)
    assert m2.names == m.names
    assert m2.get_province_continent(3) == 1
    assert m2.get_province_continent(4) == 0


# ──────────────── StateManager ────────────────

def test_state_manager_add_state():
    from domain.managers.state import StateManager, StateData
    m = StateManager()
    s = StateData(id=1, name="Test", provinces=[1, 2, 3], manpower=100000)
    m._states[1] = s
    m._province_to_state = {1: 1, 2: 1, 3: 1}
    assert m.get_state(1).name == "Test"
    assert m.get_state_of_province(2) == 1


def test_state_data_has_advanced_fields():
    """Advanced fields added in Phase 2 must have default values."""
    from domain.managers.state import StateData
    s = StateData(id=1)
    assert s.impassable is False
    assert s.controller_tag == ""
    assert s.local_supplies == 0.0
    assert s.resources == {}
    assert s.buildings == {}
    assert s.extra_cores == []
    assert s.claims == []


# ──────────────── CountryManager ────────────────

def test_country_manager_crud():
    from domain.managers.country import CountryManager
    m = CountryManager()
    m.create_country("TST", "TestLand", (100, 100, 200))
    assert "TST" in m.countries
    m.set_capital("TST", 42)
    assert m.countries["TST"].capital == 42
    m.assign_state(1, "TST")
    assert m.get_owner_of_state(1) == "TST"
