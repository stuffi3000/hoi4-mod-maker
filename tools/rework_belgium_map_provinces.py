"""Split oversized provinces in the authored Belgium Map v1.1 project.

The operation is intentionally conservative:

* every original province ID survives;
* pixels never move between original provinces, states, or countries;
* victory points, country capitals, supply nodes, special adjacencies, and
  province buildings keep their original IDs;
* railway edges are remapped to adjacent children on the same old borders;
* child provinces inherit state, strategic-region, continent, and terrain
  metadata from their parent; and
* major victory-point cities receive extra subdivisions and urban terrain.

CORINE Land Cover 2024 is used as a soft watershed boundary guide.  This is a
one-shot authoring tool and additionally needs ``rasterio`` and
``scikit-image`` beside the project's normal dependencies.

Run without ``--apply`` to inspect the plan.  A real run creates a sibling
``.province_rework.bak`` and replaces the project atomically.
"""

from __future__ import annotations

import argparse
import copy
import heapq
import io
import json
import math
import os
import shutil
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy import ndimage


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.constants import MIN_PROVINCE_PIXELS, TILE_LAKE, TILE_LAND
from data.terrain_types import PALETTE_TO_TYPE, TERRAIN_PALETTE_INDEX
from domain.validators.province import (
    detect_non_contiguous,
    detect_x_crossings,
    validate_provinces,
)
from export.writers.map._coords import safe_coord


DEFAULT_PROJECT = ROOT / "projects" / "Belgium_Map_v1_1.hoi4proj"
DEFAULT_REPORT = ROOT / "projects" / "Belgium_Map_v1_1.state_authoring.json"
DEFAULT_SOURCE_DIR = Path(
    r"C:\Users\stuff\Documents\HOI4\Belgium\base map\qgis\EU data"
)
DEFAULT_TARGET_AREA = 1550
DEFAULT_MAX_PROVINCES = 13_000
DEFAULT_URBAN_POPULATION = 75_000
URBAN_CLC_CLASSES = (111, 112, 121, 122, 123, 124)


class ReworkError(RuntimeError):
    """Raised when a safety invariant prevents the project rewrite."""


def _load_archive(path: Path) -> tuple[dict[str, bytes], dict[str, zipfile.ZipInfo]]:
    with zipfile.ZipFile(path, "r") as archive:
        bad_entry = archive.testzip()
        if bad_entry:
            raise ReworkError(f"Corrupt project archive entry: {bad_entry}")
        entries = {name: archive.read(name) for name in archive.namelist()}
        infos = {info.filename: info for info in archive.infolist()}
    return entries, infos


def _load_array(entries: dict[str, bytes], name: str) -> np.ndarray:
    try:
        return np.load(io.BytesIO(entries[name]), allow_pickle=False)
    except KeyError as exc:
        raise ReworkError(f"Project is missing {name}") from exc


