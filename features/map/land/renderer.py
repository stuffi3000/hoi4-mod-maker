"""Land mode rendering: tile_map (land/sea/lake) → BGRA display buffer.

Pixels on new_land_mask will be overlaid with an extra layer of bright yellow (BGRA), allowing users to
You can see at a glance the area that has just been drawn but has not yet generated a province."""

# New World Highlight Color (BGRA) - bright yellow, distinguished from ordinary land green
_NEW_LAND_HIGHLIGHT = (60, 230, 255, 255)


def _overlay_new_land(canvas, buf, region_mask=None, y0: int = 0, x0: int = 0) -> None:
    """Cover the pixels of new_land_mask with the highlight color. region_mask optional, used for local rendering."""
    nlm = getattr(canvas, "new_land_mask", None)
    if nlm is None or not nlm.any():
        return
    if region_mask is None:
        mask = nlm
    else:
        mask = nlm[y0:y0 + buf.shape[0], x0:x0 + buf.shape[1]]
    if not mask.any():
        return
    b, g, r, a = _NEW_LAND_HIGHLIGHT
    buf[mask, 0] = b
    buf[mask, 1] = g
    buf[mask, 2] = r
    buf[mask, 3] = a


def render(canvas) -> None:
    from ui.canvas_widget import _TILE_BGRA
    for tile_type, (b, g, r, a) in _TILE_BGRA.items():
        mask = canvas._tile_map == tile_type
        canvas._display_buffer[mask, 0] = b
        canvas._display_buffer[mask, 1] = g
        canvas._display_buffer[mask, 2] = r
        canvas._display_buffer[mask, 3] = a
    _overlay_new_land(canvas, canvas._display_buffer)


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    from ui.canvas_widget import _TILE_BGRA
    region = canvas._tile_map[y0:y1, x0:x1]
    buf = canvas._display_buffer[y0:y1, x0:x1]
    for tile_type, (b, g, r, a) in _TILE_BGRA.items():
        mask = region == tile_type
        buf[mask, 0] = b
        buf[mask, 1] = g
        buf[mask, 2] = r
        buf[mask, 3] = a
    _overlay_new_land(canvas, buf, region_mask=True, y0=y0, x0=x0)
