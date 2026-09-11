"""positions.txt — Provincial unit/text/city/port position coordinates."""
import os
import numpy as np
# The size is taken from province_map.shape, no need to use from data.constants import MAP_* (from import
# It is value binding, it will not be updated after set_map_size, and an error will occur if the map is not the default size).


from export.writers.map._coords import safe_coord as _safe_coord


def write_positions_txt(province_map: np.ndarray,
                        tile_map: np.ndarray,
                        output_dir: str,
                        pid_count=None, sum_x=None, sum_y=None) -> None:
    """Generate positions.txt for each province.
    If the precalculated pid_count/sum_x/sum_y is passed in, use it directly; otherwise, calculate it yourself."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)

    province_count = int(province_map.max())
    if province_count == 0:
        return

    H, W = province_map.shape
    # Use precomputed data, or calculate it yourself
    if pid_count is None:
        flat_pm = province_map.ravel()
        n = province_count + 1
        pid_count = np.bincount(flat_pm, minlength=n)
        ys_grid, xs_grid = np.mgrid[0:H, 0:W]
        sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=n)
        sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=n)

    lines = []
    for pid in range(1, province_count + 1):
        if pid_count[pid] == 0:
            continue
        cx, cy = _safe_coord(pid, province_map, pid_count, sum_x, sum_y)
        # Convert to HOI4 coordinate system: Z from bottom
        hoi4_x = cx
        hoi4_z = H - cy
        y = 9.500

        # All 6 position slots use the center of mass
        pos_line = f"{hoi4_x:.3f} {y:.3f} {hoi4_z:.3f}"
        positions = "\n\t\t".join([pos_line] * 6)
        rotations = " ".join(["0.000"] * 6)
        heights = " ".join(["0.000"] * 6)

        lines.append(
            f"{pid}={{\n"
            f"\tposition={{\n"
            f"\t\t{positions}\n"
            f"\t}}\n"
            f"\trotation={{\n"
            f"\t\t{rotations}\n"
            f"\t}}\n"
            f"\theight={{\n"
            f"\t\t{heights}\n"
            f"\t}}\n"
            f"}}"
        )

    # Write in binary mode to avoid automatic conversion of \n → \r\n on Windows
    with open(os.path.join(d, "positions.txt"), "wb") as f:
        f.write("\n".join(lines).encode("utf-8"))
