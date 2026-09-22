"""Shared province surface classification and normalization helpers.

HOI4 treats a province as one surface class.  A province raster can contain
small accidental fragments of another class, but those fragments must not
survive export: in particular, a lake province must not also contain land
pixels.  These helpers keep the checker, export repairs, and editor
auto-completion on the same classification rules.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE


SURFACE_TILES = {
    "land": int(TILE_LAND),
    "sea": int(TILE_SEA),
    "lake": int(TILE_LAKE),
}


@dataclass(frozen=True)
class ProvinceSurfaceCounts:
    """Surface pixel counts for one positive province ID."""

    province_id: int
    land: int
    sea: int
    lake: int
    total: int

    @property
    def is_land_lake_split(self) -> bool:
        return self.land > 0 and self.lake > 0

    @property
    def dominant_surface(self) -> str:
        return dominant_surface(self.land, self.sea, self.lake)


@dataclass(frozen=True)
class ProvinceSurfaceNormalization:
    """One normalized province and the number of changed tile pixels."""

    province_id: int
    land: int
    sea: int
    lake: int
    total: int
    target_surface: str
    changed_pixels: int


def dominant_surface(land: int, sea: int, lake: int) -> str:
    """Return the export classification for a province's known surfaces.

    The tie rules intentionally match the long-standing exporter behavior:
    land wins ties, then lake wins over sea, otherwise the province is sea.
    """
    if land >= sea and land >= lake:
        return "land"
    if lake > sea:
        return "lake"
    return "sea"


def surface_counts_by_province(tile_map, province_map) -> dict[int, ProvinceSurfaceCounts]:
    """Return known surface counts for every positive province ID.

    Invalid or mismatched rasters produce an empty result so the checker can
    report its own shape error without crashing while trying to inspect
    province surfaces.
    """
    try:
        tile = np.asarray(tile_map)
        province = np.asarray(province_map)
        if tile.ndim != 2 or province.ndim != 2 or tile.shape != province.shape:
            return {}
        flat_province = province.ravel()
        flat_tile = tile.ravel()
        valid = flat_province > 0
        if not bool(np.any(valid)):
            return {}
        province_values = flat_province[valid].astype(np.int64, copy=False)
        tile_values = flat_tile[valid].astype(np.int64, copy=False)
        max_id = int(province_values.max())
        size = max_id + 1
        total = np.bincount(province_values, minlength=size)
        land = np.bincount(
            province_values,
            weights=(tile_values == int(TILE_LAND)).astype(np.int64),
            minlength=size,
        )
        sea = np.bincount(
            province_values,
            weights=(tile_values == int(TILE_SEA)).astype(np.int64),
            minlength=size,
        )
        lake = np.bincount(
            province_values,
            weights=(tile_values == int(TILE_LAKE)).astype(np.int64),
            minlength=size,
        )
    except (TypeError, ValueError, OverflowError):
        return {}

    return {
        int(pid): ProvinceSurfaceCounts(
            province_id=int(pid),
            land=int(land[pid]),
            sea=int(sea[pid]),
            lake=int(lake[pid]),
            total=int(total[pid]),
        )
        for pid in range(1, size)
        if int(total[pid]) > 0
    }


def find_land_lake_splits(tile_map, province_map) -> tuple[ProvinceSurfaceCounts, ...]:
    """Return positive provinces containing both land and lake pixels."""
    table = surface_counts_by_province(tile_map, province_map)
    return tuple(item for item in table.values() if item.is_land_lake_split)


def normalize_land_lake_splits(
    tile_map,
    province_map,
    province_ids=None,
    overrides=None,
) -> tuple[ProvinceSurfaceNormalization, ...]:
    """Normalize land/lake-split provinces in place.

    A split province is rewritten to its dominant export surface.  The
    optional ``province_ids`` filter is useful when applying a previously
    planned repair; ``overrides`` preserves explicit project surface choices.
    """
    try:
        tile = np.asarray(tile_map)
        province = np.asarray(province_map)
        if tile.ndim != 2 or province.ndim != 2 or tile.shape != province.shape:
            return ()
    except (TypeError, ValueError):
        return ()

    allowed = None if province_ids is None else {int(pid) for pid in province_ids}
    forced = {int(pid): str(value).strip().lower() for pid, value in (overrides or {}).items()}
    results: list[ProvinceSurfaceNormalization] = []
    for counts in find_land_lake_splits(tile, province):
        if allowed is not None and counts.province_id not in allowed:
            continue
        target = forced.get(counts.province_id, counts.dominant_surface)
        if target not in SURFACE_TILES:
            target = counts.dominant_surface
        mask = province == counts.province_id
        changed = int(np.count_nonzero(tile[mask] != SURFACE_TILES[target]))
        if changed:
            tile[mask] = SURFACE_TILES[target]
        results.append(
            ProvinceSurfaceNormalization(
                province_id=counts.province_id,
                land=counts.land,
                sea=counts.sea,
                lake=counts.lake,
                total=counts.total,
                target_surface=target,
                changed_pixels=changed,
            )
        )
    return tuple(results)


__all__ = [
    "ProvinceSurfaceCounts",
    "ProvinceSurfaceNormalization",
    "SURFACE_TILES",
    "dominant_surface",
    "find_land_lake_splits",
    "normalize_land_lake_splits",
    "surface_counts_by_province",
]
