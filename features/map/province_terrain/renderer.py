"""province_terrain mode rendering: fills each province with the gameplay terrain color.

Depends on canvas._provincial_terrain_color_rgb precomputed RGB array (updated by app_controller trigger)."""


def render(canvas) -> None:
    if canvas._provincial_terrain_color_rgb is not None:
        canvas._display_buffer[:, :, 0] = canvas._provincial_terrain_color_rgb[:, :, 2]
        canvas._display_buffer[:, :, 1] = canvas._provincial_terrain_color_rgb[:, :, 1]
        canvas._display_buffer[:, :, 2] = canvas._provincial_terrain_color_rgb[:, :, 0]
        canvas._display_buffer[:, :, 3] = 255
    else:
        canvas._display_buffer[:, :, 0] = 40
        canvas._display_buffer[:, :, 1] = 40
        canvas._display_buffer[:, :, 2] = 40
        canvas._display_buffer[:, :, 3] = 255


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    buf = canvas._display_buffer[y0:y1, x0:x1]
    if canvas._provincial_terrain_color_rgb is not None:
        region = canvas._provincial_terrain_color_rgb[y0:y1, x0:x1]
        buf[:, :, 0] = region[:, :, 2]
        buf[:, :, 1] = region[:, :, 1]
        buf[:, :, 2] = region[:, :, 0]
        buf[:, :, 3] = 255
    else:
        buf[:, :, :] = [40, 40, 40, 255]
