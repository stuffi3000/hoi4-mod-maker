"""Dissolve artificial anchor circles from Belgium Map v1.1.

``rework_belgium_map_provinces.py`` reserved compact cores around victory
points and other position-sensitive province IDs.  Those cores preserved map
positions well, but their circular geometry is visually intrusive.  This
follow-up tool propagates the surrounding split provinces through every such
core and gives the original province ID to the surrounding child whose map
position stays closest to the old anchor.  The surrounding province
subdivision is otherwise retained.

The tool also restores the pre-rework graphical terrain, restores original
provincial terrain attributes, compacts only generated child IDs, and rebuilds
railway endpoints on adjacent children of the same original province pair.

Run without ``--apply`` to inspect the plan.  A real run writes a sibling
``.city_circle_cleanup.bak`` before replacing the project atomically.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.constants import MIN_PROVINCE_PIXELS
from domain.validators.province import validate_provinces
from export.writers.map._coords import safe_coord
from tools.rework_belgium_map_provinces import (
    ReworkError,
    _array_bytes,
    _country_raster,
    _json_bytes,
    _load_archive,
    _load_array,
    _pid_statistics,
    _position_sensitive_ids,
    _province_adjacency_codes,
    _remap_railways,
    _repair_non_contiguous_within_parents,
    _repair_x_crossings_within_parents,
    _safe_pixel,
    _state_raster,
    _write_archive_atomic,
)


DEFAULT_PROJECT = ROOT / "projects" / "Belgium_Map_v1_1.hoi4proj"
DEFAULT_BASELINE = ROOT / "projects" / "Belgium_Map_v1_1.hoi4proj.province_rework.bak"
DEFAULT_REPORT = ROOT / "projects" / "Belgium_Map_v1_1.city_circle_cleanup.json"


def _unique_mapped(values: list[int], mapping: dict[int, int]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for raw_value in values:
        value = mapping[int(raw_value)]
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _mask_safe_coordinate(
    mask: np.ndarray, row_offset: int, column_offset: int
) -> tuple[float, float]:
    """Return the exporter-style safe coordinate for one local province mask."""
    rows, columns = np.where(mask)
    if not rows.size:
        raise ReworkError("Cannot calculate a coordinate for an empty province")
    center_row = float(rows.mean())
    center_column = float(columns.mean())
    rounded_row = int(round(center_row))
    rounded_column = int(round(center_column))
    if (
        0 <= rounded_row < mask.shape[0]
        and 0 <= rounded_column < mask.shape[1]
        and mask[rounded_row, rounded_column]
    ):
        return column_offset + center_column, row_offset + center_row
    median_row = float(np.median(rows))
    median_column = float(np.median(columns))
    rounded_row = int(round(median_row))
    rounded_column = int(round(median_column))
    if (
        0 <= rounded_row < mask.shape[0]
        and 0 <= rounded_column < mask.shape[1]
        and mask[rounded_row, rounded_column]
    ):
        return column_offset + median_column, row_offset + median_row
    nearest = int(
        np.argmin(
            (rows.astype(float) - center_row) ** 2
            + (columns.astype(float) - center_column) ** 2
        )
    )
    return (
        float(column_offset + columns[nearest]),
        float(row_offset + rows[nearest]),
    )


def _dissolve_anchor_cores(
    province_map: np.ndarray,
    baseline_map: np.ndarray,
    target_parents: set[int],
    anchors: dict[int, tuple[int, int]],
) -> tuple[np.ndarray, dict[int, int], dict[int, tuple[int, int]], int]:
    """Fill each core from all surrounding children and preserve its old ID."""
    result = province_map.copy()
    child_to_parent: dict[int, int] = {}
    retained_pixels: dict[int, tuple[int, int]] = {}
    dissolved_pixels = 0
    for index, parent in enumerate(sorted(target_parents), 1):
        rows, columns = np.where(baseline_map == parent)
        row0, row1 = int(rows.min()), int(rows.max()) + 1
        column0, column1 = int(columns.min()), int(columns.max()) + 1
        slices = (slice(row0, row1), slice(column0, column1))
        parent_mask = baseline_map[slices] == parent
        local = result[slices]
        core = parent_mask & (local == parent)
        sources = parent_mask & (local != parent)
        if not np.any(core) or not np.any(sources):
            continue

        # Only child pixels inside this original parent are zero-valued sources
        # for the nearest-neighbour transform.  Pixels outside the parent are
        # deliberately excluded so state/country borders cannot move.
        search = ~sources
        _distance, nearest = ndimage.distance_transform_edt(
            search,
            return_distances=True,
            return_indices=True,
        )
        propagated = local[nearest[0], nearest[1]]
        local[core] = propagated[core]
        anchor = anchors[parent]
        old_coordinate = _mask_safe_coordinate(
            province_map[slices] == parent, row0, column0
        )
        candidates = [
            int(pid)
            for pid in np.unique(local[parent_mask])
            if int(pid) > int(baseline_map.max())
        ]
        recipient = min(
            candidates,
            key=lambda pid: (
                math.dist(
                    old_coordinate,
                    _mask_safe_coordinate(local == pid, row0, column0),
                ),
                -int(np.count_nonzero(local == pid)),
                pid,
            ),
        )
        if recipient <= int(baseline_map.max()) or recipient in child_to_parent:
            raise ReworkError(
                f"Anchor core {parent} resolved to invalid generated child {recipient}"
            )

        source_rows, source_columns = np.where(province_map[slices] == recipient)
        if not source_rows.size:
            raise ReworkError(f"Generated child {recipient} has no source pixels")
        global_rows = source_rows + row0
        global_columns = source_columns + column0
        distances = (
            (global_rows - anchor[0]) ** 2
            + (global_columns - anchor[1]) ** 2
        )
        nearest_source = int(np.argmin(distances))
        retained_pixels[parent] = (
            int(global_rows[nearest_source]),
            int(global_columns[nearest_source]),
        )

        # Rename the complete underlying child to the original ID.  This keeps
        # VP/capital/supply/building references stable without retaining the
        # artificial core boundary.
        result[result == recipient] = parent
        child_to_parent[recipient] = parent
        dissolved_pixels += int(core.sum())
        if index % 100 == 0:
            print(f"  dissolved {index:,}/{len(target_parents):,} anchor cores")
    return result, child_to_parent, retained_pixels, dissolved_pixels


def _compact_generated_ids(
    province_map: np.ndarray,
    baseline_maximum: int,
    child_to_parent: dict[int, int],
) -> tuple[np.ndarray, dict[int, int]]:
    live = sorted(int(pid) for pid in np.unique(province_map) if pid > 0)
    missing_original = set(range(1, baseline_maximum + 1)) - set(live)
    if missing_original:
        raise ReworkError(f"Original IDs disappeared: {sorted(missing_original)[:10]}")
    generated = [pid for pid in live if pid > baseline_maximum]
    compact_generated = {
        pid: baseline_maximum + index for index, pid in enumerate(generated, 1)
    }
    mapping = {pid: pid for pid in range(1, baseline_maximum + 1)}
    mapping.update(compact_generated)
    mapping.update(child_to_parent)

    lookup = np.arange(int(province_map.max()) + 1, dtype=np.int32)
    for old_pid, new_pid in compact_generated.items():
        lookup[old_pid] = new_pid
    compacted = lookup[province_map]
    expected_maximum = baseline_maximum + len(generated)
    if int(compacted.max()) != expected_maximum:
        raise ReworkError(
            f"Generated-ID compaction produced {int(compacted.max())}, expected {expected_maximum}"
        )
    return compacted, mapping


def _remap_states(
    states: dict[str, dict[str, Any]], mapping: dict[int, int]
) -> dict[str, dict[str, Any]]:
    result = copy.deepcopy(states)
    for state in result.values():
        state["provinces"] = _unique_mapped(state.get("provinces", []), mapping)
    return result


def _remap_regions(
    regions: dict[str, Any], mapping: dict[int, int]
) -> dict[str, Any]:
    result = copy.deepcopy(regions)
    for region in result.get("regions", []):
        region["province_ids"] = _unique_mapped(
            region.get("province_ids", []), mapping
        )
    return result


def _remap_continents(
    continents: dict[str, Any], mapping: dict[int, int]
) -> dict[str, Any]:
    result = copy.deepcopy(continents)
    assignments: dict[str, int] = {}
    for pid_text, continent in result.get("province_continent", {}).items():
        mapped = str(mapping[int(pid_text)])
        if mapped in assignments and assignments[mapped] != continent:
            raise ReworkError(f"Conflicting continent assignments for province {mapped}")
        assignments[mapped] = int(continent)
    result["province_continent"] = assignments
    return result


def _remap_terrain(
    current: dict[str, str],
    baseline: dict[str, str],
    mapping: dict[int, int],
    baseline_maximum: int,
) -> dict[str, str]:
    restored = dict(current)
    for pid in range(1, baseline_maximum + 1):
        if str(pid) in baseline:
            restored[str(pid)] = baseline[str(pid)]
        else:
            restored.pop(str(pid), None)
    result: dict[str, str] = {}
    for pid_text, terrain in restored.items():
        mapped = str(mapping[int(pid_text)])
        if mapped in result and result[mapped] != terrain:
            raise ReworkError(f"Conflicting terrain assignments for province {mapped}")
        result[mapped] = str(terrain)
    return result


def _child_lineage(
    province_map: np.ndarray, baseline_map: np.ndarray
) -> np.ndarray:
    baseline_base = int(baseline_map.max()) + 1
    encoded = np.unique(
        province_map.astype(np.int64) * baseline_base
        + baseline_map.astype(np.int64)
    )
    province_ids = encoded // baseline_base
    parents = encoded % baseline_base
    counts = np.bincount(province_ids, minlength=int(province_map.max()) + 1)
    if int(counts[1:].min()) != 1 or int(counts[1:].max()) != 1:
        raise ReworkError("A surviving province crosses an original province boundary")
    result = np.zeros(int(province_map.max()) + 1, dtype=np.int32)
    result[province_ids] = parents
    return result


def _validate_railways(
    railways: dict[str, Any],
    baseline_railways: dict[str, Any],
    province_map: np.ndarray,
    lineage: np.ndarray,
) -> None:
    entries = railways.get("entries", [])
    baseline_entries = baseline_railways.get("entries", [])
    if len(entries) != len(baseline_entries):
        raise ReworkError("Railway entry count changed")
    base = int(province_map.max()) + 1
    adjacency = _province_adjacency_codes(province_map)
    for current, baseline in zip(entries, baseline_entries):
        current_ids = [int(pid) for pid in current.get("province_ids", [])]
        baseline_ids = [int(pid) for pid in baseline.get("province_ids", [])]
        if current.get("level") != baseline.get("level"):
            raise ReworkError("Railway level changed")
        if [int(lineage[pid]) for pid in current_ids] != baseline_ids:
            raise ReworkError(
                f"Railway parent lineage changed: {baseline_ids} -> {current_ids}"
            )
        for first, second in zip(current_ids, current_ids[1:]):
            code = min(first, second) * base + max(first, second)
            if code not in adjacency:
                raise ReworkError(f"Railway edge is no longer adjacent: {first}-{second}")


def _validate_result(
    current_map: np.ndarray,
    final_map: np.ndarray,
    baseline_map: np.ndarray,
    tile_map: np.ndarray,
    current_states: dict[str, dict[str, Any]],
    final_states: dict[str, dict[str, Any]],
    current_entries: dict[str, bytes],
    final_terrain_map: np.ndarray,
    baseline_terrain_map: np.ndarray,
    final_regions: dict[str, Any],
    final_railways: dict[str, Any],
    baseline_railways: dict[str, Any],
    target_parents: set[int],
) -> dict[str, Any]:
    if not np.array_equal(
        _state_raster(current_map, current_states),
        _state_raster(final_map, final_states),
    ):
        raise ReworkError("State boundary raster changed")
    if not np.array_equal(
        _country_raster(current_map, current_states),
        _country_raster(final_map, final_states),
    ):
        raise ReworkError("Country boundary raster changed")
    if not np.array_equal(final_terrain_map, baseline_terrain_map):
        raise ReworkError("Graphical terrain was not restored exactly")

    for sid, current_state in current_states.items():
        final_state = final_states[sid]
        for field, value in current_state.items():
            if field != "provinces" and final_state.get(field) != value:
                raise ReworkError(f"State {sid} field changed unexpectedly: {field}")

    for name in (
        "countries.json", "supply_nodes.json", "adjacencies.json",
        "adjacency_rules.json",
    ):
        if name not in current_entries:
            raise ReworkError(f"Project is missing {name}")

    validation = validate_provinces(
        tile_map, final_map, min_pixels=MIN_PROVINCE_PIXELS
    )
    failures = {
        key: validation[key]
        for key in ("x_crossings", "too_small", "not_contiguous", "too_large", "id_gaps")
        if validation[key]
    }
    if failures:
        details = {
            key: value
            for key, value in validation.items()
            if key in failures or key.endswith("_ids")
        }
        raise ReworkError(f"Province validation failed: {details}")

    lineage = _child_lineage(final_map, baseline_map)
    _validate_railways(
        final_railways, baseline_railways, final_map, lineage
    )

    seen = Counter(
        int(pid)
        for region in final_regions.get("regions", [])
        for pid in region.get("province_ids", [])
    )
    live = set(int(pid) for pid in np.unique(final_map) if pid > 0)
    if set(seen) != live or any(count != 1 for count in seen.values()):
        raise ReworkError("Strategic regions do not cover every province exactly once")

    final_areas = np.bincount(
        final_map.ravel(), minlength=int(final_map.max()) + 1
    )

    return {
        "province_validation": validation,
        "railway_edges_validated": len(final_railways.get("entries", [])),
        "strategic_regions_validated": len(final_regions.get("regions", [])),
        "minimum_preserved_anchor_province_pixels": min(
            int(final_areas[pid]) for pid in target_parents
        ),
    }


def remove_circles(args: argparse.Namespace) -> dict[str, Any]:
    project = args.project.resolve()
    baseline_path = args.baseline.resolve()
    if not project.is_file() or not baseline_path.is_file():
        raise ReworkError("Project or pre-rework baseline archive is missing")
    current_entries, current_infos = _load_archive(project)
    baseline_entries, _baseline_infos = _load_archive(baseline_path)

    current_map = _load_array(current_entries, "province_map.npy").astype(
        np.int32, copy=False
    )
    baseline_map = _load_array(baseline_entries, "province_map.npy").astype(
        np.int32, copy=False
    )
    tile_map = _load_array(current_entries, "tile_map.npy")
    current_terrain_map = _load_array(current_entries, "terrain_map.npy")
    baseline_terrain_map = _load_array(baseline_entries, "terrain_map.npy")
    if current_map.shape != baseline_map.shape or current_map.shape != tile_map.shape:
        raise ReworkError("Current and baseline map arrays do not align")

    current_states = json.loads(current_entries["states.json"])
    current_regions = json.loads(current_entries["strategic_regions.json"])
    current_continents = json.loads(current_entries["continents.json"])
    current_terrain = json.loads(current_entries["provincial_terrain.json"])
    baseline_terrain = json.loads(baseline_entries["provincial_terrain.json"])
    baseline_railways = json.loads(baseline_entries["railways.json"])

    baseline_maximum = int(baseline_map.max())
    generated = current_map > baseline_maximum
    split_parents = set(int(pid) for pid in np.unique(baseline_map[generated]))
    position_sensitive = _position_sensitive_ids(current_entries, current_states)
    target_parents = position_sensitive & split_parents
    if not target_parents:
        raise ReworkError("No generated anchor cores were found")

    counts, sum_x, sum_y = _pid_statistics(baseline_map)
    anchors = {
        pid: _safe_pixel(pid, baseline_map, counts, sum_x, sum_y)
        for pid in target_parents
    }
    projected = int(current_map.max()) - len(target_parents)
    print(
        f"Plan: dissolve {len(target_parents):,} anchor circles; "
        f"{int(current_map.max()):,} -> {projected:,} provinces"
    )
    if not args.apply:
        return {
            "dry_run": True,
            "anchor_circles": len(target_parents),
            "projected_provinces": projected,
        }

    dissolved_map, child_to_parent, retained_pixels, dissolved_pixels = _dissolve_anchor_cores(
        current_map, baseline_map, target_parents, anchors
    )
    protected = set(retained_pixels.values())
    x_repairs = _repair_x_crossings_within_parents(
        dissolved_map, baseline_map, protected
    )
    connectivity_repairs = _repair_non_contiguous_within_parents(
        dissolved_map,
        baseline_map,
        retained_pixels,
    )
    x_repairs += _repair_x_crossings_within_parents(
        dissolved_map, baseline_map, protected
    )

    final_map, mapping = _compact_generated_ids(
        dissolved_map, baseline_maximum, child_to_parent
    )
    final_states = _remap_states(current_states, mapping)
    final_regions = _remap_regions(current_regions, mapping)
    final_continents = _remap_continents(current_continents, mapping)
    final_terrain = _remap_terrain(
        current_terrain, baseline_terrain, mapping, baseline_maximum
    )
    final_railways = _remap_railways(
        baseline_railways, baseline_map, final_map
    )

    validation = _validate_result(
        current_map,
        final_map,
        baseline_map,
        tile_map,
        current_states,
        final_states,
        current_entries,
        baseline_terrain_map,
        baseline_terrain_map,
        final_regions,
        final_railways,
        baseline_railways,
        target_parents,
    )

    current_count, current_sum_x, current_sum_y = _pid_statistics(current_map)
    final_count, final_sum_x, final_sum_y = _pid_statistics(final_map)
    vp_ids = {
        int(pid)
        for state in current_states.values()
        for pid in state.get("victory_points", {})
    }
    vp_shifts = []
    for pid in vp_ids:
        old_x, old_y = safe_coord(
            pid, current_map, current_count, current_sum_x, current_sum_y
        )
        new_x, new_y = safe_coord(
            pid, final_map, final_count, final_sum_x, final_sum_y
        )
        vp_shifts.append(math.hypot(new_x - old_x, new_y - old_y))

    report = {
        "project": str(project),
        "old_provinces": int(current_map.max()),
        "new_provinces": int(final_map.max()),
        "anchor_circles_dissolved": len(target_parents),
        "core_pixels_redistributed": dissolved_pixels,
        "graphical_terrain_pixels_restored": int(
            np.count_nonzero(current_terrain_map != baseline_terrain_map)
        ),
        "maximum_vp_position_shift_from_circular_version": max(
            vp_shifts, default=0.0
        ),
        "median_vp_position_shift_from_circular_version": float(
            np.median(vp_shifts) if vp_shifts else 0.0
        ),
        "x_crossing_pixels_repaired": x_repairs,
        "disconnected_fragment_pixels_repaired": connectivity_repairs,
        **validation,
    }

    updated_entries = dict(current_entries)
    updated_entries["province_map.npy"] = _array_bytes(final_map)
    updated_entries["terrain_map.npy"] = _array_bytes(baseline_terrain_map)
    updated_entries["states.json"] = _json_bytes(final_states)
    updated_entries["strategic_regions.json"] = _json_bytes(final_regions)
    updated_entries["continents.json"] = _json_bytes(final_continents)
    updated_entries["provincial_terrain.json"] = _json_bytes(final_terrain)
    updated_entries["railways.json"] = _json_bytes(final_railways)

    backup = project.with_name(project.name + ".city_circle_cleanup.bak")
    if backup.exists() and not args.overwrite_backup:
        raise ReworkError(
            f"Backup already exists: {backup}. Use --overwrite-backup after reviewing it."
        )
    shutil.copy2(project, backup)
    _write_archive_atomic(project, updated_entries, current_infos)
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Backup: {backup}")
    print(f"Report: {args.output_report}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output-report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--overwrite-backup", action="store_true")
    args = parser.parse_args()
    try:
        report = remove_circles(args)
    except ReworkError as exc:
        print(f"City-circle cleanup failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
