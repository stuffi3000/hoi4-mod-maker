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

from data.constants import TILE_LAND
from data.constants import TILE_SEA
from data.constants import TILE_LAKE
from domain.managers.map_placement import POSITION_SLOT_COUNT
from domain.managers.map_placement import ProvincePositionSlot

__all__ = [
    "DIAGNOSTIC_CODES",
    "PlacementDiagnostic",
    "PlacementProposalResult",
    "generate_placement_proposals",
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
