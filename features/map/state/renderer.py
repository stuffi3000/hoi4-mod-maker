"""State mode rendering.

Three layers are superimposed, allowing users to see clearly "which country/state/who the selected one belongs to" at a glance when editing province ownership:

  1. **Background color = state color ⊗ National color 50/50 mix** (assigned area)
     Unallocated state degenerates into pure state color, and without country data there is no mixing.
  2. **Country Borders = 3 pixel white bold line**, drawn only between two assigned countries
     (Skip ocean/unallocated area).
  3. **Selected Country Highlight** = Select the country of the owner of the state, all pixels are superimposed with a warm yellow tone,
     You can immediately see "where are the other states in this country". Pass in canvas._highlight_country_rgb.

Performance: The country border mask is cached in the canvas and is only recalculated when country_rgb / assigned_mask changes."""
import numpy as np


_HL_BGR = np.array([80, 230, 255], dtype=np.uint16)  # warm yellow (BGR)


def _compute_country_borders(country_rgb, assigned_mask):
    """Border mask between two assigned countries, bolded to ~3 pixels thick."""
    h, w = country_rgb.shape[:2]
    borders = np.zeros((h, w), dtype=bool)

    diff_v = (country_rgb[:-1] != country_rgb[1:]).any(axis=2)
    a_v = assigned_mask[:-1] & assigned_mask[1:]
    border_v = diff_v & a_v
    borders[:-1, :] |= border_v
    borders[1:, :] |= border_v

    diff_h = (country_rgb[:, :-1] != country_rgb[:, 1:]).any(axis=2)
    a_h = assigned_mask[:, :-1] & assigned_mask[:, 1:]
    border_h = diff_h & a_h
    borders[:, :-1] |= border_h
    borders[:, 1:] |= border_h

    borders = (
        borders
        | np.roll(borders, 1, axis=0) | np.roll(borders, -1, axis=0)
        | np.roll(borders, 1, axis=1) | np.roll(borders, -1, axis=1)
    )
    return borders


def _get_country_borders_cached(canvas):
    rgb = getattr(canvas, "_country_color_rgb", None)
    mask = getattr(canvas, "_country_assigned_mask", None)
    if rgb is None or mask is None:
        return None
    cache = getattr(canvas, "_state_country_borders_cache", None)
    key = (id(rgb), id(mask))
    if cache and cache[0] == key:
        return cache[1]
    borders = _compute_country_borders(rgb, mask)
    canvas._state_country_borders_cache = (key, borders)
    return borders


def _highlight_mask(country_rgb, assigned_mask, highlight_rgb):
    if country_rgb is None or assigned_mask is None or highlight_rgb is None:
        return None
    hr, hg, hb = highlight_rgb
    return (
        assigned_mask
        & (country_rgb[:, :, 0] == hr)
        & (country_rgb[:, :, 1] == hg)
        & (country_rgb[:, :, 2] == hb)
    )


def _fill_blended(buf, state_rgb, country_rgb, mask) -> None:
    """State color ⊗ National color 50/50 is written into the BGRA buffer. Only the state color is used in addition to the mask."""
    if state_rgb is None:
        buf[..., 0] = 40
        buf[..., 1] = 40
        buf[..., 2] = 40
        buf[..., 3] = 255
        return
    if country_rgb is not None and mask is not None:
        blend = (
            (state_rgb.astype(np.uint16) + country_rgb.astype(np.uint16)) >> 1
        ).astype(np.uint8)
        rgb = np.where(mask[..., None], blend, state_rgb)
    else:
        rgb = state_rgb
    buf[..., 0] = rgb[..., 2]  # B
    buf[..., 1] = rgb[..., 1]  # G
    buf[..., 2] = rgb[..., 0]  # R
    buf[..., 3] = 255


def _draw_borders(buf, borders) -> None:
    buf[borders, 0] = 255
    buf[borders, 1] = 255
    buf[borders, 2] = 255
    buf[borders, 3] = 255


def _draw_highlight(buf, hl_mask) -> None:
    """Select the national pixels and mix them with warm yellow in a ratio of 7:9 (yellow accounts for ~56%, retaining more original information than pure coloring)."""
    if hl_mask is None or not hl_mask.any():
        return
    cur = buf[hl_mask, :3].astype(np.uint16)
    new = (cur * 7 + _HL_BGR * 9) >> 4
    buf[hl_mask, :3] = new.astype(np.uint8)


def render(canvas) -> None:
    state_rgb = canvas._state_color_rgb
    country_rgb = getattr(canvas, "_country_color_rgb", None)
    mask = getattr(canvas, "_country_assigned_mask", None)
    highlight_rgb = getattr(canvas, "_highlight_country_rgb", None)

    _fill_blended(canvas._display_buffer, state_rgb, country_rgb, mask)

    borders = _get_country_borders_cached(canvas)
    if borders is not None:
        _draw_borders(canvas._display_buffer, borders)

    hl = _highlight_mask(country_rgb, mask, highlight_rgb)
    _draw_highlight(canvas._display_buffer, hl)


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    state_rgb = canvas._state_color_rgb
    country_rgb = getattr(canvas, "_country_color_rgb", None)
    mask = getattr(canvas, "_country_assigned_mask", None)
    highlight_rgb = getattr(canvas, "_highlight_country_rgb", None)

    buf = canvas._display_buffer[y0:y1, x0:x1]
    s_region = state_rgb[y0:y1, x0:x1] if state_rgb is not None else None
    c_region = country_rgb[y0:y1, x0:x1] if country_rgb is not None else None
    m_region = mask[y0:y1, x0:x1] if mask is not None else None
    _fill_blended(buf, s_region, c_region, m_region)

    borders_full = _get_country_borders_cached(canvas)
    if borders_full is not None:
        _draw_borders(buf, borders_full[y0:y1, x0:x1])

    hl_full = _highlight_mask(country_rgb, mask, highlight_rgb)
    if hl_full is not None:
        _draw_highlight(buf, hl_full[y0:y1, x0:x1])
