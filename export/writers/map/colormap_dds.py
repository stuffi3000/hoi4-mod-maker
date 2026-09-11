"""map/terrain/colormap_rgb_cityemissivemask_a.dds generated.

When HOI4 zooms out to the strategic perspective, the engine uses this 2816x1024 DDS as the "Global Overview" background texture.
The vanilla file depicts the Earth's continents (North America/Europe/Africa), which are not covered by the overhead MOD → the user can see the Earth when zooming out.

Format: DDS, 2816x1024, uncompressed BGRA8, 128 byte header.
RGB channel stores color, Alpha channel stores city night light mask (0 = no lights, 255 = bright city).
The light mask is automatically lit from urban terrain (+ halo), and the alpha is all 0 when there is no urban terrain.

Generation logic: downsample the tile_map from 5632x2048 to 2816x1024, and paint the land with earth color / the ocean with dark blue."""

from __future__ import annotations

import os
import struct

import numpy as np

from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE

# Do not solidify _DDS_WIDTH/_DDS_HEIGHT at the top of the module - that will bind to MAP_WIDTH at import time
# (5632), set_map_size will not be updated, causing the DDS file header to be inconsistent with the actual pixel size → corrupting the file.
# All dimensions are taken from tile_map.shape within the function.

# Default colors (B, G, R, A) — DDS byte order. Overridable by user via ColormapSettings.
_DEFAULT_COLOR_LAND = (60, 90, 95, 0)
_DEFAULT_COLOR_SEA  = (90, 55, 30, 0)
_DEFAULT_COLOR_LAKE = (140, 110, 70, 0)

# Strategic view colorization by terrain type (B, G, R, A) — Increase saturation to make patches of color more visible
_TERRAIN_TYPE_COLORS: dict[str, tuple[int, int, int, int]] = {
    "plains":   (60, 140, 110, 0),   # Bright grass green
    "forest":   (40, 95, 50, 0),     # deep forest green
    "hills":    (75, 130, 150, 0),   # Yellowish brown (increased saturation)
    "mountain": (110, 115, 120, 0),  # Taupe (brighter, with snow on the top of the mountain)
    "desert":   (80, 175, 215, 0),   # Sand yellow (increased saturation)
    "marsh":    (60, 100, 70, 0),    # Swamp dark green
    "jungle":   (30, 90, 45, 0),     # Jungle dark green
    "urban":    (90, 100, 110, 0),   # urban gray
    "ocean":    (90, 55, 30, 0),
    "lakes":    (180, 130, 80, 0),
}


def _build_dds_header(width: int, height: int) -> bytes:
    """Construct 128-byte DDS file header (uncompressed BGRA8, single mipmap)."""
    # Matches vanilla parameters: flags=0x100f, pitch=width*4, pf_flags=0x41 (ALPHAPIXELS|RGB)
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)           # dwSize
    struct.pack_into("<I", header, 8, 0x100f)        # dwFlags (CAPS+HEIGHT+WIDTH+PITCH+PIXELFORMAT)
    struct.pack_into("<I", header, 12, height)       # dwHeight
    struct.pack_into("<I", header, 16, width)        # dwWidth
    struct.pack_into("<I", header, 20, width * 4)    # dwPitchOrLinearSize
    struct.pack_into("<I", header, 24, 0)            # dwDepth
    struct.pack_into("<I", header, 28, 1)            # dwMipMapCount
    # dwReserved1[11] — 44 bytes 0
    # ddspf at offset 76
    struct.pack_into("<I", header, 76, 32)           # dwSize
    struct.pack_into("<I", header, 80, 0x41)         # dwFlags (ALPHAPIXELS | RGB)
    struct.pack_into("<I", header, 84, 0)            # dwFourCC
    struct.pack_into("<I", header, 88, 32)           # dwRGBBitCount
    struct.pack_into("<I", header, 92, 0x00FF0000)   # R mask
    struct.pack_into("<I", header, 96, 0x0000FF00)   # G mask
    struct.pack_into("<I", header, 100, 0x000000FF)  # B mask
    struct.pack_into("<I", header, 104, 0xFF000000)  # A mask
    struct.pack_into("<I", header, 108, 0x1000)      # dwCaps (TEXTURE)
    return bytes(header)


