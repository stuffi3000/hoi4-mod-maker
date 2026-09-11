"""Automatic terrain refinement — Automatically generate rich graphical terrain annotations for maps by latitude/elevation/noise.

The source of rich details in vanilla maps: terrain.bmp changes terrain variants every few dozen pixels
(Forest patches/hill transition/desert rocky mixed arrangement). It is unrealistic to draw 11 million pixels by hand, this module
Write geographical rules into rules and automatically generate:

1. Latitudinal tone: jungle zone → desert zone (subtropical high pressure) → temperate zone grassland/forest → frigid zone → snowfield
2. Altitude superposition: hills → mountains → snow peaks, and the variation follows the climate zone (deserts are desert hills)
3. Noise patches: forest/swamp/variant mixing, breaking up large color blocks

Output and export share the same set of palette indexes (data/terrain_types.GRAPHICAL_TERRAINS),
So what you see in the preview is what you export into the game. Full numpy vectorization, zero Qt."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter

from data.constants import TILE_LAND, TILE_LAKE, SEA_LEVEL
from domain.generators.base import GeneratorParams
from domain.preview.climate_tint import latitude_field

# ── Palette index (data/terrain_types.GRAPHICAL_TERRAINS verified) ──
IDX_PLAINS, IDX_PLAINS_VAR = 0, 5
IDX_FOREST, IDX_FOREST_VAR = 1, 4
IDX_DESERT, IDX_DESERT_VAR, IDX_DESERT_ROCK = 3, 7, 12
IDX_DESERT_HILLS, IDX_DESERT_MOUNTAIN = 8, 11
IDX_HILLS = 17
IDX_MOUNTAIN, IDX_MOUNTAIN_VAR, IDX_MOUNTAIN_GRASS = 6, 10, 20
IDX_SNOW_MOUNTAIN, IDX_PLAINS_SNOW = 16, 19
IDX_MARSH = 9
IDX_JUNGLE, IDX_JUNGLE_VAR, IDX_JUNGLE_MOUNTAIN = 21, 22, 27
IDX_LAKES, IDX_OCEAN = 14, 15

# Altitude threshold (heightmap grayscale, relative sea level)
# According to tools/vanilla_terrain_stats.py 2026-07-04 actual measurement calibration:
# Original hills P25=12/P50=20, mountains P25=20/P50=32/P75=48 — far smoother than intuitive
HILL_START = 14.0
MOUNTAIN_START = 26.0
SNOW_PEAK_START = 60.0

# Latitude band boundary (degrees)
JUNGLE_END = 16.0
DESERT_START, DESERT_END = 20.0, 38.0
TEMPERATE_END = 62.0
COLD_END = 74.0


def _quantile_thresholds(noise: np.ndarray, fracs: list[float]) -> list[float]:
    """Cut the noise field into a threshold list with specified area proportions (fracs is the cumulative proportion, in ascending order).

    Use quantiles instead of fixed thresholds that slap your head — variant blending ratios can be precisely aligned
    Original measured value (e.g. Forest 67:33)."""
    return [float(np.quantile(noise, f)) for f in fracs]


def generate_detailed_terrain(
    tile_map: np.ndarray,
    height_map: np.ndarray,
    equator_y: float | None = None,
    seed: int = 0,
) -> np.ndarray:
    """Generates a refined terrain.bmp palette index map (H, W) uint8.

    Read-only input, returns new array, does not modify any item data."""
    h, w = tile_map.shape
    rng = np.random.default_rng(seed)

    lat = latitude_field(h, w, equator_y, seed)
    hf = height_map.astype(np.float32) - float(SEA_LEVEL)

    # Noise field: forest patches (medium frequency) / variant mix (low frequency + fine grain) / swamp dotted (medium frequency)
    # Variant noise mixed with 30% fine-grained components: original patch boundary density measured 0.252 (per 4 land masses
    # (1 pixel on the boundary), the boundary of pure low-frequency noise is too smooth and sparse
    forest_blob = gaussian_filter(
        rng.standard_normal((h, w)).astype(np.float32), 14.0)
    forest_blob /= max(float(np.abs(forest_blob).max()), 1e-6)
    variant_fine = gaussian_filter(
        rng.standard_normal((h, w)).astype(np.float32), 1.8)
    variant_fine /= max(float(np.abs(variant_fine).max()), 1e-6)
    # The edges of forest patches are mixed with fine grains - the original forest/plains border is a dog-tooth-shaped edge.
    forest_noise = forest_blob * 0.78 + variant_fine * 0.22
    variant_low = gaussian_filter(
        rng.standard_normal((h, w)).astype(np.float32), 55.0)
    variant_low /= max(float(np.abs(variant_low).max()), 1e-6)
    variant_noise = variant_low * 0.40 + variant_fine * 0.60
    marsh_noise = gaussian_filter(
        rng.standard_normal((h, w)).astype(np.float32), 9.0)
    marsh_noise /= max(float(np.abs(marsh_noise).max()), 1e-6)

    out = np.full((h, w), IDX_OCEAN, dtype=np.uint8)
    land = tile_map == TILE_LAND

    # The area ratio of the variant mixture is measured according to the original version (tools/vanilla_terrain_stats.py):
    # Plain 91:7, Forest 67:33, Jungle 87:13, Desert 44:32:14:10
    q_plains, = _quantile_thresholds(variant_noise, [0.91])
    q_jungle, = _quantile_thresholds(variant_noise, [0.87])
    q_d1, q_d2, q_d3 = _quantile_thresholds(variant_noise, [0.44, 0.76, 0.90])

    # ── 1. Latitude tone ──
    # Principle: Any climate zone is "keynote + patch", and the entire zone cannot be lumped into color blocks.
    base = np.full((h, w), IDX_PLAINS, dtype=np.uint8)
    base[variant_noise > q_plains] = IDX_PLAINS_VAR

    jungle_band = lat < JUNGLE_END
    jungle = jungle_band & (forest_noise > -0.12)        # ~6 into jungle patches, remaining plains
    base[jungle] = IDX_JUNGLE
    base[jungle & (variant_noise > q_jungle)] = IDX_JUNGLE_VAR

    desert_band = (lat >= DESERT_START) & (lat < DESERT_END)
    desert = desert_band & (variant_low > -0.35)         # Transition to steppe with margins
    base[desert] = IDX_DESERT
    base[desert & (variant_noise > q_d1)] = IDX_DESERT_VAR
    base[desert & (variant_noise > q_d2)] = IDX_DESERT_HILLS
    base[desert & (variant_noise > q_d3)] = IDX_DESERT_ROCK

    snow = lat >= COLD_END
    base[snow] = IDX_PLAINS_SNOW

    # ── 2. Forest patches (density varies with climate zone, no trees grow in deserts/snowfields) ──
    forest_density = np.zeros((h, w), dtype=np.float32)
    forest_density[(lat >= JUNGLE_END) & (lat < DESERT_START)] = 0.15
    forest_density[(lat >= DESERT_END) & (lat < TEMPERATE_END)] = 0.30
    forest_density[(lat >= TEMPERATE_END) & (lat < COLD_END)] = 0.22
    forest = (forest_noise > (0.62 - forest_density)) & (forest_density > 0)
    q_forest, = _quantile_thresholds(variant_noise, [0.67])   # Original 67:33
    base[forest] = IDX_FOREST
    base[forest & (variant_noise > q_forest)] = IDX_FOREST_VAR

    # ── 3. Swamp embellishment: Temperate low-lying flat land ──
    marsh = (
        (lat >= DESERT_END) & (lat < COLD_END)
        & (hf < 12.0) & (marsh_noise > 0.78) & ~forest
    )
    base[marsh] = IDX_MARSH

    # ── 4. Altitude overlay (overrides base tone, variants follow climate zone) ──
    # NOTE: The generic hills map (IDX_HILLS→atlas tile 2) is arid sand tones,
    # Using it directly on temperate hills will make the whole map turn yellow - humid hills retain the vegetation map.
    # The three-dimensional feeling is given to high light and shadow; only the hills in the arid zone are mapped with sand-colored hills.
    hills = hf >= HILL_START
    base[hills & desert] = IDX_DESERT_HILLS
    base[hills & (lat >= DESERT_END) & (variant_noise > 0.45)] = IDX_HILLS

    # Mountain variant measured according to the original version 42:34:22 (idx11:idx20:idx10)
    q_m1, q_m2 = _quantile_thresholds(variant_noise, [0.42, 0.76])
    mountains = hf >= MOUNTAIN_START
    base[mountains] = IDX_MOUNTAIN
    base[mountains & (variant_noise > q_m1)] = IDX_MOUNTAIN_GRASS
    base[mountains & (variant_noise > q_m2)] = IDX_MOUNTAIN_VAR
    base[mountains & desert] = IDX_DESERT_MOUNTAIN
    base[mountains & jungle] = IDX_JUNGLE_MOUNTAIN

    peaks = hf >= SNOW_PEAK_START
    base[peaks] = IDX_SNOW_MOUNTAIN
    # Mountains in the frigid zone are all snowy mountains
    base[mountains & snow] = IDX_SNOW_MOUNTAIN

    # ── 5. Return to water and land ──
    out[land] = base[land]
    out[tile_map == TILE_LAKE] = IDX_LAKES
    return out


# ── Standard generator interface (first implementation of domain/generators/base.py protocol) ──

@dataclass(frozen=True)
class TerrainDetailParams(GeneratorParams):
    """Climate refinement parameters. equator_y=None means the equator is at the vertical center of the map."""
    equator_y: float | None = None


class TerrainDetailGenerator:
    """Refine Terrain by Climate — First generator for Route C."""

    id = "terrain_detail"
    target_layer = "terrain_map"

    def default_params(self) -> TerrainDetailParams:
        return TerrainDetailParams()

    def generate(self, map_data, params: TerrainDetailParams,
                 mask: np.ndarray | None = None) -> np.ndarray:
        out = generate_detailed_terrain(
            map_data.tile_map, map_data.height_map,
            equator_y=params.equator_y, seed=params.seed,
        )
        if mask is not None:
            # Keep the original layer outside the mask (protect the manually refined area)
            out = np.where(mask, out, map_data.terrain_map)
        return out.astype(np.uint8)
