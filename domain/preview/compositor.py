"""Preview compositor — combines project data + original game textures into an "in-game look and feel" screen.

Layered overlay (all numpy vectorized, zero Qt):
1. Terrain material base: terrain_map palette index → atlas tile → tile sampling according to pixel coordinates
2. Height light and shadow: height map gradient algorithm line, and dot product of parallel light to obtain light and shade (approximate game shader)
3. Ocean/Lake: Shore gradient, the formula is the same as the exported colormap_water (domain/water_colormap)
4. River: River pixels are overlaid with river color

The material/mapping comes from the game body (services/game_assets), and the light and shadow formula is approximate——
The positioning is "enough to judge what the map looks like" and does not seek to be consistent with the game pixel by pixel."""

from __future__ import annotations

import numpy as np

from data.constants import TILE_LAND

# The color of the river (slightly brighter than the shallows, can only be seen clearly on land)
RIVER_RGB = np.array([60, 120, 190], dtype=np.float32)
# Indexes <= 11 in river_map are river data (254/255 are background)
RIVER_MAX_INDEX = 11

# Lighting: parallel light from the northwest + ambient light background (the light in the game also comes from the northwest)
LIGHT_DIR = (-0.5, -0.5, 1.0)
AMBIENT = 0.55       # Ambient light intensity (minimum brightness without light)
DIFFUSE = 0.65       # Diffuse reflection intensity (part affected by slope aspect)
# Steepness coefficient for converting height gradient to normal: The larger the mountain, the stronger the contrast between light and dark.
SLOPE_SCALE = 3.0


def _texture_lut(terrain_to_texture: dict[int, int], tile_count: int) -> np.ndarray:
    """Lookup table for palette index (0..255) → tile number.

    Undefined indexes and out-of-bounds tile numbers (e.g. texture=255 for lakes) fall back to
    Plain tiles (map with index 0, if not, use tile 0) - these pixels
    It will then be covered by a layer of water, and it doesn’t matter what kind of bottom it is laid on, as long as it doesn’t cross the boundary."""
    fallback = terrain_to_texture.get(0, 0)
    if not (0 <= fallback < tile_count):
        fallback = 0
    lut = np.full(256, fallback, dtype=np.int32)
    for palette_idx, tex in terrain_to_texture.items():
        if 0 <= palette_idx < 256 and 0 <= tex < tile_count:
            lut[palette_idx] = tex
    return lut


def _hillshade(height_map: np.ndarray) -> np.ndarray:
    """Heightmap → Luminance coefficients per pixel (H, W) float32, approximately [AMBIENT, AMBIENT+DIFFUSE]."""
    h = height_map.astype(np.float32)
    gy, gx = np.gradient(h)
    # normal ∝ (-gx*k, -gy*k, 1), normalized
    nx = -gx * SLOPE_SCALE
    ny = -gy * SLOPE_SCALE
    nz = np.ones_like(nx)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)

    lx, ly, lz = LIGHT_DIR
    lnorm = (lx * lx + ly * ly + lz * lz) ** 0.5
    dot = (nx * lx + ny * ly + nz * lz) / (norm * lnorm)
    return AMBIENT + DIFFUSE * np.clip(dot, 0.0, 1.0)


def compose_preview(
    tile_map: np.ndarray,
    terrain_map: np.ndarray,
    height_map: np.ndarray,
    river_map: np.ndarray | None,
    atlas_tiles: np.ndarray,
    terrain_to_texture: dict[int, int],
    tint: np.ndarray | None = None,
) -> np.ndarray:
    """Synthesize preview, return (H, W, 3) uint8.

    Parameters:
        tile_map: land/sea/lake classification (H, W) uint8
        terrain_map: graphics terrain palette index (H, W) uint8
        height_map: height map (H, W) uint8
        river_map: river map (H, W) uint8, None = do not draw rivers
        atlas_tiles: game material tiles (N, th, tw, 4) uint8 (game_assets.atlas_tiles)
        terrain_to_texture: palette index → tile number (game_assets.terrain_to_texture)
        tint: area tone map (H, W, 3) uint8, None = no tint.
              P company shader convention: material × hue × 2 (hue 128 is the original color)"""
    h, w = tile_map.shape
    tile_count, th, tw = atlas_tiles.shape[0], atlas_tiles.shape[1], atlas_tiles.shape[2]

    # ── 1. Terrain material base ──
    lut = _texture_lut(terrain_to_texture, tile_count)
    tex_idx = lut[terrain_map]                      # (H, W) Tile number per pixel
    ys = np.arange(h, dtype=np.int32) % th
    xs = np.arange(w, dtype=np.int32) % tw
    ty = np.broadcast_to(ys[:, None], (h, w))       # Coordinates within tiles (tiled sampling)
    tx = np.broadcast_to(xs[None, :], (h, w))
    base = atlas_tiles[tex_idx, ty, tx, :3].astype(np.float32)

    # ── 1.5 regional hue (origin of yellowish color in North Africa/greenish color in Western Europe) ──
    if tint is not None:
        base = base * (tint.astype(np.float32) / 255.0) * 2.0

    # ── 2. High light and shadow ──
    shade = _hillshade(height_map)
    rgb = base * shade[:, :, None]

    # ── 3. Ocean/Lake: The same gradient formula as the exported colormap_water ──
    # The color source of the sea surface in the game is that texture, and the preview directly uses the same offshore gradient → export as you see it.
    water = tile_map != TILE_LAND
    if np.any(water):
        from domain.water_colormap import water_color_rgb
        water_rgb = water_color_rgb(tile_map)
        rgb[water] = water_rgb[water]

    # ── 4. River coverage ──
    if river_map is not None:
        rivers = river_map <= RIVER_MAX_INDEX
        rgb[rivers] = RIVER_RGB

    return np.clip(rgb, 0, 255).astype(np.uint8)
