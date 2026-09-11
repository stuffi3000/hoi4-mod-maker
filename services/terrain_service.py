"""Terrain/elevation automatic generation service.

Automatically generate terrain_map and height_map from tile_map (land/sea/lake).
smart_auto_terrain: Smart terrain generation based on heightmap + Perlin noise."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT,
    TILE_LAND, TILE_LAKE, TILE_SEA,
    OCEAN_HEIGHT, LAND_BASE_HEIGHT, SEA_LEVEL,
)
from data.terrain_types import (
    DEFAULT_TERRAIN_FOR_TILE, TERRAIN_PALETTE_INDEX,
    PAINTABLE_GROUPS,
)


def auto_terrain(tile_map: np.ndarray) -> np.ndarray:
    """Generate terrain_map according to tile_map default rules (legacy simple map)."""
    terrain = np.zeros_like(tile_map, dtype=np.uint8)
    for tile_type, terrain_name in DEFAULT_TERRAIN_FOR_TILE.items():
        mask = tile_map == tile_type
        terrain[mask] = TERRAIN_PALETTE_INDEX[terrain_name]
    return terrain


# ── Intelligent terrain generation ──────────────────────────────────────

@dataclass(frozen=True)
class TerrainGenConfig:
    """Intelligent terrain generation parameters — UI exposed to user adjustment."""
    # Height threshold (corresponding to heightmap 0-255)
    plains_max: int = 115       # Below → plains/forests
    hills_min: int = 130        # above this → hills
    mountain_min: int = 165     # above this → mountainous
    snow_min: int = 210         # Above This → Snow Mountain

    # Forest: Part of the plain area becomes forest
    forest_noise_threshold: float = 0.1   # noise > this value → forest (the lower the value, the more forest)

    # Desert: latitude zone + low altitude
    desert_band_y_min: float = 0.20   # Upper latitude bound (map y scale)
    desert_band_y_max: float = 0.80   # latitude lower bound
    desert_noise_threshold: float = 0.15  # noise > this value → desert

    # Jungle: forested areas near the equator
    jungle_band_y_min: float = 0.35
    jungle_band_y_max: float = 0.65
    jungle_probability: float = 0.5   # Probability of equatorial forest turning into jungle

    # Noise parameters
    noise_scale: float = 80.0        # Boundary disturbance scale
    noise_amplitude: float = 20.0    # Height offset (pixels)
    scatter_scale: float = 12.0      # Scatter size (the smaller, the more fragmented)
    scatter_strength: float = 0.65   # Scatter threshold (lower means more spots)

    # Threshold overall shift (user controls "how many mountains")
    # -50 = All thresholds raised by 50 → more plains/hills, less mountains/snowy mountains
    # 0 = default
    # +50 = threshold lowered by 50 → mountainous snowy mountains
    threshold_offset: int = 0

    # seeds
    seed: int = 42


def smart_auto_terrain(
    height_map: np.ndarray,
    tile_map: np.ndarray,
    config: TerrainGenConfig | None = None,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Intelligent terrain generation based on heightmap + Perlin noise.

    Parameters
    ----------
    height_map: uint8 height map
    tile_map : uint8 tile type map (TILE_LAND/SEA/LAKE)
    config: Generate parameters, use default value when None
    mask: bool array, only generate areas where mask==True (for local reshaping)

    Returns
    -------
    terrain_map: uint8 terrain index map"""
    from domain.noise import perlin_2d

    if config is None:
        config = TerrainGenConfig()

    h, w = height_map.shape
    terrain = np.full((h, w), 15, dtype=np.uint8)  # Default ocean

    # 1. Generate noise layer (downsampling acceleration)
    ds = 4 if h > 1024 else 1
    boundary_noise = perlin_2d((h, w), scale=config.noise_scale,
                               octaves=4, seed=config.seed, downsample=ds)
    forest_noise = perlin_2d((h, w), scale=config.noise_scale * 0.7,
                             octaves=3, seed=config.seed + 100, downsample=ds)
    desert_noise = perlin_2d((h, w), scale=config.noise_scale * 0.6,
                             octaves=3, seed=config.seed + 200, downsample=ds)
    scatter_noise = perlin_2d((h, w), scale=config.scatter_scale,
                              octaves=2, seed=config.seed + 300, downsample=ds)
    variant_noise = perlin_2d((h, w), scale=config.scatter_scale * 2,
                              octaves=2, seed=config.seed + 400, downsample=ds)

    # 2. Perturbation height (Perlin offset makes the boundary organic)
    perturbed = height_map.astype(np.float32) + boundary_noise * config.noise_amplitude

    # 3. Basic layering
    # Key: land = tile_map==LAND and heightmap≥SEA_LEVEL (double judgment to avoid extending to the sea)
    # HOI4 looks at the heightmap in the game to determine whether it is sea or land, if tile_map and heightmap are inconsistent
    # (For example, tile_map=LAND but heightmap<95) will cause the terrain rendering to run into the sea
    land = (tile_map == TILE_LAND) & (height_map >= SEA_LEVEL)
    lake = tile_map == TILE_LAKE
    # sea = explicit sea or inconsistent pixels for "land but height < sea level"
    sea = (tile_map == TILE_SEA) | ((tile_map == TILE_LAND) & (height_map < SEA_LEVEL))

    # Threshold overall offset (user "mountain size" slider)
    # offset > 0 → lower the threshold → more mountains; offset < 0 → raise the threshold → fewer mountains
    off = int(config.threshold_offset)
    plains_max_eff = config.plains_max - off
    mountain_min_eff = config.mountain_min - off
    snow_min_eff = config.snow_min - off

    # Latitude parameter
    y_ratio = np.linspace(0, 1, h, dtype=np.float32)[:, None]  # (h, 1)

    # plain layer
    is_low = perturbed < plains_max_eff
    plains_mask = land & is_low

    # Forest: Noisier areas of the plains
    is_forest = plains_mask & (forest_noise > config.forest_noise_threshold)
    is_plains = plains_mask & ~is_forest

    # Jungle: forests near the equator
    in_jungle_band = (y_ratio >= config.jungle_band_y_min) & (y_ratio <= config.jungle_band_y_max)
    jungle_prob_mask = (variant_noise + 1) / 2 < config.jungle_probability  # Normalize to [0,1]
    is_jungle = is_forest & in_jungle_band & jungle_prob_mask
    is_forest = is_forest & ~is_jungle

    # Desert: non-equatorial, low altitude, noise matching
    in_desert_band = (y_ratio < config.desert_band_y_min) | (y_ratio > config.desert_band_y_max)
    is_desert = is_plains & in_desert_band & (desert_noise > config.desert_noise_threshold)
    is_plains = is_plains & ~is_desert

    # hilly layer
    is_mid = (perturbed >= plains_max_eff) & (perturbed < mountain_min_eff)
    is_hills = land & is_mid

    # mountain strata
    is_high = (perturbed >= mountain_min_eff) & (perturbed < snow_min_eff)
    is_mountain = land & is_high

    # snow mountain layer
    is_snow = land & (perturbed >= snow_min_eff)

    # Swamp: low elevation + specific noise areas (minor embellishments)
    is_marsh = is_plains & (scatter_noise > 0.7) & (perturbed < plains_max_eff - 10)
    is_plains = is_plains & ~is_marsh

    # 4. Assign basic palette index
    terrain[is_plains] = 0     # plains terrain_0
    terrain[is_forest] = 1     # forest terrain_1
    terrain[is_jungle] = 21    # jungle_18
    terrain[is_desert] = 3     # desert
    terrain[is_hills] = 17     # hills_blend
    terrain[is_mountain] = 6   # mountain terrain_6
    terrain[is_snow] = 16      # snow_16
    terrain[is_marsh] = 9      # marsh terrain_9
    terrain[lake] = 14         # lakes
    terrain[sea] = 15          # ocean

    # 5. Graphic variant dispersion (creating spot effects)
    _apply_variants(terrain, scatter_noise, variant_noise, config, land)

    # 6. Sea/Lake Protection (last step, make sure it is absolutely not covered)
    terrain[sea] = 15
    terrain[lake] = 14

    # 7. If there is a mask, only the mask area is returned
    if mask is not None:
        return terrain, mask

    return terrain


