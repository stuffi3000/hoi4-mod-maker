"""Logistics Mode Canvas Rendering - Railroad Grade Shaded Illustration.

Each province with railways is colored by level (1=grey-blue → 5=red).
Much faster than drawing line segments and KR 1027 rails don’t get stuck."""

from __future__ import annotations


def render(canvas) -> None:
    """Logistics Mode: Railroad grade coloring."""
    if canvas._railway_color_rgb is not None:
        canvas._display_buffer[:, :, 0] = canvas._railway_color_rgb[:, :, 2]
        canvas._display_buffer[:, :, 1] = canvas._railway_color_rgb[:, :, 1]
        canvas._display_buffer[:, :, 2] = canvas._railway_color_rgb[:, :, 0]
        canvas._display_buffer[:, :, 3] = 255
    else:
        # fallback: Map of land and sea floor
        from features.map.land import renderer as land_renderer
        land_renderer.render(canvas)


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    buf = canvas._display_buffer[y0:y1, x0:x1]
    if canvas._railway_color_rgb is not None:
        region = canvas._railway_color_rgb[y0:y1, x0:x1]
        buf[:, :, 0] = region[:, :, 2]
        buf[:, :, 1] = region[:, :, 1]
        buf[:, :, 2] = region[:, :, 0]
        buf[:, :, 3] = 255
    else:
        from features.map.land import renderer as land_renderer
        land_renderer.partial_render(canvas, x0, y0, x1, y1)
