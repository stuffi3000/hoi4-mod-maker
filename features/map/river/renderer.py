"""River mode rendering: terrain basemap + river overlay.

HOI4 states that the river must be 1 pixel wide, but a 1 pixel blue/red/yellow line is barely visible on the canvas,
Only the bright green "source" stands out. So when rendering we visually inflate the river to 3 pixels,
But the data layer remains 1 pixel (the exported rivers.bmp is unaffected)."""

import numpy as np

from features.map.terrain import renderer as terrain_renderer
from domain.managers.river import VALID_RIVER_VALUES


# Visual expansion radius (canvas appears bold). 0 = no expansion (1px), 1 = 3×3, 2 = 5×5
# The data layer is always 1px (HOI4 rules), this only affects the visual weight in the editor.
_DISPLAY_DILATE_RADIUS = 0


def _make_river_mask(river_data: np.ndarray) -> np.ndarray:
    """River pixel mask: All valid river values (including 0=source)."""
    mask = np.zeros(river_data.shape, dtype=bool)
    for v in VALID_RIVER_VALUES:
        mask |= (river_data == v)
    return mask


def _dilated_color_overlay(
    river_data: np.ndarray, color_lut: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (dilated_mask, dilated_colors) — based on 1px of original river_data
    The vision expands into a thick line of (2r+1) × (2r+1).

    Color priority: source/entry/estuary > width index.
    That is, if there is both width and marker in a neighborhood, the marker color wins."""
    h, w = river_data.shape
    r = _DISPLAY_DILATE_RADIUS
    if r <= 0:
        return _make_river_mask(river_data), color_lut[river_data]

    # source mask (original 1px river position)
    src_mask = _make_river_mask(river_data)
    if not np.any(src_mask):
        return src_mask, color_lut[river_data]

    # Color source for each pixel: "Source/Inlet/Inlet" (index 0/1/2) first, followed by width
    # First calculate a "priority" field: markers = high, widths = low, bg = 0
    priority = np.zeros_like(river_data, dtype=np.uint8)
    priority[src_mask] = 1  # ordinary river
    priority[(river_data == 0) | (river_data == 1) | (river_data == 2)] = 2  # markers

    # Dilation: scan each offset (dy, dx) ∈ [-r, r], copy the original pixel to the neighborhood, retain high priority
    out_values = np.zeros_like(river_data)
    out_priority = np.zeros_like(priority)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            # Move river_data along (dy, dx) to the canvas
            y_src_start = max(0, -dy)
            y_src_end = min(h, h - dy)
            x_src_start = max(0, -dx)
            x_src_end = min(w, w - dx)
            y_dst_start = max(0, dy)
            y_dst_end = min(h, h + dy)
            x_dst_start = max(0, dx)
            x_dst_end = min(w, w + dx)

            src_vals = river_data[y_src_start:y_src_end, x_src_start:x_src_end]
            src_prio = priority[y_src_start:y_src_end, x_src_start:x_src_end]
            dst_vals = out_values[y_dst_start:y_dst_end, x_dst_start:x_dst_end]
            dst_prio = out_priority[y_dst_start:y_dst_end, x_dst_start:x_dst_end]

            # Higher priority values override
            win = src_prio > dst_prio
            dst_vals[win] = src_vals[win]
            dst_prio[win] = src_prio[win]

    dilated_mask = out_priority > 0
    dilated_colors = color_lut[out_values]
    return dilated_mask, dilated_colors


def render(canvas) -> None:
    from ui.canvas_widget import _RIVER_COLOR_LUT
    # First render the terrain as a base map (you must be able to see the direction of the valley when drawing a river)
    terrain_renderer.render(canvas)
    mask, colors = _dilated_color_overlay(canvas._river_map, _RIVER_COLOR_LUT)
    if np.any(mask):
        canvas._display_buffer[mask] = colors[mask]


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    from ui.canvas_widget import _RIVER_COLOR_LUT
    # Inflated display will cause 1px source pixel to affect ±r neighborhood → local refresh range must also be expanded
    r = _DISPLAY_DILATE_RADIUS
    h, w = canvas._river_map.shape
    ex0 = max(0, x0 - r)
    ey0 = max(0, y0 - r)
    ex1 = min(w, x1 + r)
    ey1 = min(h, y1 + r)
    # First redraw the base map (terrain) of the expanded area to prevent old river pixels from remaining in the expanded area.
    terrain_renderer.partial_render(canvas, ex0, ey0, ex1, ey1)
    region = canvas._river_map[ey0:ey1, ex0:ex1]
    mask, colors = _dilated_color_overlay(region, _RIVER_COLOR_LUT)
    if np.any(mask):
        buf = canvas._display_buffer[ey0:ey1, ex0:ex1]
        buf[mask] = colors[mask]