def _apply_variants(
    terrain: np.ndarray,
    scatter: np.ndarray,
    variant: np.ndarray,
    config: TerrainGenConfig,
    land: np.ndarray,
) -> None:
    """Sprinkle scattered dots of different graphic variations over a large area to create a natural spot effect."""
    threshold = config.scatter_strength

    # Forest area spread forest variant (index 4)
    forest_mask = (terrain == 1) & (scatter > threshold)
    terrain[forest_mask] = 4  # terrain_4 (forest variant)

    # Plains area spreading plains variant (index 5)
    plains_mask = (terrain == 0) & (scatter < -threshold)
    terrain[plains_mask] = 5  # terrain_5 (plains variant)

    # Spread variant in mountainous areas
    mt_mask = terrain == 6
    # Assign different mountain variants with variant_noise
    terrain[mt_mask & (variant > 0.3)] = 10   # terrain_10
    terrain[mt_mask & (variant > 0.5)] = 20   # mountain_variation_grass
    terrain[mt_mask & (variant < -0.3)] = 11  # desert_mountain_11

    # Desert area spread variant
    desert_mask = terrain == 3
    terrain[desert_mask & (scatter > threshold)] = 7    # terrain_7
    terrain[desert_mask & (scatter < -threshold)] = 12  # desert_12
    terrain[desert_mask & (variant > 0.4)] = 8          # desert_hills

    # Some of the hilly areas turned into desert hills.
    hills_mask = terrain == 17
    terrain[hills_mask & (variant < -0.5)] = 2   # desert_mountain (hills variant)

    # Jungle area spread variant
    jungle_mask = terrain == 21
    terrain[jungle_mask & (scatter > threshold)] = 22  # jungle_blend

    # Part of the snow mountain area turns into a grassland mountain
    snow_edge = (terrain == 16) & (variant > 0.3) & (scatter < 0)
    terrain[snow_edge] = 19  # plains_snow


