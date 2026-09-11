"""Apply the JSON exported by region_annotator.html to 5.hoi4proj.

Usage:
    1. Save the "copy to clipboard" JSON in the web page as tools/regions.json
       (Or pass the path directly in the command line parameter)
    2. python tools/apply_regions.py [regions.json]

Application rules (effects for each type):
    mountain → terrain palette=6, height ~=185 (middle of mountain band)
    snow → terrain palette=16, height ~=225
    hills → terrain palette=17, height ~=145
    plains → terrain palette=0, height ~=108 (reduces abrupt height)
    forest → terrain palette=1, height ~=118
    desert → terrain palette=3, height ~=110
    downgrade → Downgrade the mountain/snow mountain by one level (retaining the approximate location), and decrease the height by the corresponding amount
    sea → tile_map=2, height=60
    lake → tile_map=3, height=90

Border feathering:
    All height modifications are feathered by 10 pixels on the edges of the mask to avoid hard cuts
    (keep bottom line >= SEA_LEVEL+1)"""
from __future__ import annotations

import json
import os
import shutil
import sys
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
from scipy.ndimage import binary_dilation, distance_transform_edt

HOME = os.path.expanduser("~")
PROJECT_PATH = os.path.join(HOME, "Desktop", "Aurora", "5.hoi4proj")
BACKUP_PATH = PROJECT_PATH + ".bak"
SEA_LEVEL = 95
FEATHER = 10   # pixels, height gradient width

# type → (palette, target_height, is_land)
TYPE_SPECS: dict[str, tuple[int, int, bool]] = {
    "mountain": (6,   185, True),
    "snow":     (16,  225, True),
    "hills":    (17,  145, True),
    "plains":   (0,   108, True),
    "forest":   (1,   118, True),
    "desert":   (3,   110, True),
    # sea/lake special treatment
    "sea":      (15,  60,  False),
    "lake":     (14,  90,  False),
}


def polygon_mask(points: list[list[float]], h: int, w: int) -> np.ndarray:
    """Ray filled polygon -> bool mask."""
    if len(points) < 3:
        return np.zeros((h, w), dtype=bool)
    ys = np.array([p[1] for p in points], dtype=np.float32)
    xs = np.array([p[0] for p in points], dtype=np.float32)
    y_min = max(0, int(ys.min()) - 1)
    y_max = min(h, int(ys.max()) + 2)
    x_min = max(0, int(xs.min()) - 1)
    x_max = min(w, int(xs.max()) + 2)
    mask = np.zeros((h, w), dtype=bool)
    if y_max <= y_min or x_max <= x_min:
        return mask
    n = len(points)
    for y in range(y_min, y_max):
        x_crossings = []
        y_line = y + 0.5
        for i in range(n):
            y0, x0 = ys[i], xs[i]
            y1, x1 = ys[(i + 1) % n], xs[(i + 1) % n]
            if (y0 <= y_line) == (y1 <= y_line):
                continue
            if y1 == y0:
                continue
            t = (y_line - y0) / (y1 - y0)
            x_cross = x0 + t * (x1 - x0)
            x_crossings.append(x_cross)
        if not x_crossings:
            continue
        x_crossings.sort()
        for i in range(0, len(x_crossings) - 1, 2):
            xa = max(x_min, int(np.ceil(x_crossings[i])))
            xb = min(x_max, int(np.floor(x_crossings[i + 1])) + 1)
            if xb > xa:
                mask[y, xa:xb] = True
    return mask


