"""Province mode rendering: maps to color LUT by province ID."""


def render(canvas) -> None:
    from ui.canvas_widget import _PROVINCE_COLOR_LUT, _PROVINCE_COLOR_LUT_SIZE
    indices = canvas._province_map % _PROVINCE_COLOR_LUT_SIZE
    canvas._display_buffer[:] = _PROVINCE_COLOR_LUT[indices]


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    from ui.canvas_widget import _PROVINCE_COLOR_LUT, _PROVINCE_COLOR_LUT_SIZE
    indices = canvas._province_map[y0:y1, x0:x1] % _PROVINCE_COLOR_LUT_SIZE
    canvas._display_buffer[y0:y1, x0:x1] = _PROVINCE_COLOR_LUT[indices]
