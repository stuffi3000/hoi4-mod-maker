"""Province coordinate calculation tool - shared by buildings.txt and positions.txt."""
import numpy as np


def safe_coord(pid, province_map, pid_count, sum_x, sum_y):
    """Returns the coordinates (cx, cy) guaranteed to be inside (not at the edge) of the province's pixels.
    First try the center of mass. If the center of mass drifts to the next province, fall back to the geometric center pixel of the province.
    HOI4 has unstable coordinate matching for edge pixels and must use internal pixels."""
    cx = sum_x[pid] / pid_count[pid]
    cy = sum_y[pid] / pid_count[pid]
    icy, icx = int(round(cy)), int(round(cx))
    h, w = province_map.shape
    if 0 <= icy < h and 0 <= icx < w and province_map[icy, icx] == pid:
        return cx, cy
    # The center of mass is not within the province → find the geometric center (median of y, median of x)
    ys, xs = np.where(province_map == pid)
    if len(ys) == 0:
        return cx, cy
    my = float(np.median(ys))
    mx = float(np.median(xs))
    imy, imx = int(round(my)), int(round(mx))
    if 0 <= imy < h and 0 <= imx < w and province_map[imy, imx] == pid:
        return mx, my
    # The median does not work either (non-convex provinces), take the pixel in the province closest to the centroid
    dist = (ys.astype(float) - cy)**2 + (xs.astype(float) - cx)**2
    best = np.argmin(dist)
    return float(xs[best]), float(ys[best])
