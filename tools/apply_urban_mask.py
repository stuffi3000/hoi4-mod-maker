"""Paint urban graphical terrain from a grayscale reference raster.

The reference raster is a full-map QGIS export.  Its urban areas are the dark
grayscale pixels while the nearly-white pixels are background/antialiasing.
Only the project's graphical terrain layer is changed; province-level combat
terrain metadata remains independent and is deliberately preserved.

Usage::

    .\\.venv\\Scripts\\python.exe tools\\apply_urban_mask.py

The project is backed up beside the original archive before the replacement is
made.  ``--dry-run`` performs the same checks without writing anything.
"""

from __future__ import annotations

import argparse
import copy
import io
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = ROOT / "projects" / "Belgium_Map_v1_1.hoi4proj"
DEFAULT_REFERENCE = Path(
    r"C:\Users\stuff\Documents\HOI4\Belgium\base map\qgis\EU data\Print_urban.png"
)

TILE_LAND = 1
TILE_SEA = 2
TILE_LAKE = 3
URBAN_INDEX = 13
OCEAN_INDEX = 15
LAKES_INDEX = 14
URBAN_GRAYSCALE_CUTOFF = 200


class UrbanMaskError(RuntimeError):
    """Raised when the source or project cannot be safely updated."""


def _read_archive(path: Path) -> tuple[dict[str, bytes], dict[str, zipfile.ZipInfo]]:
    with zipfile.ZipFile(path, "r") as archive:
        bad_entry = archive.testzip()
        if bad_entry:
            raise UrbanMaskError(f"Corrupt project archive entry: {bad_entry}")
        entries = {name: archive.read(name) for name in archive.namelist()}
        infos = {info.filename: info for info in archive.infolist()}
    return entries, infos


def _load_array(entries: dict[str, bytes], name: str) -> np.ndarray:
    try:
        return np.load(io.BytesIO(entries[name]), allow_pickle=False)
    except KeyError as exc:
        raise UrbanMaskError(f"Project is missing {name}") from exc


def _array_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def _write_archive_atomic(
    project: Path,
    entries: dict[str, bytes],
    infos: dict[str, zipfile.ZipInfo],
) -> None:
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{project.name}.", suffix=".tmp", dir=project.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for name, payload in entries.items():
                archive.writestr(copy.copy(infos[name]), payload)
        with zipfile.ZipFile(temporary, "r") as archive:
            bad_entry = archive.testzip()
            if bad_entry:
                raise UrbanMaskError(f"Rebuilt archive is corrupt at {bad_entry}")
        os.replace(temporary, project)
    finally:
        if temporary.exists():
            temporary.unlink()


def _next_backup_path(project: Path) -> Path:
    candidate = project.with_name(project.name + ".urban_mask.bak")
    index = 2
    while candidate.exists():
        candidate = project.with_name(project.name + f".urban_mask.bak{index}")
        index += 1
    return candidate


def _load_reference(path: Path, expected_shape: tuple[int, int]) -> np.ndarray:
    if not path.is_file():
        raise UrbanMaskError(f"Reference raster does not exist: {path}")
    try:
        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    except Exception as exc:  # pragma: no cover - Pillow exception varies
        raise UrbanMaskError(f"Cannot read reference raster {path}: {exc}") from exc

    if rgb.shape[:2] != expected_shape:
        raise UrbanMaskError(
            f"Reference raster is {rgb.shape[1]}x{rgb.shape[0]}; "
            f"project layers are {expected_shape[1]}x{expected_shape[0]}"
        )

    grayscale = (rgb[:, :, 0] == rgb[:, :, 1]) & (rgb[:, :, 1] == rgb[:, :, 2])
    return grayscale & (rgb[:, :, 0] < URBAN_GRAYSCALE_CUTOFF)


def apply_mask(project: Path, reference: Path, *, dry_run: bool = False) -> dict[str, int | bool | str]:
    if not project.is_file():
        raise UrbanMaskError(f"Project archive does not exist: {project}")

    entries, infos = _read_archive(project)
    tile_map = _load_array(entries, "tile_map.npy")
    terrain_map = _load_array(entries, "terrain_map.npy")
    if tile_map.shape != terrain_map.shape:
        raise UrbanMaskError(
            f"Tile layer {tile_map.shape} and terrain layer {terrain_map.shape} differ"
        )
    if tile_map.ndim != 2:
        raise UrbanMaskError(f"Map layers must be two-dimensional, got {tile_map.ndim}")

    source_mask = _load_reference(reference, terrain_map.shape)
    land_mask = tile_map == TILE_LAND
    paint_mask = source_mask & land_mask
    water_source_mask = source_mask & ~land_mask

    new_terrain = terrain_map.copy()
    new_terrain[paint_mask] = URBAN_INDEX
    changed_mask = new_terrain != terrain_map

    # The operation is graphical-only and must not disturb HOI4's water rules.
    if np.any(new_terrain[tile_map == TILE_SEA] != OCEAN_INDEX):
        raise UrbanMaskError("Sea pixels do not all use the ocean terrain index")
    if np.any(new_terrain[tile_map == TILE_LAKE] != LAKES_INDEX):
        raise UrbanMaskError("Lake pixels do not all use the lakes terrain index")
    if np.any(changed_mask & ~paint_mask):
        raise UrbanMaskError("Terrain changed outside the land urban mask")

    result: dict[str, int | bool | str] = {
        "project": str(project),
        "reference": str(reference),
        "source_mask_pixels": int(source_mask.sum()),
        "land_pixels_painted": int(paint_mask.sum()),
        "water_mask_pixels_skipped": int(water_source_mask.sum()),
        "pixels_changed": int(changed_mask.sum()),
        "urban_pixels_after": int((new_terrain == URBAN_INDEX).sum()),
        "dry_run": dry_run,
    }

    if dry_run or not np.any(changed_mask):
        return result

    entries["terrain_map.npy"] = _array_bytes(new_terrain)
    backup = _next_backup_path(project)
    shutil.copy2(project, backup)
    _write_archive_atomic(project, entries, infos)

    with zipfile.ZipFile(project, "r") as archive:
        saved = _load_array({"terrain_map.npy": archive.read("terrain_map.npy")}, "terrain_map.npy")
        if not np.array_equal(saved, new_terrain):
            raise UrbanMaskError("Saved terrain layer does not match the generated layer")
        if archive.testzip():
            raise UrbanMaskError("Saved project archive failed integrity validation")
    result["backup"] = str(backup)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = apply_mask(args.project.resolve(), args.reference.resolve(), dry_run=args.dry_run)
    except UrbanMaskError as exc:
        print(f"ERROR: {exc}")
        return 2
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
