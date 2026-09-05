"""Build the validated Belgium Map v1.1 HOI4 Map Maker project.

The source files are QGIS exports and their accompanying ETRS89 / LAEA Europe
reference data.  The resulting project is intentionally a map-only project:
political state and country ownership can be authored in the editor after the
geographic layers have been reviewed.

Usage::

    .\\.venv\\Scripts\\python.exe tools\\create_belgium_map_v1_1.py

The generated ``.hoi4proj`` and its validation report are written below the
ignored ``output/Belgium_Map_v1_1`` directory by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.constants import SEA_LEVEL, TILE_LAKE, TILE_LAND, TILE_SEA
from data.terrain_types import TERRAIN_PALETTE_INDEX, TERRAIN_TYPES
from domain.generators.province import (
    auto_classify_water,
    compact_province_ids,
    generate_province_colors,
    generate_provinces_for_type,
)
from domain.managers.continent import ContinentManager
from domain.managers.country import CountryManager
from domain.managers.river import (
    RIVER_BG_LAND,
    RIVER_BG_SEA,
    VALID_RIVER_VALUES,
    validate_rivers,
)
from domain.managers.state import StateManager
from domain.project_io import save_project
from domain.validators.province import (
    _merge_small_provinces,
    _remove_unrepairable_small_provinces,
    _repair_disconnected_provinces,
    _repair_x_crossings,
    validate_provinces,
)
from services.reference_map_service import (
    generate_hydrology_from_rgb,
    generate_land_water_from_rgb,
    generate_provinces_from_rgb,
)
from services.terrain_service import compute_provincial_terrain_from_bmp


DEFAULT_SOURCE_DIR = Path(r"C:\Users\stuff\Documents\HOI4\Belgium")
DEFAULT_OUTPUT_DIR = ROOT / "output" / "Belgium_Map_v1_1"
PROJECT_NAME = "Belgium_Map_v1_1"
TARGET_SIZE = (5632, 2048)
MIN_PROVINCE_PIXELS = 50

# Representative QGIS palette entries.  Keeping the selections explicit makes
# reruns independent of palette quantisation and UI colour-picker heuristics.
STATE_LAND_COLOR = (221, 136, 57)
SEA_COLOR = (255, 255, 255)
RIVER_COLORS = (
    (12, 6, 195),
    (18, 13, 154),
    (22, 19, 124),
    (25, 23, 101),
)


class GenerationError(RuntimeError):
    """Raised when a source or generated layer fails a required check."""


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _read_world_file(path: Path) -> tuple[float, float, float, float, float, float]:
    values = [line.strip().replace(",", ".") for line in path.read_text().splitlines()]
    if len(values) != 6:
        raise GenerationError(f"Expected six values in world file: {path}")
    try:
        return tuple(float(value) for value in values)  # type: ignore[return-value]
    except ValueError as exc:
        raise GenerationError(f"Invalid numeric value in world file: {path}") from exc


def _read_extent_file(path: Path) -> tuple[float, float, float, float]:
    values: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        values[key.strip().lower()] = float(value.strip().replace(",", "."))
    required = ("x min", "y min", "x max", "y max")
    missing = [key for key in required if key not in values]
    if missing:
        raise GenerationError(f"Extent file is missing: {', '.join(missing)}")
    return values["x min"], values["y min"], values["x max"], values["y max"]


def _world_extent(
    world: tuple[float, float, float, float, float, float], image_size: tuple[int, int]
) -> tuple[float, float, float, float]:
    """Return outer raster bounds; world files specify the upper-left centre."""
    pixel_x, rotation_y, rotation_x, pixel_y, origin_x, origin_y = world
    if rotation_x != 0 or rotation_y != 0:
        raise GenerationError("Rotated world files are not supported by this importer")
    if pixel_x <= 0 or pixel_y >= 0:
        raise GenerationError("World file must use positive X and negative Y resolution")
    width, height = image_size
    x_min = origin_x - pixel_x / 2.0
    x_max = origin_x + pixel_x * (width - 0.5)
    y_max = origin_y - pixel_y / 2.0
    y_min = origin_y + pixel_y * (height - 0.5)
    return x_min, y_min, x_max, y_max


def validate_source_layout(source_dir: Path) -> dict[str, Any]:
    """Validate QGIS source files, CRS metadata, and raster/grid alignment."""
    qgis_dir = source_dir / "base map" / "qgis" / "EU data"
    required = {
        "state outlines": qgis_dir / "Print_states.png",
        "inland water": qgis_dir / "Print_inland-water.png",
        "rivers": qgis_dir / "Print_inland-water-rivers.png",
        "reference raster": qgis_dir / "test3.png",
        "world file": qgis_dir / "test3.pgw",
        "extent metadata": qgis_dir / "extents.txt",
        "country CRS": qgis_dir / "CNTR_RG_01M_2024_3035.prj",
        "commune CRS": qgis_dir / "COMM_RG_01M_2016_3035.prj",
        "country geometry": qgis_dir / "CNTR_RG_01M_2024_3035.shp",
        "commune geometry": qgis_dir / "COMM_RG_01M_2016_3035.shp",
        "satellite base map": source_dir / "base map.png",
    }
    missing = [label for label, path in required.items() if not path.is_file()]
    if missing:
        raise GenerationError(f"Missing required source data: {', '.join(missing)}")

    state_size = Image.open(required["state outlines"]).size
    water_size = Image.open(required["inland water"]).size
    river_size = Image.open(required["rivers"]).size
    satellite_size = Image.open(required["satellite base map"]).size
    if any(size != TARGET_SIZE for size in (state_size, water_size, river_size, satellite_size)):
        raise GenerationError(
            "QGIS/state/water/river/satellite rasters must all be 5632x2048"
        )

    reference_size = Image.open(required["reference raster"]).size
    world = _read_world_file(required["world file"])
    measured_extent = _world_extent(world, reference_size)
    declared_extent = _read_extent_file(required["extent metadata"])
    max_extent_error = max(
        abs(actual - expected)
        for actual, expected in zip(measured_extent, declared_extent)
    )
    # QGIS's saved canvas extent is allowed to differ from a pixel-centre
    # world-file reconstruction by less than half a source pixel.  This
    # fixture has a symmetric 32.75 m Y difference (about 0.27 px), while
    # its X bounds are exact; treating that as a misalignment would reject a
    # valid render solely because of QGIS's export rounding.
    half_pixel_tolerance = max(abs(world[0]), abs(world[3])) / 2.0 + 0.001
    if max_extent_error > half_pixel_tolerance:
        raise GenerationError(
            "World-file bounds disagree with extents.txt by "
            f"{max_extent_error:.3f} m (tolerance {half_pixel_tolerance:.3f} m)"
        )

    crs_texts = [
        required["country CRS"].read_text(encoding="utf-8"),
        required["commune CRS"].read_text(encoding="utf-8"),
    ]
    if any("Lambert_Azimuthal_Equal_Area" not in text for text in crs_texts):
        raise GenerationError("Source datasets are not in ETRS89 / LAEA Europe")
    if crs_texts[0] != crs_texts[1]:
        raise GenerationError("Country and commune datasets use different CRS definitions")

    x_min, y_min, x_max, y_max = declared_extent
    metres_per_pixel = (
        (x_max - x_min) / TARGET_SIZE[0],
        (y_max - y_min) / TARGET_SIZE[1],
    )
    if abs(metres_per_pixel[0] - metres_per_pixel[1]) > 0.2:
        raise GenerationError("Target raster does not preserve the projected-map aspect ratio")

    return {
        "crs": "ETRS89 / LAEA Europe (EPSG:3035)",
        "extent_metres": {
            "x_min": x_min,
            "y_min": y_min,
            "x_max": x_max,
            "y_max": y_max,
        },
        "reference_raster_size": {"width": reference_size[0], "height": reference_size[1]},
        "target_raster_size": {"width": TARGET_SIZE[0], "height": TARGET_SIZE[1]},
        "target_metres_per_pixel": {
            "x": metres_per_pixel[0],
            "y": metres_per_pixel[1],
        },
        "world_file_extent_error_metres": max_extent_error,
        "source_files": {label: str(path) for label, path in required.items()},
    }


def _remove_tiny_lakes(tile_map: np.ndarray, min_pixels: int) -> int:
    """Return physically tiny inland-water features to land before province import."""
    lake_mask = tile_map == TILE_LAKE
    labels, _ = ndimage.label(
        lake_mask,
        structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool),
    )
    sizes = np.bincount(labels.ravel())
    too_small = sizes < int(min_pixels)
    too_small[0] = False
    removal_mask = too_small[labels]
    removed = int(removal_mask.sum())
    tile_map[removal_mask] = TILE_LAND
    return removed


def _repair_mixed_surface_crossings(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    reason_ids: dict[str, set[int]],
) -> int:
    """Resolve rare X-crossings where matching surface types touch only diagonally.

    Province IDs cannot cross land/sea/lake types.  If an X-crossing has no
    orthogonally adjacent same-type corner, preserve the rarer source surface
    and change one immediately adjacent, more common surface pixel to it.  A
    single-pixel adjustment is preferable to emitting an HOI4-invalid border
    topology, and the normal repair pass immediately cleans up any affected
    small or disconnected province.
    """
    from domain.validators.province import detect_x_crossings

    positions = detect_x_crossings(province_map)
    if not positions:
        return 0
    surface_sizes = {
        surface: int((tile_map == surface).sum())
        for surface in (TILE_LAND, TILE_SEA, TILE_LAKE)
    }
    height, width = province_map.shape
    changed = 0
    for y, x in positions:
        right = 0 if x == width - 1 else x + 1
        corners = ((y, x), (y, right), (y + 1, x), (y + 1, right))
        values = [int(province_map[py, px]) for py, px in corners]
        if len(set(values)) != 4:
            continue
        candidates: list[tuple[tuple[int, int, int, int], int, int]] = []
        for destination, (dy, dx) in enumerate(corners):
            for source, (sy, sx) in enumerate(corners):
                if destination == source or abs(dy - sy) + abs(dx - sx) != 1:
                    continue
                source_surface = int(tile_map[sy, sx])
                destination_surface = int(tile_map[dy, dx])
                if source_surface == destination_surface:
                    continue
                # Preserve small lake/sea features before the much larger
                # land surface, then prefer the smallest coordinate change.
                score = (
                    surface_sizes[source_surface],
                    -surface_sizes[destination_surface],
                    destination,
                    source,
                )
                candidates.append((score, destination, source))
        if not candidates:
            continue
        _, destination, source = min(candidates)
        dy, dx = corners[destination]
        sy, sx = corners[source]
        old_pid = int(province_map[dy, dx])
        new_pid = int(province_map[sy, sx])
        tile_map[dy, dx] = tile_map[sy, sx]
        province_map[dy, dx] = new_pid
        reason_ids["border_adjusted"].update((old_pid, new_pid))
        changed += 1
    return changed


def _synchronise_river_background(tile_map: np.ndarray, river_map: np.ndarray) -> None:
    """Keep river backgrounds valid if province repair adjusts a water edge."""
    river_features = np.isin(river_map, list(VALID_RIVER_VALUES))
    river_map[~river_features] = RIVER_BG_LAND
    river_map[(tile_map == TILE_SEA) | (tile_map == TILE_LAKE)] = RIVER_BG_SEA


def _fill_unassigned_surface_pixels(tile_map: np.ndarray, province_map: np.ndarray) -> int:
    """Absorb rare cleared fragments into a touching province of the same type."""
    height, width = province_map.shape
    filled = 0
    structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
    for surface in (TILE_LAND, TILE_SEA, TILE_LAKE):
        unassigned = (tile_map == surface) & (province_map == 0)
        labels, count = ndimage.label(unassigned, structure=structure)
        for component_id in range(1, count + 1):
            ys, xs = np.where(labels == component_id)
            contacts: dict[int, int] = {}
            fallback_contacts: dict[tuple[int, int], int] = {}
            for delta_y, delta_x in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                neighbor_y = ys + delta_y
                valid_y = (neighbor_y >= 0) & (neighbor_y < height)
                if not np.any(valid_y):
                    continue
                neighbor_x = (xs + delta_x) % width
                neighbor_ids = province_map[neighbor_y[valid_y], neighbor_x[valid_y]]
                neighbor_surfaces = tile_map[neighbor_y[valid_y], neighbor_x[valid_y]]
                for province_id, neighbor_surface in zip(neighbor_ids, neighbor_surfaces):
                    if province_id > 0:
                        pid = int(province_id)
                        surface_id = int(neighbor_surface)
                        fallback_key = (surface_id, pid)
                        fallback_contacts[fallback_key] = (
                            fallback_contacts.get(fallback_key, 0) + 1
                        )
                        if surface_id == surface:
                            contacts[pid] = contacts.get(pid, 0) + 1
            if not contacts:
                # This is necessarily a tiny isolated component: it was
                # cleared by the <50px repair.  Convert it to the most
                # strongly touching surface rather than preserving a type-
                # crossing or an unassigned hole.
                if not fallback_contacts:
                    raise GenerationError("A cleared fragment has no neighbouring province")
                target_surface, target = max(
                    fallback_contacts,
                    key=lambda key: (fallback_contacts[key], -key[0], -key[1]),
                )
                tile_map[ys, xs] = target_surface
            else:
                target = max(contacts, key=lambda pid: (contacts[pid], -pid))
            province_map[ys, xs] = target
            filled += len(ys)
    return filled


def _repair_all_x_crossings(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    reason_ids: dict[str, set[int]],
) -> int:
    """Iterate local X repairs until nearby edge edits no longer create one."""
    repaired = 0
    for _ in range(24):
        changed = _repair_x_crossings(tile_map, province_map, reason_ids)
        changed += _repair_mixed_surface_crossings(tile_map, province_map, reason_ids)
        repaired += changed
        if not changed:
            break
    return repaired


def build_tiles_and_rivers(
    state_rgb: np.ndarray,
    inland_water_rgb: np.ndarray,
    river_rgb: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Generate land, sea, filtered lake tiles, and valid blue-source rivers."""
    tile_map = generate_land_water_from_rgb(
        state_rgb,
        land_colors=[STATE_LAND_COLOR],
        sea_colors=[SEA_COLOR],
        color_tolerance=28,
    )
    interior_sea_pixels = auto_classify_water(tile_map)
    tile_map, _water_rivers, lake_stats = generate_hydrology_from_rgb(
        inland_water_rgb,
        tile_map,
        min_feature_pixels=4,
        lake_radius=3.0,
    )
    tiny_lake_pixels = _remove_tiny_lakes(tile_map, MIN_PROVINCE_PIXELS)

    # The blue rendition is used only for river paths.  Passing no lake
    # colours prevents broad rivers being promoted to lake tiles.
    _ignored_tiles, river_map, river_stats = generate_hydrology_from_rgb(
        river_rgb,
        tile_map,
        min_feature_pixels=750,
        lake_radius=2.0,
        lake_colors=[],
        river_colors=list(RIVER_COLORS),
        color_tolerance=28,
    )
    river_map[(tile_map == TILE_SEA) | (tile_map == TILE_LAKE)] = RIVER_BG_SEA

    return tile_map, river_map, {
        "interior_sea_converted_to_lake_pixels": int(interior_sea_pixels),
        "inland_water_import": lake_stats,
        "tiny_lake_pixels_returned_to_land": tiny_lake_pixels,
        "river_import": river_stats,
    }


