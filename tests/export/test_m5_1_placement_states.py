"""M5.1 follow-up: placement state refs stay synced on state delete/compact."""
from __future__ import annotations

import inspect
import types

import numpy as np
import pytest

from domain.managers.country import CountryManager
from domain.managers.map_placement import MapPlacementManager
from domain.managers.state import StateManager
from services.export_planner import (
    _apply_state_empty_cleanup,
    analyze_state_empty_cleanup,
    plan_export,
)
from services.export_service import (
    _precheck_clean_empty_states,
    pre_export_check_and_fix,
)

pytestmark = pytest.mark.unit


def _maps():
    tile = np.ones((2, 4), dtype=np.uint8)
    province = np.array([[1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    return tile, province


def _managers_with_gap():
    states = StateManager()
    s1 = states.create_state([1])
    s2 = states.create_state([])
    s3 = states.create_state([2])
    assert (s1.id, s2.id, s3.id) == (1, 2, 3)
    countries = CountryManager()
    countries.create_country("TST", "Testland", (100, 120, 200))
    countries.assign_state(1, "TST")
    countries.assign_state(3, "TST")
    countries.get_country("TST").capital = 1
    placements = MapPlacementManager()
    b_keep = placements.add_building(1, "bunker", 1.0, 1.0, state_id=1)
    b_remap = placements.add_building(2, "bunker", 2.0, 2.0, state_id=3)
    b_deleted = placements.add_building(1, "arms_factory", 3.0, 3.0, state_id=2)
    b_unknown = placements.add_building(1, "bunker", 4.0, 4.0, state_id=99)
    b_none = placements.add_building(1, "bunker", 5.0, 5.0)
    ids = {
        "keep": b_keep,
        "remap": b_remap,
        "deleted": b_deleted,
        "unknown": b_unknown,
        "none": b_none,
    }
    return states, countries, placements, ids


def _state_of(mgr, rid):
    rec = mgr.get_building(rid)
    assert rec is not None
    return rec.state_id


def test_precheck_signature_stays_backward_compatible():
    sig = inspect.signature(_precheck_clean_empty_states)
    params = list(sig.parameters.values())
    assert [p.name for p in params[:3]] == ["state_mgr", "country_mgr", "fixed"]
    assert "map_placement_mgr" in sig.parameters
    assert sig.parameters["map_placement_mgr"].default is None
    sig2 = inspect.signature(pre_export_check_and_fix)
    assert "map_placement_mgr" in sig2.parameters
    assert sig2.parameters["map_placement_mgr"].default is None


def test_snapshot_repair_remaps_and_clears_snapshot_only():
    tile, province = _maps()
    states, countries, live, ids = _managers_with_gap()
    live_before = live.to_dict()
    live_states_before = sorted(states.states.keys())

    plan = plan_export(
        tile,
        province,
        None,
        state_mgr=states,
        country_mgr=countries,
        map_placement_mgr=live,
        profile_name="foundation",
    )
    snap_mgr = plan.snapshot.map_placement_mgr
    assert snap_mgr is not live
    assert snap_mgr.to_dict() == live_before
    assert live_states_before == [1, 2, 3]

    actions = analyze_state_empty_cleanup(plan.snapshot)
    assert len(actions) == 1

    _apply_state_empty_cleanup(plan.snapshot, actions[0])

    assert sorted(plan.snapshot.state_mgr.states.keys()) == [1, 2]
    assert plan.snapshot.country_mgr.get_owner_of_state(1) == "TST"
    assert plan.snapshot.country_mgr.get_owner_of_state(2) == "TST"
    assert plan.snapshot.country_mgr.get_owner_of_state(3) == ""
    assert _state_of(snap_mgr, ids["keep"]) == 1
    assert _state_of(snap_mgr, ids["remap"]) == 2
    assert _state_of(snap_mgr, ids["deleted"]) is None
    assert _state_of(snap_mgr, ids["unknown"]) is None
    assert _state_of(snap_mgr, ids["none"]) is None

    assert live.to_dict() == live_before
    assert _state_of(live, ids["remap"]) == 3
    assert _state_of(live, ids["deleted"]) == 2
    assert _state_of(live, ids["unknown"]) == 99
    assert sorted(states.states.keys()) == [1, 2, 3]


def test_legacy_preflight_remaps_and_clears_with_fixed_messages():
    tile, province = _maps()
    states, countries, placements, ids = _managers_with_gap()

    report = pre_export_check_and_fix(
        tile,
        province,
        None,
        states,
        countries,
        map_placement_mgr=placements,
    )

    assert sorted(states.states.keys()) == [1, 2]
    assert countries.get_owner_of_state(1) == "TST"
    assert countries.get_owner_of_state(2) == "TST"
    assert _state_of(placements, ids["keep"]) == 1
    assert _state_of(placements, ids["remap"]) == 2
    assert _state_of(placements, ids["deleted"]) is None
    assert _state_of(placements, ids["unknown"]) is None
    assert _state_of(placements, ids["none"]) is None
    assert any("Deleted 1 empty states" in m for m in report.fixed)
    assert any("Renumbered" in m for m in report.fixed)


def test_deleted_only_clears_without_renumber():
    states = StateManager()
    states.create_state([1])
    states.create_state([])
    countries = CountryManager()
    countries.create_country("TST", "Testland", (100, 120, 200))
    countries.assign_state(1, "TST")
    countries.get_country("TST").capital = 1
    placements = MapPlacementManager()
    b_keep = placements.add_building(1, "bunker", 1.0, 1.0, state_id=1)
    b_gone = placements.add_building(1, "bunker", 2.0, 2.0, state_id=2)
    fixed: list = []
    _precheck_clean_empty_states(states, countries, fixed, placements)

    assert sorted(states.states.keys()) == [1]
    assert _state_of(placements, b_keep) == 1
    assert _state_of(placements, b_gone) is None
    assert any("Deleted 1 empty states" in m for m in fixed)
    assert not any("Renumbered" in m for m in fixed)


def test_export_mod_forwards_placement_through_preflight(monkeypatch):
    import shutil
    import tempfile
    from services import export_service as svc

    tile, province = _maps()
    states, countries, placements, ids = _managers_with_gap()
    canvas = types.SimpleNamespace(
        tile_map=tile,
        province_map=province,
        terrain_map=None,
        river_map=None,
        height_map=None,
        map_data=types.SimpleNamespace(provincial_terrain={}),
    )
    monkeypatch.setattr(
        "export.mod_exporter.export_full_mod", lambda *a, **k: None
    )
    outdir = tempfile.mkdtemp(prefix="hoi4_m51_state_test_")
    try:
        report = svc.export_mod(
            outdir,
        canvas,
        states,
        countries,
        None,
        map_placement_mgr=placements,
        )
        assert sorted(states.states.keys()) == [1, 2]
        assert _state_of(placements, ids["keep"]) == 1
        assert _state_of(placements, ids["remap"]) == 2
        assert _state_of(placements, ids["deleted"]) is None
        assert _state_of(placements, ids["unknown"]) is None
        assert any("Deleted 1 empty states" in m for m in report.fixed)
        assert any("Renumbered" in m for m in report.fixed)
    finally:
        shutil.rmtree(outdir, ignore_errors=True)
