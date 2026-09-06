import numpy as np
import pytest

from data.constants import SEA_LEVEL, TILE_LAKE, TILE_LAND, TILE_SEA
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.managers.river import (
    RIVER_BG_LAND,
    RIVER_MOUTH,
    RIVER_SOURCE,
    RIVER_WIDTH_1,
)
from tools.update_belgium_map_v1_1 import (
    UpdateError,
    _build_lake_surface,
    _drop_endpointless_micro_loops,
    _prepare_height_and_terrain,
    _strict_river_validation,
)


def test_lake_components_use_orthogonal_connectivity():
    tiles = np.full((3, 3), TILE_LAND, dtype=np.uint8)
    rgb = np.full((3, 3, 3), (207, 213, 16), dtype=np.uint8)
    rgb[0, 0] = (8, 225, 222)
    rgb[1, 1] = (8, 225, 222)

    updated, mask, stats = _build_lake_surface(tiles, rgb, minimum_pixels=1)

    assert int(mask.sum()) == 2
    assert stats["components"] == 2
    assert updated[0, 0] == TILE_LAKE
    assert updated[1, 1] == TILE_LAKE


def test_endpointless_micro_loop_is_removed():
    loop = np.ones((3, 3), dtype=bool)
    loop[1, 1] = False

    cleaned, components, pixels = _drop_endpointless_micro_loops(loop)

    assert not cleaned.any()
    assert components == 1
    assert pixels == 8


def test_large_endpointless_loop_is_rejected():
    loop = np.ones((7, 7), dtype=bool)
    loop[1:-1, 1:-1] = False

    with pytest.raises(UpdateError, match="closed 24-pixel loop"):
        _drop_endpointless_micro_loops(loop)


def test_river_markers_must_be_on_endpoints():
    tiles = np.full((5, 7), TILE_LAND, dtype=np.uint8)
    rivers = np.full(tiles.shape, RIVER_BG_LAND, dtype=np.uint8)
    rivers[2, 1:6] = RIVER_WIDTH_1
    rivers[2, 1] = RIVER_SOURCE
    rivers[2, 5] = RIVER_MOUTH

    report = _strict_river_validation(rivers, tiles)
    assert report["passed"] is True
    assert report["networks_4_connected"] == 1

    rivers[2, 1] = RIVER_WIDTH_1
    rivers[2, 3] = RIVER_SOURCE
    with pytest.raises(UpdateError, match="source away from an endpoint"):
        _strict_river_validation(rivers, tiles)


def test_height_normalisation_preserves_relief_without_invalid_terrain():
    raw = np.tile(np.linspace(0, 255, 10, dtype=np.uint8), (10, 1))
    tiles = np.full(raw.shape, TILE_LAND, dtype=np.uint8)
    tiles[0] = TILE_SEA
    tiles[1, :2] = TILE_LAKE
    old_terrain = np.full(raw.shape, TERRAIN_PALETTE_INDEX["plains"], dtype=np.uint8)
    old_terrain[2, 0] = TERRAIN_PALETTE_INDEX["forest"]

    height, terrain, report = _prepare_height_and_terrain(
        raw, tiles, old_terrain
    )

    land = tiles == TILE_LAND
    assert int(height[land].min()) >= SEA_LEVEL + 1
    assert int(height[land].max()) <= 255
    assert np.all(height[tiles == TILE_SEA] < SEA_LEVEL)
    assert np.all(height[tiles == TILE_LAKE] == SEA_LEVEL - 5)
    assert np.all(np.diff(height[2].astype(np.int16)) >= 0)
    assert terrain[2, 0] == TERRAIN_PALETTE_INDEX["forest"]
    assert set(np.unique(terrain)).issubset(
        {
            TERRAIN_PALETTE_INDEX["plains"],
            TERRAIN_PALETTE_INDEX["forest"],
            TERRAIN_PALETTE_INDEX["hills"],
            TERRAIN_PALETTE_INDEX["mountain"],
            TERRAIN_PALETTE_INDEX["lakes"],
            TERRAIN_PALETTE_INDEX["ocean"],
        }
    )
    assert report["normalisation"]["method"] == "gamma"
