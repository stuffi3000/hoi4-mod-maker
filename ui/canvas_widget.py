"""Compatibility layer — Legacy code references MapCanvas and color LUTs via ui.canvas_widget."""
from views.canvas.widget import MapCanvas
from views.canvas.luts import (
    _TILE_BGRA,
    _TERRAIN_COLOR_LUT,
    _TERRAIN_DISPLAY_COLORS,
    _RIVER_COLOR_LUT,
    _PROVINCE_COLOR_LUT,
    _PROVINCE_COLOR_LUT_SIZE,
)
