"""Conformally beautify the terrain - retain the layout drawn by the author, and render the rough color blocks into original-level details.

Complementary to "terrain_detail, spread by latitude from zero":
Here **the author's drawings of forests and deserts remain unchanged**, and only do three things:

1. Boundary naturalization: domain warping — nudging each pixel with smooth noise
   At the sampling position, the straight color block boundaries become organic interlacing; the macro layout remains unchanged.
2. Intra-block mixed variants: A single color block is mixed with variants of the same family according to the measured ratio of the original version.
   (Forest 67:33, Desert 44:32:14:10, Mountain 42:34:22, Plains 91:7, Jungle 87:13
    — tools/vanilla_terrain_stats.py 2026-07-04 actual measurement)
3. Altitude superposition: hills/mountains/snow lines are automatically dotted at high places (the thresholds are the same as those measured in the original version)

Water bodies (sea/lake) and urban pixels are retained as they are; sea and land boundaries are not distorted (the coastline is sacred).
Full numpy vectorization, zero Qt; read-only input, returns new array."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter

from data.constants import TILE_LAND, TILE_LAKE, SEA_LEVEL
from data.terrain_types import PALETTE_TO_TYPE
from domain.generators.base import GeneratorParams
from domain.generators.terrain_detail import (
    _quantile_thresholds,
    IDX_PLAINS, IDX_PLAINS_VAR, IDX_FOREST, IDX_FOREST_VAR,
    IDX_DESERT, IDX_DESERT_VAR, IDX_DESERT_ROCK, IDX_DESERT_HILLS,
    IDX_DESERT_MOUNTAIN, IDX_HILLS, IDX_MOUNTAIN, IDX_MOUNTAIN_VAR,
    IDX_MOUNTAIN_GRASS, IDX_SNOW_MOUNTAIN, IDX_JUNGLE, IDX_JUNGLE_VAR,
    IDX_JUNGLE_MOUNTAIN, IDX_LAKES, IDX_OCEAN, IDX_MARSH,
    HILL_START, MOUNTAIN_START, SNOW_PEAK_START,
)

IDX_URBAN = 13

# Family → (variant index list, cumulative proportion threshold) — original measured mixing ratio
_FAMILY_MIX: dict[str, tuple[list[int], list[float]]] = {
    "plains":   ([IDX_PLAINS, IDX_PLAINS_VAR],                        [0.91]),
    "forest":   ([IDX_FOREST, IDX_FOREST_VAR],                        [0.67]),
    "jungle":   ([IDX_JUNGLE, IDX_JUNGLE_VAR],                        [0.87]),
    "desert":   ([IDX_DESERT, IDX_DESERT_VAR, IDX_DESERT_HILLS,
                  IDX_DESERT_ROCK],                                   [0.44, 0.76, 0.90]),
    "mountain": ([IDX_MOUNTAIN, IDX_MOUNTAIN_GRASS, IDX_MOUNTAIN_VAR], [0.42, 0.76]),
}


@dataclass(frozen=True)
class TerrainBeautifyParams(GeneratorParams):
    """Conformal beautification parameters. warp_strength = Boundary warp magnitude (pixels)."""
    warp_strength: float = 6.0


class TerrainBeautifyGenerator:
    """Conformal Beautification — The third generator for route C."""

    id = "terrain_beautify"
    target_layer = "terrain_map"

    def default_params(self) -> TerrainBeautifyParams:
        return TerrainBeautifyParams()

    def generate(self, map_data, params: TerrainBeautifyParams,
                 mask: np.ndarray | None = None) -> np.ndarray:
        out = beautify_terrain(
            map_data.terrain_map, map_data.tile_map, map_data.height_map,
            seed=params.seed, warp_strength=params.warp_strength,
        )
        if mask is not None:
            out = np.where(mask, out, map_data.terrain_map)
        return out.astype(np.uint8)


def beautify_terrain(
    terrain_map: np.ndarray,
    tile_map: np.ndarray,
    height_map: np.ndarray,
    seed: int = 0,
    warp_strength: float = 6.0,
) -> np.ndarray:
    """Conformal beautification, returns new terrain_map (H, W) uint8."""
    h, w = terrain_map.shape
    rng = np.random.default_rng(seed)
    land = tile_map == TILE_LAND

    # ── 1. Domain distortion: Naturalization of boundaries (only sampling within the land, the coastline remains unchanged) ──
    def _smooth(sigma: float) -> np.ndarray:
        f = gaussian_filter(rng.standard_normal((h, w)).astype(np.float32), sigma)
        return f / max(float(np.abs(f).max()), 1e-6)

    dy = (_smooth(9.0) * warp_strength).round().astype(np.int32)
    dx = (_smooth(9.0) * warp_strength).round().astype(np.int32)
    yy, xx = np.mgrid[0:h, 0:w]
    sy = np.clip(yy + dy, 0, h - 1)
    sx = np.clip(xx + dx, 0, w - 1)
    warped = terrain_map[sy, sx]
    # The three types of pixels do not participate in distortion and are retained as they are:
    # 1) Itself is water / the sampling source is water - the coastline and lakeshore are sacred
    # 2) The self or the sampling source is a city/swamp - points explicitly placed by the author cannot be
    # It cannot be twisted in (the edges are chewed off by neighbors) nor can it be twisted out (smeared around)
    src_is_land = land[sy, sx]
    orig_protected = np.isin(terrain_map, [IDX_URBAN, IDX_MARSH])
    src_protected = orig_protected[sy, sx]
    warp_ok = land & src_is_land & ~orig_protected & ~src_protected
    base = np.where(warp_ok, warped, terrain_map).astype(np.uint8)

    # ── 2. Intra-block hybrid variant (according to the actual measured proportions of the original version) ──
    variant_low = _smooth(55.0)
    variant_fine = _smooth(2.5)
    variant_noise = variant_low * 0.7 + variant_fine * 0.3   # Fine grain aligned original patch density

    # Which family the current pixel belongs to (by palette index → provincial type)
    fam_lut = np.full(256, "", dtype=object)
    for idx, t in PALETTE_TO_TYPE.items():
        fam_lut[idx] = t
    families = fam_lut[base]

    out = base.copy()
    for fam, (variants, fracs) in _FAMILY_MIX.items():
        fam_mask = (families == fam) & land
        if not bool(fam_mask.any()):
            continue
        thresholds = _quantile_thresholds(variant_noise, fracs)
        sel = out[fam_mask]
        noise_vals = variant_noise[fam_mask]
        sel[:] = variants[0]
        for t, var_idx in zip(thresholds, variants[1:]):
            sel[noise_vals > t] = var_idx
        out[fam_mask] = sel

    # ── 3. Altitude superposition (the city/swamp is immobile — that is the author’s clear design) ──
    # The original image (orig_protected) is used for protection judgment, which is the same as the distortion stage.
    hf = height_map.astype(np.float32) - float(SEA_LEVEL)
    overlay_ok = land & ~orig_protected

    is_desert_fam = (families == "desert")
    hills = overlay_ok & (hf >= HILL_START) & (hf < MOUNTAIN_START)
    out[hills & is_desert_fam] = IDX_DESERT_HILLS

    mountains = overlay_ok & (hf >= MOUNTAIN_START)
    q_m1, q_m2 = _quantile_thresholds(variant_noise, [0.42, 0.76])
    out[mountains] = IDX_MOUNTAIN
    out[mountains & (variant_noise > q_m1)] = IDX_MOUNTAIN_GRASS
    out[mountains & (variant_noise > q_m2)] = IDX_MOUNTAIN_VAR
    out[mountains & is_desert_fam] = IDX_DESERT_MOUNTAIN

    out[overlay_ok & (hf >= SNOW_PEAK_START)] = IDX_SNOW_MOUNTAIN

    # ── 4. Forced restoration of water bodies ──
    out[tile_map == TILE_LAKE] = IDX_LAKES
    out[~land & (tile_map != TILE_LAKE)] = IDX_OCEAN
    return out.astype(np.uint8)