def write_water_colormap_dds(
    tile_map: np.ndarray,
    output_dir: str,
) -> None:
    """Generate map/terrain/colormap_water_0/1/2.dds — ocean colors, three MIP levels.

    The gradient formula is in domain/water_colormap (same as previewing the sea surface):
    < 80px from land, green → dark blue, pure dark blue in the far sea."""
    try:
        from domain.water_colormap import water_color_rgb
        rgb = water_color_rgb(tile_map)
    except ImportError:
        # No scipy returns solid color
        return _write_water_colormap_solid(tile_map, output_dir)

    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    full_pixels = np.empty((*tile_map.shape, 4), dtype=np.uint8)
    full_pixels[..., 0] = rgb[..., 2]   # B
    full_pixels[..., 1] = rgb[..., 1]   # G
    full_pixels[..., 2] = rgb[..., 0]   # R
    full_pixels[..., 3] = 255

    out_dir = os.path.join(output_dir, "map", "terrain")
    os.makedirs(out_dir, exist_ok=True)

    src_h, src_w = tile_map.shape
    for level, divisor in enumerate([2, 4, 8]):
        dds_w = src_w // divisor
        dds_h = src_h // divisor
        if dds_w < 1 or dds_h < 1:
            break
        ds = full_pixels[::divisor, ::divisor][:dds_h, :dds_w]
        header = _build_dds_header(dds_w, dds_h)
        with open(os.path.join(out_dir, f"colormap_water_{level}.dds"), "wb") as f:
            f.write(header)
            f.write(np.ascontiguousarray(ds).tobytes())


def _write_water_colormap_solid(tile_map, output_dir):
    """Fallback (solid color) when scipy is not available."""
    water_color = np.array([110, 70, 30, 255], dtype=np.uint8)
    out_dir = os.path.join(output_dir, "map", "terrain")
    os.makedirs(out_dir, exist_ok=True)
    src_h, src_w = tile_map.shape
    for level, divisor in enumerate([2, 4, 8]):
        dds_w = src_w // divisor
        dds_h = src_h // divisor
        if dds_w < 1 or dds_h < 1:
            break
        pixels = np.empty((dds_h, dds_w, 4), dtype=np.uint8)
        pixels[:] = water_color
        header = _build_dds_header(dds_w, dds_h)
        with open(os.path.join(out_dir, f"colormap_water_{level}.dds"), "wb") as f:
            f.write(header)
            f.write(pixels.tobytes())