@dataclass(frozen=True)
class HeightGenConfig:
    """Heightmap generation parameters."""
    # Base height (refer to the original version: coast ~97, inland plains ~120, mountains 200+)
    coast_height: int = 97      # Coastline base height (95 just above sea level)
    inland_max: int = 220       # The highest basic value inland (plus noise ±40 can reach 260, allowing high mountainous areas to reach snow_min=210 to become snowy mountains)
    # distance field
    distance_power: float = 0.35 # power of distance from coast
    distance_scale: float = 250.0 # Distance normalized scale (pixels)
    # Noise — making mountains and valleys
    noise_scale: float = 200.0   # Large-scale noise (mountain direction)
    noise_amplitude: float = 200.0 # Noise maximum height deviation (actual about ±100)
    detail_scale: float = 50.0   # Small scale noise (terrain details)
    detail_amplitude: float = 35.0
    # Smooth
    smooth_sigma: float = 3.0    # Final Gaussian smoothing (small values retain peaks)
    # seeds
    seed: int = 42


def smart_auto_height(
    tile_map: np.ndarray,
    config: HeightGenConfig | None = None,
) -> np.ndarray:
    """Intelligent height map generation: two-way distance field (gradient of land and sea) + Perlin noise mountains + smoothing.

    Old version bugs:
        1. The ocean is uniformly set to OCEAN_HEIGHT=40 → the coast is like a cliff
        2. Use power(dist, 0.35) for land. The coast rises instantly → the land side is also a cliff.
    New version:
        - Oceans also use distance fields: shallow sea 94 → deep sea 70 (gradually deeper)
        - Linear distance for land: Coast 97 → Inland 180 (slowly rising)
        - Noise is only added inland away from the coast and does not damage the beach area"""
    from scipy.ndimage import gaussian_filter, distance_transform_edt
    from domain.noise import perlin_2d

    if config is None:
        config = HeightGenConfig()

    h, w = tile_map.shape
    land = tile_map == TILE_LAND
    lake = tile_map == TILE_LAKE
    sea = (tile_map == TILE_SEA) | (tile_map == 0)

    # 1. Two-way distance field
    dist_to_sea = distance_transform_edt(~sea).astype(np.float32)   # Distance from land pixel to sea
    dist_to_land = distance_transform_edt(~land).astype(np.float32)  # Distance from ocean pixel to land

    hm = np.full((h, w), float(SEA_LEVEL), dtype=np.float32)

    # 2. Land foundation height: linear (no power required, avoid coastal cliffs)
    # Coast 97 → Inland 180 (peaks at about 250 pixels deep)
    max_dist = max(config.distance_scale, 1.0)
    land_height_factor = np.clip(dist_to_sea / max_dist, 0, 1)
    hm[land] = config.coast_height + land_height_factor[land] * (config.inland_max - config.coast_height)

    # 3. Ocean base height: shallow sea 94 → deep sea 70 (coefficient 0.8/pixel, capped at -25)
    hm[sea] = SEA_LEVEL - np.clip(dist_to_land[sea] * 0.8, 1, 25)

    # 4. Perlin noise superposition - only added inland away from the coast (protected beach areas)
    ds = 4 if h > 1024 else 1
    mountain_noise = perlin_2d((h, w), scale=config.noise_scale,
                               octaves=4, seed=config.seed, downsample=ds)
    detail_noise = perlin_2d((h, w), scale=config.detail_scale,
                             octaves=3, seed=config.seed + 500, downsample=ds)
    # The third layer: Alpine clusters (dense and sharp, only the parts above the threshold work, simulating real mountain chains)
    peaks_noise = perlin_2d((h, w), scale=80.0,
                            octaves=5, seed=config.seed + 777, downsample=ds)

    # Noise weight: Coast 0% → 100% after 5 pixels inland (protect coast gradient)
    noise_weight = np.clip((dist_to_sea - 5) / 10.0, 0, 1).astype(np.float32)
    hm[land] += (mountain_noise[land] * config.noise_amplitude
                 + detail_noise[land] * config.detail_amplitude) * noise_weight[land]

    # Peak clusters: only add mountains where peaks_noise > 0.3 (about 30% of the inland area forms a mountain chain)
    peak_threshold = 0.3
    peak_strength = 120.0  # For every +0.1 → +12 height above the threshold, add up to 84 (0.7→84)
    peak_bonus = np.maximum(peaks_noise - peak_threshold, 0) * peak_strength
    # Only works far away from the coast (≥20 pixels), keeping mountains away from the sea
    peak_mask = land & (dist_to_sea >= 20)
    hm[peak_mask] += peak_bonus[peak_mask]

    # 5. Slightly smooth (no peaks shaved)
    hm = gaussian_filter(hm, sigma=2.0)

    # 6. Mandatory constraints (keep the bottom line and ensure the correct determination of land and sea in HOI4)
    hm[lake] = SEA_LEVEL - 5
    hm[land] = np.maximum(hm[land], SEA_LEVEL + 1)  # Land at least 96
    hm[sea] = np.minimum(hm[sea], SEA_LEVEL - 1)    # sea at least 94

    # HOI4 requires the height of the top and bottom rows to be close to sea level
    hm[0, :] = np.minimum(hm[0, :], SEA_LEVEL)
    hm[-1, :] = np.minimum(hm[-1, :], SEA_LEVEL)

    return np.clip(hm, 30, 255).astype(np.uint8)