def _repair_provinces(
    tile_map: np.ndarray, province_map: np.ndarray
) -> tuple[np.ndarray, dict[str, Any]]:
    """Run the non-destructive reference-import repairs with bounded memory use."""
    before = validate_provinces(tile_map, province_map, min_pixels=MIN_PROVINCE_PIXELS)
    if before["too_large"]:
        raise GenerationError("Source province import contains oversized provinces")

    reason_ids = {
        "border_adjusted": set(),
        "too_small_merged": set(),
        "too_small_removed": set(),
        "not_contiguous": set(),
        "too_large_split": set(),
    }
    repaired = province_map.copy()
    for _ in range(4):
        changes = 0
        changes += _repair_all_x_crossings(tile_map, repaired, reason_ids)
        changes += _repair_disconnected_provinces(tile_map, repaired, reason_ids)
        changes += _merge_small_provinces(
            tile_map, repaired, reason_ids, MIN_PROVINCE_PIXELS
        )
        changes += _remove_unrepairable_small_provinces(
            tile_map, repaired, reason_ids, MIN_PROVINCE_PIXELS
        )
        changes += _fill_unassigned_surface_pixels(tile_map, repaired)
        if not changes:
            break
    # Surface-aware X fixes can remove a narrow bridge from the province that
    # lost a pixel.  Alternate once more between the two local repairs so the
    # final map has neither crossing nor a detached remnant.
    for _ in range(4):
        changes = _repair_all_x_crossings(tile_map, repaired, reason_ids)
        changes += _repair_disconnected_provinces(tile_map, repaired, reason_ids)
        changes += _merge_small_provinces(
            tile_map, repaired, reason_ids, MIN_PROVINCE_PIXELS
        )
        changes += _remove_unrepairable_small_provinces(
            tile_map, repaired, reason_ids, MIN_PROVINCE_PIXELS
        )
        changes += _fill_unassigned_surface_pixels(tile_map, repaired)
        if not changes:
            break
    compacted_gaps = compact_province_ids(repaired)
    after = validate_provinces(tile_map, repaired, min_pixels=MIN_PROVINCE_PIXELS)

    hard_issue_keys = ("x_crossings", "too_small", "not_contiguous", "too_large")
    unresolved = {key: int(after[key]) for key in hard_issue_keys if after[key]}
    if after["id_gaps"]:
        unresolved["id_gaps"] = len(after["id_gaps"])
    if unresolved:
        raise GenerationError(f"Province validation did not converge: {unresolved}")
    if np.any((tile_map > 0) & (repaired == 0)):
        raise GenerationError("Province repair left valid surface pixels unassigned")

    return repaired, {
        "before": _compact_validation(before),
        "after": _compact_validation(after),
        "repair_counts": {key: len(value) for key, value in reason_ids.items()},
        "compacted_province_count": int(compacted_gaps),
    }


