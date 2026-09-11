"""One-off script: Clean up the scattered small hills in 5.hoi4proj and keep the big ridges.

Algorithm:
1. Connected component analysis of all "mountain type" pixels in terrain_map
2. Mark pixels of blob < BIG_BLOB_THRESHOLD as "scatter" → downgrade to hills (palette 17)
3. Lower the height_map of scatter pixels to 145 (hilly band)
4. Extreme peak of Snow height > 225 → pressed to 200
5. Find all provinces with provincial_terrain='mountain' but >70% of pixels in scatter points → reduce to hills
6. Preserve all pixels and attributes of large ridges

Save to 5.hoi4proj (original file), original backup in 5.hoi4proj.bak."""
from __future__ import annotations

import json
import os
import sys
import shutil
from collections import Counter
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
from scipy.ndimage import label

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.terrain_types import PALETTE_TO_TYPE

PROJECT_PATH = os.path.join(
    os.path.expanduser("~"), "Desktop", "Aurora", "5.hoi4proj"
)
BIG_BLOB_THRESHOLD = 2000   # Mountain patches with number of pixels < this value are considered "scatters" and downgraded
SNOW_TOP_CAP = 200          # The highest pressure of the snow mountain reaches this value (rather than completely reducing it to a mountain)
SNOW_HEIGHT_CUTOFF = 225    # Only handle > snow-capped mountains at this height
HILLS_HEIGHT_TARGET = 145   # Target altitude after downgrading in scattered mountain terrain


def main() -> None:
    assert os.path.exists(PROJECT_PATH), f"not found: {PROJECT_PATH}"
    print(f"Opening: {PROJECT_PATH}")

    # Read all entries
    entries: dict[str, bytes] = {}
    with ZipFile(PROJECT_PATH, "r") as zf:
        for name in zf.namelist():
            entries[name] = zf.read(name)

    tm = np.load(BytesIO(entries["terrain_map.npy"]))
    hm = np.load(BytesIO(entries["height_map.npy"]))
    tile = np.load(BytesIO(entries["tile_map.npy"]))
    pm = np.load(BytesIO(entries["province_map.npy"]))
    pt_raw = entries.get("provincial_terrain.json", b"{}").decode("utf-8")
    pt: dict[str, str] = json.loads(pt_raw)

    orig_tm = tm.copy()
    orig_hm = hm.copy()

    land_mask = tile == 1
    n_land = int(land_mask.sum())

    # —— Step 1: Mountain connected component ——
    mountain_palettes = [
        idx for idx, typ in PALETTE_TO_TYPE.items() if typ == "mountain"
    ]
    mountain_mask = np.isin(tm, mountain_palettes) & land_mask
    labels, n_blobs = label(mountain_mask, structure=np.ones((3, 3), dtype=bool))
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0  # background

    # scatter blob
    small_labels = np.where((sizes > 0) & (sizes < BIG_BLOB_THRESHOLD))[0]
    big_labels = np.where(sizes >= BIG_BLOB_THRESHOLD)[0]
    scatter_mask = np.isin(labels, small_labels)
    big_blob_mask = np.isin(labels, big_labels)

    print(f"Mountain blobs: {n_blobs} total")
    print(f"  big (>= {BIG_BLOB_THRESHOLD} px):  {len(big_labels):>4d}")
    print(f"  small (scatter):               {len(small_labels):>4d}")
    print(f"  scatter pixels: {int(scatter_mask.sum()):,d} "
          f"({scatter_mask.sum() / mountain_mask.sum() * 100:.1f}% of all mountains)")

    # —— Step 2: Downgrade the scattered pixels to hills_blend (17), and increase the height to 145 ——
    tm_new = tm.copy()
    hm_new = hm.copy()
    tm_new[scatter_mask] = 17  # hills_blend
    # Height: If original height > 145, press to 145; otherwise keep
    hm_sub = hm_new[scatter_mask]
    hm_new[scatter_mask] = np.minimum(hm_sub, HILLS_HEIGHT_TARGET).astype(np.uint8)

    # —— Step 3: Lower the top of Snow height ——
    # Only change the height, not the terrain (palette 16 is reserved, it is in the big ridge)
    snow_top_mask = (tm == 16) & (hm > SNOW_HEIGHT_CUTOFF) & land_mask
    hm_new[snow_top_mask] = SNOW_TOP_CAP
    n_snow_capped = int(snow_top_mask.sum())

    # —— Step 4: Downgrade the attribute layer provincial_terrain ——
    # Find provinces with "mountain type but >70% pixels in scatter"
    pt_new: dict[str, str] = dict(pt)
    mountain_pids = [int(pid) for pid, typ in pt.items() if typ == "mountain"]
    total_px = np.bincount(pm.ravel())
    scatter_px = np.bincount(pm[scatter_mask], minlength=total_px.size)
    big_blob_px = np.bincount(pm[big_blob_mask & mountain_mask],
                              minlength=total_px.size)

    downgraded_pids: list[int] = []
    for pid in mountain_pids:
        if pid <= 0 or pid >= total_px.size:
            continue
        total = total_px[pid]
        if total == 0:
            continue
        in_big = big_blob_px[pid]
        # Rules: If the pixels of the province in the large ridge are < 30% of the total area of the province → judged as a "scatter province" → downgraded to hills
        if in_big < 0.30 * total:
            pt_new[str(pid)] = "hills"
            downgraded_pids.append(pid)

    print(f"\nProvince attribute downgrade:")
    print(f"  mountain provinces before: {len(mountain_pids)}")
    print(f"  downgraded to hills:       {len(downgraded_pids)}")
    print(f"  mountain provinces after:  {len(mountain_pids) - len(downgraded_pids)}")
    print(f"\nSnow peaks capped to {SNOW_TOP_CAP}: {n_snow_capped:,d} pixels")

    # Total statistics
    new_mountain_type_pixels = int(np.isin(tm_new,
                                           [idx for idx, t in PALETTE_TO_TYPE.items() if t == "mountain"]).sum())
    print(f"\nMountain-type visual pixels:")
    print(f"  before: {int(mountain_mask.sum()):>10,d} ({mountain_mask.sum() / n_land * 100:.2f}%)")
    print(f"  after:  {new_mountain_type_pixels:>10,d} "
          f"({new_mountain_type_pixels / n_land * 100:.2f}%)")

    # —— Step 5: Write back to zip ——
    entries["terrain_map.npy"] = _np_to_bytes(tm_new)
    entries["height_map.npy"] = _np_to_bytes(hm_new)
    entries["provincial_terrain.json"] = json.dumps(
        pt_new, ensure_ascii=False, indent=2
    ).encode("utf-8")

    tmp_path = PROJECT_PATH + ".tmp"
    with ZipFile(tmp_path, "w", ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    shutil.move(tmp_path, PROJECT_PATH)
    print(f"\nSaved: {PROJECT_PATH}")


def _np_to_bytes(arr: np.ndarray) -> bytes:
    buf = BytesIO()
    np.save(buf, arr)
    return buf.getvalue()


if __name__ == "__main__":
    main()
