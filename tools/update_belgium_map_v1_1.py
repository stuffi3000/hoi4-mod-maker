"""Update the Belgium Map v1.1 project from the revised QGIS rasters.

The QGIS exports are anti-aliased RGB renders rather than HOI4 palette images.
This updater therefore extracts each selected colour as a blend between the
yellow land fill and the source colour, rasterises every river with orthogonal
steps, and uses the detailed river render only for shortest-path links between
large-river/canal components.  The resulting archive is checked after it is
written and a validation report is emitted beside it.

Usage::

    .\\.venv\\Scripts\\python.exe tools\\update_belgium_map_v1_1.py \\
        --project C:\\Users\\stuff\\Documents\\HOI4\\Belgium_Map_v1_1.hoi4proj

The command creates ``.bak`` before replacing the requested archive.  Use
``--dry-run`` to perform all extraction and validation without writing files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZipFile

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.constants import SEA_LEVEL, TILE_LAKE, TILE_LAND, TILE_SEA
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.generators.province import compact_province_ids
from domain.managers.continent import ContinentManager
from domain.managers.country import CountryManager
from domain.managers.river import (
    RIVER_BG_LAND,
    RIVER_BG_SEA,
    RIVER_MARKER,
    RIVER_MOUTH,
    RIVER_SOURCE,
    RIVER_WIDTH_1,
    RIVER_WIDTH_5,
    VALID_RIVER_VALUES,
    validate_rivers,
)
from domain.managers.state import StateManager
from domain.project_io import load_project, save_project
from domain.validators.province import (
    detect_x_crossings,
    detect_non_contiguous,
    _repair_large_provinces,
    validate_provinces,
)
from services.reference_map_service import (
    _bridge_diagonals,
    _pure_diagonal_count,
    _remove_solid_blocks_topologically,
)
from services.terrain_service import (
    TerrainGenConfig,
    compute_provincial_terrain_from_bmp,
    smart_auto_terrain,
)


DEFAULT_PROJECT = Path(r"C:\Users\stuff\Documents\HOI4\Belgium_Map_v1_1.hoi4proj")
DEFAULT_SOURCE_DIR = Path(r"C:\Users\stuff\Documents\HOI4\Belgium\base map\qgis\EU data")
TARGET_SIZE = (5632, 2048)  # width, height
MIN_LAKE_PIXELS = 50
LAND_FILL = np.asarray((207, 213, 16), dtype=np.float32)

SOURCE_FILES = {
    "states": "Print_states.png",
    "rivers": "Print_rivers.png",
    "rivers_full": "Print_rivers_full.png",
    "canals": "Print_canals.png",
    "inland_water": "Print_inland-water.png",
    "heightmap": "Print_heightmap.png",
}
SOURCE_COLOURS = {
    "rivers": (12, 6, 195),
    "rivers_full": (44, 37, 189),
    "canals": (0, 252, 18),
    "inland_water": (8, 225, 222),
}

CROSS = ndimage.generate_binary_structure(2, 1)
EIGHT = np.ones((3, 3), dtype=bool)


class UpdateError(RuntimeError):
    """Raised when a source or generated layer violates a required contract."""


def _load_rgb(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"), dtype=np.uint8)
    except Exception as exc:  # pragma: no cover - Pillow's exception varies by plugin
        raise UpdateError(f"Cannot read raster {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_sources(source_dir: Path, shape: tuple[int, int]) -> dict[str, Any]:
    if shape != (TARGET_SIZE[1], TARGET_SIZE[0]):
        raise UpdateError(f"Project layers are {shape[::-1]}; expected {TARGET_SIZE}")
    metadata: dict[str, Any] = {"directory": str(source_dir), "files": {}}
    for key, filename in SOURCE_FILES.items():
        path = source_dir / filename
        if not path.is_file():
            raise UpdateError(f"Missing required source raster: {path}")
        with Image.open(path) as image:
            if image.size != TARGET_SIZE:
                raise UpdateError(
                    f"{path.name} is {image.size}; expected {TARGET_SIZE}"
                )
            metadata["files"][key] = {
                "name": filename,
                "size": list(image.size),
                "mode": image.mode,
                "sha256": _sha256(path),
            }
    return metadata


def _blend_mask(
    rgb: np.ndarray,
    core_colour: tuple[int, int, int],
    *,
    tolerance: float = 10.0,
    minimum_ink: float = 0.03,
) -> np.ndarray:
    """Detect a source colour and its anti-aliased land-colour blends.

    QGIS's PNG export retains a one-pixel anti-alias fringe.  Every fringe
    colour lies on (or very close to) the line from the yellow land fill to the
    selected core colour; projecting onto that line recovers the complete
    feature without confusing the white sea background.
    """

    work = rgb.astype(np.float32, copy=False)
    core = np.asarray(core_colour, dtype=np.float32)
    vector = core - LAND_FILL
    denominator = float(np.dot(vector, vector))
    if denominator <= 0:
        raise UpdateError("Source core colour must differ from the land fill")
    projection = np.sum((work - LAND_FILL) * vector, axis=2) / denominator
    projected = LAND_FILL + projection[..., None] * vector
    residual = np.sqrt(np.sum((work - projected) ** 2, axis=2))
    return (
        (projection >= float(minimum_ink))
        & (projection <= 1.05)
        & (residual <= float(tolerance))
    )


def _remove_small_components(mask: np.ndarray, minimum_pixels: int) -> np.ndarray:
    labels, count = ndimage.label(mask, structure=EIGHT)
    if count == 0:
        return np.zeros_like(mask, dtype=bool)
    sizes = np.bincount(labels.ravel())
    keep = sizes >= max(1, int(minimum_pixels))
    keep[0] = False
    return keep[labels]


def _pure_diagonal_locations(mask: np.ndarray) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    result: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for direction in (1, -1):
        if direction == 1:
            upper = mask[:-1, :-1]
            lower = mask[1:, 1:]
            side_a = mask[1:, :-1]
            side_b = mask[:-1, 1:]
        else:
            upper = mask[:-1, 1:]
            lower = mask[1:, :-1]
            side_a = mask[1:, 1:]
            side_b = mask[:-1, :-1]
        ys, xs = np.where(upper & lower & ~side_a & ~side_b)
        for y, x in zip(ys.tolist(), xs.tolist()):
            if direction == 1:
                result.append(((y, x), (y + 1, x + 1)))
            else:
                result.append(((y, x + 1), (y + 1, x)))
    return result


def _remove_pure_diagonals(mask: np.ndarray) -> np.ndarray:
    """Remove a corner from isolated diagonal pairs while retaining lines."""

    result = mask.copy()
    for _ in range(6000):
        locations = _pure_diagonal_locations(result)
        if not locations:
            break
        first, second = locations[0]
        choices: list[tuple[int, int, int, int, int, int]] = []
        for py, px in (first, second):
            y0, y1 = max(0, py - 3), min(result.shape[0], py + 4)
            x0, x1 = max(0, px - 3), min(result.shape[1], px + 4)
            local = result[y0:y1, x0:x1].copy()
            local[py - y0, px - x0] = False
            local_blocks = int(
                (
                    local[:-1, :-1]
                    & local[:-1, 1:]
                    & local[1:, :-1]
                    & local[1:, 1:]
                ).sum()
            )
            local_diag = _pure_diagonal_count(local)
            local_components = ndimage.label(local, structure=CROSS)[1]
            degree = 0
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = py + dy, px + dx
                if 0 <= ny < result.shape[0] and 0 <= nx < result.shape[1]:
                    degree += int(result[ny, nx])
            choices.append(
                (local_diag, local_blocks, local_components, degree, py, px)
            )
        _, _, _, _, py, px = min(choices)
        result[py, px] = False
    return result


def _orthogonalise(mask: np.ndarray) -> np.ndarray:
    """Thin/bridge a source mask and enforce HOI4's H/V-only raster contract."""

    result = mask.astype(bool, copy=True)
    allowed = result.copy()
    for _ in range(4):
        result = _bridge_diagonals(result, allowed)
        result = _remove_solid_blocks_topologically(result)
    # The helper intentionally preserves ambiguous junctions.  Resolve the
    # handful of residual pure diagonals deterministically after it finishes.
    result = _remove_pure_diagonals(result)
    result = _remove_solid_blocks_topologically(result)
    return _remove_pure_diagonals(result)


