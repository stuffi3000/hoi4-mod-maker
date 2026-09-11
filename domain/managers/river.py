"""Storage, palette definitions, and validation for HOI4 ``rivers.bmp``."""
import numpy as np


# Vanilla river palette indices.
RIVER_SOURCE = 0
RIVER_MARKER = 1
RIVER_MOUTH = 2
RIVER_WIDTH_1 = 3
RIVER_WIDTH_2 = 4
RIVER_WIDTH_3 = 5
RIVER_WIDTH_4 = 6
RIVER_WIDTH_5 = 7
RIVER_WIDTH_6 = 8
RIVER_WIDTH_7 = 9
RIVER_WIDTH_8 = 10
RIVER_WIDTH_9 = 11

RIVER_BG_SEA = 254
RIVER_BG_LAND = 255
RIVER_ERASE = RIVER_BG_LAND

RIVER_PALETTE = {
    0: (0, 255, 0),
    1: (255, 0, 0),
    2: (255, 252, 0),
    3: (0, 225, 255),
    4: (0, 200, 255),
    5: (0, 150, 255),
    6: (0, 100, 255),
    7: (0, 0, 255),
    8: (0, 0, 225),
    9: (0, 0, 200),
    10: (0, 0, 150),
    11: (0, 0, 100),
    12: (0, 85, 0),
    13: (0, 125, 0),
    14: (0, 158, 0),
    15: (24, 206, 0),
    254: (122, 122, 122),
    255: (255, 255, 255),
}

RIVER_DISPLAY_COLORS = {
    index: (blue, green, red, 255)
    for index, (red, green, blue) in RIVER_PALETTE.items()
}

# Marker entries are single-pixel controls; width entries are brush values.
RIVER_MARKER_TYPES = [
    (RIVER_SOURCE, "river_marker_source"),
    (RIVER_MARKER, "river_marker_confluence"),
    (RIVER_MOUTH, "river_marker_mouth"),
]

# Vanilla does not use indices 5 and 8 for hand-drawn river widths.
RIVER_WIDTH_TYPES = [
    (RIVER_WIDTH_1, "river_width_1"),
    (RIVER_WIDTH_2, "river_width_2"),
    (RIVER_WIDTH_4, "river_width_4"),
    (RIVER_WIDTH_5, "river_width_5"),
    (RIVER_WIDTH_7, "river_width_7"),
    (RIVER_WIDTH_8, "river_width_8"),
    (RIVER_WIDTH_9, "river_width_9"),
]

PAINTABLE_RIVER_TYPES = RIVER_MARKER_TYPES + RIVER_WIDTH_TYPES
VALID_RIVER_VALUES = set(range(0, 12))


def validate_rivers(river_map: np.ndarray, lang: str = "en") -> list[str]:
    """Validate river connectivity, width, source markers, and diagonal joins.

    ``lang`` remains as a compatibility argument for callers from older project
    files. Validation messages are always English in the current application.
    """
    from scipy.ndimage import label

    warnings: list[str] = []
    river_mask = np.zeros_like(river_map, dtype=bool)
    for value in VALID_RIVER_VALUES:
        river_mask |= river_map == value

    if not np.any(river_mask):
        return ["No river data"]

    structure = np.ones((3, 3), dtype=int)
    labeled, river_count = label(river_mask, structure=structure)
    pixel_counts = np.bincount(labeled.ravel(), minlength=river_count + 1)
    source_counts = np.bincount(
        labeled[river_map == RIVER_SOURCE].ravel(), minlength=river_count + 1
    )
    for river_id in range(1, river_count + 1):
        if source_counts[river_id] == 0:
            pixel_count = int(pixel_counts[river_id])
            warnings.append(
                f"River #{river_id} ({pixel_count}px): missing source marker (green)"
            )

    # A solid 2x2 block indicates a river wider than one pixel.
    river_pixels = river_mask.astype(np.uint8)
    block_sum = (
        river_pixels[:-1, :-1]
        + river_pixels[:-1, 1:]
        + river_pixels[1:, :-1]
        + river_pixels[1:, 1:]
    )
    wide_pixels = int((block_sum >= 4).sum())
    if wide_pixels:
        warnings.append(
            f"{wide_pixels} places where river is wider than 1 pixel (2x2 solid block)"
        )

    # Find diagonal-only contacts that have no orthogonal bridge.
    diagonal_count = 0
    ys, xs = np.where(river_mask)
    height, width = river_map.shape
    for dy, dx in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
        neighbor_y, neighbor_x = ys + dy, xs + dx
        valid = (
            (neighbor_y >= 0)
            & (neighbor_y < height)
            & (neighbor_x >= 0)
            & (neighbor_x < width)
        )
        has_diagonal = valid & river_mask[
            np.clip(neighbor_y, 0, height - 1), np.clip(neighbor_x, 0, width - 1)
        ]

        first_y, first_x = ys + dy, xs
        second_y, second_x = ys, xs + dx
        valid_first = (
            (first_y >= 0) & (first_y < height) & (first_x >= 0) & (first_x < width)
        )
        valid_second = (
            (second_y >= 0)
            & (second_y < height)
            & (second_x >= 0)
            & (second_x < width)
        )
        has_first = valid_first & river_mask[
            np.clip(first_y, 0, height - 1), np.clip(first_x, 0, width - 1)
        ]
        has_second = valid_second & river_mask[
            np.clip(second_y, 0, height - 1), np.clip(second_x, 0, width - 1)
        ]
        diagonal_count += int((has_diagonal & ~has_first & ~has_second).sum())

    if diagonal_count:
        warnings.append(
            f"{diagonal_count // 2} diagonal connections found (should be orthogonal)"
        )

    if not warnings:
        warnings.append("River validation passed ✓")
    return warnings
