"""Adjacency and logistics validation slice (M3.3d).

Pure, non-mutating checks over in-memory province/tile rasters plus the
repository logistics managers.  The public entry point is
:func:`validate_logistics_references`, which returns a deterministic list
of :class:`domain.validation.ValidationFinding`.

Stable finding codes emitted here (all use layer ``logistics``):

- ``logistics.adjacency_endpoint``: adjacency endpoints, through
  provinces, coordinates, types, and rule references are missing or
  illegal.  Impassable entries must keep ``through_id``, coordinates,
  and rule names unset, mirroring ``AdjacencyEntry.to_csv_line``.
- ``logistics.adjacency_rule``: required provinces or icon provinces in
  adjacency rules do not resolve against the supplied province map.
- ``logistics.railway_route``: railway routes with fewer than two
  province IDs, illegal levels, unknown or illegal province IDs,
  revisited provinces (self-loops), non-adjacent consecutive
  provinces, impassable crossings, or water provinces.
- ``logistics.supply_node``: supply nodes with unknown provinces or
  illegal levels.
- ``logistics.port``: supply nodes sitting on water and adjacency-rule
  icons outside sea provinces.  Ports need coastal/sea access, so these
  are only reported when tile data allows a surface check.
- ``logistics.graph``: disconnected railway/supply components and
  supply nodes without railway reachability.
- ``logistics.duplicate_route``: identical railway routes defined more
  than once (either orientation counts as the same path).

Severity policy: invalid references, self-loops, illegal levels, and
duplicate routes are ``error``.  Disconnected components and unreachable
supply nodes are ``warning`` and waivable so intentional island or
overseas-convoy layouts can be accepted with a reason.

Manager arguments are duck-typed read-only views: any object exposing
``get_all()`` works, including the repository managers
(``AdjacencyManager``, ``AdjacencyRuleManager``, ``RailwayManager``,
``SupplyNodeManager``) and lightweight test fakes.  Absent managers are
a no-op.  Missing ``province_map`` disables existence, adjacency,
surface, and coordinate-bound checks while structural checks (levels,
lengths, types, duplicates, self-loops) still run.  ``tile_map`` only
enables surface/port checks when both rasters are 2-D and share a
shape.  ``country_mgr`` and ``profile`` are accepted for central-registry
call compatibility and currently produce no findings.

Findings are aggregated to at most one per code with sorted
``affected_ids`` and ``coordinates`` (``(x, y)`` pairs, capped) and are
returned in ``CODES`` order so repeated calls are byte-identical.  Inputs
are only read; arrays are inspected through ``numpy`` views and managers
are never mutated.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from domain.logistics_graph import analyze_logistics_graph
from domain.validation import ValidationFinding

try:
    from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
except Exception:  # pragma: no cover - fallback tile constants for tooling
    TILE_LAND = 1  # type: ignore[assignment]
    TILE_SEA = 2  # type: ignore[assignment]
    TILE_LAKE = 3  # type: ignore[assignment]

try:
    from domain.managers.railway import RailwayManager as _RailwayManager

    _RAILWAY_MAX_LEVEL = int(_RailwayManager.MAX_LEVEL)
except Exception:  # pragma: no cover - import-time fallback for tooling
    _RailwayManager = None  # type: ignore[assignment]
    _RAILWAY_MAX_LEVEL = 5

__all__ = ["CODES", "LAYER", "validate_logistics_references"]

LAYER = "logistics"

CODES = (
    "logistics.adjacency_endpoint",
    "logistics.adjacency_rule",
    "logistics.railway_route",
    "logistics.supply_node",
    "logistics.port",
    "logistics.graph",
    "logistics.duplicate_route",
)

_COORD_LIMIT = 8
_EVIDENCE_DETAILS = 6
_GRAPH_AFFECTED_LIMIT = 64
_LEGAL_ADJACENCY_TYPES = ("sea", "impassable")
_WATER_SURFACES = ("sea", "lake")


def _resolve_wrap_horizontal(wrap_horizontal=None, profile=None):
    if wrap_horizontal is not None:
        return bool(wrap_horizontal)
    if profile is not None:
        try:
            return bool(profile.dimensions.wrap_horizontal)
        except Exception:
            pass
    return True


def _as_int(value: Any) -> int | None:
    """Return ``value`` as an int, or None when it is not integer-like."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        try:
            number = float(value)
        except (OverflowError, ValueError):
            return None
        if number.is_integer():
            return int(number)
        return None
    return None


