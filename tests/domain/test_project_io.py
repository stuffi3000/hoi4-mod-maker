"""Round-trip coverage for authored project metadata."""

from __future__ import annotations

import numpy as np

from domain.managers.country import CountryManager
from domain.managers.state import StateManager
from domain.project_io import load_project, save_project


def test_project_round_trip_preserves_localised_state_and_vp_names(tmp_path):
    states = StateManager()
    state = states.create_state([1])
    state.name = "Bruxelles-Capitale"
    state.name_en = "Brussels-Capital"
    state.victory_points = {1: 50}
    state.vp_names = {1: "Bruxelles"}
    state.vp_names_en = {1: "Brussels"}

    countries = CountryManager()
    path = tmp_path / "roundtrip.hoi4proj"
    array = np.ones((2, 2), dtype=np.int32)
    save_project(
        str(path),
        tile_map=np.ones((2, 2), dtype=np.uint8),
        province_map=array,
        terrain_map=np.zeros((2, 2), dtype=np.uint8),
        height_map=np.ones((2, 2), dtype=np.float32),
        state_mgr=states,
        country_mgr=countries,
    )

    restored_states = StateManager()
    restored_countries = CountryManager()
    load_project(str(path), restored_states, restored_countries)
    restored = restored_states.get_state(1)

    assert restored is not None
    assert restored.name_en == "Brussels-Capital"
    assert restored.vp_names == {1: "Bruxelles"}
    assert restored.vp_names_en == {1: "Brussels"}
