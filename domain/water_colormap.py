"""Sea surface coloring — a shallow to dark gradient based on the distance from the land, and the export and preview share the same formula.

Effect: Nearshore greenish, gradient to deep blue distant sea within 80 pixels; land/lake pixels are filled with deep sea color
     (Exactly consistent with the exported colormap_water, what you see in the preview is the game sea surface color source).
Applicable: export/writers/map/colormap_dds (packaged into BGRA DDS),
     domain/preview/compositor (preview the sea surface and take RGB directly).
Call: water_color_rgb(tile_map) → (H, W, 3) float32 RGB [0,255]"""
import numpy as np

from data.constants import TILE_SEA

# Shallow sea (nearshore) green → deep sea dark blue
SHALLOW_RGB = np.array([130.0, 200.0, 180.0], dtype=np.float32)
DEEP_RGB = np.array([30.0, 70.0, 110.0], dtype=np.float32)
# So many pixels from land to achieve pure deep sea color
DEEP_DISTANCE = 80.0


def water_color_rgb(tile_map: np.ndarray) -> np.ndarray:
    """tile_map (H, W) uint8 → sea surface color (H, W, 3) float32.

    Ocean pixels gradient according to distance from land; non-ocean pixels (land/lakes) are filled with dark sea color —
    The engine does not use the water color of the land, and fills it uniformly to avoid mip edge artifacts.
    Requires scipy; downgraded by the caller when unavailable."""
    from scipy.ndimage import distance_transform_edt

    sea = (tile_map == TILE_SEA) | (tile_map == 0)
    dist_to_land = distance_transform_edt(sea).astype(np.float32)
    norm = np.clip(dist_to_land / DEEP_DISTANCE, 0.0, 1.0)
    rgb = SHALLOW_RGB + (DEEP_RGB - SHALLOW_RGB) * norm[..., None]
    rgb[~sea] = DEEP_RGB
    return rgb