def _array_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def _pid_statistics(province_map: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    maximum = int(province_map.max())
    flat = province_map.ravel()
    count = np.bincount(flat, minlength=maximum + 1)
    sum_x = np.zeros(maximum + 1, dtype=np.float64)
    sum_y = np.zeros(maximum + 1, dtype=np.float64)
    x_weights = np.arange(province_map.shape[1], dtype=np.float64)
    for row, values in enumerate(province_map):
        row_count = np.bincount(values, minlength=maximum + 1)
        sum_y += row * row_count
        sum_x += np.bincount(values, weights=x_weights, minlength=maximum + 1)
    return count, sum_x, sum_y


def _safe_pixel(
    pid: int,
    province_map: np.ndarray,
    count: np.ndarray,
    sum_x: np.ndarray,
    sum_y: np.ndarray,
) -> tuple[int, int]:
    x, y = safe_coord(pid, province_map, count, sum_x, sum_y)
    row = int(round(y))
    column = int(round(x))
    if province_map[row, column] == pid:
        return row, column
    rows, columns = np.where(province_map == pid)
    if rows.size == 0:
        raise ReworkError(f"Province {pid} has no pixels")
    index = int(np.argmin((rows - y) ** 2 + (columns - x) ** 2))
    return int(rows[index]), int(columns[index])


def _state_pid_maps(states: dict[str, dict[str, Any]], maximum: int) -> tuple[np.ndarray, dict[int, str]]:
    pid_to_state = np.zeros(maximum + 1, dtype=np.int32)
    pid_to_owner: dict[int, str] = {}
    for sid_text, state in states.items():
        sid = int(sid_text)
        owner = str(state.get("owner_tag", ""))
        for raw_pid in state.get("provinces", []):
            pid = int(raw_pid)
            if pid <= 0 or pid > maximum:
                raise ReworkError(f"State {sid} references invalid province {pid}")
            if pid_to_state[pid] and pid_to_state[pid] != sid:
                raise ReworkError(f"Province {pid} belongs to more than one state")
            pid_to_state[pid] = sid
            pid_to_owner[pid] = owner
    return pid_to_state, pid_to_owner


def _vp_population_lookup(
    states: dict[str, dict[str, Any]], report_path: Path
) -> dict[int, int]:
    if not report_path.is_file():
        raise ReworkError(f"State-authoring report not found: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    candidates: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for state in report.get("states", []):
        for city in state.get("cities_considered", []):
            candidates[int(city["province_id"])].append(
                (str(city["name"]), int(city.get("population", 0)))
            )

    result: dict[int, int] = {}
    for state in states.values():
        names = state.get("vp_names") or {}
        names_en = state.get("vp_names_en") or {}
        for pid_text in state.get("victory_points", {}):
            pid = int(pid_text)
            name = str(names.get(str(pid), names_en.get(str(pid), "")))
            options = candidates.get(pid, [])
            exact = [population for candidate, population in options if candidate.casefold() == name.casefold()]
            result[pid] = max(exact or [population for _, population in options] or [0])
    return result


def _load_clc(source_dir: Path, shape: tuple[int, int]) -> np.ndarray:
    try:
        import rasterio
        from affine import Affine
        from rasterio.warp import Resampling, reproject
    except ImportError as exc:
        raise ReworkError(
            "CORINE alignment requires rasterio (and its affine dependency)"
        ) from exc

    clc_path = source_dir / "urbanisation" / "CLC2024ACC_V2024_21.tif"
    world_path = source_dir / "test3.pgw"
    if not clc_path.is_file() or not world_path.is_file():
        raise ReworkError(f"Missing CORINE raster or project world file below {source_dir}")
    world = [float(value.strip().replace(",", ".")) for value in world_path.read_text().splitlines()]
    if len(world) != 6:
        raise ReworkError(f"Invalid world file: {world_path}")
    pixel_x, rotation_y, rotation_x, pixel_y, origin_x, origin_y = world
    transform = Affine(
        pixel_x,
        rotation_x,
        origin_x - pixel_x / 2.0,
        rotation_y,
        pixel_y,
        origin_y - pixel_y / 2.0,
    )
    destination = np.full(shape, -32768, dtype=np.int16)
    with rasterio.open(clc_path) as source:
        reproject(
            rasterio.band(source, 1),
            destination,
            src_transform=source.transform,
            src_crs=source.crs,
            src_nodata=source.nodata,
            dst_transform=transform,
            dst_crs="EPSG:3035",
            dst_nodata=-32768,
            resampling=Resampling.nearest,
        )
    return destination


def _landuse_edges(clc: np.ndarray) -> np.ndarray:
    valid = clc >= 0
    edges = np.zeros(clc.shape, dtype=np.uint8)
    horizontal = valid[:, :-1] & valid[:, 1:] & (clc[:, :-1] != clc[:, 1:])
    vertical = valid[:-1, :] & valid[1:, :] & (clc[:-1, :] != clc[1:, :])
    edges[:, :-1] |= horizontal
    edges[:, 1:] |= horizontal
    edges[:-1, :] |= vertical
    edges[1:, :] |= vertical
    return edges


def _major_city_bonus(population: int, threshold: int) -> int:
    if population < threshold:
        return 0
    return 1 + int(population >= 200_000) + int(population >= 500_000)


def _split_plan(
    areas: np.ndarray,
    state_pids: Iterable[int],
    populations: dict[int, int],
    target_area: int,
    urban_population: int,
    old_maximum: int,
    max_provinces: int,
    extra_parts: dict[int, int] | None = None,
) -> dict[int, int]:
    plan: dict[int, int] = {}
    for pid in sorted(set(int(value) for value in state_pids)):
        area = int(areas[pid])
        parts = max(1, math.ceil(area / target_area))
        parts += _major_city_bonus(populations.get(pid, 0), urban_population)
        parts = min(parts, max(1, area // MIN_PROVINCE_PIXELS))
        if parts > 1:
            plan[pid] = parts
    for pid, parts in (extra_parts or {}).items():
        area = int(areas[pid])
        safe_parts = min(int(parts), max(1, area // MIN_PROVINCE_PIXELS))
        if safe_parts > 1:
            plan[int(pid)] = max(plan.get(int(pid), 1), safe_parts)
    projected = old_maximum + sum(parts - 1 for parts in plan.values())
    if projected > max_provinces:
        raise ReworkError(
            f"Split plan would create {projected:,} provinces, above the {max_provinces:,} cap"
        )
    return plan


def _farthest_seeds(mask: np.ndarray, count: int, anchor: tuple[int, int]) -> list[tuple[int, int]]:
    rows, columns = np.where(mask)
    if rows.size < count:
        raise ReworkError("Province mask has fewer pixels than requested markers")
    coordinates = np.column_stack((rows, columns)).astype(np.float64)
    seeds = [anchor]
    minimum_distance = np.sum((coordinates - np.asarray(anchor)) ** 2, axis=1)
    for _ in range(1, count):
        index = int(np.argmax(minimum_distance))
        seed = (int(rows[index]), int(columns[index]))
        seeds.append(seed)
        distance = np.sum((coordinates - coordinates[index]) ** 2, axis=1)
        minimum_distance = np.minimum(minimum_distance, distance)
    return seeds


def _watershed_labels(
    mask: np.ndarray,
    count: int,
    anchor: tuple[int, int],
    edge_cost: np.ndarray,
) -> np.ndarray:
    try:
        from skimage.segmentation import watershed
    except ImportError as exc:
        raise ReworkError("Province splitting requires scikit-image") from exc
    seeds = _farthest_seeds(mask, count, anchor)
    markers = np.zeros(mask.shape, dtype=np.int32)
    for label, (row, column) in enumerate(seeds, 1):
        markers[row, column] = label
    elevation = edge_cost.astype(np.float32) * 3.0
    labels = watershed(
        elevation,
        markers=markers,
        mask=mask,
        compactness=0.02,
        watershed_line=False,
    ).astype(np.int32, copy=False)
    found = set(int(value) for value in np.unique(labels[mask]))
    if found != set(range(1, count + 1)):
        raise ReworkError(f"Watershed returned {len(found)} of {count} requested parts")
    return labels


def _grow_anchor_core(
    mask: np.ndarray,
    anchor: tuple[int, int],
    target_size: int,
) -> np.ndarray:
    """Grow a connected, near-circular core around an exported safe coordinate."""
    core = np.zeros(mask.shape, dtype=bool)
    queued = np.zeros(mask.shape, dtype=bool)
    queue: list[tuple[int, int, int]] = [(0, anchor[0], anchor[1])]
    queued[anchor] = True
    grown = 0
    while queue and grown < target_size:
        _distance, row, column = heapq.heappop(queue)
        core[row, column] = True
        grown += 1
        for next_row, next_column in (
            (row - 1, column), (row + 1, column),
            (row, column - 1), (row, column + 1),
        ):
            if not (0 <= next_row < mask.shape[0] and 0 <= next_column < mask.shape[1]):
                continue
            if queued[next_row, next_column] or not mask[next_row, next_column]:
                continue
            queued[next_row, next_column] = True
            distance = (next_row - anchor[0]) ** 2 + (next_column - anchor[1]) ** 2
            heapq.heappush(queue, (distance, next_row, next_column))
    return core


def _component_part_counts(component_sizes: np.ndarray, total_parts: int) -> list[int] | None:
    component_count = len(component_sizes)
    if component_count > total_parts:
        return None
    counts = [1] * component_count
    capacities = [max(1, int(size) // MIN_PROVINCE_PIXELS) for size in component_sizes]
    while sum(counts) < total_parts:
        candidates = [
            index for index in range(component_count)
            if counts[index] < capacities[index]
        ]
        if not candidates:
            return None
        best = max(candidates, key=lambda index: (component_sizes[index] / counts[index], -index))
        counts[best] += 1
    return counts


def _anchor_core_labels(
    mask: np.ndarray,
    parts: int,
    anchor: tuple[int, int],
    edge_cost: np.ndarray,
) -> np.ndarray | None:
    """Reserve label 1 around a VP, then divide the remaining parent area."""
    area = int(mask.sum())
    maximum_core = area - MIN_PROVINCE_PIXELS * (parts - 1)
    average = area / parts
    candidate_sizes = sorted({
        max(MIN_PROVINCE_PIXELS, min(maximum_core, int(round(average * factor))))
        for factor in (0.40, 0.50, 0.60, 0.75)
    })
    structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
    for core_size in candidate_sizes:
        core = _grow_anchor_core(mask, anchor, core_size)
        if int(core.sum()) < MIN_PROVINCE_PIXELS:
            continue
        remainder = mask & ~core
        components, component_count = ndimage.label(remainder, structure=structure)
        if component_count == 0:
            continue
        component_sizes = np.bincount(components.ravel())[1:]
        if int(component_sizes.min()) < MIN_PROVINCE_PIXELS:
            continue
        allocations = _component_part_counts(component_sizes, parts - 1)
        if allocations is None:
            continue

        result = np.zeros(mask.shape, dtype=np.int32)
        result[core] = 1
        next_label = 2
        valid = True
        for component, allocation in enumerate(allocations, 1):
            component_mask = components == component
            rows, columns = np.where(component_mask)
            centre = np.array((rows.mean(), columns.mean()))
            index = int(np.argmin(np.sum((np.column_stack((rows, columns)) - centre) ** 2, axis=1)))
            component_anchor = (int(rows[index]), int(columns[index]))
            component_labels = None
            for local_cost in (edge_cost, np.zeros(mask.shape, dtype=np.uint8)):
                candidate = _watershed_labels(
                    component_mask, allocation, component_anchor, local_cost
                )
                counts = np.bincount(candidate[component_mask], minlength=allocation + 1)
                if int(counts[1:].min()) >= MIN_PROVINCE_PIXELS:
                    component_labels = candidate
                    break
            if component_labels is None:
                valid = False
                break
            for local_label in range(1, allocation + 1):
                result[component_labels == local_label] = next_label
                next_label += 1
        if valid and next_label == parts + 1:
            core_rows, core_columns = np.where(result == 1)
            centre_row = float(core_rows.mean())
            centre_column = float(core_columns.mean())
            rounded = (int(round(centre_row)), int(round(centre_column)))
            if (
                result[rounded] == 1
                and math.hypot(centre_row - anchor[0], centre_column - anchor[1]) <= 2.5
            ):
                return result
    return None


def _local_split(
    old_map: np.ndarray,
    pid: int,
    parts: int,
    anchor: tuple[int, int],
    edge_cost: np.ndarray,
    preserve_anchor: bool,
) -> tuple[tuple[slice, slice], np.ndarray, int]:
    rows, columns = np.where(old_map == pid)
    if rows.size == 0:
        raise ReworkError(f"Cannot split absent province {pid}")
    row0, row1 = int(rows.min()), int(rows.max()) + 1
    column0, column1 = int(columns.min()), int(columns.max()) + 1
    slices = (slice(row0, row1), slice(column0, column1))
    mask = old_map[slices] == pid
    local_anchor = (anchor[0] - row0, anchor[1] - column0)
    while parts > 1:
        if preserve_anchor:
            labels = _anchor_core_labels(
                mask, parts, local_anchor, edge_cost[slices]
            )
            if labels is not None:
                return slices, labels, parts
            parts -= 1
            continue
        for local_cost in (edge_cost[slices], np.zeros(mask.shape, dtype=np.uint8)):
            labels = _watershed_labels(mask, parts, local_anchor, local_cost)
            counts = np.bincount(labels[mask], minlength=parts + 1)
            if int(counts[1:].min()) >= MIN_PROVINCE_PIXELS:
                return slices, labels, parts
        parts -= 1
    return slices, np.where(mask, 1, 0).astype(np.int32), 1


def _assign_splits(
    old_map: np.ndarray,
    plan: dict[int, int],
    anchors: dict[int, tuple[int, int]],
    edge_cost: np.ndarray,
    preserved_parents: set[int],
) -> tuple[np.ndarray, dict[int, list[int]]]:
    result = old_map.copy()
    next_id = int(old_map.max()) + 1
    children: dict[int, list[int]] = {}
    reduced = 0
    for index, (pid, parts) in enumerate(sorted(plan.items()), 1):
        slices, labels, actual_parts = _local_split(
            old_map, pid, parts, anchors[pid], edge_cost, pid in preserved_parents
        )
        reduced += parts - actual_parts
        child_ids = list(range(next_id, next_id + actual_parts - 1))
        next_id += actual_parts - 1
        local = result[slices]
        local[labels == 1] = pid
        for label, child_id in enumerate(child_ids, 2):
            local[labels == label] = child_id
        children[pid] = child_ids
        if index % 250 == 0:
            print(f"  split {index:,}/{len(plan):,} parent provinces")
    if reduced:
        print(f"  reduced the plan by {reduced:,} children to avoid sub-{MIN_PROVINCE_PIXELS}-pixel provinces")
    return result, children


def _repair_x_crossings_within_parents(
    province_map: np.ndarray,
    old_map: np.ndarray,
    protected_pixels: set[tuple[int, int]],
    max_rounds: int = 12,
) -> int:
    repaired = 0
    width = province_map.shape[1]
    for _ in range(max_rounds):
        positions = detect_x_crossings(province_map)
        if not positions:
            return repaired
        counts = np.bincount(province_map.ravel(), minlength=int(province_map.max()) + 1)
        changed = 0
        for row, column in positions:
            right = 0 if column == width - 1 else column + 1
            coordinates = [(row, column), (row, right), (row + 1, column), (row + 1, right)]
            candidates: list[tuple[int, int, int]] = []
            for destination_index, (dy, dx) in enumerate(coordinates):
                if (dy, dx) in protected_pixels:
                    continue
                destination = int(province_map[dy, dx])
                if counts[destination] <= MIN_PROVINCE_PIXELS:
                    continue
                for sy, sx in (
                    (dy - 1, dx), (dy + 1, dx), (dy, (dx - 1) % width),
                    (dy, (dx + 1) % width),
                ):
                    if sy < 0 or sy >= province_map.shape[0]:
                        continue
                    if old_map[dy, dx] != old_map[sy, sx]:
                        continue
                    source = int(province_map[sy, sx])
                    if source == destination:
                        continue
                    candidates.append((int(counts[destination]), destination_index, source))
            if not candidates:
                continue
            _, destination_index, source = max(candidates)
            dy, dx = coordinates[destination_index]
            destination = int(province_map[dy, dx])
            province_map[dy, dx] = source
            counts[destination] -= 1
            counts[source] += 1
            changed += 1
            repaired += 1
        if changed == 0:
            break
    remaining = detect_x_crossings(province_map)
    for row, column in remaining:
        right = 0 if column == width - 1 else column + 1
        coordinates = [(row, column), (row, right), (row + 1, column), (row + 1, right)]
        by_parent: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for coordinate in coordinates:
            by_parent[int(old_map[coordinate])].append(coordinate)
        options: list[tuple[int, list[tuple[int, int]], int]] = []
        counts = np.bincount(province_map.ravel(), minlength=int(province_map.max()) + 1)
        for parent, parent_coordinates in by_parent.items():
            if len(parent_coordinates) < 2:
                continue
            for start in parent_coordinates:
                for target_coordinate in parent_coordinates:
                    target = int(province_map[target_coordinate])
                    if target == int(province_map[start]):
                        continue
                    path = _shortest_parent_path(
                        province_map,
                        old_map,
                        start,
                        target,
                        parent,
                        protected_pixels,
                    )
                    if not path:
                        continue
                    removed = Counter(int(province_map[coordinate]) for coordinate in path)
                    if any(counts[pid] - amount < MIN_PROVINCE_PIXELS for pid, amount in removed.items()):
                        continue
                    options.append((len(path), path, target))
        if options:
            _length, path, target = min(options, key=lambda item: (item[0], item[2]))
            for coordinate in path:
                province_map[coordinate] = target
            repaired += len(path)

    for _ in range(max_rounds):
        positions = detect_x_crossings(province_map)
        if not positions:
            return repaired
        before = len(positions)
        repaired += _repair_x_crossings_within_parents(
            province_map, old_map, protected_pixels, max_rounds=1
        ) if max_rounds > 1 else 0
        if len(detect_x_crossings(province_map)) >= before:
            break

    remaining = detect_x_crossings(province_map)
    if remaining:
        details = []
        for row, column in remaining[:5]:
            right = 0 if column == width - 1 else column + 1
            details.append({
                "position": (row, column),
                "new": province_map[row:row + 2, [column, right]].tolist(),
                "parent": old_map[row:row + 2, [column, right]].tolist(),
                "protected": [
                    (y, x) in protected_pixels
                    for y, x in ((row, column), (row, right), (row + 1, column), (row + 1, right))
                ],
            })
        raise ReworkError(
            f"Could not safely repair {len(remaining)} X crossings: {details}"
        )
    return repaired


def _shortest_parent_path(
    province_map: np.ndarray,
    old_map: np.ndarray,
    start: tuple[int, int],
    target_pid: int,
    parent_pid: int,
    protected_pixels: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Find a short 4-connected bridge to an existing label inside one parent."""
    rows, columns = np.where(old_map == parent_pid)
    row0, row1 = int(rows.min()), int(rows.max()) + 1
    column0, column1 = int(columns.min()), int(columns.max()) + 1
    parent_mask = old_map[row0:row1, column0:column1] == parent_pid
    start_local = (start[0] - row0, start[1] - column0)
    queue: deque[tuple[int, int]] = deque([start_local])
    visited = np.zeros(parent_mask.shape, dtype=bool)
    visited[start_local] = True
    previous: dict[tuple[int, int], tuple[int, int]] = {}
    destination: tuple[int, int] | None = None
    while queue:
        local_row, local_column = queue.popleft()
        global_coordinate = (local_row + row0, local_column + column0)
        if global_coordinate != start and int(province_map[global_coordinate]) == target_pid:
            destination = (local_row, local_column)
            break
        for next_row, next_column in (
            (local_row - 1, local_column), (local_row + 1, local_column),
            (local_row, local_column - 1), (local_row, local_column + 1),
        ):
            if not (0 <= next_row < parent_mask.shape[0] and 0 <= next_column < parent_mask.shape[1]):
                continue
            if visited[next_row, next_column] or not parent_mask[next_row, next_column]:
                continue
            global_next = (next_row + row0, next_column + column0)
            if global_next in protected_pixels and global_next != start:
                continue
            visited[next_row, next_column] = True
            previous[(next_row, next_column)] = (local_row, local_column)
            queue.append((next_row, next_column))
    if destination is None:
        return []
    path: list[tuple[int, int]] = []
    current = destination
    while current != start_local:
        prior = previous[current]
        if current != destination:
            path.append((current[0] + row0, current[1] + column0))
        current = prior
    path.append(start)
    path.reverse()
    return path


def _repair_non_contiguous_within_parents(
    province_map: np.ndarray,
    old_map: np.ndarray,
    protected_pixels: dict[int, tuple[int, int]],
) -> int:
    """Merge detached fragments without moving pixels across an original parent."""
    repaired = 0
    height, width = province_map.shape
    for pid in detect_non_contiguous(province_map):
        rows, columns = np.where(province_map == pid)
        row0, row1 = int(rows.min()), int(rows.max()) + 1
        column0, column1 = int(columns.min()), int(columns.max()) + 1
        mask = province_map[row0:row1, column0:column1] == pid
        labels, component_count = ndimage.label(
            mask, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
        )
        if component_count <= 1:
            continue
        keep = 0
        anchor = protected_pixels.get(pid)
        if anchor is not None and row0 <= anchor[0] < row1 and column0 <= anchor[1] < column1:
            keep = int(labels[anchor[0] - row0, anchor[1] - column0])
        if keep <= 0:
            keep = int(np.bincount(labels.ravel())[1:].argmax()) + 1
        for component in range(1, component_count + 1):
            if component == keep:
                continue
            local_rows, local_columns = np.where(labels == component)
            global_rows = local_rows + row0
            global_columns = local_columns + column0
            parent = int(old_map[global_rows[0], global_columns[0]])
            neighbours: Counter[int] = Counter()
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                neighbour_rows = global_rows + dy
                neighbour_columns = (global_columns + dx) % width
                valid = (neighbour_rows >= 0) & (neighbour_rows < height)
                neighbour_rows = neighbour_rows[valid]
                neighbour_columns = neighbour_columns[valid]
                same_parent = old_map[neighbour_rows, neighbour_columns] == parent
                values = province_map[
                    neighbour_rows[same_parent], neighbour_columns[same_parent]
                ]
                neighbours.update(int(value) for value in values if int(value) != pid)
            if not neighbours:
                raise ReworkError(f"Detached fragment of province {pid} has no parent-safe neighbour")
            target = max(neighbours, key=lambda value: (neighbours[value], -value))
            province_map[global_rows, global_columns] = target
            repaired += int(global_rows.size)
    return repaired


def _inherit_metadata(
    states: dict[str, dict[str, Any]],
    strategic_regions: dict[str, Any],
    continents: dict[str, Any],
    provincial_terrain: dict[str, str],
    children: dict[int, list[int]],
    old_terrain_map: np.ndarray,
    old_map: np.ndarray,
) -> None:
    parent_to_state: dict[int, dict[str, Any]] = {}
    for state in states.values():
        for raw_pid in state.get("provinces", []):
            parent_to_state[int(raw_pid)] = state
    for parent, child_ids in children.items():
        state = parent_to_state.get(parent)
        if state is not None:
            state["provinces"].extend(child_ids)

    parent_to_region: dict[int, dict[str, Any]] = {}
    for region in strategic_regions.get("regions", []):
        for raw_pid in region.get("province_ids", []):
            pid = int(raw_pid)
            if pid in parent_to_region:
                raise ReworkError(f"Province {pid} occurs in multiple strategic regions")
            parent_to_region[pid] = region
    for parent, child_ids in children.items():
        region = parent_to_region.get(parent)
        if region is None:
            raise ReworkError(f"Province {parent} has no strategic region to inherit")
        region["province_ids"].extend(child_ids)

    continent_map = continents.setdefault("province_continent", {})
    for parent, child_ids in children.items():
        if str(parent) in continent_map:
            for child in child_ids:
                continent_map[str(child)] = continent_map[str(parent)]

    for parent, child_ids in children.items():
        terrain = provincial_terrain.get(str(parent))
        if terrain is None:
            values = old_terrain_map[old_map == parent]
            if values.size:
                terrain = PALETTE_TO_TYPE.get(int(np.bincount(values).argmax()), "plains")
        if terrain is not None:
            for child in child_ids:
                provincial_terrain[str(child)] = terrain


def _state_raster(province_map: np.ndarray, states: dict[str, dict[str, Any]]) -> np.ndarray:
    lookup = np.zeros(int(province_map.max()) + 1, dtype=np.int32)
    for sid_text, state in states.items():
        sid = int(sid_text)
        for raw_pid in state.get("provinces", []):
            pid = int(raw_pid)
            if lookup[pid] and lookup[pid] != sid:
                raise ReworkError(f"Province {pid} is assigned to multiple states")
            lookup[pid] = sid
    return lookup[province_map]


def _country_raster(
    province_map: np.ndarray,
    states: dict[str, dict[str, Any]],
) -> np.ndarray:
    tags = sorted({str(state.get("owner_tag", "")) for state in states.values()})
    tag_ids = {tag: index for index, tag in enumerate(tags, 1)}
    lookup = np.zeros(int(province_map.max()) + 1, dtype=np.int16)
    for state in states.values():
        value = tag_ids[str(state.get("owner_tag", ""))]
        for raw_pid in state.get("provinces", []):
            lookup[int(raw_pid)] = value
    return lookup[province_map]


def _reference_ids(entries: dict[str, bytes], states: dict[str, dict[str, Any]]) -> set[int]:
    result: set[int] = set()
    countries = json.loads(entries["countries.json"])
    result.update(int(country.get("capital", 0)) for country in countries.get("countries", {}).values())
    for state in states.values():
        result.update(int(pid) for pid in state.get("victory_points", {}))
        result.update(int(pid) for pid in state.get("province_buildings", {}))
    for railway in json.loads(entries["railways.json"]).get("entries", []):
        result.update(int(pid) for pid in railway.get("province_ids", []))
    for node in json.loads(entries["supply_nodes.json"]).get("nodes", []):
        result.add(int(node["province_id"]))
    for adjacency in json.loads(entries["adjacencies.json"]).get("entries", []):
        result.update((int(adjacency["from_province"]), int(adjacency["to_province"])))
    for rule in json.loads(entries["adjacency_rules.json"]).get("rules", []):
        for key in ("start_province", "stop_province"):
            if key in rule:
                result.add(int(rule[key]))
    result.discard(0)
    return result


def _position_sensitive_ids(
    entries: dict[str, bytes], states: dict[str, dict[str, Any]]
) -> set[int]:
    result: set[int] = set()
    countries = json.loads(entries["countries.json"])
    result.update(int(country.get("capital", 0)) for country in countries.get("countries", {}).values())
    for state in states.values():
        result.update(int(pid) for pid in state.get("victory_points", {}))
        result.update(int(pid) for pid in state.get("province_buildings", {}))
    for node in json.loads(entries["supply_nodes.json"]).get("nodes", []):
        result.add(int(node["province_id"]))
    result.discard(0)
    return result


def _remap_railways(
    railways: dict[str, Any],
    old_map: np.ndarray,
    new_map: np.ndarray,
) -> dict[str, Any]:
    """Move each old railway edge onto adjacent children of the same parents."""
    result = copy.deepcopy(railways)
    old_base = int(old_map.max()) + 1
    new_base = int(new_map.max()) + 1
    requested: set[int] = set()
    for entry in result.get("entries", []):
        ids = [int(pid) for pid in entry.get("province_ids", [])]
        if len(ids) != 2:
            raise ReworkError("This preservation pass expects two-province railway entries")
        low, high = sorted(ids)
        requested.add(low * old_base + high)
    requested_array = np.asarray(sorted(requested), dtype=np.int64)
    factor = new_base * new_base
    candidates: dict[int, Counter[tuple[int, int]]] = defaultdict(Counter)

    for old_first, old_second, new_first, new_second in (
        (old_map[:, :-1], old_map[:, 1:], new_map[:, :-1], new_map[:, 1:]),
        (old_map[:-1, :], old_map[1:, :], new_map[:-1, :], new_map[1:, :]),
    ):
        low = np.minimum(old_first, old_second).astype(np.int64, copy=False)
        high = np.maximum(old_first, old_second).astype(np.int64, copy=False)
        old_code = low * old_base + high
        selected = (old_first != old_second) & np.isin(old_code, requested_array)
        if not np.any(selected):
            continue
        first_is_low = old_first[selected] == low[selected]
        child_low = np.where(first_is_low, new_first[selected], new_second[selected]).astype(np.int64)
        child_high = np.where(first_is_low, new_second[selected], new_first[selected]).astype(np.int64)
        combined = old_code[selected] * factor + child_low * new_base + child_high
        values, counts = np.unique(combined, return_counts=True)
        for value, count in zip(values.tolist(), counts.tolist()):
            old_code_value, child_code = divmod(int(value), factor)
            child_low_value, child_high_value = divmod(child_code, new_base)
            candidates[old_code_value][(child_low_value, child_high_value)] += int(count)

    for entry in result.get("entries", []):
        first, second = (int(pid) for pid in entry["province_ids"])
        low, high = sorted((first, second))
        old_code = low * old_base + high
        if not candidates[old_code]:
            raise ReworkError(f"Railway edge {first}-{second} has no child adjacency")
        child_low, child_high = max(
            candidates[old_code],
            key=lambda pair: (candidates[old_code][pair], -pair[0], -pair[1]),
        )
        entry["province_ids"] = (
            [child_low, child_high] if first == low else [child_high, child_low]
        )
    return result


def _province_adjacency_codes(province_map: np.ndarray) -> set[int]:
    base = int(province_map.max()) + 1
    result: set[int] = set()
    for first, second in (
        (province_map[:, :-1], province_map[:, 1:]),
        (province_map[:-1, :], province_map[1:, :]),
    ):
        selected = first != second
        low = np.minimum(first[selected], second[selected]).astype(np.int64, copy=False)
        high = np.maximum(first[selected], second[selected]).astype(np.int64, copy=False)
        result.update(int(value) for value in np.unique(low * base + high))
    return result


def _validate_result(
    old_map: np.ndarray,
    new_map: np.ndarray,
    tile_map: np.ndarray,
    old_states: dict[str, dict[str, Any]],
    new_states: dict[str, dict[str, Any]],
    entries: dict[str, bytes],
    max_provinces: int,
    anchors: dict[int, tuple[int, int]],
    vp_ids: set[int],
    position_sensitive_ids: set[int],
    railways: dict[str, Any],
) -> dict[str, Any]:
    if int(new_map.max()) > max_provinces:
        raise ReworkError(f"Province cap exceeded: {int(new_map.max()):,}")
    if not np.array_equal(_state_raster(old_map, old_states), _state_raster(new_map, new_states)):
        raise ReworkError("State boundary raster changed")
    if not np.array_equal(_country_raster(old_map, old_states), _country_raster(new_map, new_states)):
        raise ReworkError("Country boundary raster changed")
    if not np.array_equal(old_map == 0, new_map == 0):
        raise ReworkError("Province coverage changed")

    old_maximum = int(old_map.max())
    live = set(int(value) for value in np.unique(new_map) if value > 0)
    missing_original = set(range(1, old_maximum + 1)) - live
    if missing_original:
        raise ReworkError(f"Original province IDs disappeared: {sorted(missing_original)[:10]}")
    references = _reference_ids(entries, old_states)
    dead_references = references - live
    if dead_references:
        raise ReworkError(f"Referenced province IDs disappeared: {sorted(dead_references)[:10]}")

    for sid, old_state in old_states.items():
        new_state = new_states[sid]
        for field in (
            "id", "name", "name_en", "manpower", "category", "owner_tag",
            "victory_points", "vp_names", "vp_names_en", "impassable",
            "controller_tag", "local_supplies", "resources", "buildings",
            "province_buildings", "extra_cores", "claims",
        ):
            if old_state.get(field) != new_state.get(field):
                raise ReworkError(f"State {sid} field changed unexpectedly: {field}")

    validation = validate_provinces(tile_map, new_map, min_pixels=MIN_PROVINCE_PIXELS)
    failures = {
        key: validation[key]
        for key in ("x_crossings", "too_small", "not_contiguous", "id_gaps")
        if validation[key]
    }
    if failures:
        raise ReworkError(f"Province validation failed: {failures}")

    new_count, new_sum_x, new_sum_y = _pid_statistics(new_map)
    position_shift: dict[int, float] = {}
    for pid in sorted(position_sensitive_ids):
        old_row, old_column = anchors[pid]
        x, y = safe_coord(pid, new_map, new_count, new_sum_x, new_sum_y)
        position_shift[pid] = float(math.hypot(x - old_column, y - old_row))
    shifted = {pid: value for pid, value in position_shift.items() if value > 3.0}
    if shifted:
        worst = sorted(shifted.items(), key=lambda item: item[1], reverse=True)[:10]
        raise ReworkError(
            f"{len(shifted)} referenced map positions moved more than 3 pixels; worst: {worst}"
        )

    adjacency = _province_adjacency_codes(new_map)
    adjacency_base = int(new_map.max()) + 1
    invalid_railways: list[tuple[int, int]] = []
    for entry in railways.get("entries", []):
        ids = [int(pid) for pid in entry.get("province_ids", [])]
        for first, second in zip(ids, ids[1:]):
            code = min(first, second) * adjacency_base + max(first, second)
            if code not in adjacency:
                invalid_railways.append((first, second))
    if invalid_railways:
        raise ReworkError(f"Railway remap left invalid edges: {invalid_railways[:10]}")

    vp_shift = {pid: position_shift[pid] for pid in vp_ids}

    return {
        "province_validation": validation,
        "reference_ids_preserved": len(references),
        "maximum_reference_anchor_shift_pixels": max(position_shift.values(), default=0.0),
        "reference_anchor_shift_over_3_pixels": len(shifted),
        "maximum_vp_anchor_shift_pixels": max(vp_shift.values(), default=0.0),
        "vp_anchor_shift_over_3_pixels": sum(value > 3.0 for value in vp_shift.values()),
        "railway_edges_validated": len(railways.get("entries", [])),
    }


def _write_archive_atomic(
    project: Path,
    entries: dict[str, bytes],
    infos: dict[str, zipfile.ZipInfo],
) -> None:
    temporary_handle, temporary_name = tempfile.mkstemp(
        prefix=f".{project.name}.", suffix=".tmp", dir=project.parent
    )
    os.close(temporary_handle)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for name, payload in entries.items():
                info = copy.copy(infos[name])
                archive.writestr(info, payload)
        with zipfile.ZipFile(temporary, "r") as archive:
            bad_entry = archive.testzip()
            if bad_entry:
                raise ReworkError(f"Rebuilt archive is corrupt at {bad_entry}")
        os.replace(temporary, project)
    finally:
        if temporary.exists():
            temporary.unlink()


def rework(args: argparse.Namespace) -> dict[str, Any]:
    project = args.project.resolve()
    if not project.is_file():
        raise ReworkError(f"Project not found: {project}")
    entries, infos = _load_archive(project)
    required = {
        "province_map.npy", "tile_map.npy", "terrain_map.npy", "states.json",
        "countries.json", "continents.json", "strategic_regions.json",
        "provincial_terrain.json", "railways.json", "supply_nodes.json",
        "adjacencies.json", "adjacency_rules.json",
    }
    missing = required - set(entries)
    if missing:
        raise ReworkError(f"Project is missing required entries: {sorted(missing)}")

    old_map = _load_array(entries, "province_map.npy").astype(np.int32, copy=False)
    tile_map = _load_array(entries, "tile_map.npy")
    old_terrain_map = _load_array(entries, "terrain_map.npy")
    new_terrain_map = old_terrain_map.copy()
    old_states = json.loads(entries["states.json"])
    new_states = copy.deepcopy(old_states)
    strategic_regions = json.loads(entries["strategic_regions.json"])
    continents = json.loads(entries["continents.json"])
    provincial_terrain = json.loads(entries["provincial_terrain.json"])

    old_maximum = int(old_map.max())
    areas, sum_x, sum_y = _pid_statistics(old_map)
    pid_to_state, pid_to_owner = _state_pid_maps(old_states, old_maximum)
    state_pids = sorted(pid_to_owner)
    populations = _vp_population_lookup(old_states, args.report)
    vp_ids = {
        int(pid)
        for state in old_states.values()
        for pid in state.get("victory_points", {})
    }
    position_sensitive_ids = _position_sensitive_ids(entries, old_states)
    anchors = {
        pid: _safe_pixel(pid, old_map, areas, sum_x, sum_y)
        for pid in range(1, old_maximum + 1)
    }

    extra_parts: dict[int, int] = {}
    existing_validation = validate_provinces(tile_map, old_map, min_pixels=MIN_PROVINCE_PIXELS)
    for pid in existing_validation.get("too_large_ids", []):
        if int(pid) < len(areas) and tile_map[anchors[int(pid)]] == TILE_LAKE:
            extra_parts[int(pid)] = 2

    plan = _split_plan(
        areas,
        state_pids,
        populations,
        args.target_area,
        args.urban_population,
        old_maximum,
        args.max_provinces,
        extra_parts,
    )
    projected = old_maximum + sum(parts - 1 for parts in plan.values())
    print(
        f"Plan: split {len(plan):,} parents; {old_maximum:,} -> "
        f"{projected:,} provinces (cap {args.max_provinces:,})"
    )
    by_owner = Counter()
    for pid, parts in plan.items():
        by_owner[pid_to_owner.get(pid, "WATER")] += parts - 1
    print("New children by owner:", ", ".join(f"{key or 'UNOWNED'}={value:,}" for key, value in sorted(by_owner.items())))
    if not args.apply:
        return {"dry_run": True, "projected_provinces": projected, "children_by_owner": dict(by_owner)}

    clc = _load_clc(args.source_dir, old_map.shape)
    edge_cost = _landuse_edges(clc)
    urban_reference = np.isin(clc, URBAN_CLC_CLASSES) | (
        old_terrain_map == TERRAIN_PALETTE_INDEX["urban"]
    )

    new_map, children = _assign_splits(
        old_map, plan, anchors, edge_cost, position_sensitive_ids
    )
    protected_pixels = {anchors[pid] for pid in position_sensitive_ids}
    x_repairs = _repair_x_crossings_within_parents(new_map, old_map, protected_pixels)
    connectivity_repairs = _repair_non_contiguous_within_parents(
        new_map,
        old_map,
        {pid: anchors[pid] for pid in position_sensitive_ids},
    )
    x_repairs += _repair_x_crossings_within_parents(new_map, old_map, protected_pixels)
    _inherit_metadata(
        new_states,
        strategic_regions,
        continents,
        provincial_terrain,
        children,
        old_terrain_map,
        old_map,
    )

    major_city_ids = {
        pid for pid, population in populations.items()
        if population >= args.urban_population
    }
    for pid in major_city_ids:
        city_pixels = new_map == pid
        new_terrain_map[city_pixels & (tile_map == TILE_LAND)] = TERRAIN_PALETTE_INDEX["urban"]
        provincial_terrain[str(pid)] = "urban"

    old_railways = json.loads(entries["railways.json"])
    new_railways = _remap_railways(old_railways, old_map, new_map)

    validation = _validate_result(
        old_map,
        new_map,
        tile_map,
        old_states,
        new_states,
        entries,
        args.max_provinces,
        anchors,
        vp_ids,
        position_sensitive_ids,
        new_railways,
    )
    final_areas = np.bincount(new_map.ravel(), minlength=int(new_map.max()) + 1)
    actual_by_owner = Counter()
    for parent, child_ids in children.items():
        actual_by_owner[pid_to_owner.get(parent, "WATER")] += len(child_ids)
    report = {
        "project": str(project),
        "old_provinces": old_maximum,
        "new_provinces": int(new_map.max()),
        "parents_split": sum(bool(child_ids) for child_ids in children.values()),
        "children_created": int(new_map.max()) - old_maximum,
        "children_by_owner": dict(sorted(actual_by_owner.items())),
        "target_area_pixels": args.target_area,
        "minimum_area_pixels": int(final_areas[1:].min()),
        "median_area_pixels": float(np.median(final_areas[1:])),
        "maximum_area_pixels": int(final_areas[1:].max()),
        "major_city_provinces_painted_urban": len(major_city_ids),
        "major_city_anchor_on_urban_reference": sum(
            bool(urban_reference[anchors[pid]]) for pid in major_city_ids
        ),
        "x_crossing_pixels_repaired": x_repairs,
        "disconnected_fragment_pixels_repaired": connectivity_repairs,
        **validation,
    }

    entries["province_map.npy"] = _array_bytes(new_map)
    entries["terrain_map.npy"] = _array_bytes(new_terrain_map)
    entries["states.json"] = _json_bytes(new_states)
    entries["strategic_regions.json"] = _json_bytes(strategic_regions)
    entries["continents.json"] = _json_bytes(continents)
    entries["provincial_terrain.json"] = _json_bytes(provincial_terrain)
    entries["railways.json"] = _json_bytes(new_railways)

    backup = project.with_name(project.name + ".province_rework.bak")
    if backup.exists() and not args.overwrite_backup:
        raise ReworkError(
            f"Backup already exists: {backup}. Use --overwrite-backup after reviewing it."
        )
    shutil.copy2(project, backup)
    _write_archive_atomic(project, entries, infos)
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Backup: {backup}")
    print(f"Report: {args.output_report}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--target-area", type=int, default=DEFAULT_TARGET_AREA)
    parser.add_argument("--max-provinces", type=int, default=DEFAULT_MAX_PROVINCES)
    parser.add_argument("--urban-population", type=int, default=DEFAULT_URBAN_POPULATION)
    parser.add_argument(
        "--output-report",
        type=Path,
        default=ROOT / "projects" / "Belgium_Map_v1_1.province_rework.json",
    )
    parser.add_argument("--apply", action="store_true", help="Write the validated result")
    parser.add_argument("--overwrite-backup", action="store_true")
    args = parser.parse_args()
    if args.target_area < MIN_PROVINCE_PIXELS:
        parser.error(f"--target-area must be at least {MIN_PROVINCE_PIXELS}")
    if args.max_provinces < 1:
        parser.error("--max-provinces must be positive")
    try:
        report = rework(args)
    except ReworkError as exc:
        print(f"Province rework failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
