"""BMP file writer (M9.1 compatibility shims): generates BMP files strictly in the format required by HOI4"""
import struct
import os
import numpy as np

from data.constants import MAP_WIDTH, MAP_HEIGHT
from domain.generators.province import generate_province_colors


def write_provinces_bmp(
    province_map: np.ndarray,
    output_dir: str,
    colors: dict[int, tuple[int, int, int]] | None = None,
) -> dict[int, tuple[int, int, int]]:
    """Write province map to 24-bit BMP file.

    Format requirements:
    - Windows BITMAPINFOHEADER format
    - 24-bit RGB
    - Pixel data bottom-up (from bottom to top)
    - Each row requires 4 bytes of padding
    - No anti-aliasing

    Parameters:
        province_map: province ID array (H, W), int32
        output_dir: output directory
        colors: Province color map {ID: (R, G, B)}, automatically generated if None

    Return:
        The actual color map used"""
    province_count = int(province_map.max())
    if colors is None:
        colors = generate_province_colors(province_count)

    # Use actual array shape, cannot use global MAP_WIDTH/HEIGHT (user may choose other sizes such as 2048×1024)
    H, W = province_map.shape

    # Make sure the output directory exists
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    file_path = os.path.join(map_dir, "provinces.bmp")

    # Build pixel data
    # BMP 24-bit format: 3 bytes per pixel (B, G, R), note the BGR order
    row_bytes = W * 3
    # Requires 4-byte alignment per line
    padding = (4 - (row_bytes % 4)) % 4
    padded_row_bytes = row_bytes + padding

    # Pixel data size
    pixel_data_size = padded_row_bytes * H

    # total file size
    file_size = 14 + 40 + pixel_data_size  # BITMAPFILEHEADER + BITMAPINFOHEADER + pixels

    with open(file_path, "wb") as f:
        # === BITMAPFILEHEADER (14 bytes) ===
        f.write(b"BM")                          # signature
        f.write(struct.pack("<I", file_size))    # file size
        f.write(struct.pack("<HH", 0, 0))        # reserved fields
        f.write(struct.pack("<I", 14 + 40))      # Pixel data offset

        # === BITMAPINFOHEADER (40 bytes) ===
        f.write(struct.pack("<I", 40))           # header size
        f.write(struct.pack("<i", W))            # Width
        f.write(struct.pack("<i", H))            # height (positive value = bottom-up)
        f.write(struct.pack("<HH", 1, 24))       # Number of color planes=1, bit depth=24
        f.write(struct.pack("<I", 0))            # Compression=0 (BI_RGB)
        f.write(struct.pack("<I", pixel_data_size))  # Pixel data size
        f.write(struct.pack("<i", 2835))         # Horizontal resolution (72 DPI)
        f.write(struct.pack("<i", 2835))         # vertical resolution
        f.write(struct.pack("<I", 0))            # Palette color count = 0
        f.write(struct.pack("<I", 0))            # Number of important colors = 0

        # === Pixel data (bottom-up) ===
        pad_bytes = b"\x00" * padding

        # Build a color lookup table (vectorized to avoid pixel-by-pixel Python loops)
        max_pid = int(province_map.max())
        # Lookup table: index=province ID → (B, G, R)
        lut = np.ones((max_pid + 1, 3), dtype=np.uint8)  # Default (1,1,1) avoids (0,0,0)
        for pid, (r, g, b) in colors.items():
            if pid <= max_pid:
                lut[pid] = [b, g, r]  # BMP is the BGR sequence

        # Start writing from the last line (bottom-up)
        for y in range(H - 1, -1, -1):
            row_ids = province_map[y, :]
            # Map pixel with ID 0 to 0 (lut[0]=(1,1,1), not black)
            row_bgr = lut[row_ids]  # (W, 3)
            f.write(row_bgr.tobytes())
            if padding:
                f.write(pad_bytes)

    return colors


def write_heightmap_bmp(
    heightmap: np.ndarray,
    output_dir: str,
) -> None:
    """Writes an 8-bit grayscale BMP heightmap.

    Format requirements:
    - 8-bit indexed color BMP
    - 256-color grayscale palette
    -bottom-up"""
    # Use actual array shape, not global MAP_WIDTH/HEIGHT
    H, W = heightmap.shape

    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    file_path = os.path.join(map_dir, "heightmap.bmp")

    row_bytes = W
    padding = (4 - (row_bytes % 4)) % 4
    padded_row_bytes = row_bytes + padding

    # Palette size: 256 RGBQUAD (4 bytes each)
    palette_size = 256 * 4
    pixel_data_size = padded_row_bytes * H
    pixel_offset = 14 + 40 + palette_size
    file_size = pixel_offset + pixel_data_size

    with open(file_path, "wb") as f:
        # === BITMAPFILEHEADER ===
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", pixel_offset))

        # === BITMAPINFOHEADER ===
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<i", W))
        f.write(struct.pack("<i", H))
        f.write(struct.pack("<HH", 1, 8))       # 8 bits
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", pixel_data_size))
        f.write(struct.pack("<i", 2835))
        f.write(struct.pack("<i", 2835))
        f.write(struct.pack("<I", 0))            # ncolors=0 (original format, indicating default 256 colors)
        f.write(struct.pack("<I", 0))

        # === Grayscale Palette ===
        for i in range(256):
            f.write(struct.pack("BBBB", i, i, i, 0))  # B, G, R, Reserved

        # === Pixel data ===
        pad_bytes = b"\x00" * padding
        for y in range(H - 1, -1, -1):
            f.write(heightmap[y, :].tobytes())
            if padding:
                f.write(pad_bytes)


