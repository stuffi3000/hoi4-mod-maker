"""Country mode rendering: country color block + assigned white border between countries + selected country red border (covering white).

Performance: The white edge mask is cached in the canvas, and country_rgb remains unchanged and is not recalculated (only the red edge is recalculated).
Correctness:
  - White borders are only drawn between lands with "allocated states" on both sides (skipping ocean/unallocated state).
  - Paint both sides of the selected country's border in red (completely covering the white border, so there will be no mixture of red and white)."""

import numpy as np


def _compute_white_borders(country_rgb, assigned_mask):
    """Compute the white border mask (H, W bool) between all assigned countries.

    Border = color change, and both sides of the border belong to "assigned countries".
    Ocean/unallocated state does not participate → no white edges are drawn between these areas and their neighbors."""
    h, w = country_rgb.shape[:2]
    borders = np.zeros((h, w), dtype=bool)
    if assigned_mask is None:
        # If no mask is passed, it will fall back to "all color changes are painted white" (compatible with old callers)
        diff_v = (country_rgb[:-1] != country_rgb[1:]).any(axis=2)
        diff_h = (country_rgb[:, :-1] != country_rgb[:, 1:]).any(axis=2)
        borders[:-1, :] |= diff_v
        borders[1:, :]  |= diff_v
        borders[:, :-1] |= diff_h
        borders[:, 1:]  |= diff_h
        return borders

    # Up and down direction: pixels (y, x) and (y+1, x) have different colors, and both pixels are assigned
    diff_v = (country_rgb[:-1] != country_rgb[1:]).any(axis=2)
    a_v = assigned_mask[:-1] & assigned_mask[1:]
    border_v = diff_v & a_v
    borders[:-1, :] |= border_v
    borders[1:, :]  |= border_v

    # left and right direction
    diff_h = (country_rgb[:, :-1] != country_rgb[:, 1:]).any(axis=2)
    a_h = assigned_mask[:, :-1] & assigned_mask[:, 1:]
    border_h = diff_h & a_h
    borders[:, :-1] |= border_h
    borders[:, 1:]  |= border_h

    return borders


def _compute_red_borders(country_rgb, highlight_rgb):
    """Calculate the mask of the selected country border (H, W bool, both sides of the border are painted red, and the white edges are automatically covered)."""
    if highlight_rgb is None:
        return None
    h, w = country_rgb.shape[:2]
    hr, hg, hb = highlight_rgb
    is_hl = (
        (country_rgb[:, :, 0] == hr)
        & (country_rgb[:, :, 1] == hg)
        & (country_rgb[:, :, 2] == hb)
    )
    if not is_hl.any():
        return None

    borders = np.zeros((h, w), dtype=bool)
    # Top and bottom: one side is highlighted + the other side is not highlighted → both pixels are painted red
    edge_v = is_hl[:-1] != is_hl[1:]
    borders[:-1, :] |= edge_v
    borders[1:, :]  |= edge_v
    # left and right
    edge_h = is_hl[:, :-1] != is_hl[:, 1:]
    borders[:, :-1] |= edge_h
    borders[:, 1:]  |= edge_h

    # Widen 1 pixel (2 pixel thick red border)
    borders = (
        borders
        | np.roll(borders, 1, axis=0)
        | np.roll(borders, -1, axis=0)
        | np.roll(borders, 1, axis=1)
        | np.roll(borders, -1, axis=1)
    )
    return borders


def _get_white_borders_cached(canvas):
    """Get the white edge from the canvas cache, if not, count it once and cache it."""
    rgb = canvas._country_color_rgb
    mask = getattr(canvas, "_country_assigned_mask", None)
    cache = getattr(canvas, "_country_borders_cache", None)
    rgb_id = id(rgb)
    mask_id = id(mask) if mask is not None else 0
    if cache and cache[0] == (rgb_id, mask_id):
        return cache[1]
    white = _compute_white_borders(rgb, mask)
    canvas._country_borders_cache = ((rgb_id, mask_id), white)
    return white


def render(canvas) -> None:
    if canvas._country_color_rgb is not None:
        rgb = canvas._country_color_rgb
        canvas._display_buffer[:, :, 0] = rgb[:, :, 2]
        canvas._display_buffer[:, :, 1] = rgb[:, :, 1]
        canvas._display_buffer[:, :, 2] = rgb[:, :, 0]
        canvas._display_buffer[:, :, 3] = 255

        # 1. White edge (taken from cache)
        white = _get_white_borders_cached(canvas)
        canvas._display_buffer[white, 0] = 255
        canvas._display_buffer[white, 1] = 255
        canvas._display_buffer[white, 2] = 255
        canvas._display_buffer[white, 3] = 255

        # 2. Red edge (covering white)
        red = _compute_red_borders(rgb, getattr(canvas, "_highlight_country_rgb", None))
        if red is not None:
            canvas._display_buffer[red, 0] = 0    # B
            canvas._display_buffer[red, 1] = 0    # G
            canvas._display_buffer[red, 2] = 255  # R
            canvas._display_buffer[red, 3] = 255
    else:
        canvas._display_buffer[:, :, 0] = 60
        canvas._display_buffer[:, :, 1] = 60
        canvas._display_buffer[:, :, 2] = 60
        canvas._display_buffer[:, :, 3] = 255


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    """Partial redrawing: still use the white edge slice of the entire image in the cache, and only the red edge is included in the selected area."""
    buf = canvas._display_buffer[y0:y1, x0:x1]
    if canvas._country_color_rgb is not None:
        rgb_full = canvas._country_color_rgb
        region = rgb_full[y0:y1, x0:x1]
        buf[:, :, 0] = region[:, :, 2]
        buf[:, :, 1] = region[:, :, 1]
        buf[:, :, 2] = region[:, :, 0]
        buf[:, :, 3] = 255

        white_full = _get_white_borders_cached(canvas)
        white = white_full[y0:y1, x0:x1]
        buf[white, 0] = 255
        buf[white, 1] = 255
        buf[white, 2] = 255
        buf[white, 3] = 255

        red = _compute_red_borders(region, getattr(canvas, "_highlight_country_rgb", None))
        if red is not None:
            buf[red, 0] = 0
            buf[red, 1] = 0
            buf[red, 2] = 255
            buf[red, 3] = 255
    else:
        buf[:, :, :] = [60, 60, 60, 255]