def _compact_validation(result: dict[str, Any]) -> dict[str, Any]:
    """Store validation information without writing thousands of province IDs."""
    return {
        "x_crossings": int(result["x_crossings"]),
        "too_small": int(result["too_small"]),
        "not_contiguous": int(result["not_contiguous"]),
        "too_large": int(result["too_large"]),
        "id_gap_count": len(result["id_gaps"]),
        "total_provinces": int(result["total_provinces"]),
        # This is a useful export metadata count, not an error: the exporter
        # marks these land provinces coastal in definition.csv.
        "coastal_land_provinces": int(result["coastal_mismatch"]),
    }


def build_provinces(
    state_rgb: np.ndarray, tile_map: np.ndarray
) -> tuple[np.ndarray, dict[str, Any]]:
    """Import state/commune outlines for land and generate the open-sea cells."""
    province_map, imported_count = generate_provinces_from_rgb(
        state_rgb,
        tile_map,
        min_region_pixels=MIN_PROVINCE_PIXELS,
    )
    np.random.seed(42)
    province_map, sea_count = generate_provinces_for_type(
        tile_map,
        province_map,
        TILE_SEA,
        target_count=160,
    )
    province_map, repair_report = _repair_provinces(tile_map, province_map)
    return province_map, {
        "state_outline_import_count": int(imported_count),
        "generated_open_sea_count": int(sea_count),
        "repair": repair_report,
    }