def apply_mountain_ridge(
    height_map: np.ndarray,
    tile_map: np.ndarray,
    points: list[tuple[int, int]],
    peak_height: int = 220,
    falloff_distance: float = 80.0,
    ridge_width: float = 5.0,
) -> np.ndarray:
    """Draws a mountain range along a given sequence of points on a height map.

    Algorithm (2026-06 upgraded to a real mountain chain, no longer a uniform "mound"):
    1. Generate ridgeline pixels along the lines connecting points → distance field
    2. Ridge profile: distance attenuation (slightly sharpened index, ridges have edges)
    3. Ups and downs along the ridge: The ridge-like fractal noise causes the main peak and pass to grow on a line
    4. Foothill texture: fractal details attenuate with the weight of the mountain, and the flat land is not polluted
    5. Take max with the original height (overlay rather than covering) + quantized jitter to prevent terrace pattern

    The seed is determined by the coordinates of the drawn line: by repeatedly adjusting the slider on the same line, the mountain shape remains stable.

    Parameters:
        height_map: (H, W) uint8, existing height map
        tile_map: (H, W) uint8, tile type
        points: [(y, x), ...] Point sequence through which the ridge line passes
        peak_height: peak height (0-255)
        falloff_distance: falloff distance (pixels)
        ridge_width: ridge width (pixels)"""
    from scipy.ndimage import distance_transform_edt
    from domain.generators.heightmap import _fbm

    if len(points) < 2:
        return height_map

    h, w = height_map.shape
    result = height_map.copy().astype(np.float32)
    land = tile_map == TILE_LAND

    # 1. Draw ridge lines on the binary map (connecting lines along points)
    ridge_mask = np.zeros((h, w), dtype=bool)
    for i in range(len(points) - 1):
        y0, x0 = points[i]
        y1, x1 = points[i + 1]
        _draw_line(ridge_mask, y0, x0, y1, x1, int(ridge_width))

    # 2. Distance to the ridgeline → mountain weight (0~1, slightly sharpened to make the ridge ridged)
    dist = distance_transform_edt(~ridge_mask).astype(np.float32)
    body = np.exp(-(dist / max(falloff_distance, 1.0)) ** 1.25)

    # 3. Ups and downs along the ridge: the same line seed is fixed, and the mountain shape does not jump when adjusting the slider
    seed = hash(tuple(map(tuple, points))) & 0xFFFF
    rng = np.random.default_rng(seed)
    ridged = 1.0 - np.abs(_fbm(rng, (h, w), ((36.0, 1.0), (18.0, 0.5))))
    profile = 0.55 + 0.45 * np.clip(ridged, 0.0, 1.0) ** 2  # Pass 0.55~main peak 1.0

    # 4. Foothills fractal texture (attenuates with the weight of the mountain)
    detail = _fbm(rng, (h, w), ((9.0, 1.0), (4.0, 0.5))) * 10.0 * body

    ridge_height = peak_height * body * profile + detail
    # Quantization jitter: Prevent integer step "terraces" from appearing on gentle slopes
    ridge_height += rng.uniform(-0.6, 0.6, ridge_height.shape).astype(np.float32)

    # 5. Only superimpose on land, take max
    result[land] = np.maximum(result[land], ridge_height[land])

    # mandatory constraints
    result[~land] = height_map[~land]  # Non-terrestrial remains unchanged
    result[land] = np.maximum(result[land], SEA_LEVEL + 1)

    return np.clip(result, 0, 255).astype(np.uint8)


def _regenerate_heightmap_region(
    height_map: np.ndarray,
    mask: np.ndarray,
    tile_map: np.ndarray,
    seed: int,
) -> np.ndarray:
    """The realistic terrain in the selected area is regenerated from scratch, and the edges are feathered to connect with the original image.

    Only run the generator on the mask bbox (+64px padding) piece, and the small selection will be completed in seconds;
    The blend weight is 0 at the selection boundary and rises smoothly to 1 inward—the boundary is continuous with no cliffs.
    Non-mask pixels are strictly equal to the original image (consistent with the refine_heightmap_region contract)."""
    from scipy.ndimage import gaussian_filter
    from domain.generators.heightmap import (
        generate_realistic_heightmap, HeightmapParams)

    ys, xs = np.where(mask)
    if ys.size == 0:
        return height_map.copy()
    h, w = height_map.shape
    pad = 64
    y0, y1 = max(int(ys.min()) - pad, 0), min(int(ys.max()) + pad + 1, h)
    x0, x1 = max(int(xs.min()) - pad, 0), min(int(xs.max()) + pad + 1, w)

    sub_tile = tile_map[y0:y1, x0:x1]
    sub_mask = mask[y0:y1, x0:x1]
    sub_old = height_map[y0:y1, x0:x1].astype(np.float32)

    fresh = generate_realistic_heightmap(
        sub_tile, HeightmapParams(seed=seed)).astype(np.float32)

    # Blending weights: selection border 0 → 8px inward then rising to 1 (gaussian(mask) at border≈0.5)
    weight = gaussian_filter(sub_mask.astype(np.float32), 8.0)
    weight = np.where(sub_mask, np.clip((weight - 0.5) * 2.0, 0.0, 1.0), 0.0)

    blended = sub_old * (1.0 - weight) + fresh * weight

    result = height_map.copy()
    sub_result = result[y0:y1, x0:x1]
    sub_result[sub_mask] = np.clip(
        blended[sub_mask], 0, 255).astype(np.uint8)
    return result


