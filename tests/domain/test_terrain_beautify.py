"""Conformal beautification terrain test—layout preservation/measured proportional blending/protected pixels."""

from types import SimpleNamespace

import numpy as np

from domain.generators.terrain_beautify import (
    beautify_terrain, TerrainBeautifyGenerator, TerrainBeautifyParams,
    IDX_URBAN,
)
from domain.generators.terrain_detail import (
    IDX_PLAINS, IDX_PLAINS_VAR, IDX_FOREST, IDX_FOREST_VAR,
    IDX_OCEAN, IDX_LAKES, IDX_MARSH, IDX_SNOW_MOUNTAIN,
)
from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE, SEA_LEVEL
from data.terrain_types import PALETTE_TO_TYPE


def _world(h=256, w=512):
    """A hand-drawn world with half forests on the left and plains on the right, with a sea at the top."""
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    tile_map[:20, :] = TILE_SEA
    terrain = np.full((h, w), IDX_PLAINS, dtype=np.uint8)
    terrain[:, :w // 2] = IDX_FOREST
    terrain[:20, :] = IDX_OCEAN
    height = np.full((h, w), SEA_LEVEL + 5, dtype=np.uint8)
    return tile_map, terrain, height


def test_layout_families_preserved():
    """The family layout drawn by the author basically remains unchanged (distortion only moves the boundaries, not moving)."""
    tile_map, terrain, height = _world()
    out = beautify_terrain(terrain, tile_map, height, seed=1)

    fam = np.vectorize(lambda i: PALETTE_TO_TYPE.get(int(i), ""))
    # Sampling area far away from the boundary: the deep left part should still be the forest family, and the deep right part should still be the plain family
    left = fam(out[100:200, 50:200])
    right = fam(out[100:200, 300:460])
    assert (left == "forest").mean() > 0.95
    assert (right == "plains").mean() > 0.95


def test_variant_mix_matches_vanilla_ratio():
    """The ratio of variants within the forest block is close to the original measured 67:33 (±8%)."""
    tile_map, terrain, height = _world()
    out = beautify_terrain(terrain, tile_map, height, seed=2)

    forest_zone = out[30:, :256]
    total = np.isin(forest_zone, [IDX_FOREST, IDX_FOREST_VAR]).sum()
    var_ratio = (forest_zone == IDX_FOREST_VAR).sum() / max(int(total), 1)
    assert 0.25 < var_ratio < 0.41


def test_water_urban_marsh_protected():
    """The sea/lake is forcibly restored; the city and swamp (the author's explicit design) are retained as they are."""
    tile_map, terrain, height = _world()
    tile_map[100:110, 100:110] = TILE_LAKE
    terrain[150:160, 150:160] = IDX_URBAN
    terrain[200:210, 300:310] = IDX_MARSH
    height[150:170, 140:320] = SEA_LEVEL + 70          # High altitudes also cannot cover protected areas.

    out = beautify_terrain(terrain, tile_map, height, seed=3)

    assert np.all(out[:20, :] == IDX_OCEAN)
    assert np.all(out[100:110, 100:110] == IDX_LAKES)
    assert np.all(out[150:160, 150:160] == IDX_URBAN)
    assert np.all(out[200:210, 300:310] == IDX_MARSH)


def test_elevation_overlay_snow_peaks():
    """The highlands above the snow line are dotted with snowy mountains (the threshold is +60 measured in the original version)."""
    tile_map, terrain, height = _world()
    height[120:130, 400:420] = SEA_LEVEL + 70
    out = beautify_terrain(terrain, tile_map, height, seed=4)
    assert np.all(out[122:128, 402:418] == IDX_SNOW_MOUNTAIN)


def test_generator_protocol():
    """Agreement: Do not change the input; can be reproduced with the same seed."""
    tile_map, terrain, height = _world()
    md = SimpleNamespace(terrain_map=terrain, tile_map=tile_map,
                         height_map=height)
    before = terrain.copy()
    gen = TerrainBeautifyGenerator()

    a = gen.generate(md, TerrainBeautifyParams(seed=7))
    b = gen.generate(md, TerrainBeautifyParams(seed=7))

    assert np.array_equal(md.terrain_map, before)      # Enter zero modifications
    assert np.array_equal(a, b)
    assert gen.target_layer == "terrain_map"
