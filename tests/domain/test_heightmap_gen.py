"""Photorealistic Heightmap Generator Testing - Hard Constraints / Mountain Chains and Plains / Generator Protocol."""

from types import SimpleNamespace

import numpy as np

from domain.generators.heightmap import (
    generate_realistic_heightmap, RealisticHeightmapGenerator,
    HeightmapParams, LAND_FLOOR, SEA_CEILING,
)
from data.constants import TILE_LAND, TILE_SEA


def _world(h=256, w=512):
    """There is a continent in the center, surrounded by oceans."""
    tile_map = np.full((h, w), TILE_SEA, dtype=np.uint8)
    tile_map[40:-40, 60:-60] = TILE_LAND
    return tile_map


def test_hard_constraints():
    """The land should not be lower than the safety bottom line, and the ocean should not be higher than the lower limit of sea level - a hard rule to prevent the game from crashing."""
    tile_map = _world()
    out = generate_realistic_heightmap(tile_map)
    land = tile_map == TILE_LAND
    assert out.dtype == np.uint8
    assert int(out[land].min()) >= LAND_FLOOR
    assert int(out[~land].max()) <= SEA_CEILING


def test_continental_shelf():
    """The seafloor near shore is shallower than offshore (continental shelf slope)."""
    tile_map = _world()
    out = generate_realistic_heightmap(tile_map)
    near_coast = out[128, 55]      # offshore 5px
    deep_sea = out[128, 5]         # far sea
    assert int(near_coast) > int(deep_sea)


def test_mountains_and_plains_coexist():
    """There are mountains (high values) and large areas of low plains, which are not uniformly bulging.

    The altitude range is calibrated according to the original actual measurement (mountain P50=+32, the peak upper limit defaults to 165) —
    The original version is far "flatter" than intuitive, and the game engine has built-in vertical exaggeration when rendering."""
    tile_map = _world()
    out = generate_realistic_heightmap(
        tile_map, HeightmapParams(seed=3, mountain_coverage=0.3))
    land_vals = out[tile_map == TILE_LAND].astype(np.int32)
    assert land_vals.max() > 140                       # Mountains exist (>sea level +45)
    plains_ratio = (land_vals < LAND_FLOOR + 10).mean()
    assert plains_ratio > 0.35                         # large plains


def test_sea_floor_is_smooth_no_dither():
    """The seabed must be smooth: to resist terrace shake, only land is spread, and the seabed must not be turned into a patch of noise.

    (User measured packet capture: The ocean generated from scratch is "higher density" than the conformally refined seabed)
    Under a straight coast, the seafloor pixel heights at the same offshore distance should be exactly the same."""
    tile_map = _world()
    out = generate_realistic_heightmap(tile_map)
    # x=5 column, the distance from the left straight line to the coast is constant → the depth of the continental shelf should be constant
    column = out[80:170, 5].astype(np.int32)
    assert int(np.ptp(column)) == 0


def test_deterministic_by_seed():
    tile_map = _world()
    a = generate_realistic_heightmap(tile_map, HeightmapParams(seed=9))
    b = generate_realistic_heightmap(tile_map, HeightmapParams(seed=9))
    c = generate_realistic_heightmap(tile_map, HeightmapParams(seed=10))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_generator_protocol_with_mask():
    """Generator interface: Do not change the input; retain the original height outside the mask."""
    tile_map = _world()
    original = np.full(tile_map.shape, 77, dtype=np.uint8)
    md = SimpleNamespace(tile_map=tile_map, height_map=original)
    gen = RealisticHeightmapGenerator()
    mask = np.zeros(tile_map.shape, dtype=bool)
    mask[:, :256] = True

    out = gen.generate(md, HeightmapParams(seed=1), mask=mask)

    assert np.all(md.height_map == 77)        # Enter zero modifications
    assert np.all(out[:, 256:] == 77)          # Reserved outside mask
    assert not np.all(out[:, :256] == 77)      # Regenerate within mask
    assert gen.target_layer == "height_map"