def write_terrain_bmp(
    terrain_map: np.ndarray,
    output_dir: str,
    game_target=None,
    install_dir: str | None = None,
) -> None:
    """Writes 8-bit indexed color terrain.bmp.
    Copy the file header + palette directly from the selected game install when provided (M6.2 trusted resolution). Legacy direct callers without a target keep a documented compatibility fallback; freeze/acceptance exports require an explicit target and report a missing palette as a blocker instead of silently substituting bytes (255 colors, offset=1074)."""
    # Use actual array shape, not global MAP_WIDTH/HEIGHT
    H, W = terrain_map.shape

    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)
    file_path = os.path.join(map_dir, "terrain.bmp")

    row_bytes = W
    padding = (4 - (row_bytes % 4)) % 4

    # Original terrain.bmp: ncolors=255, offset=1074
    # Strategy: From the original read-only palette, generate the correct file header yourself (to avoid file size mismatch)
    n_colors = 255
    palette_size = n_colors * 4
    pixel_data_size = (row_bytes + padding) * H
    pixel_offset = 14 + 40 + palette_size
    file_size = pixel_offset + pixel_data_size

    # M6.2: use the selected GameTarget/install_dir when provided. Legacy
    # direct callers without either keep a documented compatibility fallback
    # (user config, then DEFAULT_HOI4_PATH) inside the helper.
    vanilla_palette = None
    try:
        from services.game_assets import read_palette_bytes as _read_palette_bytes
        vanilla_palette, _palette_source = _read_palette_bytes(
            game_target, install_dir, "map/terrain.bmp", n_colors
        )
    except (ImportError, OSError, AttributeError, TypeError, ValueError):
        vanilla_palette = None

    with open(file_path, "wb") as f:
        # Generate the correct file header yourself (exact file size match)
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", pixel_offset))
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<i", W))
        f.write(struct.pack("<i", H))
        f.write(struct.pack("<HH", 1, 8))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", pixel_data_size))
        f.write(struct.pack("<i", 2835))
        f.write(struct.pack("<i", 2835))
        f.write(struct.pack("<I", n_colors))
        f.write(struct.pack("<I", n_colors))

        # Palette: Give priority to using the original version, otherwise generate it yourself
        if vanilla_palette and len(vanilla_palette) == n_colors * 4:
            f.write(vanilla_palette)
        else:
            from data.terrain_types import TERRAIN_TYPES, TERRAIN_PALETTE_INDEX
            palette = [(0, 0, 0)] * n_colors
            for terrain_name, index in TERRAIN_PALETTE_INDEX.items():
                if index < n_colors:
                    t = TERRAIN_TYPES[terrain_name]
                    palette[index] = t.color
            for r, g, b in palette:
                f.write(struct.pack("BBBB", b, g, r, 0))

        # Pixel data
        pad_bytes = b"\x00" * padding
        for y in range(H - 1, -1, -1):
            f.write(terrain_map[y, :].tobytes())
            if padding:
                f.write(pad_bytes)


def write_rivers_bmp(
    output_dir: str,
    river_map: np.ndarray | None = None,
    shape: tuple[int, int] | None = None,
) -> None:
    """Write rivers.bmp — 8-bit indexed color BMP.
    If river_map is not None, the actual river data is used; otherwise an all-white blank file is generated.
    shape is used when river_map=None to specify dimensions (H, W) to avoid using the global MAP_*."""
    from domain.managers.river import RIVER_PALETTE

    # Use actual array shape or externally specified size, cannot use global MAP_WIDTH/HEIGHT
    if river_map is not None:
        H, W = river_map.shape
    elif shape is not None:
        H, W = shape
    else:
        H, W = MAP_HEIGHT, MAP_WIDTH  # fallback, old behavior

    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)
    file_path = os.path.join(map_dir, "rivers.bmp")

    row_bytes = W
    padding = (4 - (row_bytes % 4)) % 4
    padded_row_bytes = row_bytes + padding
    palette_size = 256 * 4
    pixel_data_size = padded_row_bytes * H
    pixel_offset = 14 + 40 + palette_size
    file_size = pixel_offset + pixel_data_size

    with open(file_path, "wb") as f:
        # BMP file header
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", pixel_offset))

        # BITMAPINFOHEADER
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<i", W))
        f.write(struct.pack("<i", H))
        f.write(struct.pack("<HH", 1, 8))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", pixel_data_size))
        f.write(struct.pack("<i", 2835))
        f.write(struct.pack("<i", 2835))
        f.write(struct.pack("<I", 0))  # ncolors=0 (original format)
        f.write(struct.pack("<I", 0))

        # Palette (256 entries, BGRA)
        for i in range(256):
            if i in RIVER_PALETTE:
                r, g, b = RIVER_PALETTE[i]
                f.write(struct.pack("BBBB", b, g, r, 0))
            else:
                # Undefined indexes are colored white
                f.write(struct.pack("BBBB", 255, 255, 255, 0))

        # Pixel data (bottom-up)
        pad_bytes = b"\x00" * padding
        if river_map is not None:
            for y in range(H - 1, -1, -1):
                f.write(river_map[y].tobytes())
                if padding:
                    f.write(pad_bytes)
        else:
            # Index 255 = Land without river background (white)
            empty_row = b"\xff" * W
            for _ in range(H):
                f.write(empty_row)
                if padding:
                    f.write(pad_bytes)


