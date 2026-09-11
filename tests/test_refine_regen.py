"""Regenerate terrain test from scratch — regenerate branch of refine_heightmap_region."""

import numpy as np

from services.terrain_service import refine_heightmap_region
from commands.map.refine_height_region import (
    RefineHeightRegionCommand, RefineParams)
from data.constants import TILE_LAND, TILE_SEA, SEA_LEVEL


def _world(h=200, w=300):
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    tile_map[:, :30] = TILE_SEA
    height_map = np.full((h, w), SEA_LEVEL + 40, dtype=np.uint8)
    return tile_map, height_map


def _lasso_mask(h=200, w=300):
    mask = np.zeros((h, w), dtype=bool)
    mask[50:150, 80:220] = True
    return mask


def test_regenerate_only_touches_mask():
    """Not a single pixel outside the selection is moved; inside the selection is redone."""
    tile_map, height_map = _world()
    mask = _lasso_mask()
    out = refine_heightmap_region(
        height_map, mask, tile_map, seed=3, regenerate=True)

    assert np.array_equal(out[~mask], height_map[~mask])
    assert not np.array_equal(out[mask], height_map[mask])


def test_regenerate_edges_blend_smoothly():
    """There is no cliff on the boundary of the selection: the difference between the inner circle of the boundary and the original image is very small (feathering connection)."""
    tile_map, height_map = _world()
    mask = _lasso_mask()
    out = refine_heightmap_region(
        height_map, mask, tile_map, seed=3, regenerate=True)

    # Row 1 inside the upper boundary of the selection: blending weight close to 0 → should be almost consistent with the original image
    border_row = out[50, 80:220].astype(np.int32)
    original_row = height_map[50, 80:220].astype(np.int32)
    assert int(np.abs(border_row - original_row).max()) <= 3


def test_regenerate_deterministic_and_seed_varies():
    tile_map, height_map = _world()
    mask = _lasso_mask()
    a = refine_heightmap_region(height_map, mask, tile_map, seed=7, regenerate=True)
    b = refine_heightmap_region(height_map, mask, tile_map, seed=7, regenerate=True)
    c = refine_heightmap_region(height_map, mask, tile_map, seed=8, regenerate=True)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_sea_floor_rebuilt_unconditionally():
    """When the mask contains oceans, the seafloor is reconstructed as the continental shelf slope—even though the refinement intensity is zero.

    The seabed is not a creative content, the chaotic legacy data is unconditionally taken over by algorithms (user feedback:
    "The ocean is a mess and I can't possibly change it myself")."""
    tile_map, height_map = _world()
    height_map[:, :30] = 93                     # The chaotic old seabed: almost close to the sea level
    mask = np.ones(tile_map.shape, dtype=bool)

    out = refine_heightmap_region(
        height_map, mask, tile_map, strength=0.0,
        enable_ridge=False, enable_erosion=False)

    assert int(out[100, 29]) > int(out[100, 2])          # Shallow near shore, deep offshore
    assert int(out[:, :30].max()) < SEA_LEVEL            # Push them all back below sea level
    land = tile_map == TILE_LAND
    assert np.array_equal(out[land], height_map[land])   # Strength 0: The land does not move


def test_command_undo_restores_exactly():
    """Take the command path: perform change selection, undo pixel-by-pixel restoration."""
    from types import SimpleNamespace
    tile_map, height_map = _world()
    mask = _lasso_mask()
    md = SimpleNamespace(height_map=height_map.copy(), tile_map=tile_map)
    before = md.height_map.copy()

    cmd = RefineHeightRegionCommand(
        md, mask, RefineParams(seed=5, regenerate=True))
    cmd.execute()
    assert not np.array_equal(md.height_map, before)

    cmd.undo()
    assert np.array_equal(md.height_map, before)
