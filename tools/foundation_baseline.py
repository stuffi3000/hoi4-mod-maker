"""Metadata-only foundation baseline capture helpers.

The helpers in this module deliberately read project/game files without copying
their binary contents.  They are used by the opt-in baseline capture command
and by the regression tests for the committed Belgium evidence fixture.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import numpy as np

from data.constants import TILE_TYPE_NAMES
from domain.managers.adjacency import AdjacencyManager
from domain.managers.adjacency_rule import AdjacencyRuleManager
from domain.managers.continent import ContinentManager
from domain.managers.country import CountryManager
from domain.managers.railway import RailwayManager
from domain.managers.state import StateManager
from domain.managers.strategic_region import StrategicRegionManager
from domain.managers.supply_node import SupplyNodeManager
from domain.project_io import load_project


DEFAULT_GAME_HEADER_PATHS = (
    "map/provinces.bmp",
    "map/terrain.bmp",
    "map/heightmap.bmp",
    "map/rivers.bmp",
    "map/trees.bmp",
    "map/world_normal.bmp",
    "map/cities.bmp",
    "map/terrain/colormap_water_0.dds",
    "map/terrain/colormap_water_1.dds",
    "map/terrain/colormap_water_2.dds",
    "map/terrain/fow_rgb_waterspec_a.dds",
)

_BMP_COMPRESSION_NAMES = {
    0: "BI_RGB",
    1: "BI_RLE8",
    2: "BI_RLE4",
    3: "BI_BITFIELDS",
    6: "BI_ALPHABITFIELDS",
}


def _new_managers() -> dict[str, Any]:
    """Create the managers needed to load a project without UI state."""

    return {
        "state": StateManager(),
        "country": CountryManager(),
        "continent": ContinentManager(),
        "adjacency": AdjacencyManager(),
        "railway": RailwayManager(),
        "supply": SupplyNodeManager(),
        "adjacency_rule": AdjacencyRuleManager(),
        "strategic_region": StrategicRegionManager(),
    }


def load_project_context(project_path: str | Path) -> dict[str, Any]:
    """Load a project into plain arrays/managers for metadata capture."""

    managers = _new_managers()
    (
        tile_map,
        province_map,
        terrain_map,
        height_map,
        river_map,
        provincial_terrain,
        tile_snapshot,
    ) = load_project(
        str(project_path),
        managers["state"],
        managers["country"],
        continent_mgr=managers["continent"],
        adjacency_mgr=managers["adjacency"],
        railway_mgr=managers["railway"],
        supply_mgr=managers["supply"],
        adjacency_rule_mgr=managers["adjacency_rule"],
        strategic_region_mgr=managers["strategic_region"],
    )
    return {
        "project_path": Path(project_path),
        "tile_map": tile_map,
        "province_map": province_map,
        "terrain_map": terrain_map,
        "height_map": height_map,
        "river_map": river_map,
        "provincial_terrain": provincial_terrain,
        "tile_snapshot": tile_snapshot,
        "managers": managers,
    }


def _province_type_counts(
    province_map: np.ndarray,
    tile_map: np.ndarray,
) -> tuple[dict[str, int], int]:
    """Return majority type counts and the number of mixed-type provinces."""

    max_pid = int(province_map.max())
    flat_provinces = province_map.ravel()
    flat_tiles = tile_map.ravel()
    tile_values = tuple(sorted(TILE_TYPE_NAMES))
    type_counts = np.stack(
        [
            np.bincount(
                flat_provinces,
                weights=(flat_tiles == tile_value),
                minlength=max_pid + 1,
            )
            for tile_value in tile_values
        ]
    )
    present = np.bincount(flat_provinces, minlength=max_pid + 1) > 0
    majority = np.argmax(type_counts, axis=0)
    result = {
        TILE_TYPE_NAMES[tile_value]: int(
            np.count_nonzero(majority[1:][present[1:]] == index)
        )
        for index, tile_value in enumerate(tile_values)
    }
    mixed = int(
        np.count_nonzero((type_counts[:, 1:] > 0).sum(axis=0) > 1)
    )
    return result, mixed


def project_summary(context: dict[str, Any]) -> dict[str, Any]:
    """Create deterministic, binary-free summary data for a loaded project."""

    tile_map = context["tile_map"]
    province_map = context["province_map"]
    managers = context["managers"]
    type_counts, mixed_count = _province_type_counts(province_map, tile_map)

    province_ids = np.unique(province_map[province_map > 0])
    tile_values, tile_counts = np.unique(tile_map, return_counts=True)
    pixel_counts = {
        TILE_TYPE_NAMES.get(int(value), f"unknown_{int(value)}"): int(count)
        for value, count in zip(tile_values, tile_counts)
    }
    state_province_ids = {
        int(pid)
        for state in managers["state"].states.values()
        for pid in state.provinces
    }
    strategic_regions = managers["strategic_region"].regions
    strategic_region_province_ids = {
        int(pid)
        for region in strategic_regions.values()
        for pid in region.province_ids
    }

    river_map = context["river_map"]
    return {
        "dimensions": {
            "width": int(province_map.shape[1]),
            "height": int(province_map.shape[0]),
        },
        "province_ids": {
            "min": int(province_ids.min()) if province_ids.size else 0,
            "max": int(province_ids.max()) if province_ids.size else 0,
            "count": int(province_ids.size),
        },
        "pixels": {
            "surface_type_counts": pixel_counts,
            "river_non_background": (
                int(np.count_nonzero(river_map != 255))
                if river_map is not None
                else None
            ),
        },
        "province_types": {
            "majority_counts": type_counts,
            "mixed_type_count": mixed_count,
        },
        "coverage": {
            "states": len(managers["state"].states),
            "state_provinces": len(state_province_ids),
            "countries": len(managers["country"].countries),
            "continents": len(managers["continent"]._names),
            "strategic_regions": len(strategic_regions),
            "strategic_region_provinces": len(strategic_region_province_ids),
        },
        "graphs": {
            "special_adjacencies": len(managers["adjacency"]._entries),
            "adjacency_rules": len(managers["adjacency_rule"]._rules),
            "railway_entries": len(managers["railway"]._entries),
            "supply_nodes": len(managers["supply"]._nodes),
        },
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_signature(paths: list[str] | tuple[str, ...]) -> str:
    """Hash a sorted relative-path inventory, not file contents."""

    normalized = "\n".join(sorted(path.replace("\\", "/") for path in paths))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _display_source(path: Path) -> str:
    """Keep committed reports portable when a source is inside the repo."""

    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_output_inventory(source: str | Path) -> dict[str, Any]:
    """Read an existing hash manifest or enumerate a generated output tree."""

    source_path = Path(source)
    if source_path.is_file():
        with source_path.open("r", encoding="utf-8") as file:
            raw_values = json.load(file)
        if not isinstance(raw_values, dict):
            raise ValueError(f"Inventory manifest must be a JSON object: {source_path}")
        values = {
            str(path).replace("\\", "/"): value
            for path, value in raw_values.items()
        }
        paths = sorted(str(path).replace("\\", "/") for path in values)
        return {
            "source": _display_source(source_path),
            "source_kind": "hash_manifest",
            "file_count": len(paths),
            "path_sha256": inventory_signature(paths),
            "selected_file_hashes": {
                path: values[path]
                for path in (
                    "map/provinces.bmp",
                    "map/terrain.bmp",
                    "map/heightmap.bmp",
                    "map/rivers.bmp",
                    "map/trees.bmp",
                    "map/definition.csv",
                    "map/default.map",
                    "map/adjacencies.csv",
                    "map/positions.txt",
                    "map/buildings.txt",
                    "map/supply_nodes.txt",
                    "map/railways.txt",
                    "map/continent.txt",
                )
                if path in values
            },
        }

    if not source_path.is_dir():
        raise FileNotFoundError(f"Output inventory source does not exist: {source_path}")
    paths = sorted(
        path.relative_to(source_path).as_posix()
        for path in source_path.rglob("*")
        if path.is_file()
    )
    return {
        "source": _display_source(source_path),
        "source_kind": "output_directory",
        "file_count": len(paths),
        "path_sha256": inventory_signature(paths),
        "selected_file_hashes": {
            path: _sha256_file(source_path / path)
            for path in paths
            if path in {
                "map/provinces.bmp",
                "map/terrain.bmp",
                "map/heightmap.bmp",
                "map/rivers.bmp",
                "map/trees.bmp",
                "map/definition.csv",
                "map/default.map",
                "map/adjacencies.csv",
                "map/positions.txt",
                "map/buildings.txt",
                "map/supply_nodes.txt",
                "map/railways.txt",
                "map/continent.txt",
            }
        },
    }


def parse_bmp_header(path: str | Path) -> dict[str, Any]:
    """Read BMP header metadata without retaining pixel data."""

    file_path = Path(path)
    with file_path.open("rb") as file:
        header = file.read(54)
    if len(header) < 54 or header[:2] != b"BM":
        raise ValueError(f"Not a BMP file: {file_path}")
    compression = struct.unpack_from("<I", header, 30)[0]
    return {
        "format": "BMP",
        "width": struct.unpack_from("<i", header, 18)[0],
        "height": struct.unpack_from("<i", header, 22)[0],
        "bits_per_pixel": struct.unpack_from("<H", header, 28)[0],
        "compression": _BMP_COMPRESSION_NAMES.get(
            compression, f"unknown_{compression}"
        ),
        "pixel_offset": struct.unpack_from("<I", header, 10)[0],
        "colors_used": struct.unpack_from("<I", header, 46)[0],
        "sha256": _sha256_file(file_path),
        "file_size": file_path.stat().st_size,
    }


def parse_dds_header(path: str | Path) -> dict[str, Any]:
    """Read DDS dimensions/format/mip metadata without retaining texture data."""

    file_path = Path(path)
    with file_path.open("rb") as file:
        header = file.read(148)
    if len(header) < 128 or header[:4] != b"DDS ":
        raise ValueError(f"Not a DDS file: {file_path}")
    four_cc = header[84:88].rstrip(b"\0").decode("ascii", errors="replace")
    return {
        "format": "DDS",
        "width": struct.unpack_from("<I", header, 16)[0],
        "height": struct.unpack_from("<I", header, 12)[0],
        "mip_count": struct.unpack_from("<I", header, 28)[0] or 1,
        "pixel_format_flags": struct.unpack_from("<I", header, 80)[0],
        "four_cc": four_cc,
        "rgb_bits": struct.unpack_from("<I", header, 88)[0],
        "has_dx10_header": four_cc == "DX10",
        "sha256": _sha256_file(file_path),
        "file_size": file_path.stat().st_size,
    }


def game_profile_metadata(
    game_install: str | Path,
    relative_paths: tuple[str, ...] = DEFAULT_GAME_HEADER_PATHS,
) -> dict[str, Any]:
    """Capture version, hashes, and headers from a user-selected install."""

    root = Path(game_install)
    if not root.is_dir():
        raise FileNotFoundError(f"Game install does not exist: {root}")

    raw_version = None
    version_file = root / "launcher-settings.json"
    if version_file.is_file():
        try:
            with version_file.open("r", encoding="utf-8") as file:
                raw_version = json.load(file).get("rawVersion")
        except (OSError, ValueError, TypeError):
            raw_version = None

    headers: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for relative_path in relative_paths:
        path = root / relative_path
        if not path.is_file():
            missing.append(relative_path)
            continue
        if path.suffix.lower() == ".bmp":
            headers[relative_path] = parse_bmp_header(path)
        elif path.suffix.lower() == ".dds":
            headers[relative_path] = parse_dds_header(path)
        else:
            headers[relative_path] = {
                "sha256": _sha256_file(path),
                "file_size": path.stat().st_size,
            }
    return {
        "profile_id": "hoi4-1.19",
        "raw_version": raw_version,
        "source_kind": "user_selected_install",
        "files": headers,
        "missing_files": missing,
    }


def capture_summary(
    project_path: str | Path,
    *,
    inventory_source: str | Path | None = None,
    game_install: str | Path | None = None,
) -> dict[str, Any]:
    """Capture a complete metadata-only report for a project and optional sources."""

    context = load_project_context(project_path)
    result: dict[str, Any] = {
        "schema_version": 1,
        "fixture_kind": "metadata_only",
        "project": project_summary(context),
    }
    if inventory_source is not None:
        result["output_inventory"] = read_output_inventory(inventory_source)
    else:
        result["output_inventory"] = {
            "status": "not_captured",
            "reason": "No generated artifact or hash manifest was supplied",
        }
    if game_install is not None:
        result["game_profile"] = game_profile_metadata(game_install)
    else:
        result["game_profile"] = {
            "status": "not_captured",
            "reason": "No user-selected game installation was supplied",
        }
    return result


def compare_baseline(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Return stable, human-readable differences for baseline comparison."""

    differences: list[str] = []
    for section in ("project", "output_inventory", "game_profile"):
        if section not in expected:
            continue
        expected_section = expected.get(section)
        actual_section = actual.get(section)
        if section == "output_inventory":
            # A committed fixture records evidence from one capture, while a
            # comparison normally reads a different explicit output path.
            # Compare artifact facts, not the path or capture source label.
            expected_section = {
                key: value
                for key, value in (expected_section or {}).items()
                if key not in {"source", "source_kind"}
            }
            actual_section = {
                key: value
                for key, value in (actual_section or {}).items()
                if key not in {"source", "source_kind"}
            }
        if expected_section != actual_section:
            differences.append(f"{section} changed")
    return differences