def write_trees_bmp(output_dir: str) -> None:
    """Write blank trees.bmp.
    The original trees.bmp size is 1650×600 (not the map size 5632×2048!)
    8-bit palette BMP, pixel value = tree model index (0 = no tree, 255 = undefined).
    [Key] Must fill in 0 (no tree), cannot fill in 255 - otherwise HOI4 will search for each pixel
    mapobject_255 model failed, graphics.log refreshed "mapobject_255 failed to load"
    and crashes when entering the game."""
    # Original actual measurement: trees.bmp = 1650x600, 8bit, ncolors=0, offset=1078
    TREE_W = 1650
    TREE_H = 600

    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)
    file_path = os.path.join(map_dir, "trees.bmp")

    row_bytes = TREE_W
    padding = (4 - (row_bytes % 4)) % 4
    padded_row_bytes = row_bytes + padding
    palette_size = 256 * 4
    pixel_data_size = padded_row_bytes * TREE_H
    pixel_offset = 14 + 40 + palette_size
    file_size = pixel_offset + pixel_data_size

    with open(file_path, "wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", pixel_offset))

        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<i", TREE_W))
        f.write(struct.pack("<i", TREE_H))
        f.write(struct.pack("<HH", 1, 8))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", pixel_data_size))
        f.write(struct.pack("<i", 2835))
        f.write(struct.pack("<i", 2835))
        f.write(struct.pack("<I", 0))  # ncolors=0 (original format)
        f.write(struct.pack("<I", 0))

        for i in range(256):
            f.write(struct.pack("BBBB", i, i, i, 0))

        pad_bytes = b"\x00" * padding
        empty_row = b"\x00" * TREE_W  # 0 = no tree (255 cannot be used)
        for _ in range(TREE_H):
            f.write(empty_row)
            if padding:
                f.write(pad_bytes)


def write_cities_bmp(output_dir: str, map_width: int | None = None, map_height: int | None = None, game_target=None, install_dir: str | None = None) -> None:
    """Write blank cities.bmp (8-bit index of the same size as the map, all 0s = no cities).
    Must strictly match vanilla format: colors_used=255 (not 256), palette 255×4 bytes,
    pixel_offset=14+40+1020=1074. Otherwise, HOI4 reports "Missing cities mask bitmap" and crashes."""
    from data.constants import MAP_WIDTH as _GW, MAP_HEIGHT as _GH
    _W = int(map_width) if map_width is not None else int(_GW)
    _H = int(map_height) if map_height is not None else int(_GH)
    MAP_WIDTH, MAP_HEIGHT = _W, _H
    # M6.2: trusted palette resolution; legacy fallback lives in the helper.
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)
    file_path = os.path.join(map_dir, "cities.bmp")

    row_bytes = MAP_WIDTH
    padding = (4 - row_bytes % 4) % 4
    padded_row_bytes = row_bytes + padding
    n_colors = 255
    palette_size = n_colors * 4
    pixel_data_size = padded_row_bytes * MAP_HEIGHT
    pixel_offset = 14 + 40 + palette_size
    file_size = pixel_offset + pixel_data_size

    # M6.2: resolve via selected target when provided.
    vanilla_palette = None
    try:
        from services.game_assets import read_palette_bytes as _read_palette_bytes2
        vanilla_palette, _cities_source = _read_palette_bytes2(
            game_target, install_dir, "map/cities.bmp", n_colors
        )
    except (ImportError, OSError, AttributeError, TypeError, ValueError):
        vanilla_palette = None

    with open(file_path, "wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", pixel_offset))
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<i", MAP_WIDTH))
        f.write(struct.pack("<i", MAP_HEIGHT))
        f.write(struct.pack("<HH", 1, 8))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", pixel_data_size))
        f.write(struct.pack("<i", 2835))
        f.write(struct.pack("<i", 2835))
        f.write(struct.pack("<I", n_colors))
        f.write(struct.pack("<I", n_colors))
        if vanilla_palette and len(vanilla_palette) == palette_size:
            f.write(vanilla_palette)
        else:
            for i in range(n_colors):
                f.write(struct.pack("BBBB", i, i, i, 0))
        empty_row = b"\x00" * MAP_WIDTH
        pad_bytes = b"\x00" * padding
        for _ in range(MAP_HEIGHT):
            f.write(empty_row)
            if padding:
                f.write(pad_bytes)