def _short(value: Any, limit: int = 24) -> str:
    """Render ``value`` compactly for evidence strings."""
    try:
        text = repr(value)
    except Exception:
        text = "<unrepresentable>"
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def _field(entry: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from dataclass-like or mapping-like manager entries."""
    if isinstance(entry, Mapping):
        try:
            return entry.get(name, default)
        except Exception:
            return default
    try:
        return getattr(entry, name, default)
    except Exception:
        return default


def _safe_get_all(manager: Any) -> list[Any]:
    """Return ``manager.get_all()`` as a list, or [] when unavailable."""
    if manager is None:
        return []
    func = getattr(manager, "get_all", None)
    if not callable(func):
        return []
    try:
        entries = func()
    except Exception:
        return []
    if entries is None:
        return []
    try:
        return list(entries)
    except TypeError:
        return []


def _province_id_set(province_map: Any) -> set[int] | None:
    """Return positive province IDs, or None when the map is unusable."""
    if province_map is None:
        return None
    try:
        arr = np.asarray(province_map)
    except Exception:
        return None
    if arr.ndim == 0:
        return None
    try:
        values = arr.ravel().tolist()
    except Exception:
        return None
    known: set[int] = set()
    for value in values:
        pid = _as_int(value)
        if pid is not None and pid > 0:
            known.add(pid)
    return known


def _raster_dims(province_map: Any, tile_map: Any) -> tuple[int, int] | None:
    """Return (height, width) from the first usable 2-D raster."""
    for candidate in (province_map, tile_map):
        if candidate is None:
            continue
        try:
            arr = np.asarray(candidate)
        except Exception:
            continue
        if arr.ndim == 2 and int(arr.shape[0]) > 0 and int(arr.shape[1]) > 0:
            return (int(arr.shape[0]), int(arr.shape[1]))
    return None


def _first_coordinates(province_map: Any) -> dict[int, tuple[int, int]]:
    """Map every positive province ID to its first (x, y) pixel."""
    try:
        prov = np.asarray(province_map)
    except Exception:
        return {}
    if prov.ndim != 2 or prov.size == 0:
        return {}
    width = int(prov.shape[1])
    flat = prov.ravel()
    first: dict[int, int] = {}
    for index in range(int(flat.shape[0])):
        try:
            pid = int(flat[index])
        except (TypeError, ValueError):
            continue
        if pid > 0 and pid not in first:
            first[pid] = int(index)
    return {pid: (index % width, index // width) for pid, index in first.items()}


def _map_adjacent_pairs(province_map: Any, wrap_horizontal: bool = True) -> set[tuple[int, int]] | None:
    """Return unordered 4-connected province pairs, including the wrap seam."""
    try:
        prov = np.asarray(province_map)
    except Exception:
        return None
    if prov.ndim != 2 or int(prov.shape[0]) == 0 or int(prov.shape[1]) == 0:
        return None
    pairs: set[tuple[int, int]] = set()

    def _absorb(mask_a: np.ndarray, mask_b: np.ndarray) -> None:
        different = mask_a != mask_b
        if not bool(np.any(different)):
            return
        try:
            stacked = np.stack((mask_a[different], mask_b[different]), axis=1)
            unique = np.unique(stacked, axis=0)
        except Exception:
            return
        for row in unique.tolist():
            first = _as_int(row[0])
            second = _as_int(row[1])
            if first is None or second is None:
                continue
            if first <= 0 or second <= 0 or first == second:
                continue
            pairs.add((min(first, second), max(first, second)))

    if int(prov.shape[0]) > 1:
        _absorb(prov[:-1, :], prov[1:, :])
    if int(prov.shape[1]) > 1:
        _absorb(prov[:, :-1], prov[:, 1:])
        if wrap_horizontal:
            _absorb(prov[:, 0], prov[:, -1])
    return pairs


def _surface_table(tile_map: Any, province_map: Any) -> dict[int, str] | None:
    """Map positive province IDs to land/sea/lake/mixed by strict majority."""
    try:
        tile = np.asarray(tile_map)
        prov = np.asarray(province_map)
    except Exception:
        return None
    if tile.ndim != 2 or prov.ndim != 2:
        return None
    if tile.shape != prov.shape or prov.size == 0:
        return None
    try:
        land_v, sea_v, lake_v = int(TILE_LAND), int(TILE_SEA), int(TILE_LAKE)
    except (TypeError, ValueError):
        land_v, sea_v, lake_v = 1, 2, 3
    try:
        flat_pm = prov.ravel().astype(np.int64, copy=False)
        flat_tm = tile.ravel().astype(np.int64, copy=False)
    except (TypeError, ValueError):
        return None
    try:
        valid = flat_pm > 0
        if not bool(np.any(valid)):
            return {}
        pm_valid = flat_pm[valid]
        tm_valid = flat_tm[valid]
        size = int(pm_valid.max()) + 1
        total = np.bincount(pm_valid, minlength=size)
        land = np.bincount(pm_valid, weights=(tm_valid == land_v).astype(np.int64), minlength=size)
        sea = np.bincount(pm_valid, weights=(tm_valid == sea_v).astype(np.int64), minlength=size)
        lake = np.bincount(pm_valid, weights=(tm_valid == lake_v).astype(np.int64), minlength=size)
    except Exception:
        return None
    table: dict[int, str] = {}
    for pid in range(1, size):
        count = int(total[pid])
        if count <= 0:
            continue
        land_n, sea_n, lake_n = int(land[pid]), int(sea[pid]), int(lake[pid])
        if land_n * 2 > count:
            table[pid] = "land"
        elif sea_n * 2 > count:
            table[pid] = "sea"
        elif lake_n * 2 > count:
            table[pid] = "lake"
        else:
            table[pid] = "mixed"
    return table


def _rule_name_set(adjacency_rule_mgr: Any) -> set[str] | None:
    """Return known adjacency-rule names, or None when no manager is given."""
    if adjacency_rule_mgr is None:
        return None
    func = getattr(adjacency_rule_mgr, "names", None)
    if callable(func):
        try:
            names = list(func())
        except Exception:
            names = None
        if names is not None:
            return set(str(n) for n in names if isinstance(n, str) and n)
    entries = _safe_get_all(adjacency_rule_mgr)
    known: set[str] = set()
    for rule in entries:
        name = _field(rule, "name", "")
        if isinstance(name, str) and name:
            known.add(name)
    return known


def _rule_entries_sorted(adjacency_rule_mgr: Any) -> list[Any]:
    """Return rule entries sorted by name for deterministic output."""
    entries = _safe_get_all(adjacency_rule_mgr)
    try:
        return sorted(entries, key=lambda r: str(_field(r, "name", "")))
    except Exception:
        return entries


def _evidence(details: list[str]) -> str:
    """Join evidence details with a deterministic truncation marker."""
    if len(details) <= _EVIDENCE_DETAILS:
        return "; ".join(details)
    head = "; ".join(details[:_EVIDENCE_DETAILS])
    return "%s; ...(+%d more)" % (head, len(details) - _EVIDENCE_DETAILS)


def _coords_for(
    affected: set[int],
    first_coords: dict[int, tuple[int, int]],
    extra: set[tuple[int, int]] | None = None,
) -> tuple[tuple[int, int], ...]:
    """Assemble sorted, capped (x, y) coordinates for a finding."""
    points: set[tuple[int, int]] = set(extra) if extra else set()
    for pid in affected:
        if pid in first_coords:
            points.add(first_coords[pid])
    return tuple(sorted(points)[:_COORD_LIMIT])


def validate_logistics_references(
    province_map: Any,
    tile_map: Any | None = None,
    *,
    adjacency_mgr: Any | None = None,
    railway_mgr: Any | None = None,
    supply_mgr: Any | None = None,
    adjacency_rule_mgr: Any | None = None,
    country_mgr: Any | None = None,
    profile: Any | None = None,
    wrap_horizontal: bool | None = None,
) -> list[ValidationFinding]:
    """Validate adjacency, railway, supply, port, and graph references.

    ``province_map`` supplies the known province IDs and map geometry;
    ``tile_map`` additionally enables surface/port checks when both
    rasters are 2-D with equal shapes.  Managers are read through
    ``get_all()`` and never mutated.  ``country_mgr`` and ``profile``
    are accepted for central-registry call compatibility and currently
    produce no findings.  Returns findings in ``CODES`` order.
    """
    _ = country_mgr
    _wrap = _resolve_wrap_horizontal(wrap_horizontal, profile)
    findings: list[ValidationFinding] = []

    known_ids = _province_id_set(province_map)
    dims = _raster_dims(province_map, tile_map)
    width = dims[1] if dims is not None else None
    height = dims[0] if dims is not None else None
    first_coords = _first_coordinates(province_map) if province_map is not None else {}
    adjacent = _map_adjacent_pairs(province_map, _wrap) if province_map is not None else None
    surfaces: dict[int, str] | None = None
    if tile_map is not None and province_map is not None:
        surfaces = _surface_table(tile_map, province_map)
    rule_names = _rule_name_set(adjacency_rule_mgr)

    adjacency_entries = _safe_get_all(adjacency_mgr)
    railway_entries = _safe_get_all(railway_mgr)
    supply_nodes = _safe_get_all(supply_mgr)
    rule_entries = _rule_entries_sorted(adjacency_rule_mgr)

    impassable_pairs: set[tuple[int, int]] = set()
    for raw in adjacency_entries:
        if _field(raw, "type", "") != "impassable":
            continue
        first = _as_int(_field(raw, "from_id", None))
        second = _as_int(_field(raw, "to_id", None))
        if first is not None and second is not None and first > 0 and second > 0:
            impassable_pairs.add((min(first, second), max(first, second)))

    endpoint_details: list[str] = []
    endpoint_ids: set[int] = set()
    endpoint_points: set[tuple[int, int]] = set()
    endpoint_bad_entries: set[int] = set()

    def _note_endpoint(index: int, detail: str, pids: list[Any]) -> None:
        endpoint_details.append("entry#%d %s" % (index, detail))
        endpoint_bad_entries.add(index)
        for raw_pid in pids:
            pid = _as_int(raw_pid)
            if pid is not None and pid > 0:
                endpoint_ids.add(pid)

    for index, raw in enumerate(adjacency_entries):
        frm = _as_int(_field(raw, "from_id", None))
        to = _as_int(_field(raw, "to_id", None))
        typ = _field(raw, "type", "")
        through_raw = _field(raw, "through_id", -1)
        through = _as_int(through_raw)
        rule = _field(raw, "rule_name", "")
        type_text = typ if isinstance(typ, str) else None
        if type_text not in _LEGAL_ADJACENCY_TYPES:
            _note_endpoint(index, "has illegal type %s" % _short(typ),
                           [_field(raw, "from_id", None), _field(raw, "to_id", None)])
        if frm is None or frm <= 0:
            _note_endpoint(index, "has illegal from_id %s" % _short(_field(raw, "from_id", None)), [])
        elif known_ids is not None and frm not in known_ids:
            _note_endpoint(index, "from_id %d is unknown" % frm, [frm])
        if to is None or to <= 0:
            _note_endpoint(index, "has illegal to_id %s" % _short(_field(raw, "to_id", None)), [])
        elif known_ids is not None and to not in known_ids:
            _note_endpoint(index, "to_id %d is unknown" % to, [to])
        if frm is not None and to is not None and frm > 0 and to > 0 and frm == to:
            _note_endpoint(index, "is a self-loop on province %d" % frm, [frm])
        if through is None or through < -1:
            _note_endpoint(index, "has illegal through_id %s" % _short(through_raw),
                           [_field(raw, "from_id", None), _field(raw, "to_id", None)])
        elif type_text == "impassable":
            if through != -1:
                _note_endpoint(index, "impassable must use through_id -1, got %d" % through,
                               [_field(raw, "from_id", None), _field(raw, "to_id", None), through])
        elif through != -1:
            if through <= 0:
                _note_endpoint(index, "has illegal through_id %d" % through,
                               [_field(raw, "from_id", None), _field(raw, "to_id", None)])
            else:
                if frm is not None and through == frm:
                    _note_endpoint(index, "through_id %d equals from_id" % through, [through])
                if to is not None and through == to:
                    _note_endpoint(index, "through_id %d equals to_id" % through, [through])
                if known_ids is not None and through not in known_ids:
                    _note_endpoint(index, "through_id %d is unknown" % through, [through])
        if not isinstance(rule, str):
            _note_endpoint(index, "has illegal rule_name %s" % _short(rule),
                           [_field(raw, "from_id", None), _field(raw, "to_id", None)])
        elif rule:
            if type_text == "impassable":
                _note_endpoint(index, "impassable must not name rule %s" % _short(rule),
                               [_field(raw, "from_id", None), _field(raw, "to_id", None)])
            elif rule_names is not None and rule not in rule_names:
                _note_endpoint(index, "rule %s is unknown" % _short(rule),
                               [_field(raw, "from_id", None), _field(raw, "to_id", None)])
        coord_values = [
            _as_int(_field(raw, "start_x", -1)),
            _as_int(_field(raw, "start_y", -1)),
            _as_int(_field(raw, "stop_x", -1)),
            _as_int(_field(raw, "stop_y", -1)),
        ]
        if any(v is None for v in coord_values):
            _note_endpoint(index, "has illegal coordinates",
                           [_field(raw, "from_id", None), _field(raw, "to_id", None)])
        elif type_text == "impassable":
            if any(v != -1 for v in coord_values):
                _note_endpoint(index, "impassable must use coordinates -1",
                               [_field(raw, "from_id", None), _field(raw, "to_id", None)])
        else:
            pairs = (("start", coord_values[0], coord_values[1]), ("stop", coord_values[2], coord_values[3]))
            for label, raw_x, raw_y in pairs:
                assert raw_x is not None and raw_y is not None
                if (raw_x == -1) != (raw_y == -1):
                    _note_endpoint(index, "%s coordinates are partially unset" % label,
                                   [_field(raw, "from_id", None), _field(raw, "to_id", None)])
                elif raw_x != -1 and raw_y != -1:
                    if raw_x < -1 or raw_y < -1:
                        _note_endpoint(index, "%s coordinates are illegal" % label,
                                       [_field(raw, "from_id", None), _field(raw, "to_id", None)])
                    elif width is not None and height is not None:
                        if not (0 <= raw_x < width and 0 <= raw_y < height):
                            _note_endpoint(index, "%s coordinates (%d, %d) are out of bounds" % (label, raw_x, raw_y),
                                           [_field(raw, "from_id", None), _field(raw, "to_id", None)])
                        else:
                            endpoint_points.add((raw_x, raw_y))
    if endpoint_details:
        findings.append(
            ValidationFinding(
                code="logistics.adjacency_endpoint",
                severity="error",
                message="%d adjacency entries have invalid endpoints, types, coordinates, or rule references" % len(endpoint_bad_entries),
                layer=LAYER,
                affected_ids=tuple(sorted(endpoint_ids)),
                coordinates=_coords_for(endpoint_ids, first_coords, endpoint_points),
                evidence=_evidence(endpoint_details),
            )
        )

    rule_details: list[str] = []
    rule_ids: set[int] = set()
    for raw in rule_entries:
        name = _field(raw, "name", "")
        label = _short(name) if isinstance(name, str) and name else "<unnamed>"
        required = _field(raw, "required_provinces", [])
        if required is None:
            required = []
        try:
            if isinstance(required, (str, bytes)):
                raise TypeError("required_provinces must be a sequence of IDs")
            required_items = list(required)
        except TypeError:
            rule_details.append("rule=%s has malformed required_provinces %s" % (label, _short(required)))
            required_items = []
        for value in required_items:
            pid = _as_int(value)
            if pid is None or pid <= 0:
                rule_details.append("rule=%s requires illegal province %s" % (label, _short(value)))
            elif known_ids is not None and pid not in known_ids:
                rule_details.append("rule=%s requires unknown province %d" % (label, pid))
                rule_ids.add(pid)
        icon = _as_int(_field(raw, "icon_province", -1))
        if icon is None or icon < -1:
            rule_details.append("rule=%s has illegal icon_province %s" % (label, _short(_field(raw, "icon_province", -1))))
        elif icon > 0:
            if known_ids is not None and icon not in known_ids:
                rule_details.append("rule=%s icon province %d is unknown" % (label, icon))
                rule_ids.add(icon)
    if rule_details:
        findings.append(
            ValidationFinding(
                code="logistics.adjacency_rule",
                severity="error",
                message="%d adjacency-rule province references do not resolve" % len(rule_details),
                layer=LAYER,
                affected_ids=tuple(sorted(rule_ids)),
                coordinates=_coords_for(rule_ids, first_coords),
                evidence=_evidence(rule_details),
            )
        )

    railway_details: list[str] = []
    railway_ids: set[int] = set()
    railway_bad_entries: set[int] = set()

    def _note_railway(index: int, detail: str, pids: list[int]) -> None:
        railway_details.append("entry#%d %s" % (index, detail))
        railway_bad_entries.add(index)
        for pid in pids:
            if pid > 0:
                railway_ids.add(pid)

    for index, raw in enumerate(railway_entries):
        level = _as_int(_field(raw, "level", None))
        level_ok = level is not None and 1 <= level <= int(_RAILWAY_MAX_LEVEL)
        raw_ids = _field(raw, "province_ids", [])
        if raw_ids is None or isinstance(raw_ids, (str, bytes)):
            if not level_ok:
                _note_railway(index, "has illegal level %s" % _short(_field(raw, "level", None)), [])
            _note_railway(index, "has malformed province_ids %s" % _short(raw_ids), [])
            continue
        try:
            ids_list = list(raw_ids)
        except TypeError:
            if not level_ok:
                _note_railway(index, "has illegal level %s" % _short(_field(raw, "level", None)), [])
            _note_railway(index, "has malformed province_ids %s" % _short(raw_ids), [])
            continue
        early_ids = [pid for pid in (_as_int(v) for v in ids_list) if pid is not None and pid > 0]
        if not level_ok:
            _note_railway(index, "has illegal level %s" % _short(_field(raw, "level", None)), early_ids)
        if len(ids_list) < 2:
            _note_railway(index, "holds fewer than two province IDs", [])
        parsed: list[int] = []
        for value in ids_list:
            pid = _as_int(value)
            if pid is None or pid <= 0:
                _note_railway(index, "holds illegal province id %s" % _short(value), [])
            else:
                parsed.append(pid)
                if known_ids is not None and pid not in known_ids:
                    _note_railway(index, "references unknown province %d" % pid, [pid])
        seen: set[int] = set()
        for pid in parsed:
            if pid in seen:
                _note_railway(index, "revisits province %d (self-loop)" % pid, [pid])
                break
            seen.add(pid)
        water_hits: set[int] = set()
        for first, second in zip(parsed, parsed[1:]):
            if first == second:
                continue
            pair = (min(first, second), max(first, second))
            if adjacent is not None and pair not in adjacent:
                _note_railway(index, "provinces %d and %d are not adjacent" % (first, second), [first, second])
            if pair in impassable_pairs:
                _note_railway(index, "provinces %d and %d cross an impassable adjacency" % (first, second), [first, second])
            if surfaces is not None:
                for pid in (first, second):
                    surf = surfaces.get(pid)
                    if surf in _WATER_SURFACES or surf == 'mixed':
                        water_hits.add(pid)
        for pid in sorted(water_hits):
            surface = surfaces.get(pid, "?") if surfaces is not None else "?"
            if surface == 'mixed':
                _note_railway(index, 'province %d is not land (surface=%s)' % (pid, surface), [pid])
            else:
                _note_railway(index, "province %d is water (surface=%s)" % (pid, surface), [pid])
    if railway_details:
        findings.append(
            ValidationFinding(
                code="logistics.railway_route",
                severity="error",
                message="%d railway routes are invalid" % len(railway_bad_entries),
                layer=LAYER,
                affected_ids=tuple(sorted(railway_ids)),
                coordinates=_coords_for(railway_ids, first_coords),
                evidence=_evidence(railway_details),
            )
        )

    supply_details: list[str] = []
    supply_ids: set[int] = set()
    supply_bad_count = 0
    for raw in supply_nodes:
        pid = _as_int(_field(raw, "province_id", None))
        level = _as_int(_field(raw, "level", None))
        broken = False
        if pid is None or pid <= 0:
            supply_details.append("supply node has illegal province %s" % _short(_field(raw, "province_id", None)))
            broken = True
        elif known_ids is not None and pid not in known_ids:
            supply_details.append("supply node references unknown province %d" % pid)
            supply_ids.add(pid)
            broken = True
        else:
            pass
        if level is None or level < 1:
            if pid is not None and pid > 0:
                supply_details.append("supply node %d has illegal level %s" % (pid, _short(_field(raw, "level", None))))
                supply_ids.add(pid)
            else:
                supply_details.append("supply node has illegal level %s" % _short(_field(raw, "level", None)))
            broken = True
        if broken:
            supply_bad_count += 1
    if supply_details:
        findings.append(
            ValidationFinding(
                code="logistics.supply_node",
                severity="error",
                message="%d supply nodes are invalid" % supply_bad_count,
                layer=LAYER,
                affected_ids=tuple(sorted(supply_ids)),
                coordinates=_coords_for(supply_ids, first_coords),
                evidence=_evidence(supply_details),
            )
        )

    port_details: list[str] = []
    port_ids: set[int] = set()
    if surfaces is not None:
        for raw in supply_nodes:
            pid = _as_int(_field(raw, "province_id", None))
            if pid is None or pid <= 0:
                continue
            surface = surfaces.get(pid)
            if surface in _WATER_SURFACES:
                port_details.append("supply node %d sits on water (surface=%s)" % (pid, surface))
                port_ids.add(pid)
        for raw in rule_entries:
            name = _field(raw, "name", "")
            label = _short(name) if isinstance(name, str) and name else "<unnamed>"
            icon = _as_int(_field(raw, "icon_province", -1))
            if icon is None or icon <= 0:
                continue
            surface = surfaces.get(icon)
            if surface is not None and surface != "sea":
                port_details.append("rule=%s icon province %d is not a sea province (surface=%s)" % (label, icon, surface))
                port_ids.add(icon)
    if port_details:
        findings.append(
            ValidationFinding(
                code="logistics.port",
                severity="error",
                message="%d port or icon placements lack sea access" % len(port_details),
                layer=LAYER,
                affected_ids=tuple(sorted(port_ids)),
                coordinates=_coords_for(port_ids, first_coords),
                evidence=_evidence(port_details),
            )
        )

    graph = analyze_logistics_graph(
        railway_entries,
        supply_nodes,
        known_provinces=known_ids,
    )
    if graph.supply_provinces and not graph.railway_provinces and not supply_details:
        missing_ids = tuple(graph.supply_off_rail)
        findings.append(
            ValidationFinding(
                code="logistics.graph",
                severity="warning",
                message="supply nodes have no railway graph",
                layer=LAYER,
                affected_ids=missing_ids[:_GRAPH_AFFECTED_LIMIT],
                coordinates=_coords_for(set(missing_ids[:_GRAPH_AFFECTED_LIMIT]), first_coords),
                evidence="components=%d; off_rail_supply=%s; missing_railway_graph=true"
                % (graph.component_count, ",".join(str(pid) for pid in missing_ids[:12])),
                waivable=True,
            )
        )
    elif graph.components and graph.component_count > 1:
        largest = set(graph.components[0].provinces)
        outside = sorted(set(graph.vertices) - largest)
        off_rail = list(graph.supply_off_rail)
        sizes = sorted((len(component.provinces) for component in graph.components), reverse=True)
        size_text = "+".join(str(n) for n in sizes[:12])
        if len(sizes) > 12:
            size_text += "+...(+%d more)" % (len(sizes) - 12)
        parts = ["components=%d" % graph.component_count, "sizes=%s" % size_text]
        if off_rail:
            shown = ",".join(str(pid) for pid in off_rail[:12])
            if len(off_rail) > 12:
                shown += ",..."
            parts.append("off_rail_supply=%s" % shown)
        shown_out = ",".join(str(pid) for pid in outside[:12])
        if len(outside) > 12:
            shown_out += ",..."
        parts.append("outside_main=%s" % shown_out)
        findings.append(
            ValidationFinding(
                code="logistics.graph",
                severity="warning",
                message="logistics graph has %d disconnected components" % graph.component_count,
                layer=LAYER,
                affected_ids=tuple(outside[:_GRAPH_AFFECTED_LIMIT]),
                coordinates=_coords_for(set(outside[:_GRAPH_AFFECTED_LIMIT]), first_coords),
                evidence="; ".join(parts) + "; affected_total=%d" % len(outside),
                waivable=True,
            )
        )

    duplicate_details: list[str] = []
    duplicate_ids: set[int] = set()
    routes_by_key: dict[tuple[int, ...], list[int]] = {}
    routes_meta: dict[tuple[int, ...], list[tuple[int, Any]]] = {}
    for index, raw in enumerate(railway_entries):
        raw_ids = _field(raw, "province_ids", [])
        if raw_ids is None or isinstance(raw_ids, (str, bytes)):
            continue
        try:
            ids_list = list(raw_ids)
        except TypeError:
            continue
        if len(ids_list) < 2:
            continue
        parsed: list[int] = []
        usable = True
        for value in ids_list:
            pid = _as_int(value)
            if pid is None or pid <= 0:
                usable = False
                break
            parsed.append(pid)
        if not usable:
            continue
        path = tuple(parsed)
        key = min(path, path[::-1])
        routes_by_key.setdefault(key, []).append(index)
        routes_meta.setdefault(key, []).append((index, _field(raw, "level", "?")))
    for key in sorted(routes_by_key):
        indices = routes_by_key[key]
        if len(indices) < 2:
            continue
        path_text = "-".join(str(pid) for pid in key)
        entries_text = ",".join(str(i) for i in sorted(indices))
        levels = sorted({_short(level) for _, level in routes_meta[key]})
        duplicate_details.append("path=%s; occurrences=%d; entries=%s; levels=%s" % (path_text, len(indices), entries_text, ",".join(levels)))
        duplicate_ids.update(key)
    if duplicate_details:
        findings.append(
            ValidationFinding(
                code="logistics.duplicate_route",
                severity="error",
                message="%d railway paths are defined more than once" % len(duplicate_details),
                layer=LAYER,
                affected_ids=tuple(sorted(duplicate_ids)),
                coordinates=_coords_for(duplicate_ids, first_coords),
                evidence=_evidence(duplicate_details),
            )
        )

    return findings
