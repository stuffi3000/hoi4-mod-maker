"""map/terrain/colormap_rgb_cityemissivemask_a.dds generated.

When HOI4 zooms out to the strategic perspective, the engine uses this 2816x1024 DDS as the "Global Overview" background texture.
The vanilla file depicts the Earth's continents (North America/Europe/Africa), which are not covered by the overhead MOD → the user can see the Earth when zooming out.

Format: DDS, 2816x1024, uncompressed BGRA8, 128 byte header.
RGB channel stores color, Alpha channel stores city night light mask (0 = no lights, 255 = bright city).
The light mask is automatically lit from urban terrain (+ halo), and the alpha is all 0 when there is no urban terrain.

Generation logic: downsample the tile_map from 5632x2048 to 2816x1024, and paint the land with earth color / the ocean with dark blue."""

from __future__ import annotations

import os

import numpy as np

from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
from domain.dds_format import build_bgra8_header

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


def _resolve_profile_arg(profile=None, game_profile=None):
    """Prefer an explicit profile, fall back to the game_profile alias."""
    return profile if profile is not None else game_profile


def _dds_contract_for(rel_path, profile):
    """Return the profile DDS contract entry for rel_path, or None."""
    if profile is None:
        return None
    try:
        norm = str(rel_path or "").replace("\\", "/")
    except (TypeError, ValueError):
        return None
    try:
        dds_map = getattr(profile, "dds", None)
    except (AttributeError, TypeError, ValueError):
        return None
    if not isinstance(dds_map, dict):
        return None
    try:
        return dds_map.get(norm)
    except (TypeError, ValueError):
        return None


def _contract_mip_count(contract, default=1):
    if isinstance(contract, dict):
        raw = None
        for key in ("mip_count", "mips", "mipmaps", "mip_levels", "mipmap_count"):
            try:
                if key in contract:
                    raw = contract[key]
                    break
            except (TypeError, ValueError):
                continue
    else:
        raw = None
        for key in ("mip_count", "mips", "mipmaps", "mip_levels", "mipmap_count"):
            try:
                candidate = getattr(contract, key, None)
            except (AttributeError, TypeError, ValueError):
                continue
            if candidate is not None:
                raw = candidate
                break
    try:
        if isinstance(raw, bool):
            raise ValueError("bool is not a mip count")
        count = int(raw)
    except (TypeError, ValueError):
        return int(default)
    return count if count > 0 else int(default)


def _write_bgra8_file(path, pixels_bgra):
    from domain.dds_format import build_bgra8_header
    pixels = np.ascontiguousarray(pixels_bgra, dtype=np.uint8)
    height = int(pixels.shape[0])
    width = int(pixels.shape[1])
    with open(path, "wb") as handle:
        handle.write(build_bgra8_header(width, height))
        handle.write(pixels.tobytes())


def _write_pixels_for_contract(rel_path, full_path, pixels_bgra, profile):
    """Write BGRA pixels as BGRA8 or profile-contract DXT5.

    Legacy callers without a profile (or without a contract entry) keep
    emitting uncompressed BGRA8. A BGRA8 contract also emits BGRA8. A
    BC3/DXT5 contract emits deterministic header-plus-mip-chain bytes via
    the bundled encoder. Any other contracted format raises ValueError so
    callers fail loudly instead of emitting mislabeled bytes.
    """
    from domain import dds_format as dds
    contract = _dds_contract_for(rel_path, profile)
    pixels = np.ascontiguousarray(pixels_bgra, dtype=np.uint8)
    if contract is None or profile is None:
        return _write_bgra8_file(full_path, pixels)
    if isinstance(contract, dict):
        raw_four = None
        for key in ("four_cc", "fourcc", "format", "pixel_format"):
            try:
                if key in contract:
                    raw_four = contract[key]
                    break
            except (TypeError, ValueError):
                continue
    else:
        raw_four = None
        for key in ("four_cc", "fourcc", "format", "pixel_format"):
            try:
                candidate = getattr(contract, key, None)
            except (AttributeError, TypeError, ValueError):
                continue
            if candidate:
                raw_four = candidate
                break
    four_cc = dds.normalize_fourcc(raw_four)
    if not four_cc or four_cc == "BGRA8":
        return _write_bgra8_file(full_path, pixels)
    if four_cc == "DXT5":
        mip_count = _contract_mip_count(contract, default=1)
        data = dds.encode_dxt5_dds(pixels, mip_count=mip_count, order="BGRA")
        with open(full_path, "wb") as handle:
            handle.write(data)
        return None
    raise ValueError(
        "profile contract for %r requires %s, which the bundled writers "
        "cannot emit" % (rel_path, four_cc or "an unknown format")
    )