def _draw_line(mask: np.ndarray, y0: int, x0: int, y1: int, x1: int, width: int) -> None:
    """Bresenham Straight + Width Extension."""
    h, w = mask.shape
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    r = width // 2

    while True:
        # Draw circular strokes
        for dy2 in range(-r, r + 1):
            for dx2 in range(-r, r + 1):
                if dy2 * dy2 + dx2 * dx2 <= r * r:
                    ny, nx = y0 + dy2, x0 + dx2
                    if 0 <= ny < h and 0 <= nx < w:
                        mask[ny, nx] = True

        if y0 == y1 and x0 == x1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def auto_height(tile_map: np.ndarray) -> np.ndarray:
    """Automatically generate heightmap from tile_map (call smart version)."""
    return smart_auto_height(tile_map)


# Height parameters for each terrain:
# base = the lowest height of the terrain (edge of area)
# peak = the highest height of the terrain (center of the area, reached spread pixels from the boundary)
# spread = distance (pixels) required from base to peak, determines "how large an area is to form a peak"
# Design:
# - mountain peak=240 is close to the upper limit of 255. The center of large mountain blocks reaches the peak, while small blocks only reach the middle section.
# - hills ups and downs 120-170
# - plains/forest basically flat land, peak slightly higher
_HEIGHT_BY_TERRAIN: dict[str, dict[str, int]] = {
    # ocean: base is "shallow coastal sea" (high), peak is "abyss" (low) - distance from land determines depth
    # spread 100px → reaches the deepest point after 100px from the land. It will be very deep in the middle of the ocean, and shallower and transitional near the coast.
    "ocean":    {"base": 92,  "peak": 35,  "spread": 100},
    "lakes":    {"base": 92,  "peak": 87,  "spread": 5},
    "plains":   {"base": 96,  "peak": 120, "spread": 30},
    "desert":   {"base": 100, "peak": 125, "spread": 25},
    "forest":   {"base": 105, "peak": 140, "spread": 20},
    "jungle":   {"base": 105, "peak": 140, "spread": 20},
    "marsh":    {"base": 95,  "peak": 105, "spread": 10},
    "urban":    {"base": 100, "peak": 115, "spread": 10},
    "hills":    {"base": 135, "peak": 185, "spread": 18},  # Improve + shorten spread, small hills are also obvious
    "mountain": {"base": 155, "peak": 245, "spread": 30},  # base 155 (single pixel is also a real mountain), peak 245 is close to the limit
}


def _terrain_array_from_provincial(
    provincial_terrain: dict[int, str],
    province_map: np.ndarray,
    tile_map: np.ndarray | None = None,
) -> np.ndarray:
    """Synthesize province-level attributes (provincial_terrain dict) into a pixel-level terrain array.

    Provinces without provincial_terrain default according to tile_map: sea→ocean, lake→lakes, land→plains."""
    max_pid = int(province_map.max())
    plains_idx = TERRAIN_PALETTE_INDEX.get("plains", 0)
    ocean_idx = TERRAIN_PALETTE_INDEX.get("ocean", 15)
    lakes_idx = TERRAIN_PALETTE_INDEX.get("lakes", 14)

    # Calculate the default terrain for each pid by tile_map (majority rule: most pixels of this pid are sea? land? lake?)
    lut = np.full(max_pid + 1, plains_idx, dtype=np.uint8)
    if tile_map is not None:
        flat_pm = province_map.ravel()
        flat_tm = tile_map.ravel()
        n = max_pid + 1
        sea_count = np.bincount(flat_pm, weights=(flat_tm == TILE_SEA), minlength=n)
        lake_count = np.bincount(flat_pm, weights=(flat_tm == TILE_LAKE), minlength=n)
        total_count = np.bincount(flat_pm, minlength=n)
        # Most sea → ocean; most lake → lakes; otherwise plains
        is_sea = sea_count * 2 > total_count
        is_lake = lake_count * 2 > total_count
        lut[is_sea] = ocean_idx
        lut[is_lake] = lakes_idx

    # The user's provincial_terrain has the highest priority, overriding the default
    for pid, name in provincial_terrain.items():
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            continue
        if 0 < pid_int <= max_pid and name in TERRAIN_PALETTE_INDEX:
            lut[pid_int] = TERRAIN_PALETTE_INDEX[name]
    return lut[province_map]


