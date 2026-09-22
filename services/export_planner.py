"""Immutable export planner (M2.1/M2.2).

Resolves target/profile, deep-copy snapshots the project, runs pre-write
validation, and produces typed repair/asset proposals without writing files.
The live project is never mutated: planning and repair application operate
exclusively on snapshot copies.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field, fields, is_dataclass

import numpy as np

from domain import dds_format as dds_format
from domain import map_art_matrix as map_art_matrix
from domain.export_contract import (
    EXPORT_LIFECYCLES,
    EXPORT_PROFILES,
    REPAIR_POLICIES,
    REPAIR_SAFETY_LEVELS,
    AssetResolution,
    ExportPlan,
    PlanRejected,
    RepairAction,
    ValidationNote,
    resolve_layers,
    select_acceptance_tags,
)


def _copy_array(values):
    if values is None:
        return None
    arr = np.array(values, copy=True, subok=False)
    return arr


def _freeze_array(arr):
    if arr is not None:
        try:
            arr.setflags(write=False)
        except (ValueError, TypeError):
            pass
    return arr


def _thaw_array(arr):
    if arr is None:
        return None
    out = np.array(arr, copy=True, subok=False)
    try:
        out.setflags(write=True)
    except (ValueError, TypeError):
        pass
    return out


def _deepcopy_manager(manager):
    if manager is None:
        return None
    return copy.deepcopy(manager)


def _hash_array(arr) -> str:
    if arr is None:
        return "none"
    try:
        digest = hashlib.sha256()
        digest.update(str(arr.shape).encode("utf-8"))
        digest.update(str(arr.dtype).encode("utf-8"))
        digest.update(np.ascontiguousarray(arr).tobytes())
        return digest.hexdigest()
    except (TypeError, ValueError):
        return "unhashable"


def _canonicalize(value, active=None):
    """Return a stable, JSON-compatible representation of project state.

    Manager ``count()`` values are not enough to prove that a live project was
    untouched: resources, references, settings, and capitals can change while
    all counts remain identical.  This deliberately includes manager object
    attributes while breaking cycles and excluding volatile event/cache links.
    """
    if active is None:
        active = set()
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, np.generic):
        return _canonicalize(value.item(), active)
    if isinstance(value, np.ndarray):
        arr = np.ascontiguousarray(value)
        return {
            "__ndarray__": True,
            "dtype": str(arr.dtype),
            "shape": list(arr.shape),
            "sha256": hashlib.sha256(arr.tobytes()).hexdigest(),
        }
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {"__bytes__": True, "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest()}
    object_id = id(value)
    if object_id in active:
        return "<cycle>"
    active.add(object_id)
    try:
        if is_dataclass(value) and not isinstance(value, type):
            return {
                "__class__": value.__class__.__module__ + "." + value.__class__.__qualname__,
                "fields": {item.name: _canonicalize(getattr(value, item.name), active)
                            for item in fields(value)},
            }
        if isinstance(value, dict):
            items = [
                (str(key), _canonicalize(item, active))
                for key, item in value.items()
            ]
            return {"__dict__": sorted(items, key=lambda item: item[0])}
        if isinstance(value, (list, tuple)):
            return [_canonicalize(item, active) for item in value]
        if isinstance(value, (set, frozenset)):
            items = [_canonicalize(item, active) for item in value]
            return sorted(items, key=lambda item: repr(item))
        attrs = getattr(value, "__dict__", None)
        if isinstance(attrs, dict):
            ignored = {"_cache", "_cached", "_event_bus", "_listeners"}
            return {
                "__class__": value.__class__.__module__ + "." + value.__class__.__qualname__,
                "attrs": {
                    str(key): _canonicalize(item, active)
                    for key, item in sorted(attrs.items(), key=lambda pair: str(pair[0]))
                    if str(key) not in ignored and not callable(item)
                },
            }
        return {"__class__": value.__class__.__module__ + "." + value.__class__.__qualname__}
    finally:
        active.remove(object_id)


def _manager_digest(managers: dict) -> str:
    canonical = {
        str(key): _canonicalize(manager)
        for key, manager in sorted(managers.items(), key=lambda pair: str(pair[0]))
        if manager is not None
    }
    payload = json.dumps(canonical, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":"), allow_nan=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _auxiliary_digest(values: dict) -> str:
    payload = json.dumps(_canonicalize(values), ensure_ascii=True, sort_keys=True,
                         separators=(",", ":"), allow_nan=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_fingerprint(tile_map, province_map, terrain_map, managers: dict, extra: str = "") -> str:
    digest = hashlib.sha256()
    digest.update(_hash_array(tile_map).encode("utf-8"))
    digest.update(_hash_array(province_map).encode("utf-8"))
    digest.update(_hash_array(terrain_map).encode("utf-8"))
    digest.update(_manager_digest(managers).encode("utf-8"))
    digest.update(str(extra).encode("utf-8"))
    return digest.hexdigest()


@dataclass
class FoundationSnapshot:
    width: int = 0
    height: int = 0
    tile_map: object = None
    province_map: object = None
    terrain_map: object = None
    height_map: object = None
    river_map: object = None
    provincial_terrain: dict = field(default_factory=dict)
    state_mgr: object = None
    country_mgr: object = None
    continent_mgr: object = None
    adjacency_mgr: object = None
    railway_mgr: object = None
    supply_mgr: object = None
    adjacency_rule_mgr: object = None
    strategic_region_mgr: object = None
    logistics_exception_mgr: object = None
    map_placement_mgr: object = None
    colormap_settings: object = None
    default_map_settings: object = None
    assets: dict = field(default_factory=dict)
    dirty_assets: frozenset = frozenset()
    project_meta: object = None
    profile_id: str = "hoi4-1.19"
    province_type_overrides: dict = field(default_factory=dict)
    fingerprint: str = ""
    live_fingerprint: str = ""
    live_auxiliary_fingerprint: str = ""

    def managers_dict(self) -> dict:
        return {
            "state_mgr": self.state_mgr,
            "country_mgr": self.country_mgr,
            "continent_mgr": self.continent_mgr,
            "adjacency_mgr": self.adjacency_mgr,
            "railway_mgr": self.railway_mgr,
            "supply_mgr": self.supply_mgr,
            "adjacency_rule_mgr": self.adjacency_rule_mgr,
            "strategic_region_mgr": self.strategic_region_mgr,
            "logistics_exception_mgr": self.logistics_exception_mgr,
            "map_placement_mgr": self.map_placement_mgr,
        }

    def mutable_arrays(self) -> dict:
        return {
            "tile_map": _thaw_array(self.tile_map),
            "province_map": _thaw_array(self.province_map),
            "terrain_map": _thaw_array(self.terrain_map),
            "height_map": _thaw_array(self.height_map),
            "river_map": _thaw_array(self.river_map),
        }

    def fork_managers(self) -> dict:
        return {key: _deepcopy_manager(manager) for key, manager in self.managers_dict().items()}

    def check_live_unchanged(self, live_arrays: dict, live_managers: dict) -> list:
        current = compute_fingerprint(
            live_arrays.get("tile_map"),
            live_arrays.get("province_map"),
            live_arrays.get("terrain_map"),
            live_managers,
        )
        if current != self.live_fingerprint:
            return ["live project changed after snapshot approval (snapshot %s... != live %s...)"
                    % (self.live_fingerprint[:12], current[:12])]
        auxiliary_keys = (
            "height_map", "river_map", "provincial_terrain", "colormap_settings",
            "default_map_settings", "assets", "dirty_assets",
        )
        provided = {key: live_arrays[key] for key in auxiliary_keys if key in live_arrays}
        if provided:
            expected = {
                "height_map": self.height_map,
                "river_map": self.river_map,
                "provincial_terrain": self.provincial_terrain,
                "colormap_settings": self.colormap_settings,
                "default_map_settings": self.default_map_settings,
                "assets": self.assets,
                "dirty_assets": self.dirty_assets,
            }
            if _auxiliary_digest(provided) != _auxiliary_digest(
                    {key: expected[key] for key in provided}):
                return ["live project auxiliary export inputs changed after snapshot approval"]
        return []


def take_snapshot(tile_map, province_map, terrain_map=None, height_map=None, river_map=None,
                  managers: dict | None = None, provincial_terrain=None,
                  colormap_settings=None, default_map_settings=None,
                  assets=None, dirty_assets=None, project_meta=None,
                  profile_id: str = "hoi4-1.19", map_placement_mgr=None) -> FoundationSnapshot:
    managers = dict(managers or {})
    if map_placement_mgr is not None:
        managers["map_placement_mgr"] = map_placement_mgr
    snapshot = FoundationSnapshot(
        width=int(province_map.shape[1]),
        height=int(province_map.shape[0]),
        tile_map=_freeze_array(_copy_array(tile_map)),
        province_map=_freeze_array(_copy_array(province_map)),
        terrain_map=_freeze_array(_copy_array(terrain_map)),
        height_map=_freeze_array(_copy_array(height_map)),
        river_map=_freeze_array(_copy_array(river_map)),
        provincial_terrain=copy.deepcopy(dict(provincial_terrain or {})),
        state_mgr=_deepcopy_manager(managers.get("state_mgr")),
        country_mgr=_deepcopy_manager(managers.get("country_mgr")),
        continent_mgr=_deepcopy_manager(managers.get("continent_mgr")),
        adjacency_mgr=_deepcopy_manager(managers.get("adjacency_mgr")),
        railway_mgr=_deepcopy_manager(managers.get("railway_mgr")),
        supply_mgr=_deepcopy_manager(managers.get("supply_mgr")),
        adjacency_rule_mgr=_deepcopy_manager(managers.get("adjacency_rule_mgr")),
        strategic_region_mgr=_deepcopy_manager(managers.get("strategic_region_mgr")),
        logistics_exception_mgr=_deepcopy_manager(managers.get("logistics_exception_mgr")),
        map_placement_mgr=_deepcopy_manager(managers.get("map_placement_mgr")),
        colormap_settings=copy.deepcopy(colormap_settings),
        default_map_settings=copy.deepcopy(default_map_settings),
        assets={
            str(path): (bytes(value) if isinstance(value, (bytes, bytearray, memoryview))
                        else copy.deepcopy(value))
            for path, value in (assets or {}).items()
        },
        dirty_assets=frozenset(dirty_assets or ()),
        project_meta=copy.deepcopy(project_meta),
        profile_id=str(profile_id or "hoi4-1.19"),
    )
    snapshot.fingerprint = compute_fingerprint(
        snapshot.tile_map, snapshot.province_map, snapshot.terrain_map,
        snapshot.managers_dict(),
    )
    snapshot.live_fingerprint = compute_fingerprint(
        tile_map, province_map, terrain_map, managers,
    )
    snapshot.live_auxiliary_fingerprint = _auxiliary_digest({
        "height_map": height_map,
        "river_map": river_map,
        "provincial_terrain": provincial_terrain or {},
        "colormap_settings": colormap_settings,
        "default_map_settings": default_map_settings,
        "assets": assets or {},
        "dirty_assets": dirty_assets or (),
    })
    return snapshot


def resolve_game_target_for_plan(game_target=None, game_dir=None, project_meta=None):
    if game_dir:
        from services.game_assets import resolve_game_target
        return resolve_game_target(str(game_dir), source="explicit")
    if game_target is not None:
        return game_target
    install = getattr(project_meta, "game_install_dir", None) if project_meta is not None else None
    profile_id = getattr(project_meta, "profile_id", None) if project_meta is not None else None
    try:
        from services.game_assets import resolve_game_target
        return resolve_game_target(install, profile_id=profile_id, source="project" if install else "default")
    except (ImportError, TypeError, ValueError, OSError):
        return None


def resolve_game_profile_for_plan(game_profile=None, game_target=None):
    if game_profile is not None:
        return game_profile
    try:
        from services.game_profile_service import load_profile_for_target, get_default_profile
        if game_target is not None:
            return load_profile_for_target(game_target)
        return get_default_profile()
    except (ImportError, TypeError, ValueError, OSError):
        return None


def resolve_lifecycle_for_plan(lifecycle=None, project_meta=None) -> str:
    candidate = lifecycle or (getattr(project_meta, "lifecycle", None) if project_meta is not None else None) or "draft"
    if candidate not in EXPORT_LIFECYCLES:
        raise PlanRejected("unknown lifecycle %r; expected one of %s" % (candidate, ", ".join(EXPORT_LIFECYCLES)))
    return candidate

APPLICATION_ORDER = (
    "province.land_lake_sync",
    "terrain.tile_sync",
    "state.empty_cleanup",
    "province.tiny_merge",
    "province.bbox_trim",
    "province.compact_ids",
    "province.tile_sync",
    "province.coastal_sea_conversion",
    "state.orphan_adopt",
    "state.unowned_assign",
    "country.capital_assign",
    "region.state_alignment",
    "region.split_disconnected",
)


def classify_provinces(province_map, tile_map, province_count=None, overrides=None):
    from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
    if province_count is None:
        province_count = int(province_map.max())
    flat_pm = np.asarray(province_map).ravel()
    flat_tm = np.asarray(tile_map).ravel()
    size = province_count + 1
    land_n = np.bincount(flat_pm, weights=(flat_tm == TILE_LAND).astype(np.int64), minlength=size)
    sea_n = np.bincount(flat_pm, weights=(flat_tm == TILE_SEA).astype(np.int64), minlength=size)
    lake_n = np.bincount(flat_pm, weights=(flat_tm == TILE_LAKE).astype(np.int64), minlength=size)
    land_ids: list = []
    sea_ids: list = []
    lake_ids: list = []
    for pid in range(1, province_count + 1):
        land_v, sea_v, lake_v = int(land_n[pid]), int(sea_n[pid]), int(lake_n[pid])
        if land_v == 0 and sea_v == 0 and lake_v == 0:
            continue
        if land_v >= sea_v and land_v >= lake_v:
            land_ids.append(pid)
        elif lake_v > sea_v:
            lake_ids.append(pid)
        else:
            sea_ids.append(pid)
    for pid, forced in (overrides or {}).items():
        pid = int(pid)
        for bucket in (land_ids, sea_ids, lake_ids):
            if pid in bucket:
                bucket.remove(pid)
        if forced == "land":
            land_ids.append(pid)
        elif forced == "lake":
            lake_ids.append(pid)
        else:
            sea_ids.append(pid)
    return sorted(land_ids), sorted(sea_ids), sorted(lake_ids)


def _state_province_map(state_mgr, province_count: int) -> dict:
    assigned: dict = {}
    if state_mgr is None:
        return assigned
    for sid, state in (getattr(state_mgr, "states", None) or {}).items():
        for pid in getattr(state, "provinces", []) or []:
            if 0 < int(pid) <= province_count:
                assigned[int(pid)] = int(sid)
    return assigned


def analyze_terrain_tile_sync(snapshot) -> list:
    if snapshot.terrain_map is None:
        return []
    from data.terrain_types import TERRAIN_PALETTE_INDEX
    from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
    ocean_idx = TERRAIN_PALETTE_INDEX["ocean"]
    lakes_idx = TERRAIN_PALETTE_INDEX["lakes"]
    tile_map = np.asarray(snapshot.tile_map)
    terrain_map = np.asarray(snapshot.terrain_map)
    land_bad = int(np.sum((tile_map == TILE_LAND) & (terrain_map == ocean_idx)))
    sea_bad = int(np.sum((tile_map == TILE_SEA) & (terrain_map != ocean_idx)))
    lake_bad = int(np.sum((tile_map == TILE_LAKE) & (terrain_map != lakes_idx)))
    total = land_bad + sea_bad + lake_bad
    if total <= 0:
        return []
    return [RepairAction(
        code="terrain.tile_sync",
        safety="safe",
        summary="Synchronize %d terrain pixels with tile surface types" % total,
        pixel_count=total,
        record_count=3,
        before="land/ocean=%d sea/non-ocean=%d lake/non-lake=%d" % (land_bad, sea_bad, lake_bad),
        after="land pixels use non-ocean terrain, sea pixels use ocean, lake pixels use lakes",
        rerun_validations=("terrain.registry", "raster.definition"),
        layer="terrain",
    )]


def analyze_state_empty_cleanup(snapshot) -> list:
    state_mgr = snapshot.state_mgr
    if state_mgr is None or not getattr(state_mgr, "states", None):
        return []
    find_empty = getattr(state_mgr, "find_empty_state_ids", None)
    empty = list(find_empty()) if callable(find_empty) else []
    remaining = sorted(s for s in getattr(state_mgr, "states", {}) if s not in set(empty))
    mapping = {}
    if remaining != list(range(1, len(remaining) + 1)):
        mapping = {old: new for new, old in enumerate(remaining, start=1) if old != new}
    if not empty and not mapping:
        return []
    return [RepairAction(
        code="state.empty_cleanup",
        safety="semantic",
        summary="Remove %d empty states and renumber %d state IDs" % (len(empty), len(mapping)),
        affected_states=tuple(sorted(empty)),
        record_count=len(empty) + len(mapping),
        before="empty states: %s" % (", ".join(str(s) for s in sorted(empty)[:10]) or "none"),
        after="state IDs are consecutive 1..N with owner references remapped",
        mapping=dict(mapping),
        rerun_validations=("state.membership", "region.coverage", "country.ownership"),
        layer="states",
    )]


def analyze_province_tiny_merge(snapshot, min_pixels: int = 8) -> list:
    province_map = np.asarray(snapshot.province_map)
    max_id = int(province_map.max())
    if max_id <= 0:
        return []
    areas = np.bincount(province_map.ravel(), minlength=max_id + 1)
    tiny = [int(pid) for pid in range(1, max_id + 1) if 0 < int(areas[pid]) < min_pixels]
    if not tiny:
        return []
    return [RepairAction(
        code="province.tiny_merge",
        safety="semantic",
        summary="Merge %d provinces smaller than %d pixels into their largest neighbour" % (len(tiny), min_pixels),
        affected_ids=tuple(sorted(tiny)),
        pixel_count=int(sum(int(areas[pid]) for pid in tiny)),
        record_count=len(tiny),
        before="tiny provinces: %s" % ", ".join(str(p) for p in sorted(tiny)[:10]),
        after="fragments adopt the largest adjacent province ID",
        rerun_validations=("raster.connectivity", "raster.definition", "state.membership"),
        layer="provinces",
    )]


def analyze_province_bbox_trim(snapshot) -> list:
    try:
        from domain.validators.province import detect_too_large_provinces
    except ImportError:
        return []
    try:
        oversized = [int(p) for p in detect_too_large_provinces(
            np.asarray(snapshot.province_map), include_engine_boundary=True)]
    except TypeError:
        return []
    if not oversized:
        return []
    return [RepairAction(
        code="province.bbox_trim",
        safety="semantic",
        summary="Trim safe boundary pixels from %d oversized provinces" % len(oversized),
        affected_ids=tuple(sorted(oversized)),
        record_count=len(oversized),
        before="bounding box reaches the 1/8 engine limit: %s" % ", ".join(str(p) for p in sorted(oversized)[:10]),
        after="outer edge pixels move to an adjacent province without breaking connectivity",
        rerun_validations=("raster.bbox", "raster.definition"),
        layer="provinces",
    )]


def analyze_province_compact_ids(snapshot) -> list:
    province_map = np.asarray(snapshot.province_map)
    present = sorted(int(p) for p in np.unique(province_map) if int(p) > 0)
    if not present:
        return []
    if present == list(range(1, len(present) + 1)):
        return []
    mapping = {old: new for new, old in enumerate(present, start=1) if old != new}
    return [RepairAction(
        code="province.compact_ids",
        safety="breaking",
        summary="Compact %d province ID gaps left by merges" % (int(present[-1]) - len(present)),
        affected_ids=tuple(present),
        record_count=len(mapping),
        before="ID range 1..%d with %d gaps" % (int(present[-1]), int(present[-1]) - len(present)),
        after="IDs are consecutive 1..%d with old-to-new mapping" % len(present),
        mapping=dict(mapping),
        rerun_validations=("raster.definition", "state.membership", "region.coverage", "logistics.graph"),
        layer="provinces",
    )]


def analyze_province_tile_sync(snapshot) -> list:
    from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
    from domain.province_surface import find_land_lake_splits
    province_map = np.asarray(snapshot.province_map)
    tile_map = np.asarray(snapshot.tile_map)
    land_ids, sea_ids, lake_ids = classify_provinces(
        province_map, tile_map, overrides=snapshot.province_type_overrides)
    land_set, sea_set, lake_set = set(land_ids), set(sea_ids), set(lake_ids)
    land_lake_split_ids = {
        item.province_id for item in find_land_lake_splits(tile_map, province_map)
    }
    flat_pm, flat_tm = province_map.ravel(), tile_map.ravel()
    disagree = 0
    for pid in np.unique(flat_pm):
        pid = int(pid)
        if pid <= 0 or pid in land_lake_split_ids:
            continue
        mask = flat_pm == pid
        tiles = flat_tm[mask]
        if pid in land_set:
            disagree += int(np.sum(tiles != TILE_LAND))
        elif pid in sea_set:
            disagree += int(np.sum(tiles != TILE_SEA))
        else:
            disagree += int(np.sum(tiles != TILE_LAKE))
    if disagree <= 0:
        return []
    return [RepairAction(
        code="province.tile_sync",
        safety="safe",
        summary="Synchronize %d tile pixels with province majority classification" % disagree,
        pixel_count=disagree,
        record_count=len(land_ids) + len(sea_ids) + len(lake_ids),
        before="%d tile pixels disagree with their province majority type" % disagree,
        after="every tile pixel matches its province land/sea/lake class",
        rerun_validations=("raster.definition", "placement.coordinates"),
        layer="provinces",
    )]


def analyze_province_land_lake_sync(snapshot) -> list:
    """Propose the safe repair that makes every land/lake split one surface."""
    from domain.province_surface import find_land_lake_splits

    splits = find_land_lake_splits(snapshot.tile_map, snapshot.province_map)
    if not splits:
        return []
    changed_pixels = sum(
        item.land + item.sea + item.lake
        - (item.land if item.dominant_surface == "land" else 0)
        - (item.sea if item.dominant_surface == "sea" else 0)
        - (item.lake if item.dominant_surface == "lake" else 0)
        for item in splits
    )
    targets = ", ".join(
        "%d→%s" % (item.province_id, item.dominant_surface)
        for item in splits[:10]
    )
    if len(splits) > 10:
        targets += ", ..."
    return [RepairAction(
        code="province.land_lake_sync",
        safety="safe",
        summary="Normalize %d province(s) that mix land and lake pixels" % len(splits),
        affected_ids=tuple(sorted(item.province_id for item in splits)),
        pixel_count=int(changed_pixels),
        record_count=len(splits),
        before="land/lake split provinces: %s" % targets,
        after="every affected province uses its dominant land/sea/lake surface",
        rerun_validations=("raster.definition", "terrain.registry", "placement.coordinates"),
        layer="provinces",
    )]


def analyze_province_coastal_conversion(snapshot) -> list:
    from export.mod_exporter import _compute_coastal_once
    province_map = np.asarray(snapshot.province_map)
    tile_map = np.asarray(snapshot.tile_map)
    province_count = int(province_map.max())
    if province_count <= 0:
        return []
    land_ids, sea_ids, _lake_ids = classify_provinces(
        province_map, tile_map, province_count, overrides=snapshot.province_type_overrides)
    coastal_set, _land_to_sea = _compute_coastal_once(province_map, land_ids, sea_ids)
    assigned = set(_state_province_map(snapshot.state_mgr, province_count))
    orphan_coastal = sorted(p for p in coastal_set if p not in assigned)
    if not orphan_coastal:
        return []
    return [RepairAction(
        code="province.coastal_sea_conversion",
        safety="semantic",
        summary="Convert %d stateless coastal provinces to sea" % len(orphan_coastal),
        affected_ids=tuple(orphan_coastal),
        record_count=len(orphan_coastal),
        before="coastal land without a state: %s" % ", ".join(str(p) for p in orphan_coastal[:10]),
        after="converted provinces classify as sea so definition.csv matches buildings.txt",
        rerun_validations=("raster.definition", "placement.coordinates", "state.membership"),
        layer="provinces",
    )]


def analyze_state_orphans(snapshot) -> list:
    province_map = np.asarray(snapshot.province_map)
    province_count = int(province_map.max())
    if province_count <= 0 or snapshot.state_mgr is None or not getattr(snapshot.state_mgr, "states", None):
        return []
    land_ids, _sea, _lake = classify_provinces(
        province_map, np.asarray(snapshot.tile_map), province_count,
        overrides=snapshot.province_type_overrides)
    assigned = set(_state_province_map(snapshot.state_mgr, province_count))
    orphans = sorted(p for p in land_ids if p not in assigned)
    if not orphans:
        return []
    return [RepairAction(
        code="state.orphan_adopt",
        safety="semantic",
        summary="Adopt %d orphaned land provinces into the nearest state" % len(orphans),
        affected_ids=tuple(orphans),
        record_count=len(orphans),
        before="land provinces without a state: %s" % ", ".join(str(p) for p in orphans[:10]),
        after="each orphan joins the geographically closest state",
        rerun_validations=("state.membership", "region.coverage"),
        layer="states",
    )]


def analyze_state_unowned(snapshot) -> list:
    state_mgr = snapshot.state_mgr
    country_mgr = snapshot.country_mgr
    if state_mgr is None or country_mgr is None or not getattr(state_mgr, "states", None):
        return []
    get_owner = getattr(country_mgr, "get_owner_of_state", None)
    if not callable(get_owner):
        return []
    unowned = [int(sid) for sid in getattr(state_mgr, "states", {}) if not get_owner(sid)]
    if not unowned or not getattr(country_mgr, "countries", None):
        return []
    first_tag = next(iter(country_mgr.countries))
    return [RepairAction(
        code="state.unowned_assign",
        safety="semantic",
        summary="Assign %d unowned states to %s" % (len(unowned), first_tag),
        affected_states=tuple(sorted(unowned)),
        record_count=len(unowned),
        before="states without an owner: %s" % ", ".join(str(s) for s in sorted(unowned)[:10]),
        after="all states are owned by %s" % first_tag,
        rerun_validations=("country.ownership", "state.membership"),
        layer="states",
    )]


def analyze_country_capitals(snapshot) -> list:
    country_mgr = snapshot.country_mgr
    state_mgr = snapshot.state_mgr
    if country_mgr is None or not getattr(country_mgr, "countries", None):
        return []
    missing = [str(tag) for tag, country in country_mgr.countries.items()
               if getattr(country, "capital", 0) <= 0]
    if not missing:
        return []
    _ = state_mgr
    return [RepairAction(
        code="country.capital_assign",
        safety="semantic",
        summary="Assign capitals to %d countries from their first state" % len(missing),
        record_count=len(missing),
        before="countries without a capital: %s" % ", ".join(missing[:10]),
        after="each country uses the first province of its first state",
        rerun_validations=("country.ownership",),
        layer="countries",
    )]


def analyze_region_alignment(snapshot) -> list:
    region_mgr = snapshot.strategic_region_mgr
    state_mgr = snapshot.state_mgr
    province_map = np.asarray(snapshot.province_map)
    province_count = int(province_map.max())
    if region_mgr is None or not getattr(region_mgr, "regions", None):
        return []
    if state_mgr is None or not getattr(state_mgr, "states", None):
        return []
    pid_to_rid: dict = {}
    for region in region_mgr.regions.values():
        for pid in getattr(region, "province_ids", []) or []:
            pid_to_rid[int(pid)] = int(getattr(region, "id", 0))
    split = []
    for sid, state in state_mgr.states.items():
        provs = [int(p) for p in getattr(state, "provinces", []) or [] if 0 < int(p) <= province_count]
        if len(provs) < 2:
            continue
        rids = {pid_to_rid.get(p, 0) for p in provs}
        if len(rids - {0}) > 1 or (len(rids) > 1 and 0 in rids):
            split.append(int(sid))
    if not split:
        return []
    return [RepairAction(
        code="region.state_alignment",
        safety="semantic",
        summary="Realign %d states split across strategic regions" % len(split),
        affected_states=tuple(sorted(split)),
        record_count=len(split),
        before="states spanning multiple regions: %s" % ", ".join(str(s) for s in sorted(split)[:10]),
        after="each connected state group sits in a single strategic region",
        rerun_validations=("region.coverage", "region.connectivity"),
        layer="regions",
    )]


def analyze_region_split(snapshot) -> list:
    region_mgr = snapshot.strategic_region_mgr
    province_map = np.asarray(snapshot.province_map)
    province_count = int(province_map.max())
    if region_mgr is None or not getattr(region_mgr, "regions", None):
        return []
    try:
        from domain.managers.strategic_region import _split_connected
    except ImportError:
        return []
    affected = []
    extra = 0
    for region in list(region_mgr.regions.values()):
        provs = [int(p) for p in getattr(region, "province_ids", []) or [] if 0 < int(p) <= province_count]
        if len(provs) < 2:
            continue
        try:
            groups = _split_connected(province_map, set(provs))
        except (TypeError, ValueError):
            continue
        if len(groups) > 1:
            affected.append(int(getattr(region, "id", 0)))
            extra += len(groups) - 1
    if not affected:
        return []
    return [RepairAction(
        code="region.split_disconnected",
        safety="semantic",
        summary="Split %d disconnected strategic regions into +%d connected regions" % (len(affected), extra),
        affected_ids=tuple(sorted(affected)),
        record_count=extra,
        before="disconnected regions: %s" % ", ".join(str(r) for r in sorted(affected)[:10]),
        after="every region is pixel-connected as the engine requires",
        rerun_validations=("region.connectivity", "region.coverage"),
        layer="regions",
    )]

def collect_findings(
    snapshot,
    game_profile,
    dimensions=None,
    profile_name: str = "legacy_full",
    lifecycle: str | None = None,
    game_target=None,
) -> list:
    findings: list = []
    province_map = np.asarray(snapshot.province_map)
    province_count = int(province_map.max()) if province_map.size else 0
    width, height = int(snapshot.width), int(snapshot.height)
    active_lifecycle = str(
        lifecycle
        if lifecycle is not None
        else getattr(snapshot.project_meta, "lifecycle", "draft")
    )
    if dimensions is not None:
        try:
            req_w, req_h = int(dimensions[0]), int(dimensions[1])
        except (TypeError, ValueError, IndexError):
            findings.append(ValidationNote("export.dimensions.invalid", "error",
                                           "Explicit export dimensions must be a (width, height) pair"))
            req_w, req_h = width, height
        if (req_w, req_h) != (width, height):
            findings.append(ValidationNote("export.dimensions.mismatch", "error",
                                           "Explicit dimensions %dx%d do not match map arrays %dx%d"
                                           % (req_w, req_h, width, height)))
    if game_profile is not None:
        for error in game_profile.validate_dimensions(width, height):
            findings.append(ValidationNote("map.dimensions.profile", "error", error, layer="map"))
        guidance = getattr(game_profile, "provinces", None)
        if guidance is not None and province_count:
            hard_max = int(getattr(guidance, "hard_max", 0) or 0)
            soft_max = int(getattr(guidance, "soft_max", 0) or 0)
            if hard_max and province_count > hard_max:
                findings.append(ValidationNote("province.count.hard_max", "error",
                                               "%d provinces exceed the profile hard maximum %d"
                                               % (province_count, hard_max), layer="provinces"))
            elif soft_max and province_count > soft_max:
                findings.append(ValidationNote("province.count.soft_max", "warning",
                                               "%d provinces exceed the profile soft maximum %d"
                                               % (province_count, soft_max), layer="provinces"))
    if province_count == 0:
        findings.append(ValidationNote("province.empty", "blocker",
                                       "No province data; generate provinces first", layer="provinces"))
        return findings
    try:
        from domain.province_surface import find_land_lake_splits

        land_lake_splits = find_land_lake_splits(
            snapshot.tile_map, snapshot.province_map
        )
    except (ImportError, TypeError, ValueError):
        land_lake_splits = ()
    if land_lake_splits:
        details = ", ".join(
            "%d (%d land/%d lake → %s)" % (
                item.province_id,
                item.land,
                item.lake,
                item.dominant_surface,
            )
            for item in land_lake_splits[:8]
        )
        if len(land_lake_splits) > 8:
            details += ", ..."
        findings.append(ValidationNote(
            "province.land_lake_split",
            "warning",
            "%d province(s) contain both land and lake pixels: %s; apply the safe land/lake normalization repair"
            % (len(land_lake_splits), details),
            layer="provinces",
        ))
    state_mgr = snapshot.state_mgr
    country_mgr = snapshot.country_mgr
    if state_mgr is None or not getattr(state_mgr, "states", None):
        findings.append(ValidationNote("state.empty", "warning",
                                       "No states; group provinces automatically or create a state manually",
                                       layer="states"))
    if country_mgr is None or not getattr(country_mgr, "countries", None):
        if profile_name == "foundation":
            findings.append(ValidationNote("country.omitted", "info",
                                           "Foundation profile omits country content by design",
                                           layer="countries"))
        else:
            findings.append(ValidationNote("country.empty", "warning",
                                           "No countries; create at least one country", layer="countries"))
    else:
        get_owner = getattr(country_mgr, "get_owner_of_state", None)
        if state_mgr is not None and callable(get_owner):
            unowned = [str(sid) for sid in getattr(state_mgr, "states", {}) if not get_owner(sid)]
            if unowned:
                if profile_name == "foundation":
                    findings.append(ValidationNote("state.unowned.foundation", "info",
                                                   "%d states have no owner; owners stay content-side and are "
                                                   "recorded as placeholders" % len(unowned), layer="states"))
                else:
                    findings.append(ValidationNote("state.unowned", "warning",
                                                   "%d states have no country: %s..."
                                                   % (len(unowned), ", ".join(unowned[:5])), layer="states"))
        missing_capitals = [str(tag) for tag, country in country_mgr.countries.items()
                            if getattr(country, "capital", 0) <= 0]
        if missing_capitals and profile_name != "foundation":
            findings.append(ValidationNote("country.capital.missing", "warning",
                                           "Countries without a capital: %s" % ", ".join(missing_capitals[:5]),
                                           layer="countries"))
    continent_mgr = snapshot.continent_mgr
    if continent_mgr is not None:
        try:
            if continent_mgr.count() == 0:
                findings.append(ValidationNote("continent.empty", "info",
                                               "No continents are defined; the default continent will be used",
                                               layer="map"))
        except TypeError:
            pass
    river_map = snapshot.river_map
    if river_map is not None:
        try:
            from domain.managers.river import validate_rivers, VALID_RIVER_VALUES
            river_arr = np.asarray(river_map)
            if bool(np.isin(river_arr, list(VALID_RIVER_VALUES)).any()):
                issues = [
                    w for w in validate_rivers(river_arr)
                    if str(w).strip().rstrip(" ✓")
                    not in ("No river data", "River validation passed")
                ]
                for issue in issues[:5]:
                    findings.append(ValidationNote("river.legality", "warning",
                                                   "River: %s" % issue, layer="rivers"))
        except (ImportError, TypeError, ValueError):
            pass
    # M4.1: an empty special-adjacency layer is not silently acceptable at
    # freeze time. Keep direct legacy callers without metadata unchanged.
    if snapshot.project_meta is not None:
        try:
            from domain.adjacency_review import evaluate_adjacency_review
            review_context = (
                "freeze" if active_lifecycle in ("frozen", "accepted")
                else "foundation_candidate"
            )
            decision = evaluate_adjacency_review(
                snapshot.adjacency_mgr,
                snapshot.adjacency_rule_mgr,
                state=getattr(snapshot.project_meta, "adjacency_review", "unreviewed"),
                note=getattr(snapshot.project_meta, "adjacency_review_note", ""),
                review_hash=getattr(snapshot.project_meta, "adjacency_review_hash", None),
                context=review_context,
            )
            if decision.finding is not None:
                findings.append(ValidationNote(
                    decision.finding.code,
                    decision.finding.severity,
                    decision.finding.message,
                    layer=decision.finding.layer,
                ))
        except (ImportError, TypeError, ValueError):
            # Metadata is an optional compatibility input for direct callers.
            pass
    # M4.3/M4.5: run the complete logistics validator during planning, before
    # staging starts.  This keeps railway, supply, adjacency, graph, and
    # exception findings in the same pre-export plan that the final verifier
    # consumes, including affected province IDs on typed findings.
    try:
        from domain.validators.logistics import validate_logistics_references

        findings.extend(validate_logistics_references(
            province_map,
            snapshot.tile_map,
            adjacency_mgr=snapshot.adjacency_mgr,
            railway_mgr=snapshot.railway_mgr,
            supply_mgr=snapshot.supply_mgr,
            adjacency_rule_mgr=snapshot.adjacency_rule_mgr,
            logistics_exception_mgr=snapshot.logistics_exception_mgr,
            country_mgr=snapshot.country_mgr,
            profile=game_profile,
            lifecycle=active_lifecycle,
        ))
    except (ImportError, TypeError, ValueError):
        # Older direct callers may provide incomplete snapshots.  Preserve
        # their compatibility behavior while normal project snapshots receive
        # the full logistics check above.
        pass
    # M5: a foundation freeze may not silently omit incomplete or unreviewed
    # manager placements. Draft plans receive warnings so the editor can keep
    # working; the validator promotes them to blockers for frozen/accepted
    # lifecycles. Legacy callers without a placement manager remain unchanged.
    if profile_name == "foundation" and getattr(snapshot, "map_placement_mgr", None) is not None:
        try:
            from domain.validators.placement import (
                validate_manager_placement_completeness,
                validate_manager_weather_positions,
            )

            findings.extend(
                validate_manager_placement_completeness(
                    province_map,
                    snapshot.tile_map,
                    snapshot.map_placement_mgr,
                    lifecycle=active_lifecycle,
                )
            )
            findings.extend(
                validate_manager_weather_positions(
                    province_map,
                    snapshot.map_placement_mgr,
                    strategic_region_mgr=snapshot.strategic_region_mgr,
                    lifecycle=active_lifecycle,
                )
            )
        except ImportError:
            # Keep the planner compatible with snapshots created before M5.
            pass
    # M5.2 Slice 1: an explicit foundation path must not silently fall back to
    # centroid/generated placement data when no placement manager is present.
    # Metadata-backed exports and frozen/accepted lifecycles are approval
    # boundaries and are blocked. Legacy direct callers without project
    # metadata that stay on draft-like lifecycles keep compatibility output.
    if profile_name == "foundation" and getattr(snapshot, "map_placement_mgr", None) is None:
        if getattr(snapshot, "project_meta", None) is not None or active_lifecycle in ("frozen", "accepted"):
            findings.append(ValidationNote(
                "placement.manager_missing",
                "blocker",
                "Foundation profile requires a MapPlacementManager; refusing centroid fallback for placements",
                layer="placement",
            ))
    try:
        from services.game_assets import missing_required_palettes as _missing_palettes
        _target = game_target
        if _target is None:
            try:
                _target = resolve_game_target_for_plan(None, None, getattr(snapshot, "project_meta", None))
            except (AttributeError, TypeError, ValueError):
                _target = None
        _install = None
        try:
            if _target is not None:
                _install = getattr(_target, "install_dir", None)
        except (AttributeError, TypeError, ValueError):
            _install = None
        _palette_msgs = _missing_palettes(_target, None, ["map/terrain.bmp", "map/cities.bmp"], active_lifecycle, profile_name)
        for _msg in _palette_msgs:
            _sev = "blocker" if active_lifecycle in ("frozen", "accepted") else "warning"
            findings.append(ValidationNote("export.palette.missing", _sev, _msg, layer="map"))
    except (ImportError, AttributeError, TypeError, ValueError, OSError):
        pass
    try:
        _assets = getattr(snapshot, "assets", None) or {}
        _dirty = set(getattr(snapshot, "dirty_assets", None) or ())
        try:
            from services.export_manifest import STRUCTURAL_OPTIONAL_PATHS as _struct_paths
        except (ImportError, AttributeError):
            _struct_paths = ("map/colors.txt", "map/airports.txt", "map/rocketsites.txt", "map/rocket_sites.txt", "map/cities.txt")
        for _spath in list(_struct_paths):
            if _spath in _assets and _spath not in _dirty:
                try:
                    from services.export_manifest import DEPRECATED_PATHS_FALLBACK as _dep_fallback
                    _deprecated = list(getattr(game_profile, "deprecated_files", None) or _dep_fallback)
                except (AttributeError, TypeError, ValueError):
                    _deprecated = []
                if _spath in _deprecated or _spath == "map/colors.txt":
                    findings.append(ValidationNote("export.structural.dropped", "warning", "Structural file %s has imported bytes but is deprecated and will be dropped before export" % _spath, layer="map"))
            elif _spath in _assets and _spath in _dirty:
                if _spath == "map/cities.txt":
                    findings.append(ValidationNote("export.structural.regenerated", "warning", "Structural file %s is dirty and will be regenerated from vanilla city groups" % _spath, layer="map"))
                else:
                    _severity = "blocker" if active_lifecycle in ("frozen", "accepted") else "warning"
                    findings.append(ValidationNote("export.structural.unsupported", _severity, "Structural file %s is dirty and has no regenerating writer" % _spath, layer="map"))
    except (AttributeError, TypeError, ValueError):
        pass
    return findings


def split_repairs_by_policy(repairs: list, repair_policy: str, lifecycle: str):
    if repair_policy == "off":
        return [], []
    proposed = list(repairs)
    if repair_policy == "propose":
        return proposed, []
    if lifecycle in ("frozen", "accepted"):
        return proposed, []
    return proposed, [r for r in repairs if r.safety == "safe"]


def _snapshot_dds_dimensions(snapshot):
    try:
        return (int(snapshot.width), int(snapshot.height))
    except (AttributeError, TypeError, ValueError):
        return (None, None)


def _dds_resolution_for_path(rel_path, game_profile, snapshot, assets, dirty, owner, rule):
    """DDS-aware resolution, or None when no profile contract applies.

    Falls back to the legacy generated/preserved handling for profiles
    without a DDS contract so custom test profiles keep their behavior.
    Blocked contracts name the missing encoder capability and the remedy.
    """
    try:
        if game_profile is None or not dds_format.has_contract(game_profile, rel_path):
            return None
    except (AttributeError, TypeError, ValueError):
        return None
    map_w, map_h = _snapshot_dds_dimensions(snapshot)
    try:
        strategy = dds_format.strategy_for_asset(rel_path, game_profile, map_w, map_h)
    except (AttributeError, TypeError, ValueError):
        return None
    raw = None
    try:
        candidate = assets.get(rel_path) if isinstance(assets, dict) else None
        if isinstance(candidate, (bytes, bytearray, memoryview)) and len(candidate) > 0:
            raw = bytes(candidate)
    except (TypeError, ValueError):
        raw = None
    try:
        dirty_flag = rel_path in (dirty or ())
    except (TypeError, ValueError):
        dirty_flag = False
    try:
        decision = dds_format.decide_dds_output(strategy, imported_bytes=raw, dirty=dirty_flag)
    except (AttributeError, TypeError, ValueError):
        return None
    if decision.action == "preserve":
        digest = ""
        try:
            digest = hashlib.sha256(raw).hexdigest()
        except (TypeError, ValueError):
            digest = ""
        return AssetResolution(rel_path, "preserved", provenance="project-assets", reason=decision.reason, size=len(raw or b""), source="project-assets", sha256=digest, output_owner=owner, profile_rule=rule, dirty_reason="")
    if decision.action == "blocked":
        reason = decision.reason
        if decision.remedy:
            reason = reason + " Remedy: " + decision.remedy
        return AssetResolution(rel_path, "blocked", provenance="dds-capability", reason=reason, size=0, source="dds-capability", sha256="", output_owner=owner, profile_rule=rule, dirty_reason=("dirty asset cannot be regenerated" if dirty_flag else "no compatible import and no encoder for the profile format"))
    return AssetResolution(rel_path, "generated", provenance="writer-generated", reason=decision.reason, size=0, source="writer-generated", sha256="", output_owner=owner, profile_rule=rule, dirty_reason="")


def findings_for_asset_blockers(resolutions, game_profile=None, lifecycle="draft"):
    """Explicit findings for blocked or required-unsupported resolutions.

    Blocked assets (DDS capability gaps, dirty map art without a writer)
    and required assets stuck at unsupported become blockers at
    frozen/accepted scope and warnings otherwise, so drafts keep working
    while freezes demand a remedy or an accepted exception.
    """
    frozen = str(lifecycle or "draft") in ("frozen", "accepted")
    severity = "blocker" if frozen else "warning"
    try:
        required = set(getattr(game_profile, "required_files", None) or [])
    except (AttributeError, TypeError, ValueError):
        required = set()
    notes = []
    covered = set()
    for entry in list(resolutions or []):
        try:
            if isinstance(entry, dict):
                rel_path = str(entry.get("rel_path", ""))
                disp = str(entry.get("disposition", ""))
                reason = str(entry.get("reason", ""))
            else:
                rel_path = str(getattr(entry, "rel_path", ""))
                disp = str(getattr(entry, "disposition", ""))
                reason = str(getattr(entry, "reason", ""))
        except (AttributeError, TypeError, ValueError):
            continue
        if rel_path:
            covered.add(rel_path)
        if not rel_path or not disp:
            continue
        if disp == "blocked":
            notes.append(ValidationNote("export.asset.blocked", severity, "%s is blocked: %s" % (rel_path, reason or "generation cannot satisfy the profile contract"), layer="assets"))
        elif disp == "unsupported" and rel_path in required:
            notes.append(ValidationNote("export.asset.blocked", severity, "%s is required but unsupported: %s" % (rel_path, reason or "no writer can produce it"), layer="assets"))
    for missing in sorted(required):
        if missing not in covered:
            notes.append(ValidationNote("export.asset.blocked", severity, "%s is required by the profile but has no asset resolution" % missing, layer="assets"))
    return notes


def build_asset_resolutions(snapshot, profile_name: str, game_profile=None, scope=None, lifecycle=None) -> list:
    from services.export_manifest import (
        CONTENT_ONLY_PATHS,
        DEPRECATED_PATHS_FALLBACK,
        PRESERVED_CAPABLE_PATHS,
        STRUCTURAL_OPTIONAL_PATHS,
        WRITER_GENERATED_FILES,
        owner_stage_for_path,
    )
    import hashlib as _hashlib
    def _sha(data):
        try:
            if isinstance(data, (bytes, bytearray, memoryview)):
                raw = bytes(data)
                if raw:
                    return _hashlib.sha256(raw).hexdigest()
        except (TypeError, ValueError):
            pass
        return ""
    def _size(data):
        try:
            return len(data or b"")
        except (TypeError, ValueError):
            return 0
    resolutions: list = []
    seen: set = set()
    assets = snapshot.assets or {}
    if not isinstance(assets, dict):
        assets = {}
    dirty = set(snapshot.dirty_assets or ())
    try:
        required = list(getattr(game_profile, "required_files", None) or [])
    except (AttributeError, TypeError, ValueError):
        required = []
    try:
        optional = list(getattr(game_profile, "optional_files", None) or [])
    except (AttributeError, TypeError, ValueError):
        optional = []
    try:
        deprecated = list(getattr(game_profile, "deprecated_files", None) or DEPRECATED_PATHS_FALLBACK)
    except (AttributeError, TypeError, ValueError):
        deprecated = list(DEPRECATED_PATHS_FALLBACK)
    required_set = set(required)
    optional_set = set(optional)
    deprecated_set = set(deprecated)
    try:
        replace_paths = list(getattr(game_profile, "replace_paths", None) or [])
    except (AttributeError, TypeError, ValueError):
        replace_paths = []
    scope_map = dict(scope or {}) if isinstance(scope, dict) else {}
    map_disabled = scope_map.get("map", True) is False
    descriptor_disabled = scope_map.get("descriptor", True) is False
    def _rule_for(path):
        if path in deprecated_set:
            return "deprecated"
        if path in required_set:
            return "required"
        if path in optional_set:
            return "optional"
        if path in set(replace_paths):
            return "inherited"
        return "writer-generated"
    def _owner_for(path):
        try:
            return owner_stage_for_path(path)
        except (AttributeError, TypeError, ValueError):
            return "assets"
    for rel_path in WRITER_GENERATED_FILES:
        if rel_path in seen:
            continue
        seen.add(rel_path)
        owner = _owner_for(rel_path)
        rule = _rule_for(rel_path)
        if (rel_path.startswith("map/") and map_disabled) or (rel_path == "descriptor.mod" and descriptor_disabled):
            resolutions.append(AssetResolution(rel_path, "omitted", provenance="profile-policy", reason="excluded by export scope", size=0, source="profile-policy", sha256="", output_owner=owner, profile_rule=rule, dirty_reason=""))
            continue
        if map_art_matrix.is_generated_dds_art(rel_path):
            dds_resolution = _dds_resolution_for_path(rel_path, game_profile, snapshot, assets, dirty, owner, rule)
            if dds_resolution is not None:
                resolutions.append(dds_resolution)
                continue
        if rel_path in PRESERVED_CAPABLE_PATHS and rel_path in assets and rel_path not in dirty:
            raw = assets.get(rel_path)
            resolutions.append(AssetResolution(rel_path, "preserved", provenance="project-assets", reason="clean imported bytes are written back", size=_size(raw), source="project-assets", sha256=_sha(raw), output_owner=owner, profile_rule=rule, dirty_reason=""))
        elif rel_path in assets and rel_path in dirty:
            resolutions.append(AssetResolution(rel_path, "generated", provenance="writer-generated", reason="dirty asset is regenerated", size=0, source="writer-generated", sha256="", output_owner=owner, profile_rule=rule, dirty_reason="dirty asset is regenerated"))
        else:
            resolutions.append(AssetResolution(rel_path, "generated", provenance="writer-generated", reason="export writers generate this file", size=0, source="writer-generated", sha256="", output_owner=owner, profile_rule=rule, dirty_reason=""))
    for rel_path in CONTENT_ONLY_PATHS:
        if rel_path in seen:
            continue
        seen.add(rel_path)
        owner = _owner_for(rel_path)
        rule = _rule_for(rel_path)
        if profile_name == "foundation":
            resolutions.append(AssetResolution(rel_path, "omitted", provenance="profile-policy", reason="excluded by the foundation profile", size=0, source="profile-policy", sha256="", output_owner=owner, profile_rule=rule, dirty_reason=""))
        elif rel_path in assets and rel_path not in dirty:
            raw = assets.get(rel_path)
            resolutions.append(AssetResolution(rel_path, "preserved", provenance="project-assets", reason="clean imported bytes are written back", size=_size(raw), source="project-assets", sha256=_sha(raw), output_owner=owner, profile_rule=rule, dirty_reason=""))
        elif rel_path in assets and rel_path in dirty:
            resolutions.append(AssetResolution(rel_path, "generated", provenance="writer-generated", reason="dirty asset is regenerated", size=0, source="writer-generated", sha256="", output_owner=owner, profile_rule=rule, dirty_reason="dirty asset is regenerated"))
        else:
            resolutions.append(AssetResolution(rel_path, "generated", provenance="writer-generated", reason="content writers generate this file", size=0, source="writer-generated", sha256="", output_owner=owner, profile_rule=rule, dirty_reason=""))
    for rel_path in replace_paths:
        if rel_path in seen:
            continue
        seen.add(rel_path)
        owner = _owner_for(rel_path)
        resolutions.append(AssetResolution(rel_path, "inherited", provenance="game-install", reason="used from the game installation at runtime", size=0, source="game-install", sha256="", output_owner=owner, profile_rule="inherited", dirty_reason=""))
    for rel_path in map_art_matrix.matrix_inherited_paths(game_profile):
        if rel_path in seen:
            continue
        if isinstance(assets, dict) and rel_path in assets:
            continue
        seen.add(rel_path)
        owner = _owner_for(rel_path)
        resolutions.append(AssetResolution(rel_path, "inherited", provenance=map_art_matrix.INHERITED_PROVENANCE, reason=map_art_matrix.inherited_reason_for(rel_path), size=0, source=map_art_matrix.INHERITED_PROVENANCE, sha256="", output_owner=owner, profile_rule="inherited", dirty_reason=""))
    for rel_path in STRUCTURAL_OPTIONAL_PATHS:
        if rel_path in seen:
            continue
        seen.add(rel_path)
        owner = _owner_for(rel_path)
        rule = _rule_for(rel_path)
        if rel_path in deprecated_set:
            if rel_path in assets and rel_path not in dirty:
                raw = assets.get(rel_path)
                resolutions.append(AssetResolution(rel_path, "omitted", provenance="profile-policy", reason="deprecated file is not emitted; imported bytes will be dropped", size=_size(raw), source="profile-policy", sha256=_sha(raw), output_owner=owner, profile_rule=rule, dirty_reason=""))
            elif rel_path in assets and rel_path in dirty:
                resolutions.append(AssetResolution(rel_path, "unsupported", provenance="profile-policy", reason="deprecated dirty file cannot be regenerated", size=0, source="profile-policy", sha256="", output_owner=owner, profile_rule=rule, dirty_reason="dirty asset cannot be regenerated"))
            else:
                resolutions.append(AssetResolution(rel_path, "omitted", provenance="profile-policy", reason="deprecated file is not emitted", size=0, source="profile-policy", sha256="", output_owner=owner, profile_rule=rule, dirty_reason=""))
            continue
        if rel_path == "map/cities.txt":
            if rel_path in assets and rel_path not in dirty:
                raw = assets.get(rel_path)
                resolutions.append(AssetResolution(rel_path, "preserved", provenance="project-assets", reason="clean imported bytes are written back", size=_size(raw), source="project-assets", sha256=_sha(raw), output_owner=owner, profile_rule=rule if rule != "writer-generated" else "optional", dirty_reason=""))
            elif rel_path in assets and rel_path in dirty:
                resolutions.append(AssetResolution(rel_path, "generated", provenance="writer-generated", reason="dirty asset is regenerated from vanilla city groups", size=0, source="writer-generated", sha256="", output_owner=owner, profile_rule=rule if rule != "writer-generated" else "optional", dirty_reason="dirty asset is regenerated"))
            else:
                resolutions.append(AssetResolution(rel_path, "generated", provenance="writer-generated", reason="vanilla city groups are generated", size=0, source="writer-generated", sha256="", output_owner=owner, profile_rule=rule if rule != "writer-generated" else "optional", dirty_reason=""))
            continue
        if rel_path in assets and rel_path not in dirty:
            raw = assets.get(rel_path)
            if map_disabled and rel_path.startswith("map/"):
                resolutions.append(AssetResolution(rel_path, "omitted", provenance="profile-policy", reason="excluded by export scope; imported bytes will be dropped", size=_size(raw), source="profile-policy", sha256=_sha(raw), output_owner=owner, profile_rule=rule, dirty_reason=""))
            else:
                resolutions.append(AssetResolution(rel_path, "preserved", provenance="project-assets", reason="clean imported bytes are written back", size=_size(raw), source="project-assets", sha256=_sha(raw), output_owner=owner, profile_rule=rule if rule != "writer-generated" else "optional", dirty_reason=""))
        elif rel_path in assets and rel_path in dirty:
            resolutions.append(AssetResolution(rel_path, "unsupported", provenance="profile-policy", reason="dirty structural file cannot be regenerated; no writer owns it", size=0, source="profile-policy", sha256="", output_owner=owner, profile_rule=rule if rule != "writer-generated" else "optional", dirty_reason="dirty asset cannot be regenerated"))
        else:
            sibling_present = False
            if rel_path in ("map/rocketsites.txt", "map/rocket_sites.txt"):
                other = "map/rocket_sites.txt" if rel_path == "map/rocketsites.txt" else "map/rocketsites.txt"
                if other in assets and other not in dirty:
                    sibling_present = True
            if sibling_present:
                resolutions.append(AssetResolution(rel_path, "omitted", provenance="profile-policy", reason="naming variant not present in import; sibling variant is preserved", size=0, source="profile-policy", sha256="", output_owner=owner, profile_rule=rule if rule != "writer-generated" else "optional", dirty_reason=""))
            else:
                resolutions.append(AssetResolution(rel_path, "omitted", provenance="profile-policy", reason="optional file is absent and empty legacy files are not emitted", size=0, source="profile-policy", sha256="", output_owner=owner, profile_rule=rule if rule != "writer-generated" else "optional", dirty_reason=""))
    for rel_path in deprecated:
        if rel_path in seen:
            continue
        seen.add(rel_path)
        owner = _owner_for(rel_path)
        if rel_path in assets and rel_path not in dirty:
            raw = assets.get(rel_path)
            resolutions.append(AssetResolution(rel_path, "omitted", provenance="profile-policy", reason="deprecated file is not emitted; imported bytes will be dropped", size=_size(raw), source="profile-policy", sha256=_sha(raw), output_owner=owner, profile_rule="deprecated", dirty_reason=""))
        elif rel_path in assets and rel_path in dirty:
            resolutions.append(AssetResolution(rel_path, "unsupported", provenance="profile-policy", reason="deprecated dirty file cannot be regenerated", size=0, source="profile-policy", sha256="", output_owner=owner, profile_rule="deprecated", dirty_reason="dirty asset cannot be regenerated"))
        else:
            resolutions.append(AssetResolution(rel_path, "omitted", provenance="profile-policy", reason="deprecated file is not emitted", size=0, source="profile-policy", sha256="", output_owner=owner, profile_rule="deprecated", dirty_reason=""))
    for rel_path in sorted(set(assets) - seen):
        owner = _owner_for(rel_path)
        rule = _rule_for(rel_path)
        if map_art_matrix.is_map_art_path(rel_path):
            if rel_path in dirty:
                art_disp, art_reason, art_prov = map_art_matrix.classify_leftover_map_art(rel_path, has_bytes=False, dirty=True)
                resolutions.append(AssetResolution(rel_path, art_disp, provenance=art_prov, reason=art_reason, size=0, source=art_prov, sha256="", output_owner=owner, profile_rule=rule, dirty_reason="dirty asset cannot be regenerated"))
            else:
                raw = assets.get(rel_path)
                try:
                    usable = isinstance(raw, (bytes, bytearray, memoryview)) and len(raw) > 0
                except (TypeError, ValueError):
                    usable = False
                art_disp, art_reason, art_prov = map_art_matrix.classify_leftover_map_art(rel_path, has_bytes=bool(usable), dirty=False)
                resolutions.append(AssetResolution(rel_path, art_disp, provenance=art_prov, reason=art_reason, size=_size(raw), source=art_prov, sha256=_sha(raw), output_owner=owner, profile_rule=rule, dirty_reason=""))
            continue
        if rel_path in dirty:
            if rel_path == "map/cities.txt" or rel_path in PRESERVED_CAPABLE_PATHS:
                resolutions.append(AssetResolution(rel_path, "generated", provenance="writer-generated", reason="dirty asset is regenerated", size=0, source="writer-generated", sha256="", output_owner=owner, profile_rule=rule, dirty_reason="dirty asset is regenerated"))
            elif rel_path in STRUCTURAL_OPTIONAL_PATHS:
                resolutions.append(AssetResolution(rel_path, "unsupported", provenance="profile-policy", reason="dirty asset has no regenerating writer", size=0, source="profile-policy", sha256="", output_owner=owner, profile_rule=rule, dirty_reason="dirty asset cannot be regenerated"))
            else:
                resolutions.append(AssetResolution(rel_path, "generated", provenance="writer-generated", reason="dirty asset is regenerated", size=0, source="writer-generated", sha256="", output_owner=owner, profile_rule=rule, dirty_reason="dirty asset is regenerated"))
        else:
            raw = assets.get(rel_path)
            resolutions.append(AssetResolution(rel_path, "preserved", provenance="project-assets", reason="clean imported bytes are preserved", size=_size(raw), source="project-assets", sha256=_sha(raw), output_owner=owner, profile_rule=rule, dirty_reason=""))
    return resolutions


def _edit_snapshot_array(snapshot, name: str, func):
    arr = _thaw_array(getattr(snapshot, name))
    if arr is None:
        return
    func(arr)
    setattr(snapshot, name, _freeze_array(arr))


def _apply_terrain_tile_sync(snapshot, action) -> None:
    from services.export_service import _precheck_sync_terrain_tile
    if snapshot.terrain_map is None:
        return
    fixed: list = []
    def _run(terrain):
        _precheck_sync_terrain_tile(terrain, np.asarray(snapshot.tile_map), fixed)
    _edit_snapshot_array(snapshot, "terrain_map", _run)


def _apply_province_land_lake_sync(snapshot, action) -> None:
    from domain.province_surface import normalize_land_lake_splits

    def _run(tile):
        normalize_land_lake_splits(
            tile,
            np.asarray(snapshot.province_map),
            province_ids=action.affected_ids,
            overrides=snapshot.province_type_overrides,
        )

    _edit_snapshot_array(snapshot, "tile_map", _run)


def _apply_state_empty_cleanup(snapshot, action) -> None:
    from services.export_service import _precheck_clean_empty_states
    if snapshot.state_mgr is None:
        return
    _precheck_clean_empty_states(snapshot.state_mgr, snapshot.country_mgr, [], getattr(snapshot, "map_placement_mgr", None))


def _apply_province_tiny_merge(snapshot, action) -> None:
    from export.mod_exporter import _merge_tiny_provinces
    merged = _merge_tiny_provinces(np.asarray(snapshot.province_map).copy(), min_pixels=8)
    snapshot.province_map = _freeze_array(merged)


def _apply_province_bbox_trim(snapshot, action) -> None:
    from export.mod_exporter import _repair_too_large_provinces
    def _run(province):
        _repair_too_large_provinces(province, np.asarray(snapshot.tile_map))
    _edit_snapshot_array(snapshot, "province_map", _run)


def _apply_province_compact_ids(snapshot, action) -> None:
    from domain.map_data import MapData
    provinces = _thaw_array(np.asarray(snapshot.province_map))
    shim = MapData.__new__(MapData)
    shim.province_map = provinces
    shim.tile_map = _thaw_array(np.asarray(snapshot.tile_map))
    shim.provincial_terrain = dict(snapshot.provincial_terrain or {})
    shim.compact_with_references(
        state_mgr=snapshot.state_mgr,
        country_mgr=snapshot.country_mgr,
        strategic_region_mgr=snapshot.strategic_region_mgr,
        continent_mgr=snapshot.continent_mgr,
        adjacency_mgr=snapshot.adjacency_mgr,
        railway_mgr=snapshot.railway_mgr,
        supply_mgr=snapshot.supply_mgr,
        adjacency_rule_mgr=snapshot.adjacency_rule_mgr,
        map_placement_mgr=getattr(snapshot, "map_placement_mgr", None),
    )
    snapshot.province_map = _freeze_array(shim.province_map)
    snapshot.tile_map = _freeze_array(shim.tile_map)
    snapshot.provincial_terrain = dict(shim.provincial_terrain or {})


def _apply_province_tile_sync(snapshot, action) -> None:
    from export.mod_exporter import _classify_provinces_fast, _sync_tile_with_province_class
    province_map = np.asarray(snapshot.province_map)
    province_count = int(province_map.max())
    land_ids, sea_ids, lake_ids = _classify_provinces_fast(province_count, province_map,
                                                           np.asarray(snapshot.tile_map))
    overrides = dict(snapshot.province_type_overrides or {})
    for pid in list(overrides):
        for bucket in (land_ids, sea_ids, lake_ids):
            if pid in bucket:
                bucket.remove(pid)
        forced = overrides[pid]
        if forced == "land":
            land_ids.append(pid)
        elif forced == "lake":
            lake_ids.append(pid)
        else:
            sea_ids.append(pid)
    def _run(tile):
        _sync_tile_with_province_class(tile, province_map, land_ids, sea_ids, lake_ids)
    _edit_snapshot_array(snapshot, "tile_map", _run)


def _apply_province_coastal_conversion(snapshot, action) -> None:
    overrides = dict(snapshot.province_type_overrides or {})
    for pid in action.affected_ids:
        overrides[int(pid)] = "sea"
    snapshot.province_type_overrides = overrides


def _apply_state_orphan_adopt(snapshot, action) -> None:
    state_mgr = snapshot.state_mgr
    if state_mgr is None or not getattr(state_mgr, "states", None):
        return
    province_map = np.asarray(snapshot.province_map)
    province_count = int(province_map.max())
    land_ids, _sea, _lake = classify_provinces(
        province_map, np.asarray(snapshot.tile_map), province_count,
        overrides=snapshot.province_type_overrides)
    assigned: dict = {}
    for sid, state in state_mgr.states.items():
        for pid in getattr(state, "provinces", []) or []:
            assigned[int(pid)] = int(sid)
    orphans = [int(p) for p in action.affected_ids if int(p) in set(land_ids) and int(p) not in assigned]
    if not orphans:
        return
    flat_pm = province_map.ravel()
    size = province_count + 1
    pid_count = np.bincount(flat_pm, minlength=size)
    height, width = province_map.shape
    ys_grid, xs_grid = np.mgrid[0:height, 0:width]
    sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=size)
    sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=size)
    centers: dict = {}
    for sid, state in state_mgr.states.items():
        total = tx = ty = 0.0
        for pid in getattr(state, "provinces", []) or []:
            pid = int(pid)
            if 0 < pid < size and pid_count[pid] > 0:
                tx += sum_x[pid]
                ty += sum_y[pid]
                total += pid_count[pid]
        if total > 0:
            centers[int(sid)] = (ty / total, tx / total)
    if not centers:
        return
    for orphan in orphans:
        if orphan >= size or pid_count[orphan] == 0:
            continue
        ocy, ocx = sum_y[orphan] / pid_count[orphan], sum_x[orphan] / pid_count[orphan]
        best = min(centers, key=lambda sid: (centers[sid][0] - ocy) ** 2 + (centers[sid][1] - ocx) ** 2)
        state = state_mgr.get_state(best) if hasattr(state_mgr, "get_state") else state_mgr.states.get(best)
        if state is not None and orphan not in (getattr(state, "provinces", []) or []):
            state.provinces.append(orphan)


def _apply_state_unowned_assign(snapshot, action) -> None:
    from services.export_service import _precheck_fix_unowned_states
    if snapshot.state_mgr is None or snapshot.country_mgr is None:
        return
    _precheck_fix_unowned_states(snapshot.state_mgr, snapshot.country_mgr, [], [])


def _apply_country_capital_assign(snapshot, action) -> None:
    from services.export_service import _precheck_fix_missing_capitals
    if snapshot.country_mgr is None:
        return
    _precheck_fix_missing_capitals(snapshot.state_mgr, snapshot.country_mgr, [], [])


def _apply_region_alignment(snapshot, action) -> None:
    from services.export_service import _precheck_align_states_to_regions
    if snapshot.strategic_region_mgr is None or snapshot.state_mgr is None:
        return
    province_map = np.asarray(snapshot.province_map)
    _precheck_align_states_to_regions(province_map, int(province_map.max()),
                                      snapshot.state_mgr, snapshot.strategic_region_mgr, [])


def _apply_region_split(snapshot, action) -> None:
    from services.export_service import _precheck_split_disconnected_regions
    if snapshot.strategic_region_mgr is None:
        return
    province_map = np.asarray(snapshot.province_map)
    _precheck_split_disconnected_regions(province_map, int(province_map.max()),
                                         snapshot.strategic_region_mgr, [])


_APPLY_HANDLERS = {
    "province.land_lake_sync": _apply_province_land_lake_sync,
    "terrain.tile_sync": _apply_terrain_tile_sync,
    "state.empty_cleanup": _apply_state_empty_cleanup,
    "province.tiny_merge": _apply_province_tiny_merge,
    "province.bbox_trim": _apply_province_bbox_trim,
    "province.compact_ids": _apply_province_compact_ids,
    "province.tile_sync": _apply_province_tile_sync,
    "province.coastal_sea_conversion": _apply_province_coastal_conversion,
    "state.orphan_adopt": _apply_state_orphan_adopt,
    "state.unowned_assign": _apply_state_unowned_assign,
    "country.capital_assign": _apply_country_capital_assign,
    "region.state_alignment": _apply_region_alignment,
    "region.split_disconnected": _apply_region_split,
}


def apply_repair_actions(snapshot, actions: list) -> list:
    ordered = sorted(actions or [], key=lambda action: APPLICATION_ORDER.index(action.code)
                     if action.code in APPLICATION_ORDER else len(APPLICATION_ORDER))
    applied = []
    for action in ordered:
        handler = _APPLY_HANDLERS.get(action.code)
        if handler is None:
            continue
        handler(snapshot, action)
        applied.append(action)
    return applied


def plan_export(tile_map, province_map, terrain_map=None, height_map=None, river_map=None,
                state_mgr=None, country_mgr=None, continent_mgr=None, adjacency_mgr=None,
                railway_mgr=None, supply_mgr=None, adjacency_rule_mgr=None,
                strategic_region_mgr=None, logistics_exception_mgr=None, provincial_terrain=None,
                colormap_settings=None, default_map_settings=None,
                assets=None, dirty_assets=None, project_meta=None,
                profile_name: str = "legacy_full", game_target=None, game_dir=None,
                game_profile=None, repair_policy: str = "propose", lifecycle=None,
                scope=None, dimensions=None, mod_name: str = "WorldTest", tag: str = "AAA",
                acceptance_count: int = 2, vanilla_tags=(), map_placement_mgr=None) -> ExportPlan:
    if profile_name == "legacy_full" and isinstance(scope, dict) and scope:
        # M9.1: the old layer-toggle dictionary is retained as an adapter, but
        # callers should migrate to an explicit profile and staged layers.
        import warnings
        from domain.export_contract import translate_legacy_scope

        profile_name, scope = translate_legacy_scope(scope)
        warnings.warn(
            "plan_export(scope=...) is deprecated; use an explicit legacy_full "
            "profile with staged layers instead",
            DeprecationWarning,
            stacklevel=2,
        )
    if profile_name not in EXPORT_PROFILES:
        raise PlanRejected("unknown export profile %r; expected one of %s"
                           % (profile_name, ", ".join(EXPORT_PROFILES)))
    if repair_policy not in REPAIR_POLICIES:
        raise PlanRejected("unknown repair policy %r; expected one of %s"
                           % (repair_policy, ", ".join(REPAIR_POLICIES)))
    target = resolve_game_target_for_plan(game_target, game_dir, project_meta)
    profile = resolve_game_profile_for_plan(game_profile, target)
    active_lifecycle = resolve_lifecycle_for_plan(lifecycle, project_meta)
    layers = resolve_layers(profile_name, scope)
    if dimensions is not None:
        try:
            dimensions = (int(dimensions[0]), int(dimensions[1]))
        except (TypeError, ValueError, IndexError):
            raise PlanRejected("dimensions must be a (width, height) pair")
    managers = {
        "state_mgr": state_mgr,
        "country_mgr": country_mgr,
        "continent_mgr": continent_mgr,
        "adjacency_mgr": adjacency_mgr,
        "railway_mgr": railway_mgr,
        "supply_mgr": supply_mgr,
        "adjacency_rule_mgr": adjacency_rule_mgr,
        "strategic_region_mgr": strategic_region_mgr,
        "logistics_exception_mgr": logistics_exception_mgr,
        "map_placement_mgr": map_placement_mgr,
    }
    snapshot = take_snapshot(
        tile_map, province_map, terrain_map, height_map, river_map,
        managers=managers, provincial_terrain=provincial_terrain,
        colormap_settings=colormap_settings, default_map_settings=default_map_settings,
        assets=assets, dirty_assets=dirty_assets, project_meta=project_meta,
        profile_id=getattr(profile, "profile_id", "hoi4-1.19") if profile is not None else "hoi4-1.19",
    )
    findings = collect_findings(
        snapshot,
        profile,
        dimensions,
        profile_name,
        lifecycle=active_lifecycle,
        game_target=target,
    )
    repairs: list = []
    repairs.extend(analyze_province_land_lake_sync(snapshot))
    repairs.extend(analyze_terrain_tile_sync(snapshot))
    repairs.extend(analyze_state_empty_cleanup(snapshot))
    repairs.extend(analyze_province_tiny_merge(snapshot))
    repairs.extend(analyze_province_bbox_trim(snapshot))
    repairs.extend(analyze_province_compact_ids(snapshot))
    repairs.extend(analyze_province_tile_sync(snapshot))
    repairs.extend(analyze_province_coastal_conversion(snapshot))
    repairs.extend(analyze_state_orphans(snapshot))
    if profile_name != "foundation":
        repairs.extend(analyze_state_unowned(snapshot))
        repairs.extend(analyze_country_capitals(snapshot))
    repairs.extend(analyze_region_alignment(snapshot))
    repairs.extend(analyze_region_split(snapshot))
    proposed, to_apply = split_repairs_by_policy(repairs, repair_policy, active_lifecycle)
    # An explicit dimension request is an approval boundary: profile errors
    # (including a mismatch between requested and actual arrays) must stop the
    # export.  Direct library callers that omit dimensions retain the legacy
    # compatibility behavior and receive the same issues as findings.
    resolutions = build_asset_resolutions(snapshot, profile_name, profile, scope, active_lifecycle)
    findings.extend(findings_for_asset_blockers(resolutions, profile, active_lifecycle))
    blockers = [note.message for note in findings
                if note.severity == "blocker"
                or (note.severity == "error" and dimensions is not None)]
    breaking = [repair for repair in proposed if repair.safety == "breaking"]
    if breaking and active_lifecycle in ("frozen", "accepted"):
        blockers.append(
            "lifecycle is %r: %d breaking repairs (%s) require unfreezing before export"
            % (active_lifecycle, len(breaking), ", ".join(sorted({r.code for r in breaking}))))
    acceptance_tags: tuple = ()
    if profile_name == "acceptance":
        from data.constants import get_vanilla_tags
        occupied = list(get_vanilla_tags(game_target=target))
        occupied.extend(list(vanilla_tags or ()))
        if country_mgr is not None:
            occupied.extend(list(getattr(country_mgr, "countries", {}) or {}))
        acceptance_tags = select_acceptance_tags(occupied, count=int(acceptance_count or 0))
    applied = apply_repair_actions(snapshot, to_apply)
    snapshot.fingerprint = compute_fingerprint(
        snapshot.tile_map, snapshot.province_map, snapshot.terrain_map,
        snapshot.managers_dict(), extra=profile_name,
    )
    return ExportPlan(
        profile_name=profile_name,
        game_target=target,
        game_profile=profile,
        lifecycle=active_lifecycle,
        repair_policy=repair_policy,
        layers=tuple(layers),
        scope=dict(scope or {}),
        snapshot=snapshot,
        proposed_repairs=list(proposed),
        applied_repairs=list(applied),
        asset_resolutions=list(resolutions),
        findings=list(findings),
        blockers=list(blockers),
        acceptance_tags=tuple(acceptance_tags),
        mod_name=str(mod_name or "WorldTest"),
        tag=str(tag or "AAA"),
    )


def plan_export_from_project(project, canvas=None, tile_map=None, province_map=None,
                             terrain_map=None, height_map=None, river_map=None,
                             **kwargs) -> ExportPlan:
    source = canvas if canvas is not None else getattr(project, "map_data", None)
    if tile_map is None:
        tile_map = getattr(source, "tile_map", None)
    if province_map is None:
        province_map = getattr(source, "province_map", None)
    if terrain_map is None:
        terrain_map = getattr(source, "terrain_map", None)
    if height_map is None:
        height_map = getattr(source, "height_map", None)
    if river_map is None:
        river_map = getattr(source, "river_map", None)
    provincial_terrain = getattr(source, "provincial_terrain", None)
    if tile_map is None or province_map is None:
        raise PlanRejected("project has no map arrays to plan an export from")
    for key in ("state_mgr", "country_mgr", "continent_mgr", "adjacency_mgr",
                "railway_mgr", "supply_mgr", "adjacency_rule_mgr", "strategic_region_mgr",
                "logistics_exception_mgr", "map_placement_mgr",
                "colormap_settings", "default_map_settings", "assets", "dirty_assets",
                "project_meta"):
        kwargs.setdefault(key, getattr(project, key, None))
    kwargs.setdefault("provincial_terrain", provincial_terrain)
    return plan_export(tile_map, province_map, terrain_map, height_map, river_map, **kwargs)


def format_plan_summary(plan: ExportPlan) -> str:
    target = getattr(plan, "game_target", None)
    if target is None:
        target_summary = "default target"
    else:
        target_summary = "%s (%s)" % (
            getattr(target, "install_dir", None) or "selected install",
            getattr(target, "supported_version", None) or "version unknown",
        )
    lines = [
        "target: %s | game profile: %s" % (
            target_summary,
            getattr(getattr(plan, "game_profile", None), "profile_id", None) or "unresolved",
        ),
        "profile: %s (lifecycle %s, repair %s)" % (plan.profile_name, plan.lifecycle, plan.repair_policy),
        "layers: %s" % ", ".join(plan.layers),
        "expected products: %d declared assets across %d stages" % (
            len(plan.asset_resolutions), len(plan.layers)),
        "proposed repairs: %d (safe=%d semantic=%d breaking=%d)" % (
            len(plan.proposed_repairs),
            len(plan.repairs_by_safety("safe")),
            len(plan.repairs_by_safety("semantic")),
            len(plan.repairs_by_safety("breaking"))),
        "applied repairs: %d" % len(plan.applied_repairs),
        "blockers: %d" % len(plan.blockers),
    ]
    for blocker in plan.blockers:
        lines.append("  [BLOCKER] %s" % blocker)
    for repair in plan.proposed_repairs:
        lines.append("  [%s/%s] %s: %s" % (repair.safety, repair.code, repair.layer, repair.summary))
    counts: dict = {}
    for resolution in plan.asset_resolutions:
        counts[resolution.disposition] = counts.get(resolution.disposition, 0) + 1
    lines.append("assets: %s" % ", ".join("%s=%d" % (key, counts.get(key, 0))
                                          for key in ("generated", "preserved", "inherited", "omitted", "unsupported")))
    if plan.acceptance_tags:
        lines.append("acceptance tags: %s" % ", ".join(plan.acceptance_tags))
    return "\n".join(lines)
