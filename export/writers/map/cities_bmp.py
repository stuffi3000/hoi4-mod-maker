"""Writers for the cosmetic city layer used by Hearts of Iron IV.

The game keeps city geometry separate from provinces. ``terrain.bmp`` marks
the pixels that use a graphical terrain with ``spawn_city = yes`` and
``cities.bmp`` selects the city style for those pixels. ``cities.txt`` then
maps each style to the vanilla city entities.
"""

from __future__ import annotations

import os
import struct

import numpy as np


# ``forest_13`` in vanilla ``common/terrain/00_terrain.txt``.
_URBAN_PALETTE_INDEX = 13
_CITY_MASK_INDEX = 15  # Western city group; this is the normal default style.
_BMP_PALETTE_ENTRIES = 255  # Match the vanilla cities.bmp header/palette.


# Keep a complete city-group definition in the exported mod. A file that only
# points to cities.bmp is accepted by the parser, but it has no building meshes,
# so urban pixels remain visually empty. This is the current vanilla setup and
# is also useful when the editor is run on a machine without a game install.
_VANILLA_CITIES_TEXT = '''types_source = "map/cities.bmp"
pixel_step_x = 2 #2
pixel_step_y = 2 #2

# Western cities
city_group = {
\tcolor_index = 15 # color index in bmp palette
\tdensity = 0.9 # 0.1 # in fraction of pixels. Negative=less dense.

\t# The following should be sorted by distance (growing)
\tbuilding = {
\t\tdistance = 1 # distance to the edge of urban area (in map pixels)
\t\tmesh = {
\t\t\t"westerngfx_house_1_1"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 2
\t\tmesh = {
\t\t\t"westerngfx_house_1_2"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 3
\t\tmesh = {
\t\t\t"westerngfx_house_1_3"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 4
\t\tmesh = {
\t\t\t"westerngfx_house_1_4"
\t\t}
\t}
}

city_group = {
\tcolor_index = 0 # color index in bmp palette
\tdensity = 0.00001 # 0.1 # in fraction of pixels. Negative=less dense.

\t# The following should be sorted by distance (growing)
\tbuilding = {
\t\tdistance = 1 # distance to the edge of urban area (in map pixels)
\t\tmesh = {
\t\t\t"asia_city_01_entity"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 2
\t\tmesh = {
\t\t\t"asia_city_02_entity"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 3
\t\tmesh = {
\t\t\t"asia_city_03_entity"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 4
\t\tmesh = {
\t\t\t"asia_city_04_entity"
\t\t}
\t}
}

city_group = {
\tcolor_index = 1 # color index in bmp palette
\tdensity = 1.0 # 0.05 # in fraction of pixels. Negative=less dense.

\t# The following should be sorted by distance (growing)
\tbuilding = {
\t\tdistance = 1 # distance to the edge of urban area (in map pixels)
\t\tmesh = {
\t\t\t"french_city_4_04_entity"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 2
\t\tmesh = {
\t\t\t"french_city_4_03_entity"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 3
\t\tmesh = {
\t\t\t"french_city_4_02_entity"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 4
\t\tmesh = {
\t\t\t"french_city_4_01_entity"
\t\t}
\t}
}

city_group = {
\tcolor_index = 2 # color index in bmp palette
\tdensity = 0.2 # 0.1 # in fraction of pixels. Negative=less dense.

\t# The following should be sorted by distance (growing)
\tbuilding = {
\t\tdistance = 1 # distance to the edge of urban area (in map pixels)
\t\tmesh = {
\t\t\t"unciv_city_01_entity"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 2
\t\tmesh = {
\t\t\t"unciv_city_02_entity"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 3
\t\tmesh = {
\t\t\t"unciv_city_03_entity"
\t\t}
\t}
\tbuilding = {
\t\tdistance = 4
\t\tmesh = {
\t\t\t"unciv_city_04_entity"
\t\t}
\t}
}
'''


