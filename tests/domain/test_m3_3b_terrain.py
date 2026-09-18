"""M3.3b terrain/river/mask validation slice tests."""
from __future__ import annotations

import numpy as np
import pytest

from data.constants import TILE_LAKE, TILE_LAND, TILE_SEA
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.managers.river import VALID_RIVER_VALUES
from domain.validation import FINDING_SEVERITIES
from domain.validators.terrain import validate_terrain_layers

pytestmark = pytest.mark.unit

_OCEAN = int(TERRAIN_PALETTE_INDEX["ocean"])
_LAKES = int(TERRAIN_PALETTE_INDEX["lakes"])
_PLAINS = int(TERRAIN_PALETTE_INDEX["plains"])

_STABLE_CODES = frozenset({
    "terrain.shape",
    "river.shape",
    "height.shape",
    "mask.shape",
    "terrain.index",
    "terrain.surface_mismatch",
    "river.value",
    "river.width",
    "river.connectivity",
    "height.value",
    "city.value",
    "tree.value",
})


def _clean_world():
    tile = np.array(
        [
            [TILE_LAND, TILE_LAND, TILE_SEA],
            [TILE_LAND, TILE_LAKE, TILE_SEA],
        ],
        dtype=np.uint8,
    )
    terrain = np.array(
        [
            [_PLAINS, _PLAINS, _OCEAN],
            [_PLAINS, _LAKES, _OCEAN],
        ],
        dtype=np.uint8,
    )
    river = np.full(tile.shape, 255, dtype=np.uint8)
    height = np.full(tile.shape, 120, dtype=np.uint8)
    city = np.zeros(tile.shape, dtype=np.uint8)
    tree = np.zeros(tile.shape, dtype=np.uint8)
    return tile, terrain, river, height, city, tree


def _codes(findings):
    return [item.code for item in findings]


def test_clean_input_has_no_findings():
    tile, terrain, river, height, city, tree = _clean_world()
    findings = validate_terrain_layers(
        tile,
        terrain,
        river_map=river,
        height_map=height,
        city_map=city,
        tree_map=tree,
    )
    assert findings == []


def test_clean_minimal_input_has_no_findings():
    tile = np.full((3, 3), TILE_LAND, dtype=np.uint8)
    terrain = np.full((3, 3), _PLAINS, dtype=np.uint8)
    assert validate_terrain_layers(tile, terrain) == []


def test_terrain_shape_mismatch_reports_stable_code():
    tile = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    terrain = np.zeros((2, 2), dtype=np.uint8)
    findings = validate_terrain_layers(tile, terrain)
    assert len(findings) == 1
    item = findings[0]
    assert item.code == "terrain.shape"
    assert item.severity == "error"
    assert item.layer == "terrain"
    assert "4x4" in item.evidence or "tile" in item.evidence


def test_optional_shape_mismatches_use_stable_codes():
    tile = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    terrain = np.full((4, 4), _PLAINS, dtype=np.uint8)
    river = np.zeros((2, 2), dtype=np.uint8)
    height = np.zeros((3, 3), dtype=np.uint8)
    city = np.zeros((2, 3), dtype=np.uint8)
    tree = np.zeros((5, 5), dtype=np.uint8)
    findings = validate_terrain_layers(
        tile, terrain, river_map=river, height_map=height, city_map=city, tree_map=tree
    )
    by_code = {}
    for item in findings:
        by_code.setdefault(item.code, []).append(item)
    assert "river.shape" in by_code
    assert "height.shape" in by_code
    assert "mask.shape" in by_code
    mask_layers = {item.layer for item in by_code["mask.shape"]}
    assert mask_layers == {"cities", "trees"}
    assert all(item.severity == "error" for item in findings)


def test_illegal_terrain_index_reports_coordinates_and_evidence():
    tile = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    terrain = np.full((4, 4), _PLAINS, dtype=np.uint8)
    terrain[1, 2] = 23
    terrain[3, 0] = 99
    findings = validate_terrain_layers(tile, terrain)
    index_hits = [item for item in findings if item.code == "terrain.index"]
    assert len(index_hits) == 1
    item = index_hits[0]
    assert item.severity == "error"
    assert item.layer == "terrain"
    assert tuple(item.affected_ids) == (23, 99)
    assert (2, 1) in tuple(item.coordinates)
    assert (0, 3) in tuple(item.coordinates)
    assert "23" in item.evidence and "99" in item.evidence


