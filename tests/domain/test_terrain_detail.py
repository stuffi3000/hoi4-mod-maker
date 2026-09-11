"""Terrain Auto-Thinning Test - Climate Zone Distribution/Elevation Overlay/Generator Protocol."""

from types import SimpleNamespace

import numpy as np

from domain.generators.terrain_detail import (
    generate_detailed_terrain, TerrainDetailGenerator, TerrainDetailParams,
    IDX_OCEAN, IDX_LAKES, IDX_DESERT, IDX_DESERT_VAR, IDX_DESERT_ROCK,
    IDX_JUNGLE, IDX_JUNGLE_VAR, IDX_SNOW_MOUNTAIN, IDX_PLAINS_SNOW,
)
from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE, SEA_LEVEL


def _world(h=180, w=512):
    """A flat world with all land (latitude spans 0~90).

    The width must be large enough: noise patch radius ~14px, a single latitude band is possible in a narrow world
    If the entire piece falls into one patch, the proportions will definitely shake."""
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    height_map = np.full((h, w), SEA_LEVEL + 10, dtype=np.uint8)
    return tile_map, height_map


def test_water_tiles_untouched():
    """Ocean/lake pixels are fixed to the corresponding index and do not participate in climate refinement."""
    tile_map, height_map = _world()
    tile_map[:, :8] = TILE_SEA
    tile_map[:, 8:12] = TILE_LAKE
    out = generate_detailed_terrain(tile_map, height_map)
    assert np.all(out[:, :8] == IDX_OCEAN)
    assert np.all(out[:, 8:12] == IDX_LAKES)


def test_climate_bands_present():
    """There are jungles at the equator, deserts in the subtropics, and snowfields at the poles—but none of them are one-size-fits-all color blocks."""
    tile_map, height_map = _world()
    out = generate_detailed_terrain(tile_map, height_map)

    eq_band = out[76:105]                      # Entire jungle zone (|latitude| < 14°)
    jungle_ratio = np.isin(eq_band, [IDX_JUNGLE, IDX_JUNGLE_VAR]).mean()
    assert 0.3 < jungle_ratio < 0.95           # There are patches of jungle, but it's not overly dense

    sub_band = out[114:126]                    # |Latitude| ≈ 24°~36° (h=180, equator at 90)
    desert_ratio = np.isin(
        sub_band, [IDX_DESERT, IDX_DESERT_VAR, IDX_DESERT_ROCK]).mean()
    assert desert_ratio > 0.3

    polar = out[:8]                            # arctic
    assert (polar == IDX_PLAINS_SNOW).mean() > 0.8


def test_high_peaks_become_snow_mountains():
    """The highlands above the snow line turn into snow mountains."""
    tile_map, height_map = _world()
    height_map[100:104, 10:14] = SEA_LEVEL + 130
    out = generate_detailed_terrain(tile_map, height_map)
    assert np.all(out[100:104, 10:14] == IDX_SNOW_MOUNTAIN)


def test_deterministic_by_seed():
    """It can be reproduced with the same seed, but the result will be different if the seed is changed."""
    tile_map, height_map = _world()
    a = generate_detailed_terrain(tile_map, height_map, seed=1)
    b = generate_detailed_terrain(tile_map, height_map, seed=1)
    c = generate_detailed_terrain(tile_map, height_map, seed=2)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_generator_protocol_with_mask():
    """Generator interface: Do not change map_data; maintain the original layer except mask."""
    tile_map, height_map = _world()
    original_terrain = np.full(tile_map.shape, 99, dtype=np.uint8)
    md = SimpleNamespace(
        tile_map=tile_map, height_map=height_map,
        terrain_map=original_terrain,
    )
    gen = TerrainDetailGenerator()
    mask = np.zeros(tile_map.shape, dtype=bool)
    mask[:, :32] = True

    out = gen.generate(md, TerrainDetailParams(seed=5), mask=mask)

    assert out.dtype == np.uint8
    assert np.all(md.terrain_map == 99)        # Enter zero modifications
    assert np.all(out[:, 32:] == 99)           # Keep the original value outside the mask
    assert not np.all(out[:, :32] == 99)       # The mask is refined
    assert gen.target_layer == "terrain_map"
