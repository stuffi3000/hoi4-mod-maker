"""Regression tests for map data that can make HOI4 fail during startup."""

from __future__ import annotations

import numpy as np

from data.constants import TILE_LAND, TILE_SEA
from domain.managers.state import StateData, StateManager
from domain.validators.province import (
    build_coastal_land_to_sea,
    get_coastal_provinces,
)
from export.mod_exporter import _compute_coastal_once, _compute_coastal_province_level
from export.writers.history.states import write_states_from_mgr
from export.writers.map.buildings import write_buildings
from export.writers.replace_path.scrubber import write_replace_path_dirs


def _seam_map() -> tuple[np.ndarray, np.ndarray]:
    """Land at the right edge touches sea at the wrapped left edge."""
    tile_map = np.array(
        [[TILE_SEA, TILE_LAND], [TILE_SEA, TILE_LAND]], dtype=np.uint8
    )
    province_map = np.array([[2, 1], [2, 1]], dtype=np.int32)
    return tile_map, province_map


def test_coastal_calculations_include_the_horizontal_map_seam():
    tile_map, province_map = _seam_map()

    coastal, land_to_sea = _compute_coastal_once(province_map, [1], [2])

    assert coastal == {1}
    assert land_to_sea == {1: 2}
    assert _compute_coastal_province_level(province_map, [1], [2]) == {1}
    assert get_coastal_provinces(tile_map, province_map) == {1}
    assert build_coastal_land_to_sea(tile_map, province_map) == {1: 2}


def test_state_writer_normalises_categories_and_moves_invalid_naval_base(tmp_path):
    _tile_map, province_map = _seam_map()
    state_mgr = StateManager()
    state = StateData(
        id=1,
        name="Safety Test",
        provinces=[1, 2],
        category="small",
        # Province 1 is inland; province 2 is the only coastal province.
        province_buildings={1: {"naval_base": 1}},
    )
    state_mgr.states[1] = state

    write_states_from_mgr(
        state_mgr,
        country_mgr=None,
        province_map=province_map,
        output_dir=str(tmp_path),
        land_id_set={1, 2},
        coastal_set={2},
    )

    text = (tmp_path / "history" / "states" / "1-STATE_1.txt").read_text(
        encoding="utf-8"
    )
    assert "state_category = rural" in text
    assert "\t\t\t1 = {\n\t\t\t\tnaval_base" not in text
    assert "\t\t\t2 = {\n\t\t\t\tnaval_base" in text


def test_buildings_writer_places_a_seam_port_on_a_land_pixel(tmp_path):
    tile_map, province_map = _seam_map()

    write_buildings(
        {1: [1]},
        province_map,
        tile_map,
        str(tmp_path),
        land_to_sea={1: 2},
    )

    lines = (tmp_path / "map" / "buildings.txt").read_text(encoding="utf-8").splitlines()
    assert "1;naval_base_spawn;1.50;11.00;1.50;0.00;2" in lines


def test_replace_path_cleanup_removes_only_legacy_generated_overlays(tmp_path):
    generated = tmp_path / "common" / "on_actions" / "15_mun_on_actions.txt"
    generated.parent.mkdir(parents=True)
    generated.write_text("# Empty - TC MOD override\non_actions = { }\n", encoding="utf-8")
    custom = generated.parent / "my_custom_action.txt"
    custom.write_text("on_actions = { }\n", encoding="utf-8")

    write_replace_path_dirs(str(tmp_path))

    assert not generated.exists()
    assert custom.exists()