def write_cities_txt(output_dir: str) -> None:
    """Write city meshes and mask settings to ``map/cities.txt``."""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)
    with open(
        os.path.join(map_dir, "cities.txt"),
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:
        f.write(_VANILLA_CITIES_TEXT)


def write_cities_bmp(
    output_dir: str,
    terrain_map: np.ndarray | None = None,
) -> None:
    """Generate ``map/cities.bmp`` from the painted Urban graphical terrain.

    The bitmap is full map resolution, just like ``provinces.bmp``. Only the
    Urban terrain index is marked; the city definitions in ``cities.txt`` and
    vanilla's ``spawn_city = yes`` terrain flag do the rest.
    """
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)
    path = os.path.join(map_dir, "cities.bmp")

    if terrain_map is not None:
        h, w = terrain_map.shape
        data = np.where(
            terrain_map == _URBAN_PALETTE_INDEX,
            _CITY_MASK_INDEX,
            0,
        ).astype(np.uint8)
    else:
        # Keep this fallback for callers that write a map without a terrain
        # layer. The exporter normally supplies its generated terrain map.
        import data.constants as _c

        w, h = _c.MAP_WIDTH, _c.MAP_HEIGHT
        data = np.zeros((h, w), dtype=np.uint8)

    _write_8bit_bmp(path, data, w, h)


def _vanilla_palette() -> bytes | None:
    """Return the installed game's 255-entry cities palette when available."""
    candidates: list[str] = []
    try:
        # The editor stores the selected installation in the user config, so it
        # is preferable to the historical hard-coded default path.
        from services.game_assets import find_hoi4_install

        install = find_hoi4_install()
        if install:
            candidates.append(os.path.join(install, "map", "cities.bmp"))
    except Exception:
        # Export must remain usable without optional game-asset discovery.
        pass

    try:
        from data.constants import DEFAULT_HOI4_PATH

        candidates.append(os.path.join(DEFAULT_HOI4_PATH, "map", "cities.bmp"))
    except Exception:
        pass

    seen: set[str] = set()
    for candidate in candidates:
        candidate = os.path.normcase(os.path.abspath(candidate))
        if candidate in seen or not os.path.isfile(candidate):
            continue
        seen.add(candidate)
        try:
            with open(candidate, "rb") as f:
                header = f.read(54)
                if len(header) != 54:
                    continue
                offset = struct.unpack_from("<I", header, 10)[0]
                bpp = struct.unpack_from("<H", header, 28)[0]
                if bpp != 8 or offset < 54:
                    continue
                f.seek(54)
                palette = f.read(_BMP_PALETTE_ENTRIES * 4)
                if len(palette) == _BMP_PALETTE_ENTRIES * 4:
                    return palette
        except OSError:
            continue
    return None


def _fallback_palette() -> bytes:
    """Build a deterministic palette for installations without vanilla files."""
    # HOI4 uses the indexed pixel values for city groups. The explicit colours
    # keep the file a genuine indexed image while retaining the useful styles
    # used by the exporter (15 = Western, 0/1/2 = alternate vanilla groups).
    city_palette = {
        0: (0, 0, 0),
        1: (150, 150, 150),
        2: (180, 140, 80),
        3: (120, 90, 50),
        15: (200, 200, 200),
    }
    entries = []
    for i in range(_BMP_PALETTE_ENTRIES):
        r, g, b = city_palette.get(
            i,
            (i, (i * 131) & 0xFF, (i * 239) & 0xFF),
        )
        entries.append(struct.pack("BBBB", b, g, r, 0))
    return b"".join(entries)


def _write_8bit_bmp(path: str, data: np.ndarray, w: int, h: int) -> None:
    """Write an 8-bit indexed, bottom-up BMP with a vanilla-compatible header."""
    row_pad = (4 - w % 4) % 4
    padded_row = w + row_pad
    palette_size = _BMP_PALETTE_ENTRIES * 4
    pixel_size = padded_row * h
    header_size = 14 + 40 + palette_size
    file_size = header_size + pixel_size

    palette = _vanilla_palette() or _fallback_palette()

    with open(path, "wb") as f:
        # BMP file header
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", header_size))

        # BITMAPINFOHEADER
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<i", w))
        f.write(struct.pack("<i", h))  # positive = bottom-up
        f.write(struct.pack("<HH", 1, 8))
        f.write(struct.pack("<I", 0))  # BI_RGB
        f.write(struct.pack("<I", pixel_size))
        f.write(struct.pack("<ii", 2835, 2835))
        f.write(struct.pack("<II", _BMP_PALETTE_ENTRIES, _BMP_PALETTE_ENTRIES))
        f.write(palette)

        # Pixel data (bottom-up, rows padded to a 4-byte boundary)
        pad = b"\x00" * row_pad
        for row_idx in range(h - 1, -1, -1):
            f.write(data[row_idx].tobytes())
            if row_pad:
                f.write(pad)
