"""v3: Build a wall according to "Full Strip", and then dig a channel.

A. Hadrian-Carralian wall: horizontal strips (x=2850-3550, y=870-960), channels x=3320-3420
C. East wall: vertical strip (x=4430-4560, y=870-1500), channel y=1200-1300
B. Middle section: immobile

Wall = land pixels raised to 215 (snowy mountains), channel = dropped to 115 (plains).
Edge Feather 15 px. Keep the land and sea boundaries, don't change the sea."""
from __future__ import annotations

import os
import shutil
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
from scipy.ndimage import distance_transform_edt

HOME = os.path.expanduser("~")
PROJECT_PATH = os.path.join(HOME, "Desktop", "Aurora", "5.hoi4proj")
BACKUP_PATH = PROJECT_PATH + ".bak"
SEA_LEVEL = 95
WALL_H = 215          # Snow mountain stall
PASS_H = 115          # plain file
FEATHER = 15

WALLS = [
    # NW horizontal strip wall (between Hadrian and Caralia)
    {
        "name": "NW Hadrian-Calabria Wall",
        "wall_bbox": (2850, 870, 3550, 960),    # x0 y0 x1 y1 — wall body
        "pass_bbox": (3320, 870, 3420, 960),    # channel
        "palette": 16,                           # snow mountain
    },
    # E Vertical Strip Wall (East Orc Blocker)
    {
        "name": "East Orc Wall",
        "wall_bbox": (4430, 870, 4560, 1500),
        "pass_bbox": (4430, 1200, 4560, 1300),
        "palette": 16,
    },
]


def apply_wall(
    tile: np.ndarray,
    terrain: np.ndarray,
    height: np.ndarray,
    wall_bbox: tuple[int, int, int, int],
    pass_bbox: tuple[int, int, int, int],
    palette: int,
) -> tuple[int, int]:
    """Fill wall + dig channel, only works on land. Return (wall px, channel px)."""
    H, W = tile.shape

    # mask
    def _box_mask(bbox):
        m = np.zeros((H, W), dtype=bool)
        x0, y0, x1, y1 = bbox
        x0 = max(0, x0); y0 = max(0, y0); x1 = min(W, x1); y1 = min(H, y1)
        m[y0:y1, x0:x1] = True
        return m

    wall_mask = _box_mask(wall_bbox)
    pass_mask = _box_mask(pass_bbox)
    land = tile == 1

    # wall = wall_bbox − pass_bbox (only moves land)
    wall_apply = wall_mask & ~pass_mask & land
    pass_apply = pass_mask & land

    n_wall = int(wall_apply.sum())
    n_pass = int(pass_apply.sum())
    if n_wall == 0 and n_pass == 0:
        return 0, 0

    # 1) Wall: height raised to WALL_H, edge FEATHER pixel feathering
    if n_wall > 0:
        dist_in = distance_transform_edt(wall_apply).astype(np.float32)
        w = np.minimum(dist_in / FEATHER, 1.0)
        target = np.full_like(height, WALL_H, dtype=np.float32)
        new_h = height.astype(np.float32) * (1 - w) + target * w
        # Only applied within wall_apply, and can only be raised but not lowered (retaining original pixels higher than the wall)
        height[wall_apply] = np.maximum(
            height[wall_apply],
            new_h[wall_apply].astype(np.uint8),
        )
        terrain[wall_apply] = palette

    # 2) Passage: height reduced to PASS_H, feathering
    if n_pass > 0:
        dist_in = distance_transform_edt(pass_apply).astype(np.float32)
        w = np.minimum(dist_in / FEATHER, 1.0)
        target = np.full_like(height, PASS_H, dtype=np.float32)
        new_h = height.astype(np.float32) * (1 - w) + target * w
        # Within the channel, high pixels are reduced, while low pixels are retained.
        height[pass_apply] = np.minimum(
            height[pass_apply],
            new_h[pass_apply].astype(np.uint8),
        )
        # Passage topography: mountains turn into hills, snowy mountains turn into mountains
        terr_in_pass = terrain[pass_apply]
        was_snow = np.isin(terr_in_pass, [16, 19, 31])
        was_mtn = np.isin(terr_in_pass, [6, 10, 11, 18, 20, 27])
        new_terr = terr_in_pass.copy()
        new_terr[was_snow] = 6
        new_terr[was_mtn] = 17
        terrain[pass_apply] = new_terr

    # Keep the bottom line
    np.maximum(height, SEA_LEVEL + 1, out=height, where=land)
    return n_wall, n_pass


def main():
    if not os.path.exists(BACKUP_PATH):
        shutil.copy2(PROJECT_PATH, BACKUP_PATH)
        print(f"Backup created: {BACKUP_PATH}")
    else:
        print(f"Backup exists: {BACKUP_PATH}")

    entries = {}
    with ZipFile(PROJECT_PATH, "r") as zf:
        for name in zf.namelist():
            entries[name] = zf.read(name)

    tile = np.load(BytesIO(entries["tile_map.npy"])).copy()
    terrain = np.load(BytesIO(entries["terrain_map.npy"])).copy()
    height = np.load(BytesIO(entries["height_map.npy"])).copy()

    for w in WALLS:
        n_wall, n_pass = apply_wall(
            tile, terrain, height,
            wall_bbox=w["wall_bbox"],
            pass_bbox=w["pass_bbox"],
            palette=w["palette"],
        )
        print(f"  {w['name']}: wall {n_wall:,d} px, passage {n_pass:,d} px")

    entries["tile_map.npy"] = _to_bytes(tile)
    entries["terrain_map.npy"] = _to_bytes(terrain)
    entries["height_map.npy"] = _to_bytes(height)

    tmp = PROJECT_PATH + ".tmp"
    with ZipFile(tmp, "w", ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    shutil.move(tmp, PROJECT_PATH)
    print(f"\nSaved: {PROJECT_PATH}")


def _to_bytes(arr):
    buf = BytesIO()
    np.save(buf, arr)
    return buf.getvalue()


if __name__ == "__main__":
    main()