def _build_lake_surface(
    old_tile_map: np.ndarray,
    inland_rgb: np.ndarray,
    minimum_pixels: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    lake_candidates = _blend_mask(inland_rgb, SOURCE_COLOURS["inland_water"])
    # Keep the existing coastline authoritative.  Clearing old lakes before
    # classification is deliberate: the revised image must be able to retain
    # a lake that already occupied a lake tile in the moved project.
    lake_candidates &= old_tile_map != TILE_SEA
    # Province connectivity is orthogonal in the editor; use the same
    # four-neighbour structure when filtering lake components so a diagonal
    # raster touch cannot become a sub-50-pixel detached lake province.
    lake_labels, lake_count = ndimage.label(lake_candidates, structure=CROSS)
    lake_sizes = np.bincount(lake_labels.ravel(), minlength=lake_count + 1)
    keep = lake_sizes >= max(1, int(minimum_pixels))
    keep[0] = False
    lake_candidates = keep[lake_labels]
    tile_map = old_tile_map.copy()
    tile_map[tile_map == TILE_LAKE] = TILE_LAND
    tile_map[lake_candidates] = TILE_LAKE
    return tile_map, lake_candidates, {
        "candidate_pixels": int(lake_candidates.sum()),
        "components": int(ndimage.label(lake_candidates, structure=EIGHT)[1]),
        "minimum_component_pixels": int(minimum_pixels),
    }


def _repair_disconnected_candidates(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    focus: np.ndarray,
    repair_reasons: dict[str, set[int]],
    next_id: int,
) -> tuple[int, int, int]:
    """Repair connectivity for province IDs near a changed surface boundary."""

    affected = ndimage.binary_dilation(focus, structure=CROSS, iterations=2)
    candidate_ids = np.unique(province_map[affected & (province_map > 0)])
    if candidate_ids.size == 0:
        return 0, next_id, 0
    # Gather all candidate coordinates in one vectorised pass.  Repeatedly
    # evaluating ``province_map == pid`` would rescan the 11.5-million-pixel
    # map once per candidate and is needlessly expensive.
    candidate_mask = np.isin(province_map, candidate_ids)
    candidate_y, candidate_x = np.where(candidate_mask)
    candidate_pid = province_map[candidate_mask]
    order = np.argsort(candidate_pid, kind="stable")
    candidate_y = candidate_y[order]
    candidate_x = candidate_x[order]
    candidate_pid = candidate_pid[order]
    repairs = 0
    surface_hole_fills = 0
    area_counts = np.bincount(province_map.ravel())
    start = 0
    while start < len(candidate_pid):
        source_pid = int(candidate_pid[start])
        stop = start + 1
        while stop < len(candidate_pid) and int(candidate_pid[stop]) == source_pid:
            stop += 1
        py = candidate_y[start:stop]
        px = candidate_x[start:stop]
        y0, y1 = int(py.min()), int(py.max()) + 1
        x0, x1 = int(px.min()), int(px.max()) + 1
        source_mask = np.zeros((y1 - y0, x1 - x0), dtype=bool)
        source_mask[py - y0, px - x0] = True
        labels, component_count = ndimage.label(source_mask, structure=CROSS)
        if component_count <= 1:
            start = stop
            continue
        sizes = np.bincount(labels.ravel(), minlength=component_count + 1)
        keep_label = int(np.argmax(sizes[1:]) + 1)
        source_type = int(tile_map[py[0], px[0]])
        for component_id in range(1, component_count + 1):
            if component_id == keep_label or sizes[component_id] == 0:
                continue
            component = labels == component_id
            ys, xs = np.where(component)
            contacts: dict[int, int] = {}
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = ys + y0 + dy, xs + x0 + dx
                valid = (
                    (ny >= 0) & (ny < province_map.shape[0])
                    & (nx >= 0) & (nx < province_map.shape[1])
                )
                if not valid.any():
                    continue
                neighbour_ids = province_map[ny[valid], nx[valid]]
                neighbour_types = tile_map[ny[valid], nx[valid]]
                for neighbour_pid, neighbour_type in zip(neighbour_ids, neighbour_types):
                    if (
                        int(neighbour_pid) > 0
                        and int(neighbour_type) == source_type
                        and int(neighbour_pid) != source_pid
                    ):
                        pid = int(neighbour_pid)
                        contacts[pid] = contacts.get(pid, 0) + 1
            if contacts:
                target_pid = max(
                    contacts,
                    key=lambda pid: (
                        contacts[pid],
                        int(area_counts[pid]) if pid < len(area_counts) else 0,
                        -pid,
                    ),
                )
            else:
                # A detached sliver often has no immediate orthogonal contact
                # after a lake cut.  Search a small halo before allocating a
                # new province; this keeps sub-50 remnants out of the final
                # definition while preserving the surface type.
                halo = ndimage.binary_dilation(
                    np.pad(component, 4), structure=EIGHT, iterations=4
                )
                hy0, hy1 = max(0, y0 - 4), min(province_map.shape[0], y1 + 4)
                hx0, hx1 = max(0, x0 - 4), min(province_map.shape[1], x1 + 4)
                halo = halo[: hy1 - hy0, : hx1 - hx0]
                halo_province = province_map[hy0:hy1, hx0:hx1]
                halo_tile = tile_map[hy0:hy1, hx0:hx1]
                halo_selection = (
                    halo
                    & (halo_tile == source_type)
                    & (halo_province > 0)
                )
                halo_ids = halo_province[
                    halo_selection
                ]
                halo_all_ids = halo_province[
                    halo
                    & (halo_province > 0)
                ]
                halo_all_types = halo_tile[
                    halo
                    & (halo_province > 0)
                ]
                halo_ids = halo_ids[halo_ids != source_pid]
                if halo_ids.size:
                    values, counts = np.unique(halo_ids, return_counts=True)
                    target_pid = int(values[int(np.argmax(counts))])
                    # The nearest province may be the opposite surface when
                    # a tiny land island is enclosed by a lake (or vice
                    # versa).  Keep the surface raster topologically sound.
                    opposite_type = TILE_LAKE if source_type == TILE_LAND else TILE_LAND
                    matching_types = [
                        int(tile)
                        for pid, tile in zip(halo_all_ids, halo_all_types)
                        if int(pid) != source_pid
                    ]
                    if (
                        matching_types
                        and source_type in (TILE_LAND, TILE_LAKE)
                        and matching_types.count(opposite_type) >= max(
                            1, matching_types.count(source_type)
                        )
                    ):
                        tile_map[ys + y0, xs + x0] = opposite_type
                        surface_hole_fills += int(len(ys))
                elif int(sizes[component_id]) < MIN_LAKE_PIXELS:
                    # Tiny land remnants enclosed by a revised lake are
                    # rasterisation holes, not meaningful land provinces.
                    # Promote them to the surrounding lake ID so both the
                    # surface and province remain orthogonally connected.
                    neighbour_types = []
                    neighbour_pids = []
                    for dy, dx in (
                        (-1, 0), (1, 0), (0, -1), (0, 1),
                    ):
                        ny, nx = ys + y0 + dy, xs + x0 + dx
                        valid = (
                            (ny >= 0) & (ny < province_map.shape[0])
                            & (nx >= 0) & (nx < province_map.shape[1])
                        )
                        neighbour_types.extend(tile_map[ny[valid], nx[valid]].tolist())
                        neighbour_pids.extend(province_map[ny[valid], nx[valid]].tolist())
                    opposite_type = TILE_LAKE if source_type == TILE_LAND else TILE_LAND
                    opposite_pids = [
                        int(pid)
                        for pid, tile in zip(neighbour_pids, neighbour_types)
                        if int(tile) == opposite_type and int(pid) > 0
                    ]
                    same_pids = [
                        int(pid)
                        for pid, tile in zip(neighbour_pids, neighbour_types)
                        if int(tile) == source_type and int(pid) > 0 and int(pid) != source_pid
                    ]
                    if opposite_pids and source_type in (TILE_LAND, TILE_LAKE):
                        values, counts = np.unique(opposite_pids, return_counts=True)
                        target_pid = int(values[int(np.argmax(counts))])
                        tile_map[ys + y0, xs + x0] = opposite_type
                        surface_hole_fills += int(len(ys))
                    elif same_pids:
                        values, counts = np.unique(same_pids, return_counts=True)
                        target_pid = int(values[int(np.argmax(counts))])
                    else:
                        target_pid = source_pid
                else:
                    target_pid = next_id
                    next_id += 1
            province_map[ys + y0, xs + x0] = target_pid
            repair_reasons["not_contiguous"].update((source_pid, target_pid))
            repairs += 1
        start = stop
    return repairs, next_id, surface_hole_fills


def _repair_remaining_components(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    repair_reasons: dict[str, set[int]],
    next_id: int,
) -> tuple[int, int]:
    """Finish a small set of detached IDs with explicit local reassignment."""

    repairs = 0
    for _ in range(3):
        ids = detect_non_contiguous(province_map)
        if not ids:
            break
        area_counts = np.bincount(province_map.ravel())
        changed = 0
        for source_pid in ids:
            source_pid = int(source_pid)
            coordinates = np.flatnonzero(province_map == source_pid)
            if coordinates.size == 0:
                continue
            ys, xs = np.divmod(coordinates, province_map.shape[1])
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            local = np.zeros((y1 - y0, x1 - x0), dtype=bool)
            local[ys - y0, xs - x0] = True
            labels, count = ndimage.label(local, structure=CROSS)
            if count <= 1:
                continue
            sizes = np.bincount(labels.ravel(), minlength=count + 1)
            keep = int(np.argmax(sizes[1:]) + 1)
            source_type = int(tile_map[ys[0], xs[0]])
            for component_id in range(1, count + 1):
                if component_id == keep or sizes[component_id] == 0:
                    continue
                cy, cx = np.where(labels == component_id)
                gy, gx = cy + y0, cx + x0
                contacts: dict[int, int] = {}
                for dy, dx in (
                    (-1, -1), (-1, 0), (-1, 1), (0, -1),
                    (0, 1), (1, -1), (1, 0), (1, 1),
                ):
                    ny, nx = gy + dy, gx + dx
                    valid = (
                        (ny >= 0) & (ny < province_map.shape[0])
                        & (nx >= 0) & (nx < province_map.shape[1])
                    )
                    if not valid.any():
                        continue
                    pids = province_map[ny[valid], nx[valid]]
                    types = tile_map[ny[valid], nx[valid]]
                    for pid, ptype in zip(pids, types):
                        if int(pid) > 0 and int(pid) != source_pid and int(ptype) == source_type:
                            contacts[int(pid)] = contacts.get(int(pid), 0) + 1
                if contacts:
                    target = max(
                        contacts,
                        key=lambda pid: (
                            contacts[pid],
                            int(area_counts[pid]) if pid < len(area_counts) else 0,
                            -pid,
                        ),
                    )
                elif int(sizes[component_id]) >= MIN_LAKE_PIXELS:
                    target = next_id
                    next_id += 1
                else:
                    # A genuinely isolated sub-50 component cannot be a valid
                    # province; merge it with the surrounding majority type.
                    neighbour_types: list[int] = []
                    neighbour_pids: list[int] = []
                    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        ny, nx = gy + dy, gx + dx
                        valid = (
                            (ny >= 0) & (ny < province_map.shape[0])
                            & (nx >= 0) & (nx < province_map.shape[1])
                        )
                        neighbour_types.extend(tile_map[ny[valid], nx[valid]].tolist())
                        neighbour_pids.extend(province_map[ny[valid], nx[valid]].tolist())
                    if neighbour_pids:
                        values, counts = np.unique(
                            [
                                int(pid)
                                for pid, ptype in zip(neighbour_pids, neighbour_types)
                                if int(pid) > 0 and int(ptype) == source_type and int(pid) != source_pid
                            ],
                            return_counts=True,
                        )
                    else:
                        values, counts = np.empty(0, dtype=np.int32), np.empty(0, dtype=np.int32)
                    if values.size:
                        target = int(values[int(np.argmax(counts))])
                    else:
                        opposite_type = TILE_LAKE if source_type == TILE_LAND else TILE_LAND
                        opposite = [
                            int(pid)
                            for pid, ptype in zip(neighbour_pids, neighbour_types)
                            if int(pid) > 0 and int(ptype) == opposite_type
                        ]
                        if opposite and source_type in (TILE_LAND, TILE_LAKE):
                            values, counts = np.unique(opposite, return_counts=True)
                            target = int(values[int(np.argmax(counts))])
                            tile_map[gy, gx] = opposite_type
                        else:
                            target = source_pid
                province_map[gy, gx] = target
                repair_reasons["not_contiguous"].update((source_pid, int(target)))
                changed += 1
        repairs += changed
        if not changed:
            break
    return repairs, next_id


def _repair_x_crossings_surface_safe(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    repair_reasons: dict[str, set[int]],
) -> int:
    """Fix mixed-surface X crossings without joining IDs diagonally."""

    height, width = province_map.shape
    area_counts = np.bincount(province_map.ravel())
    repaired = 0

    def removal_keeps_connected(pid: int, y: int, x: int) -> bool:
        """Reject a corner edit that would split the source province."""
        coordinates = np.flatnonzero(province_map == pid)
        if coordinates.size <= 1:
            return True
        ys, xs = np.divmod(coordinates, width)
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        local = np.zeros((y1 - y0, x1 - x0), dtype=bool)
        local[ys - y0, xs - x0] = True
        if not local[y - y0, x - x0]:
            return True
        local[y - y0, x - x0] = False
        return ndimage.label(local, structure=CROSS)[1] <= 1

    for y, x in detect_x_crossings(province_map):
        right = 0 if x == width - 1 else x + 1
        corners = ((y, x), (y, right), (y + 1, x), (y + 1, right))
        values = [int(province_map[py, px]) for py, px in corners]
        if len(set(values)) != 4:
            continue
        candidates: list[tuple[tuple[int, int, int, int], int, int]] = []
        for destination, (dy, dx) in enumerate(corners):
            dst_type = int(tile_map[dy, dx])
            contacts: dict[int, int] = {}
            # Use neighbours outside the 2x2 crossing.  The diagonal corner
            # itself is intentionally excluded: copying it would merely turn
            # the X into a diagonal-only connection for that province.
            for oy, ox in (
                (-1, -1), (-1, 0), (-1, 1),
                (0, -1), (0, 1),
                (1, -1), (1, 0), (1, 1),
                (-2, 0), (2, 0), (0, -2), (0, 2),
            ):
                ny = dy + oy
                nx = (dx + ox) % width
                if ny < 0 or ny >= height:
                    continue
                # Skip the other three corners of this crossing.
                if (ny, nx) in corners:
                    continue
                pid = int(province_map[ny, nx])
                if pid > 0 and int(tile_map[ny, nx]) == dst_type:
                    contacts[pid] = contacts.get(pid, 0) + 1
            for source_pid, contact_count in contacts.items():
                if source_pid == values[destination]:
                    continue
                if not removal_keeps_connected(values[destination], dy, dx):
                    continue
                score = (
                    int(area_counts[source_pid]) if source_pid < len(area_counts) else 0,
                    contact_count,
                    -source_pid,
                    -destination,
                )
                candidates.append((score, destination, source_pid))
        if not candidates:
            # At a one-pixel lake/land corner there may be no outside
            # same-surface province.  Copy an orthogonal corner's complete
            # surface/ID pair; changing one raster edge pixel is safer than
            # leaving an X-crossing that the game cannot load.
            fallback: list[tuple[tuple[int, int, int], int, int]] = []
            for destination, (dy, dx) in enumerate(corners):
                for source in (
                    (destination + 1) % 4,
                    (destination + 2) % 4,
                    (destination + 3) % 4,
                ):
                    if source == (destination + 2) % 4:
                        continue  # diagonal corner is never a safe bridge
                    source_pid = int(province_map[corners[source]])
                    if source_pid <= 0:
                        continue
                    destination_pid = values[destination]
                    fallback.append(
                        (
                            (
                                int(area_counts[destination_pid]) if destination_pid < len(area_counts) else 0,
                                int(tile_map[dy, dx] != tile_map[corners[source]]),
                                -int(area_counts[source_pid]) if source_pid < len(area_counts) else 0,
                            ),
                            destination,
                            source,
                        )
                    )
            if not fallback:
                continue
            # Prefer a corner whose province remains connected when the
            # pixel is removed; otherwise the later province validator would
            # trade this X for a detached one-pixel tail.
            safe_fallback = [
                item for item in fallback
                if removal_keeps_connected(values[item[1]], *corners[item[1]])
            ]
            if safe_fallback:
                fallback = safe_fallback
            _, destination, source = min(fallback)
            dy, dx = corners[destination]
            sy, sx = corners[source]
            old_pid = int(province_map[dy, dx])
            province_map[dy, dx] = province_map[sy, sx]
            tile_map[dy, dx] = tile_map[sy, sx]
            repair_reasons["border_adjusted"].update((old_pid, int(province_map[sy, sx])))
            repaired += 1
            continue
        # Removing a corner from the smallest province minimises damage; use
        # the largest adjacent target when several choices are possible.
        candidates.sort(key=lambda item: (int(area_counts[values[item[1]]]), -item[0][0], item[0][2]))
        _, destination, target_pid = candidates[0]
        dy, dx = corners[destination]
        old_pid = int(province_map[dy, dx])
        if old_pid == target_pid:
            continue
        province_map[dy, dx] = target_pid
        repair_reasons["border_adjusted"].update((old_pid, target_pid))
        repaired += 1
    return repaired


def _repair_surface_provinces(
    old_tile_map: np.ndarray,
    new_tile_map: np.ndarray,
    old_province_map: np.ndarray,
) -> tuple[np.ndarray, dict[str, int]]:
    """Keep existing land/sea IDs and rebuild only the revised lake set."""

    province_map = old_province_map.astype(np.int32, copy=True)
    changed = old_tile_map != new_tile_map
    lake = new_tile_map == TILE_LAKE
    province_map[changed | lake] = 0

    # Fill changed land/sea pixels from the nearest still-valid province of
    # that surface type.  This keeps political/strategic IDs stable.
    for tile_type in (TILE_LAND, TILE_SEA):
        target = new_tile_map == tile_type
        valid = target & (province_map > 0)
        if not valid.any():
            raise UpdateError(f"No existing province can seed tile type {tile_type}")
        _, nearest = ndimage.distance_transform_edt(
            ~valid, return_distances=True, return_indices=True
        )
        unassigned = target & (province_map == 0)
        province_map[unassigned] = province_map[
            nearest[0][unassigned], nearest[1][unassigned]
        ]

    # Allocate new lake IDs into old gaps first (the moved project has a lake
    # block immediately before its sea IDs), then append if necessary.  This
    # avoids remapping all existing province/state references.
    lake_labels, lake_count = ndimage.label(lake, structure=EIGHT)
    used = set(np.unique(province_map[province_map > 0]).tolist())
    next_candidate = 1
    allocated = 0
    for lake_id in range(1, lake_count + 1):
        pixels = lake_labels == lake_id
        while next_candidate in used:
            next_candidate += 1
        province_map[pixels] = next_candidate
        used.add(next_candidate)
        next_candidate += 1
        allocated += 1

    # Repair only province topology; the surface raster itself is authoritative
    # and is never changed by these routines.
    repair_reasons = {
        "border_adjusted": set(),
        "too_small_merged": set(),
        "too_small_removed": set(),
        "not_contiguous": set(),
        "too_large_split": set(),
    }
    topology_repairs = _repair_x_crossings_surface_safe(
        new_tile_map, province_map, repair_reasons
    )

    # Carving the revised lakes can split a few pre-existing land provinces.
    # The generic validator's disconnected repair recomputes a full-map area
    # cache for every component, which is unnecessarily expensive here.  Only
    # IDs touching the changed lake boundary can have changed connectivity;
    # repair those IDs with one local label pass each.
    next_id = int(province_map.max()) + 1
    # Repeat because a detached fragment assigned to another candidate ID can
    # make that target non-contiguous in the same pass.  Each pass still uses
    # one vectorised coordinate gather rather than a full-map scan per ID.
    surface_hole_fills = 0
    for _ in range(5):
        repaired, next_id, fills = _repair_disconnected_candidates(
            new_tile_map, province_map, changed, repair_reasons, next_id
        )
        topology_repairs += repaired
        surface_hole_fills += fills
        if not repaired:
            break

    # A lake island can leave a detached fragment whose ID is no longer in the
    # two-pixel focus halo after the first reassignment.  Two global candidate
    # passes catch those residuals with one vectorised gather each.
    all_pixels = np.ones_like(changed, dtype=bool)
    for _ in range(2):
        repaired, next_id, fills = _repair_disconnected_candidates(
            new_tile_map, province_map, all_pixels, repair_reasons, next_id
        )
        topology_repairs += repaired
        surface_hole_fills += fills
        if not repaired:
            break

    # Split any oversized province introduced by the changed surface while
    # retaining its tile type.  This is normally a single open-sea province.
    topology_repairs += _repair_large_provinces(
        new_tile_map, province_map, repair_reasons, MIN_LAKE_PIXELS
    )
    # New IDs and split fragments can create fresh 2x2 four-way crossings;
    # repeat the same-surface border repair after all reassignment work.
    for _ in range(8):
        fixed = _repair_x_crossings_surface_safe(new_tile_map, province_map, repair_reasons)
        topology_repairs += fixed
        if not fixed:
            break

    # Hole promotion above can move a handful of pixels from land to lake (or
    # the reverse).  Clear any resulting mixed-surface province pixels before
    # the final nearest-surface fill; otherwise a lake pixel could retain a
    # land ID and make that ID appear disconnected.
    max_pid = int(province_map.max())
    if max_pid > 0:
        type_counts = np.stack(
            [
                np.bincount(
                    province_map.ravel(),
                    weights=(new_tile_map.ravel() == tile_type).astype(np.int32),
                    minlength=max_pid + 1,
                )
                for tile_type in (TILE_LAND, TILE_SEA, TILE_LAKE)
            ]
        )
        dominant_type = np.asarray(
            (TILE_LAND, TILE_SEA, TILE_LAKE), dtype=np.uint8
        )[np.argmax(type_counts, axis=0)]
        mixed_pixels = (province_map > 0) & (
            new_tile_map != dominant_type[province_map]
        )
        province_map[mixed_pixels] = 0
    for tile_type in (TILE_LAND, TILE_SEA, TILE_LAKE):
        target = new_tile_map == tile_type
        valid = target & (province_map > 0)
        if not valid.any():
            raise UpdateError(f"Province repair removed all IDs for tile type {tile_type}")
        _, nearest = ndimage.distance_transform_edt(
            ~valid, return_distances=True, return_indices=True
        )
        unassigned = target & (province_map == 0)
        province_map[unassigned] = province_map[
            nearest[0][unassigned], nearest[1][unassigned]
        ]

    remaining_repairs, next_id = _repair_remaining_components(
        new_tile_map, province_map, repair_reasons, next_id
    )
    topology_repairs += remaining_repairs
    # The explicit reassignment cannot create unassigned pixels, but run one
    # more same-surface fill after any future-proof extension of that helper.
    for tile_type in (TILE_LAND, TILE_SEA, TILE_LAKE):
        target = new_tile_map == tile_type
        valid = target & (province_map > 0)
        if not valid.any():
            raise UpdateError(f"Province repair removed all IDs for tile type {tile_type}")
        _, nearest = ndimage.distance_transform_edt(
            ~valid, return_distances=True, return_indices=True
        )
        unassigned = target & (province_map == 0)
        province_map[unassigned] = province_map[
            nearest[0][unassigned], nearest[1][unassigned]
        ]

    for _ in range(8):
        fixed = _repair_x_crossings_surface_safe(new_tile_map, province_map, repair_reasons)
        topology_repairs += fixed
        if not fixed:
            break
    # Border corrections can detach a one-pixel tail from the destination
    # province.  Resolve that interaction once more, then finish with a final
    # crossing pass.
    remaining_repairs, next_id = _repair_remaining_components(
        new_tile_map, province_map, repair_reasons, next_id
    )
    topology_repairs += remaining_repairs
    for _ in range(8):
        fixed = _repair_x_crossings_surface_safe(new_tile_map, province_map, repair_reasons)
        topology_repairs += fixed
        if not fixed:
            break
    # If the old map had an unusual gap pattern, compacting is the safest
    # fallback.  Normal Belgium v1.1 input uses all IDs except its old lake
    # block, so this branch is not expected and is reported if encountered.
    unique = np.unique(province_map)
    if unique.size and unique[0] == 0:
        expected = np.arange(int(unique.max()) + 1, dtype=unique.dtype)
    else:
        expected = np.arange(1, int(unique.max()) + 1, dtype=unique.dtype)
    compacted = not np.array_equal(unique, expected)
    if compacted:
        compact_province_ids(province_map)

    return province_map, {
        "changed_surface_pixels": int(changed.sum()),
        "surface_hole_fills": int(surface_hole_fills),
        "lake_provinces": int(allocated),
        "compacted_ids": int(compacted),
        "topology_repairs": int(topology_repairs),
        "topology_repair_ids": int(
            len(set().union(*(set(values) for values in repair_reasons.values())))
        ),
    }


def _connect_with_full_rivers(
    primary: np.ndarray,
    detailed: np.ndarray,
) -> tuple[np.ndarray, dict[str, int]]:
    """Join primary components through the detailed raster using an MST."""

    primary = primary.astype(bool, copy=True)
    detailed = detailed.astype(bool, copy=False)
    primary_labels, primary_count = ndimage.label(primary, structure=CROSS)
    detailed_labels, detailed_count = ndimage.label(detailed, structure=CROSS)
    result = primary.copy()
    components_used = 0
    groups_linked = 0
    pixels_added = 0

    for detailed_id, bounds in enumerate(
        ndimage.find_objects(detailed_labels), start=1
    ):
        if bounds is None:
            continue
        sub = detailed_labels[bounds] == detailed_id
        primary_sub = primary_labels[bounds]
        groups = np.unique(primary_sub[sub & (primary_sub > 0)])
        if groups.size < 2:
            continue
        components_used += 1
        y0, x0 = bounds[0].start, bounds[1].start
        height, width = sub.shape

        # Multi-source BFS gives a shortest path from every primary group to
        # every other group in this detailed component.
        owner = np.full((height, width), -1, dtype=np.int32)
        parent = np.full((height, width), -1, dtype=np.int32)
        distance = np.full((height, width), -1, dtype=np.int32)
        queue: deque[int] = deque()
        seeds = np.argwhere(sub & (primary_sub > 0))
        for sy, sx in seeds.tolist():
            group = int(primary_sub[sy, sx])
            if owner[sy, sx] < 0:
                owner[sy, sx] = group
                distance[sy, sx] = 0
                queue.append(int(sy * width + sx))

        edges: dict[tuple[int, int], tuple[int, tuple[int, int], tuple[int, int]]] = {}
        while queue:
            flat = queue.popleft()
            y, x = divmod(flat, width)
            group = int(owner[y, x])
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y + dy, x + dx
                if ny < 0 or nx < 0 or ny >= height or nx >= width or not sub[ny, nx]:
                    continue
                other = int(owner[ny, nx])
                if other < 0:
                    owner[ny, nx] = group
                    distance[ny, nx] = distance[y, x] + 1
                    parent[ny, nx] = flat
                    queue.append(int(ny * width + nx))
                elif other != group:
                    key = (min(group, other), max(group, other))
                    score = int(distance[y, x]) + int(distance[ny, nx]) + 1
                    previous = edges.get(key)
                    if previous is None or score < previous[0]:
                        edges[key] = (score, (y, x), (ny, nx))

        disjoint = {int(group): int(group) for group in groups.tolist()}

        def find(value: int) -> int:
            while disjoint[value] != value:
                disjoint[value] = disjoint[disjoint[value]]
                value = disjoint[value]
            return value

        for (left, right), (_, first, second) in sorted(
            edges.items(), key=lambda item: item[1][0]
        ):
            root_left, root_right = find(left), find(right)
            if root_left == root_right:
                continue
            disjoint[root_left] = root_right
            groups_linked += 1
            for sy, sx in (first, second):
                flat = int(sy * width + sx)
                while flat >= 0:
                    py, px = divmod(flat, width)
                    gy, gx = y0 + py, x0 + px
                    if not result[gy, gx]:
                        result[gy, gx] = True
                        pixels_added += 1
                    flat = int(parent[py, px])

    return result, {
        "detailed_components": int(detailed_count),
        "primary_components_before_links": int(primary_count),
        "detailed_components_used_for_links": int(components_used),
        "groups_linked": int(groups_linked),
        "connector_pixels_added": int(pixels_added),
    }


def _build_river_map(
    tile_map: np.ndarray,
    height_map: np.ndarray,
    main_source: np.ndarray,
    canal_source: np.ndarray,
    detailed_source: np.ndarray,
) -> tuple[np.ndarray, dict[str, int]]:
    land = tile_map == TILE_LAND
    main = _orthogonalise(main_source & land)
    canals = _orthogonalise(canal_source & land)
    detailed = _orthogonalise(detailed_source & land)
    primary = main | canals
    linked, link_stats = _connect_with_full_rivers(primary, detailed)

    # Final topology pass after connector paths.  Insertion/removal is bounded
    # and deterministic; all pixels remain on land and all links stay H/V.
    line_mask = linked & land
    for _ in range(6):
        line_mask = _remove_solid_blocks_topologically(line_mask)
        # Restrict inserted orthogonal bridge pixels to land.  Passing the
        # land mask as ``allowed`` prevents a cleanup bridge from leaking into
        # a sea/lake tile at a raster edge.
        line_mask = _bridge_diagonals(line_mask, land)
        line_mask = _remove_solid_blocks_topologically(line_mask)
    line_mask &= land
    line_mask = _remove_pure_diagonals(line_mask)
    # A handful of anti-alias specks can survive the source-mask cleanup at
    # the image border.  They are not usable HOI4 rivers and cannot carry both
    # source and mouth markers, so discard only these sub-8-pixel fragments.
    line_mask = _remove_small_components(line_mask, 8)

    water = (tile_map == TILE_SEA) | (tile_map == TILE_LAKE)
    river_map = np.full(tile_map.shape, RIVER_BG_LAND, dtype=np.uint8)
    river_map[water] = RIVER_BG_SEA
    river_map[line_mask] = RIVER_WIDTH_1
    river_map[line_mask & main] = RIVER_WIDTH_5

    labels, network_count = ndimage.label(line_mask, structure=CROSS)
    degrees = ndimage.convolve(line_mask.astype(np.uint8), CROSS.astype(np.uint8)) - line_mask
    water_halo = ndimage.binary_dilation(water, structure=EIGHT, iterations=1)
    source_total = mouth_total = confluence_total = 0
    fallback_mouths = 0
    for network_id, bounds in enumerate(ndimage.find_objects(labels), start=1):
        if bounds is None:
            continue
        local = labels[bounds] == network_id
        local_degrees = degrees[bounds]
        ys, xs = np.where(local)
        gy, gx = ys + bounds[0].start, xs + bounds[1].start
        endpoints = local & (local_degrees <= 1)
        ey, ex = np.where(endpoints)
        if len(ey) == 0:
            ey, ex = ys, xs
        eyg, exg = ey + bounds[0].start, ex + bounds[1].start

        # Highest endpoint is the source; this is consistent with the DEM
        # while remaining deterministic when elevations tie.
        order = np.lexsort((exg, eyg, -height_map[eyg, exg]))
        source_y, source_x = int(eyg[order[0]]), int(exg[order[0]])

        touches_water = water_halo[eyg, exg]
        mouth_coords = [
            (int(y), int(x))
            for y, x, touches in zip(eyg, exg, touches_water)
            if bool(touches) and (int(y), int(x)) != (source_y, source_x)
        ]
        if not mouth_coords:
            alternatives = [
                (int(y), int(x))
                for y, x in zip(eyg, exg)
                if (int(y), int(x)) != (source_y, source_x)
            ]
            if alternatives:
                alternatives.sort(key=lambda p: (int(height_map[p]), p[0], p[1]))
                mouth_coords = [alternatives[0]]
                fallback_mouths += 1

        # Junction pixels are red confluence markers.  Marker precedence is
        # confluence -> mouth -> source so source/mouth retain their semantics.
        confluence = local & (local_degrees >= 3)
        cy, cx = np.where(confluence)
        cgy, cgx = cy + bounds[0].start, cx + bounds[1].start
        river_map[cgy, cgx] = RIVER_MARKER
        confluence_total += len(cgy)
        for my, mx in mouth_coords:
            river_map[my, mx] = RIVER_MOUTH
        mouth_total += len(mouth_coords)
        river_map[source_y, source_x] = RIVER_SOURCE
        source_total += 1

    topology = {
        "line_pixels": int(line_mask.sum()),
        "networks": int(network_count),
        "source_markers": int(source_total),
        "mouth_markers": int(mouth_total),
        "confluence_markers": int(confluence_total),
        "fallback_mouth_markers": int(fallback_mouths),
        "main_source_pixels": int(main.sum()),
        "canal_source_pixels": int(canals.sum()),
        "detailed_source_pixels": int(detailed.sum()),
        **link_stats,
    }
    return river_map, topology


def _strict_river_validation(
    river_map: np.ndarray,
    tile_map: np.ndarray,
) -> dict[str, Any]:
    line = np.isin(river_map, list(VALID_RIVER_VALUES))
    labels4, count4 = ndimage.label(line, structure=CROSS)
    labels8, count8 = ndimage.label(line, structure=EIGHT)
    degrees = ndimage.convolve(line.astype(np.uint8), CROSS.astype(np.uint8)) - line
    errors: list[str] = []
    invalid = ~np.isin(river_map, list(VALID_RIVER_VALUES) + [RIVER_BG_LAND, RIVER_BG_SEA])
    if invalid.any():
        errors.append(f"{int(invalid.sum())} invalid river-map values")
    if np.any(line & (tile_map != TILE_LAND)):
        errors.append(f"{int((line & (tile_map != TILE_LAND)).sum())} river pixels on water")
    blocks = line[:-1, :-1] & line[:-1, 1:] & line[1:, :-1] & line[1:, 1:]
    diagonal_count = _pure_diagonal_count(line)
    if blocks.any():
        errors.append(f"{int(blocks.sum())} solid 2x2 river blocks")
    if diagonal_count:
        errors.append(f"{int(diagonal_count)} diagonal-only river joins")
    if count4 != count8:
        errors.append(f"4/8-connectivity mismatch ({count4}/{count8})")

    network_details: list[dict[str, int]] = []
    for network_id in range(1, count4 + 1):
        component = labels4 == network_id
        sources = int((river_map[component] == RIVER_SOURCE).sum())
        mouths = int((river_map[component] == RIVER_MOUTH).sum())
        confluences = int((river_map[component] == RIVER_MARKER).sum())
        if sources != 1:
            errors.append(f"river network {network_id} has {sources} source markers")
        if mouths < 1:
            errors.append(f"river network {network_id} has no mouth marker")
        network_details.append(
            {
                "pixels": int(component.sum()),
                "sources": sources,
                "mouths": mouths,
                "confluences": confluences,
            }
        )

    tool_messages = validate_rivers(river_map, lang="en")
    tool_passed = len(tool_messages) == 1 and "passed" in tool_messages[0].lower()
    if not tool_passed:
        errors.extend(f"tool validator: {message}" for message in tool_messages)
    if errors:
        raise UpdateError("River validation failed: " + "; ".join(errors[:8]))
    return {
        "passed": True,
        "line_pixels": int(line.sum()),
        "networks_4_connected": int(count4),
        "networks_8_connected": int(count8),
        "solid_blocks": int(blocks.sum()),
        "diagonal_only_joins": int(diagonal_count),
        "tool_messages": tool_messages,
        "network_details": network_details,
    }


def _prepare_height_and_terrain(
    source_height: np.ndarray,
    tile_map: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    raw = source_height.astype(np.uint8, copy=True)
    height = raw.copy()
    land = tile_map == TILE_LAND
    sea = tile_map == TILE_SEA
    lake = tile_map == TILE_LAKE
    # Keep the source relief values intact wherever valid; only enforce the
    # engine's waterline contracts and flatten lakes to a stable water level.
    height[land] = np.maximum(height[land], SEA_LEVEL + 1)
    height[sea] = np.minimum(height[sea], SEA_LEVEL - 1)
    height[lake] = SEA_LEVEL - 5

    terrain = smart_auto_terrain(
        height,
        tile_map,
        TerrainGenConfig(seed=42, noise_amplitude=10.0),
    ).astype(np.uint8, copy=False)
    terrain[tile_map == TILE_SEA] = TERRAIN_PALETTE_INDEX["ocean"]
    terrain[tile_map == TILE_LAKE] = TERRAIN_PALETTE_INDEX["lakes"]
    terrain[tile_map == TILE_LAND] = np.where(
        np.isin(terrain[tile_map == TILE_LAND],
                (TERRAIN_PALETTE_INDEX["ocean"], TERRAIN_PALETTE_INDEX["lakes"])),
        TERRAIN_PALETTE_INDEX["plains"],
        terrain[tile_map == TILE_LAND],
    )
    report = {
        "source_range": [int(raw.min()), int(raw.max())],
        "height_ranges": {
            "land": [int(height[land].min()), int(height[land].max())],
            "sea": [int(height[sea].min()), int(height[sea].max())],
            "lake": [int(height[lake].min()), int(height[lake].max())],
        },
        "terrain_pixels": {
            str(int(value)): int((terrain == value).sum())
            for value in np.unique(terrain)
        },
    }
    return height, terrain, report


def _repair_state_references(state_mgr: StateManager, province_map: np.ndarray, tile_map: np.ndarray) -> int:
    land_ids = set(np.unique(province_map[tile_map == TILE_LAND]).tolist())
    removed = 0
    state_mgr._province_to_state.clear()
    for state in state_mgr.states.values():
        old = list(state.provinces)
        state.provinces = [pid for pid in old if pid in land_ids]
        removed += len(old) - len(state.provinces)
        state.victory_points = {
            pid: value for pid, value in state.victory_points.items() if pid in land_ids
        }
        state.province_buildings = {
            pid: value for pid, value in state.province_buildings.items() if pid in land_ids
        }
        for pid in state.provinces:
            state_mgr._province_to_state[pid] = state.id
    return removed


def _validate_project_layers(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    terrain_map: np.ndarray,
    height_map: np.ndarray,
    river_map: np.ndarray,
) -> dict[str, Any]:
    expected_shape = (TARGET_SIZE[1], TARGET_SIZE[0])
    arrays = (tile_map, province_map, terrain_map, height_map, river_map)
    if any(array.shape != expected_shape for array in arrays):
        raise UpdateError("Saved layers do not share the expected 5632x2048 shape")
    if np.any((tile_map > 0) & (province_map == 0)):
        raise UpdateError("A surface pixel has no province ID")

    land = tile_map == TILE_LAND
    sea = tile_map == TILE_SEA
    lake = tile_map == TILE_LAKE
    if np.any(height_map[land] <= SEA_LEVEL):
        raise UpdateError("Land height is not strictly above sea level")
    if np.any(height_map[sea] >= SEA_LEVEL) or np.any(height_map[lake] >= SEA_LEVEL):
        raise UpdateError("Sea/lake height is not below sea level")
    if np.any(terrain_map[sea] != TERRAIN_PALETTE_INDEX["ocean"]):
        raise UpdateError("Sea terrain is not ocean")
    if np.any(terrain_map[lake] != TERRAIN_PALETTE_INDEX["lakes"]):
        raise UpdateError("Lake terrain is not lakes")
    if np.any(np.isin(terrain_map[land],
                      (TERRAIN_PALETTE_INDEX["ocean"], TERRAIN_PALETTE_INDEX["lakes"]))):
        raise UpdateError("Land contains a water terrain index")

    province_report = validate_provinces(tile_map, province_map, min_pixels=50)
    hard = {
        key: int(province_report[key])
        for key in ("x_crossings", "too_small", "not_contiguous", "too_large")
        if province_report.get(key)
    }
    gaps = province_report.get("id_gaps") or []
    if gaps:
        hard["id_gaps"] = len(gaps)
    if hard:
        raise UpdateError(f"Province validation failed: {hard}")
    return {
        "province_validation": {
            key: value for key, value in province_report.items()
            if key in ("province_count", "id_gaps", "x_crossings", "too_small", "not_contiguous", "too_large")
        },
        "surface_pixels": {
            "land": int(land.sum()),
            "sea": int(sea.sum()),
            "lake": int(lake.sum()),
        },
    }


def _archive_entries(path: Path) -> list[str]:
    with ZipFile(path, "r") as archive:
        return archive.namelist()


def update_project(
    project_path: Path,
    source_dir: Path,
    *,
    minimum_lake_pixels: int = MIN_LAKE_PIXELS,
    dry_run: bool = False,
    report_path: Path | None = None,
) -> dict[str, Any]:
    if not project_path.is_file():
        raise UpdateError(f"Project archive does not exist: {project_path}")
    if minimum_lake_pixels < 1:
        raise UpdateError("minimum lake component size must be positive")

    state_mgr = StateManager()
    country_mgr = CountryManager()
    continent_mgr = ContinentManager()
    tile_map, province_map, old_terrain, old_height, old_rivers, old_pt, snapshot = load_project(
        str(project_path), state_mgr, country_mgr, continent_mgr
    )
    source_meta = _validate_sources(source_dir, tile_map.shape)
    source = {key: _load_rgb(source_dir / filename) for key, filename in SOURCE_FILES.items()}

    new_tile_map, lake_mask, lake_stats = _build_lake_surface(
        tile_map, source["inland_water"], minimum_lake_pixels
    )
    new_province_map, province_repair = _repair_surface_provinces(
        tile_map, new_tile_map, province_map
    )
    source_height = np.asarray(
        Image.open(source_dir / SOURCE_FILES["heightmap"]).convert("L"), dtype=np.uint8
    )
    new_height, new_terrain, terrain_stats = _prepare_height_and_terrain(
        source_height, new_tile_map
    )

    river_map, river_stats = _build_river_map(
        new_tile_map,
        new_height,
        _blend_mask(source["rivers"], SOURCE_COLOURS["rivers"]),
        _blend_mask(source["canals"], SOURCE_COLOURS["canals"]),
        _blend_mask(source["rivers_full"], SOURCE_COLOURS["rivers_full"]),
    )
    river_validation = _strict_river_validation(river_map, new_tile_map)
    layer_validation = _validate_project_layers(
        new_tile_map, new_province_map, new_terrain, new_height, river_map
    )
    provincial_terrain = compute_provincial_terrain_from_bmp(
        new_terrain, new_province_map, new_tile_map
    )
    removed_state_refs = _repair_state_references(
        state_mgr, new_province_map, new_tile_map
    )

    before_stats = {
        "surface_pixels": {
            "land": int((tile_map == TILE_LAND).sum()),
            "sea": int((tile_map == TILE_SEA).sum()),
            "lake": int((tile_map == TILE_LAKE).sum()),
        },
        "river_pixels": int(np.isin(old_rivers, list(VALID_RIVER_VALUES)).sum()) if old_rivers is not None else 0,
        "river_networks": int(ndimage.label(np.isin(old_rivers, list(VALID_RIVER_VALUES)), structure=CROSS)[1]) if old_rivers is not None else 0,
        "height_range": [int(old_height.min()), int(old_height.max())],
    }
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": str(project_path),
        "source": source_meta,
        "before": before_stats,
        "after": {
            "lake": lake_stats,
            "province_repair": province_repair,
            "river": river_stats,
            "river_validation": river_validation,
            "terrain_height": terrain_stats,
            "layer_validation": layer_validation,
            "provincial_terrain_entries": len(provincial_terrain),
            "removed_state_province_references": removed_state_refs,
        },
        "dry_run": bool(dry_run),
    }

    if not dry_run:
        backup = project_path.with_suffix(project_path.suffix + ".bak")
        if backup.exists():
            index = 2
            while project_path.with_suffix(project_path.suffix + f".bak{index}").exists():
                index += 1
            backup = project_path.with_suffix(project_path.suffix + f".bak{index}")
        shutil.copy2(project_path, backup)
        temporary = project_path.with_suffix(project_path.suffix + ".tmp")
        if temporary.exists():
            temporary.unlink()
        entries_before = _archive_entries(project_path)
        save_project(
            str(temporary),
            tile_map=new_tile_map,
            province_map=new_province_map,
            terrain_map=new_terrain,
            height_map=new_height,
            state_mgr=state_mgr,
            country_mgr=country_mgr,
            river_map=river_map,
            continent_mgr=continent_mgr if "continents.json" in entries_before else None,
            provincial_terrain=provincial_terrain,
            tile_snapshot=new_tile_map.copy(),
        )
        os.replace(temporary, project_path)
        report["backup"] = str(backup)
        report["project_sha256"] = _sha256(project_path)

        # Reload the written archive independently; this catches serialization
        # and shape errors that an in-memory validation cannot see.
        check_state = StateManager()
        check_country = CountryManager()
        check_continent = ContinentManager()
        reloaded = load_project(str(project_path), check_state, check_country, check_continent)
        checks = {
            "tile_equal": bool(np.array_equal(reloaded[0], new_tile_map)),
            "province_equal": bool(np.array_equal(reloaded[1], new_province_map)),
            "terrain_equal": bool(np.array_equal(reloaded[2], new_terrain)),
            "height_equal": bool(np.array_equal(reloaded[3], new_height)),
            "river_equal": bool(np.array_equal(reloaded[4], river_map)),
            "shape": list(reloaded[0].shape),
        }
        if not all(checks[key] for key in ("tile_equal", "province_equal", "terrain_equal", "height_equal", "river_equal")):
            raise UpdateError(f"Reloaded archive differs from generated layers: {checks}")
        report["reload_validation"] = checks

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--minimum-lake-pixels", type=int, default=MIN_LAKE_PIXELS)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report_path = args.report
    if report_path is None and not args.dry_run:
        report_path = args.project.with_name(args.project.stem + ".validation.json")
    try:
        report = update_project(
            args.project,
            args.source_dir,
            minimum_lake_pixels=args.minimum_lake_pixels,
            dry_run=args.dry_run,
            report_path=report_path,
        )
    except UpdateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "project": report["project"],
        "dry_run": report["dry_run"],
        "lake_pixels": report["after"]["lake"]["candidate_pixels"],
        "river_pixels": report["after"]["river_validation"]["line_pixels"],
        "river_networks": report["after"]["river_validation"]["networks_4_connected"],
        "height_ranges": report["after"]["terrain_height"]["height_ranges"],
        "report": str(report_path) if report_path else None,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