def auto_height_from_terrain(
    terrain_map: np.ndarray,
    tile_map: np.ndarray,
    provincial_terrain: dict[int, str] | None = None,
    province_map: np.ndarray | None = None,
    smooth_sigma: float = 4.0,
) -> np.ndarray:
    """Deduce height_map from terrain (use distance field to fill the height interval of each terrain).

    Data source priority:
      1. provincial_terrain (province-level attribute, user’s real intention) — priority, HOI4 actually uses this judgment
      2. terrain_map (pixel-level decoration) — fallback, only when provincial_terrain is not provided

    Algorithm: For each terrain, calculate the "distance from the **boundary** of the terrain area" (distance_transform_edt).
        distance = 0 (area edge) → base height
        distance ≥ spread (depth within the region) → peak height
    → The center of the big mountain is 240 (mountain tip), the small hills only reach the middle section, and the plains are basically flat + slightly undulating.

    The height range is 60-240, and smooth_sigma controls the smoothness."""
    from scipy.ndimage import gaussian_filter, distance_transform_edt

    # Select data source
    if provincial_terrain and province_map is not None and provincial_terrain:
        terrain_arr = _terrain_array_from_provincial(
            provincial_terrain, province_map, tile_map=tile_map
        )
    else:
        terrain_arr = terrain_map

    h, w = terrain_arr.shape
    hm = np.full((h, w), float(SEA_LEVEL), dtype=np.float32)

    # 1. Each terrain: distance field → height
    for name, params in _HEIGHT_BY_TERRAIN.items():
        if name not in TERRAIN_PALETTE_INDEX:
            continue
        idx = TERRAIN_PALETTE_INDEX[name]
        mask = terrain_arr == idx
        if not mask.any():
            continue
        # The distance from the terrain pixel to the boundary of the terrain area (the closest distance to a non-terrain pixel)
        dist = distance_transform_edt(mask).astype(np.float32)
        spread = max(params["spread"], 1)
        # norm: 0 (edge) → 1 (depth, distance ≥ spread)
        norm = np.minimum(dist / spread, 1.0)
        base = float(params["base"])
        peak = float(params["peak"])
        hm[mask] = base + norm[mask] * (peak - base)

    # 2. Gaussian smoothing (eliminates steep changes in terrain boundaries, makes sigma smaller to retain mountain tops)
    hm = gaussian_filter(hm, sigma=smooth_sigma)

    # 3. Enforce land/sea/lake constraints
    land = tile_map == TILE_LAND
    sea = (tile_map == TILE_SEA) | (tile_map == 0)
    lake = tile_map == TILE_LAKE
    hm[land] = np.maximum(hm[land], SEA_LEVEL + 1)
    hm[sea] = np.minimum(hm[sea], SEA_LEVEL - 1)
    hm[lake] = SEA_LEVEL - 5

    # HOI4 top and bottom row boundaries
    hm[0, :] = np.minimum(hm[0, :], SEA_LEVEL)
    hm[-1, :] = np.minimum(hm[-1, :], SEA_LEVEL)

    return np.clip(hm, 30, 255).astype(np.uint8)


def smooth_height(
    height_map: np.ndarray,
    tile_map: np.ndarray | None = None,
    sigma: float = 4.0,
) -> np.ndarray:
    """Gaussian smoothed heightmap — Only land pixels are processed, sea/lake are kept at their original values.

    Implementation method: perform Gaussian blur on land_mask*height, and then divide it by the Gaussian blur of land_mask,
    Obtains a weighted average calculated using only land pixels (to avoid sea surface 0 values dragging down the coast height)."""
    from scipy.ndimage import gaussian_filter
    from data.constants import TILE_LAND

    if tile_map is None:
        hm = height_map.astype(np.float32)
        return np.clip(gaussian_filter(hm, sigma=sigma), 0, 255).astype(np.uint8)

    land_mask = (tile_map == TILE_LAND).astype(np.float32)
    hm_land = height_map.astype(np.float32) * land_mask
    blurred = gaussian_filter(hm_land, sigma=sigma)
    weight = gaussian_filter(land_mask, sigma=sigma)
    out = height_map.astype(np.float32).copy()
    valid = (tile_map == TILE_LAND) & (weight > 1e-6)
    out[valid] = blurred[valid] / weight[valid]
    return np.clip(out, 0, 255).astype(np.uint8)


