"""Auto Climatic Tone — Replaces the hand-drawn regional tone maps from Parasite Artists.

Seventy percent of the "good-looking" vanilla map comes from the hand-painted colormap (Saharan Golden/European Emerald/Polar Cold White).
This module automatically generates the same tone layer according to geographical rules:

1. Latitudinal climate zone: equatorial wet green → subtropical dry yellow (Hadry cell subsidence zone) → temperate green
   → Cold gray in the cold zone → Polar snow white
2. Altitude correction: the mountains gradually turn into rock gray/snow white
3. Low-frequency noise: breaks up the "contour sense" of latitude bands and makes the edges of color blocks natural

Output (H, W, 3) uint8 tone map, 128 = primary color (matching the synthesizer material×hue×2 formula).
Full numpy vectorization, zero Qt."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter

from data.constants import TILE_LAND, SEA_LEVEL

# Climate Zone Key: |Latitude| → Hue RGB (128 is neutral)
# The value is designed around 128 to avoid overexposure/overdarkness under the ×2 formula
_LAT_KEYS = np.array([0, 12, 22, 33, 45, 58, 68, 78, 90], dtype=np.float32)
_LAT_R = np.array([108, 112, 138, 150, 122, 112, 124, 150, 165], dtype=np.float32)
_LAT_G = np.array([132, 134, 132, 138, 130, 124, 126, 152, 168], dtype=np.float32)
_LAT_B = np.array([ 96, 100,  98, 100, 104, 108, 122, 155, 175], dtype=np.float32)

# Altitude correction: Above this altitude, the transition to ash begins, and the snow line turns white
# (Calibrated according to the original actual measurement: mountain P50=+32, see tools/vanilla_terrain_stats.py)
_ROCK_START = SEA_LEVEL + 26.0
_SNOW_LINE = SEA_LEVEL + 60.0
_ROCK_RGB = np.array([130, 128, 126], dtype=np.float32)
_SNOW_RGB = np.array([175, 178, 185], dtype=np.float32)

# Low frequency noise: amplitude (hue units) and smoothing radius (pixels)
_NOISE_AMP = 9.0
_NOISE_SIGMA = 48.0


def latitude_field(
    h: int,
    w: int,
    equator_y: float | None = None,
    seed: int = 0,
    amp: float = _NOISE_AMP,
    sigma: float = _NOISE_SIGMA,
) -> np.ndarray:
    """Per-pixel "latitude" (H, W) float32, 0~90, meandering with low-frequency noise.

    Terrain refinement and climate tones share this field, ensuring that the forest zone and the tonal zone match up."""
    eq = h / 2.0 if equator_y is None else float(equator_y)
    ys = np.arange(h, dtype=np.float32)
    lat = np.abs(ys - eq) / max(eq, h - eq) * 90.0          # (H,)

    rng = np.random.default_rng(seed)
    wobble = gaussian_filter(
        rng.standard_normal((h, w)).astype(np.float32), sigma)
    wobble *= amp / max(float(np.abs(wobble).max()), 1e-6)
    return np.clip(lat[:, None] + wobble, 0.0, 90.0)


def generate_climate_tint(
    tile_map: np.ndarray,
    height_map: np.ndarray,
    equator_y: float | None = None,
    seed: int = 0,
) -> np.ndarray:
    """Automatically generate a tone map by latitude/altitude, returning (H, W, 3) uint8.

    Parameters:
        tile_map: land/sea/lake classification (H, W); water pixel output neutral 128 (will be covered by water color anyway)
        height_map: height map (H, W)
        equator_y: Equator row, None = map vertically centered (H/2)
        seed: noise seed, the same seed result can be reproduced"""
    h, w = tile_map.shape

    # ── 1. Latitude climate zone ──
    lat2d = latitude_field(h, w, equator_y, seed)           # (H, W)

    tint = np.empty((h, w, 3), dtype=np.float32)
    tint[:, :, 0] = np.interp(lat2d, _LAT_KEYS, _LAT_R)
    tint[:, :, 1] = np.interp(lat2d, _LAT_KEYS, _LAT_G)
    tint[:, :, 2] = np.interp(lat2d, _LAT_KEYS, _LAT_B)

    # ── 2. Altitude correction: Alpine → Ash → Snow ──
    hf = height_map.astype(np.float32)
    rock_t = np.clip((hf - _ROCK_START) / (_SNOW_LINE - _ROCK_START), 0.0, 1.0)
    if np.any(rock_t > 0):
        # First transition to rock ash (first half), then transition to snow white (second half)
        half = np.clip(rock_t * 2.0, 0.0, 1.0)[:, :, None]
        peak = np.clip(rock_t * 2.0 - 1.0, 0.0, 1.0)[:, :, None]
        tint = tint * (1.0 - half) + _ROCK_RGB * half
        tint = tint * (1.0 - peak) + _SNOW_RGB * peak

    # ── 3. The water body is neutral ──
    tint[tile_map != TILE_LAND] = 128.0

    return np.clip(tint, 0, 255).astype(np.uint8)