def test_explicit_terrain_indices_override_registry():
    tile = np.full((3, 3), TILE_LAND, dtype=np.uint8)
    terrain = np.full((3, 3), 1, dtype=np.uint8)
    assert validate_terrain_layers(tile, terrain) == []
    findings = validate_terrain_layers(tile, terrain, terrain_indices={"plains": 0})
    assert _codes(findings) == ["terrain.index"]
    assert tuple(findings[0].affected_ids) == (1,)
    assert "explicit" in findings[0].evidence


def test_surface_mismatch_reports_land_sea_lake():
    tile = np.array(
        [[TILE_LAND, TILE_SEA, TILE_LAKE]],
        dtype=np.uint8,
    )
    terrain = np.array(
        [[_OCEAN, _PLAINS, _PLAINS]],
        dtype=np.uint8,
    )
    findings = validate_terrain_layers(tile, terrain)
    surface = [item for item in findings if item.code == "terrain.surface_mismatch"]
    assert len(surface) == 3
    kinds = [item.evidence for item in findings if item.code == "terrain.surface_mismatch"]
    assert any("surface=land" in text for text in kinds)
    assert any("surface=sea" in text for text in kinds)
    assert any("surface=lake" in text for text in kinds)
    for item in surface:
        assert item.severity == "error"
        assert item.layer == "terrain"
        assert len(item.coordinates) > 0


def test_surface_mismatch_skips_illegal_indices():
    tile = np.full((2, 2), TILE_SEA, dtype=np.uint8)
    terrain = np.full((2, 2), 23, dtype=np.uint8)
    findings = validate_terrain_layers(tile, terrain)
    assert _codes(findings) == ["terrain.index"]


def test_illegal_river_values():
    tile = np.full((3, 3), TILE_LAND, dtype=np.uint8)
    terrain = np.full((3, 3), _PLAINS, dtype=np.uint8)
    river = np.full((3, 3), 255, dtype=np.uint8)
    river[0, 0] = 200
    river[2, 1] = 253
    findings = validate_terrain_layers(tile, terrain, river_map=river)
    value_hits = [item for item in findings if item.code == "river.value"]
    assert len(value_hits) == 1
    item = value_hits[0]
    assert item.severity == "error"
    assert item.layer == "rivers"
    assert tuple(item.affected_ids) == (200, 253)
    assert (0, 0) in tuple(item.coordinates)
    assert (1, 2) in tuple(item.coordinates)


def test_legal_river_values_and_backgrounds_pass():
    tile = np.full((2, 4), TILE_LAND, dtype=np.uint8)
    terrain = np.full((2, 4), _PLAINS, dtype=np.uint8)
    river = np.array([[0, 3, 254, 255], [255, 255, 255, 255]], dtype=np.uint8)
    for value in list(VALID_RIVER_VALUES)[:4]:
        assert 0 <= int(value) <= 11
    findings = validate_terrain_layers(tile, terrain, river_map=river)
    assert all(item.code != "river.value" for item in findings)


def test_river_width_finding_is_warning_and_deterministic():
    tile = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    terrain = np.full((4, 4), _PLAINS, dtype=np.uint8)
    river = np.full((4, 4), 255, dtype=np.uint8)
    river[1:3, 1:3] = 3
    first = validate_terrain_layers(tile, terrain, river_map=river)
    second = validate_terrain_layers(tile, terrain, river_map=river)
    assert first == second
    width = [item for item in first if item.code == "river.width"]
    assert len(width) == 1
    assert width[0].severity == "warning"
    assert width[0].layer == "rivers"


def test_river_diagonal_connectivity_finding():
    tile = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    terrain = np.full((4, 4), _PLAINS, dtype=np.uint8)
    river = np.full((4, 4), 255, dtype=np.uint8)
    river[1, 1] = 3
    river[2, 2] = 3
    findings = validate_terrain_layers(tile, terrain, river_map=river)
    connectivity = [item for item in findings if item.code == "river.connectivity"]
    assert len(connectivity) == 1
    assert connectivity[0].severity == "warning"
    assert len(connectivity[0].coordinates) > 0


def test_river_orthogonal_chain_has_no_topology_findings():
    tile = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    terrain = np.full((4, 4), _PLAINS, dtype=np.uint8)
    river = np.full((4, 4), 255, dtype=np.uint8)
    river[1, 1] = 3
    river[1, 2] = 3
    river[1, 3] = 3
    findings = validate_terrain_layers(tile, terrain, river_map=river)
    assert _codes(findings) == []