def _gaussian(
    x: np.ndarray,
    y: np.ndarray,
    center_x: float,
    center_y: float,
    radius_x: float,
    radius_y: float,
    amplitude: float,
) -> np.ndarray:
    return amplitude * np.exp(
        -0.5
        * (((x - center_x) / radius_x) ** 2 + ((y - center_y) / radius_y) ** 2)
    )


def build_terrain_and_height(
    tile_map: np.ndarray, satellite_rgb: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Use the aligned satellite image plus regional relief to build terrain/height."""
    height, width = tile_map.shape
    if satellite_rgb.shape[:2] != (height, width):
        raise GenerationError("Satellite base map is not aligned with the QGIS raster")

    # Smooth satellite colours into land-cover-scale values rather than using
    # individual roads, fields, or roof pixels as terrain decisions.
    smoothed = cv2.GaussianBlur(satellite_rgb, (0, 0), sigmaX=12, sigmaY=12)
    source = smoothed.astype(np.float32)
    red, green, blue = source[:, :, 0], source[:, :, 1], source[:, :, 2]
    brightness = (red + green + blue) / 3.0
    vegetation = green - (0.55 * red + 0.45 * blue)

    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = xx / max(width - 1, 1)
    ny = yy / max(height - 1, 1)

    # A gently rising base plus broad Ardennes/Eifel uplands.  These masks are
    # deliberately broad so the imagery controls texture while the known
    # regional relief controls the elevation hierarchy.
    relief = 4.0 + 5.0 * ny + 2.0 * nx
    relief += _gaussian(nx, ny, 0.57, 0.70, 0.11, 0.14, 32.0)  # Ardennes
    relief += _gaussian(nx, ny, 0.82, 0.75, 0.08, 0.14, 75.0)  # Eifel / east
    relief += _gaussian(nx, ny, 0.33, 0.84, 0.15, 0.12, 10.0)  # French uplands
    relief += np.clip(vegetation, 0.0, 35.0) * 0.06
    relief = cv2.GaussianBlur(relief, (0, 0), sigmaX=18, sigmaY=18)

    height_map = np.full((height, width), SEA_LEVEL, dtype=np.float32)
    land = tile_map == TILE_LAND
    sea = tile_map == TILE_SEA
    lakes = tile_map == TILE_LAKE
    height_map[land] = 96.0 + relief[land]
    sea_distance = ndimage.distance_transform_edt(sea)
    height_map[sea] = np.maximum(40.0, SEA_LEVEL - 1.0 - sea_distance[sea] * 0.22)
    height_map[lakes] = SEA_LEVEL - 5.0
    height_map = np.clip(height_map, 30, 220).astype(np.uint8)

    terrain_map = np.full((height, width), TERRAIN_PALETTE_INDEX["plains"], dtype=np.uint8)
    terrain_map[sea] = TERRAIN_PALETTE_INDEX["ocean"]
    terrain_map[lakes] = TERRAIN_PALETTE_INDEX["lakes"]

    forest = land & (vegetation > 22.0) & (brightness < 95.0)
    hills = land & (height_map >= 130)
    mountains = land & (height_map >= 172)
    terrain_map[forest] = TERRAIN_PALETTE_INDEX["forest"]
    terrain_map[hills] = TERRAIN_PALETTE_INDEX["hills"]
    terrain_map[mountains] = TERRAIN_PALETTE_INDEX["mountain"]
    return terrain_map, height_map


def _province_type_summary(tile_map: np.ndarray, province_map: np.ndarray) -> dict[str, int]:
    max_id = int(province_map.max())
    totals = np.bincount(province_map.ravel(), minlength=max_id + 1)
    result: dict[str, int] = {}
    type_names = (("land", TILE_LAND), ("sea", TILE_SEA), ("lake", TILE_LAKE))
    assigned_by_type = np.zeros((3, max_id + 1), dtype=np.int64)
    for index, (name, tile_type) in enumerate(type_names):
        assigned_by_type[index] = np.bincount(
            province_map.ravel(),
            weights=(tile_map.ravel() == tile_type),
            minlength=max_id + 1,
        ).astype(np.int64)
        result[name] = int(np.count_nonzero(assigned_by_type[index][1:]))
    mixed = np.sum(assigned_by_type > 0, axis=0) > 1
    if np.any(mixed[1:]):
        raise GenerationError("At least one province contains more than one surface type")
    if np.any(totals[1:] == 0):
        raise GenerationError("Province IDs are not contiguous after repair")
    return result


def validate_layers(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    terrain_map: np.ndarray,
    height_map: np.ndarray,
    river_map: np.ndarray,
) -> dict[str, Any]:
    """Run final layer contracts that must hold before saving a project."""
    shapes = {
        tile_map.shape,
        province_map.shape,
        terrain_map.shape,
        height_map.shape,
        river_map.shape,
    }
    if shapes != {(TARGET_SIZE[1], TARGET_SIZE[0])}:
        raise GenerationError(f"Layer dimensions do not match {TARGET_SIZE}: {shapes}")
    if np.any((tile_map > 0) & (province_map == 0)):
        raise GenerationError("A valid surface pixel has no province")

    land = tile_map == TILE_LAND
    sea = tile_map == TILE_SEA
    lakes = tile_map == TILE_LAKE
    ocean_index = TERRAIN_PALETTE_INDEX["ocean"]
    lake_index = TERRAIN_PALETTE_INDEX["lakes"]
    if np.any(terrain_map[sea] != ocean_index) or np.any(terrain_map[lakes] != lake_index):
        raise GenerationError("Water terrain does not match the generated surface layer")
    if np.any(np.isin(terrain_map[land], (ocean_index, lake_index))):
        raise GenerationError("Land terrain contains a water terrain index")
    if np.any(height_map[land] <= SEA_LEVEL):
        raise GenerationError("Land height must be above sea level")
    if np.any(height_map[sea] >= SEA_LEVEL) or np.any(height_map[lakes] >= SEA_LEVEL):
        raise GenerationError("Sea and lake heights must remain below sea level")

    river_messages = validate_rivers(river_map, lang="en")
    river_valid = len(river_messages) == 1 and "passed" in river_messages[0].lower()
    if not river_valid:
        raise GenerationError(f"River validation failed: {river_messages[:5]}")
    river_pixels = int(np.isin(river_map, list(VALID_RIVER_VALUES)).sum())

    final_province_validation = validate_provinces(
        tile_map, province_map, min_pixels=MIN_PROVINCE_PIXELS
    )
    hard_province_issues = {
        key: int(final_province_validation[key])
        for key in ("x_crossings", "too_small", "not_contiguous", "too_large")
        if final_province_validation[key]
    }
    if final_province_validation["id_gaps"]:
        hard_province_issues["id_gaps"] = len(final_province_validation["id_gaps"])
    if hard_province_issues:
        raise GenerationError(f"Final province validation failed: {hard_province_issues}")

    return {
        "province_types": _province_type_summary(tile_map, province_map),
        "province_validation": _compact_validation(final_province_validation),
        "river_validation": {
            "passed": river_valid,
            "river_pixels": river_pixels,
            "messages": river_messages,
        },
        "terrain_pixel_counts": {
            name: int((terrain_map == TERRAIN_PALETTE_INDEX[name]).sum())
            for name in ("plains", "forest", "hills", "mountain", "ocean", "lakes")
        },
        "height_ranges": {
            "land": [int(height_map[land].min()), int(height_map[land].max())],
            "sea": [int(height_map[sea].min()), int(height_map[sea].max())],
            "lake": [int(height_map[lakes].min()), int(height_map[lakes].max())],
        },
    }


def _terrain_preview(terrain_map: np.ndarray) -> np.ndarray:
    palette = np.zeros((256, 3), dtype=np.uint8)
    for terrain in TERRAIN_TYPES.values():
        palette[TERRAIN_PALETTE_INDEX[terrain.name]] = terrain.color
    return palette[terrain_map]


def _tile_preview(tile_map: np.ndarray) -> np.ndarray:
    palette = np.array(
        [(0, 0, 0), (101, 151, 72), (47, 93, 165), (82, 157, 189)], dtype=np.uint8
    )
    return palette[tile_map]


def _province_preview(province_map: np.ndarray) -> np.ndarray:
    colours = generate_province_colors(int(province_map.max()))
    lookup = np.zeros((int(province_map.max()) + 1, 3), dtype=np.uint8)
    for province_id, colour in colours.items():
        lookup[province_id] = colour
    return lookup[province_map]


def write_preview(
    output_path: Path,
    tile_map: np.ndarray,
    province_map: np.ndarray,
    terrain_map: np.ndarray,
    height_map: np.ndarray,
    river_map: np.ndarray,
) -> None:
    """Save a compact 2x2 visual inspection sheet alongside the project."""
    size = (1408, 512)
    terrain = _terrain_preview(terrain_map)
    river_mask = np.isin(river_map, list(VALID_RIVER_VALUES))
    terrain[river_mask] = (20, 165, 225)
    panels = (_tile_preview(tile_map), _province_preview(province_map), terrain)
    resized = [Image.fromarray(panel).resize(size, Image.Resampling.NEAREST) for panel in panels]
    height = Image.fromarray(height_map).resize(size, Image.Resampling.BILINEAR).convert("RGB")
    canvas = Image.new("RGB", (size[0] * 2, size[1] * 2), "black")
    canvas.paste(resized[0], (0, 0))
    canvas.paste(resized[1], (size[0], 0))
    canvas.paste(resized[2], (0, size[1]))
    canvas.paste(height, (size[0], size[1]))
    canvas.save(output_path, optimize=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_readme(output_dir: Path, project_path: Path) -> None:
    (output_dir / "README.md").write_text(
        "# Belgium Map v1.1\n\n"
        f"Open `{project_path.name}` in HOI4 Map Maker.\n\n"
        "The project contains validated geographic layers only: land, sea, lakes, "
        "provinces, rivers, terrain, and heightmap. Political state/country ownership "
        "is deliberately left for later authoring. See `validation.json` for exact "
        "source provenance, spatial-reference checks, and validation results.\n",
        encoding="utf-8",
    )


def create_project(source_dir: Path, output_dir: Path, overwrite: bool) -> Path:
    qgis_dir = source_dir / "base map" / "qgis" / "EU data"
    project_path = output_dir / f"{PROJECT_NAME}.hoi4proj"
    if project_path.exists() and not overwrite:
        raise GenerationError(
            f"Project already exists: {project_path}. Re-run with --overwrite to replace it."
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    spatial_reference = validate_source_layout(source_dir)
    state_rgb = _load_rgb(qgis_dir / "Print_states.png")
    inland_water_rgb = _load_rgb(qgis_dir / "Print_inland-water.png")
    river_rgb = _load_rgb(qgis_dir / "Print_inland-water-rivers.png")
    satellite_rgb = _load_rgb(source_dir / "base map.png")

    tile_map, river_map, hydrology_report = build_tiles_and_rivers(
        state_rgb, inland_water_rgb, river_rgb
    )
    province_map, province_report = build_provinces(state_rgb, tile_map)
    _synchronise_river_background(tile_map, river_map)
    terrain_map, height_map = build_terrain_and_height(tile_map, satellite_rgb)
    layer_validation = validate_layers(
        tile_map, province_map, terrain_map, height_map, river_map
    )
    provincial_terrain = compute_provincial_terrain_from_bmp(
        terrain_map, province_map, tile_map
    )

    state_manager = StateManager()
    country_manager = CountryManager()
    continent_manager = ContinentManager()
    continent_manager.rename_continent(0, "Europe")
    save_project(
        str(project_path),
        tile_map=tile_map,
        province_map=province_map,
        terrain_map=terrain_map,
        height_map=height_map,
        state_mgr=state_manager,
        country_mgr=country_manager,
        river_map=river_map,
        continent_mgr=continent_manager,
        provincial_terrain=provincial_terrain,
        tile_snapshot=tile_map.copy(),
    )
    preview_path = output_dir / f"{PROJECT_NAME}_preview.png"
    write_preview(preview_path, tile_map, province_map, terrain_map, height_map, river_map)
    _write_readme(output_dir, project_path)

    report = {
        "project": {
            "name": "Belgium Map v1.1",
            "file": project_path.name,
            "sha256": _sha256(project_path),
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Validated geographic layers; political ownership intentionally omitted.",
        },
        "spatial_reference": spatial_reference,
        "hydrology": hydrology_report,
        "provinces": province_report,
        "validation": layer_validation,
        "provincial_terrain_entries": len(provincial_terrain),
    }
    (output_dir / "validation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return project_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory containing the Belgium source-map folder",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory that receives the project and validation artefacts",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing project with the same name",
    )
    args = parser.parse_args()
    try:
        project_path = create_project(args.source_dir, args.output_dir, args.overwrite)
    except GenerationError as exc:
        print(f"Generation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Created validated project: {project_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
