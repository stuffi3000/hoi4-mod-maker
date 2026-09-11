"""Color Lookup Table (LUT) — BGRA color mapping for tiles/terrains/rivers/provinces
Split from canvas_widget.py and shared by renderer and widget"""
import numpy as np

from data.constants import TILE_UNDEFINED, TILE_LAND, TILE_SEA, TILE_LAKE
from data.terrain_types import TERRAIN_TYPES, TERRAIN_PALETTE_INDEX, GRAPHICAL_TERRAINS, PALETTE_TO_TYPE
from domain.managers.river import (
    RIVER_DISPLAY_COLORS, RIVER_SOURCE, RIVER_BG_LAND, RIVER_BG_SEA,
    RIVER_ERASE, VALID_RIVER_VALUES,
)

# BGRA value corresponding to the parcel type (QImage Format_RGB32)
_TILE_BGRA = {
    TILE_UNDEFINED: (30, 20, 20, 255),
    TILE_LAND:      (101, 172, 139, 255),
    TILE_SEA:       (156, 105, 68, 255),
    TILE_LAKE:      (210, 160, 100, 255),
}

# Build terrain index → BGRA color lookup table (covers all graphical terrain)
# Each variant uses an independent, highly saturated color to ensure that it is distinguishable at a glance on the canvas.
_TERRAIN_COLOR_LUT = np.zeros((256, 4), dtype=np.uint8)
_TERRAIN_DISPLAY_COLORS: dict[int, tuple[int, int, int]] = {
    # plains group: green
    0:  (120, 180, 60),   # plain
    5:  (100, 160, 40),   # plain (variant)
    19: (180, 200, 220),  # Snowfield (white-blue)
    # forest group: dark green
    1:  (30, 130, 30),    # forest
    4:  (50, 150, 70),    # forest (variant)
    # hills group: yellow orange
    2:  (210, 180, 80),   # desert hills
    17: (230, 200, 60),   # hills
    # mountain group: distinct gray and brown
    6:  (140, 130, 120),  # Mountain
    10: (160, 140, 100),  # Mountain (variant)
    11: (180, 150, 100),  # desert mountains
    16: (200, 210, 230),  # Snow Mountain (white-blue)
    18: (190, 170, 110),  # sandy mountains
    20: (130, 150, 100),  # grassy mountains
    27: (80, 120, 70),    # jungle mountains
    31: (110, 90, 60),    # Desert mountain top (dark brown)
    # desert group: yellow sand series
    3:  (220, 190, 100),  # desert
    7:  (200, 170, 80),   # Desert (variant)
    8:  (210, 160, 90),   # desert hills
    12: (230, 210, 130),  # desert (rocky land)
    # marsh: dark green
    9:  (70, 120, 90),    # swamp
    # urban: purple gray
    13: (160, 130, 170),  # city
    # jungle: yellow-green
    21: (60, 140, 20),    # jungle
    22: (80, 160, 40),    # Jungle (variant)
    # water (not drawable but needs to be displayed)
    14: (60, 130, 200),   # lake
    15: (30, 80, 180),    # ocean
}
for _idx, (_r, _g, _b) in _TERRAIN_DISPLAY_COLORS.items():
    _TERRAIN_COLOR_LUT[_idx] = (_b, _g, _r, 255)  # BGRA

# River Color LUT (Index → BGRA)
_RIVER_COLOR_LUT = np.zeros((256, 4), dtype=np.uint8)
for _ridx, _rbgra in RIVER_DISPLAY_COLORS.items():
    _RIVER_COLOR_LUT[_ridx] = _rbgra
# The background color does not need to be displayed on the canvas (use a basemap)

# Height → BGRA color LUT (shared by height renderer and state/country terrain basemap)
# Color band: 0-40 dark blue deep sea / 40-90 light blue shallow sea / 90-95 cyan sea level
# 95-130 green plains / 130-160 yellow-green hills / 160-200 brown mountains
# 200-240 dark brown mountain / 240-255 white snow top
_HEIGHT_COLOR_LUT = np.zeros((256, 4), dtype=np.uint8)
_HEIGHT_BANDS = [
    (0,   40,  (20,  40,  80),  (30,  60, 120)),
    (40,  90,  (60,  90, 140),  (100, 140, 180)),
    (90,  95,  (140, 180, 180), (160, 200, 180)),
    (95,  130, (80,  160, 80),  (140, 190, 100)),
    (130, 160, (160, 190, 100), (200, 200, 80)),
    (160, 200, (160, 140, 60),  (140, 100, 50)),
    (200, 240, (120, 80,  40),  (100, 70,  50)),
    (240, 256, (200, 200, 210), (255, 255, 255)),
]
for _lo, _hi, (_r0, _g0, _b0), (_r1, _g1, _b1) in _HEIGHT_BANDS:
    _span = max(_hi - _lo, 1)
    for _v in range(_lo, min(_hi, 256)):
        _t = (_v - _lo) / _span
        _r = int(_r0 + (_r1 - _r0) * _t)
        _g = int(_g0 + (_g1 - _g0) * _t)
        _b = int(_b0 + (_b1 - _b0) * _t)
        _HEIGHT_COLOR_LUT[_v] = (_b, _g, _r, 255)  # BGRA

# Terrain basemap LUT in State/Country mode (desaturate to avoid grabbing the color of state/country)
# Sea area: dark → light blue (height < SEA_LEVEL); land: grayscale (height >= SEA_LEVEL, the higher the brighter)
_HEIGHT_UNDERLAY_LUT = np.zeros((256, 4), dtype=np.uint8)
_SEA_LVL = 90
for _v in range(256):
    if _v < _SEA_LVL:
        _t = _v / max(_SEA_LVL, 1)
        _b = int(110 + _t * 70)
        _g = int(60 + _t * 60)
        _r = int(30 + _t * 40)
        _HEIGHT_UNDERLAY_LUT[_v] = (_b, _g, _r, 255)
    else:
        _t = (_v - _SEA_LVL) / max(255 - _SEA_LVL, 1)
        _gray = int(120 + _t * 120)
        _HEIGHT_UNDERLAY_LUT[_v] = (_gray, _gray, _gray, 255)

# Province random color LUT (deterministic, based on province ID)
_PROVINCE_COLOR_LUT_SIZE = 65536
_rng = np.random.RandomState(42)
_PROVINCE_COLOR_LUT = np.zeros((_PROVINCE_COLOR_LUT_SIZE, 4), dtype=np.uint8)
_PROVINCE_COLOR_LUT[:, 0] = _rng.randint(40, 220, _PROVINCE_COLOR_LUT_SIZE, dtype=np.uint8)
_PROVINCE_COLOR_LUT[:, 1] = _rng.randint(40, 220, _PROVINCE_COLOR_LUT_SIZE, dtype=np.uint8)
_PROVINCE_COLOR_LUT[:, 2] = _rng.randint(40, 220, _PROVINCE_COLOR_LUT_SIZE, dtype=np.uint8)
_PROVINCE_COLOR_LUT[:, 3] = 255
# ID 0 = not assigned, use dark color
_PROVINCE_COLOR_LUT[0] = (30, 20, 20, 255)
