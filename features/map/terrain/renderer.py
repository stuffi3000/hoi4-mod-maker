"""Terrain mode rendering: terrain_map → color LUT."""


def render(canvas) -> None:
    from ui.canvas_widget import _TERRAIN_COLOR_LUT
    buf = canvas._display_buffer
    tm = canvas._terrain_map
    bh, bw = buf.shape[:2]
    mh, mw = tm.shape[:2]
    if (bh, bw) == (mh, mw):
        buf[:] = _TERRAIN_COLOR_LUT[tm]
    else:
        rh, rw = min(bh, mh), min(bw, mw)
        buf[:rh, :rw] = _TERRAIN_COLOR_LUT[tm[:rh, :rw]]


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    from ui.canvas_widget import _TERRAIN_COLOR_LUT
    tm = canvas._terrain_map
    mh, mw = tm.shape[:2]
    x1 = min(x1, mw)
    y1 = min(y1, mh)
    if x0 >= x1 or y0 >= y1:
        return
    canvas._display_buffer[y0:y1, x0:x1] = (
        _TERRAIN_COLOR_LUT[tm[y0:y1, x0:x1]]
    )
