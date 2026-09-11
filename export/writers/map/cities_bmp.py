"""map/cities.bmp writer.

HOI4 uses cities.bmp to determine the city 3D model distribution. 8-bit indexed BMP.
scan urban terrain in terrain_map (palette index 13, spawn_city=yes),
Mark the city at the corresponding location. Without terrain_map, all black (no city) is generated.

Reference: Map modding.txt §Cities"""

from __future__ import annotations

import os
import struct

import numpy as np

# Note: Do not import MAP_WIDTH/HEIGHT at the top of the module — from import is value binding, set_map_size
# It will not be updated later. Use import data.constants as _c to get the dynamic value when needed in the function.


# Palette index in terrain.bmp with spawn_city=yes
_URBAN_PALETTE_INDEX = 13


def write_cities_bmp(output_dir: str,
                     terrain_map: np.ndarray | None = None) -> None:
    """Generate map/cities.bmp (full size, same size as provinces.bmp).
    vanilla cities.bmp is full size 5632x2048, not 1/4."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "cities.bmp")

    # The dimensions are authoritative with terrain_map (consistent with provinces.bmp); fallback to global when there is no terrain
    if terrain_map is not None:
        h, w = terrain_map.shape
        data = (terrain_map == _URBAN_PALETTE_INDEX).astype(np.uint8) * 15
    else:
        import data.constants as _c
        w, h = _c.MAP_WIDTH, _c.MAP_HEIGHT
        data = np.zeros((h, w), dtype=np.uint8)

    _write_8bit_bmp(path, data, w, h)


def _write_8bit_bmp(path: str, data: np.ndarray,
                    w: int, h: int) -> None:
    """Write 8-bit indexed BMP files (bottom-up)."""
    row_pad = (4 - w % 4) % 4
    padded_row = w + row_pad

    palette_size = 256 * 4
    pixel_size = padded_row * h
    header_size = 14 + 40 + palette_size
    file_size = header_size + pixel_size

    with open(path, "wb") as f:
        # BMP header
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", header_size))

        # DIB header
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<i", w))
        f.write(struct.pack("<i", h))  # positive = bottom-up
        f.write(struct.pack("<HH", 1, 8))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", pixel_size))
        f.write(struct.pack("<ii", 2835, 2835))
        f.write(struct.pack("<II", 256, 0))

        # Palette — must be a **real** palette (not identity grayscale),
        # Otherwise, some parsers will read BMP as grayscale L mode, and the 8-bit pixel value will be regarded as height difference.
        # Palette index invalid → HOI4 read exception city type → EXCEPTION_INT_DIVIDE_BY_ZERO.
        # HOI4 actually only reads index 0 / 1 / 2 / 3 / 15, and fill in the rest with any non-matching characters.
        _CITIES_PALETTE = {
            0: (0, 0, 0),        # no city
            1: (150, 150, 150),  # Ordinary city
            2: (180, 140, 80),   # desert city
            3: (120, 90, 50),    # dark city
            15: (200, 200, 200), # desert city (variant)
        }
        for i in range(256):
            if i in _CITIES_PALETTE:
                r, g, b = _CITIES_PALETTE[i]
            else:
                # Fill other indexes with a color that is significantly different from identity grayscale to prevent the parser from downgrading.
                r, g, b = (i, (i * 131) & 0xFF, (i * 239) & 0xFF)
            f.write(struct.pack("BBBB", b, g, r, 0))  # BMP palette = BGRA

        # Pixel data (bottom-up)
        pad = b"\x00" * row_pad
        for row_idx in range(h - 1, -1, -1):
            f.write(data[row_idx].tobytes())
            if row_pad:
                f.write(pad)
