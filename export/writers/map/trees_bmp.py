"""map/trees.bmp writer.

8-bit indexed BMP, bottom-up, vanilla palette (256 colors).
Size = map ÷ 4 (HOI4 scaled to actual map).

Reference: Map modding.txt §Trees (lines 419-470)."""

from __future__ import annotations

import os
import struct

import numpy as np

# Note: Use import as, not from import — from import is value binding, set_map_size is not updated.
import data.constants as _const
from data.trees_palette import TREES_PALETTE_BYTES


def write_trees_bmp(
    output_dir: str,
    tree_map: np.ndarray | None = None,
    map_width: int | None = None,
    map_height: int | None = None,
) -> None:
    """Generate map/trees.bmp.

    tree_map: uint8 array (H//4, W//4), one palette index per pixel.
              None → completely black (no tree).
    map_width/map_height: actual map size, used to calculate the size when tree_map=None."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "trees.bmp")

    if tree_map is not None:
        data = tree_map.astype(np.uint8)
        h, w = data.shape[:2]
    else:
        mw = map_width if map_width else _const.MAP_WIDTH
        mh = map_height if map_height else _const.MAP_HEIGHT
        w = mw // 4
        h = mh // 4
        data = np.zeros((h, w), dtype=np.uint8)

    # BMP row padding (each row must be multiple of 4 bytes)
    row_bytes = w
    row_pad = (4 - row_bytes % 4) % 4
    padded_row = row_bytes + row_pad

    # BMP is bottom-up: flip vertically
    data_flipped = data[::-1, :]

    # Write BMP
    palette_size = 256 * 4  # 1024
    pixel_size = padded_row * h
    header_size = 14 + 40 + palette_size
    file_size = header_size + pixel_size

    with open(path, "wb") as f:
        # BMP file header (14 bytes)
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", header_size))

        # DIB header (40 bytes)
        f.write(struct.pack("<I", 40))       # header size
        f.write(struct.pack("<i", w))        # width
        f.write(struct.pack("<i", h))        # height (positive = bottom-up)
        f.write(struct.pack("<HH", 1, 8))   # planes, bpp
        f.write(struct.pack("<I", 0))        # compression (none)
        f.write(struct.pack("<I", pixel_size))
        f.write(struct.pack("<ii", 2835, 2835))  # ppm
        f.write(struct.pack("<II", 256, 0))       # colors used, important

        # Palette (256 × BGRA)
        f.write(TREES_PALETTE_BYTES)

        # Pixel data (bottom-up, padded rows)
        pad = b"\x00" * row_pad
        for row in range(h):
            f.write(data_flipped[row, :].tobytes())
            if row_pad:
                f.write(pad)


def auto_generate_tree_map(terrain_map: np.ndarray) -> np.ndarray:
    """Automatically generate tree_map from terrain_map (downsampled to trees resolution).

    terrain_map: (H, W) uint8, palette index.
    Return: (H//4, W//4) uint8, trees palette index."""
    from data.terrain_types import TERRAIN_PALETTE_INDEX
    from data.trees_palette import TERRAIN_TO_TREE_INDEX

    full_h, full_w = terrain_map.shape[:2]
    h = full_h // 4
    w = full_w // 4

    # downsample terrain_map
    step_y = max(1, full_h // h)
    step_x = max(1, full_w // w)
    small_terrain = terrain_map[::step_y, ::step_x][:h, :w]

    # Construct reverse lookup table: terrain_palette_index → terrain_name
    idx_to_name: dict[int, str] = {}
    for tname, tidx in TERRAIN_PALETTE_INDEX.items():
        idx_to_name[tidx] = tname

    tree_map = np.zeros((h, w), dtype=np.uint8)
    for terrain_idx, terrain_name in idx_to_name.items():
        tree_idx = TERRAIN_TO_TREE_INDEX.get(terrain_name, 0)
        if tree_idx > 0:
            tree_map[small_terrain == terrain_idx] = tree_idx

    return tree_map
