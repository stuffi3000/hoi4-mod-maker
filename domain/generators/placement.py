"""Deterministic province position proposal generator, M5.2 slice.

Pure proposal step that suggests positions.txt slot coordinates from
in-memory rasters without touching managers, exports, services, views,
the filesystem, the user interface, or any game installation.

Coordinate convention:
    Raster pixel space with origin at the top left. For a pixel at column
    col and row row, the proposal uses fractional pixel centers
    pos_x equals col plus 0.5 and pos_y equals row plus 0.5, with
    0 <= pos_x < width and 0 <= pos_y < height. Rotation is always 0.0 in
    this slice. Height is 0.0 unless a height map is supplied, in which
    case height is the selected local height sample as a finite float.
    Non finite height samples are replaced with 0.0 so every record keeps
    finite floats.

Scoring:
    Candidates are land pixels of one province only, so proposals can
    never land outside their province and never on sea, lake, or
    undefined tiles. Each candidate is scored from normalized
    per-province components:
    interior distance to the province border with larger preferred,
    coast distance to the nearest sea or lake tile with larger preferred
    when water exists, local height closeness to the province median with
    closer preferred when a height map is supplied, and local slope from
    central differences with flatter preferred when a height map is
    supplied. Weights tune the relative importance. Surface type is
    enforced by construction because only land tiles are candidates.
    Separation between slots is enforced greedily with a minimum Euclidean
    distance in pixel units.

Determinism:
    Inputs are never mutated. There are no global map size assumptions,
    the actual array dimensions are used. The seed affects only
    deterministic tie breaking between exactly equal scores through a
    stable integer hash of seed, province id, row, and column. The same
    inputs and seed always produce equal records. Output is sorted by
    province id then slot.

Absence handling:
    Sea, lake, and non land provinces are skipped, they receive no land
    proposals. Provinces with fewer usable pixels than requested slots
    receive fewer unique records, never duplicated centroids. Every
    absence is reported explicitly with a PlacementDiagnostic. This module
    never emits silently repeated centroids and never emits authored,
    reviewed, or final data. Generated proposals always use provenance
    generated with review status unreviewed. No fallback provenance
    records are emitted by this slice, the diagnostic list is the explicit
    absence signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from math import isfinite as math_isfinite
from numbers import Integral as IntegralNumber
import operator as operator_module
from typing import Iterable as TypingIterable

import numpy as np
from scipy.ndimage import distance_transform_edt as edt_distance

from collections.abc import Mapping as CollectionsMapping
from data.constants import TILE_LAND
from data.constants import TILE_SEA
from data.constants import TILE_LAKE
from domain.managers.map_placement import POSITION_SLOT_COUNT
from domain.managers.map_placement import POSITION_SLOT_MAX
from domain.managers.map_placement import POSITION_SLOT_MIN
from domain.managers.map_placement import PortPlacement
from domain.managers.map_placement import ProvincePositionSlot

__all__ = [
    "DIAGNOSTIC_CODES",
    "INGEST_DIAGNOSTIC_CODES",
    "PORT_DIAGNOSTIC_CODES",
    "PlacementAcceptanceReport",
    "PlacementDiagnostic",
    "PlacementProposalResult",
    "PlacementStoreReport",
    "PortProposalResult",
    "PortStoreReport",
    "ProposalIngestDiagnostic",
    "accept_stored_placements",
    "generate_placement_proposals",
    "generate_port_proposals",
    "store_placement_proposals",
    "store_port_proposals",
]

DIAGNOSTIC_CODES = (
    "non_land",
    "unknown_province",
    "insufficient_space",
)


@dataclass(frozen=True)
class PlacementDiagnostic:
    """Deterministic explanation for a missing or partial proposal set.

    Attributes:
        province_id: Province the diagnostic refers to.
        code: One of non_land, unknown_province, or insufficient_space.
            non_land means the province has no land pixels and sea, lake,
            and non land provinces are skipped for land proposals.
            unknown_province means the requested id is absent from the
            province map. insufficient_space means fewer unique separated
            slots were available than requested.
        message: Human readable deterministic detail.
    """

    province_id: int
    code: str
    message: str


@dataclass
class PlacementProposalResult:
    """Small documented result type for proposal generation.

    Attributes:
        slots: ProvincePositionSlot records with provenance generated and
            review status unreviewed, sorted by province id then slot.
        diagnostics: Explicit absence signals sorted by province id, then
            code, then message. Empty when every requested province
            received the full slot count.
    """

    slots: list = dataclass_field(default_factory=list)
    diagnostics: list = dataclass_field(default_factory=list)

    def __post_init__(self):
        ordered_slots = sorted(
            list(self.slots),
            key=lambda record: (int(record.province_id), int(record.slot)),
        )
        ordered_diagnostics = sorted(
            list(self.diagnostics),
            key=lambda diag: (
                int(diag.province_id),
                str(diag.code),
                str(diag.message),
            ),
        )
        self.slots = ordered_slots
        self.diagnostics = ordered_diagnostics

    def slots_for_province(self, province_id: int) -> list:
        """Return slots for one province in slot order."""
        wanted = int(province_id)
        return [
            record
            for record in self.slots
            if int(record.province_id) == wanted
        ]

    def diagnostics_for_province(self, province_id: int) -> list:
        """Return diagnostics for one province in stable order."""
        wanted = int(province_id)
        return [
            diag
            for diag in self.diagnostics
            if int(diag.province_id) == wanted
        ]


def _coerce_seed(seed_value) -> int:
    """Coerce seed to int while rejecting booleans."""
    if isinstance(seed_value, bool):
        raise ValueError("seed must be an integer, got boolean")
    try:
        seed_int = operator_module.index(seed_value)
    except TypeError as exc_info:
        raise ValueError(f"seed must be an integer, got {seed_value!r}") from exc_info
    return int(seed_int)


def _coerce_slot_count(slot_value) -> int:
    """Validate slot count against the positions.txt contract."""
    if isinstance(slot_value, bool):
        raise ValueError("slot_count must be an integer, got boolean")
    try:
        slot_int = operator_module.index(slot_value)
    except TypeError as exc_info:
        raise ValueError(
            f"slot_count must be an integer, got {slot_value!r}"
        ) from exc_info
    slot_int = int(slot_int)
    if not 1 <= slot_int <= int(POSITION_SLOT_COUNT):
        raise ValueError(
            "slot_count must be within 1 and "
            f"{int(POSITION_SLOT_COUNT)}, got {slot_int!r}"
        )
    return slot_int


def _coerce_nonnegative_float(param_value, param_name: str) -> float:
    """Validate tuning floats as finite values at least zero."""
    if isinstance(param_value, bool):
        raise ValueError(f"{param_name} must be a number, got boolean")
    try:
        param_float = float(param_value)
    except (TypeError, ValueError) as exc_info:
        raise ValueError(
            f"{param_name} must be a number, got {param_value!r}"
        ) from exc_info
    if not math_isfinite(param_float):
        raise ValueError(f"{param_name} must be finite, got {param_value!r}")
    if param_float < 0.0:
        raise ValueError(f"{param_name} must be at least zero, got {param_value!r}")
    return float(param_float)


def _coerce_province_list(
    requested_ids: TypingIterable[int] | None,
    present_ids: set[int],
) -> list[int]:
    """Return sorted unique requested ids or sorted present ids."""
    if requested_ids is None:
        return sorted(present_ids)
    collected: list[int] = []
    seen: set[int] = set()
    for raw_value in requested_ids:
        if isinstance(raw_value, bool) or not isinstance(raw_value, IntegralNumber):
            raise ValueError(
                f"province_ids must hold positive integers, got {raw_value!r}"
            )
        pid_int = int(raw_value)
        if pid_int <= 0:
            raise ValueError(
                f"province_ids must hold positive integers, got {raw_value!r}"
            )
        if pid_int not in seen:
            seen.add(pid_int)
            collected.append(pid_int)
    collected.sort()
    return collected


def _tiebreak_keys(
    seed_u32: int,
    province_id: int,
    row_values: np.ndarray,
    col_values: np.ndarray,
) -> np.ndarray:
    """Stable deterministic tie break keys in the unit interval.

    Uses 64 bit integer mixing of column, row, province id, and seed so
    the same inputs always hash identically on every platform and run.
    """
    row_u64 = row_values.astype(np.uint64, copy=False)
    col_u64 = col_values.astype(np.uint64, copy=False)
    mixed = col_u64 * np.uint64(73856093)
    mixed = mixed ^ (row_u64 * np.uint64(19349663))
    mixed = mixed ^ (np.uint64(int(province_id)) * np.uint64(83492791))
    mixed = mixed ^ (np.uint64(int(seed_u32)) * np.uint64(2971215073))
    mixed = mixed & np.uint64(0xFFFFFFFF)
    return mixed.astype(np.float64) / float(0x100000000)


def _normalize_higher(values: np.ndarray) -> np.ndarray:
    """Normalize so larger input maps toward one, ties map to zero."""
    work = np.asarray(values, dtype=np.float64)
    min_value = float(work.min())
    max_value = float(work.max())
    span = max_value - min_value
    if span <= 0.0:
        return np.zeros(work.shape, dtype=np.float64)
    return (work - min_value) / span


def _normalize_lower(values: np.ndarray) -> np.ndarray:
    """Normalize so smaller input maps toward one, ties map to zero."""
    work = np.asarray(values, dtype=np.float64)
    min_value = float(work.min())
    max_value = float(work.max())
    span = max_value - min_value
    if span <= 0.0:
        return np.zeros(work.shape, dtype=np.float64)
    return float(1.0) - (work - min_value) / span


def _normalize_closeness(values: np.ndarray) -> np.ndarray:
    """Normalize so values near the median map toward one."""
    work = np.asarray(values, dtype=np.float64)
    min_value = float(work.min())
    max_value = float(work.max())
    span = max_value - min_value
    if span <= 0.0:
        return np.zeros(work.shape, dtype=np.float64)
    median_value = float(np.median(work))
    closeness = float(1.0) - np.abs(work - median_value) / span
    return np.clip(closeness, float(0.0), float(1.0))


def generate_placement_proposals(
    province_map: np.ndarray,
    tile_map: np.ndarray,
    height_map: np.ndarray | None = None,
    province_ids: TypingIterable[int] | None = None,
    *,
    seed: int = 0,
    slot_count: int = int(POSITION_SLOT_COUNT),
    min_separation: float = 2.0,
    border_weight: float = 1.0,
    coast_weight: float = 1.0,
    height_weight: float = 0.5,
    slope_weight: float = 1.0,
) -> PlacementProposalResult:
    """Generate deterministic land position proposals without side effects.

    Args:
        province_map: Two dimensional integer array of province ids where
            zero means unassigned. Actual dimensions are used, no global
            map size is assumed.
        tile_map: Two dimensional integer array with the same shape as
            province_map holding tile surface types. Only tiles equal to
            land are candidates, which enforces surface type handling.
        height_map: Optional two dimensional numeric array with the same
            shape. When supplied, local height closeness to the province
            median and local slope from central differences contribute to
            scoring, and output height is the selected local sample.
        province_ids: Optional iterable of province ids to propose for.
            Defaults to every positive id present in province_map. Order
            of this iterable does not affect output order.
        seed: Deterministic integer seed affecting only tie breaking
            between exactly equal scores.
        slot_count: Number of slots per province, defaults to six and must
            stay within one and six to match the positions contract.
        min_separation: Minimum Euclidean distance in pixel units between
            slots of the same province. Must be finite and at least zero.
        border_weight: Weight for interior distance from the province
            border. Must be finite and at least zero.
        coast_weight: Weight for distance from land and sea coast, namely
            the nearest sea or lake tile. Must be finite and at least zero.
            When the map holds no water, this component is neutral.
        height_weight: Weight for height closeness, used only when a
            height map is supplied. Must be finite and at least zero.
        slope_weight: Weight for flatness, used only when a height map is
            supplied. Must be finite and at least zero.

    Returns:
        PlacementProposalResult with slots sorted by province id then slot
        and diagnostics sorted by province id, code, and message. Every
        slot uses provenance generated with review status unreviewed,
        rotation 0.0, fractional pixel-center coordinates, and finite
        floats. Provinces without land pixels produce no slots and one
        non_land diagnostic. Unknown requested ids produce one
        unknown_province diagnostic. Provinces with fewer unique separated
        pixels than requested produce the available unique slots plus one
        insufficient_space diagnostic. No coordinates are ever duplicated
        within a province.
    """
    province_arr = np.asarray(province_map)
    tile_arr = np.asarray(tile_map)
    if province_arr.ndim != 2 or tile_arr.ndim != 2:
        raise ValueError("province_map and tile_map must be two dimensional arrays")
    if province_arr.shape != tile_arr.shape:
        raise ValueError("province_map and tile_map must share the same shape")
    num_rows = int(province_arr.shape[0])
    num_cols = int(province_arr.shape[1])
    if num_rows <= 0 or num_cols <= 0:
        raise ValueError("province_map and tile_map must be non empty")

    seed_int = _coerce_seed(seed)
    seed_u32 = int(seed_int) & int(0xFFFFFFFF)
    wanted_slots = _coerce_slot_count(slot_count)
    separation = _coerce_nonnegative_float(min_separation, "min_separation")
    border_importance = _coerce_nonnegative_float(border_weight, "border_weight")
    coast_importance = _coerce_nonnegative_float(coast_weight, "coast_weight")
    height_importance = _coerce_nonnegative_float(height_weight, "height_weight")
    slope_importance = _coerce_nonnegative_float(slope_weight, "slope_weight")

    flat_provinces = province_arr.ravel()
    present_ids: set[int] = set()
    for raw_pid in np.unique(flat_provinces):
        pid_int = int(raw_pid)
        if pid_int > 0:
            present_ids.add(pid_int)
    ordered_pids = _coerce_province_list(province_ids, present_ids)

    safe_height: np.ndarray | None = None
    slope_field: np.ndarray | None = None
    raw_height: np.ndarray | None = None
    if height_map is not None:
        raw_height = np.asarray(height_map, dtype=np.float64)
        if raw_height.shape != province_arr.shape:
            raise ValueError("height_map must share the shape of province_map")
        finite_mask = np.isfinite(raw_height)
        if np.any(finite_mask):
            fill_value = float(np.median(raw_height[finite_mask]))
        else:
            fill_value = float(0.0)
        safe_height = np.where(finite_mask, raw_height, fill_value)
        grad_rows = np.zeros_like(safe_height, dtype=np.float64)
        grad_cols = np.zeros_like(safe_height, dtype=np.float64)
        if num_rows > 1:
            grad_rows = np.asarray(
                np.gradient(safe_height, axis=0), dtype=np.float64
            )
        if num_cols > 1:
            grad_cols = np.asarray(
                np.gradient(safe_height, axis=1), dtype=np.float64
            )
        slope_field = np.hypot(grad_rows, grad_cols)

    water_mask = (tile_arr == int(TILE_SEA)) | (tile_arr == int(TILE_LAKE))
    if bool(np.any(water_mask)):
        coast_field = np.asarray(edt_distance(~water_mask), dtype=np.float64)
    else:
        coast_field = np.full(
            province_arr.shape, float(max(num_rows, num_cols)), dtype=np.float64
        )

    land_mask_global = tile_arr == int(TILE_LAND)
    result_slots: list[ProvincePositionSlot] = []
    result_diagnostics: list[PlacementDiagnostic] = []

    for province_id in ordered_pids:
        if province_id not in present_ids:
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="unknown_province",
                    message=(
                        f"province {int(province_id)} is absent from "
                        "province_map, no proposals generated"
                    ),
                )
            )
            continue
        province_mask = province_arr == int(province_id)
        candidate_mask = province_mask & land_mask_global
        land_rows, land_cols = np.nonzero(candidate_mask)
        if land_rows.size == 0:
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="non_land",
                    message=(
                        f"province {int(province_id)} has no land pixels, "
                        "sea and lake and non land provinces are skipped"
                    ),
                )
            )
            continue

        min_row = int(land_rows.min())
        max_row = int(land_rows.max())
        min_col = int(land_cols.min())
        max_col = int(land_cols.max())
        box_top = max(0, min_row - 1)
        box_bottom = min(num_rows, max_row + 2)
        box_left = max(0, min_col - 1)
        box_right = min(num_cols, max_col + 2)
        box_mask = province_arr[box_top:box_bottom, box_left:box_right] == int(
            province_id
        )
        padded = np.zeros(
            (int(box_mask.shape[0]) + 2, int(box_mask.shape[1]) + 2),
            dtype=bool,
        )
        padded[1:-1, 1:-1] = box_mask
        interior_box = np.asarray(edt_distance(padded), dtype=np.float64)
        interior_values = interior_box[
            (land_rows - box_top + 1), (land_cols - box_left + 1)
        ].astype(np.float64, copy=False)
        coast_values = coast_field[land_rows, land_cols].astype(
            np.float64, copy=False
        )

        interior_norm = _normalize_higher(interior_values)
        coast_norm = _normalize_higher(coast_values)
        total_score = (
            border_importance * interior_norm + coast_importance * coast_norm
        )

        if safe_height is not None and slope_field is not None:
            height_values = safe_height[land_rows, land_cols].astype(
                np.float64, copy=False
            )
            slope_values = slope_field[land_rows, land_cols].astype(
                np.float64, copy=False
            )
            height_norm = _normalize_closeness(height_values)
            slope_norm = _normalize_lower(slope_values)
            total_score = (
                total_score
                + height_importance * height_norm
                + slope_importance * slope_norm
            )

        tie_values = _tiebreak_keys(seed_u32, province_id, land_rows, land_cols)
        sort_order = np.lexsort((tie_values, -total_score))

        picked_rows: list[int] = []
        picked_cols: list[int] = []
        picked_heights: list[float] = []
        for order_pos in sort_order.tolist():
            cand_index = int(order_pos)
            cand_row = int(land_rows[cand_index])
            cand_col = int(land_cols[cand_index])
            if picked_rows:
                row_diff = np.asarray(picked_rows, dtype=np.float64) - float(
                    cand_row
                )
                col_diff = np.asarray(picked_cols, dtype=np.float64) - float(
                    cand_col
                )
                nearest = float(np.min(np.hypot(row_diff, col_diff)))
                if nearest < float(separation):
                    continue
            picked_rows.append(cand_row)
            picked_cols.append(cand_col)
            if raw_height is not None:
                raw_value = float(raw_height[cand_row, cand_col])
                if math_isfinite(raw_value):
                    picked_heights.append(float(raw_value))
                else:
                    picked_heights.append(float(0.0))
            else:
                picked_heights.append(float(0.0))
            if len(picked_rows) >= int(wanted_slots):
                break

        for slot_index in range(len(picked_rows)):
            pos_x = float(picked_cols[slot_index]) + float(0.5)
            pos_y = float(picked_rows[slot_index]) + float(0.5)
            result_slots.append(
                ProvincePositionSlot(
                    province_id=int(province_id),
                    slot=int(slot_index),
                    x=float(pos_x),
                    y=float(pos_y),
                    rotation=float(0.0),
                    height=float(picked_heights[slot_index]),
                    meaning="",
                    provenance="generated",
                    review_status="unreviewed",
                )
            )
        if len(picked_rows) < int(wanted_slots):
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="insufficient_space",
                    message=(
                        f"province {int(province_id)} produced "
                        f"{len(picked_rows)} of {int(wanted_slots)} "
                        "unique slots with min_separation "
                        f"{float(separation)}, no centroid was duplicated"
                    ),
                )
            )

    result = PlacementProposalResult(
        slots=result_slots, diagnostics=result_diagnostics
    )
    return result


PORT_DIAGNOSTIC_CODES = (
    "unknown_province",
    "unknown_sea",
    "non_land",
    "non_sea",
    "missing_mapping",
    "invalid_mapping",
    "no_adjacency",
)


@dataclass
class PortProposalResult:
    """Small documented result type for port proposal generation.

    Attributes:
        ports: PortPlacement records with provenance generated and review
            status unreviewed, sorted by province id. At most one record
            per land province is ever emitted.
        diagnostics: Explicit absence signals sorted by province id, then
            code, then message. Empty when every requested land province
            received a port proposal.
    """

    ports: list = dataclass_field(default_factory=list)
    diagnostics: list = dataclass_field(default_factory=list)

    def __post_init__(self):
        ordered_ports = sorted(
            list(self.ports),
            key=lambda record: int(record.province_id),
        )
        ordered_diagnostics = sorted(
            list(self.diagnostics),
            key=lambda diag: (
                int(diag.province_id),
                str(diag.code),
                str(diag.message),
            ),
        )
        self.ports = ordered_ports
        self.diagnostics = ordered_diagnostics

    def ports_for_province(self, province_id: int) -> list:
        """Return port proposals for one province in stable order."""
        wanted = int(province_id)
        return [
            record
            for record in self.ports
            if int(record.province_id) == wanted
        ]

    def diagnostics_for_province(self, province_id: int) -> list:
        """Return diagnostics for one province in stable order."""
        wanted = int(province_id)
        return [
            diag
            for diag in self.diagnostics
            if int(diag.province_id) == wanted
        ]


def generate_port_proposals(
    province_map: np.ndarray,
    tile_map: np.ndarray,
    sea_mapping: CollectionsMapping,
    height_map: np.ndarray | None = None,
    province_ids: TypingIterable[int] | None = None,
    *,
    seed: int = 0,
    border_weight: float = 1.0,
    coast_weight: float = 1.0,
    height_weight: float = 0.5,
    slope_weight: float = 1.0,
) -> PortProposalResult:
    """Generate deterministic port and naval-base spawn proposals.

    Pure proposal step that suggests one PortPlacement per coastal land
    province from in-memory rasters without touching managers, exports,
    services, views, the filesystem, the user interface, or any game
    installation. Inputs are never mutated and no global state is used.

    Args:
        province_map: Two dimensional integer array of province ids where
            zero means unassigned. Actual dimensions are used, no global
            map size is assumed.
        tile_map: Two dimensional integer array with the same shape as
            province_map holding tile surface types. Only tiles equal to
            land can host a port, and only tiles equal to sea count as
            sea surface for adjacency.
        sea_mapping: Mapping of land province id to intended sea province
            id. The mapped sea province is always used exactly as given,
            this function never substitutes a different sea province.
        height_map: Optional two dimensional numeric array with the same
            shape. When supplied, local height closeness to the legal
            candidate median and local slope from central differences
            contribute to scoring, and output height is the selected
            local sample as a finite float.
        province_ids: Optional iterable of land province ids to propose
            for. Defaults to the sorted positive integer keys of
            sea_mapping. Order of this iterable does not affect output
            order.
        seed: Deterministic integer seed affecting only tie breaking
            between exactly equal scores through a stable integer hash
            of seed, province id, row, and column.
        border_weight: Weight for interior distance from the province
            border. Must be finite and at least zero. Larger interior
            distance is preferred among legal coastal pixels.
        coast_weight: Weight for distance from the nearest sea or lake
            tile. Must be finite and at least zero. Larger distance is
            preferred among legal coastal pixels, and the component is
            neutral when the map holds no water.
        height_weight: Weight for height closeness within the legal
            coastal set, used only when a height map is supplied. Must
            be finite and at least zero.
        slope_weight: Weight for flatness within the legal coastal set,
            used only when a height map is supplied. Must be finite and
            at least zero.

    Returns:
        PortProposalResult with ports sorted by province id and
        diagnostics sorted by province id, code, and message. Every port
        uses provenance generated with review status unreviewed,
        rotation 0.0, fractional pixel-center coordinates with finite
        floats, local height as a finite float with non finite samples
        replaced by 0.0, and the exact mapped sea province. At most one
        port per land province is emitted, so centroids are never
        repeated.

    Absence handling:
        A port is emitted only when the land province exists, the mapped
        sea province exists, the sea province holds at least one sea
        surface tile, the land province holds at least one land tile,
        and at least one land pixel of the land province is 4-neighbor
        adjacent to a tile that is both part of the exact mapped sea
        province and a sea surface tile. Every other case produces no
        port and exactly one diagnostic for the land province. Missing
        mapping entries produce missing_mapping. Non positive integer
        mapping values produce invalid_mapping. Absent land ids produce
        unknown_province. Absent sea ids produce unknown_sea. Land
        provinces without land pixels produce non_land. Sea provinces
        without sea surface tiles produce non_sea. Land provinces with
        no exact adjacency produce no_adjacency, and no fallback sea is
        ever chosen. Diagnostics carry the requesting land province id
        and name both ids in the message.
    """
    province_arr = np.asarray(province_map)
    tile_arr = np.asarray(tile_map)
    if province_arr.ndim != 2 or tile_arr.ndim != 2:
        raise ValueError("province_map and tile_map must be two dimensional arrays")
    if province_arr.shape != tile_arr.shape:
        raise ValueError("province_map and tile_map must share the same shape")
    num_rows = int(province_arr.shape[0])
    num_cols = int(province_arr.shape[1])
    if num_rows <= 0 or num_cols <= 0:
        raise ValueError("province_map and tile_map must be non empty")
    if not isinstance(sea_mapping, CollectionsMapping):
        raise ValueError("sea_mapping must be a mapping of land province to sea province")

    seed_int = _coerce_seed(seed)
    seed_u32 = int(seed_int) & int(0xFFFFFFFF)
    border_importance = _coerce_nonnegative_float(border_weight, "border_weight")
    coast_importance = _coerce_nonnegative_float(coast_weight, "coast_weight")
    height_importance = _coerce_nonnegative_float(height_weight, "height_weight")
    slope_importance = _coerce_nonnegative_float(slope_weight, "slope_weight")

    flat_provinces = province_arr.ravel()
    present_ids: set[int] = set()
    for raw_pid in np.unique(flat_provinces):
        pid_int = int(raw_pid)
        if pid_int > 0:
            present_ids.add(pid_int)

    mapping_snapshot = dict(sea_mapping)
    clean_mapping: dict[int, object] = {}
    for raw_key, raw_value in mapping_snapshot.items():
        if isinstance(raw_key, bool):
            continue
        try:
            key_int = operator_module.index(raw_key)
        except TypeError:
            continue
        key_int = int(key_int)
        if key_int <= 0:
            continue
        clean_mapping[int(key_int)] = raw_value

    if province_ids is None:
        ordered_pids = sorted(clean_mapping.keys())
    else:
        ordered_pids = _coerce_province_list(province_ids, present_ids)

    safe_height: np.ndarray | None = None
    slope_field: np.ndarray | None = None
    raw_height: np.ndarray | None = None
    if height_map is not None:
        raw_height = np.asarray(height_map, dtype=np.float64)
        if raw_height.shape != province_arr.shape:
            raise ValueError("height_map must share the shape of province_map")
        finite_mask = np.isfinite(raw_height)
        if np.any(finite_mask):
            fill_value = float(np.median(raw_height[finite_mask]))
        else:
            fill_value = float(0.0)
        safe_height = np.where(finite_mask, raw_height, fill_value)
        grad_rows = np.zeros_like(safe_height, dtype=np.float64)
        grad_cols = np.zeros_like(safe_height, dtype=np.float64)
        if num_rows > 1:
            grad_rows = np.asarray(
                np.gradient(safe_height, axis=0), dtype=np.float64
            )
        if num_cols > 1:
            grad_cols = np.asarray(
                np.gradient(safe_height, axis=1), dtype=np.float64
            )
        slope_field = np.hypot(grad_rows, grad_cols)

    water_mask = (tile_arr == int(TILE_SEA)) | (tile_arr == int(TILE_LAKE))
    if bool(np.any(water_mask)):
        coast_field = np.asarray(edt_distance(~water_mask), dtype=np.float64)
    else:
        coast_field = np.full(
            province_arr.shape, float(max(num_rows, num_cols)), dtype=np.float64
        )

    land_mask_global = tile_arr == int(TILE_LAND)
    result_ports: list[PortPlacement] = []
    result_diagnostics: list[PlacementDiagnostic] = []

    for province_id in ordered_pids:
        if province_id not in present_ids:
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="unknown_province",
                    message=(
                        f"province {int(province_id)} is absent from "
                        "province_map, no port proposal generated"
                    ),
                )
            )
            continue
        if province_id not in clean_mapping:
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="missing_mapping",
                    message=(
                        f"province {int(province_id)} has no intended sea "
                        "province in sea_mapping, no port proposal generated"
                    ),
                )
            )
            continue
        raw_sea = clean_mapping[int(province_id)]
        if isinstance(raw_sea, bool):
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="invalid_mapping",
                    message=(
                        f"province {int(province_id)} maps to invalid sea "
                        f"province {raw_sea!r}, expected a positive integer"
                    ),
                )
            )
            continue
        try:
            sea_candidate = operator_module.index(raw_sea)
        except TypeError:
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="invalid_mapping",
                    message=(
                        f"province {int(province_id)} maps to invalid sea "
                        f"province {raw_sea!r}, expected a positive integer"
                    ),
                )
            )
            continue
        sea_candidate = int(sea_candidate)
        if sea_candidate <= 0:
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="invalid_mapping",
                    message=(
                        f"province {int(province_id)} maps to invalid sea "
                        f"province {raw_sea!r}, expected a positive integer"
                    ),
                )
            )
            continue
        sea_id = int(sea_candidate)
        if sea_id not in present_ids:
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="unknown_sea",
                    message=(
                        f"province {int(province_id)} maps to sea province "
                        f"{int(sea_id)} absent from province_map, no port "
                        "proposal generated"
                    ),
                )
            )
            continue
        sea_surface_mask = (province_arr == int(sea_id)) & (
            tile_arr == int(TILE_SEA)
        )
        if not bool(np.any(sea_surface_mask)):
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="non_sea",
                    message=(
                        f"province {int(province_id)} maps to sea province "
                        f"{int(sea_id)} with no sea surface tiles, no port "
                        "proposal generated"
                    ),
                )
            )
            continue
        province_mask = province_arr == int(province_id)
        land_mask = province_mask & land_mask_global
        if not bool(np.any(land_mask)):
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="non_land",
                    message=(
                        f"province {int(province_id)} has no land pixels, "
                        "sea and lake and non land provinces are skipped"
                    ),
                )
            )
            continue
        adjacent_to_sea = np.zeros(province_arr.shape, dtype=bool)
        adjacent_to_sea[1:, :] |= sea_surface_mask[:-1, :]
        adjacent_to_sea[:-1, :] |= sea_surface_mask[1:, :]
        adjacent_to_sea[:, 1:] |= sea_surface_mask[:, :-1]
        adjacent_to_sea[:, :-1] |= sea_surface_mask[:, 1:]
        legal_mask = land_mask & adjacent_to_sea
        legal_rows, legal_cols = np.nonzero(legal_mask)
        if legal_rows.size == 0:
            result_diagnostics.append(
                PlacementDiagnostic(
                    province_id=int(province_id),
                    code="no_adjacency",
                    message=(
                        f"province {int(province_id)} has no land pixel "
                        "4-neighbor adjacent to sea province "
                        f"{int(sea_id)} on a sea surface tile, no fallback "
                        "sea was chosen"
                    ),
                )
            )
            continue
        prov_rows, prov_cols = np.nonzero(province_mask)
        min_row = int(prov_rows.min())
        max_row = int(prov_rows.max())
        min_col = int(prov_cols.min())
        max_col = int(prov_cols.max())
        box_top = max(0, min_row - 1)
        box_bottom = min(num_rows, max_row + 2)
        box_left = max(0, min_col - 1)
        box_right = min(num_cols, max_col + 2)
        box_mask = province_arr[box_top:box_bottom, box_left:box_right] == int(
            province_id
        )
        padded = np.zeros(
            (int(box_mask.shape[0]) + 2, int(box_mask.shape[1]) + 2),
            dtype=bool,
        )
        padded[1:-1, 1:-1] = box_mask
        interior_box = np.asarray(edt_distance(padded), dtype=np.float64)
        interior_values = interior_box[
            (legal_rows - box_top + 1), (legal_cols - box_left + 1)
        ].astype(np.float64, copy=False)
        coast_values = coast_field[legal_rows, legal_cols].astype(
            np.float64, copy=False
        )
        interior_norm = _normalize_higher(interior_values)
        coast_norm = _normalize_higher(coast_values)
        total_score = (
            border_importance * interior_norm + coast_importance * coast_norm
        )
        if safe_height is not None and slope_field is not None:
            height_values = safe_height[legal_rows, legal_cols].astype(
                np.float64, copy=False
            )
            slope_values = slope_field[legal_rows, legal_cols].astype(
                np.float64, copy=False
            )
            height_norm = _normalize_closeness(height_values)
            slope_norm = _normalize_lower(slope_values)
            total_score = (
                total_score
                + height_importance * height_norm
                + slope_importance * slope_norm
            )
        tie_values = _tiebreak_keys(seed_u32, province_id, legal_rows, legal_cols)
        sort_order = np.lexsort((tie_values, -total_score))
        best_pos = int(sort_order[0])
        best_row = int(legal_rows[best_pos])
        best_col = int(legal_cols[best_pos])
        if raw_height is not None:
            raw_value = float(raw_height[best_row, best_col])
            if math_isfinite(raw_value):
                best_height = float(raw_value)
            else:
                best_height = float(0.0)
        else:
            best_height = float(0.0)
        pos_x = float(best_col) + float(0.5)
        pos_y = float(best_row) + float(0.5)
        result_ports.append(
            PortPlacement(
                province_id=int(province_id),
                x=float(pos_x),
                y=float(pos_y),
                rotation=float(0.0),
                height=float(best_height),
                sea_province=int(sea_id),
                provenance="generated",
                review_status="unreviewed",
            )
        )

    result = PortProposalResult(
        ports=result_ports, diagnostics=result_diagnostics
    )
    return result


INGEST_DIAGNOSTIC_CODES = (
    "protected",
    "exists_unreviewed_generated",
    "missing",
)


@dataclass(frozen=True)
class ProposalIngestDiagnostic:
    """Deterministic explanation for a skipped or missing proposal record.

    Attributes:
        kind: Either slot or port, naming the affected collection.
        province_id: Province the diagnostic refers to.
        slot: Slot index for slot records, None for port records.
        code: One of protected, exists_unreviewed_generated, or missing.
            protected means the manager already holds an authored or
            reviewed record at that key and the existing record was kept.
            exists_unreviewed_generated means the manager already holds
            an unreviewed generated record at that key and it was kept
            because replace_generated was False. missing means an
            acceptance request named a key with no stored record.
        message: Human readable deterministic detail.
    """

    kind: str
    province_id: int
    slot: int | None
    code: str
    message: str


@dataclass
class PlacementStoreReport:
    """Concise deterministic outcome of slot proposal ingestion.

    Attributes:
        stored_keys: Newly stored (province_id, slot) keys in sorted order.
        replaced_keys: Explicitly replaced unreviewed generated keys in
            sorted order. Only ever non empty when replace_generated is
            True.
        skipped: ProposalIngestDiagnostic records for proposals that were
            not stored, sorted by kind, province id, slot, code, message.
    """

    stored_keys: list = dataclass_field(default_factory=list)
    replaced_keys: list = dataclass_field(default_factory=list)
    skipped: list = dataclass_field(default_factory=list)

    def __post_init__(self):
        self.stored_keys = sorted(
            [(int(pid), int(slot)) for pid, slot in self.stored_keys]
        )
        self.replaced_keys = sorted(
            [(int(pid), int(slot)) for pid, slot in self.replaced_keys]
        )
        self.skipped = sorted(
            list(self.skipped),
            key=lambda diag: (
                str(diag.kind),
                int(diag.province_id),
                -1 if diag.slot is None else int(diag.slot),
                str(diag.code),
                str(diag.message),
            ),
        )

    @property
    def stored_count(self):
        return len(self.stored_keys)

    @property
    def replaced_count(self):
        return len(self.replaced_keys)

    @property
    def skipped_count(self):
        return len(self.skipped)


@dataclass
class PortStoreReport:
    """Concise deterministic outcome of port proposal ingestion.

    Attributes:
        stored_ids: Newly stored port province ids in sorted order.
        replaced_ids: Explicitly replaced unreviewed generated port ids in
            sorted order. Only ever non empty when replace_generated is
            True.
        skipped: ProposalIngestDiagnostic records for proposals that were
            not stored, sorted by kind, province id, slot, code, message.
    """

    stored_ids: list = dataclass_field(default_factory=list)
    replaced_ids: list = dataclass_field(default_factory=list)
    skipped: list = dataclass_field(default_factory=list)

    def __post_init__(self):
        self.stored_ids = sorted([int(pid) for pid in self.stored_ids])
        self.replaced_ids = sorted([int(pid) for pid in self.replaced_ids])
        self.skipped = sorted(
            list(self.skipped),
            key=lambda diag: (
                str(diag.kind),
                int(diag.province_id),
                -1 if diag.slot is None else int(diag.slot),
                str(diag.code),
                str(diag.message),
            ),
        )

    @property
    def stored_count(self):
        return len(self.stored_ids)

    @property
    def replaced_count(self):
        return len(self.replaced_ids)

    @property
    def skipped_count(self):
        return len(self.skipped)


@dataclass
class PlacementAcceptanceReport:
    """Concise deterministic outcome of explicit proposal acceptance.

    Attributes:
        accepted_slot_keys: Accepted (province_id, slot) keys in order.
        accepted_port_ids: Accepted port province ids in sorted order.
        missing: ProposalIngestDiagnostic records for requested keys with
            no stored record, sorted by kind, province id, slot, message.
    """

    accepted_slot_keys: list = dataclass_field(default_factory=list)
    accepted_port_ids: list = dataclass_field(default_factory=list)
    missing: list = dataclass_field(default_factory=list)

    def __post_init__(self):
        self.accepted_slot_keys = sorted(
            [(int(pid), int(slot)) for pid, slot in self.accepted_slot_keys]
        )
        self.accepted_port_ids = sorted(
            [int(pid) for pid in self.accepted_port_ids]
        )
        self.missing = sorted(
            list(self.missing),
            key=lambda diag: (
                str(diag.kind),
                int(diag.province_id),
                -1 if diag.slot is None else int(diag.slot),
                str(diag.code),
                str(diag.message),
            ),
        )

    @property
    def accepted_count(self):
        return len(self.accepted_slot_keys) + len(self.accepted_port_ids)

    @property
    def missing_count(self):
        return len(self.missing)


def _require_store_manager(manager, method_names):
    """Return the manager after checking the required methods exist."""
    if manager is None:
        raise TypeError(
            "manager must be a MapPlacementManager-like object, got None"
        )
    missing = [
        name for name in method_names if not callable(getattr(manager, name, None))
    ]
    if missing:
        raise TypeError(
            f"manager is missing required methods: {sorted(missing)}"
        )
    return manager


def _require_replace_flag(replace_generated):
    """Validate the explicit replacement flag as a real boolean."""
    if not isinstance(replace_generated, bool):
        raise ValueError(
            "replace_generated must be a boolean, "
            f"got {replace_generated!r}"
        )
    return bool(replace_generated)


def _is_replaceable_generated(record):
    """Tell whether a stored record may be replaced under the flag."""
    return (
        getattr(record, "provenance", None) == "generated"
        and getattr(record, "review_status", None) == "unreviewed"
    )


def _validate_unreviewed_generated(record, expected_type, kind):
    """Enforce the generator-to-manager proposal contract before mutation."""
    if not isinstance(record, expected_type):
        raise TypeError(
            f"{kind} proposal records must be {expected_type.__name__} "
            f"instances, got {type(record).__name__}"
        )
    if record.provenance != "generated" or record.review_status != "unreviewed":
        raise ValueError(
            f"{kind} proposals must remain generated and unreviewed until "
            f"explicit acceptance; got provenance={record.provenance!r}, "
            f"review_status={record.review_status!r}"
        )
    return record


def _coerce_accept_slot_keys(slot_keys):
    """Validate acceptance slot keys into a sorted unique key list."""
    if slot_keys is None:
        return []
    if isinstance(slot_keys, (str, bytes)):
        raise TypeError(
            "slot_keys must be an iterable of (province_id, slot) pairs, "
            f"got {slot_keys!r}"
        )
    try:
        raw_items = list(slot_keys)
    except TypeError as exc_info:
        raise TypeError(
            "slot_keys must be an iterable of (province_id, slot) pairs, "
            f"got {slot_keys!r}"
        ) from exc_info
    seen = set()
    for raw in raw_items:
        if isinstance(raw, (str, bytes)):
            raise TypeError(
                "slot_keys entries must be (province_id, slot) pairs, "
                f"got {raw!r}"
            )
        try:
            pair = tuple(raw)
        except TypeError as exc_info:
            raise TypeError(
                "slot_keys entries must be (province_id, slot) pairs, "
                f"got {raw!r}"
            ) from exc_info
        if len(pair) != 2:
            raise TypeError(
                "slot_keys entries must be (province_id, slot) pairs, "
                f"got {raw!r}"
            )
        raw_pid, raw_slot = pair
        if isinstance(raw_pid, bool):
            raise ValueError(
                "slot province_id must be a positive integer, "
                f"got {raw_pid!r}"
            )
        try:
            pid = operator_module.index(raw_pid)
        except TypeError as exc_info:
            raise TypeError(
                "slot province_id must be a positive integer, "
                f"got {raw_pid!r}"
            ) from exc_info
        pid = int(pid)
        if pid <= 0:
            raise ValueError(
                "slot province_id must be a positive integer, "
                f"got {raw_pid!r}"
            )
        if isinstance(raw_slot, bool):
            raise ValueError(
                "slot must be an integer in "
                f"{int(POSITION_SLOT_MIN)}..{int(POSITION_SLOT_MAX)}, "
                f"got {raw_slot!r}"
            )
        try:
            slot = operator_module.index(raw_slot)
        except TypeError as exc_info:
            raise TypeError(
                "slot must be an integer in "
                f"{int(POSITION_SLOT_MIN)}..{int(POSITION_SLOT_MAX)}, "
                f"got {raw_slot!r}"
            ) from exc_info
        slot = int(slot)
        if not int(POSITION_SLOT_MIN) <= slot <= int(POSITION_SLOT_MAX):
            raise ValueError(
                "slot must be an integer in "
                f"{int(POSITION_SLOT_MIN)}..{int(POSITION_SLOT_MAX)}, "
                f"got {raw_slot!r}"
            )
        seen.add((int(pid), int(slot)))
    return sorted(seen)


def _coerce_accept_port_ids(port_ids):
    """Validate acceptance port ids into a sorted unique id list."""
    if port_ids is None:
        return []
    if isinstance(port_ids, (str, bytes)):
        raise TypeError(
            "port_ids must be an iterable of province ids, "
            f"got {port_ids!r}"
        )
    try:
        raw_items = list(port_ids)
    except TypeError as exc_info:
        raise TypeError(
            "port_ids must be an iterable of province ids, "
            f"got {port_ids!r}"
        ) from exc_info
    seen = set()
    for raw in raw_items:
        if isinstance(raw, bool):
            raise ValueError(
                f"port province_id must be a positive integer, got {raw!r}"
            )
        try:
            pid = operator_module.index(raw)
        except TypeError as exc_info:
            raise TypeError(
                f"port province_id must be a positive integer, got {raw!r}"
            ) from exc_info
        pid = int(pid)
        if pid <= 0:
            raise ValueError(
                f"port province_id must be a positive integer, got {raw!r}"
            )
        seen.add(int(pid))
    return sorted(seen)


def store_placement_proposals(manager, proposal, *, replace_generated=False):
    """Store land slot proposals without ever marking them reviewed.

    Copies every record from a PlacementProposalResult into the supplied
    manager with float transforms, meaning, provenance, and review status
    preserved verbatim, so stored proposals stay generated and unreviewed.
    Ingestion never calls a mark reviewed method. The proposal object
    and its records are never mutated, and stored records are fresh copies.
    Only the explicitly supplied manager is mutated.

    Args:
        manager: MapPlacementManager-like object providing
            get_province_slot and set_province_slot.
        proposal: PlacementProposalResult whose slots are stored in
            (province_id, slot) order for determinism.
        replace_generated: When False, the default, any key that already
            holds a record is skipped and reported. When True, keys that
            already hold an unreviewed generated record are replaced,
            while authored or reviewed records are still kept and reported
            as protected.

    Returns:
        PlacementStoreReport with sorted stored, replaced, and skipped
        entries. Skipped entries use code exists_unreviewed_generated for
        kept unreviewed generated records and protected for kept authored
        or reviewed records.
    """
    _require_store_manager(manager, ("get_province_slot", "set_province_slot"))
    if not isinstance(proposal, PlacementProposalResult):
        raise TypeError(
            "proposal must be a PlacementProposalResult, "
            f"got {type(proposal).__name__}"
        )
    replace = _require_replace_flag(replace_generated)
    ordered = sorted(
        list(proposal.slots),
        key=lambda record: (int(record.province_id), int(record.slot)),
    )
    for record in ordered:
        _validate_unreviewed_generated(record, ProvincePositionSlot, "slot")
    stored_keys = []
    replaced_keys = []
    skipped = []
    for record in ordered:
        pid = int(record.province_id)
        slot = int(record.slot)
        existing = manager.get_province_slot(pid, slot)
        if existing is None:
            manager.set_province_slot(
                pid,
                slot,
                float(record.x),
                float(record.y),
                rotation=float(record.rotation),
                height=float(record.height),
                meaning=str(record.meaning),
                provenance=str(record.provenance),
                review_status=str(record.review_status),
            )
            stored_keys.append((pid, slot))
            continue
        if replace and _is_replaceable_generated(existing):
            manager.set_province_slot(
                pid,
                slot,
                float(record.x),
                float(record.y),
                rotation=float(record.rotation),
                height=float(record.height),
                meaning=str(record.meaning),
                provenance=str(record.provenance),
                review_status=str(record.review_status),
            )
            replaced_keys.append((pid, slot))
            continue
        if _is_replaceable_generated(existing):
            skipped.append(
                ProposalIngestDiagnostic(
                    kind="slot",
                    province_id=int(pid),
                    slot=int(slot),
                    code="exists_unreviewed_generated",
                    message=(
                        f"slot {(int(pid), int(slot))!r} already holds an "
                        "unreviewed generated record, kept; pass "
                        "replace_generated=True to replace it"
                    ),
                )
            )
        else:
            skipped.append(
                ProposalIngestDiagnostic(
                    kind="slot",
                    province_id=int(pid),
                    slot=int(slot),
                    code="protected",
                    message=(
                        f"slot {(int(pid), int(slot))!r} already holds a "
                        f"{existing.provenance} {existing.review_status} "
                        "record, kept and never overwritten by default"
                    ),
                )
            )
    return PlacementStoreReport(
        stored_keys=stored_keys, replaced_keys=replaced_keys, skipped=skipped
    )


def store_port_proposals(manager, proposal, *, replace_generated=False):
    """Store port proposals without ever marking them reviewed.

    Copies every record from a PortProposalResult into the supplied
    manager with float transforms, the exact mapped sea province,
    provenance, and review status preserved verbatim, so stored proposals
    stay generated and unreviewed. Ingestion never calls a mark reviewed
    method. The proposal object and its records are never mutated, and
    stored records are fresh copies. Only the explicitly supplied manager
    is mutated.

    Args:
        manager: MapPlacementManager-like object providing get_port and
            set_port.
        proposal: PortProposalResult whose ports are stored in province
            id order for determinism.
        replace_generated: When False, the default, any province that
            already holds a port is skipped and reported. When True,
            provinces that already hold an unreviewed generated port are
            replaced, while authored or reviewed ports are still kept and
            reported as protected.

    Returns:
        PortStoreReport with sorted stored, replaced, and skipped
        entries. Skipped entries use code exists_unreviewed_generated for
        kept unreviewed generated ports and protected for kept authored
        or reviewed ports.
    """
    _require_store_manager(manager, ("get_port", "set_port"))
    if not isinstance(proposal, PortProposalResult):
        raise TypeError(
            "proposal must be a PortProposalResult, "
            f"got {type(proposal).__name__}"
        )
    replace = _require_replace_flag(replace_generated)
    ordered = sorted(list(proposal.ports), key=lambda record: int(record.province_id))
    for record in ordered:
        _validate_unreviewed_generated(record, PortPlacement, "port")
    stored_ids = []
    replaced_ids = []
    skipped = []
    for record in ordered:
        pid = int(record.province_id)
        raw_sea = record.sea_province
        sea_arg = None if raw_sea is None else int(raw_sea)
        existing = manager.get_port(pid)
        if existing is None:
            manager.set_port(
                pid,
                float(record.x),
                float(record.y),
                rotation=float(record.rotation),
                height=float(record.height),
                sea_province=sea_arg,
                provenance=str(record.provenance),
                review_status=str(record.review_status),
            )
            stored_ids.append(pid)
            continue
        if replace and _is_replaceable_generated(existing):
            manager.set_port(
                pid,
                float(record.x),
                float(record.y),
                rotation=float(record.rotation),
                height=float(record.height),
                sea_province=sea_arg,
                provenance=str(record.provenance),
                review_status=str(record.review_status),
            )
            replaced_ids.append(pid)
            continue
        if _is_replaceable_generated(existing):
            skipped.append(
                ProposalIngestDiagnostic(
                    kind="port",
                    province_id=int(pid),
                    slot=None,
                    code="exists_unreviewed_generated",
                    message=(
                        f"port province {int(pid)} already holds an "
                        "unreviewed generated record, kept; pass "
                        "replace_generated=True to replace it"
                    ),
                )
            )
        else:
            skipped.append(
                ProposalIngestDiagnostic(
                    kind="port",
                    province_id=int(pid),
                    slot=None,
                    code="protected",
                    message=(
                        f"port province {int(pid)} already holds a "
                        f"{existing.provenance} {existing.review_status} "
                        "record, kept and never overwritten by default"
                    ),
                )
            )
    return PortStoreReport(
        stored_ids=stored_ids, replaced_ids=replaced_ids, skipped=skipped
    )


def accept_stored_placements(
    manager, slot_keys=(), port_ids=(), *, review_status="reviewed"
):
    """Explicitly accept selected stored proposals in one deterministic call.

    This is the only helper in this module that changes review status, and
    it only touches the explicitly listed keys. Ingestion helpers never
    accept anything. Callers that prefer single-record calls may use
    manager.mark_slot_reviewed and manager.mark_port_reviewed directly
    with identical effect.

    Args:
        manager: MapPlacementManager-like object providing
            get_province_slot, mark_slot_reviewed, get_port, and
            mark_port_reviewed.
        slot_keys: Iterable of (province_id, slot) pairs to accept.
            Duplicates are accepted once, order does not matter.
        port_ids: Iterable of port province ids to accept. Duplicates are
            accepted once, order does not matter.
        review_status: Either reviewed or accepted. Unreviewed and unknown
            values are rejected so acceptance can never silently reset a
            record.

    Returns:
        PlacementAcceptanceReport with sorted accepted keys and sorted
        missing diagnostics for requested keys with no stored record.
    """
    _require_store_manager(
        manager,
        (
            "get_province_slot",
            "mark_slot_reviewed",
            "get_port",
            "mark_port_reviewed",
        ),
    )
    if review_status not in ("reviewed", "accepted"):
        raise ValueError(
            "review_status must be reviewed or accepted, "
            f"got {review_status!r}; acceptance never resets to unreviewed"
        )
    wanted_slots = _coerce_accept_slot_keys(slot_keys)
    wanted_ports = _coerce_accept_port_ids(port_ids)
    accepted_slots = []
    accepted_ports = []
    missing = []
    for pid, slot in wanted_slots:
        existing = manager.get_province_slot(pid, slot)
        if existing is None:
            missing.append(
                ProposalIngestDiagnostic(
                    kind="slot",
                    province_id=int(pid),
                    slot=int(slot),
                    code="missing",
                    message=(
                        f"slot {(int(pid), int(slot))!r} has no stored "
                        "record, nothing was accepted"
                    ),
                )
            )
            continue
        manager.mark_slot_reviewed(pid, slot, review_status)
        accepted_slots.append((int(pid), int(slot)))
    for pid in wanted_ports:
        existing = manager.get_port(pid)
        if existing is None:
            missing.append(
                ProposalIngestDiagnostic(
                    kind="port",
                    province_id=int(pid),
                    slot=None,
                    code="missing",
                    message=(
                        f"port province {int(pid)} has no stored record, "
                        "nothing was accepted"
                    ),
                )
            )
            continue
        manager.mark_port_reviewed(pid, review_status)
        accepted_ports.append(int(pid))
    return PlacementAcceptanceReport(
        accepted_slot_keys=accepted_slots,
        accepted_port_ids=accepted_ports,
        missing=missing,
    )