def test_optional_layers_value_contracts():
    tile = np.full((3, 3), TILE_LAND, dtype=np.uint8)
    terrain = np.full((3, 3), _PLAINS, dtype=np.uint8)
    height = np.zeros((3, 3), dtype=np.int16)
    height[0, 0] = 300
    city = np.zeros((3, 3), dtype=np.int16)
    city[1, 1] = -4
    tree = np.zeros((3, 3), dtype=np.uint8)
    tree[2, 2] = 7
    findings = validate_terrain_layers(
        tile, terrain, height_map=height, city_map=city, tree_map=tree
    )
    by_code = {item.code: item for item in findings}
    assert by_code["height.value"].layer == "heightmap"
    assert by_code["city.value"].layer == "cities"
    assert by_code["tree.value"].layer == "trees"
    assert by_code["tree.value"].affected_ids == (7,)
    assert (2, 2) in tuple(by_code["tree.value"].coordinates)


def test_valid_optional_layers_pass():
    tile = np.full((3, 3), TILE_LAND, dtype=np.uint8)
    terrain = np.full((3, 3), _PLAINS, dtype=np.uint8)
    height = np.full((3, 3), 120, dtype=np.uint8)
    city = np.zeros((3, 3), dtype=np.uint8)
    tree = np.zeros((3, 3), dtype=np.uint8)
    tree[0, 0] = 6
    assert validate_terrain_layers(tile, terrain, height_map=height, city_map=city, tree_map=tree) == []


def test_profile_tree_indices_override():
    tile = np.full((2, 2), TILE_LAND, dtype=np.uint8)
    terrain = np.full((2, 2), _PLAINS, dtype=np.uint8)
    tree = np.full((2, 2), 6, dtype=np.uint8)
    assert validate_terrain_layers(tile, terrain, tree_map=tree) == []
    findings = validate_terrain_layers(tile, terrain, tree_map=tree, profile={"tree_indices": [0]})
    assert _codes(findings) == ["tree.value"]
    assert "profile" in findings[0].evidence


def test_stable_codes_and_metadata():
    tile = np.full((3, 3), TILE_LAND, dtype=np.uint8)
    terrain = np.full((3, 3), 23, dtype=np.uint8)
    river = np.zeros((2, 2), dtype=np.uint8)
    findings = validate_terrain_layers(tile, terrain, river_map=river)
    assert len(findings) >= 2
    for item in findings:
        assert item.code in _STABLE_CODES
        assert item.severity in FINDING_SEVERITIES
        assert item.message.strip() != ""
        assert item.code.strip() != ""
        assert item.evidence.strip() != ""
        for coord in item.coordinates:
            assert len(coord) == 2
            assert isinstance(coord[0], int)
            assert isinstance(coord[1], int)


def test_no_mutation_of_inputs():
    tile, terrain, river, height, city, tree = _clean_world()
    terrain = terrain.copy()
    terrain[0, 0] = 23
    river = river.copy()
    river[0, 0] = 200
    before = [part.copy() for part in (tile, terrain, river, height, city, tree)]
    validate_terrain_layers(tile, terrain, river_map=river, height_map=height, city_map=city, tree_map=tree)
    for original, snapshot in zip((tile, terrain, river, height, city, tree), before):
        assert np.array_equal(original, snapshot)


def test_deterministic_results():
    tile = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    terrain = np.full((4, 4), _PLAINS, dtype=np.uint8)
    terrain[0, 1] = 23
    terrain[2, 3] = 99
    river = np.full((4, 4), 255, dtype=np.uint8)
    river[0, 0] = 200
    first = validate_terrain_layers(tile, terrain, river_map=river)
    second = validate_terrain_layers(tile, terrain, river_map=river)
    assert first == second
    assert [item.code for item in first] == [item.code for item in second]
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]


def test_finding_order_is_shape_then_index_then_river():
    tile = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    terrain = np.full((4, 4), 23, dtype=np.uint8)
    river = np.zeros((2, 2), dtype=np.uint8)
    findings = validate_terrain_layers(tile, terrain, river_map=river)
    assert _codes(findings)[0] == "river.shape"
    assert "terrain.index" in _codes(findings)
