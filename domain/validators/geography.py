"""M3.3c geography and reference validator (map-foundation plan).

Pure, non-mutating checks over an in-memory province raster plus the
existing state, strategic-region, continent, and country managers. The
public entry point is :func:`validate_geography_references`, which returns
a deterministic list of :class:`domain.validation.ValidationFinding`.

Stable finding codes in fixed rule order:

- ``geography.state_membership``: required land provinces with no state,
  geographically disconnected multi-province states, and states spanning
  multiple strategic regions. Severity
  ``error``.
- ``geography.state_reference``: non-positive or gapped state IDs, empty
  states, and state province references that do not resolve to the
  raster. Severity ``error``.
- ``geography.duplicate_membership``: one province claimed by several
  states or several strategic regions, including repeats inside a single
  list. Severity ``error``. State duplicates are reported before region
  duplicates.
- ``geography.region_coverage``: raster provinces with no strategic
  region, and geographically disconnected multi-province regions.
  Severity ``warning`` and waivable, because uncovered or fragmented
  regions are suspicious but sometimes intentional during drafting.
- ``geography.region_reference``: non-positive or gapped region IDs,
  empty regions, and region province references that do not resolve.
  Severity ``error``.
- ``geography.continent_reference``: continent indices outside the known
  names list, and continent province references that do not resolve.
  Severity ``error``. Missing assignments implicitly belong to the
  default continent and are not reported, matching
  ``domain.managers.continent.ContinentManager`` semantics.
- ``geography.country_reference``: state ownership pointing at unknown
  states or unknown country tags, and capital provinces that are missing
  or outside the raster. Severity ``error``.

Reference design notes:

- Required land provinces use the repository majority rule (land pixels
  more than half of the province pixels), matching the country, continent,
  and strategic-region color maps. When no usable tile map is supplied,
  every positive raster province is required.
- Strategic regions must cover every positive raster province (land and
  sea), matching ``export/writers/map/strategic_regions.py``, which
  assigns all centroids. Supply areas are generated at export time from
  the full state list, so every state is covered by construction; the
  deterministic proxy here is strategic-region province coverage.
- Disconnected membership is reported only when deterministically
  established from the supplied province raster with 4-connectivity.
  Single-province groups are skipped so province-level fragmentation
  stays with ``raster.connectivity``. Horizontal wrap adjacency honors
  the selected wrap contract: an explicit ``wrap_horizontal`` argument
  wins, otherwise ``profile.dimensions.wrap_horizontal`` applies, and
  the default is ``True`` for HOI4. The same contract feeds both state
  and strategic-region checks without mutating inputs.
- A state must not span multiple strategic regions unless explicitly
  supported. The cross-region check reuses
  ``geography.state_membership`` (no new public code), runs only when
  both state and strategic-region data resolve, and ignores dangling
  province references so unresolved IDs cannot create false positives.
  Findings name the covering regions with representative coordinates.
- Malformed or object-dtype province rasters never raise while coercing
  IDs; they yield a typed ``geography.state_reference`` finding and the
  validator continues with the coercible IDs.
- The validator never mutates its arrays or managers, never touches Qt,
  and keeps no global mutable state. Findings use fixed rule order with
  sorted affected IDs and coordinates so repeated calls are identical.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from domain.validation import ValidationFinding

__all__ = ["CODES", "validate_geography_references"]

CODES = (
    "geography.state_membership",
    "geography.state_reference",
    "geography.duplicate_membership",
    "geography.region_coverage",
    "geography.region_reference",
    "geography.continent_reference",
    "geography.country_reference",
)

_LAYER_STATES = "states"
_LAYER_REGIONS = "strategic_regions"
_LAYER_CONTINENTS = "continents"
_LAYER_COUNTRIES = "countries"

_FALLBACK_TILE_LAND = 1
_EVIDENCE_LIMIT = 12


def _tile_land() -> int:
    try:
        from data.constants import TILE_LAND as _land
        return int(_land)
    except Exception:
        return int(_FALLBACK_TILE_LAND)


def _resolve_wrap_horizontal(profile: Any = None, wrap_horizontal: bool | None = None) -> bool:
    if wrap_horizontal is not None:
        return bool(wrap_horizontal)
    if profile is not None:
        try:
            return bool(profile.dimensions.wrap_horizontal)
        except Exception:
            pass
    return True


def _coerce_pid(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, float):
        try:
            if value.is_integer():
                return int(value)
        except Exception:
            return None
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _coerce_sid(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, float):
        try:
            if value.is_integer():
                return int(value)
        except Exception:
            return None
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


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
        sid = _coerce_sid(key)
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
            pid = _coerce_pid(entry)
            if pid is None:
                unparseable += 1
            else:
                parsed.append(int(pid))
        groups[int(sid)] = parsed
    return (sorted(groups.keys()), groups, int(unparseable), sorted(set(mismatched)))


def _extract_states(state_mgr: Any) -> tuple[list[int], dict[int, list[int]], int, list[int]] | None:
    if state_mgr is None:
        return None
    raw = _read_mapping(state_mgr, ("states", "_states"))
    if raw is None:
        if isinstance(state_mgr, Mapping):
            raw = state_mgr.get("states", state_mgr) if "states" in state_mgr else state_mgr
        else:
            return None
    return _parse_province_groups(raw, ("provinces", "province_ids"))


def _extract_regions(region_mgr: Any) -> tuple[list[int], dict[int, list[int]], int, list[int]] | None:
    if region_mgr is None:
        return None
    raw = _read_mapping(region_mgr, ("regions", "_regions"))
    if raw is None:
        if isinstance(region_mgr, Mapping):
            raw = region_mgr.get("regions", region_mgr) if "regions" in region_mgr else None
        if raw is None:
            return None
    return _parse_province_groups(raw, ("province_ids", "provinces"))


def _extract_continent(continent_mgr: Any) -> tuple[list[str], dict[int, int], int] | None:
    if continent_mgr is None:
        return None
    names: list[str] = []
    try:
        raw_names = _read_mapping(continent_mgr, ("names", "_names"))
        if raw_names is not None:
            if callable(raw_names) and not isinstance(raw_names, list):
                try:
                    raw_names = raw_names()
                except Exception:
                    raw_names = None
            if raw_names is not None:
                names = [str(v) for v in list(raw_names)]
    except Exception:
        names = []
    mapping: dict[int, int] = {}
    unparseable = 0
    try:
        raw_map = _read_mapping(continent_mgr, ("_province_continent", "province_continent", "mapping", "assignments"))
        if raw_map is None:
            if isinstance(continent_mgr, Mapping):
                raw_map = continent_mgr.get("province_continent", {})
            else:
                raw_map = {}
        if not isinstance(raw_map, Mapping):
            raw_map = {}
        for key, value in list(raw_map.items()):
            pid = _coerce_pid(key)
            if pid is None or isinstance(value, bool):
                unparseable += 1
                continue
            try:
                ci = int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                unparseable += 1
                continue
            mapping[int(pid)] = int(ci)
    except Exception:
        mapping = {}
    return (list(names), dict(mapping), int(unparseable))


def _extract_countries(country_mgr: Any) -> tuple[dict[str, int | None], dict[int, str], list[str], int] | None:
    if country_mgr is None:
        return None
    capitals: dict[str, int | None] = {}
    order: list[str] = []
    unparseable = 0
    try:
        raw_countries = _read_mapping(country_mgr, ("countries", "_countries"))
        if raw_countries is None:
            if isinstance(country_mgr, Mapping):
                raw_countries = country_mgr.get("countries", {})
            else:
                return None
        if not isinstance(raw_countries, Mapping):
            return None
        for tag, obj in list(raw_countries.items()):
            tag_text = str(tag) if tag is not None else ""
            if not tag_text:
                unparseable += 1
                continue
            raw_cap: Any = None
            try:
                if isinstance(obj, Mapping):
                    raw_cap = obj.get("capital", 0)
                else:
                    raw_cap = getattr(obj, "capital", 0)
            except Exception:
                raw_cap = 0
            if raw_cap is None:
                capitals[tag_text] = None
            elif isinstance(raw_cap, bool):
                unparseable += 1
                capitals[tag_text] = None
            else:
                pid = _coerce_pid(raw_cap)
                if pid is None:
                    unparseable += 1
                    capitals[tag_text] = None
                else:
                    capitals[tag_text] = int(pid)
            order.append(tag_text)
    except Exception:
        return None
    owners: dict[int, str] = {}
    try:
        raw_owner = _read_mapping(country_mgr, ("_state_owner", "state_owner", "owners", "state_owners"))
        if isinstance(raw_owner, Mapping):
            for key, value in list(raw_owner.items()):
                sid = _coerce_sid(key)
                if sid is None:
                    unparseable += 1
                    continue
                owners[int(sid)] = str(value) if value is not None else ""
        else:
            get_states = getattr(country_mgr, "get_states_of_country", None)
            if callable(get_states):
                for tag in sorted(set(order)):
                    try:
                        sids = list(get_states(tag))
                    except Exception:
                        continue
                    for entry in sids:
                        sid = _coerce_sid(entry)
                        if sid is None:
                            unparseable += 1
                            continue
                        sid = int(sid)
                        if sid not in owners:
                            owners[sid] = tag
    except Exception:
        owners = {}
    return (dict(capitals), dict(owners), sorted(set(order)), int(unparseable))
def _coerce_raster_pid(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        try:
            as_float = float(value)
        except Exception:
            return None
        if as_float.is_integer():
            return int(as_float)
        return None
    if isinstance(value, np.generic):
        try:
            return _coerce_raster_pid(value.item())
        except Exception:
            return None
    return None


def _present_ids(prov: np.ndarray) -> list[int]:
    try:
        unique = np.unique(prov).tolist()
    except Exception:
        try:
            flat_fallback = np.ravel(prov).tolist()
        except Exception:
            return []
        present_fallback: set[int] = set()
        for item in flat_fallback:
            try:
                pid = _coerce_raster_pid(item)
            except Exception:
                continue
            if pid is not None and int(pid) > 0:
                present_fallback.add(int(pid))
        return sorted(present_fallback)
    present: set[int] = set()
    for item in unique:
        try:
            pid = _coerce_raster_pid(item)
        except Exception:
            continue
        if pid is not None and int(pid) > 0:
            present.add(int(pid))
    return sorted(present)


def _raster_unparseable_count(prov: np.ndarray) -> int:
    try:
        unique = np.unique(prov).tolist()
    except Exception:
        try:
            flat = np.ravel(prov).tolist()
        except Exception:
            return 1
        bad = 0
        for item in flat:
            try:
                pid = _coerce_raster_pid(item)
            except Exception:
                bad += 1
                continue
            if pid is None:
                bad += 1
        return int(bad)
    bad_unique = 0
    for item in unique:
        try:
            pid = _coerce_raster_pid(item)
        except Exception:
            bad_unique += 1
            continue
        if pid is None:
            bad_unique += 1
    return int(bad_unique)


def _first_coordinates(prov: np.ndarray, width: int) -> dict[int, tuple[int, int]]:
    flat = prov.ravel()
    first: dict[int, int] = {}
    try:
        total = int(flat.shape[0])
    except Exception:
        return {}
    for index in range(total):
        try:
            pid = int(flat[index])
        except Exception:
            continue
        if pid > 0 and pid not in first:
            first[pid] = int(index)
    out: dict[int, tuple[int, int]] = {}
    for pid, index in first.items():
        y, x = divmod(int(index), int(width))
        out[int(pid)] = (int(x), int(y))
    return out


def _required_land_ids(prov: np.ndarray, tile: np.ndarray | None, present: list[int]) -> set[int]:
    if tile is None:
        return set(present)
    try:
        if tile.ndim != 2 or tile.shape != prov.shape:
            return set(present)
    except Exception:
        return set(present)
    land_value = _tile_land()
    try:
        flat_pm = prov.ravel().astype(np.int64, copy=False)
        flat_tm = tile.ravel()
    except Exception:
        return set(present)
    if not present:
        return set()
    try:
        max_id = int(max(present))
    except Exception:
        return set(present)
    size = max_id + 1
    try:
        total = np.bincount(flat_pm, minlength=size)
        land = np.bincount(flat_pm, weights=(flat_tm == land_value).astype(np.int64), minlength=size)
    except Exception:
        return set(present)
    required: set[int] = set()
    for pid in present:
        pid = int(pid)
        if pid <= 0 or pid >= size:
            continue
        try:
            count = int(total[pid])
            land_count = int(land[pid])
        except Exception:
            continue
        if count > 0 and land_count * 2 > count:
            required.add(int(pid))
    return required


def _count_components_fallback(mask: np.ndarray, wrap_horizontal: bool = False) -> int:
    try:
        height, width = int(mask.shape[0]), int(mask.shape[1])
    except Exception:
        return 0
    try:
        grid = np.asarray(mask, dtype=bool)
    except Exception:
        return 0
    if not bool(np.any(grid)):
        return 0
    wrap = bool(wrap_horizontal) and int(width) > 1
    seen = np.zeros((height, width), dtype=bool)
    components = 0
    for y in range(height):
        for x in range(width):
            if not bool(grid[y, x]) or bool(seen[y, x]):
                continue
            components += 1
            stack = [(y, x)]
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                if cy > 0 and bool(grid[cy - 1, cx]) and not bool(seen[cy - 1, cx]):
                    seen[cy - 1, cx] = True
                    stack.append((cy - 1, cx))
                if cy + 1 < height and bool(grid[cy + 1, cx]) and not bool(seen[cy + 1, cx]):
                    seen[cy + 1, cx] = True
                    stack.append((cy + 1, cx))
                if wrap:
                    for nx in ((cx - 1) % width, (cx + 1) % width):
                        if bool(grid[cy, nx]) and not bool(seen[cy, nx]):
                            seen[cy, nx] = True
                            stack.append((cy, nx))
                else:
                    if cx > 0 and bool(grid[cy, cx - 1]) and not bool(seen[cy, cx - 1]):
                        seen[cy, cx - 1] = True
                        stack.append((cy, cx - 1))
                    if cx + 1 < width and bool(grid[cy, cx + 1]) and not bool(seen[cy, cx + 1]):
                        seen[cy, cx + 1] = True
                        stack.append((cy, cx + 1))
    return int(components)


def _count_wrapped_components(labeled: np.ndarray, total: int, wrap_horizontal: bool) -> int:
    try:
        total_int = int(total)
    except Exception:
        return 0
    if not bool(wrap_horizontal) or total_int <= 1:
        return int(total_int)
    try:
        height, width = int(labeled.shape[0]), int(labeled.shape[1])
    except Exception:
        return int(total_int)
    if width <= 1 or height <= 0:
        return int(total_int)
    parent = list(range(total_int + 1))
    def _find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return int(value)
    try:
        for y in range(height):
            left = int(labeled[y, 0])
            right = int(labeled[y, width - 1])
            if left != 0 and right != 0 and left != right:
                left_root = _find(int(left))
                right_root = _find(int(right))
                if left_root != right_root:
                    if left_root < right_root:
                        parent[right_root] = left_root
                    else:
                        parent[left_root] = right_root
    except Exception:
        return int(total_int)
    try:
        roots = {_find(label) for label in range(1, total_int + 1)}
    except Exception:
        return int(total_int)
    return int(len(roots))


def _disconnected_group_ids(
    prov: np.ndarray,
    groups: dict[int, list[int]],
    present_set: set[int],
    wrap_horizontal: bool = True,
) -> list[int]:
    disconnected: list[int] = []
    try:
        structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
        from scipy.ndimage import label as _label
        use_scipy = True
    except Exception:
        _label = None  # type: ignore[assignment]
        structure = None  # type: ignore[assignment]
        use_scipy = False
    wrap = bool(wrap_horizontal)
    for gid in sorted(groups.keys()):
        try:
            pids = sorted({int(p) for p in groups.get(gid, []) if int(p) in present_set})
        except Exception:
            continue
        if len(pids) <= 1:
            continue
        try:
            mask = np.isin(prov, pids)
        except Exception:
            continue
        if not bool(np.any(mask)):
            continue
        try:
            if use_scipy:
                labeled, count = _label(mask, structure=structure)  # type: ignore[misc]
                total = _count_wrapped_components(labeled, int(count), wrap)
            else:
                total = int(_count_components_fallback(mask, wrap_horizontal=wrap))
        except Exception:
            continue
        if total > 1:
            disconnected.append(int(gid))
    return sorted(disconnected)


def _short_list(values: list[Any], limit: int = _EVIDENCE_LIMIT) -> str:
    shown = [str(v) for v in values[:limit]]
    text = ",".join(shown)
    if len(values) > limit:
        text += ",..."
    return text
def validate_geography_references(
    province_map: Any,
    tile_map: Any | None = None,
    *,
    state_mgr: Any | None = None,
    country_mgr: Any | None = None,
    continent_mgr: Any | None = None,
    strategic_region_mgr: Any | None = None,
    profile: Any | None = None,
    wrap_horizontal: bool | None = None,
    **_ignored: Any,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    try:
        prov = np.asarray(province_map)
    except Exception:
        return [
            ValidationFinding(
                code="geography.state_reference",
                severity="error",
                message="province_map must be array-like for geography validation",
                layer=_LAYER_STATES,
                evidence="non-array province_map",
            )
        ]
    if prov.ndim != 2:
        return [
            ValidationFinding(
                code="geography.state_reference",
                severity="error",
                message="province_map must be a 2-D array",
                layer=_LAYER_STATES,
                evidence="province_ndim=%s" % (getattr(prov, "ndim", "?"),),
            )
        ]
    try:
        height, width = int(prov.shape[0]), int(prov.shape[1])
    except Exception:
        return [
            ValidationFinding(
                code="geography.state_reference",
                severity="error",
                message="province_map shape is not readable",
                layer=_LAYER_STATES,
                evidence="unreadable shape",
            )
        ]
    if height <= 0 or width <= 0 or prov.size == 0:
        return [
            ValidationFinding(
                code="geography.state_reference",
                severity="error",
                message="province_map must be non-empty",
                layer=_LAYER_STATES,
                evidence="shape=%dx%d" % (int(width), int(height)),
            )
        ]
    try:
        prov_int = prov.astype(np.int32, copy=False)
    except Exception:
        prov_int = prov
    wrap = _resolve_wrap_horizontal(profile, wrap_horizontal)
    try:
        raster_unparseable = _raster_unparseable_count(prov_int)
    except Exception:
        raster_unparseable = 0
    if int(raster_unparseable) > 0:
        findings.append(
            ValidationFinding(
                code="geography.state_reference",
                severity="error",
                message="province_map contains unparseable province IDs",
                layer=_LAYER_STATES,
                evidence="unparseable_province_ids=%d" % int(raster_unparseable),
            )
        )
    present = _present_ids(prov_int)
    present_set = set(present)
    coords = _first_coordinates(prov_int, width)
    tile_arr: np.ndarray | None = None
    if tile_map is not None:
        try:
            candidate = np.asarray(tile_map)
            if candidate.ndim == 2 and candidate.shape == prov_int.shape and candidate.size > 0:
                tile_arr = candidate
        except Exception:
            tile_arr = None
    required_land = _required_land_ids(prov_int, tile_arr, present)

    state_ids: list[int] = []
    state_groups: dict[int, list[int]] = {}
    state_lookup_ok = False
    if state_mgr is not None:
        try:
            parsed = _extract_states(state_mgr)
        except Exception:
            parsed = None
        if parsed is not None:
            state_ids, state_groups, state_unparseable, state_mismatched = parsed
            state_lookup_ok = True
            assigned = {int(p) for pids in state_groups.values() for p in pids if int(p) > 0}
            missing = sorted(required_land - assigned)
            if missing:
                findings.append(
                    ValidationFinding(
                        code="geography.state_membership",
                        severity="error",
                        message="%d land provinces have no state" % len(missing),
                        layer=_LAYER_STATES,
                        affected_ids=tuple(missing),
                        coordinates=tuple(coords[p] for p in missing if p in coords),
                        evidence="missing=%s; required=%d; assigned=%d" % (_short_list(missing), len(required_land), len(assigned)),
                    )
                )
            disconnected_states = _disconnected_group_ids(prov_int, state_groups, present_set, wrap)
            if disconnected_states:
                rep_coords: list[tuple[int, int]] = []
                for sid in disconnected_states:
                    try:
                        candidates = sorted({int(p) for p in state_groups.get(sid, []) if int(p) in present_set and int(p) in coords})
                    except Exception:
                        candidates = []
                    if candidates:
                        rep_coords.append(coords[candidates[0]])
                rep_coords = sorted(set(rep_coords))
                findings.append(
                    ValidationFinding(
                        code="geography.state_membership",
                        severity="error",
                        message="%d states are geographically disconnected" % len(disconnected_states),
                        layer=_LAYER_STATES,
                        affected_ids=tuple(disconnected_states),
                        coordinates=tuple(rep_coords),
                        evidence="disconnected_states=%s" % (_short_list(disconnected_states),),
                    )
                )
            invalid_sids = sorted(s for s in state_ids if int(s) <= 0)
            empty_sids = sorted(s for s in state_ids if not state_groups.get(s))
            gaps: list[int] = []
            positive_sids = sorted(s for s in state_ids if int(s) > 0)
            if positive_sids:
                try:
                    top = int(max(positive_sids))
                    full = set(range(1, top + 1))
                    gaps = sorted(full - set(positive_sids))
                except Exception:
                    gaps = []
            dangling = sorted({int(p) for pids in state_groups.values() for p in pids if int(p) > 0 and int(p) not in present_set})
            invalid_pids = sorted({int(p) for pids in state_groups.values() for p in pids if int(p) <= 0})
            ref_ids = sorted(set(invalid_sids) | set(gaps) | set(empty_sids) | set(dangling) | set(invalid_pids) | set(int(v) for v in state_mismatched))
            parts: list[str] = []
            if invalid_sids:
                parts.append("invalid_state_ids=%s" % (_short_list(invalid_sids),))
            if gaps:
                parts.append("missing_state_ids=%s" % (_short_list(gaps),))
            if empty_sids:
                parts.append("empty_states=%s" % (_short_list(empty_sids),))
            if state_mismatched:
                parts.append("id_mismatch=%s" % (_short_list(sorted(set(int(v) for v in state_mismatched))),))
            if dangling:
                parts.append("unknown_province_refs=%s" % (_short_list(dangling),))
            if invalid_pids:
                parts.append("invalid_province_refs=%s" % (_short_list(invalid_pids),))
            if int(state_unparseable) > 0:
                parts.append("unparseable_entries=%d" % int(state_unparseable))
            if ref_ids or parts:
                has_problem = bool(invalid_sids or gaps or empty_sids or state_mismatched or dangling or invalid_pids or int(state_unparseable) > 0)
                if has_problem:
                    findings.append(
                        ValidationFinding(
                            code="geography.state_reference",
                            severity="error",
                            message="state references do not resolve",
                            layer=_LAYER_STATES,
                            affected_ids=tuple(ref_ids),
                            evidence="; ".join(parts) if parts else "state_refs_invalid",
                        )
                    )
            counts: dict[int, int] = {}
            owners_of: dict[int, list[int]] = {}
            for sid in sorted(state_groups.keys()):
                try:
                    seen_in_state: dict[int, int] = {}
                    for p in state_groups.get(sid, []):
                        p = int(p)
                        if p <= 0:
                            continue
                        counts[p] = counts.get(p, 0) + 1
                        seen_in_state[p] = seen_in_state.get(p, 0) + 1
                    for p, times in seen_in_state.items():
                        if times > 1:
                            owners_of.setdefault(int(p), []).append(int(sid))
                        elif counts.get(p, 0) > 1:
                            pass
                except Exception:
                    continue
            try:
                pid_to_states: dict[int, list[int]] = {}
                for sid in sorted(state_groups.keys()):
                    for p in state_groups.get(sid, []):
                        p = int(p)
                        if p <= 0:
                            continue
                        pid_to_states.setdefault(int(p), []).append(int(sid))
                duplicates = sorted(p for p, sids in pid_to_states.items() if len(sids) > 1 or len(set(sids)) != len(sids))
                dup_unique: list[int] = []
                for p in duplicates:
                    try:
                        sids = sorted(set(pid_to_states.get(int(p), [])))
                        if len(sids) > 1:
                            dup_unique.append(int(p))
                        else:
                            total = sum(1 for sid in pid_to_states.get(int(p), []) for _ in [1])
                            if total > 1:
                                dup_unique.append(int(p))
                    except Exception:
                        continue
                duplicates = sorted(set(dup_unique))
            except Exception:
                duplicates = []
            if duplicates:
                details: list[str] = []
                for p in duplicates[:6]:
                    try:
                        sids = sorted(set(pid_to_states.get(int(p), [])))
                        details.append("%d:states=%s" % (int(p), _short_list(sids)))
                    except Exception:
                        continue
                findings.append(
                    ValidationFinding(
                        code="geography.duplicate_membership",
                        severity="error",
                        message="%d provinces belong to several states" % len(duplicates),
                        layer=_LAYER_STATES,
                        affected_ids=tuple(duplicates),
                        coordinates=tuple(coords[p] for p in duplicates if p in coords),
                        evidence="duplicates=%s; %s" % (_short_list(duplicates), "; ".join(details)),
                    )
                )
    region_ids: list[int] = []
    region_groups: dict[int, list[int]] = {}
    region_lookup_ok = False
    if strategic_region_mgr is not None:
        try:
            parsed_regions = _extract_regions(strategic_region_mgr)
        except Exception:
            parsed_regions = None
        if parsed_regions is not None:
            region_ids, region_groups, region_unparseable, region_mismatched = parsed_regions
            region_lookup_ok = True
            covered = {int(p) for pids in region_groups.values() for p in pids if int(p) > 0}
            uncovered = sorted(set(present) - covered)
            if uncovered:
                findings.append(
                    ValidationFinding(
                        code="geography.region_coverage",
                        severity="warning",
                        message="%d provinces have no strategic region" % len(uncovered),
                        layer=_LAYER_REGIONS,
                        affected_ids=tuple(uncovered),
                        coordinates=tuple(coords[p] for p in uncovered if p in coords),
                        evidence="uncovered=%s; present=%d; covered=%d" % (_short_list(uncovered), len(present), len(covered)),
                        waivable=True,
                    )
                )
            disconnected_regions = _disconnected_group_ids(prov_int, region_groups, present_set, wrap)
            if disconnected_regions:
                rep: list[tuple[int, int]] = []
                for rid in disconnected_regions:
                    try:
                        cands = sorted({int(p) for p in region_groups.get(rid, []) if int(p) in present_set and int(p) in coords})
                    except Exception:
                        cands = []
                    if cands:
                        rep.append(coords[cands[0]])
                rep = sorted(set(rep))
                findings.append(
                    ValidationFinding(
                        code="geography.region_coverage",
                        severity="warning",
                        message="%d strategic regions are geographically disconnected" % len(disconnected_regions),
                        layer=_LAYER_REGIONS,
                        affected_ids=tuple(disconnected_regions),
                        coordinates=tuple(rep),
                        evidence="disconnected_regions=%s" % (_short_list(disconnected_regions),),
                        waivable=True,
                    )
                )
            invalid_rids = sorted(r for r in region_ids if int(r) <= 0)
            empty_rids = sorted(r for r in region_ids if not region_groups.get(r))
            region_gaps: list[int] = []
            positive_rids = sorted(r for r in region_ids if int(r) > 0)
            if positive_rids:
                try:
                    top_r = int(max(positive_rids))
                    region_gaps = sorted(set(range(1, top_r + 1)) - set(positive_rids))
                except Exception:
                    region_gaps = []
            dangling_r = sorted({int(p) for pids in region_groups.values() for p in pids if int(p) > 0 and int(p) not in present_set})
            invalid_rpids = sorted({int(p) for pids in region_groups.values() for p in pids if int(p) <= 0})
            region_ref_ids = sorted(set(invalid_rids) | set(region_gaps) | set(empty_rids) | set(dangling_r) | set(invalid_rpids) | set(int(v) for v in region_mismatched))
            region_parts: list[str] = []
            if invalid_rids:
                region_parts.append("invalid_region_ids=%s" % (_short_list(invalid_rids),))
            if region_gaps:
                region_parts.append("missing_region_ids=%s" % (_short_list(region_gaps),))
            if empty_rids:
                region_parts.append("empty_regions=%s" % (_short_list(empty_rids),))
            if region_mismatched:
                region_parts.append("id_mismatch=%s" % (_short_list(sorted(set(int(v) for v in region_mismatched))),))
            if dangling_r:
                region_parts.append("unknown_province_refs=%s" % (_short_list(dangling_r),))
            if invalid_rpids:
                region_parts.append("invalid_province_refs=%s" % (_short_list(invalid_rpids),))
            if int(region_unparseable) > 0:
                region_parts.append("unparseable_entries=%d" % int(region_unparseable))
            if invalid_rids or region_gaps or empty_rids or region_mismatched or dangling_r or invalid_rpids or int(region_unparseable) > 0:
                findings.append(
                    ValidationFinding(
                        code="geography.region_reference",
                        severity="error",
                        message="strategic-region references do not resolve",
                        layer=_LAYER_REGIONS,
                        affected_ids=tuple(region_ref_ids),
                        evidence="; ".join(region_parts) if region_parts else "region_refs_invalid",
                    )
                )
            try:
                region_pid_to_rids: dict[int, list[int]] = {}
                for rid in sorted(region_groups.keys()):
                    for p in region_groups.get(rid, []):
                        p = int(p)
                        if p <= 0:
                            continue
                        region_pid_to_rids.setdefault(int(p), []).append(int(rid))
                region_dups = sorted(p for p, rids in region_pid_to_rids.items() if len(set(rids)) > 1)
            except Exception:
                region_dups = []
                region_pid_to_rids = {}
            if region_dups:
                rdetails: list[str] = []
                for p in region_dups[:6]:
                    try:
                        rids = sorted(set(region_pid_to_rids.get(int(p), [])))
                        rdetails.append("%d:regions=%s" % (int(p), _short_list(rids)))
                    except Exception:
                        continue
                findings.append(
                    ValidationFinding(
                        code="geography.duplicate_membership",
                        severity="error",
                        message="%d provinces belong to several strategic regions" % len(region_dups),
                        layer=_LAYER_REGIONS,
                        affected_ids=tuple(region_dups),
                        coordinates=tuple(coords[p] for p in region_dups if p in coords),
                        evidence="duplicates=%s; %s" % (_short_list(region_dups), "; ".join(rdetails)),
                    )
                )
    if state_lookup_ok and region_lookup_ok:
        try:
            pid_to_region_sets: dict[int, set[int]] = {}
            for rid in sorted(region_groups.keys()):
                try:
                    rids_pids = region_groups.get(rid, [])
                except Exception:
                    continue
                for entry in rids_pids:
                    try:
                        pid_int = int(entry)
                    except Exception:
                        continue
                    if pid_int <= 0 or pid_int not in present_set:
                        continue
                    pid_to_region_sets.setdefault(int(pid_int), set()).add(int(rid))
            pid_to_single_region: dict[int, int] = {}
            for pid_key, rid_set in pid_to_region_sets.items():
                if len(rid_set) == 1:
                    pid_to_single_region[int(pid_key)] = int(next(iter(rid_set)))
            crossing_states: list[int] = []
            crossing_regions: dict[int, list[int]] = {}
            for sid in sorted(state_groups.keys()):
                try:
                    state_pids = [int(entry) for entry in state_groups.get(sid, [])]
                except Exception:
                    continue
                covering: set[int] = set()
                for pid_value in state_pids:
                    try:
                        pid_checked = int(pid_value)
                    except Exception:
                        continue
                    if pid_checked <= 0 or pid_checked not in present_set:
                        continue
                    rid_hit = pid_to_single_region.get(int(pid_checked))
                    if rid_hit is not None:
                        covering.add(int(rid_hit))
                if len(covering) > 1:
                    crossing_states.append(int(sid))
                    crossing_regions[int(sid)] = sorted(covering)
            crossing_states = sorted(set(crossing_states))
            if crossing_states:
                cross_coords: list[tuple[int, int]] = []
                for sid in crossing_states:
                    try:
                        cands = sorted({int(entry) for entry in state_groups.get(sid, []) if int(entry) in present_set and int(entry) in coords})
                    except Exception:
                        cands = []
                    if cands:
                        cross_coords.append(coords[cands[0]])
                cross_coords = sorted(set(cross_coords))
                cross_details: list[str] = []
                for sid in crossing_states:
                    cross_details.append("%d:regions=%s" % (int(sid), _short_list(crossing_regions.get(int(sid), []))))
                findings.append(
                    ValidationFinding(
                        code="geography.state_membership",
                        severity="error",
                        message="%d states span multiple strategic regions" % len(crossing_states),
                        layer=_LAYER_STATES,
                        affected_ids=tuple(crossing_states),
                        coordinates=tuple(cross_coords),
                        evidence="cross_region_states=%s; %s" % (_short_list(crossing_states), "; ".join(cross_details)),
                    )
                )
        except Exception:
            pass
    if continent_mgr is not None:
        try:
            parsed_continent = _extract_continent(continent_mgr)
        except Exception:
            parsed_continent = None
        if parsed_continent is not None:
            names, cmap, cont_unparseable = parsed_continent
            bad_pids: set[int] = set()
            bad_index_pids: list[int] = []
            dangling_c: list[int] = []
            invalid_c: list[int] = []
            total_names = len(names)
            for pid, ci in cmap.items():
                pid = int(pid)
                ci = int(ci)
                if pid <= 0:
                    invalid_c.append(pid)
                    bad_pids.add(pid)
                elif pid not in present_set:
                    dangling_c.append(pid)
                    bad_pids.add(pid)
                elif ci < 0 or ci >= total_names:
                    bad_index_pids.append(pid)
                    bad_pids.add(pid)
            bad_sorted = sorted(bad_pids)
            cont_parts: list[str] = []
            if not total_names:
                cont_parts.append("no_continents_defined")
            if bad_index_pids:
                cont_parts.append("out_of_range=%s; continents=%d" % (_short_list(sorted(bad_index_pids)), int(total_names)))
            if dangling_c:
                cont_parts.append("unknown_province_refs=%s" % (_short_list(sorted(dangling_c)),))
            if invalid_c:
                cont_parts.append("invalid_province_refs=%s" % (_short_list(sorted(invalid_c)),))
            if int(cont_unparseable) > 0:
                cont_parts.append("unparseable_entries=%d" % int(cont_unparseable))
            if bad_sorted or (not total_names and cmap) or int(cont_unparseable) > 0 or (not total_names):
                needs = bool(bad_sorted or int(cont_unparseable) > 0 or not total_names)
                if needs:
                    coord_pids = sorted(p for p in bad_index_pids if p in coords)
                    findings.append(
                        ValidationFinding(
                            code="geography.continent_reference",
                            severity="error",
                            message="continent assignments do not resolve",
                            layer=_LAYER_CONTINENTS,
                            affected_ids=tuple(bad_sorted),
                            coordinates=tuple(coords[p] for p in coord_pids),
                            evidence="; ".join(cont_parts) if cont_parts else "continent_refs_invalid",
                        )
                    )
    if country_mgr is not None:
        try:
            parsed_countries = _extract_countries(country_mgr)
        except Exception:
            parsed_countries = None
        if parsed_countries is not None:
            capitals, owners, tags, country_unparseable = parsed_countries
            known_tags = set(tags)
            unknown_tags: list[str] = []
            dangling_states: list[int] = []
            invalid_owned: list[int] = []
            for sid, tag in owners.items():
                sid = int(sid)
                tag_text = str(tag) if tag is not None else ""
                if sid <= 0:
                    invalid_owned.append(sid)
                elif state_lookup_ok and sid not in set(state_ids):
                    dangling_states.append(sid)
                if tag_text not in known_tags:
                    if tag_text not in unknown_tags:
                        unknown_tags.append(tag_text)
            unknown_tags = sorted(unknown_tags)
            bad_capitals: list[int] = []
            missing_capitals: list[str] = []
            mismatched_capitals: list[int] = []
            pid_to_state: dict[int, int] = {}
            if state_lookup_ok:
                try:
                    for sid in sorted(state_groups.keys()):
                        for p in state_groups.get(sid, []):
                            p = int(p)
                            if p <= 0:
                                continue
                            if p not in pid_to_state:
                                pid_to_state[p] = int(sid)
                            else:
                                if int(sid) < int(pid_to_state[p]):
                                    pid_to_state[p] = int(sid)
                except Exception:
                    pid_to_state = {}
            for tag in sorted(capitals.keys()):
                cap = capitals.get(tag)
                if cap is None or int(cap) <= 0:
                    bad_capitals.append(0)
                    missing_capitals.append(str(tag))
                elif int(cap) not in present_set:
                    bad_capitals.append(int(cap))
                else:
                    if state_lookup_ok and pid_to_state:
                        try:
                            owner_sid = pid_to_state.get(int(cap), 0)
                            expected_owner = owners.get(int(owner_sid), "") if owner_sid else ""
                            if owner_sid and expected_owner != tag:
                                mismatched_capitals.append(int(cap))
                        except Exception:
                            pass
            country_ref_ids = sorted(set([s for s in dangling_states if s != 0] + [s for s in invalid_owned if s != 0] + [c for c in bad_capitals if c != 0] + mismatched_capitals))
            country_parts: list[str] = []
            if dangling_states:
                country_parts.append("unknown_state_refs=%s" % (_short_list(sorted(dangling_states)),))
            if invalid_owned:
                country_parts.append("invalid_state_refs=%s" % (_short_list(sorted(invalid_owned)),))
            if unknown_tags:
                country_parts.append("unknown_country_tags=%s" % (_short_list(unknown_tags),))
            if missing_capitals:
                country_parts.append("missing_capitals=%s" % (_short_list(sorted(missing_capitals)),))
            dangling_caps = sorted(c for c in bad_capitals if c != 0 and c not in mismatched_capitals)
            if dangling_caps:
                country_parts.append("unknown_capital_provinces=%s" % (_short_list(dangling_caps),))
            if mismatched_capitals:
                country_parts.append("capital_state_mismatch=%s" % (_short_list(sorted(mismatched_capitals)),))
            if int(country_unparseable) > 0:
                country_parts.append("unparseable_entries=%d" % int(country_unparseable))
            has_country_problem = bool(dangling_states or invalid_owned or unknown_tags or missing_capitals or dangling_caps or mismatched_capitals or int(country_unparseable) > 0)
            if has_country_problem:
                cap_coords = sorted({coords[c] for c in mismatched_capitals + dangling_caps if c in coords})
                findings.append(
                    ValidationFinding(
                        code="geography.country_reference",
                        severity="error",
                        message="country references do not resolve",
                        layer=_LAYER_COUNTRIES,
                        affected_ids=tuple(country_ref_ids),
                        coordinates=tuple(cap_coords),
                        evidence="; ".join(country_parts) if country_parts else "country_refs_invalid",
                    )
                )
    ordered: list[ValidationFinding] = []
    order = {code: index for index, code in enumerate(CODES)}
    buckets: dict[str, list[ValidationFinding]] = {code: [] for code in CODES}
    for item in findings:
        buckets[item.code].append(item) if item.code in buckets else None
    for code in CODES:
        ordered.extend(buckets.get(code, []))
    return ordered