def write_fow_dds(
    tile_map: np.ndarray,
    output_dir: str,
    height_map: np.ndarray | None = None,
) -> None:
    """Generate map/terrain/fow_rgb_waterspec_a.dds — fog of war shading + water reflection.

    Channel semantics (2026-07-10 decoding vanilla actual test, wiki no documentation):
    - RGB: Grayscale light and dark under fog, land bright (~150, getting brighter with height) / ocean dark (~64)
    - A: Water surface reflection intensity, sea ~46 / land ~21
    The size is half the size of provinces.bmp. Not overwriting will fall back to the vanilla earth shape map,
    The reflection and fog textures on the custom map follow the distribution of land and sea on the earth → misaligned."""
    ds = tile_map[::2, ::2]
    h, w = ds.shape
    sea = (ds == TILE_SEA) | (ds == 0)
    lake = ds == TILE_LAKE
    land = ~sea & ~lake

    gray = np.full((h, w), 64.0, dtype=np.float32)
    gray[lake] = 80.0
    if height_map is not None and height_map.shape == tile_map.shape:
        ds_height = height_map[::2, ::2].astype(np.float32)
        # Sea level (~95) near ~130, alpine ~185 — aligns with vanilla land 140~170 zone
        gray[land] = np.clip(130.0 + (ds_height[land] - 95.0) * 0.4, 120.0, 185.0)
    else:
        gray[land] = 150.0
    alpha = np.where(land, 21.0, 46.0).astype(np.float32)

    # Mild blur: natural transition to the coast (vanilla low-resolution hand-drawn without hard edges)
    try:
        from scipy.ndimage import gaussian_filter
        gray = gaussian_filter(gray, sigma=1.5)
        alpha = gaussian_filter(alpha, sigma=1.5)
    except ImportError:
        pass

    pixels = np.empty((h, w, 4), dtype=np.uint8)
    pixels[..., :3] = np.clip(gray, 0, 255).astype(np.uint8)[..., None]
    pixels[..., 3] = np.clip(alpha, 0, 255).astype(np.uint8)

    out_dir = os.path.join(output_dir, "map", "terrain")
    os.makedirs(out_dir, exist_ok=True)
    header = _build_dds_header(w, h)
    with open(os.path.join(out_dir, "fow_rgb_waterspec_a.dds"), "wb") as f:
        f.write(header)
        f.write(pixels.tobytes())