def compute_provincial_terrain_from_bmp(
    terrain_map: np.ndarray,
    province_map: np.ndarray,
    tile_map: np.ndarray,
) -> dict[int, str]:
    """The provincial_terrain dict is inferred from terrain.bmp by per-province majority terrain.

    Used for: After the terrain is automatically generated, the dict attribute layer is updated accordingly (one-way synchronization: Vision → Attributes).

    Algorithm:
    1. Find the "real land province": the number of LAND pixels in this province > the number of SEA+LAKE pixels
    2. For these land provinces, count terrain_map most of the terrain → write into dict
    3. Ocean/lake province is never written into dict (to avoid accidentally changing the ocean attribute to land attribute)"""
    from data.terrain_types import PALETTE_TO_TYPE

    flat_pid = province_map.ravel()
    flat_tile = tile_map.ravel()
    flat_ter = terrain_map.ravel()

    max_pid = int(province_map.max())
    if max_pid <= 0:
        return {}

    # Step 1: Count the number of LAND / SEA+LAKE pixels in each province
    land_pixel_mask = flat_tile == TILE_LAND
    non_land_pixel_mask = (flat_tile == TILE_SEA) | (flat_tile == TILE_LAKE)

    land_counts = np.bincount(
        flat_pid[land_pixel_mask], minlength=max_pid + 1
    )
    non_land_counts = np.bincount(
        flat_pid[non_land_pixel_mask], minlength=max_pid + 1
    )

    # Real land province: LAND has strictly more pixels than sea/lake pixels
    is_land_province = land_counts > non_land_counts
    is_land_province[0] = False  # province 0 never counts
    land_pids = set(np.where(is_land_province)[0].tolist())

    if not land_pids:
        return {}

    # Step 2: Only count terrain_map most terrains for land province
    # Filter: only look at LAND pixels in land province (not look at SEA pixels on the border)
    valid_mask = land_pixel_mask & np.isin(flat_pid, list(land_pids))
    valid_pid = flat_pid[valid_mask].astype(np.int64)
    valid_ter = flat_ter[valid_mask].astype(np.int64)

    if len(valid_pid) == 0:
        return {}

    keys = valid_pid * 256 + valid_ter
    unique, counts = np.unique(keys, return_counts=True)

    best: dict[int, tuple[int, int]] = {}
    for k, c in zip(unique, counts):
        pid = int(k // 256)
        terr = int(k % 256)
        cnt = int(c)
        if pid not in best or cnt > best[pid][0]:
            best[pid] = (cnt, terr)

    # Step 3: Convert to provincial type name
    result: dict[int, str] = {}
    for pid, (_, terr_idx) in best.items():
        ptype = PALETTE_TO_TYPE.get(terr_idx)
        # Ocean/lake terrain is not included (double protection, even if the ocean index is mixed in the pixel, it will be skipped)
        if ptype and ptype not in ("ocean", "lakes"):
            result[pid] = ptype

    return result


# ── Partially refined height map ────────────────────────────────────────

FEATHER_RADIUS = 20  # Border feather pixel width


def refine_heightmap_region(
    height_map: np.ndarray,
    mask: np.ndarray,
    tile_map: np.ndarray,
    strength: float = 0.5,
    enable_ridge: bool = True,
    enable_erosion: bool = True,
    enable_noise: bool = False,
    enable_shrink: bool = False,
    shrink_distance: float = 25.0,
    seed: int = 42,
    regenerate: bool = False,
) -> np.ndarray:
    """Locally refined height map.

    Based on the height_map drawn by the user, overlay ridges/erosion/noise/shrinkage in the mask selection.
    Keep the user's intention (which one is higher and which one is lower) and just add decorations to it; or tighten the mountains that are drawn too big.
    Borders FEATHER_RADIUS Feather pixels to avoid hard edges.

    All calculations are only performed within the mask bbox (+padding), supporting 5632×2048 large images and small selections without lag.

    Parameters:
        height_map: (H, W) uint8, original height map
        mask: (H, W) bool, selection
        tile_map: (H, W) uint8, land/sea/lake determination (only handles land)
        strength: 0..1, refined strength
        enable_ridge: ridge sharpening
        enable_erosion: Erosion Gully
        enable_noise: highly correlated noise
        enable_shrink: Shrink the shape of the mountains (pull down the edges of the mountains that are drawn larger)
        shrink_distance: shrinkage effect distance (pixels), the larger the shrinkage, the more severe the shrinkage
        seed: random seed
        regenerate: True = Ignore the refinement switch and regenerate the realistic terrain in the selection from scratch
                    (Mountain chain/plain/continental shelf), edge feathering connects the original image

    Return:
        (H, W) uint8 New height map. Non-mask area === Enter the original image."""
    from scipy.ndimage import distance_transform_edt, gaussian_filter, maximum_filter

    if regenerate:
        return _regenerate_heightmap_region(height_map, mask, tile_map, seed)

    result = height_map.copy()

    # Ocean pixels within mask: seafloor unconditionally reconstructed as continental shelf slope.
    # The seabed is not a creative content (there is no hand-drawn seabed by the author), it is a mess of data left behind on the seabed.
    # Taken over directly by the algorithm - contrary to and complementary to the "conformal" principle of land.
    sea_in_mask = mask & (tile_map != TILE_LAND)
    if bool(sea_in_mask.any()):
        from domain.generators.heightmap import rebuild_sea_floor
        rebuilt = rebuild_sea_floor(height_map, tile_map)
        result[sea_in_mask] = rebuilt[sea_in_mask]

    if strength <= 0 or not (
        enable_ridge or enable_erosion or enable_noise or enable_shrink
    ):
        return result

    strength = float(np.clip(strength, 0.0, 1.0))
    land_mask = tile_map == TILE_LAND
    work_mask_full = mask & land_mask
    if not np.any(work_mask_full):
        return result

    # —— Calculated only within the bbox of mask (with padding for feathering + neighborhood operator) ——
    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    H, W = height_map.shape
    pad = FEATHER_RADIUS + 6  # Feathering distance + neighborhood operator footprint
    y0 = max(0, y0 - pad); y1 = min(H, y1 + pad)
    x0 = max(0, x0 - pad); x1 = min(W, x1 + pad)

    mask_sub = mask[y0:y1, x0:x1]
    land_sub = land_mask[y0:y1, x0:x1]
    work_sub = work_mask_full[y0:y1, x0:x1]
    hm_sub = result[y0:y1, x0:x1].astype(np.float32)

    # 1) Feathering weight
    dist_in = distance_transform_edt(mask_sub).astype(np.float32)
    feather = np.minimum(dist_in / FEATHER_RADIUS, 1.0)
    w = feather * strength

    # 2) Ridge sharpening
    if enable_ridge:
        local_max = maximum_filter(hm_sub, size=5)
        ridge_pix = (hm_sub == local_max) & (hm_sub > SEA_LEVEL + 20) & land_sub
        ridge_boost = gaussian_filter(
            ridge_pix.astype(np.float32) * 15.0, sigma=2.0
        )
        hm_sub = hm_sub + ridge_boost * w

    # 3) Erosion gullies
    if enable_erosion:
        erosion = _simulate_erosion(hm_sub, work_sub, seed=seed, iterations=30)
        hm_sub = hm_sub - erosion * w * 10.0

    # 4) Highly correlated noise
    if enable_noise:
        rng = np.random.default_rng(seed)
        noise = rng.standard_normal(hm_sub.shape).astype(np.float32) * 4.0
        noise = gaussian_filter(noise, sigma=1.5)
        height_factor = np.clip((hm_sub - SEA_LEVEL) / 100.0, 0.0, 1.0)
        hm_sub = hm_sub + noise * height_factor * w

    # 5) Shrink the shape of the mountains (pull the edges of the enlarged mountains toward the sea level)
    if enable_shrink:
        # Find "high ground": > SEA_LEVEL+30 and land
        high_mask = (hm_sub > SEA_LEVEL + 30) & land_sub
        # Do a distance transform on "non-highlands" → the distance from each highland pixel to the nearest lowland
        # Those who are close are pulled down (the edge), while those who are far away (the center of the mountain) do not move.
        if np.any(high_mask) and np.any(~high_mask):
            dist_from_low = distance_transform_edt(high_mask).astype(np.float32)
            pull = np.clip(1.0 - dist_from_low / max(shrink_distance, 1.0), 0.0, 1.0)
            # Only works on highland pixels
            pull_effective = pull * high_mask.astype(np.float32) * w
            # Pull height towards SEA_LEVEL + 1
            hm_sub = hm_sub - (hm_sub - (SEA_LEVEL + 1)) * pull_effective

    # 6) Keep the bottom line (land cannot < SEA_LEVEL+1 to avoid land turning into sea)
    clipped = np.clip(hm_sub, SEA_LEVEL + 1, 255)
    sub_result = result[y0:y1, x0:x1]
    sub_result[work_sub] = clipped[work_sub].astype(np.uint8)
    result[y0:y1, x0:x1] = sub_result
    return result


def _simulate_erosion(
    hm: np.ndarray,
    work_mask: np.ndarray,
    seed: int,
    iterations: int = 30,
) -> np.ndarray:
    """Minimalist hydraulic erosion: Walk N steps along the steepest downhill slope from a random starting point, accumulating erosion along the way.

    Returns a (H, W) float32 erosion map multiplied by the caller's weights and subtracted from hm.
    Erosion only occurs within work_mask."""
    h, w = hm.shape
    erosion = np.zeros_like(hm, dtype=np.float32)

    # Number of starting points: selection area × 0.005 (experience value, enough to produce the effect without exploding)
    area = int(work_mask.sum())
    n_starts = max(20, min(area // 200, 5000))

    rng = np.random.default_rng(seed)
    ys_all, xs_all = np.where(work_mask)
    if len(ys_all) == 0:
        return erosion
    idx = rng.integers(0, len(ys_all), size=n_starts)
    start_ys = ys_all[idx]
    start_xs = xs_all[idx]

    # 3x3 neighbor offset
    neighbors = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    ]

    for sy, sx in zip(start_ys, start_xs):
        y, x = int(sy), int(sx)
        for _ in range(iterations):
            if not (0 <= y < h and 0 <= x < w):
                break
            if not work_mask[y, x]:
                break
            # Find the lowest neighbor
            cur = hm[y, x]
            best_dy, best_dx = 0, 0
            best_h = cur
            for dy, dx in neighbors:
                ny, nx = y + dy, x + dx
                if not (0 <= ny < h and 0 <= nx < w):
                    continue
                if hm[ny, nx] < best_h:
                    best_h = hm[ny, nx]
                    best_dy, best_dx = dy, dx
            if best_dy == 0 and best_dx == 0:
                break  # Local minimum, stop
            erosion[y, x] += 0.1
            y += best_dy
            x += best_dx
            erosion[y, x] += 0.3

    # Slightly smoothed to avoid single pixel gullies
    from scipy.ndimage import gaussian_filter
    erosion = gaussian_filter(erosion, sigma=0.8)
    return erosion