def _build_dds_header(width: int, height: int) -> bytes:
    """Construct 128-byte DDS file header (uncompressed BGRA8, single mipmap)."""
    return build_bgra8_header(width, height)


def write_water_colormap_dds(
    tile_map: np.ndarray,
    output_dir: str,
    profile=None,
    game_profile=None,
) -> None:
    """Generate map/terrain/colormap_water_0/1/2.dds — ocean colors, three MIP levels.

    The gradient formula is in domain/water_colormap (same as previewing the sea surface):
    < 80px from land, green → dark blue, pure dark blue in the far sea."""
    try:
        from domain.water_colormap import water_color_rgb
        rgb = water_color_rgb(tile_map)
    except ImportError:
        # No scipy returns solid color
        return _write_water_colormap_solid(tile_map, output_dir, profile=profile, game_profile=game_profile)

    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    full_pixels = np.empty((*tile_map.shape, 4), dtype=np.uint8)
    full_pixels[..., 0] = rgb[..., 2]   # B
    full_pixels[..., 1] = rgb[..., 1]   # G
    full_pixels[..., 2] = rgb[..., 0]   # R
    full_pixels[..., 3] = 255

    out_dir = os.path.join(output_dir, "map", "terrain")
    os.makedirs(out_dir, exist_ok=True)

    active_profile = _resolve_profile_arg(profile, game_profile)
    src_h, src_w = tile_map.shape
    for level, divisor in enumerate([2, 4, 8]):
        dds_w = src_w // divisor
        dds_h = src_h // divisor
        if dds_w < 1 or dds_h < 1:
            break
        ds = full_pixels[::divisor, ::divisor][:dds_h, :dds_w]
        rel_path = "map/terrain/colormap_water_%d.dds" % level
        _write_pixels_for_contract(
            rel_path, os.path.join(out_dir, "colormap_water_%d.dds" % level),
            np.ascontiguousarray(ds), active_profile,
        )


def _write_water_colormap_solid(tile_map, output_dir, profile=None, game_profile=None):
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
        rel_path = "map/terrain/colormap_water_%d.dds" % level
        _write_pixels_for_contract(
            rel_path, os.path.join(out_dir, "colormap_water_%d.dds" % level),
            np.ascontiguousarray(pixels),
            _resolve_profile_arg(profile, game_profile),
        )


