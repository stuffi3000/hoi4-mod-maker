"""Pure deterministic placement overlay model (M5.3 slice).

Read-only model for a future placement map overlay. It classifies
duck-typed placement records (slots, ports, buildings, weather) plus
victory-point locations and ``placement.collision`` finding coordinates
into sorted, stable markers without importing PyQt, touching the
filesystem, using global map state, or mutating its inputs.

The model remains independent of Qt and project services; the canvas and
MainWindow consume it for interactive display and selection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real
from typing import Any

__all__ = [
    "PlacementOverlayMarker",
    "PlacementOverlayModel",
    "build_placement_overlay_model",
]

_OVERLAY_KINDS: tuple[str, ...] = (
    "slot",
    "port",
    "building",
    "weather",
    "vp",
    "collision",
)

_MISSING: Any = object()

_REVIEW_STATUSES = frozenset({"reviewed", "accepted"})
_GENERATED_PROVENANCES = frozenset({"generated", "fallback"})
_AUTHORED_PROVENANCES = frozenset({"authored", "imported"})

_POSITION_SLOT_MIN = 0
_POSITION_SLOT_MAX = 5

_X_NAMES: tuple[str, ...] = ("x", "pos_x")
_Y_NAMES: tuple[str, ...] = ("y", "pos_y")
_XY_TUPLE_NAMES: tuple[str, ...] = (
    "position",
    "pos",
    "xy",
    "coords",
    "coord",
    "point",
)
_PROVINCE_NAMES: tuple[str, ...] = ("province_id", "province", "pid")
_REGION_NAMES: tuple[str, ...] = ("region_id", "region", "rid")
_PROVENANCE_NAMES: tuple[str, ...] = ("provenance", "origin", "source")
_REVIEW_NAMES: tuple[str, ...] = ("review_status", "review")


@dataclass(frozen=True)
class PlacementOverlayMarker:
    """One read-only overlay symbol.

    ``kind`` is one of ``slot``, ``port``, ``building``, ``weather``,
    ``vp``, or ``collision``. ``key`` is a stable, deterministic identity
    string (identity fields plus kind, never an input-order index).
    ``x``/``y`` are finite floats with fractional precision preserved.
    ``role`` is the display role: ``reviewed``/``accepted`` for reviewed
    records, ``generated`` for unreviewed generated/fallback records,
    ``authored`` for authored/imported records, ``unreviewed`` for
    anything else, plus explicit ``vp`` and ``collision`` roles.
    """

    kind: str
    key: str
    x: float
    y: float
    role: str


@dataclass(frozen=True)
class PlacementOverlayModel:
    """Deterministic overlay result.

    ``markers`` holds every record, victory-point, and collision marker
    sorted by ``(kind, key, x, y)``. ``collision_points`` holds the
    de-duplicated, sorted ``(x, y)`` float pairs contributed by findings
    with code ``placement.collision``.
    """

    markers: tuple[PlacementOverlayMarker, ...]
    collision_points: tuple[tuple[float, float], ...]


def _field(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        try:
            return record.get(name, default)
        except Exception:
            return default
    try:
        return getattr(record, name, default)
    except Exception:
        return default


def _has(record: Any, name: str) -> bool:
    if isinstance(record, Mapping):
        try:
            return name in record
        except Exception:
            return False
    try:
        return hasattr(record, name)
    except Exception:
        return False


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        try:
            number = float(int(value))
        except (OverflowError, ValueError):
            return None
        return number if isfinite(number) else None
    if isinstance(value, Real):
        try:
            number = float(value)
        except (OverflowError, ValueError):
            return None
        return number if isfinite(number) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        return number if isfinite(number) else None
    return None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        try:
            number = float(value)
        except (OverflowError, ValueError):
            return None
        if not isfinite(number) or not number.is_integer():
            return None
        return int(number)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            pass
        try:
            number = float(text)
        except ValueError:
            return None
        if not isfinite(number) or not number.is_integer():
            return None
        return int(number)
    return None


def _first_field(record: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        if _has(record, name):
            return _field(record, name, None)
    return _MISSING


def _parse_direct_xy(record: Any) -> tuple[float | None, float | None, bool]:
    present = any(_has(record, name) for name in _X_NAMES)
    present = present or any(_has(record, name) for name in _Y_NAMES)
    if not present:
        return (None, None, False)
    raw_x = _MISSING
    raw_y = _MISSING
    for name in _X_NAMES:
        if _has(record, name):
            raw_x = _field(record, name, None)
            break
    for name in _Y_NAMES:
        if _has(record, name):
            raw_y = _field(record, name, None)
            break
    if raw_x is _MISSING or raw_y is _MISSING:
        return (None, None, True)
    return (_as_float(raw_x), _as_float(raw_y), True)


def _parse_tuple_xy(record: Any) -> tuple[float | None, float | None]:
    for name in _XY_TUPLE_NAMES:
        if not _has(record, name):
            continue
        raw = _field(record, name, None)
        if raw is None or isinstance(raw, (str, bytes)):
            continue
        try:
            items = list(raw)
        except TypeError:
            continue
        if len(items) < 2:
            continue
        cand_x = _as_float(items[0])
        cand_y = _as_float(items[1])
        if cand_x is not None and cand_y is not None:
            return (cand_x, cand_y)
    return (None, None)


def _parse_record_xy(record: Any) -> tuple[float | None, float | None]:
    direct_x, direct_y, present = _parse_direct_xy(record)
    if present:
        if direct_x is not None and direct_y is not None:
            return (direct_x, direct_y)
        fallback = _parse_tuple_xy(record)
        if fallback[0] is not None and fallback[1] is not None:
            return fallback
        if direct_x is not None and direct_y is not None:
            return (direct_x, direct_y)
        return (None, None)
    return _parse_tuple_xy(record)


def _coerce_bound(value: Any) -> float | None:
    if value is None:
        return None
    number = _as_float(value)
    if number is None:
        return None
    return float(number)


def _in_bounds(x: float, y: float, width: float | None, height: float | None) -> bool:
    if width is not None and not (0 <= x < width):
        return False
    if height is not None and not (0 <= y < height):
        return False
    return True


def _coerce_positive_id(value: Any) -> int | None:
    number = _as_int(value)
    if number is None or number <= 0:
        return None
    return int(number)


def _province_part(record: Any) -> str:
    raw = _first_field(record, _PROVINCE_NAMES)
    if raw is _MISSING:
        return "?"
    pid = _coerce_positive_id(raw)
    return str(pid) if pid is not None else "?"


def _record_role(record: Any) -> str:
    review_raw = _first_field(record, _REVIEW_NAMES)
    provenance_raw = _first_field(record, _PROVENANCE_NAMES)
    review = ""
    if isinstance(review_raw, str):
        review = review_raw.strip().lower()
    provenance = ""
    if isinstance(provenance_raw, str):
        provenance = provenance_raw.strip().lower()
    if review in _REVIEW_STATUSES:
        return review
    if provenance in _GENERATED_PROVENANCES:
        return "generated"
    if provenance in _AUTHORED_PROVENANCES:
        return "authored"
    return "unreviewed"


def _classify_record(record: Any) -> str | None:
    if record is None or isinstance(record, (str, bytes, bool, int, float)):
        return None
    if isinstance(record, (list, tuple, set, frozenset)):
        return None
    if _has(record, "slot"):
        return "slot"
    if _has(record, "sea_province"):
        return "port"
    if _has(record, "building_type"):
        return "building"
    if _has(record, "region_id"):
        return "weather"
    return None


def _slot_key(record: Any, slot_index: int) -> str:
    return "slot:%s:%d" % (_province_part(record), int(slot_index))


def _port_key(record: Any) -> str:
    return "port:%s" % (_province_part(record),)


def _building_key(record: Any, building_type: str) -> str:
    raw_id = _field(record, "id", None)
    bid = _coerce_positive_id(raw_id)
    if bid is not None:
        return "building:%d" % (bid,)
    return "building:%s:%s" % (_province_part(record), building_type)


def _weather_key(record: Any, region_id: int) -> str:
    raw_id = _field(record, "id", None)
    wid = _coerce_positive_id(raw_id)
    if wid is not None:
        return "weather:%d" % (wid,)
    return "weather:region:%d" % (int(region_id),)


def _build_record_marker(
    record: Any, width: float | None, height: float | None
) -> PlacementOverlayMarker | None:
    kind = _classify_record(record)
    if kind is None:
        return None
    pos_x, pos_y = _parse_record_xy(record)
    if pos_x is None or pos_y is None:
        return None
    x = float(pos_x)
    y = float(pos_y)
    if not (isfinite(x) and isfinite(y)):
        return None
    if not _in_bounds(x, y, width, height):
        return None
    role = _record_role(record)
    if kind == "slot":
        slot_index = _as_int(_field(record, "slot", None))
        if slot_index is None:
            return None
        if not (_POSITION_SLOT_MIN <= slot_index <= _POSITION_SLOT_MAX):
            return None
        return PlacementOverlayMarker(
            kind="slot", key=_slot_key(record, slot_index), x=x, y=y, role=role
        )
    if kind == "port":
        return PlacementOverlayMarker(
            kind="port", key=_port_key(record), x=x, y=y, role=role
        )
    if kind == "building":
        raw_building = _field(record, "building_type", None)
        if not isinstance(raw_building, str) or not raw_building.strip():
            return None
        building_type = raw_building.strip()
        return PlacementOverlayMarker(
            kind="building",
            key=_building_key(record, building_type),
            x=x,
            y=y,
            role=role,
        )
    if kind == "weather":
        region_id = _coerce_positive_id(_field(record, "region_id", None))
        if region_id is None:
            return None
        return PlacementOverlayMarker(
            kind="weather",
            key=_weather_key(record, region_id),
            x=x,
            y=y,
            role=role,
        )
    return None


def _as_record_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, (str, bytes)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _parse_vp_entry(entry: Any, width: float | None, height: float | None) -> PlacementOverlayMarker | None:
    if entry is None or isinstance(entry, (str, bytes, bool, int, float)):
        if isinstance(entry, (int, float)) and not isinstance(entry, bool):
            return None
        if entry is None or isinstance(entry, (str, bytes, bool)):
            return None
    if isinstance(entry, Mapping):
        raw_pid = entry.get("province_id", entry.get("province", entry.get("pid")))
        pid = _coerce_positive_id(raw_pid)
        pos_x, pos_y = _parse_record_xy(entry)
        if pid is None or pos_x is None or pos_y is None:
            return None
        x = float(pos_x)
        y = float(pos_y)
        if not (isfinite(x) and isfinite(y)):
            return None
        if not _in_bounds(x, y, width, height):
            return None
        return PlacementOverlayMarker(
            kind="vp", key="vp:%d" % (pid,), x=x, y=y, role="vp"
        )
    if isinstance(entry, (list, tuple)) and not isinstance(entry, (str, bytes)):
        try:
            items = list(entry)
        except TypeError:
            return None
        if len(items) == 3:
            pid = _coerce_positive_id(items[0])
            x = _as_float(items[1])
            y = _as_float(items[2])
            if pid is None or x is None or y is None:
                return None
            fx = float(x)
            fy = float(y)
            if not (isfinite(fx) and isfinite(fy)):
                return None
            if not _in_bounds(fx, fy, width, height):
                return None
            return PlacementOverlayMarker(
                kind="vp", key="vp:%d" % (pid,), x=fx, y=fy, role="vp"
            )
        return None
    if isinstance(entry, (set, frozenset)):
        return None
    raw_pid = _first_field(entry, _PROVINCE_NAMES)
    if raw_pid is _MISSING:
        return None
    pid = _coerce_positive_id(raw_pid)
    pos_x, pos_y = _parse_record_xy(entry)
    if pid is None or pos_x is None or pos_y is None:
        return None
    x = float(pos_x)
    y = float(pos_y)
    if not (isfinite(x) and isfinite(y)):
        return None
    if not _in_bounds(x, y, width, height):
        return None
    return PlacementOverlayMarker(
        kind="vp", key="vp:%d" % (pid,), x=x, y=y, role="vp"
    )


def _finding_code(finding: Any) -> str:
    try:
        code = _field(finding, "code", None)
    except Exception:
        return ""
    if not isinstance(code, str):
        return ""
    return code.strip()


def _parse_pair(item: Any) -> tuple[float, float] | None:
    if item is None or isinstance(item, (str, bytes, bool, int, float)):
        return None
    if isinstance(item, Mapping):
        pos_x, pos_y = _parse_record_xy(item)
        if pos_x is None or pos_y is None:
            return None
        return (float(pos_x), float(pos_y))
    try:
        items = list(item)
    except TypeError:
        return None
    if len(items) != 2:
        return None
    x = _as_float(items[0])
    y = _as_float(items[1])
    if x is None or y is None:
        return None
    return (float(x), float(y))


def _collision_points_from_findings(
    findings: list[Any], width: float | None, height: float | None
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for finding in findings:
        if finding is None or isinstance(finding, (str, bytes, bool, int, float)):
            continue
        if _finding_code(finding) != "placement.collision":
            continue
        raw_coords = _field(finding, "coordinates", None)
        candidates: list[Any] = []
        if raw_coords is None:
            fallback_x, fallback_y = _parse_record_xy(finding)
            if fallback_x is not None and fallback_y is not None:
                candidates = [(fallback_x, fallback_y)]
            else:
                continue
        elif isinstance(raw_coords, (str, bytes)):
            continue
        else:
            try:
                candidates = list(raw_coords)
            except TypeError:
                continue
        for item in candidates:
            pair = _parse_pair(item)
            if pair is None:
                continue
            x, y = pair
            if not (isfinite(x) and isfinite(y)):
                continue
            if not _in_bounds(x, y, width, height):
                continue
            points.append((float(x), float(y)))
    return points


def build_placement_overlay_model(
    records: Any = (),
    *,
    vp_points: Any = (),
    findings: Any = (),
    width: Any = None,
    height: Any = None,
) -> PlacementOverlayModel:
    """Build a deterministic read-only overlay model.

    ``records`` holds duck-typed slot/port/building/weather objects or
    mappings. A record is a slot when ``slot`` exists, a port when
    ``sea_province`` exists, a building when ``building_type`` exists,
    and weather when ``region_id`` exists; anything else is skipped.
    Records with missing, non-finite, or (when bounds are given)
    out-of-bounds ``x``/``y`` coordinates are skipped, as are records
    with malformed kind identities (bad slot index, empty building
    type, or non-positive region id).

    ``vp_points`` entries are either ``(province_id, x, y)`` sequences
    or mappings/objects carrying ``province_id``/``x``/``y``.
    ``findings`` entries with code ``placement.collision`` contribute
    their valid ``coordinates`` pairs. Malformed coordinates are
    ignored safely.

    ``width``/``height`` are optional map bounds; when provided, only
    points with ``0 <= x < width`` and ``0 <= y < height`` are kept.
    Fractional coordinates are preserved verbatim, inputs are never
    mutated, and output markers are sorted by ``(kind, key, x, y)``
    while collision points are de-duplicated and sorted.
    """
    bound_width = _coerce_bound(width)
    bound_height = _coerce_bound(height)
    record_list = _as_record_list(records)
    vp_list = _as_record_list(vp_points)
    finding_list = _as_record_list(findings)

    markers: list[PlacementOverlayMarker] = []
    for record in record_list:
        try:
            marker = _build_record_marker(record, bound_width, bound_height)
        except Exception:
            continue
        if marker is not None:
            markers.append(marker)

    for entry in vp_list:
        try:
            marker = _parse_vp_entry(entry, bound_width, bound_height)
        except Exception:
            continue
        if marker is not None:
            markers.append(marker)

    try:
        raw_points = _collision_points_from_findings(
            finding_list, bound_width, bound_height
        )
    except Exception:
        raw_points = []
    unique_sorted = sorted(set(raw_points))
    for point in unique_sorted:
        markers.append(
            PlacementOverlayMarker(
                kind="collision",
                key="collision:%r:%r" % (float(point[0]), float(point[1])),
                x=float(point[0]),
                y=float(point[1]),
                role="collision",
            )
        )

    markers.sort(key=lambda item: (item.kind, item.key, item.x, item.y))
    return PlacementOverlayModel(
        markers=tuple(markers),
        collision_points=tuple(unique_sorted),
    )
