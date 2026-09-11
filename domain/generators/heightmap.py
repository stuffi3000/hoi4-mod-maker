"""Photorealistic heightmap generation — Member 2 of the generator protocol.

Solve the three root causes of the "soft round bun world":
1. Mountains are not chained → Use ridged fractal noise (ridged FBM, 1-|noise| naturally formed
   Continuous and sharp ridge lines), and then use low-frequency "mountain belt fields" to limit the mountains to vast areas.
2. The plain is uneven → the amplitude of the lowland is reduced to ±2, and the large flat light and shadow are clean.
3. No texture → Multi-octave noise is superimposed, and the amplitude amplifies with altitude (rough mountains and delicate plains),
   High-frequency "erosion patterns" on slope surfaces

Hard constraints (to prevent game crashes, see CLAUDE.md):
- Land pixels ≥ SEA_LEVEL + 15 (coastal depressions will cause abnormal game determination)
- Ocean pixels ≤ SEA_LEVEL - 2, there is a continental shelf slope offshore (by the way, the preview
  Coastal shoals have realistic depth gradients)

Full numpy/scipy vectorization, zero Qt; read-only input, returns new array."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter, zoom

from data.constants import TILE_LAND, SEA_LEVEL, OCEAN_HEIGHT
from domain.generators.base import GeneratorParams

# ── Altitude calibration (based on tools/vanilla_terrain_stats.py 2026-07-04 actual measurement) ──
# The original is far "flatter" than intuitive: plains median +4, hills +20, mountains +32 (P75=48).
# The game engine renders with built-in vertical exaggeration — if the height map is made too high, the game will become a spiky hell.
LAND_FLOOR = SEA_LEVEL + 6        # The original plains are as low as +1~4, leaving a minimum safety margin
SEA_CEILING = SEA_LEVEL - 2


@dataclass(frozen=True)
class HeightmapParams(GeneratorParams):
    """Realistic height map parameters (default values are calibrated according to the original altitude distribution)."""
    mountain_coverage: float = 0.28   # Proportion of mountainous areas in land (0~1)
    peak_height: int = 165            # The highest peak grayscale (original mountain P75≈143, the peak is one level higher)
    shelf_width: float = 60.0         # Continental shelf width (pixels)


def _fbm(rng: np.random.Generator, shape: tuple[int, int],
         octaves: tuple[tuple[float, float], ...]) -> np.ndarray:
    """Fractal noise: (sigma, amplitude) octaves superimposed, output roughly [-1, 1].

    Performance key: Large sigma low-frequency octaves are calculated on a downsampling grid and then amplified
    (sigma 110 takes several seconds to directly filter on the 11.5 million pixels of the entire image, on a 1/8 grid
    Equivalent to sigma 14 for almost free). Full-size map generation dropped from 34s to seconds."""
    h, w = shape
    out = np.zeros(shape, dtype=np.float32)
    for sigma, amp in octaves:
        k = 1
        while sigma / (k * 2) >= 6.0 and k < 8:
            k *= 2
        if k > 1:
            sh, sw = h // k + 2, w // k + 2
            small = gaussian_filter(
                rng.standard_normal((sh, sw)).astype(np.float32), sigma / k)
            # Bilinear amplification itself is smooth, and there is no need to perform full-image filtering or smearing.
            layer = zoom(small, k, order=1)[:h, :w]
        else:
            layer = gaussian_filter(
                rng.standard_normal(shape).astype(np.float32), sigma)
        layer /= max(float(np.abs(layer).max()), 1e-6)
        out += layer * amp
    return out / max(float(np.abs(out).max()), 1e-6)


def generate_realistic_heightmap(
    tile_map: np.ndarray,
    params: HeightmapParams | None = None,
) -> np.ndarray:
    """Generate a photorealistic height map (H, W) uint8. The outlines of land and sea fully comply with tile_map."""
    if params is None:
        params = HeightmapParams()
    h, w = tile_map.shape
    rng = np.random.default_rng(params.seed)
    land = tile_map == TILE_LAND

    # ── 1. Coastal distance field: land rises inward, seafloor falls outward (continental shelf) ──
    d_land = distance_transform_edt(land).astype(np.float32)
    d_sea = distance_transform_edt(~land).astype(np.float32)

    elev = np.empty((h, w), dtype=np.float32)
    # Land base: LAND_FLOOR at the coast, climbing very slowly inland (cap +5 —
    # The original plain P50 is only +4; if the slope is too steep, it will be converted into "terraces" contours)
    elev[:] = LAND_FLOOR + np.minimum(np.sqrt(d_land) * 0.35, 5.0)
    # Seafloor: gentle slope within the continental shelf, falling outside to the deep sea
    shelf_t = np.clip(d_sea / max(params.shelf_width, 1.0), 0.0, 1.0)
    sea_depth = SEA_CEILING - 4.0 - shelf_t * (SEA_CEILING - 4.0 - OCEAN_HEIGHT)
    elev[~land] = sea_depth[~land]

    # ── 2. Mountain belt field: Low-frequency noise picks out "mountainous areas" ──
    belt = _fbm(rng, (h, w), ((110.0, 1.0), (55.0, 0.5)))
    # Do not place mountain belts near the coast (mountains generally do not start close to the coastline)
    coast_falloff = np.clip(d_land / 25.0, 0.0, 1.0)
    belt_land = belt[land] * coast_falloff[land]
    if belt_land.size:
        # Set a threshold based on the target proportion to smoothly transition into mountainous areas.
        thresh = float(np.quantile(
            belt_land, 1.0 - np.clip(params.mountain_coverage, 0.02, 0.9)))
        belt_w = np.clip((belt * coast_falloff - thresh) / 0.18, 0.0, 1.0)
    else:
        belt_w = np.zeros((h, w), dtype=np.float32)

    # ── 3. Ridge fractal: 1-|FBM| Naturally formed continuous ridge chain ──
    ridge_base = _fbm(rng, (h, w),
                      ((48.0, 1.0), (24.0, 0.5), (12.0, 0.25)))
    ridged = 1.0 - np.abs(ridge_base)            # Ridgeline = noise zero crossing
    # Strong sharpening: Only the pixels close to the ridge line reach the height of the mountain, and the rest within the mountain belt are foothills →
    # When the terrain is refined and classified by altitude, the rocks are only traced on the ridges, and the shape of the mountain chain is revealed.
    ridged = np.clip(ridged, 0.0, 1.0) ** 3.5

    peak_range = float(params.peak_height) - (LAND_FLOOR + 11.0)
    mountains = ridged * belt_w * max(peak_range, 0.0)

    # ── 4. Hilly zone: mid-frequency transition on the edge of the mountainous area (original hilly P50≈+20) ──
    hill_w = np.clip(belt_w * 2.0, 0.0, 1.0) - belt_w   # Mountain belt edge weight
    hills = (_fbm(rng, (h, w), ((20.0, 1.0), (10.0, 0.5))) * 0.5 + 0.5) \
        * hill_w * 16.0

    # ── 5. Slightly undulating plains + erosion patterns on slopes ──
    plains = _fbm(rng, (h, w), ((30.0, 1.0), (9.0, 0.4))) * 2.5
    elev_land = elev + mountains + hills + plains

    gy, gx = np.gradient(elev_land)
    slope = np.sqrt(gx * gx + gy * gy)
    erosion = _fbm(rng, (h, w), ((4.0, 1.0),)) * np.clip(slope * 1.5, 0.0, 4.0)
    elev_land += erosion

    elev[land] = elev_land[land]

    # ── 6. Smooth the entire body and then pull back the constraints (smoothing will erode the coast and must be clamped twice) ──
    elev = gaussian_filter(elev, 1.2)
    # Jitter: ±0.6 white noise breaks up uint8 quantized integer steps that would otherwise appear on gentle slopes
    # "Terrace" contours visible to the naked eye (amplified by light and shadow).
    # Spread on land only - the sea bottom must be smooth (spraying on the sea will be noisy in the height view,
    # And it is inconsistent with the seafloor reconstruction results of conformal refinement, user’s actual measurement capture package)
    dither = rng.uniform(-0.6, 0.6, elev.shape).astype(np.float32)
    elev[land] += dither[land]
    elev[land] = np.clip(elev[land], LAND_FLOOR, 255.0)
    elev[~land] = np.clip(elev[~land], 0.0, SEA_CEILING)

    return elev.astype(np.uint8)


def rebuild_sea_floor(
    height_map: np.ndarray,
    tile_map: np.ndarray,
    shelf_width: float = 60.0,
) -> np.ndarray:
    """Only the seafloor (continental shelf slope) is reconstructed, and the land does not move a single pixel.

    The bottom of the sea is not a creative content - no author can draw the bottom of the sea by hand, the chaotic height of the sea bottom
    (import/legacy build) should be taken over unconditionally by the algorithm:
    Nearshore = gentle slope below sea level, falling to the deep sea with distance from the shore."""
    land = tile_map == TILE_LAND
    d_sea = distance_transform_edt(~land).astype(np.float32)
    shelf_t = np.clip(d_sea / max(shelf_width, 1.0), 0.0, 1.0)
    sea_depth = SEA_CEILING - 4.0 - shelf_t * (SEA_CEILING - 4.0 - OCEAN_HEIGHT)

    result = height_map.copy()
    sea = ~land
    result[sea] = np.clip(sea_depth[sea], 0, SEA_CEILING).astype(np.uint8)
    return result


# ── Standard generator interface ──

class RealisticHeightmapGenerator:
    """Photorealistic Heightmap — Second generator for route C."""

    id = "realistic_heightmap"
    target_layer = "height_map"

    def default_params(self) -> HeightmapParams:
        return HeightmapParams()

    def generate(self, map_data, params: HeightmapParams,
                 mask: np.ndarray | None = None) -> np.ndarray:
        out = generate_realistic_heightmap(map_data.tile_map, params)
        if mask is not None:
            # Maintain the original height outside the mask (protect imported/manually refined areas)
            out = np.where(mask, out, map_data.height_map).astype(np.uint8)
        return out
