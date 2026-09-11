"""Coastline Smoothing — Smooth land and sea boundaries on a tile_map

Algorithm reference Azgaar Fantasy Map Generator's coastline processing:
1. Extract land-sea boundary pixels
2. Apply Gaussian blur to tile_map
3. Use threshold to re-binarize (land/sea)
4. Keep the lake the same

Effect: The jagged coastline turns into a natural arc.
Should be used before generating provinces so that province boundaries naturally follow the smoothed coastline."""
import numpy as np
from scipy.ndimage import gaussian_filter

from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE


def smooth_coastline(
    tile_map: np.ndarray,
    strength: float = 2.0,
    region: tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    """Smooth land and sea boundaries for tile_map.

    Parameters:
        tile_map: (H, W) uint8, TILE_LAND/SEA/LAKE
        strength: Smoothing strength (Gaussian sigma), the larger the smoother
        region: optional (y0, x0, y1, x1) local region, None=full image

    Return:
        New tile_map (does not modify the original array)"""
    result = tile_map.copy()

    if region is not None:
        y0, x0, y1, x1 = region
        # Leave margin for Gaussian blur to avoid edge artifacts
        margin = int(strength * 4)
        H, W = tile_map.shape
        ey0 = max(0, y0 - margin)
        ex0 = max(0, x0 - margin)
        ey1 = min(H, y1 + margin)
        ex1 = min(W, x1 + margin)
        sub = tile_map[ey0:ey1, ex0:ex1]
    else:
        sub = tile_map
        y0, x0 = 0, 0
        ey0, ex0 = 0, 0

    # Save lake position (does not participate in smoothing)
    lake_mask = sub == TILE_LAKE

    # Binary map of land: land=1, rest=0
    land_float = (sub == TILE_LAND).astype(np.float32)

    # Gaussian blur
    blurred = gaussian_filter(land_float, sigma=strength)

    # Thresholding: > 0.5 → land, otherwise ocean
    new_land = blurred > 0.5

    # Construct a smoothed subgraph
    smoothed = np.where(new_land, TILE_LAND, TILE_SEA).astype(sub.dtype)
    smoothed[lake_mask] = TILE_LAKE

    if region is not None:
        # Only the area specified by the user is written back (the margin part is not written)
        ry0 = y0 - ey0
        rx0 = x0 - ex0
        ry1 = ry0 + (y1 - y0)
        rx1 = rx0 + (x1 - x0)
        result[y0:y1, x0:x1] = smoothed[ry0:ry1, rx0:rx1]
    else:
        result[:] = smoothed

    return result
