"""Automatic climate tone test - Latitudinal climate zone/elevation correction/water neutral."""

import numpy as np

from domain.preview.climate_tint import generate_climate_tint
from data.constants import TILE_LAND, TILE_SEA, SEA_LEVEL


def _world(h=180, w=64):
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    height_map = np.full((h, w), SEA_LEVEL + 10, dtype=np.uint8)
    return tile_map, height_map


def test_output_shape_and_determinism():
    tile_map, height_map = _world()
    a = generate_climate_tint(tile_map, height_map, seed=7)
    b = generate_climate_tint(tile_map, height_map, seed=7)
    assert a.shape == (180, 64, 3)
    assert a.dtype == np.uint8
    assert np.array_equal(a, b)          # The same seed can be reproduced


def test_equator_green_subtropics_yellow():
    """The equatorial zone is greener, and the subtropical dry zone is relatively yellower (the R-G difference is larger).

    Climate zone boundaries have noisy meanderings, so compare means over strips rather than single rows."""
    tile_map, height_map = _world()
    tint = generate_climate_tint(tile_map, height_map).astype(np.int32)
    eq_band = tint[85:96]                 # near the equator
    sub_band = tint[148:166]              # |Latitude| ≈ 29°~38°
    eq_yellowness = float((eq_band[:, :, 0] - eq_band[:, :, 1]).mean())
    sub_yellowness = float((sub_band[:, :, 0] - sub_band[:, :, 1]).mean())
    assert eq_yellowness < 0              # Equatorial green (G>R)
    assert sub_yellowness > eq_yellowness + 10


def test_poles_brighter_than_tropics():
    """The polar snow is brighter than the equator."""
    tile_map, height_map = _world()
    tint = generate_climate_tint(tile_map, height_map)
    assert int(tint[0].mean()) > int(tint[90].mean())


def test_high_mountains_turn_snowy():
    """The mountains above the snow line are nearly snow-white, which is obviously brighter than the flat land at the same latitude."""
    tile_map, height_map = _world()
    height_map[100, 10] = SEA_LEVEL + 130
    tint = generate_climate_tint(tile_map, height_map)
    assert int(tint[100, 10].sum()) > int(tint[100, 40].sum()) + 60


def test_water_is_neutral():
    """Water pixel output is neutral 128 (will be covered by water color, but not messy)."""
    tile_map, height_map = _world()
    tile_map[:, :8] = TILE_SEA
    tint = generate_climate_tint(tile_map, height_map)
    assert np.all(tint[:, :8] == 128)
