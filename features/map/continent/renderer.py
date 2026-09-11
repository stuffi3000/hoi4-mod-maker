"""Continent mode rendering: Continental partition color map."""


def render(canvas) -> None:
    rgb = getattr(canvas, "_continent_color_rgb", None)
    if rgb is not None:
        canvas._display_buffer[:, :, 0] = rgb[:, :, 2]
        canvas._display_buffer[:, :, 1] = rgb[:, :, 1]
        canvas._display_buffer[:, :, 2] = rgb[:, :, 0]
        canvas._display_buffer[:, :, 3] = 255
    else:
        canvas._display_buffer[:, :, 0] = 40
        canvas._display_buffer[:, :, 1] = 40
        canvas._display_buffer[:, :, 2] = 40
        canvas._display_buffer[:, :, 3] = 255


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    buf = canvas._display_buffer[y0:y1, x0:x1]
    rgb = getattr(canvas, "_continent_color_rgb", None)
    if rgb is not None:
        region = rgb[y0:y1, x0:x1]
        buf[:, :, 0] = region[:, :, 2]
        buf[:, :, 1] = region[:, :, 1]
        buf[:, :, 2] = region[:, :, 0]
        buf[:, :, 3] = 255
    else:
        buf[:, :, :] = [40, 40, 40, 255]
