"""Standalone placement validation slice (M3.3e).

Pure, non-mutating checks over in-memory province/tile rasters plus
read-only placement records. The public entry point is
:func:`validate_placement_references`, which returns a deterministic list
of :class:`domain.validation.ValidationFinding`.

The generic entry point stays dependency-free and accepts duck-typed records
instead of manager types.  A separate manager-backed weather entry point
extends the same contract for containment and spacing without mutating the
manager.  Every entry may be a mapping or a dataclass-like object; unknown
extra fields are preserved by being ignored.

Accepted record shapes (all fields optional unless noted):

- Placement, position, and building entries share one transform shape:
  province (province_id|province|pid|provinceId), state
  (state_id|state|sid|stateId), building (building_type|type|building
  |kind), coordinates in raster pixel space (origin top-left,
  0 <= x < W, 0 <= y < H) via x|pos_x|cx|px|col|hoi4_x|map_x paired
  with y|pos_y|cy|py|row|hoi4_z|hoi4_y|map_y|z, or a tuple field
  position|coords|xy|pos|transform|coord|point holding (x, y).
  HOI4 bottom-origin values must be converted by the caller.
  Sea connection for ports via sea_province|sea_id|sea|adjacent_sea
  |sea_pid|connected_sea. Provenance via provenance|origin|source
  |status|review|review_status|generation|phase plus boolean flags
  fallback|is_fallback|fallback_position|is_generated|generated
  |unreviewed|is_unreviewed|proposal|is_proposal. Optional declared
  Fallback flags accept explicit boolean-like values (true/1/yes/y/t/on,
  non-zero integers, True) and canonical fallback provenance values. Arbitrary strings are ignored.
  Exact duplicate and repeated-centroid use exact coordinate identity;
  near collisions remain distance based. Ports with missing, illegal, or
  unknown provinces report placement.port coastal/sea validation cannot succeed.
  surface via surface|surface_type|terrain|expected_surface.
  Rotation, height, slot, index, id and other keys are ignored.
- Weather entries use the same coordinate convention plus region
  (region_id|strategic_region_id|region|rid|id); size and type are
  ignored. Optional province hints are evidence only.
- State and strategic-region managers are read-only views: repository
  managers with states|_states or regions|_regions mappings, plain
  mappings such as {sid: [pids]}, or objects exposing get_all() with
  id plus provinces|province_ids. Absent managers disable those checks.

Stable codes (layer placement): placement.coordinate, placement.building,
placement.port, placement.collision, placement.fallback,
placement.weather. Coordinate/building/port/weather are error.
Collision is warning waivable. Fallback is warning waivable while
lifecycle is draft-like, otherwise blocker not waivable.
Findings aggregate to one per code in CODES order with sorted capped
ids and coordinates. No filesystem or Qt access.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import math

import numpy as np

from domain.validation import ValidationFinding

try:
    from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
except Exception:
    TILE_LAND = 1  # type: ignore[assignment]
    TILE_SEA = 2  # type: ignore[assignment]
    TILE_LAKE = 3  # type: ignore[assignment]

try:
    from data.constants import VALID_3D_BUILDING_TYPES as _VALID_3D_TYPES
except Exception:
    _VALID_3D_TYPES = frozenset()  # type: ignore[assignment]

__all__ = [
    "CODES",
    "LAYER",
    "MANAGER_COMPLETENESS_CODES",
    "validate_manager_placement_completeness",
    "validate_manager_weather_positions",
    "validate_placement_references",
]

LAYER = "placement"

CODES = (
    "placement.coordinate",
    "placement.building",
    "placement.port",
    "placement.collision",
    "placement.fallback",
    "placement.weather",
)

MANAGER_COMPLETENESS_CODES = (
    "placement.completeness",
    "placement.review",
)

_COORD_LIMIT = 8
_AFFECTED_LIMIT = 64
_EVIDENCE_DETAILS = 6
_WRITER_REQUIRED_STATE_ENTITIES = (
    "arms_factory",
    "industrial_complex",
    "air_base",
    "anti_air_building",
    "bunker",
    "fuel_silo",
    "radar_station",
    "nuclear_reactor_spawn",
    "rocket_site_spawn",
    "synthetic_refinery",
    "supply_node",
)
_WRITER_COASTAL_STATE_ENTITIES = ("dockyard", "coastal_bunker")

_PORT_TYPES = frozenset({
    "dockyard",
    "coastal_bunker",
    "naval_base",
    "naval_base_spawn",
    "floating_harbor",
})
_SEA_REQUIRED_TYPES = frozenset({"naval_base", "naval_base_spawn"})

_FALLBACK_PROVENANCE = frozenset({
    "fallback",
    "generated",
    "proposal",
    "unreviewed",
    "auto",
    "centroid",
    "default",
    "centroid_fallback",
    "fallback_centroid",
    "generated_proposal",
    "unreviewed_generated",
    "auto_generated",
})

_MISSING = object()

_X_NAMES = ("x", "pos_x", "cx", "px", "col", "hoi4_x", "map_x")
_Y_NAMES = ("y", "pos_y", "cy", "py", "row", "hoi4_z", "hoi4_y", "map_y", "z")
_XY_TUPLE_NAMES = ("position", "coords", "xy", "pos", "transform", "coord", "point")
_PROVINCE_NAMES = ("province_id", "province", "pid", "provinceId")
_STATE_NAMES = ("state_id", "state", "sid", "stateId")
_BUILDING_NAMES = ("building_type", "type", "building", "kind")
_SEA_NAMES = ("sea_province", "sea_id", "sea", "adjacent_sea", "sea_pid", "connected_sea")
_PROVENANCE_NAMES = ("provenance", "origin", "source", "status", "review", "review_status", "generation", "phase")
_FALLBACK_FLAG_NAMES = (
    "fallback",
    "is_fallback",
    "fallback_position",
    "is_generated",
    "generated",
    "unreviewed",
    "is_unreviewed",
    "proposal",
    "is_proposal",
)
_SURFACE_NAMES = ("surface", "surface_type", "terrain", "expected_surface")
_REGION_NAMES = ("region_id", "strategic_region_id", "region", "rid", "id")


def _resolve_wrap_horizontal(wrap_horizontal=None, profile=None) -> bool:
    if wrap_horizontal is not None:
        return bool(wrap_horizontal)
    if profile is not None:
        try:
            return bool(profile.dimensions.wrap_horizontal)
        except Exception:
            pass
        try:
            if isinstance(profile, Mapping):
                dims = profile.get("dimensions", None)
                if isinstance(dims, Mapping) and "wrap_horizontal" in dims:
                    return bool(dims.get("wrap_horizontal"))
        except Exception:
            pass
    return True


def _is_strict_lifecycle(lifecycle: Any) -> bool:
    try:
        text = str(lifecycle if lifecycle is not None else "draft").strip().lower()
    except Exception:
        return False
    if not text:
        return False
    if text.startswith("draft"):
        return False
    return True


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        try:
            number = float(value)
        except (OverflowError, ValueError):
            return None
        if math.isfinite(number) and number.is_integer():
            return int(number)
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                number = float(text)
            except ValueError:
                return None
            if math.isfinite(number) and number.is_integer():
                return int(number)
            return None
    return None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, np.integer)):
        try:
            number = float(int(value))
        except (OverflowError, ValueError):
            return None
        return number if math.isfinite(number) else None
    if isinstance(value, (float, np.floating)):
        try:
            number = float(value)
        except (OverflowError, ValueError):
            return None
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _short(value: Any, limit: int = 24) -> str:
    try:
        text = repr(value)
    except Exception:
        text = object.__repr__(value)
    if len(text) > limit:
        return text[:limit] + "..."
    return text
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


def _field_present(record: Any, name: str) -> bool:
    if isinstance(record, Mapping):
        try:
            return name in record
        except Exception:
            return False
    try:
        return hasattr(record, name)
    except Exception:
        return False


def _first_present(record: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        if _field_present(record, name):
            return _field(record, name, None)
    return _MISSING


def _safe_entries(entries: Any) -> list[Any]:
    if entries is None:
        return []
    if isinstance(entries, Mapping):
        return [entries]
    if isinstance(entries, (str, bytes)):
        return [entries]
    try:
        return list(entries)
    except TypeError:
        return [entries]


def _is_malformed_record(record: Any) -> bool:
    if record is None:
        return True
    if isinstance(record, (str, bytes, bool, int, float, np.integer, np.floating)):
        return True
    if isinstance(record, (list, tuple, set, frozenset)):
        return True
    return False


def _parse_xy(record: Any) -> tuple[float | None, float | None, bool]:
    present = False
    for name in _X_NAMES:
        if _field_present(record, name):
            present = True
            break
    if not present:
        for name in _Y_NAMES:
            if _field_present(record, name):
                present = True
                break
    if not present:
        for name in _XY_TUPLE_NAMES:
            if _field_present(record, name):
                present = True
                break
    if not present:
        return (None, None, False)
    raw_x = None
    raw_y = None
    for name in _X_NAMES:
        if _field_present(record, name):
            raw_x = _field(record, name, None)
            break
    for name in _Y_NAMES:
        if _field_present(record, name):
            raw_y = _field(record, name, None)
            break
    parsed_x = _as_number(raw_x) if raw_x is not None else None
    parsed_y = _as_number(raw_y) if raw_y is not None else None
    if parsed_x is not None and parsed_y is not None:
        return (float(parsed_x), float(parsed_y), True)
    for name in _XY_TUPLE_NAMES:
        if _field_present(record, name):
            raw = _field(record, name, None)
            if raw is None or isinstance(raw, (str, bytes)):
                continue
            try:
                items = list(raw)
            except TypeError:
                continue
            if len(items) < 2:
                continue
            cand_x = _as_number(items[0])
            cand_y = _as_number(items[1])
            if cand_x is not None and cand_y is not None:
                return (float(cand_x), float(cand_y), True)
    return (None, None, True)


def _parse_optional_id(record: Any, names: tuple[str, ...]) -> tuple[int | None, bool, bool]:
    raw = _first_present(record, names)
    if raw is _MISSING or raw is None:
        return (None, False, False)
    parsed = _as_int(raw)
    if parsed is None:
        return (None, True, True)
    return (int(parsed), True, False)


def _parse_building(record: Any) -> tuple[str | None, bool, bool]:
    raw = _first_present(record, _BUILDING_NAMES)
    if raw is _MISSING or raw is None:
        return (None, False, False)
    if not isinstance(raw, str):
        return (None, True, True)
    text = raw.strip()
    if not text:
        return (None, True, True)
    return (text, True, False)


def _parse_surface_hint(record: Any) -> str | None:
    raw = _first_present(record, _SURFACE_NAMES)
    if raw is _MISSING or raw is None:
        return None
    if not isinstance(raw, str):
        return None
    text = raw.strip().lower()
    if text in ("land", "sea", "lake"):
        return text
    return None


def _parse_provenance(record: Any) -> tuple[str | None, bool]:
    provenance: str | None = None
    for name in _PROVENANCE_NAMES:
        if _field_present(record, name):
            raw = _field(record, name, None)
            if isinstance(raw, str) and raw.strip():
                provenance = raw.strip()
                break
    flagged = False
    for name in _FALLBACK_FLAG_NAMES:
        if _field_present(record, name):
            try:
                value = _field(record, name, None)
            except Exception:
                continue
            if isinstance(value, bool):
                if value:
                    flagged = True
                    break
            elif isinstance(value, (int, np.integer)):
                try:
                    if int(value) != 0:
                        flagged = True
                        break
                except (TypeError, ValueError):
                    continue
            elif isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ('1', 'true', 'yes', 'y', 't', 'on'):
                    flagged = True
                    break
                if lowered in _FALLBACK_PROVENANCE:
                    flagged = True
                    break
            elif value is not None:
                try:
                    if bool(value):
                        flagged = True
                        break
                except Exception:
                    continue
    if provenance is not None and provenance.strip().lower() in _FALLBACK_PROVENANCE:
        flagged = True
    return (provenance, bool(flagged))
def _province_id_set(province_map: Any) -> set[int] | None:
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


def _raster_geometry(province_map: Any) -> tuple[Any | None, int | None, int | None, set[int] | None]:
    if province_map is None:
        return (None, None, None, None)
    try:
        arr = np.asarray(province_map)
    except Exception:
        return (None, None, None, None)
    if arr.ndim != 2:
        return (None, None, None, None)
    try:
        height = int(arr.shape[0])
        width = int(arr.shape[1])
    except Exception:
        return (None, None, None, None)
    if height <= 0 or width <= 0 or arr.size == 0:
        return (None, None, None, None)
    return (arr, height, width, _province_id_set(arr))


def _surface_table(tile_map: Any, province_map: Any) -> dict[int, str] | None:
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


def _coastal_land_to_sea(tile_map: Any, province_map: Any, wrap_horizontal: bool) -> dict[int, int] | None:
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
        land_v, sea_v = int(TILE_LAND), int(TILE_SEA)
    except (TypeError, ValueError):
        land_v, sea_v = 1, 2
    try:
        land_mask = tile == land_v
        sea_mask = tile == sea_v
    except Exception:
        return None
    out: dict[int, int] = {}

    def _absorb(land_idx: Any, sea_idx: Any) -> None:
        try:
            land_pids = np.asarray(prov)[land_idx]
            sea_pids = np.asarray(prov)[sea_idx]
        except Exception:
            return
        try:
            flat_land = np.ravel(land_pids).tolist()
            flat_sea = np.ravel(sea_pids).tolist()
        except Exception:
            return
        for land_raw, sea_raw in zip(flat_land, flat_sea):
            land_pid = _as_int(land_raw)
            sea_pid = _as_int(sea_raw)
            if land_pid is None or sea_pid is None:
                continue
            if land_pid > 0 and sea_pid > 0 and land_pid not in out:
                out[land_pid] = int(sea_pid)

    try:
        if tile.shape[0] > 1:
            up = land_mask[1:, :] & sea_mask[:-1, :]
            if bool(np.any(up)):
                ys, xs = np.where(up)
                _absorb((ys + 1, xs), (ys, xs))
            down = land_mask[:-1, :] & sea_mask[1:, :]
            if bool(np.any(down)):
                ys, xs = np.where(down)
                _absorb((ys, xs), (ys + 1, xs))
        if tile.shape[1] > 1:
            left = land_mask[:, 1:] & sea_mask[:, :-1]
            if bool(np.any(left)):
                ys, xs = np.where(left)
                _absorb((ys, xs + 1), (ys, xs))
            right = land_mask[:, :-1] & sea_mask[:, 1:]
            if bool(np.any(right)):
                ys, xs = np.where(right)
                _absorb((ys, xs), (ys, xs + 1))
            if wrap_horizontal:
                wrap_left = land_mask[:, 0] & sea_mask[:, -1]
                if bool(np.any(wrap_left)):
                    ys = np.where(wrap_left)[0]
                    _absorb((ys, np.zeros_like(ys)), (ys, np.full_like(ys, tile.shape[1] - 1)))
                wrap_right = land_mask[:, -1] & sea_mask[:, 0]
                if bool(np.any(wrap_right)):
                    ys = np.where(wrap_right)[0]
                    _absorb((ys, np.full_like(ys, tile.shape[1] - 1)), (ys, np.zeros_like(ys)))
    except Exception:
        return out
    return out


def _tile_surface_at(tile_arr: Any | None, pos_x: float, pos_y: float) -> str | None:
    if tile_arr is None:
        return None
    try:
        height = int(tile_arr.shape[0])
        width = int(tile_arr.shape[1])
    except Exception:
        return None
    try:
        ix = int(math.floor(float(pos_x)))
        iy = int(math.floor(float(pos_y)))
    except (TypeError, ValueError, OverflowError):
        return None
    if ix < 0 or iy < 0 or ix >= width or iy >= height:
        return None
    try:
        raw = tile_arr[iy, ix]
    except Exception:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    try:
        land_v, sea_v, lake_v = int(TILE_LAND), int(TILE_SEA), int(TILE_LAKE)
    except (TypeError, ValueError):
        land_v, sea_v, lake_v = 1, 2, 3
    if value == land_v:
        return "land"
    if value == sea_v:
        return "sea"
    if value == lake_v:
        return "lake"
    return "undefined"


def _province_at(prov_arr: Any | None, pos_x: float, pos_y: float) -> int | None:
    if prov_arr is None:
        return None
    try:
        height = int(prov_arr.shape[0])
        width = int(prov_arr.shape[1])
    except Exception:
        return None
    try:
        ix = int(math.floor(float(pos_x)))
        iy = int(math.floor(float(pos_y)))
    except (TypeError, ValueError, OverflowError):
        return None
    if ix < 0 or iy < 0 or ix >= width or iy >= height:
        return None
    try:
        raw = prov_arr[iy, ix]
    except Exception:
        return None
    pid = _as_int(raw)
    if pid is None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return int(pid)
def _read_mapping(manager: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        try:
            if hasattr(manager, name):
                value = getattr(manager, name)
                if callable(value) and not isinstance(value, dict):
                    try:
                        value = value()
                    except Exception:
                        continue
                return value
        except Exception:
            continue
    return None


def _parse_province_groups(raw: Any, province_attrs: tuple[str, ...]) -> tuple[list[int], dict[int, list[int]], int, list[int]] | None:
    if raw is None:
        return ([], {}, 0, [])
    if not isinstance(raw, Mapping):
        return None
    groups: dict[int, list[int]] = {}
    unparseable = 0
    mismatched: list[int] = []
    try:
        items = list(raw.items())
    except Exception:
        return None
    for key, obj in items:
        sid = _as_int(key)
        if sid is None:
            unparseable += 1
            continue
        sid = int(sid)
        raw_list: list[Any] = []
        obj_id: Any = None
        try:
            if isinstance(obj, (list, tuple, set, frozenset)):
                raw_list = list(obj)
            elif isinstance(obj, Mapping):
                found = None
                for attr in province_attrs:
                    if attr in obj:
                        found = obj.get(attr)
                        break
                try:
                    raw_list = list(found) if found is not None else []
                except TypeError:
                    raw_list = []
                obj_id = obj.get("id", None)
            else:
                found = None
                for attr in province_attrs:
                    try:
                        if hasattr(obj, attr):
                            found = getattr(obj, attr)
                            break
                    except Exception:
                        continue
                try:
                    raw_list = list(found) if found is not None else []
                except TypeError:
                    raw_list = []
                try:
                    obj_id = getattr(obj, "id", None)
                except Exception:
                    obj_id = None
        except Exception:
            raw_list = []
        if obj_id is not None and not isinstance(obj_id, bool):
            try:
                oid = int(obj_id)  # type: ignore[arg-type]
                if int(oid) != int(sid):
                    mismatched.append(int(sid))
            except (TypeError, ValueError):
                pass
        parsed: list[int] = []
        for entry in raw_list:
            pid = _as_int(entry)
            if pid is None:
                unparseable += 1
            else:
                parsed.append(int(pid))
        groups[int(sid)] = parsed
    return (sorted(groups.keys()), groups, int(unparseable), sorted(set(mismatched)))


def _groups_from_get_all(manager: Any, id_names: tuple[str, ...], province_attrs: tuple[str, ...]) -> dict[int, list[int]] | None:
    func = getattr(manager, "get_all", None)
    if not callable(func):
        return None
    try:
        entries = func()
    except Exception:
        return None
    if entries is None:
        return None
    try:
        items = list(entries)
    except TypeError:
        return None
    groups: dict[int, list[int]] = {}
    for entry in items:
        raw_id: Any = None
        for name in id_names:
            raw_id = _field(entry, name, None)
            if raw_id is not None:
                break
        gid = _as_int(raw_id)
        if gid is None:
            continue
        raw_list: Any = None
        for attr in province_attrs:
            candidate = _field(entry, attr, None)
            if candidate is not None:
                raw_list = candidate
                break
        if raw_list is None or isinstance(raw_list, (str, bytes)):
            continue
        try:
            values = list(raw_list)
        except TypeError:
            continue
        parsed: list[int] = []
        for value in values:
            pid = _as_int(value)
            if pid is not None:
                parsed.append(int(pid))
        groups[int(gid)] = parsed
    return groups


def _extract_state_lookup(state_mgr: Any) -> tuple[set[int] | None, dict[int, int]]:
    if state_mgr is None:
        return (None, {})
    raw = _read_mapping(state_mgr, ("states", "_states"))
    parsed = None
    if isinstance(raw, Mapping):
        parsed = _parse_province_groups(raw, ("provinces", "province_ids"))
    elif isinstance(state_mgr, Mapping):
        candidate: Any = None
        try:
            candidate = state_mgr.get("states", state_mgr) if "states" in state_mgr else state_mgr
        except Exception:
            candidate = None
        if isinstance(candidate, Mapping):
            parsed = _parse_province_groups(candidate, ("provinces", "province_ids"))
    if parsed is None:
        groups = _groups_from_get_all(state_mgr, ("id", "state_id"), ("provinces", "province_ids"))
        if groups is None:
            return (None, {})
        parsed = (sorted(groups.keys()), groups, 0, [])
    _ids, groups, _unparseable, _mismatched = parsed
    known = set(int(sid) for sid in _ids)
    pid_to_state: dict[int, int] = {}
    for sid, pids in groups.items():
        for pid in pids:
            if pid not in pid_to_state:
                pid_to_state[int(pid)] = int(sid)
    return (known, pid_to_state)


def _extract_region_lookup(region_mgr: Any) -> tuple[set[int] | None, dict[int, int]]:
    if region_mgr is None:
        return (None, {})
    raw = _read_mapping(region_mgr, ("regions", "_regions"))
    parsed = None
    if isinstance(raw, Mapping):
        parsed = _parse_province_groups(raw, ("province_ids", "provinces"))
    elif isinstance(region_mgr, Mapping):
        candidate: Any = None
        try:
            candidate = region_mgr.get("regions", None)
        except Exception:
            candidate = None
        if isinstance(candidate, Mapping):
            parsed = _parse_province_groups(candidate, ("province_ids", "provinces"))
        else:
            try:
                keys = list(region_mgr.keys())
                if keys and all(isinstance(_as_int(k), int) for k in keys):
                    parsed = _parse_province_groups(dict(region_mgr), ("province_ids", "provinces"))
            except Exception:
                parsed = None
    if parsed is None:
        groups = _groups_from_get_all(region_mgr, ("id", "region_id"), ("province_ids", "provinces"))
        if groups is None:
            return (None, {})
        parsed = (sorted(groups.keys()), groups, 0, [])
    _ids, groups, _unparseable, _mismatched = parsed
    known = set(int(rid) for rid in _ids)
    pid_to_region: dict[int, int] = {}
    for rid, pids in groups.items():
        for pid in pids:
            if pid not in pid_to_region:
                pid_to_region[int(pid)] = int(rid)
    return (known, pid_to_region)


def _resolve_legal_buildings() -> frozenset[str]:
    names: set[str] = set()
    try:
        for value in set(_VALID_3D_TYPES):
            if isinstance(value, str) and value.strip():
                names.add(value.strip())
    except Exception:
        pass
    for value in _WRITER_REQUIRED_STATE_ENTITIES:
        names.add(value)
    for value in _WRITER_COASTAL_STATE_ENTITIES:
        names.add(value)
    names.add("naval_base_spawn")
    names.add("naval_base")
    if not names:
        names = {
            "arms_factory", "industrial_complex", "air_base",
            "anti_air_building", "bunker", "fuel_silo", "radar_station",
            "nuclear_reactor_spawn", "rocket_site_spawn", "synthetic_refinery",
            "supply_node", "dockyard", "coastal_bunker", "naval_base_spawn",
        }
    return frozenset(names)


def _evidence(details: list[str]) -> str:
    if len(details) <= _EVIDENCE_DETAILS:
        return "; ".join(details)
    head = "; ".join(details[:_EVIDENCE_DETAILS])
    return "%s; ...(+%d more)" % (head, len(details) - _EVIDENCE_DETAILS)


def _capped_ids(values: set[int]) -> tuple:
    return tuple(sorted(values)[:_AFFECTED_LIMIT])


def _capped_coords(points: set[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    return tuple(sorted(points)[:_COORD_LIMIT])


def _pixel_point(pos_x: float, pos_y: float) -> tuple[int, int] | None:
    try:
        return (int(math.floor(float(pos_x))), int(math.floor(float(pos_y))))
    except (TypeError, ValueError, OverflowError):
        return None


def _quant_key(pos_x: float, pos_y: float) -> tuple[float, float]:
    return (round(float(pos_x), 2), round(float(pos_y), 2))


def _exact_key(pos_x: float, pos_y: float) -> tuple[float, float]:
    return (float(pos_x), float(pos_y))
def validate_placement_references(
    province_map: Any,
    tile_map: Any | None = None,
    *,
    placement_entries: Any | None = None,
    position_entries: Any | None = None,
    building_entries: Any | None = None,
    weather_entries: Any | None = None,
    state_mgr: Any | None = None,
    strategic_region_mgr: Any | None = None,
    profile: Any | None = None,
    lifecycle: Any = "draft",
    wrap_horizontal: bool | None = None,
    collision_tolerance: float = 1.0,
    **_ignored: Any,
) -> list[ValidationFinding]:
    """Validate authored placement, building, port, collision, fallback, and weather references."""
    try:
        tolerance = float(collision_tolerance)
    except (TypeError, ValueError):
        tolerance = 1.0
    if not math.isfinite(tolerance) or tolerance < 0:
        tolerance = 1.0
    wrap = _resolve_wrap_horizontal(wrap_horizontal, profile)
    strict_fallback = _is_strict_lifecycle(lifecycle)
    legal_buildings = _resolve_legal_buildings()
    legal_lower = {str(name).strip().lower() for name in legal_buildings if str(name).strip()}

    prov_arr, height, width, known_ids = _raster_geometry(province_map)
    dims_available = prov_arr is not None and height is not None and width is not None

    tile_arr: Any | None = None
    surfaces: dict[int, str] | None = None
    coastal_set: set[int] | None = None
    land_to_sea: dict[int, int] | None = None
    if tile_map is not None and prov_arr is not None:
        try:
            candidate = np.asarray(tile_map)
        except Exception:
            candidate = None
        if candidate is not None and candidate.ndim == 2 and candidate.shape == prov_arr.shape and candidate.size > 0:
            tile_arr = candidate
            surfaces = _surface_table(tile_arr, prov_arr)
            land_to_sea = _coastal_land_to_sea(tile_arr, prov_arr, wrap)
            coastal_set = set(land_to_sea.keys()) if land_to_sea is not None else set()

    known_states, pid_to_state = _extract_state_lookup(state_mgr)
    known_regions, pid_to_region = _extract_region_lookup(strategic_region_mgr)

    transforms: list[dict[str, Any]] = []
    for source, collection in (
        ("placement", placement_entries),
        ("position", position_entries),
        ("building", building_entries),
    ):
        for index, raw in enumerate(_safe_entries(collection)):
            if _is_malformed_record(raw):
                transforms.append({
                    "source": source, "index": int(index), "raw": raw, "malformed": True,
                    "province_id": None, "province_present": False, "province_illegal": False,
                    "state_id": None, "state_present": False, "state_illegal": False,
                    "building": None, "building_present": False, "building_malformed": False,
                    "sea_id": None, "sea_present": False, "sea_illegal": False,
                    "pos_x": None, "pos_y": None, "xy_present": False,
                    "provenance": None, "is_fallback": False, "surface_hint": None,
                })
                continue
            province_id, province_present, province_illegal = _parse_optional_id(raw, _PROVINCE_NAMES)
            state_id, state_present, state_illegal = _parse_optional_id(raw, _STATE_NAMES)
            building, building_present, building_malformed = _parse_building(raw)
            sea_id, sea_present, sea_illegal = _parse_optional_id(raw, _SEA_NAMES)
            pos_x, pos_y, xy_present = _parse_xy(raw)
            provenance, is_fallback = _parse_provenance(raw)
            surface_hint = _parse_surface_hint(raw)
            transforms.append({
                "source": source, "index": int(index), "raw": raw, "malformed": False,
                "province_id": province_id, "province_present": bool(province_present), "province_illegal": bool(province_illegal),
                "state_id": state_id, "state_present": bool(state_present), "state_illegal": bool(state_illegal),
                "building": building, "building_present": bool(building_present), "building_malformed": bool(building_malformed),
                "sea_id": sea_id, "sea_present": bool(sea_present), "sea_illegal": bool(sea_illegal),
                "pos_x": pos_x, "pos_y": pos_y, "xy_present": bool(xy_present),
                "provenance": provenance, "is_fallback": bool(is_fallback), "surface_hint": surface_hint,
            })

    weather: list[dict[str, Any]] = []
    for index, raw in enumerate(_safe_entries(weather_entries)):
        if _is_malformed_record(raw):
            weather.append({
                "index": int(index), "raw": raw, "malformed": True,
                "region_id": None, "region_present": False, "region_illegal": False,
                "pos_x": None, "pos_y": None, "xy_present": False,
            })
            continue
        region_id, region_present, region_illegal = _parse_optional_id(raw, _REGION_NAMES)
        pos_x, pos_y, xy_present = _parse_xy(raw)
        weather.append({
            "index": int(index), "raw": raw, "malformed": False,
            "region_id": region_id, "region_present": bool(region_present), "region_illegal": bool(region_illegal),
            "pos_x": pos_x, "pos_y": pos_y, "xy_present": bool(xy_present),
        })

    if not transforms and not weather:
        return []

    findings: list[ValidationFinding] = []

    coord_details: list[str] = []
    coord_ids: set[int] = set()
    coord_points: set[tuple[int, int]] = set()

    def _note_coord(detail: str, pids: list[int | None], point: tuple[int, int] | None) -> None:
        coord_details.append(detail)
        for pid in pids:
            if isinstance(pid, int) and pid > 0:
                coord_ids.add(pid)
        if point is not None:
            coord_points.add(point)

    for item in transforms:
        source = str(item["source"])
        index = int(item["index"])
        label = "%s#%d" % (source, index)
        if bool(item["malformed"]):
            _note_coord("%s is a malformed record" % label, [], None)
            continue
        pos_x = item["pos_x"]
        pos_y = item["pos_y"]
        province_id = item["province_id"]
        state_id = item["state_id"]
        pids_for_note: list[int | None] = []
        if isinstance(province_id, int) and province_id > 0:
            pids_for_note.append(province_id)
        if pos_x is None or pos_y is None:
            if isinstance(province_id, int) and province_id > 0:
                _note_coord("%s has missing or malformed coordinates for province %d" % (label, int(province_id)), pids_for_note, None)
            else:
                _note_coord("%s has missing or malformed coordinates" % label, pids_for_note, None)
            continue
        point = _pixel_point(pos_x, pos_y)
        if dims_available and height is not None and width is not None:
            if not (0 <= float(pos_x) < float(width) and 0 <= float(pos_y) < float(height)):
                _note_coord("%s at (%.2f, %.2f) is out of bounds for %dx%d" % (label, float(pos_x), float(pos_y), int(width), int(height)), pids_for_note, point)
                continue
            actual = _province_at(prov_arr, pos_x, pos_y)
            if actual is not None and isinstance(province_id, int) and province_id > 0 and int(actual) != int(province_id):
                if int(actual) > 0:
                    _note_coord("%s declares province %d but resolves to province %d" % (label, int(province_id), int(actual)), [province_id, int(actual)], point)
                else:
                    _note_coord("%s declares province %d but resolves to unassigned land" % (label, int(province_id)), [province_id], point)
            if actual is not None and int(actual) > 0 and isinstance(state_id, int) and state_id > 0 and pid_to_state:
                expected_state = pid_to_state.get(int(actual))
                if expected_state is not None and int(expected_state) != int(state_id):
                    _note_coord("%s declares state %d but resolves to state %d through province %d" % (label, int(state_id), int(expected_state), int(actual)), pids_for_note, point)
            surface_hint = item["surface_hint"]
            if surface_hint is not None and tile_arr is not None:
                actual_surface = _tile_surface_at(tile_arr, pos_x, pos_y)
                if actual_surface is not None and actual_surface in ("land", "sea", "lake") and actual_surface != surface_hint:
                    _note_coord("%s declares surface %s but resolves to %s" % (label, surface_hint, actual_surface), pids_for_note, point)
    if coord_details:
        findings.append(
            ValidationFinding(
                code="placement.coordinate",
                severity="error",
                message="%d placement coordinates are out of bounds or resolve to foreign provinces" % len(coord_details),
                layer=LAYER,
                affected_ids=_capped_ids(coord_ids),
                coordinates=_capped_coords(coord_points),
                evidence=_evidence(sorted(coord_details)),
            )
        )
    building_details: list[str] = []
    building_ids: set[int] = set()
    building_points: set[tuple[int, int]] = set()

    def _note_building(detail: str, pids: list[int | None], point: tuple[int, int] | None) -> None:
        building_details.append(detail)
        for pid in pids:
            if isinstance(pid, int) and pid > 0:
                building_ids.add(pid)
        if point is not None:
            building_points.add(point)

    for item in transforms:
        source = str(item["source"])
        index = int(item["index"])
        label = "%s#%d" % (source, index)
        if bool(item["malformed"]):
            continue
        pos_x = item["pos_x"]
        pos_y = item["pos_y"]
        point = _pixel_point(pos_x, pos_y) if pos_x is not None and pos_y is not None else None
        province_id = item["province_id"]
        state_id = item["state_id"]
        province_pids: list[int | None] = []
        if isinstance(province_id, int) and province_id > 0:
            province_pids.append(int(province_id))
        has_building = bool(item["building_present"])
        if not has_building:
            if bool(item["province_present"]) and bool(item["province_illegal"]):
                _note_building("%s has illegal province %s" % (label, _short(_first_present(item["raw"], _PROVINCE_NAMES))), [], point)
            elif isinstance(province_id, int) and province_id > 0 and known_ids is not None and int(province_id) not in known_ids:
                _note_building("%s references unknown province %d" % (label, int(province_id)), [int(province_id)], point)
            if bool(item["state_present"]) and bool(item["state_illegal"]):
                _note_building("%s has illegal state %s" % (label, _short(_first_present(item["raw"], _STATE_NAMES))), province_pids, point)
            elif isinstance(state_id, int) and state_id > 0 and known_states is not None and int(state_id) not in known_states:
                _note_building("%s references unknown state %d" % (label, int(state_id)), province_pids, point)
            continue
        if bool(item["building_malformed"]):
            _note_building("%s has malformed building type %s" % (label, _short(_first_present(item["raw"], _BUILDING_NAMES))), province_pids, point)
        else:
            building = item["building"]
            text = str(building) if building is not None else ""
            if text.strip().lower() not in legal_lower:
                _note_building("%s has illegal building type %s" % (label, _short(building)), province_pids, point)
        if bool(item["province_present"]) and bool(item["province_illegal"]):
            _note_building("%s has illegal province %s" % (label, _short(_first_present(item["raw"], _PROVINCE_NAMES))), [], point)
        elif isinstance(province_id, int) and province_id > 0 and known_ids is not None and int(province_id) not in known_ids:
            _note_building("%s references unknown province %d" % (label, int(province_id)), [int(province_id)], point)
        if bool(item["state_present"]) and bool(item["state_illegal"]):
            _note_building("%s has illegal state %s" % (label, _short(_first_present(item["raw"], _STATE_NAMES))), province_pids, point)
        elif isinstance(state_id, int) and state_id > 0 and known_states is not None and int(state_id) not in known_states:
            _note_building("%s references unknown state %d" % (label, int(state_id)), province_pids, point)
        if isinstance(province_id, int) and province_id > 0 and isinstance(state_id, int) and state_id > 0 and pid_to_state:
            expected_state = pid_to_state.get(int(province_id))
            if expected_state is not None and int(expected_state) != int(state_id):
                _note_building("%s places province %d in state %d but declares state %d" % (label, int(province_id), int(expected_state), int(state_id)), [int(province_id)], point)
        if tile_arr is not None and pos_x is not None and pos_y is not None and dims_available:
            in_bounds = False
            try:
                in_bounds = 0 <= float(pos_x) < float(width) and 0 <= float(pos_y) < float(height)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                in_bounds = False
            if in_bounds:
                surface = _tile_surface_at(tile_arr, pos_x, pos_y)
                if surface is not None and surface in ("sea", "lake", "undefined"):
                    building = item["building"]
                    name = str(building).strip() if isinstance(building, str) and building.strip() else "building"
                    _note_building("%s places %s on water (surface=%s)" % (label, _short(name), surface), province_pids, point)
    if building_details:
        findings.append(
            ValidationFinding(
                code="placement.building",
                severity="error",
                message="%d building or state placements are invalid" % len(building_details),
                layer=LAYER,
                affected_ids=_capped_ids(building_ids),
                coordinates=_capped_coords(building_points),
                evidence=_evidence(sorted(building_details)),
            )
        )

    port_details: list[str] = []
    port_ids: set[int] = set()
    port_points: set[tuple[int, int]] = set()

    def _note_port(detail: str, pids: list[int | None], point: tuple[int, int] | None) -> None:
        port_details.append(detail)
        for pid in pids:
            if isinstance(pid, int) and pid > 0:
                port_ids.add(pid)
        if point is not None:
            port_points.add(point)

    for item in transforms:
        if bool(item["malformed"]):
            continue
        if not bool(item["building_present"]) or bool(item["building_malformed"]):
            continue
        building = item["building"]
        if not isinstance(building, str):
            continue
        lowered = building.strip().lower()
        if lowered not in _PORT_TYPES:
            continue
        source = str(item["source"])
        index = int(item["index"])
        label = "%s#%d" % (source, index)
        province_id = item["province_id"]
        sea_id = item["sea_id"]
        pos_x = item["pos_x"]
        pos_y = item["pos_y"]
        point = _pixel_point(pos_x, pos_y) if pos_x is not None and pos_y is not None else None
        if not isinstance(province_id, int) or province_id <= 0 or bool(item['province_illegal']):
            if bool(item['province_illegal']):
                _note_port('%s port %s has illegal province %s and coastal/sea validation cannot succeed' % (label, _short(building), _short(_first_present(item['raw'], _PROVINCE_NAMES))), [], point)
            elif not bool(item['province_present']):
                _note_port('%s port %s is missing its province and coastal/sea validation cannot succeed' % (label, _short(building)), [], point)
            else:
                _note_port('%s port %s has missing or invalid province %s and coastal/sea validation cannot succeed' % (label, _short(building), _short(_first_present(item['raw'], _PROVINCE_NAMES))), [], point)
            continue
        if known_ids is not None and int(province_id) not in known_ids:
            _note_port('%s port %s references unknown province %d and coastal/sea validation cannot succeed' % (label, _short(building), int(province_id)), [int(province_id)], point)
            continue
        if coastal_set is not None and land_to_sea is not None:
            if int(province_id) not in coastal_set:
                _note_port("%s port %s on non-coastal province %d" % (label, _short(building), int(province_id)), [int(province_id)], point)
                continue
        if lowered in _SEA_REQUIRED_TYPES:
            if not bool(item["sea_present"]) or bool(item["sea_illegal"]) or not isinstance(sea_id, int) or sea_id <= 0:
                _note_port("%s port %s is missing its sea connection" % (label, _short(building)), [int(province_id)], point)
                continue
            assert isinstance(sea_id, int)
            if known_ids is not None and int(sea_id) not in known_ids:
                _note_port("%s port %s references unknown sea province %d" % (label, _short(building), int(sea_id)), [int(province_id), int(sea_id)], point)
                continue
            if surfaces is not None:
                sea_surface = surfaces.get(int(sea_id))
                if sea_surface is not None and sea_surface != "sea":
                    _note_port("%s port %s uses sea province %d with surface=%s" % (label, _short(building), int(sea_id), sea_surface), [int(province_id), int(sea_id)], point)
                    continue
            if land_to_sea is not None:
                expected_sea = land_to_sea.get(int(province_id))
                if expected_sea is not None and int(expected_sea) != int(sea_id):
                    _note_port("%s port %s uses sea %d but intended sea is %d" % (label, _short(building), int(sea_id), int(expected_sea)), [int(province_id), int(sea_id)], point)
        else:
            if bool(item["sea_present"]) and not bool(item["sea_illegal"]) and isinstance(sea_id, int) and sea_id > 0:
                if known_ids is not None and int(sea_id) not in known_ids:
                    _note_port("%s port %s references unknown sea province %d" % (label, _short(building), int(sea_id)), [int(province_id), int(sea_id)], point)
                    continue
                if surfaces is not None:
                    sea_surface = surfaces.get(int(sea_id))
                    if sea_surface is not None and sea_surface != "sea":
                        _note_port("%s port %s uses sea province %d with surface=%s" % (label, _short(building), int(sea_id), sea_surface), [int(province_id), int(sea_id)], point)
    if port_details:
        findings.append(
            ValidationFinding(
                code="placement.port",
                severity="error",
                message="%d port or naval-base placements lack coastal or sea access" % len(port_details),
                layer=LAYER,
                affected_ids=_capped_ids(port_ids),
                coordinates=_capped_coords(port_points),
                evidence=_evidence(sorted(port_details)),
            )
        )
    valid_points: list[tuple[int, float, float, int | None, str, int]] = []
    for global_index, item in enumerate(transforms):
        if bool(item["malformed"]):
            continue
        pos_x = item["pos_x"]
        pos_y = item["pos_y"]
        if pos_x is None or pos_y is None:
            continue
        if dims_available and height is not None and width is not None:
            try:
                if not (0 <= float(pos_x) < float(width) and 0 <= float(pos_y) < float(height)):
                    continue
            except (TypeError, ValueError):
                continue
        province_id = item["province_id"]
        pid_value = int(province_id) if isinstance(province_id, int) and province_id > 0 else None
        valid_points.append((int(global_index), float(pos_x), float(pos_y), pid_value, str(item["source"]), int(item["index"])))

    collision_details: list[str] = []
    collision_ids: set[int] = set()
    collision_points: set[tuple[int, int]] = set()
    if len(valid_points) >= 2:
        groups: dict[tuple[float, float], list[tuple[int, float, float, int | None, str, int]]] = {}
        for entry in valid_points:
            key = _exact_key(entry[1], entry[2])
            groups.setdefault(key, []).append(entry)
        for key in sorted(groups.keys()):
            members = groups[key]
            if len(members) < 2:
                continue
            members_sorted = sorted(members, key=lambda e: (e[0], e[4], e[5]))
            labels = ", ".join("%s#%d" % (m[4], m[5]) for m in members_sorted)
            detail = "duplicate_transform at (%.2f, %.2f): %s" % (float(key[0]), float(key[1]), labels)
            collision_details.append(detail)
            for _gi, _x, _y, _pid, _src, _idx in members_sorted:
                if _pid is not None:
                    collision_ids.add(int(_pid))
            point = _pixel_point(key[0], key[1])
            if point is not None:
                collision_points.add(point)
        near_pairs: list[tuple[int, int, float, tuple[int, float, float, int | None, str, int], tuple[int, float, float, int | None, str, int]]] = []
        for pos_a in range(len(valid_points)):
            entry_a = valid_points[pos_a]
            key_a = _exact_key(entry_a[1], entry_a[2])
            for pos_b in range(pos_a + 1, len(valid_points)):
                entry_b = valid_points[pos_b]
                key_b = _exact_key(entry_b[1], entry_b[2])
                if key_a == key_b:
                    continue
                dx = abs(float(entry_a[1]) - float(entry_b[1]))
                if wrap and width is not None and width > 0:
                    try:
                        dx = min(dx, float(width) - dx)
                    except (TypeError, ValueError):
                        pass
                dy = abs(float(entry_a[2]) - float(entry_b[2]))
                try:
                    dist = math.hypot(dx, dy)
                except (TypeError, ValueError):
                    continue
                if dist < tolerance and dist > 0:
                    near_pairs.append((entry_a[0], entry_b[0], float(dist), entry_a, entry_b))
        near_pairs.sort(key=lambda t: (t[0], t[1]))
        for _ga, _gb, dist, entry_a, entry_b in near_pairs:
            label_a = "%s#%d" % (entry_a[4], entry_a[5])
            label_b = "%s#%d" % (entry_b[4], entry_b[5])
            detail = "near_collision %s and %s distance=%.2f" % (label_a, label_b, float(dist))
            collision_details.append(detail)
            for entry in (entry_a, entry_b):
                if entry[3] is not None:
                    collision_ids.add(int(entry[3]))
                point = _pixel_point(entry[1], entry[2])
                if point is not None:
                    collision_points.add(point)
    if collision_details:
        findings.append(
            ValidationFinding(
                code="placement.collision",
                severity="warning",
                message="%d duplicate or near-colliding transforms" % len(collision_details),
                layer=LAYER,
                affected_ids=_capped_ids(collision_ids),
                coordinates=_capped_coords(collision_points),
                evidence=_evidence(sorted(collision_details)),
                waivable=True,
            )
        )

    fallback_details: list[str] = []
    fallback_ids: set[int] = set()
    fallback_points: set[tuple[int, int]] = set()
    for item in transforms:
        if bool(item["malformed"]):
            continue
        if bool(item["is_fallback"]):
            source = str(item["source"])
            index = int(item["index"])
            provenance = item["provenance"]
            pos_x = item["pos_x"]
            pos_y = item["pos_y"]
            point = _pixel_point(pos_x, pos_y) if pos_x is not None and pos_y is not None else None
            province_id = item["province_id"]
            if provenance is not None:
                detail = "%s#%d uses fallback provenance %s" % (source, index, _short(provenance))
            else:
                detail = "%s#%d is flagged as fallback" % (source, index)
            fallback_details.append(detail)
            if isinstance(province_id, int) and province_id > 0:
                fallback_ids.add(int(province_id))
            if point is not None:
                fallback_points.add(point)
    if len(valid_points) >= 2:
        repeat_groups: dict[tuple[float, float], list[tuple[int, float, float, int | None, str, int]]] = {}
        for entry in valid_points:
            key = _exact_key(entry[1], entry[2])
            repeat_groups.setdefault(key, []).append(entry)
        for key in sorted(repeat_groups.keys()):
            members = repeat_groups[key]
            if len(members) < 2:
                continue
            members_sorted = sorted(members, key=lambda e: (e[0], e[4], e[5]))
            labels = ", ".join("%s#%d" % (m[4], m[5]) for m in members_sorted)
            detail = "repeated_centroid at (%.2f, %.2f): %s" % (float(key[0]), float(key[1]), labels)
            already = False
            for existing in fallback_details:
                if "repeated_centroid at (%.2f, %.2f)" % (float(key[0]), float(key[1])) in existing:
                    already = True
                    break
            if not already:
                fallback_details.append(detail)
            for _gi, _x, _y, _pid, _src, _idx in members_sorted:
                if _pid is not None:
                    fallback_ids.add(int(_pid))
            point = _pixel_point(key[0], key[1])
            if point is not None:
                fallback_points.add(point)
    if fallback_details:
        unique_fallback = sorted(set(fallback_details))
        if strict_fallback:
            findings.append(
                ValidationFinding(
                    code="placement.fallback",
                    severity="blocker",
                    message="%d fallback or repeated-centroid positions must be reviewed" % len(unique_fallback),
                    layer=LAYER,
                    affected_ids=_capped_ids(fallback_ids),
                    coordinates=_capped_coords(fallback_points),
                    evidence=_evidence(unique_fallback),
                    waivable=False,
                )
            )
        else:
            findings.append(
                ValidationFinding(
                    code="placement.fallback",
                    severity="warning",
                    message="%d fallback or repeated-centroid positions" % len(unique_fallback),
                    layer=LAYER,
                    affected_ids=_capped_ids(fallback_ids),
                    coordinates=_capped_coords(fallback_points),
                    evidence=_evidence(unique_fallback),
                    waivable=True,
                )
            )
    weather_details: list[str] = []
    weather_ids: set[int] = set()
    weather_points: set[tuple[int, int]] = set()

    def _note_weather(detail: str, rids: list[int | None], point: tuple[int, int] | None) -> None:
        weather_details.append(detail)
        for rid in rids:
            if isinstance(rid, int) and rid > 0:
                weather_ids.add(rid)
        if point is not None:
            weather_points.add(point)

    for item in weather:
        index = int(item["index"])
        label = "weather#%d" % index
        if bool(item["malformed"]):
            _note_weather("%s is a malformed record" % label, [], None)
            continue
        region_id = item["region_id"]
        pos_x = item["pos_x"]
        pos_y = item["pos_y"]
        point = _pixel_point(pos_x, pos_y) if pos_x is not None and pos_y is not None else None
        if bool(item["region_present"]) and bool(item["region_illegal"]):
            _note_weather("%s has illegal region %s" % (label, _short(_first_present(item["raw"], _REGION_NAMES))), [], point)
        elif isinstance(region_id, int) and region_id > 0 and known_regions is not None and int(region_id) not in known_regions:
            _note_weather("%s references unknown strategic region %d" % (label, int(region_id)), [int(region_id)], point)
        if pos_x is None or pos_y is None:
            rids: list[int | None] = [region_id] if isinstance(region_id, int) else []
            _note_weather("%s has missing or malformed coordinates" % label, rids, None)
            continue
        if dims_available and height is not None and width is not None:
            if not (0 <= float(pos_x) < float(width) and 0 <= float(pos_y) < float(height)):
                rids2: list[int | None] = [region_id] if isinstance(region_id, int) and region_id > 0 else []
                _note_weather("%s at (%.2f, %.2f) is out of bounds for %dx%d" % (label, float(pos_x), float(pos_y), int(width), int(height)), rids2, point)
                continue
            if isinstance(region_id, int) and region_id > 0 and pid_to_region:
                actual_province = _province_at(prov_arr, pos_x, pos_y)
                if actual_province is not None and int(actual_province) > 0:
                    actual_region = pid_to_region.get(int(actual_province))
                    if actual_region is not None and int(actual_region) != int(region_id):
                        _note_weather("%s declares region %d but resolves to province %d in region %d" % (label, int(region_id), int(actual_province), int(actual_region)), [int(region_id)], point)
                elif actual_province is not None and int(actual_province) <= 0:
                    _note_weather("%s declares region %d but resolves to unassigned land" % (label, int(region_id)), [int(region_id)], point)
    if weather_details:
        findings.append(
            ValidationFinding(
                code="placement.weather",
                severity="error",
                message="%d weather positions lie outside their strategic regions" % len(weather_details),
                layer=LAYER,
                affected_ids=_capped_ids(weather_ids),
                coordinates=_capped_coords(weather_points),
                evidence=_evidence(sorted(weather_details)),
            )
        )

    ordered = {code: pos for pos, code in enumerate(CODES)}
    findings.sort(key=lambda item: ordered.get(item.code, len(ordered)))
    return findings


def _safe_manager_records(manager: Any, accessor_name: str) -> list[Any]:
    """Read one manager collection without allowing malformed records to crash validation."""
    if manager is None:
        return []
    try:
        accessor = getattr(manager, accessor_name, None)
        if not callable(accessor):
            return []
        values = accessor()
        if values is None:
            return []
        return list(values)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return []


def _manager_status(record: Any) -> str | None:
    """Return a normalized review status for a manager-like record."""
    raw = _field(record, "review_status", None)
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    return value or None


def _manager_int(record: Any, name: str) -> int | None:
    """Read one positive integer reference from a manager-like record."""
    parsed = _as_int(_field(record, name, None))
    return parsed if parsed is not None and parsed > 0 else None


def validate_manager_placement_completeness(
    province_map: Any,
    tile_map: Any | None,
    manager: Any | None,
    *,
    lifecycle: Any = "draft",
) -> list[ValidationFinding]:
    """Validate manager records that a foundation writer would consume.

    This is deliberately narrower than :func:`validate_placement_references`:
    it checks only whether land provinces have all six explicitly reviewed
    position slots and whether existing manager records are reviewed. It does
    not duplicate coordinate, surface, state, region, or port-adjacency
    validation. A missing manager disables this compatibility check, matching
    legacy callers that have no authored placement model yet.

    Draft-like lifecycles report warnings so an editor can continue to work;
    ``frozen`` and ``accepted`` report blockers. The manager and raster inputs
    are read-only and malformed duck-typed records are represented in the
    deterministic evidence instead of raising.
    """
    if manager is None:
        return []

    try:
        lifecycle_text = str(lifecycle if lifecycle is not None else "draft").strip().lower()
    except Exception:
        lifecycle_text = "draft"
    strict = lifecycle_text not in (
        "draft",
        "candidate",
        "draft_preview",
        "foundation_candidate",
    )
    severity = "blocker" if strict else "warning"
    findings: list[ValidationFinding] = []
    completeness_details: list[str] = []
    completeness_ids: set[int] = set()
    review_details: list[str] = []
    review_ids: set[int] = set()

    try:
        province_arr = np.asarray(province_map)
        tile_arr = np.asarray(tile_map)
    except Exception:
        province_arr = None
        tile_arr = None

    land_ids: set[int] = set()
    if (
        province_arr is None
        or tile_arr is None
        or province_arr.ndim != 2
        or tile_arr.ndim != 2
        or province_arr.shape != tile_arr.shape
    ):
        completeness_details.append(
            "province and tile maps must be matching two-dimensional arrays"
        )
    else:
        try:
            land_values = province_arr[tile_arr == int(TILE_LAND)].ravel()
            for raw_pid in land_values.tolist():
                pid = _as_int(raw_pid)
                if pid is not None and pid > 0:
                    land_ids.add(int(pid))
        except (TypeError, ValueError, IndexError):
            completeness_details.append("land province set could not be read")

    slot_records = _safe_manager_records(manager, "list_province_slots")
    slots_by_province: dict[int, dict[int, list[Any]]] = {}
    for index, record in enumerate(slot_records):
        pid = _manager_int(record, "province_id")
        slot = _as_int(_field(record, "slot", None))
        if pid is None or slot is None or not 0 <= int(slot) < 6:
            review_details.append(
                "slot record #%d has an invalid province_id or slot" % index
            )
            if pid is not None:
                review_ids.add(int(pid))
            continue
        slots_by_province.setdefault(int(pid), {}).setdefault(int(slot), []).append(record)
        status = _manager_status(record)
        if status not in ("reviewed", "accepted"):
            review_details.append(
                "slot province %d index %d has review_status %s"
                % (int(pid), int(slot), repr(status))
            )
            review_ids.add(int(pid))

    for pid in sorted(land_ids):
        by_slot = slots_by_province.get(int(pid), {})
        missing = [slot for slot in range(6) if slot not in by_slot]
        duplicate = [slot for slot in range(6) if len(by_slot.get(slot, ())) > 1]
        if missing:
            completeness_ids.add(int(pid))
            completeness_details.append(
                "land province %d is missing position slots %s"
                % (int(pid), ",".join(str(slot) for slot in missing))
            )
        if duplicate:
            completeness_ids.add(int(pid))
            completeness_details.append(
                "land province %d has duplicate position slots %s"
                % (int(pid), ",".join(str(slot) for slot in duplicate))
            )

    for label, accessor, id_field in (
        ("building", "list_buildings", "province_id"),
        ("port", "list_ports", "province_id"),
        ("weather", "list_weather", "region_id"),
    ):
        for index, record in enumerate(_safe_manager_records(manager, accessor)):
            status = _manager_status(record)
            if status in ("reviewed", "accepted"):
                continue
            record_id = _manager_int(record, id_field)
            if record_id is not None:
                review_ids.add(int(record_id))
                reference = "%d" % int(record_id)
            else:
                reference = "?"
            review_details.append(
                "%s record #%d (%s) has review_status %s"
                % (label, index, reference, repr(status))
            )

    if completeness_details:
        findings.append(
            ValidationFinding(
                code="placement.completeness",
                severity=severity,
                message="%d land province placement groups are incomplete"
                % len(completeness_details),
                layer=LAYER,
                affected_ids=_capped_ids(completeness_ids),
                evidence=_evidence(sorted(completeness_details)),
            )
        )
    if review_details:
        findings.append(
            ValidationFinding(
                code="placement.review",
                severity=severity,
                message="%d placement records are not reviewed for foundation output"
                % len(review_details),
                layer=LAYER,
                affected_ids=_capped_ids(review_ids),
                evidence=_evidence(sorted(review_details)),
            )
        )
    return findings


def validate_manager_weather_positions(
    province_map: Any,
    manager: Any | None,
    *,
    strategic_region_mgr: Any | None = None,
    lifecycle: Any = "draft",
    min_spacing: float = 1.0,
) -> list[ValidationFinding]:
    """Validate manager weather containment and intra-region spacing.

    Weather records are read through the manager's public ``list_weather``
    accessor and are never normalized or changed.  Draft-like lifecycles keep
    the editor usable with warnings; frozen and accepted lifecycles promote
    the same deterministic finding to a blocker.
    """
    if manager is None:
        return []
    records = _safe_manager_records(manager, "list_weather")
    if not records and strategic_region_mgr is None:
        return []

    try:
        spacing = float(min_spacing)
    except (TypeError, ValueError, OverflowError):
        spacing = 1.0
    if not math.isfinite(spacing) or spacing <= 0.0:
        spacing = 1.0

    try:
        lifecycle_text = str(lifecycle if lifecycle is not None else "draft").strip().lower()
    except Exception:
        lifecycle_text = "draft"
    severity = (
        "warning"
        if lifecycle_text in ("draft", "candidate", "draft_preview", "foundation_candidate")
        else "blocker"
    )

    province_arr, height, width, _known_provinces = _raster_geometry(province_map)
    known_regions, province_to_region = _extract_region_lookup(strategic_region_mgr)
    expected_regions = {int(region_id) for region_id in province_to_region.values()}
    details: list[str] = []
    affected_regions: set[int] = set()
    affected_points: set[tuple[int, int]] = set()
    valid_by_region: dict[int, list[tuple[float, float, str, tuple[int, int] | None]]] = {}

    for index, record in enumerate(records):
        raw_id = _field(record, "id", None)
        record_id = _as_int(raw_id)
        label = "weather#%d" % (record_id if record_id is not None and record_id > 0 else index)
        region_id = _manager_int(record, "region_id")
        x = _as_number(_field(record, "x", None))
        y = _as_number(_field(record, "y", None))
        point = _pixel_point(x, y) if x is not None and y is not None else None
        if point is not None:
            affected_points.add(point)
        if region_id is None:
            details.append("%s has a missing or illegal region_id" % label)
            continue
        affected_regions.add(int(region_id))
        if x is None or y is None:
            details.append("%s in region %d has missing or malformed coordinates" % (label, region_id))
            continue
        if known_regions is not None and int(region_id) not in known_regions:
            details.append("%s references unknown strategic region %d" % (label, region_id))
            continue
        if (
            province_arr is not None
            and height is not None
            and width is not None
            and not (0.0 <= float(x) < float(width) and 0.0 <= float(y) < float(height))
        ):
            details.append(
                "%s in region %d at (%.2f, %.2f) is out of bounds for %dx%d"
                % (label, region_id, float(x), float(y), int(width), int(height))
            )
            continue
        if province_to_region and province_arr is not None:
            actual_province = _province_at(province_arr, x, y)
            actual_region = (
                province_to_region.get(int(actual_province))
                if actual_province is not None and int(actual_province) > 0
                else None
            )
            if actual_region is None:
                details.append(
                    "%s declares region %d but resolves to an unassigned province"
                    % (label, region_id)
                )
                continue
            if int(actual_region) != int(region_id):
                details.append(
                    "%s declares region %d but resolves to region %d"
                    % (label, region_id, int(actual_region))
                )
                continue
        valid_by_region.setdefault(int(region_id), []).append(
            (float(x), float(y), label, point)
        )

    for region_id in sorted(expected_regions - set(valid_by_region)):
        details.append(
            "strategic region %d has no valid weather position"
            % int(region_id)
        )
        affected_regions.add(int(region_id))

    for region_id in sorted(valid_by_region):
        points = sorted(valid_by_region[region_id], key=lambda item: (item[0], item[1], item[2]))
        for left_index, left in enumerate(points):
            for right in points[left_index + 1 :]:
                distance = math.hypot(right[0] - left[0], right[1] - left[1])
                if distance >= spacing:
                    continue
                details.append(
                    "weather positions %s and %s in region %d are %.3f apart; minimum spacing is %.3f"
                    % (left[2], right[2], region_id, distance, spacing)
                )
                affected_regions.add(int(region_id))
                for point in (left[3], right[3]):
                    if point is not None:
                        affected_points.add(point)

    if not details:
        return []
    return [
        ValidationFinding(
            code="placement.weather",
            severity=severity,
            message="%d manager weather placement issues" % len(details),
            layer=LAYER,
            affected_ids=_capped_ids(affected_regions),
            coordinates=_capped_coords(affected_points),
            evidence=_evidence(sorted(details)),
        )
    ]
