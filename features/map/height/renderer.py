"""Height mode rendering: height_map → color (reuse views.canvas.luts._HEIGHT_COLOR_LUT).

The editor uses colored terrain maps to easily distinguish height from low, and the exported heightmap.bmp is still grayscale."""

from views.canvas.luts import _HEIGHT_COLOR_LUT


def render(canvas) -> None:
    buf = canvas._display_buffer
    hm = canvas._height_map
    bh, bw = buf.shape[:2]
    mh, mw = hm.shape[:2]
    if (bh, bw) == (mh, mw):
        buf[:] = _HEIGHT_COLOR_LUT[hm]
    else:
        rh, rw = min(bh, mh), min(bw, mw)
        buf[:rh, :rw] = _HEIGHT_COLOR_LUT[hm[:rh, :rw]]


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    hm = canvas._height_map
    mh, mw = hm.shape[:2]
    x1 = min(x1, mw)
    y1 = min(y1, mh)
    if x0 >= x1 or y0 >= y1:
        return
    canvas._display_buffer[y0:y1, x0:x1] = _HEIGHT_COLOR_LUT[hm[y0:y1, x0:x1]]
