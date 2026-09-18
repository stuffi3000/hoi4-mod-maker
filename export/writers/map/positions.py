"""positions.txt writer with profile aware placement support."""
import os
import numpy as np
from export.writers.map._coords import safe_coord as _safe_coord
_REVIEWED = ("reviewed", "accepted")
_COMPAT_PROFILES = ("acceptance", "scaffold", "legacy_full")
_COMPAT_MARKER = "# generated placeholders for {profile} compatibility; reviewed manager records override where complete"
def _resolve_mgr(placement_manager, map_placement_mgr):
    if placement_manager is not None:
        return placement_manager
    return map_placement_mgr
def _reviewed_groups(mgr):
    groups = {}
    try:
        records = mgr.list_province_slots()
    except Exception:
        return {}
    if not records:
        return {}
    for rec in records:
        try:
            status = getattr(rec, "review_status", None)
        except Exception:
            continue
        if status not in _REVIEWED:
            continue
        try:
            pid = int(getattr(rec, "province_id"))
            slot = int(getattr(rec, "slot"))
        except Exception:
            continue
        if pid <= 0:
            continue
        if slot < 0 or slot > 5:
            continue
        by_slot = groups.setdefault(pid, {})
        if slot not in by_slot:
            by_slot[slot] = rec
    return groups
def _foundation_blocks(groups, map_h):
    blocks = {}
    for pid in sorted(groups):
        by_slot = groups[pid]
        if set(by_slot.keys()) != {0, 1, 2, 3, 4, 5}:
            continue
        try:
            ordered = [by_slot[i] for i in range(6)]
            pos_parts = []
            rot_parts = []
            h_parts = []
            for rec in ordered:
                x = float(getattr(rec, "x"))
                y = float(getattr(rec, "y"))
                rot = float(getattr(rec, "rotation", 0.0))
                h = float(getattr(rec, "height", 0.0))
                hoi4_z = float(map_h) - y
                pos_parts.append(f"{x:.3f} 9.500 {hoi4_z:.3f}")
                rot_parts.append(f"{rot:.3f}")
                h_parts.append(f"{h:.3f}")
        except Exception:
            continue
        positions = "\n\t\t".join(pos_parts)
        rotations = " ".join(rot_parts)
        heights = " ".join(h_parts)
        blocks[pid] = (
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
    return blocks
def _legacy_block(pid, cx, cy, map_h):
    hoi4_x = cx
    hoi4_z = map_h - cy
    y = 9.500
    pos_line = f"{hoi4_x:.3f} {y:.3f} {hoi4_z:.3f}"
    positions = "\n\t\t".join([pos_line] * 6)
    rotations = " ".join(["0.000"] * 6)
    heights = " ".join(["0.000"] * 6)
    return (
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
def write_positions_txt(province_map, tile_map, output_dir, pid_count=None, sum_x=None, sum_y=None, placement_manager=None, map_placement_mgr=None, profile_name=None):
    """Generate positions.txt for each province. Trailing placement args keep direct callers valid."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    province_count = int(province_map.max())
    if province_count == 0:
        return
    H, W = province_map.shape
    mgr = _resolve_mgr(placement_manager, map_placement_mgr)
    is_foundation = (mgr is not None and profile_name == "foundation")
    is_compat = (mgr is not None and profile_name in _COMPAT_PROFILES)
    if is_foundation:
        groups = _reviewed_groups(mgr)
        blocks = _foundation_blocks(groups, H)
        lines = [blocks[pid] for pid in sorted(blocks)]
        with open(os.path.join(d, "positions.txt"), "wb") as f:
            f.write("\n".join(lines).encode("utf-8"))
        return
    if pid_count is None:
        flat_pm = province_map.ravel()
        n = province_count + 1
        pid_count = np.bincount(flat_pm, minlength=n)
        ys_grid, xs_grid = np.mgrid[0:H, 0:W]
        sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=n)
        sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=n)
    legacy_ordered = []
    for pid in range(1, province_count + 1):
        if pid_count[pid] == 0:
            continue
        cx, cy = _safe_coord(pid, province_map, pid_count, sum_x, sum_y)
        legacy_ordered.append((pid, _legacy_block(pid, cx, cy, H)))
    if is_compat:
        groups = _reviewed_groups(mgr)
        fblocks = _foundation_blocks(groups, H)
        merged = []
        for pid, blk in legacy_ordered:
            if pid in fblocks:
                merged.append(fblocks[pid])
            else:
                merged.append(blk)
        marker = _COMPAT_MARKER.format(profile=profile_name)
        with open(os.path.join(d, "positions.txt"), "wb") as f:
            if merged:
                f.write((marker + "\n" + "\n".join(merged)).encode("utf-8"))
            else:
                f.write(marker.encode("utf-8"))
        return
    lines = [blk for _, blk in legacy_ordered]
    with open(os.path.join(d, "positions.txt"), "wb") as f:
        f.write("\n".join(lines).encode("utf-8"))