def write_fow_dds(
    tile_map: np.ndarray,
    output_dir: str,
    height_map: np.ndarray | None = None,
    profile=None,
    game_profile=None,
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
    _write_pixels_for_contract(
        "map/terrain/fow_rgb_waterspec_a.dds",
        os.path.join(out_dir, "fow_rgb_waterspec_a.dds"),
        np.ascontiguousarray(pixels),
        _resolve_profile_arg(profile, game_profile),
    )


def write_colormap_dds(
    tile_map: np.ndarray,
    output_dir: str,
    settings=None,
    terrain_map: np.ndarray | None = None,
    height_map: np.ndarray | None = None,
    profile=None,
    game_profile=None,
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


# M6.5 inspectable DDS strategy helpers. Legacy calls without a profile
# emit honestly labeled uncompressed BGRA8 and never claim DXT5/BC3; when a
# profile with a BC3/DXT5 contract is passed, water and fog writers emit
# deterministic encoder bytes. These helpers expose the profile strategy
# behind each overview asset for the planner, the manifest, and tests.


def strategy_for_dds_output(rel_path, tile_map, profile=None,
                            map_width=None, map_height=None):
    """Return the inspectable DdsStrategy for one overview DDS asset.

    Map dimensions default to the tile_map shape. The strategy carries
    the expected FourCC, dimensions, mip policy, DX10 flag, encoder
    capability, and provenance; see domain.dds_format.
    """
    from domain import dds_format as dds

    if map_width is None or map_height is None:
        try:
            map_height = int(tile_map.shape[0])
            map_width = int(tile_map.shape[1])
        except (AttributeError, TypeError, ValueError, IndexError):
            map_width = None
            map_height = None
    return dds.strategy_for_asset(rel_path, profile, map_width, map_height)


def _would_be_dds_size(rel_path, map_width, map_height):
    norm = str(rel_path or "").replace("\\", "/")
    try:
        map_width = int(map_width)
        map_height = int(map_height)
    except (TypeError, ValueError):
        return None
    if norm.endswith("colormap_water_1.dds"):
        return (map_width // 4, map_height // 4)
    if norm.endswith("colormap_water_2.dds"):
        return (map_width // 8, map_height // 8)
    return (map_width // 2, map_height // 2)


def generated_dds_satisfies_contract(rel_path, tile_map, profile=None):
    """Check whether profile-aware writer output would satisfy a contract.

    Legacy calls without a profile always satisfy the legacy BGRA8 bytes.
    BGRA8 contracts are satisfied when the writers emit the contracted
    dimensions. BC3/DXT5 water and fog contracts are satisfied by the
    bundled deterministic encoder at the contracted dimensions and mip
    policy (one mip per water file, the contracted chain for fog).
    Unsupported formats return False so the planner blocks or preserves
    instead of mislabeling bytes.
    """
    strategy = strategy_for_dds_output(rel_path, tile_map, profile)
    if strategy.requirement != "profile-contract":
        return (True, "no profile DDS contract; legacy BGRA8 output applies")
    if not strategy.can_generate:
        return (
            False,
            "profile requires %s, which the bundled writers cannot emit; "
            "output must be blocked or preserved, never mislabeled"
            % (strategy.four_cc or "an unsupported format"),
        )
    try:
        map_height = int(tile_map.shape[0])
        map_width = int(tile_map.shape[1])
    except (AttributeError, TypeError, ValueError, IndexError):
        return (False, "tile_map shape is unusable; dimensions are unknown")
    would_be = _would_be_dds_size(rel_path, map_width, map_height)
    expected = (strategy.expected_width, strategy.expected_height)
    if would_be is not None and expected[0] is not None and tuple(would_be) != tuple(expected):
        return (
            False,
            "writers emit %dx%d but the profile expects %sx%s"
            % (would_be[0], would_be[1], expected[0], expected[1]),
        )
    if strategy.has_dx10_header:
        return (
            False,
            "the selected profile requires a DX10 DDS header, but the "
            "bundled writers emit legacy 128-byte headers",
        )
    expected_mips = int(strategy.mip_count or 1)
    emitted_mips = expected_mips if strategy.four_cc == "DXT5" else 1
    if expected_mips != emitted_mips:
        return (
            False,
            "writers emit %d mip level(s) but the profile expects %d"
            % (emitted_mips, expected_mips),
        )
    if strategy.four_cc == "DXT5":
        return (
            True,
            "writers emit deterministic BC3/DXT5 at the contracted dimensions and mip policy",
        )
    return (
        True,
        "writers emit BGRA8 at the contracted dimensions and mip policy",
    )


def read_dds_header_info(path_or_bytes):
    """Parse emitted DDS bytes or files into inspectable header fields."""
    from domain.dds_format import parse_dds_header

    if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
        return parse_dds_header(bytes(path_or_bytes))
    with open(path_or_bytes, "rb") as handle:
        return parse_dds_header(handle.read())
