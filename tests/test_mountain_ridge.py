"""Draw Mountain Line Test — Upgraded real mountain chain behavior (no test coverage before)."""

import numpy as np

from services.terrain_service import apply_mountain_ridge
from data.constants import TILE_LAND, TILE_SEA, SEA_LEVEL


def _world(h=200, w=400):
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    tile_map[:, :40] = TILE_SEA
    height_map = np.full((h, w), SEA_LEVEL + 20, dtype=np.uint8)
    return tile_map, height_map


def test_ridge_raises_heights_near_line_only():
    """The ridgeline is elevated near, and the ocean is motionless in the distance."""
    tile_map, height_map = _world()
    points = [(100, 80), (100, 350)]
    out = apply_mountain_ridge(height_map, tile_map, points, peak_height=220)

    assert int(out[100, 200]) > 150            # on the ridge
    assert int(out[10, 200]) == SEA_LEVEL + 20  # The plain is motionless in the distance
    assert np.array_equal(out[:, :40], height_map[:, :40])  # The ocean does not move


def test_crest_has_peaks_and_passes():
    """There are fluctuations in height along the ridge (main peak and pass), and it is no longer a uniform mound."""
    tile_map, height_map = _world()
    points = [(100, 80), (100, 350)]
    out = apply_mountain_ridge(height_map, tile_map, points, peak_height=220)

    crest = out[100, 90:340].astype(np.int32)   # Sampling along the ridge
    assert crest.max() - crest.min() > 25       # There are significant peaks and valleys
    assert crest.min() > 100                    # But the pass is still a mountain, constantly connected


def test_same_line_is_deterministic():
    """The results of two calls for the same line are consistent (the mountain shape does not jump when previewing the slider)."""
    tile_map, height_map = _world()
    points = [(60, 100), (140, 300)]
    a = apply_mountain_ridge(height_map, tile_map, points, peak_height=200)
    b = apply_mountain_ridge(height_map, tile_map, points, peak_height=200)
    assert np.array_equal(a, b)