def line_mask(
    points: list[list[float]],
    h: int,
    w: int,
    width: int,
) -> np.ndarray:
    """Polyline + Dilation = Ridge mask."""
    if len(points) < 2:
        return np.zeros((h, w), dtype=bool)
    mask = np.zeros((h, w), dtype=bool)
    for i in range(len(points) - 1):
        x0, y0 = int(points[i][0]), int(points[i][1])
        x1, y1 = int(points[i + 1][0]), int(points[i + 1][1])
        _bres(mask, y0, x0, y1, x1)
    # Expansion radius = width/2
    from scipy.ndimage import binary_dilation
    from scipy.ndimage import generate_binary_structure
    r = max(1, width // 2)
    # Use circular structural elements
    yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
    struct = (yy * yy + xx * xx <= r * r)
    return binary_dilation(mask, structure=struct)


def _bres(mask: np.ndarray, y0: int, x0: int, y1: int, x1: int) -> None:
    """Bresenham draws the line."""
    h, w = mask.shape
    dx = abs(x1 - x0); dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        if 0 <= y0 < h and 0 <= x0 < w:
            mask[y0, x0] = True
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy; x0 += sx
        if e2 < dx:
            err += dx; y0 += sy


def apply_region(
    tile: np.ndarray,
    terrain: np.ndarray,
    height: np.ndarray,
    mask: np.ndarray,
    type_name: str,
) -> None:
    """Press type to change the mask area to the corresponding terrain. Modify in place."""
    if not np.any(mask):
        return

    if type_name == "downgrade":
        # Special: Recognize mountains/snowy mountains and downgrade one level
        snow_mask = mask & (terrain == 16)
        mountain_mask = mask & np.isin(terrain, [6, 10, 11, 18, 20, 27, 31])
        hills_mask = mask & np.isin(terrain, [17, 2, 8])
        # snow→mountain, mountain→hill, hill→flat
        terrain[snow_mask] = 6
        terrain[mountain_mask] = 17
        terrain[hills_mask] = 0
        # Altitude synchronized descent (with feathering)
        _lower_height_feathered(height, snow_mask, drop=45)
        _lower_height_feathered(height, mountain_mask, drop=35)
        _lower_height_feathered(height, hills_mask, drop=30)
        # Keep the bottom line on land
        land_in = mask & (tile == 1)
        np.maximum(height, SEA_LEVEL + 1, out=height, where=land_in)
        return

    spec = TYPE_SPECS.get(type_name)
    if spec is None:
        print(f"[warn] unknown type: {type_name}")
        return
    palette, target_h, is_land = spec

    if is_land:
        # Change the sea in the mask to land
        tile[mask & (tile != 1)] = 1
        terrain[mask] = palette
        _set_height_feathered(height, mask, target_h, tile_land_only=True, tile=tile)
        # Keep the bottom line
        np.maximum(height, SEA_LEVEL + 1, out=height, where=mask)
    else:
        # Sea/Lake: Change tile, lower height
        if type_name == "sea":
            tile[mask] = 2
            terrain[mask] = 15
        elif type_name == "lake":
            tile[mask] = 3
            terrain[mask] = 14
        _set_height_feathered(height, mask, target_h, tile_land_only=False, tile=tile)


def _lower_height_feathered(
    height: np.ndarray,
    mask: np.ndarray,
    drop: int,
) -> None:
    """Height of the mask area -= drop, edge FEATHER pixel feathering. Not lower than sea level."""
    if not np.any(mask):
        return
    dist_in = distance_transform_edt(mask).astype(np.float32)
    w = np.minimum(dist_in / FEATHER, 1.0)  # 0..1
    new_h = height.astype(np.float32) - drop * w
    new_h = np.clip(new_h, SEA_LEVEL + 1, 255)
    height[mask] = new_h[mask].astype(np.uint8)


def _set_height_feathered(
    height: np.ndarray,
    mask: np.ndarray,
    target: int,
    tile_land_only: bool,
    tile: np.ndarray,
) -> None:
    """Smoothly transition the inner height of the mask to the target. Edge FEATHER pixel feathering maintains the original height."""
    if not np.any(mask):
        return
    dist_in = distance_transform_edt(mask).astype(np.float32)
    w = np.minimum(dist_in / FEATHER, 1.0)  # Inside mask: 0 edge, 1 center
    orig = height.astype(np.float32)
    new_h = orig * (1 - w) + float(target) * w
    new_h = np.clip(new_h, 0, 255)
    if tile_land_only:
        new_h = np.maximum(new_h, SEA_LEVEL + 1)
    height[mask] = new_h[mask].astype(np.uint8)


def main() -> None:
    # path resolution
    if len(sys.argv) > 1:
        json_path = sys.argv[1]
    else:
        json_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "regions.json"
        )
    assert os.path.exists(json_path), f"not found: {json_path}"

    # backup
    if not os.path.exists(BACKUP_PATH):
        shutil.copy2(PROJECT_PATH, BACKUP_PATH)
        print(f"Backup created: {BACKUP_PATH}")
    else:
        print(f"Backup already exists: {BACKUP_PATH}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    regions = data.get("regions", [])
    print(f"Loaded {len(regions)} regions from {json_path}")

    # Read project
    entries: dict[str, bytes] = {}
    with ZipFile(PROJECT_PATH, "r") as zf:
        for name in zf.namelist():
            entries[name] = zf.read(name)

    tile = np.load(BytesIO(entries["tile_map.npy"])).copy()
    terrain = np.load(BytesIO(entries["terrain_map.npy"])).copy()
    height = np.load(BytesIO(entries["height_map.npy"])).copy()
    h, w = tile.shape

    # Apply each region
    for i, r in enumerate(regions):
        type_name = r.get("type")
        mode = r.get("mode", "polygon")
        points = r.get("points", [])
        if mode == "line":
            mask = line_mask(points, h, w, r.get("width", 80))
        else:
            mask = polygon_mask(points, h, w)
        n = int(mask.sum())
        print(f"  [{i+1}/{len(regions)}] {type_name:<10} ({mode}, {len(points)} pts) "
              f"→ {n:,d} px")
        apply_region(tile, terrain, height, mask, type_name)

    # write back
    entries["tile_map.npy"] = _np_to_bytes(tile)
    entries["terrain_map.npy"] = _np_to_bytes(terrain)
    entries["height_map.npy"] = _np_to_bytes(height)

    tmp = PROJECT_PATH + ".tmp"
    with ZipFile(tmp, "w", ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    shutil.move(tmp, PROJECT_PATH)
    print(f"\nApplied. Saved: {PROJECT_PATH}")
    print(f"Rollback: cp {BACKUP_PATH} {PROJECT_PATH}")


def _np_to_bytes(arr: np.ndarray) -> bytes:
    buf = BytesIO()
    np.save(buf, arr)
    return buf.getvalue()


if __name__ == "__main__":
    main()