def write_colormap_dds(
    tile_map: np.ndarray,
    output_dir: str,
    settings=None,
    terrain_map: np.ndarray | None = None,
    height_map: np.ndarray | None = None,
) -> None:
    """Generate map/terrain/colormap_rgb_cityemissivemask_a.dds from tile_map + terrain_map.

    - tile_map: (MAP_HEIGHT, MAP_WIDTH) uint8, TILE_LAND/SEA/LAKE
    - terrain_map: (MAP_HEIGHT, MAP_WIDTH) uint8, optional, if available, color according to terrain
    - settings: ColormapSettings instance, None uses default color
    - Output: Downsampled BGRA8 DDS"""
    # No longer checks for consistency with global MAP_WIDTH/HEIGHT — use tile_map.shape as authoritative,
    # HOI4 only requires multiples of 256 and does not limit the default size.

    # Decide on three colors
    if settings is not None:
        color_land = settings.land.to_bgra()
        color_sea = settings.sea.to_bgra()
        color_lake = settings.lake.to_bgra()
    else:
        color_land = _DEFAULT_COLOR_LAND
        color_sea = _DEFAULT_COLOR_SEA
        color_lake = _DEFAULT_COLOR_LAKE

    downsampled = tile_map[::2, ::2]
    h, w = downsampled.shape
    pixels = np.empty((h, w, 4), dtype=np.uint8)
    pixels[:] = color_sea
    land_mask = downsampled == TILE_LAND
    lake_mask = downsampled == TILE_LAKE
    urban_mask = np.zeros((h, w), dtype=bool)  # For city lights (alpha channel)

    if terrain_map is not None and terrain_map.shape == tile_map.shape:
        # Color land by terrain type
        from data.terrain_types import PALETTE_TO_TYPE
        ds_terrain = terrain_map[::2, ::2]
        # Fill in the default land color first
        pixels[land_mask] = color_land
        # Then cover by terrain type
        for idx in np.unique(ds_terrain[land_mask]):
            ttype = PALETTE_TO_TYPE.get(int(idx))
            if ttype and ttype in _TERRAIN_TYPE_COLORS:
                tmask = land_mask & (ds_terrain == idx)
                pixels[tmask] = _TERRAIN_TYPE_COLORS[ttype]
                if ttype == "urban":
                    urban_mask |= tmask
    else:
        pixels[land_mask] = color_land

    pixels[lake_mask] = color_lake

    # ── Height modulation + snow mountain + coastal beach (only done with heightmap) ──
    if height_map is not None and height_map.shape == tile_map.shape:
        ds_height = height_map[::2, ::2].astype(np.float32)
        # 1. Snow Mountain: Height > 200 → Gradual White
        snow_t = np.clip((ds_height - 200) / 40.0, 0, 1)  # 200→0, 240→1
        snow_color = np.array([240, 240, 250], dtype=np.float32)
        # 2. High brightness: 100 (coast)=1.0, 200=1.25, 50=0.8 (dark valley)
        brightness = np.clip(0.7 + (ds_height - 95) / 200.0, 0.65, 1.35)
        rgb = pixels[..., :3].astype(np.float32)
        rgb = rgb * brightness[..., None]
        # snow mixed in
        rgb[land_mask] = (
            rgb[land_mask] * (1 - snow_t[land_mask, None])
            + snow_color * snow_t[land_mask, None]
        )
        pixels[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        # 3. Coastal beach: land < 4px from the sea → light yellow
        try:
            from scipy.ndimage import distance_transform_edt
            sea_full = (tile_map == TILE_SEA) | (tile_map == 0)
            dist_to_sea_full = distance_transform_edt(~sea_full).astype(np.float32)
            ds_dist = dist_to_sea_full[::2, ::2]
            beach_t = np.clip(1 - ds_dist / 4.0, 0, 1) * 0.6  # 60% sand within 4px
            beach = np.array([130, 200, 235], dtype=np.float32)  # BGR light sand color
            rgb = pixels[..., :3].astype(np.float32)
            mix = land_mask & (ds_dist < 4)
            rgb[mix] = rgb[mix] * (1 - beach_t[mix, None]) + beach * beach_t[mix, None]
            pixels[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        except ImportError:
            pass

    # ── Eliminate "collage" hard edges: add noise + gaussian blur to land ──
    # Why: vanilla colormap is hand-painted by an artist + noise, with thousands of colors;
    # We only have 7 solid colors according to the terrain type, and the atlas material is stacked on top of it to form a hard-edged block.
    # After adding noise + mild blur, there are gradient bands between adjacent terrains, and the "collage" is invisible to the naked eye.
    try:
        from scipy.ndimage import gaussian_filter
        rng = np.random.default_rng(42)
        # Only dither + blur the three channels of land BGR (alpha remains 0)
        rgb = pixels[..., :3].astype(np.float32)
        noise = rng.integers(-12, 13, size=rgb.shape, dtype=np.int16).astype(np.float32)
        rgb = rgb + noise
        for c in range(3):
            rgb[..., c] = gaussian_filter(rgb[..., c], sigma=2.5)
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        pixels[..., :3] = rgb
        # Blurring will cause the color to seep into the ocean/lake and cover it back to pure sea/lake color (the sea surface is also rendered by colormap_water)
        pixels[downsampled == TILE_SEA] = color_sea
        pixels[lake_mask] = color_lake
    except ImportError:
        pass  # Fallback to hard-edged version when scipy is not available

    # ── City night lights: alpha channel, urban terrain glow + blur halo ──
    # (wiki: "more opacity means stronger night lights"; Tile light texture
    # citylights_rgb_snowmask_a can use vanilla, the position is determined by this mask)
    alpha = np.zeros((h, w), dtype=np.float32)
    alpha[urban_mask] = 200.0
    if urban_mask.any():
        try:
            from scipy.ndimage import gaussian_filter
            # The city itself remains fully bright, and the halo takes the maximum value of the blur result (the small city is not dimmed by the blur)
            alpha = np.maximum(alpha, gaussian_filter(alpha, sigma=2.0))
        except ImportError:
            pass
    # Light stays only on land (blur will seep into the sea)
    alpha[~land_mask] = 0.0
    pixels[..., 3] = np.clip(alpha, 0, 255).astype(np.uint8)

    # write file
    out_dir = os.path.join(output_dir, "map", "terrain")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "colormap_rgb_cityemissivemask_a.dds")
    # Use dynamic dimensions — same as pixels (= downsampled.shape)
    header = _build_dds_header(w, h)
    with open(out_path, "wb") as f:
        f.write(header)
        f.write(pixels.tobytes())
