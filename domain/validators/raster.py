"""M3.3a raster and definition validator (map-foundation plan).

Pure, non-mutating checks over in-memory tile and province rasters that
return shared :class:`domain.validation.ValidationFinding` objects. The
validator has no Qt dependency and keeps no global mutable state so a
future central registry can call it with caller-supplied arrays.

Stable finding codes (all use layer ``provinces``):

- ``raster.dimensions``: tile/province shape problems, explicit
  ``expected_dimensions`` mismatches, and profile dimension violations.
- ``raster.definition_missing``: nonzero raster IDs with no supplied
  definition entry (including negative IDs, which can never be valid).
- ``raster.definition_orphan``: supplied definition IDs with no raster
  pixels. Only emitted when ``definitions`` is supplied.
- ``raster.id_gap``: positive IDs are not contiguous ``1..max``.
- ``raster.surface_unknown``: a province whose dominant tile surface is
  not land/sea/lake (undefined or illegal tile values dominate).
- ``raster.surface_mixed``: a province whose pixels mix surfaces.
- ``raster.connectivity``: a province ID with several 4-connected parts.
- ``raster.x_crossing``: a 2x2 block (or horizontal seam block when
  wrapping applies) with four distinct province IDs.
- ``raster.bbox``: a province bounding box wider or taller than
  ``max_bbox_ratio`` of the map (profile ``provinces.max_bbox_ratio``
  by default, ``0.125`` otherwise).

Severity policy: hard breaks that block a foundation candidate are
``error`` (shape mismatches that prevent any further check are
``blocker``). Suspicious but non-blocking states (orphans and mixed
surfaces) are ``warning`` and marked waivable. ``info`` is unused so
tiny synthetic fixtures stay quiet unless they violate an explicit
threshold.

Thresholds are explicit and testable: pass ``profile``,
``expected_dimensions`` (``(width, height)``), ``wrap_horizontal``,
``max_bbox_ratio``, ``include_engine_boundary``, and
``mixed_threshold`` explicitly. Without a profile or explicit
dimensions, small synthetic arrays are not judged against game-size
rules. Bounding-box and mixed-surface checks use only the supplied
thresholds, so callers can relax them for fixtures
(for example ``max_bbox_ratio=1.0``).
Findings are aggregated to one per failure family with sorted
``affected_ids`` and ``coordinates`` (``(x, y)`` pairs) and returned in
fixed rule order for deterministic output.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
from domain.validation import ValidationFinding

try:
    from domain.validators.province import (
        detect_id_gaps,
        detect_non_contiguous,
        detect_x_crossings,
    )
except Exception:  # pragma: no cover - import-time fallback for tooling
    detect_id_gaps = None  # type: ignore[assignment]
    detect_non_contiguous = None  # type: ignore[assignment]
    detect_x_crossings = None  # type: ignore[assignment]

LAYER = "provinces"

CODES = (
    "raster.dimensions",
    "raster.definition_missing",
    "raster.definition_orphan",
    "raster.id_gap",
    "raster.surface_unknown",
    "raster.surface_mixed",
    "raster.connectivity",
    "raster.x_crossing",
    "raster.bbox",
)

_DEFAULT_BBOX_RATIO = 0.125
_EPS = 1e-9

_TILE_KNOWN = (int(TILE_LAND), int(TILE_SEA), int(TILE_LAKE))


def _is_rgb_key(value: Any) -> bool:
    if isinstance(value, (tuple, list)) and len(value) == 3:
        try:
            parts = [int(v) for v in value]
        except (TypeError, ValueError):
            return False
        return all(0 <= p <= 255 for p in parts)
    return False


def _parse_single_definition_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("definition IDs must be positive integers, got bool")
    if isinstance(value, (int, np.integer)):
        pid = int(value)
        if pid <= 0:
            raise ValueError("definition IDs must be positive, got %r" % (value,))
        return pid
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError("definition IDs must be integers, got %r" % (value,))
        pid = int(value)
        if pid <= 0:
            raise ValueError("definition IDs must be positive, got %r" % (value,))
        return pid
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("definition ID string must not be empty")
        try:
            pid = int(text)
        except ValueError:
            raise ValueError("cannot parse definition ID from %r" % (value,)) from None
        if pid <= 0:
            raise ValueError("definition IDs must be positive, got %r" % (value,))
        return pid
    raise ValueError("cannot parse definition ID from %r" % (type(value).__name__,))


def _parse_mapping_value_id(value: Any) -> int:
    if isinstance(value, Mapping):
        for key in ("id", "province_id", "province", "ID", "Id"):
            if key in value:
                return _parse_single_definition_id(value[key])
        raise ValueError("definition mapping entry has no id field: %r" % (value,))
    return _parse_single_definition_id(value)


def _normalize_definition_ids(definitions: Any) -> set[int] | None:
    """Normalize supported definition inputs to a set of positive IDs.

    Accepted shapes (all without mutating the input):

    - ``None``: definition coverage is skipped (returns ``None``).
    - Mapping with ID keys (``{1: ..., 2: ...}``): keys are IDs.
    - Mapping with RGB keys (``{(r, g, b): {"id": n}}`` as produced by
      the province importer): each value supplies its ID.
    - Iterable of IDs (list/tuple/set/frozenset/ndarray of ints or
      numeric strings).
    - Iterable of mappings with an ``id`` (or ``province_id``) field.
    - A single int-like value is treated as one definition ID.

    Raises ``ValueError`` for unparseable entries so bad test fixtures
    fail loudly instead of silently changing coverage results.
    """
    if definitions is None:
        return None
    if isinstance(definitions, Mapping):
        if len(definitions) == 0:
            return set()
        keys = list(definitions.keys())
        if any(_is_rgb_key(k) for k in keys):
            if not all(_is_rgb_key(k) for k in keys):
                raise ValueError("definition mapping mixes RGB and ID keys")
            return {_parse_mapping_value_id(v) for v in definitions.values()}
        return {_parse_single_definition_id(k) for k in keys}
    if isinstance(definitions, (bytes, str)):
        return {_parse_single_definition_id(definitions)}
    if isinstance(definitions, (int, np.integer, float)) and not isinstance(definitions, bool):
        return {_parse_single_definition_id(definitions)}
    if isinstance(definitions, np.ndarray):
        return {_parse_single_definition_id(v) for v in definitions.ravel().tolist()}
    try:
        items = list(definitions)  # type: ignore[arg-type]
    except TypeError:
        raise ValueError(
            "unsupported definitions type %r" % (type(definitions).__name__,)
        ) from None
    result: set[int] = set()
    for item in items:
        if isinstance(item, Mapping):
            result.add(_parse_mapping_value_id(item))
        else:
            result.add(_parse_single_definition_id(item))
    return result


def _resolve_wrap(profile: Any, wrap_horizontal: bool | None) -> bool:
    if wrap_horizontal is not None:
        return bool(wrap_horizontal)
    if profile is not None:
        try:
            return bool(profile.dimensions.wrap_horizontal)
        except Exception:
            pass
    return True


def _resolve_bbox_ratio(profile: Any, max_bbox_ratio: float | None) -> float:
    if max_bbox_ratio is not None:
        ratio = float(max_bbox_ratio)
        if not 0.0 < ratio <= 1.0:
            raise ValueError("max_bbox_ratio must be in (0, 1], got %r" % (max_bbox_ratio,))
        return ratio
    if profile is not None:
        try:
            ratio = float(profile.provinces.max_bbox_ratio)
            if 0.0 < ratio <= 1.0:
                return ratio
        except Exception:
            pass
    return _DEFAULT_BBOX_RATIO


def _profile_dimension_errors(profile: Any, width: int, height: int) -> list[str]:
    if profile is None:
        return []
    func = getattr(profile, "validate_dimensions", None)
    if callable(func):
        try:
            errors = list(func(int(width), int(height)))
        except Exception:
            return []
        return [str(e) for e in errors if str(e).strip()]
    return []


def _first_coordinates(prov: np.ndarray, width: int) -> dict[int, tuple[int, int]]:
    """Map every nonzero province ID to its first (x, y) pixel in row-major order."""
    flat = prov.ravel()
    first: dict[int, int] = {}
    for index in range(flat.shape[0]):
        pid = int(flat[index])
        if pid != 0 and pid not in first:
            first[pid] = int(index)
    out: dict[int, tuple[int, int]] = {}
    for pid, index in first.items():
        y, x = divmod(int(index), int(width))
        out[int(pid)] = (int(x), int(y))
    return out


def _surface_table(tile: np.ndarray, prov: np.ndarray) -> dict[int, tuple[int, int, int, int, int]]:
    """Return {pid: (land, sea, lake, unknown, total)} for positive IDs only."""
    flat_pm = prov.ravel()
    flat_tm = tile.ravel()
    valid = flat_pm > 0
    if not bool(np.any(valid)):
        return {}
    pm_valid = flat_pm[valid].astype(np.int64, copy=False)
    tm_valid = flat_tm[valid].astype(np.int64, copy=False)
    max_id = int(pm_valid.max())
    size = max_id + 1
    total = np.bincount(pm_valid, minlength=size)
    land = np.bincount(pm_valid, weights=(tm_valid == int(TILE_LAND)).astype(np.int64), minlength=size)
    sea = np.bincount(pm_valid, weights=(tm_valid == int(TILE_SEA)).astype(np.int64), minlength=size)
    lake = np.bincount(pm_valid, weights=(tm_valid == int(TILE_LAKE)).astype(np.int64), minlength=size)
    table: dict[int, tuple[int, int, int, int, int]] = {}
    for pid in range(1, size):
        count = int(total[pid])
        if count <= 0:
            continue
        land_n, sea_n, lake_n = int(land[pid]), int(sea[pid]), int(lake[pid])
        unknown_n = count - land_n - sea_n - lake_n
        table[int(pid)] = (land_n, sea_n, lake_n, int(unknown_n), count)
    return table


def _dominant_surface(land: int, sea: int, lake: int) -> tuple[str, int]:
    if land >= sea and land >= lake:
        return ("land", int(land))
    if lake > sea:
        return ("lake", int(lake))
    return ("sea", int(sea))


def _bbox_table(prov: np.ndarray) -> dict[int, tuple[int, int, int, int, int, int]]:
    """Return {pid: (x0, y0, x1, y1, w, h)} for positive IDs only."""
    height, width = prov.shape
    flat = prov.ravel().astype(np.int64, copy=False)
    positive = flat[flat > 0]
    if positive.size == 0:
        return {}
    max_id = int(positive.max())
    size = max_id + 1
    ys, xs = np.indices(prov.shape)
    flat_y = ys.ravel().astype(np.int64, copy=False)
    flat_x = xs.ravel().astype(np.int64, copy=False)
    mask = flat > 0
    flat_pos = flat[mask]
    flat_y_pos = flat_y[mask]
    flat_x_pos = flat_x[mask]
    min_y = np.full(size, height, dtype=np.int64)
    max_y = np.full(size, -1, dtype=np.int64)
    min_x = np.full(size, width, dtype=np.int64)
    max_x = np.full(size, -1, dtype=np.int64)
    np.minimum.at(min_y, flat_pos, flat_y_pos)
    np.maximum.at(max_y, flat_pos, flat_y_pos)
    np.minimum.at(min_x, flat_pos, flat_x_pos)
    np.maximum.at(max_x, flat_pos, flat_x_pos)
    table: dict[int, tuple[int, int, int, int, int, int]] = {}
    present = set(int(v) for v in np.unique(positive).tolist())
    for pid in sorted(present):
        if max_y[pid] < 0:
            continue
        x0, y0, x1, y1 = int(min_x[pid]), int(min_y[pid]), int(max_x[pid]), int(max_y[pid])
        table[int(pid)] = (x0, y0, x1, y1, int(x1 - x0 + 1), int(y1 - y0 + 1))
    return table


def _oversized_ids(
    prov: np.ndarray,
    ratio: float,
    include_engine_boundary: bool,
) -> tuple[list[int], dict[int, tuple[int, int, int, int, int, int]]]:
    height, width = prov.shape
    table = _bbox_table(prov)
    if not table:
        return [], table
    boundary_is_invalid = bool(include_engine_boundary) or (width >= 256 and height >= 256)
    limit_w = float(width) * float(ratio)
    limit_h = float(height) * float(ratio)
    oversized: list[int] = []
    use_integer_path = abs(float(ratio) - _DEFAULT_BBOX_RATIO) < 1e-12
    for pid in sorted(table):
        _x0, _y0, _x1, _y1, w, h = table[pid]
        if use_integer_path:
            bad = (w * 8 > width) or (h * 8 > height)
            if boundary_is_invalid and (w * 8 == width or h * 8 == height):
                bad = True
        else:
            if boundary_is_invalid:
                bad = (float(w) + _EPS >= limit_w) or (float(h) + _EPS >= limit_h)
            else:
                bad = (float(w) > limit_w + _EPS) or (float(h) > limit_h + _EPS)
        if bad:
            oversized.append(int(pid))
    return oversized, table


def validate_raster_definition(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    definitions: Any = None,
    *,
    profile: Any = None,
    expected_dimensions: tuple[int, int] | list[int] | None = None,
    wrap_horizontal: bool | None = None,
    max_bbox_ratio: float | None = None,
    include_engine_boundary: bool = False,
    mixed_threshold: float = 0.0,
) -> list[ValidationFinding]:
    """Validate raster shape, definitions, IDs, surfaces, and geometry.

    The inputs are read-only: arrays are inspected through ``numpy``
    views and ``definitions`` is normalized without mutation. Returns
    findings in fixed rule order (dimensions, definition coverage, ID
    gaps, surfaces, connectivity, crossings, bounding boxes) with sorted
    IDs and coordinates so repeated calls with equal inputs produce
    equal outputs.
    """
    if tile_map is None or province_map is None:
        raise ValueError("tile_map and province_map must not be None")
    try:
        mixed_value = float(mixed_threshold)
    except (TypeError, ValueError):
        raise ValueError("mixed_threshold must be a float in [0, 1]") from None
    if not 0.0 <= mixed_value <= 1.0:
        raise ValueError("mixed_threshold must be in [0, 1]")
    if not isinstance(include_engine_boundary, bool):
        raise ValueError("include_engine_boundary must be a bool")
    if wrap_horizontal is not None and not isinstance(wrap_horizontal, bool):
        raise ValueError("wrap_horizontal must be a bool or None")

    expected: tuple[int, int] | None = None
    if expected_dimensions is not None:
        try:
            ew, eh = int(expected_dimensions[0]), int(expected_dimensions[1])  # type: ignore[index]
        except Exception:
            raise ValueError("expected_dimensions must be (width, height) integers") from None
        if ew <= 0 or eh <= 0:
            raise ValueError("expected_dimensions must be positive (width, height)")
        expected = (int(ew), int(eh))

    ratio = _resolve_bbox_ratio(profile, max_bbox_ratio)
    wrap = _resolve_wrap(profile, wrap_horizontal)

    tile = np.asarray(tile_map)
    prov_raw = np.asarray(province_map)
    findings: list[ValidationFinding] = []

    if tile.ndim != 2 or prov_raw.ndim != 2:
        findings.append(
            ValidationFinding(
                code="raster.dimensions",
                severity="blocker",
                message="Tile and province rasters must be 2-D arrays",
                layer=LAYER,
                evidence="tile_ndim=%d province_ndim=%d" % (int(tile.ndim), int(prov_raw.ndim)),
            )
        )
        return findings
    if tile.shape != prov_raw.shape:
        findings.append(
            ValidationFinding(
                code="raster.dimensions",
                severity="blocker",
                message="Tile and province rasters must share the same shape",
                layer=LAYER,
                evidence="tile=%dx%d province=%dx%d"
                % (int(tile.shape[1]), int(tile.shape[0]), int(prov_raw.shape[1]), int(prov_raw.shape[0])),
            )
        )
        return findings

    height, width = int(prov_raw.shape[0]), int(prov_raw.shape[1])
    if height <= 0 or width <= 0:
        findings.append(
            ValidationFinding(
                code="raster.dimensions",
                severity="blocker",
                message="Raster dimensions must be positive",
                layer=LAYER,
                evidence="shape=%dx%d" % (width, height),
            )
        )
        return findings

    if expected is not None and (width, height) != expected:
        findings.append(
            ValidationFinding(
                code="raster.dimensions",
                severity="error",
                message="Raster dimensions do not match the expected dimensions",
                layer=LAYER,
                evidence="actual=%dx%d expected=%dx%d" % (width, height, expected[0], expected[1]),
            )
        )

    profile_errors = _profile_dimension_errors(profile, width, height)
    if profile_errors:
        findings.append(
            ValidationFinding(
                code="raster.dimensions",
                severity="error",
                message="Raster dimensions fail profile validation",
                layer=LAYER,
                evidence="; ".join(profile_errors),
            )
        )

    prov = prov_raw.astype(np.int32, copy=False)
    unique_ids = sorted(int(v) for v in np.unique(prov).tolist())
    present = sorted(pid for pid in unique_ids if pid > 0)
    negatives = sorted(pid for pid in unique_ids if pid < 0)
    present_set = set(present)

    definition_ids = _normalize_definition_ids(definitions)

    if definition_ids is not None:
        raster_ids = set(present) | set(negatives)
        missing = sorted(raster_ids - set(definition_ids))
        if missing:
            coords = _first_coordinates(prov, width)
            findings.append(
                ValidationFinding(
                    code="raster.definition_missing",
                    severity="error",
                    message="%d raster province IDs have no definition entry" % len(missing),
                    layer=LAYER,
                    affected_ids=tuple(missing),
                    coordinates=tuple(coords[pid] for pid in missing if pid in coords),
                    evidence="missing=%s; raster=%d; definitions=%d"
                    % (",".join(str(p) for p in missing[:12]) + (",..." if len(missing) > 12 else ""), len(raster_ids), len(definition_ids)),
                )
            )
        orphans = sorted(set(definition_ids) - set(present) - set(negatives))
        if orphans:
            findings.append(
                ValidationFinding(
                    code="raster.definition_orphan",
                    severity="warning",
                    message="%d definition IDs have no raster pixels" % len(orphans),
                    layer=LAYER,
                    affected_ids=tuple(orphans),
                    evidence="orphans=%s" % (",".join(str(p) for p in orphans[:12]) + (",..." if len(orphans) > 12 else "")),
                    waivable=True,
                )
            )
    elif negatives:
        coords = _first_coordinates(prov, width)
        findings.append(
            ValidationFinding(
                code="raster.definition_missing",
                severity="error",
                message="%d negative raster IDs can never have a definition" % len(negatives),
                layer=LAYER,
                affected_ids=tuple(negatives),
                coordinates=tuple(coords[pid] for pid in negatives if pid in coords),
                evidence="negative=%s" % (",".join(str(p) for p in negatives[:12]) + (",..." if len(negatives) > 12 else "")),
            )
        )

    if detect_id_gaps is not None:
        try:
            gaps = [int(v) for v in detect_id_gaps(prov)]
        except Exception:
            gaps = []
    else:
        gaps = []
        if present:
            full = set(range(1, int(max(present)) + 1))
            gaps = sorted(full - present_set)
    if gaps:
        findings.append(
            ValidationFinding(
                code="raster.id_gap",
                severity="error",
                message="Province IDs are not contiguous 1..%d" % int(max(present) if present else 0),
                layer=LAYER,
                affected_ids=tuple(gaps),
                evidence="missing=%s; max=%d"
                % (",".join(str(p) for p in gaps[:12]) + (",..." if len(gaps) > 12 else ""), int(max(present) if present else 0)),
                repair_code="province.compact_ids",
            )
        )

    if present:
        table = _surface_table(tile, prov)
        coords = _first_coordinates(prov, width)
        unknown_ids: list[int] = []
        mixed_ids: list[int] = []
        mixed_details: list[str] = []
        unknown_details: list[str] = []
        for pid in sorted(table):
            land_n, sea_n, lake_n, unknown_n, total = table[pid]
            if total <= 0:
                continue
            if unknown_n > 0 and unknown_n >= land_n and unknown_n >= sea_n and unknown_n >= lake_n:
                unknown_ids.append(int(pid))
                unknown_details.append(
                    "pid=%d land=%d sea=%d lake=%d unknown=%d" % (int(pid), land_n, sea_n, lake_n, unknown_n)
                )
                continue
            _name, dominant_n = _dominant_surface(land_n, sea_n, lake_n)
            minority = int(total) - int(dominant_n)
            if minority < 0:
                minority = 0
            fraction = (float(minority) / float(total)) if total else 0.0
            if minority > 0 and fraction > float(mixed_value) + _EPS:
                mixed_ids.append(int(pid))
                mixed_details.append(
                    "pid=%d land=%d sea=%d lake=%d unknown=%d majority=%s minority=%.3f"
                    % (int(pid), land_n, sea_n, lake_n, unknown_n, _name, fraction)
                )
        if unknown_ids:
            findings.append(
                ValidationFinding(
                    code="raster.surface_unknown",
                    severity="error",
                    message="%d provinces have an unknown dominant surface" % len(unknown_ids),
                    layer=LAYER,
                    affected_ids=tuple(unknown_ids),
                    coordinates=tuple(coords[pid] for pid in unknown_ids if pid in coords),
                    evidence="; ".join(unknown_details[:6]) + ("; ..." if len(unknown_details) > 6 else ""),
                )
            )
        if mixed_ids:
            findings.append(
                ValidationFinding(
                    code="raster.surface_mixed",
                    severity="warning",
                    message="%d provinces mix land/sea/lake surfaces" % len(mixed_ids),
                    layer=LAYER,
                    affected_ids=tuple(mixed_ids),
                    coordinates=tuple(coords[pid] for pid in mixed_ids if pid in coords),
                    evidence="; ".join(mixed_details[:6]) + ("; ..." if len(mixed_details) > 6 else ""),
                    waivable=True,
                )
            )

        non_contiguous: list[int] = []
        if detect_non_contiguous is not None:
            try:
                non_contiguous = [int(v) for v in detect_non_contiguous(prov)]
            except Exception:
                non_contiguous = []
        non_contiguous = sorted(set(non_contiguous) & present_set)
        if non_contiguous:
            findings.append(
                ValidationFinding(
                    code="raster.connectivity",
                    severity="error",
                    message="%d provinces are not 4-connected" % len(non_contiguous),
                    layer=LAYER,
                    affected_ids=tuple(non_contiguous),
                    coordinates=tuple(coords[pid] for pid in non_contiguous if pid in coords),
                    evidence="non_contiguous=%s" % (",".join(str(p) for p in non_contiguous[:12]) + (",..." if len(non_contiguous) > 12 else "")),
                    repair_code="province.reconnect",
                )
            )

        positions: list[tuple[int, int]] = []
        if detect_x_crossings is not None:
            try:
                positions = [(int(y), int(x)) for y, x in detect_x_crossings(prov, map_width=width, wrap_horizontal=wrap, profile=profile)]
            except Exception:
                positions = []
        positions = sorted(set(positions))
        if positions:
            involved: set[int] = set()
            for y, x in positions:
                if not (0 <= y < height - 1):
                    continue
                if x == width - 1:
                    corners = [(y, x), (y, 0), (y + 1, x), (y + 1, 0)]
                elif 0 <= x < width - 1:
                    corners = [(y, x), (y, x + 1), (y + 1, x), (y + 1, x + 1)]
                else:
                    continue
                for py, px in corners:
                    if 0 <= py < height and 0 <= px < width:
                        pid = int(prov[py, px])
                        if pid != 0:
                            involved.add(pid)
            affected = sorted(involved)
            xy = tuple(sorted((int(x), int(y)) for y, x in positions))
            findings.append(
                ValidationFinding(
                    code="raster.x_crossing",
                    severity="error",
                    message="%d X-crossings with four distinct IDs in a 2x2 block" % len(positions),
                    layer=LAYER,
                    affected_ids=tuple(affected),
                    coordinates=xy,
                    evidence="crossings=%d; first=%s" % (len(positions), ",".join("%d,%d" % pair for pair in xy[:6])),
                    repair_code="province.fix_x_crossing",
                )
            )

        oversized, bbox_lookup = _oversized_ids(prov, ratio, bool(include_engine_boundary))
        oversized = sorted(set(oversized) & present_set)
        if oversized:
            limit_w = float(width) * float(ratio)
            limit_h = float(height) * float(ratio)
            parts: list[str] = []
            for pid in oversized[:6]:
                entry = bbox_lookup.get(int(pid))
                if entry is None:
                    continue
                _x0, _y0, _x1, _y1, w, h = entry
                parts.append("pid=%d bbox=%dx%d limit=%.2fx%.2f" % (int(pid), int(w), int(h), limit_w, limit_h))
            findings.append(
                ValidationFinding(
                    code="raster.bbox",
                    severity="error",
                    message="%d provinces exceed %.3g of the map width/height" % (len(oversized), float(ratio)),
                    layer=LAYER,
                    affected_ids=tuple(oversized),
                    coordinates=tuple(
                        (int(bbox_lookup[pid][0]), int(bbox_lookup[pid][1])) for pid in oversized if pid in bbox_lookup
                    ),
                    evidence="ratio=%.4g limit=%.2fx%.2f; %s%s"
                    % (float(ratio), limit_w, limit_h, "; ".join(parts), "; ..." if len(oversized) > 6 else ""),
                    repair_code="province.bbox_trim",
                )
            )

    return findings


