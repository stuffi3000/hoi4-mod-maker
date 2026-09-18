"""Export manifests, reports, and foundation-lock comparison (M2.5/M2.6).

Makes generated, preserved, inherited, and omitted assets visible for every
profile and supports lock comparison for the M3/M8 freeze workflow.

M3.4 adds a deterministic, path-independent foundation-manifest foundation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone


PRESERVED_CAPABLE_PATHS = (
    "map/world_normal.bmp",
    "map/terrain/colormap_rgb_cityemissivemask_a.dds",
    "map/terrain/colormap_water_0.dds",
    "map/terrain/colormap_water_1.dds",
    "map/terrain/colormap_water_2.dds",
    "map/terrain/fow_rgb_waterspec_a.dds",
)

WRITER_GENERATED_FILES = (
    "map/provinces.bmp",
    "map/heightmap.bmp",
    "map/terrain.bmp",
    "map/rivers.bmp",
    "map/trees.bmp",
    "map/cities.bmp",
    "map/world_normal.bmp",
    "map/terrain/colormap_rgb_cityemissivemask_a.dds",
    "map/terrain/colormap_water_0.dds",
    "map/terrain/colormap_water_1.dds",
    "map/terrain/colormap_water_2.dds",
    "map/terrain/fow_rgb_waterspec_a.dds",
    "map/definition.csv",
    "map/continent.txt",
    "map/adjacencies.csv",
    "map/adjacency_rules.txt",
    "map/default.map",
    "map/seasons.txt",
    "map/ambient_object.txt",
    "map/weatherpositions.txt",
    "map/buildings.txt",
    "map/positions.txt",
    "map/unitstacks.txt",
    "map/supply_nodes.txt",
    "map/railways.txt",
    "descriptor.mod",
)

CONTENT_ONLY_PATHS = (
    "history/countries",
    "common/country_tags",
    "common/countries",
    "common/characters",
    "common/units",
    "common/ideas",
    "common/names",
    "history/units",
    "localisation",
    "gfx/flags",
    "common/bookmarks",
)

DEPRECATED_PATHS_FALLBACK = ("map/colors.txt",)

MANIFEST_SCHEMA = "foundation-manifest/3.4"
MANIFEST_VERSION = "3.4"
MANIFEST_GENERATOR = "hoi4-mod-maker/export_manifest"
IDENTITY_HASH_ALGORITHM = "sha256-canonical-json-v1"
LOCK_SCHEMA = "foundation-lock/3.4"
LOCK_VERSION = "3.4"

CRITICAL_ARRAYS = ("tile", "province", "terrain", "height", "river")
MANAGER_KEYS = (
    "state_mgr",
    "country_mgr",
    "continent_mgr",
    "adjacency_mgr",
    "railway_mgr",
    "supply_mgr",
    "adjacency_rule_mgr",
    "strategic_region_mgr",
)
AUXILIARY_KEYS = (
    "provincial_terrain",
    "colormap_settings",
    "default_map_settings",
    "assets",
    "dirty_assets",
)
PORTABLE_TARGET_KEYS = (
    "profile_id",
    "raw_version",
    "display_version",
    "revision",
    "checksum",
    "supported_version",
)
TARGET_DIAGNOSTIC_KEYS = (
    "install_dir",
    "validated_at",
    "source",
    "required_files",
    "missing_files",
)
SCOPE_PATH_KEYS = frozenset({
    "replace_path",
    "output_dir",
    "install_dir",
    "game_dir",
    "game_install_dir",
})
CANONICAL_EXCLUDE_TOP_KEYS = ("metadata", "created_at", "tool_version")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tool_version() -> str:
    try:
        from version import VERSION
        return str(VERSION)
    except (ImportError, AttributeError):
        return "unknown"


def hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_written_files(output_dir: str) -> list:
    from domain.export_contract import WrittenFile
    written = []
    for root, _dirs, files in os.walk(output_dir):
        for name in sorted(files):
            full = os.path.join(root, name)
            try:
                size = os.path.getsize(full)
                digest = hash_file(full)
            except OSError:
                continue
            written.append(WrittenFile(os.path.relpath(full, output_dir).replace(os.sep, "/"), size, digest))
    return written


def validate_staged_artifacts(output_dir: str, plan) -> list[str]:
    """Validate the profile/layer products before a staged promotion.

    The legacy ``ModVerifier`` intentionally remains a stricter, engine-shaped
    checker and is not yet profile-aware enough for geography-only foundation
    shells.  This M2 gate checks the products promised by the selected stage
    graph without treating omitted profile content as an error.
    """
    errors: list[str] = []
    scope = dict(getattr(plan, "scope", {}) or {})

    def enabled(key: str) -> bool:
        return bool(scope.get(key, True))

    def require_file(rel_path: str) -> None:
        path = os.path.join(output_dir, rel_path.replace("/", os.sep))
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            errors.append("missing or empty staged file: %s" % rel_path)

    def require_dir(rel_path: str) -> None:
        path = os.path.join(output_dir, rel_path.replace("/", os.sep))
        files = []
        if os.path.isdir(path):
            for root, _dirs, names in os.walk(path):
                files.extend(os.path.join(root, name) for name in names)
        if not files:
            errors.append("missing or empty staged directory: %s" % rel_path)

    if enabled("map"):
        for rel_path in (
            "map/provinces.bmp", "map/heightmap.bmp", "map/terrain.bmp",
            "map/rivers.bmp", "map/definition.csv", "map/default.map",
            "map/continent.txt", "map/adjacencies.csv", "map/adjacency_rules.txt",
            "map/seasons.txt", "map/ambient_object.txt", "map/buildings.txt",
            "map/positions.txt",
        ):
            require_file(rel_path)
    if enabled("strategic_regions"):
        require_dir("map/strategicregions")
    if enabled("supply"):
        require_file("map/supply_nodes.txt")
        require_file("map/railways.txt")
    if enabled("states"):
        require_dir("history/states")
    if enabled("countries") and getattr(plan, "profile_name", "") in ("acceptance", "scaffold", "legacy_full"):
        require_dir("history/countries")
        require_dir("history/units")
        require_dir("common/country_tags")
    if enabled("localisation") and getattr(plan, "profile_name", "") != "foundation":
        require_dir("localisation")
    if (enabled("gfx") and getattr(plan, "profile_name", "") in ("scaffold", "legacy_full")):
        require_dir("gfx/flags")
    if enabled("descriptor"):
        require_file("descriptor.mod")
    return errors


def _hash_array(arr) -> str:
    if arr is None:
        return "none"
    try:
        import numpy as np
        digest = hashlib.sha256()
        digest.update(str(arr.shape).encode("utf-8"))
        digest.update(str(arr.dtype).encode("utf-8"))
        digest.update(np.ascontiguousarray(arr).tobytes())
        return digest.hexdigest()
    except Exception:
        return "unhashable"


def _canonicalize(value, active=None):
    if active is None:
        active = set()
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    try:
        import numpy as np
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
    except ImportError:
        pass
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


def _digest_canonical(value) -> str:
    payload = json.dumps(_canonicalize(value), ensure_ascii=True, sort_keys=True,
                         separators=(",", ":"), allow_nan=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()



def _source_array_hashes(snapshot) -> dict:
    if snapshot is None:
        return {key: "none" for key in CRITICAL_ARRAYS}
    mapping = {
        "tile": getattr(snapshot, "tile_map", None),
        "province": getattr(snapshot, "province_map", None),
        "terrain": getattr(snapshot, "terrain_map", None),
        "height": getattr(snapshot, "height_map", None),
        "river": getattr(snapshot, "river_map", None),
    }
    return {key: _hash_array(value) for key, value in mapping.items()}


def _source_manager_hashes(snapshot) -> dict:
    if snapshot is None:
        return {key: "none" for key in MANAGER_KEYS}
    managers = None
    getter = getattr(snapshot, "managers_dict", None)
    if callable(getter):
        try:
            managers = getter()
        except Exception:
            managers = None
    if not isinstance(managers, dict):
        try:
            managers = {key: getattr(snapshot, key, None) for key in MANAGER_KEYS}
        except Exception:
            managers = {}
    result: dict = {}
    for key in MANAGER_KEYS:
        manager = managers.get(key) if isinstance(managers, dict) else None
        if manager is None:
            result[key] = "none"
            continue
        try:
            result[key] = _digest_canonical(manager)
        except Exception:
            result[key] = "unhashable"
    return result


def _source_auxiliary_hashes(snapshot) -> dict:
    if snapshot is None:
        return {key: "none" for key in AUXILIARY_KEYS}
    values = {
        "provincial_terrain": getattr(snapshot, "provincial_terrain", {}),
        "colormap_settings": getattr(snapshot, "colormap_settings", None),
        "default_map_settings": getattr(snapshot, "default_map_settings", None),
        "assets": getattr(snapshot, "assets", {}),
        "dirty_assets": getattr(snapshot, "dirty_assets", ()),
    }
    result: dict = {}
    for key in AUXILIARY_KEYS:
        try:
            result[key] = _digest_canonical(values.get(key))
        except Exception:
            result[key] = "unhashable"
    return result


def _target_to_dict(game_target):
    if game_target is None:
        return None
    to_dict = getattr(game_target, "to_dict", None)
    if callable(to_dict):
        try:
            data = to_dict()
            if isinstance(data, dict):
                return dict(data)
        except Exception:
            pass
    if isinstance(game_target, dict):
        return dict(game_target)
    data: dict = {}
    for key in PORTABLE_TARGET_KEYS + TARGET_DIAGNOSTIC_KEYS:
        try:
            if hasattr(game_target, key):
                data[key] = getattr(game_target, key)
        except Exception:
            continue
    if data:
        return data
    return None


def _portable_target_identity(game_target, game_profile=None, snapshot=None) -> dict:
    data = _target_to_dict(game_target) or {}
    identity = {key: data.get(key) for key in PORTABLE_TARGET_KEYS}
    profile_id = None
    if game_profile is not None:
        if isinstance(game_profile, dict):
            profile_id = game_profile.get("profile_id")
        elif isinstance(game_profile, str):
            profile_id = game_profile
        else:
            try:
                profile_id = getattr(game_profile, "profile_id", None)
            except Exception:
                profile_id = None
    if profile_id is None:
        profile_id = data.get("profile_id")
    if profile_id is None and snapshot is not None:
        try:
            profile_id = getattr(snapshot, "profile_id", None)
        except Exception:
            profile_id = None
    identity["game_profile"] = profile_id
    return identity


def _target_diagnostics(game_target) -> dict:
    data = _target_to_dict(game_target) or {}
    required = data.get("required_files") or {}
    if isinstance(required, dict):
        try:
            required = {str(key): bool(value) for key, value in sorted(required.items(), key=lambda kv: str(kv[0]))}
        except Exception:
            required = {str(key): bool(value) for key, value in required.items()}
    else:
        required = {}
    missing = data.get("missing_files") or []
    try:
        missing = sorted(str(value) for value in missing)
    except Exception:
        try:
            missing = [str(value) for value in list(missing)]
        except Exception:
            missing = []
    is_usable = None
    if game_target is not None and not isinstance(game_target, dict):
        try:
            prop = getattr(game_target, "is_usable", None)
            if prop is not None:
                is_usable = bool(prop() if callable(prop) else prop)
        except Exception:
            is_usable = None
    return {
        "install_dir": data.get("install_dir"),
        "validated_at": data.get("validated_at"),
        "source": data.get("source"),
        "required_files": required,
        "missing_files": missing,
        "is_usable": is_usable,
    }


def _game_profile_detail(game_profile):
    if game_profile is None:
        return None
    if isinstance(game_profile, str):
        return {"profile_id": game_profile}
    if isinstance(game_profile, dict):
        return {
            "profile_id": game_profile.get("profile_id"),
            "display_name": game_profile.get("display_name"),
            "supported_version_pattern": game_profile.get("supported_version_pattern"),
        }
    try:
        return {
            "profile_id": getattr(game_profile, "profile_id", None),
            "display_name": getattr(game_profile, "display_name", None),
            "supported_version_pattern": getattr(game_profile, "supported_version_pattern", None),
        }
    except Exception:
        return None


def _portable_project(snapshot) -> dict:
    if snapshot is None:
        return {"schema_version": None, "profile_id": None, "generator_version": None}
    try:
        profile_id = getattr(snapshot, "profile_id", None)
    except Exception:
        profile_id = None
    meta = None
    try:
        meta = getattr(snapshot, "project_meta", None)
    except Exception:
        meta = None
    schema_version = None
    generator_version = None
    meta_profile = None
    if meta is not None:
        try:
            if isinstance(meta, dict):
                schema_version = meta.get("schema_version")
                generator_version = meta.get("generator_version")
                game = meta.get("game") or {}
                if isinstance(game, dict):
                    meta_profile = game.get("profile_id")
                if meta_profile is None:
                    meta_profile = meta.get("profile_id")
            else:
                schema_version = getattr(meta, "schema_version", None)
                generator_version = getattr(meta, "generator_version", None)
                try:
                    meta_profile = getattr(meta, "profile_id", None)
                except Exception:
                    meta_profile = None
        except Exception:
            pass
    resolved = profile_id if profile_id is not None else meta_profile
    return {
        "schema_version": schema_version,
        "profile_id": resolved,
        "generator_version": generator_version,
    }


def _portable_scope(scope) -> dict:
    base = dict(scope or {})
    return {str(key): base[key] for key in base if str(key) not in SCOPE_PATH_KEYS}



def _asset_counts(plan) -> dict:
    counts: dict = {}
    for resolution in getattr(plan, "asset_resolutions", []) or []:
        if isinstance(resolution, dict):
            disposition = resolution.get("disposition", "unknown")
        else:
            disposition = getattr(resolution, "disposition", "unknown")
        counts[disposition] = counts.get(disposition, 0) + 1
    return counts


def _manager_count(manager):
    if manager is None:
        return None
    try:
        states = getattr(manager, "states", None)
        if isinstance(states, dict):
            return int(len(states))
        countries = getattr(manager, "countries", None)
        if isinstance(countries, dict):
            return int(len(countries))
        count_fn = getattr(manager, "count", None)
        if callable(count_fn):
            try:
                return int(count_fn())
            except Exception:
                pass
        names = getattr(manager, "_names", None)
        if isinstance(names, list):
            return int(len(names))
        get_all = getattr(manager, "get_all", None)
        if callable(get_all):
            try:
                return int(len(get_all()))
            except Exception:
                pass
        for attr in ("regions", "entries", "nodes", "railways", "adjacencies", "rules"):
            try:
                value = getattr(manager, attr, None)
            except Exception:
                continue
            if isinstance(value, dict):
                return int(len(value))
            if isinstance(value, (list, tuple, set, frozenset)):
                return int(len(value))
        try:
            return int(len(manager))
        except Exception:
            return None
    except Exception:
        return None


def _stable_counts(plan, snapshot) -> dict:
    province_ids = 0
    province_max = 0
    prov_map = None
    try:
        prov_map = getattr(snapshot, "province_map", None) if snapshot is not None else None
    except Exception:
        prov_map = None
    if prov_map is not None:
        try:
            import numpy as np
            arr = np.asanyarray(prov_map)
            if arr.size:
                try:
                    province_max = int(arr.max())
                except Exception:
                    province_max = 0
                try:
                    uniq = np.unique(arr.ravel())
                    count = 0
                    for value in uniq.tolist():
                        try:
                            if int(value) != 0:
                                count += 1
                        except Exception:
                            count += 1
                    province_ids = int(count)
                except Exception:
                    province_ids = 0
        except Exception:
            province_ids = 0
            province_max = 0
    try:
        width = int(getattr(snapshot, "width", 0) or 0) if snapshot is not None else 0
    except Exception:
        width = 0
    try:
        height = int(getattr(snapshot, "height", 0) or 0) if snapshot is not None else 0
    except Exception:
        height = 0
    mgr_dict = None
    if snapshot is not None:
        getter = getattr(snapshot, "managers_dict", None)
        if callable(getter):
            try:
                mgr_dict = getter()
            except Exception:
                mgr_dict = None
        if not isinstance(mgr_dict, dict):
            try:
                mgr_dict = {key: getattr(snapshot, key, None) for key in MANAGER_KEYS}
            except Exception:
                mgr_dict = {}
    else:
        mgr_dict = {}
    managers: dict = {}
    for key in MANAGER_KEYS:
        try:
            managers[key] = _manager_count((mgr_dict or {}).get(key))
        except Exception:
            managers[key] = None
    return {
        "province_ids": int(province_ids),
        "province_max": int(province_max),
        "map_pixels": int(width * height) if width and height else 0,
        "managers": managers,
    }


def _repair_to_dict(entry):
    if hasattr(entry, "to_dict"):
        try:
            return entry.to_dict()
        except Exception:
            pass
    if isinstance(entry, dict):
        return dict(entry)
    return {"value": str(entry)}


def _finding_to_dict(entry):
    if hasattr(entry, "to_dict"):
        try:
            return entry.to_dict()
        except Exception:
            pass
    if isinstance(entry, dict):
        return dict(entry)
    return {"value": str(entry)}


def _sorted_written_files(written_files) -> list:
    items = []
    for entry in list(written_files or []):
        if hasattr(entry, "to_dict"):
            try:
                items.append(entry.to_dict())
                continue
            except Exception:
                pass
        if isinstance(entry, dict):
            items.append(dict(entry))
        else:
            items.append(entry)
    def _key(item):
        if isinstance(item, dict):
            return str(item.get("rel_path", repr(item)))
        return str(item)
    try:
        return sorted(items, key=_key)
    except Exception:
        return items


def _sorted_asset_resolutions(asset_resolutions) -> list:
    items = []
    for entry in list(asset_resolutions or []):
        if hasattr(entry, "to_dict"):
            try:
                items.append(entry.to_dict())
                continue
            except Exception:
                pass
        if isinstance(entry, dict):
            items.append(dict(entry))
        else:
            items.append(entry)
    def _key(item):
        if isinstance(item, dict):
            return str(item.get("rel_path", repr(item)))
        return str(item)
    try:
        return sorted(items, key=_key)
    except Exception:
        return items


def _sorted_strings(values) -> list:
    items = list(values or [])
    try:
        def _key(value):
            if isinstance(value, dict):
                try:
                    return json.dumps(value, sort_keys=True, default=str)
                except Exception:
                    return repr(value)
            return str(value)
        return sorted(items, key=_key)
    except Exception:
        return items


def _sorted_stages(stage_results) -> list:
    out = []
    for entry in list(stage_results or []):
        if hasattr(entry, "to_dict"):
            try:
                data = entry.to_dict()
            except Exception:
                continue
        elif isinstance(entry, dict):
            data = dict(entry)
        else:
            continue
        if not isinstance(data, dict):
            continue
        owned = data.get("owned_files") or []
        try:
            data["owned_files"] = sorted(str(value) for value in owned)
        except Exception:
            pass
        written = data.get("written") or []
        try:
            norm = []
            for item in written:
                if hasattr(item, "to_dict"):
                    try:
                        norm.append(item.to_dict())
                        continue
                    except Exception:
                        pass
                if isinstance(item, dict):
                    norm.append(dict(item))
                else:
                    norm.append(item)
            def _wkey(item):
                if isinstance(item, dict):
                    return str(item.get("rel_path", repr(item)))
                return str(item)
            data["written"] = sorted(norm, key=_wkey)
        except Exception:
            pass
        out.append(data)
    out.sort(
        key=lambda item: (
            str(item.get("stage", "")),
            json.dumps(item, ensure_ascii=True, sort_keys=True, default=str),
        )
    )
    return out


# Stable fallback label for manifest files no export stage can own.
OWNERSHIP_FALLBACK_STAGE = "unowned"


def _normalize_manifest_path(value) -> str:
    try:
        text = str(value)
    except Exception:
        return ""
    text = text.strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.strip().strip("/")


def _stage_name_of(entry):
    name = None
    if isinstance(entry, dict):
        name = entry.get("stage")
    else:
        try:
            name = getattr(entry, "stage", None)
        except Exception:
            name = None
    if name is None:
        return None
    try:
        text = str(name).strip()
    except Exception:
        return None
    return text or None


def _stage_written_paths(entry) -> list:
    if isinstance(entry, dict):
        written = entry.get("written") or []
    else:
        try:
            written = getattr(entry, "written", None) or []
        except Exception:
            written = []
    if isinstance(written, str):
        candidates = [written]
    else:
        try:
            candidates = list(written)
        except TypeError:
            return []
    paths = []
    for item in candidates:
        rel = None
        if isinstance(item, dict):
            rel = item.get("rel_path")
        else:
            converter = getattr(item, "to_dict", None)
            if callable(converter):
                try:
                    data = converter()
                except Exception:
                    data = None
                if isinstance(data, dict):
                    rel = data.get("rel_path")
            if rel is None:
                try:
                    rel = getattr(item, "rel_path", None)
                except Exception:
                    rel = None
            if rel is None and isinstance(item, str):
                rel = item
        if rel is None:
            continue
        norm = _normalize_manifest_path(rel)
        if norm:
            paths.append(norm)
    return paths


def _stage_owned_paths(entry) -> list:
    if isinstance(entry, dict):
        owned = entry.get("owned_files") or []
    else:
        try:
            owned = getattr(entry, "owned_files", None) or []
        except Exception:
            owned = []
    if isinstance(owned, str):
        candidates = [owned]
    else:
        try:
            candidates = list(owned)
        except TypeError:
            return []
    paths = []
    for item in candidates:
        try:
            text = str(item)
        except Exception:
            continue
        norm = _normalize_manifest_path(text)
        if norm:
            paths.append(norm)
    return paths


def _build_stage_ownership(stage_results) -> tuple:
    # Map normalized paths to stage names in a stable, sorted order. Only
    # entries with a usable stage name take part in the join, so records
    # without one stay out of ownership while remaining in stages output.
    # Exact written claims win over owned prefixes, the longest prefix wins,
    # and stage-name order breaks remaining ties.
    try:
        entries = list(stage_results or [])
    except TypeError:
        return {}, []
    named = []
    for entry in entries:
        name = _stage_name_of(entry)
        if not name:
            continue
        named.append((name, entry))
    named.sort(key=lambda pair: pair[0])
    written_claims: dict = {}
    for name, entry in named:
        for path in _stage_written_paths(entry):
            if path not in written_claims:
                written_claims[path] = name
    owned_claims: dict = {}
    for name, entry in named:
        for path in _stage_owned_paths(entry):
            if path not in owned_claims:
                owned_claims[path] = name
    owned_prefixes = sorted(
        owned_claims.items(), key=lambda item: (-len(item[0]), item[1], item[0])
    )
    return written_claims, owned_prefixes


def _resolve_file_stage(rel_path, written_claims, owned_prefixes) -> str:
    norm = _normalize_manifest_path(rel_path)
    if not norm:
        return OWNERSHIP_FALLBACK_STAGE
    try:
        stage = (written_claims or {}).get(norm)
    except Exception:
        stage = None
    if stage:
        return stage
    try:
        prefixes = list(owned_prefixes or [])
    except TypeError:
        prefixes = []
    for prefix, stage in prefixes:
        if norm == prefix or norm.startswith(prefix + "/"):
            return stage
    return OWNERSHIP_FALLBACK_STAGE


def _enrich_written_files(written_files, stage_results) -> list:
    # Return sorted written-file dicts with a deterministic stage label.
    # Labels derive from caller supplied StageResult metadata only, so no
    # filesystem I/O happens here. Files no stage claims fall back to
    # OWNERSHIP_FALLBACK_STAGE. Inputs are copied, never mutated, and any
    # pre-existing stage label is recomputed deterministically.
    items = _sorted_written_files(written_files)
    written_claims, owned_prefixes = _build_stage_ownership(stage_results)
    enriched = []
    for item in items:
        if isinstance(item, dict):
            rel = item.get("rel_path")
            if rel is None:
                rel = ""
            item["stage"] = _resolve_file_stage(rel, written_claims, owned_prefixes)
            enriched.append(item)
            continue
        try:
            rel = str(item)
        except Exception:
            continue
        enriched.append(
            {
                "rel_path": rel,
                "size": 0,
                "sha256": "",
                "stage": _resolve_file_stage(rel, written_claims, owned_prefixes),
            }
        )
    return enriched


def _sha256_of_bytes(value) -> str:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return ""
    try:
        return hashlib.sha256(bytes(value)).hexdigest()
    except Exception:
        return ""


def _written_hash_index(written_files) -> dict:
    try:
        entries = list(written_files or [])
    except TypeError:
        return {}
    candidates: dict = {}
    for entry in entries:
        rel = None
        digest = ""
        if isinstance(entry, dict):
            rel = entry.get("rel_path")
            digest = entry.get("sha256") or ""
        else:
            converter = getattr(entry, "to_dict", None)
            data = None
            if callable(converter):
                try:
                    data = converter()
                except Exception:
                    data = None
            if isinstance(data, dict):
                rel = data.get("rel_path")
                digest = data.get("sha256") or ""
            else:
                try:
                    rel = getattr(entry, "rel_path", None)
                except Exception:
                    rel = None
                try:
                    digest = getattr(entry, "sha256", "") or ""
                except Exception:
                    digest = ""
        if rel is None:
            continue
        norm = _normalize_manifest_path(rel)
        if not norm:
            continue
        try:
            text = str(digest) if digest else ""
        except Exception:
            text = ""
        candidates.setdefault(norm, []).append(text)
    index = {}
    for norm, digests in candidates.items():
        non_empty = sorted(value for value in digests if value)
        index[norm] = non_empty[0] if non_empty else ""
    return index


def _enrich_asset_resolutions(asset_resolutions, snapshot_assets, written_hashes) -> list:
    # Return sorted asset dicts with deterministic provenance hashes.
    # source_sha256 hashes the byte-like snapshot asset for the same path and
    # stays empty when no byte value exists; output_sha256 reuses the staged
    # written-file hash when available and stays empty otherwise. Missing
    # metadata is never invented. All AssetResolution fields and the stable
    # path ordering are preserved, and inputs are copied, never mutated.
    items = _sorted_asset_resolutions(asset_resolutions)
    normalized_assets: dict = {}
    if isinstance(snapshot_assets, dict):
        try:
            ordered_keys = sorted(snapshot_assets, key=lambda key: str(key))
        except Exception:
            try:
                ordered_keys = list(snapshot_assets)
            except TypeError:
                ordered_keys = []
        for key in ordered_keys:
            norm = _normalize_manifest_path(key)
            if norm and norm not in normalized_assets:
                try:
                    normalized_assets[norm] = snapshot_assets[key]
                except Exception:
                    continue
    try:
        hashes = dict(written_hashes or {})
    except Exception:
        hashes = {}
    enriched = []
    for item in items:
        if not isinstance(item, dict):
            enriched.append(item)
            continue
        rel = item.get("rel_path")
        norm = _normalize_manifest_path(rel) if rel is not None else ""
        if norm in normalized_assets:
            item["source_sha256"] = _sha256_of_bytes(normalized_assets[norm])
        else:
            item["source_sha256"] = ""
        try:
            output = hashes.get(norm, "") if norm else ""
            item["output_sha256"] = str(output) if output else ""
        except Exception:
            item["output_sha256"] = ""
        enriched.append(item)
    return enriched


def _compute_identity_hash(profile_name, portable_target, portable_project, map_size, layers, portable_scope, sources, snapshot_fingerprint) -> str:
    payload = {
        "layers": list(layers or []),
        "map_size": dict(map_size or {}),
        "profile": profile_name,
        "project": dict(portable_project or {}),
        "scope": dict(portable_scope or {}),
        "snapshot_fingerprint": snapshot_fingerprint,
        "sources": sources,
        "target": dict(portable_target or {}),
    }
    canonical = json.dumps(_canonicalize(payload), ensure_ascii=True, sort_keys=True,
                           separators=(",", ":"), allow_nan=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()



def _validation_gate_contexts():
    """Return known gate contexts, preferring the shared contract."""
    try:
        from domain.validation import GATE_CONTEXTS as shared_contexts
        contexts = tuple(shared_contexts)
        if contexts:
            return contexts
    except Exception:
        pass
    return ("draft_preview", "foundation_candidate", "freeze", "acceptance", "accepted_lock")


def _normalize_gate_context(value):
    """Return a valid gate context string or None without raising."""
    try:
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        if text in _validation_gate_contexts():
            return text
        return None
    except Exception:
        return None


def _fallback_gate_context(plan):
    """Derive a deterministic gate context from plan profile and lifecycle."""
    try:
        candidate = getattr(plan, "validation_context", None)
        normalized = _normalize_gate_context(candidate)
        if normalized:
            return normalized
    except Exception:
        pass
    profile_name = ""
    lifecycle_name = ""
    try:
        profile_name = str(getattr(plan, "profile_name", "") or "").strip()
    except Exception:
        profile_name = ""
    try:
        lifecycle_name = str(getattr(plan, "lifecycle", "") or "").strip()
    except Exception:
        lifecycle_name = ""
    if profile_name == "acceptance":
        return "acceptance"
    mapping = {
        "draft": "draft_preview",
        "candidate": "foundation_candidate",
        "frozen": "freeze",
        "accepted": "accepted_lock",
    }
    if lifecycle_name in mapping:
        return mapping[lifecycle_name]
    try:
        contexts = _validation_gate_contexts()
        if lifecycle_name in contexts:
            return lifecycle_name
        if profile_name in contexts:
            return profile_name
    except Exception:
        pass
    return "draft_preview"


def _extract_report_context(value):
    """Return the preserved report context when valid, else None."""
    try:
        from domain.validation import ValidationReport as SharedReport
        if isinstance(value, SharedReport):
            return _normalize_gate_context(value.context)
    except Exception:
        pass
    try:
        if isinstance(value, dict):
            raw = value.get("context", None)
        else:
            raw = getattr(value, "context", None)
        return _normalize_gate_context(raw)
    except Exception:
        return None


def _extract_report_source(value):
    """Return the preserved report source string without raising."""
    try:
        from domain.validation import ValidationReport as SharedReport
        if isinstance(value, SharedReport):
            try:
                text = str(value.source or "").strip()
                return text
            except Exception:
                return ""
    except Exception:
        pass
    try:
        if isinstance(value, dict):
            raw = value.get("source", value.get("report_source", ""))
        else:
            raw = getattr(value, "source", "")
        if raw is None:
            return ""
        return str(raw).strip()
    except Exception:
        return ""
def _stable_sort_key(value):
    """Return a deterministic sort key for arbitrary JSON-like values."""
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return ""


def _deepcopy_value(value):
    """Return a deep copy without mutating the input."""
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _is_shared_validation_report(value):
    """Return True for shared ValidationReport instances without raising."""
    try:
        from domain.validation import ValidationReport as SharedReport
        return isinstance(value, SharedReport)
    except Exception:
        return False


def _mapping_looks_like_report(data):
    """Return True when a mapping carries report-shaped keys."""
    try:
        if not isinstance(data, dict):
            return False
        for key_name in ("findings", "source", "context", "total", "counts"):
            if key_name in data:
                return True
        return False
    except Exception:
        return False


def _accepted_keys_for(value):
    """Return sorted accepted-exception keys using the shared normalizer."""
    try:
        from domain.validation import _normalize_accepted_keys as shared_normalize
        return sorted(shared_normalize(value))
    except Exception:
        return []


def _accepted_records_for(value):
    """Return sorted accepted-exception record copies without mutation."""
    try:
        if value is None:
            return []
        if isinstance(value, str):
            return []
        if isinstance(value, dict):
            exceptions_value = value.get("validation_exceptions", None)
            if isinstance(exceptions_value, (list, tuple, set, frozenset)):
                return _accepted_records_for(exceptions_value)
            try:
                copied = dict(value)
            except Exception:
                return []
            has_key = False
            for key_name in ("exception_id", "id", "code", "reason", "reviewed_by", "reviewed_at"):
                if key_name in copied:
                    has_key = True
                    break
            if not has_key:
                return []
            try:
                ordered = {str(key): copied[key] for key in sorted(copied, key=lambda item: str(item))}
            except Exception:
                ordered = copied
            return [ordered]
        try:
            items = list(value)
        except TypeError:
            return []
        records = []
        for entry in items:
            if isinstance(entry, dict):
                try:
                    copied = dict(entry)
                except Exception:
                    continue
                try:
                    ordered = {str(key): copied[key] for key in sorted(copied, key=lambda item: str(item))}
                except Exception:
                    ordered = copied
                records.append(ordered)
        try:
            records.sort(key=_stable_sort_key)
        except Exception:
            pass
        return records
    except Exception:
        return []
def _collect_accepted_exceptions(plan, explicit_accepted, explicit_validation_exceptions, explicit_report):
    """Collect accepted records, gate input, and keys without mutation."""
    raw = None
    has_explicit = False
    try:
        if explicit_accepted is not None:
            raw = explicit_accepted
            has_explicit = True
        elif explicit_validation_exceptions is not None:
            raw = explicit_validation_exceptions
            has_explicit = True
        elif isinstance(explicit_report, dict):
            for key_name in ("accepted_exceptions", "validation_exceptions", "accepted", "accepted_keys"):
                if key_name in explicit_report:
                    try:
                        candidate = explicit_report.get(key_name, None)
                    except Exception:
                        candidate = None
                    if candidate is not None:
                        raw = candidate
                        has_explicit = True
                        break
    except Exception:
        raw = None
        has_explicit = False
    if not has_explicit:
        try:
            for attr_name in ("accepted_exceptions", "validation_exceptions"):
                try:
                    candidate = getattr(plan, attr_name, None)
                except Exception:
                    candidate = None
                if candidate is not None:
                    raw = candidate
                    has_explicit = True
                    break
        except Exception:
            pass
    if not has_explicit:
        try:
            snapshot = getattr(plan, "snapshot", None)
        except Exception:
            snapshot = None
        meta = None
        try:
            if snapshot is not None:
                meta = getattr(snapshot, "project_meta", None)
        except Exception:
            meta = None
        if meta is None:
            try:
                meta = getattr(plan, "project_meta", None)
            except Exception:
                meta = None
        if meta is not None:
            try:
                if isinstance(meta, dict):
                    if "validation_exceptions" in meta:
                        raw = meta.get("validation_exceptions", None)
                    elif "accepted_exceptions" in meta:
                        raw = meta.get("accepted_exceptions", None)
                    else:
                        raw = None
                else:
                    for attr_name in ("validation_exceptions", "accepted_exceptions"):
                        try:
                            candidate = getattr(meta, attr_name, None)
                        except Exception:
                            candidate = None
                        if candidate is not None:
                            raw = candidate
                            break
            except Exception:
                raw = None
    if raw is None:
        raw = []
    try:
        records = _accepted_records_for(raw)
    except Exception:
        records = []
    try:
        keys = _accepted_keys_for(raw)
    except Exception:
        keys = []
    return records, raw, keys


def _safe_build_validation_report(findings_value, source_value, context_value):
    """Build a shared ValidationReport tolerantly without mutation."""
    try:
        from domain.validation import ValidationReport as SharedReport
        from domain.validation import coerce_finding as shared_coerce
    except Exception:
        return None
    try:
        normalized_context = _normalize_gate_context(context_value) or "draft_preview"
    except Exception:
        normalized_context = "draft_preview"
    try:
        if source_value is None:
            source_text = ""
        else:
            source_text = str(source_value).strip() if source_value else ""
    except Exception:
        source_text = ""
    collected = []
    try:
        if findings_value is None:
            raw_items = []
        elif isinstance(findings_value, (str, bytes)):
            raw_items = []
        else:
            if hasattr(findings_value, "code") and hasattr(findings_value, "severity"):
                raw_items = [findings_value]
            elif isinstance(findings_value, dict):
                raw_items = [findings_value]
            else:
                try:
                    raw_items = list(findings_value)
                except TypeError:
                    raw_items = [findings_value]
        for item in raw_items:
            try:
                collected.append(shared_coerce(item))
            except Exception:
                continue
    except Exception:
        collected = []
    try:
        return SharedReport(findings=tuple(collected), source=source_text, context=normalized_context)
    except Exception:
        try:
            return SharedReport(findings=(), source=source_text, context="draft_preview")
        except Exception:
            return None
def _resolve_validation_report(plan, explicit_report, explicit_context):
    """Resolve findings, source, and deterministic context without mutation."""
    try:
        normalized_explicit = _normalize_gate_context(explicit_context)
    except Exception:
        normalized_explicit = None
    try:
        plan_report = getattr(plan, "validation_report", None)
    except Exception:
        plan_report = None
    selected = None
    try:
        if normalized_explicit:
            selected = normalized_explicit
        else:
            explicit_ctx = _extract_report_context(explicit_report) if explicit_report is not None else None
            if explicit_ctx:
                selected = explicit_ctx
            else:
                plan_ctx = _extract_report_context(plan_report) if plan_report is not None else None
                if plan_ctx:
                    selected = plan_ctx
                else:
                    selected = _fallback_gate_context(plan)
    except Exception:
        selected = None
    if not selected:
        selected = "draft_preview"
    origin = "plan.findings"
    source_text = "plan.findings"
    findings_value = None
    try:
        if explicit_report is not None:
            origin = "explicit"
            if _is_shared_validation_report(explicit_report):
                try:
                    source_text = str(explicit_report.source or "").strip() or "explicit"
                except Exception:
                    source_text = "explicit"
                try:
                    findings_value = list(explicit_report.findings)
                except Exception:
                    findings_value = []
            elif isinstance(explicit_report, dict) and _mapping_looks_like_report(explicit_report):
                try:
                    source_text = str(explicit_report.get("source", "") or "").strip() or "explicit"
                except Exception:
                    source_text = "explicit"
                try:
                    findings_value = explicit_report.get("findings", [])
                except Exception:
                    findings_value = []
            elif isinstance(explicit_report, (list, tuple)):
                source_text = "explicit"
                findings_value = explicit_report
            elif hasattr(explicit_report, "to_dict") and callable(getattr(explicit_report, "to_dict")):
                try:
                    data = explicit_report.to_dict()
                except Exception:
                    data = None
                if isinstance(data, dict) and _mapping_looks_like_report(data):
                    try:
                        source_text = str(data.get("source", "") or "").strip() or "explicit"
                    except Exception:
                        source_text = "explicit"
                    try:
                        findings_value = data.get("findings", [])
                    except Exception:
                        findings_value = []
                else:
                    source_text = "explicit"
                    findings_value = []
            else:
                source_text = "explicit"
                findings_value = []
        elif plan_report is not None:
            origin = "plan.validation_report"
            if _is_shared_validation_report(plan_report):
                try:
                    source_text = str(plan_report.source or "").strip() or "plan.validation_report"
                except Exception:
                    source_text = "plan.validation_report"
                try:
                    findings_value = list(plan_report.findings)
                except Exception:
                    findings_value = []
            elif isinstance(plan_report, dict) and _mapping_looks_like_report(plan_report):
                try:
                    source_text = str(plan_report.get("source", "") or "").strip() or "plan.validation_report"
                except Exception:
                    source_text = "plan.validation_report"
                try:
                    findings_value = plan_report.get("findings", [])
                except Exception:
                    findings_value = []
            elif isinstance(plan_report, (list, tuple)):
                source_text = "plan.validation_report"
                findings_value = plan_report
            elif hasattr(plan_report, "to_dict") and callable(getattr(plan_report, "to_dict")):
                try:
                    data = plan_report.to_dict()
                except Exception:
                    data = None
                if isinstance(data, dict) and _mapping_looks_like_report(data):
                    try:
                        source_text = str(data.get("source", "") or "").strip() or "plan.validation_report"
                    except Exception:
                        source_text = "plan.validation_report"
                    try:
                        findings_value = data.get("findings", [])
                    except Exception:
                        findings_value = []
                else:
                    source_text = "plan.validation_report"
                    findings_value = []
            else:
                source_text = "plan.validation_report"
                findings_value = []
        else:
            origin = "plan.findings"
            source_text = "plan.findings"
            try:
                findings_value = getattr(plan, "findings", []) or []
            except Exception:
                findings_value = []
    except Exception:
        origin = "plan.findings"
        source_text = "plan.findings"
        findings_value = []
    try:
        report = _safe_build_validation_report(findings_value, source_text, selected)
    except Exception:
        report = None
    if report is None:
        try:
            report = _safe_build_validation_report([], source_text or "plan.findings", selected or "draft_preview")
        except Exception:
            report = None
    return report, origin, selected
def _copy_finding_dicts(value):
    """Copy finding-like dicts without mutation."""
    try:
        items = list(value or [])
    except Exception:
        return []
    copied = []
    for entry in items:
        try:
            if isinstance(entry, dict):
                copied.append({str(key): _deepcopy_value(val) for key, val in entry.items()})
            else:
                copied.append(_deepcopy_value(entry))
        except Exception:
            continue
    return copied


def _safe_validation_fallback():
    """Return a deterministic empty validation section without dependencies."""
    return {
        "source": "plan.findings",
        "context": "draft_preview",
        "total": 0,
        "counts": {"info": 0, "warning": 0, "error": 0, "blocker": 0},
        "findings": [],
        "gate": {
            "context": "draft_preview",
            "allowed": True,
            "blocking": [],
            "visible_warnings": [],
            "waived": [],
        },
        "accepted_exceptions": [],
        "accepted_keys": [],
        "report_source": "plan.findings",
        "report_context": "draft_preview",
        "report_origin": "plan.findings",
    }


def _build_validation_section(plan, explicit_report, explicit_context, explicit_accepted, explicit_validation_exceptions):
    """Serialize validation findings, gate state, and exceptions deterministically."""
    try:
        report, origin, selected = _resolve_validation_report(plan, explicit_report, explicit_context)
    except Exception:
        return _safe_validation_fallback()
    if report is None:
        return _safe_validation_fallback()
    try:
        records, raw_accepted, keys = _collect_accepted_exceptions(plan, explicit_accepted, explicit_validation_exceptions, explicit_report)
    except Exception:
        records = []
        raw_accepted = []
        keys = []
    try:
        gate = report.evaluate(selected, accepted=raw_accepted)
        gate_dict = gate.to_dict()
    except Exception:
        try:
            gate = report.evaluate(selected, accepted=())
            gate_dict = gate.to_dict()
        except Exception:
            gate_dict = {"context": selected, "allowed": True, "blocking": [], "visible_warnings": [], "waived": []}
    try:
        report_dict = report.to_dict()
    except Exception:
        report_dict = {"source": "", "context": selected, "total": 0, "counts": {"info": 0, "warning": 0, "error": 0, "blocker": 0}, "findings": []}
    try:
        gate_context = str(gate_dict.get("context", selected) or selected)
    except Exception:
        gate_context = selected
    try:
        allowed = bool(gate_dict.get("allowed", True))
    except Exception:
        allowed = True
    try:
        blocking = _copy_finding_dicts(gate_dict.get("blocking", []))
    except Exception:
        blocking = []
    try:
        visible = _copy_finding_dicts(gate_dict.get("visible_warnings", []))
    except Exception:
        visible = []
    try:
        waived = _copy_finding_dicts(gate_dict.get("waived", []))
    except Exception:
        waived = []
    ordered_gate = {
        "context": gate_context,
        "allowed": allowed,
        "blocking": blocking,
        "visible_warnings": visible,
        "waived": waived,
    }
    try:
        source_text = str(report_dict.get("source", "") or "")
    except Exception:
        source_text = ""
    try:
        total = int(report_dict.get("total", 0) or 0)
    except Exception:
        total = 0
    try:
        counts_raw = report_dict.get("counts", {}) or {}
        counts = {}
        for severity in ("info", "warning", "error", "blocker"):
            try:
                counts[severity] = int(counts_raw.get(severity, 0) or 0)
            except Exception:
                counts[severity] = 0
    except Exception:
        counts = {"info": 0, "warning": 0, "error": 0, "blocker": 0}
    try:
        findings_list = _copy_finding_dicts(report_dict.get("findings", []))
    except Exception:
        findings_list = []
    try:
        records_copy = _deepcopy_value(records)
        if not isinstance(records_copy, list):
            records_copy = []
    except Exception:
        records_copy = []
    try:
        keys_copy = list(keys or [])
    except Exception:
        keys_copy = []
    try:
        report_context_text = str(report_dict.get("context", selected) or selected)
    except Exception:
        report_context_text = selected
    return {
        "source": source_text,
        "context": selected,
        "total": total,
        "counts": counts,
        "findings": findings_list,
        "gate": ordered_gate,
        "accepted_exceptions": records_copy,
        "accepted_keys": keys_copy,
        "report_source": source_text,
        "report_context": report_context_text,
        "report_origin": origin,
    }


def _convert_to_plain_dict(value):
    """Convert mapping-like results to plain dicts without mutation."""
    try:
        if value is None:
            return None
        if isinstance(value, dict):
            return dict(value)
        converter = getattr(value, "to_dict", None)
        if callable(converter):
            try:
                data = converter()
                if isinstance(data, dict):
                    return dict(data)
            except Exception:
                pass
        return None
    except Exception:
        return None


def _ordered_mapping_with_status_first(data, default_status):
    """Return a stable mapping with status first and remaining keys sorted."""
    try:
        working = dict(data) if isinstance(data, dict) else {}
    except Exception:
        working = {}
    try:
        raw_status = working.get("status", None)
        if isinstance(raw_status, str) and raw_status.strip():
            status_text = raw_status.strip()
        else:
            status_text = default_status
    except Exception:
        status_text = default_status
    ordered = {"status": status_text}
    try:
        for key in sorted(working, key=lambda item: str(item)):
            if str(key) == "status":
                continue
            try:
                ordered[str(key)] = _deepcopy_value(working[key])
            except Exception:
                continue
    except Exception:
        pass
    return ordered


def _build_acceptance_section(plan, explicit_acceptance, explicit_acceptance_result):
    """Serialize acceptance as a stable mapping without inventing passes."""
    raw = None
    try:
        if explicit_acceptance is not None:
            raw = explicit_acceptance
        elif explicit_acceptance_result is not None:
            raw = explicit_acceptance_result
        else:
            try:
                candidate = getattr(plan, "acceptance_result", None)
                if candidate is not None:
                    raw = candidate
                else:
                    try:
                        candidate_two = getattr(plan, "engine_acceptance", None)
                    except Exception:
                        candidate_two = None
                    if candidate_two is not None:
                        raw = candidate_two
            except Exception:
                raw = None
    except Exception:
        raw = None
    if raw is None:
        return {"status": "not_run"}
    try:
        data = _convert_to_plain_dict(raw)
    except Exception:
        data = None
    if data is None:
        return {"status": "not_run"}
    try:
        if not data:
            return {"status": "not_run"}
        return _ordered_mapping_with_status_first(data, "unknown")
    except Exception:
        return {"status": "not_run"}


def _build_lock_compat_section(plan, explicit_lock):
    """Serialize lock compatibility without filesystem input."""
    raw = None
    try:
        if explicit_lock is not None:
            raw = explicit_lock
        else:
            for attr_name in ("lock_compat", "lock_compat_result", "foundation_lock_compat", "lock_compatibility"):
                try:
                    candidate = getattr(plan, attr_name, None)
                except Exception:
                    candidate = None
                if candidate is not None:
                    raw = candidate
                    break
    except Exception:
        raw = None
    if raw is None:
        return {"status": "not_run", "breaking": False, "differences": []}
    try:
        data = _convert_to_plain_dict(raw)
    except Exception:
        data = None
    if data is None:
        return {"status": "not_run", "breaking": False, "differences": []}
    try:
        if not data:
            return {"status": "not_run", "breaking": False, "differences": []}
    except Exception:
        pass
    try:
        raw_status = data.get("status", None)
        if isinstance(raw_status, str) and raw_status.strip():
            status_text = raw_status.strip()
        else:
            status_text = "unknown"
    except Exception:
        status_text = "unknown"
    try:
        raw_breaking = data.get("breaking", False)
        breaking = bool(raw_breaking) if not isinstance(raw_breaking, bool) else raw_breaking
    except Exception:
        breaking = False
    try:
        raw_diffs = data.get("differences", [])
        if isinstance(raw_diffs, (list, tuple)):
            diffs = []
            for entry in raw_diffs:
                try:
                    if isinstance(entry, dict):
                        diffs.append({str(key): _deepcopy_value(val) for key, val in entry.items()})
                    else:
                        diffs.append(_deepcopy_value(entry))
                except Exception:
                    continue
            try:
                diffs.sort(key=_stable_sort_key)
            except Exception:
                pass
        else:
            diffs = []
    except Exception:
        diffs = []
    ordered = {"status": status_text, "breaking": breaking, "differences": diffs}
    try:
        for key in sorted(data, key=lambda item: str(item)):
            if str(key) in ("status", "breaking", "differences"):
                continue
            try:
                ordered[str(key)] = _deepcopy_value(data[key])
            except Exception:
                continue
    except Exception:
        pass
    return ordered



def build_manifest_dict(plan, written_files: list, stage_results: list | None = None,
                        placeholders: list | None = None, provenance: list | None = None,
                        validation_report=None, acceptance=None, acceptance_result=None,
                        lock_compat=None, validation_context=None,
                        accepted_exceptions=None, validation_exceptions=None) -> dict:
    snapshot = getattr(plan, "snapshot", None)
    tool_version = _tool_version()
    created_at = _utc_now_iso()
    profile_name = getattr(plan, "profile_name", "legacy_full")
    lifecycle = getattr(plan, "lifecycle", "draft")
    repair_policy = getattr(plan, "repair_policy", "propose")
    layers = list(getattr(plan, "layers", []) or [])
    scope = dict(getattr(plan, "scope", {}) or {})
    mod_name = getattr(plan, "mod_name", "")
    game_target = getattr(plan, "game_target", None)
    game_profile = getattr(plan, "game_profile", None)
    try:
        snapshot_fingerprint = getattr(snapshot, "fingerprint", "") if snapshot is not None else ""
    except Exception:
        snapshot_fingerprint = ""
    if snapshot is not None:
        try:
            width = int(getattr(snapshot, "width", 0) or 0)
        except Exception:
            width = 0
        try:
            height = int(getattr(snapshot, "height", 0) or 0)
        except Exception:
            height = 0
        map_size = {"width": width, "height": height}
    else:
        map_size = {}
    legacy_target = None
    try:
        if game_target is not None and hasattr(game_target, "to_dict"):
            legacy_target = game_target.to_dict()
        elif isinstance(game_target, dict):
            legacy_target = dict(game_target)
        else:
            legacy_target = _target_to_dict(game_target)
    except Exception:
        try:
            legacy_target = _target_to_dict(game_target)
        except Exception:
            legacy_target = None
    game_profile_id = None
    try:
        if isinstance(game_profile, dict):
            game_profile_id = game_profile.get("profile_id")
        elif isinstance(game_profile, str):
            game_profile_id = game_profile
        elif game_profile is not None:
            game_profile_id = getattr(game_profile, "profile_id", None)
    except Exception:
        game_profile_id = None
    sources = {
        "arrays": _source_array_hashes(snapshot),
        "managers": _source_manager_hashes(snapshot),
        "auxiliary": _source_auxiliary_hashes(snapshot),
    }
    portable_target = _portable_target_identity(game_target, game_profile, snapshot)
    diagnostics_target = _target_diagnostics(game_target)
    portable_project = _portable_project(snapshot)
    game_profile_detail = _game_profile_detail(game_profile)
    counts = _stable_counts(plan, snapshot)
    portable_scope = _portable_scope(scope)
    try:
        identity_hash = _compute_identity_hash(
            profile_name, portable_target, portable_project,
            map_size, layers, portable_scope, sources, snapshot_fingerprint,
        )
    except Exception:
        identity_hash = "unhashable"
    try:
        proposed = [_repair_to_dict(entry) for entry in (getattr(plan, "proposed_repairs", []) or [])]
    except Exception:
        proposed = []
    try:
        applied = [_repair_to_dict(entry) for entry in (getattr(plan, "applied_repairs", []) or [])]
    except Exception:
        applied = []
    try:
        findings = [_finding_to_dict(entry) for entry in (getattr(plan, "findings", []) or [])]
    except Exception:
        findings = []
    try:
        blockers = list(getattr(plan, "blockers", []) or [])
    except Exception:
        blockers = []
    try:
        acceptance_tags = list(getattr(plan, "acceptance_tags", []) or [])
    except Exception:
        acceptance_tags = []
    try:
        snapshot_assets = getattr(snapshot, "assets", None) if snapshot is not None else None
    except Exception:
        snapshot_assets = None
    written_hashes = _written_hash_index(written_files)
    enriched_files = _enrich_written_files(written_files, stage_results)
    try:
        plan_resolutions = getattr(plan, "asset_resolutions", []) or []
    except Exception:
        plan_resolutions = []
    enriched_assets = _enrich_asset_resolutions(plan_resolutions, snapshot_assets, written_hashes)
    try:
        validation_section = _build_validation_section(plan, validation_report, validation_context, accepted_exceptions, validation_exceptions)
    except Exception:
        validation_section = _safe_validation_fallback()
    try:
        acceptance_section = _build_acceptance_section(plan, acceptance, acceptance_result)
    except Exception:
        acceptance_section = {"status": "not_run"}
    try:
        engine_acceptance_section = dict(acceptance_section)
    except Exception:
        engine_acceptance_section = {"status": "not_run"}
    try:
        lock_section = _build_lock_compat_section(plan, lock_compat)
    except Exception:
        lock_section = {"status": "not_run", "breaking": False, "differences": []}
    return {
        "manifest_schema": MANIFEST_SCHEMA,
        "manifest_version": MANIFEST_VERSION,
        "metadata": {
            "tool_version": tool_version,
            "created_at": created_at,
            "generator": MANIFEST_GENERATOR,
        },
        "tool_version": tool_version,
        "profile": profile_name,
        "lifecycle": lifecycle,
        "repair_policy": repair_policy,
        "layers": layers,
        "scope": dict(scope),
        "counts": counts,
        "mod_name": mod_name,
        "game_target": legacy_target,
        "target": {
            "identity": portable_target,
            "diagnostics": diagnostics_target,
        },
        "game_profile": game_profile_id,
        "game_profile_detail": game_profile_detail,
        "project": portable_project,
        "snapshot_fingerprint": snapshot_fingerprint,
        "map_size": map_size,
        "sources": sources,
        "identity": {
            "identity_hash": identity_hash,
            "algorithm": IDENTITY_HASH_ALGORITHM,
        },
        "proposed_repairs": proposed,
        "applied_repairs": applied,
        "asset_counts": _asset_counts(plan),
        "asset_resolutions": enriched_assets,
        "findings": findings,
        "blockers": blockers,
        "acceptance_tags": acceptance_tags,
        "placeholders": _sorted_strings(placeholders),
        "provenance": _sorted_strings(provenance),
        "stages": _sorted_stages(stage_results),
        "written_files": enriched_files,
        "validation": validation_section,
        "acceptance": acceptance_section,
        "engine_acceptance": engine_acceptance_section,
        "lock_compat": lock_section,
    }


def write_manifest(output_dir: str, plan, written_files: list, stage_results: list | None = None,
                   placeholders: list | None = None, provenance: list | None = None,
                   manifest_name: str = "foundation_manifest.json", validation_report=None,
                   acceptance=None, acceptance_result=None, lock_compat=None,
                   validation_context=None, accepted_exceptions=None, validation_exceptions=None) -> str:
    payload = build_manifest_dict(plan, written_files, stage_results, placeholders, provenance, validation_report=validation_report, acceptance=acceptance, acceptance_result=acceptance_result, lock_compat=lock_compat, validation_context=validation_context, accepted_exceptions=accepted_exceptions, validation_exceptions=validation_exceptions)
    path = os.path.join(output_dir, manifest_name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    return path


def canonical_manifest_dict(manifest: dict) -> dict:
    if not isinstance(manifest, dict):
        return {}
    try:
        data = copy.deepcopy(dict(manifest))
    except Exception:
        data = dict(manifest)
    for key in CANONICAL_EXCLUDE_TOP_KEYS:
        data.pop(key, None)
    game_target = data.get("game_target")
    if isinstance(game_target, dict):
        try:
            data["game_target"] = {key: game_target.get(key) for key in PORTABLE_TARGET_KEYS}
        except Exception:
            pass
    target = data.get("target")
    if isinstance(target, dict):
        identity = target.get("identity")
        if isinstance(identity, dict):
            data["target"] = {"identity": dict(identity)}
        else:
            data["target"] = {"identity": {}}
    scope = data.get("scope")
    if isinstance(scope, dict):
        try:
            data["scope"] = {key: scope[key] for key in scope if str(key) not in SCOPE_PATH_KEYS}
        except Exception:
            pass
    return data


def canonical_manifest_json(manifest: dict) -> str:
    return json.dumps(canonical_manifest_dict(manifest), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def manifest_identity_hash(manifest: dict) -> str:
    if isinstance(manifest, dict):
        identity = manifest.get("identity") or {}
        if isinstance(identity, dict) and identity.get("identity_hash"):
            return str(identity.get("identity_hash"))
    return ""


def write_report(output_dir: str, plan, written_files: list, manifest_path: str,
                 report_name: str = "foundation_report.md") -> str:
    counts = _asset_counts(plan)
    lines = [
        "# Export report: %s" % getattr(plan, "mod_name", ""),
        "",
        "Profile: %s | Lifecycle: %s | Repair policy: %s" % (
            getattr(plan, "profile_name", ""), getattr(plan, "lifecycle", ""),
            getattr(plan, "repair_policy", "")),
        "Created: %s | Manifest: %s" % (_utc_now_iso(), os.path.basename(manifest_path)),
        "",
        "## Repairs",
        "",
    ]
    for repair in getattr(plan, "proposed_repairs", []) or []:
        applied = "applied" if repair in (getattr(plan, "applied_repairs", []) or []) else "proposed"
        lines.append("- [%s/%s] %s (%s): %s" % (
            repair.safety, applied, repair.code, repair.layer, repair.summary))
        if repair.mapping:
            lines.append("  mapping entries: %d" % len(repair.mapping))
        if repair.rerun_validations:
            lines.append("  rerun: %s" % ", ".join(repair.rerun_validations))
    lines.extend(["", "## Assets", ""])
    for key in ("generated", "preserved", "inherited", "omitted", "unsupported"):
        lines.append("- %s: %d" % (key, counts.get(key, 0)))
    lines.extend(["", "## Files (%d)" % len(written_files or []), ""])
    for written in sorted(written_files or [], key=lambda w: w.rel_path):
        lines.append("- %s (%d bytes)" % (written.rel_path, written.size))
    if getattr(plan, "blockers", None):
        lines.extend(["", "## Blockers", ""])
        for blocker in plan.blockers:
            lines.append("- %s" % blocker)
    path = os.path.join(output_dir, report_name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def write_lock_file(output_dir: str, plan, lock_name: str = "foundation.lock.json") -> str:
    snapshot = getattr(plan, "snapshot", None)
    try:
        manifest = build_manifest_dict(plan, [])
    except Exception:
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}
    try:
        metadata_tool = (manifest.get("metadata") or {}).get("tool_version") or _tool_version()
    except Exception:
        metadata_tool = _tool_version()
    try:
        manifest_identity = manifest.get("identity") or {}
        if not isinstance(manifest_identity, dict):
            manifest_identity = {}
        identity_hash = manifest_identity.get("identity_hash", "")
        identity_algorithm = manifest_identity.get("algorithm", IDENTITY_HASH_ALGORITHM)
        if not isinstance(identity_hash, str):
            identity_hash = ""
        if not isinstance(identity_algorithm, str) or not identity_algorithm:
            identity_algorithm = IDENTITY_HASH_ALGORITHM
    except Exception:
        identity_hash = ""
        identity_algorithm = IDENTITY_HASH_ALGORITHM
    try:
        profile_name = manifest.get("profile", getattr(plan, "profile_name", ""))
    except Exception:
        try:
            profile_name = getattr(plan, "profile_name", "")
        except Exception:
            profile_name = ""
    try:
        lifecycle_name = manifest.get("lifecycle", getattr(plan, "lifecycle", "draft"))
    except Exception:
        try:
            lifecycle_name = getattr(plan, "lifecycle", "draft")
        except Exception:
            lifecycle_name = "draft"
    try:
        project = manifest.get("project", None)
        if not isinstance(project, dict):
            project = _portable_project(snapshot)
    except Exception:
        try:
            project = _portable_project(snapshot)
        except Exception:
            project = {"schema_version": None, "profile_id": None, "generator_version": None}
    try:
        game_profile_id = manifest.get("game_profile", None)
        if game_profile_id is None:
            game_profile = getattr(plan, "game_profile", None)
            if isinstance(game_profile, dict):
                game_profile_id = game_profile.get("profile_id")
            elif isinstance(game_profile, str):
                game_profile_id = game_profile
            elif game_profile is not None:
                try:
                    game_profile_id = getattr(game_profile, "profile_id", None)
                except Exception:
                    game_profile_id = None
    except Exception:
        game_profile_id = None
    try:
        detail = manifest.get("game_profile_detail", None)
        if detail is None:
            detail = _game_profile_detail(getattr(plan, "game_profile", None))
    except Exception:
        detail = None
    try:
        target_node = manifest.get("target", None)
        target_identity = None
        if isinstance(target_node, dict):
            inner = target_node.get("identity")
            if isinstance(inner, dict):
                target_identity = dict(inner)
        if target_identity is None:
            target_identity = _portable_target_identity(getattr(plan, "game_target", None), getattr(plan, "game_profile", None), snapshot)
    except Exception:
        try:
            target_identity = _portable_target_identity(getattr(plan, "game_target", None), getattr(plan, "game_profile", None), snapshot)
        except Exception:
            target_identity = {key: None for key in PORTABLE_TARGET_KEYS}
            target_identity["game_profile"] = None
    if not isinstance(target_identity, dict):
        try:
            target_identity = _portable_target_identity(getattr(plan, "game_target", None), getattr(plan, "game_profile", None), snapshot)
        except Exception:
            target_identity = {key: None for key in PORTABLE_TARGET_KEYS}
            target_identity["game_profile"] = None
    try:
        fingerprint = manifest.get("snapshot_fingerprint", "")
        if not isinstance(fingerprint, str):
            fingerprint = getattr(snapshot, "fingerprint", "") if snapshot is not None else ""
    except Exception:
        try:
            fingerprint = getattr(snapshot, "fingerprint", "") if snapshot is not None else ""
        except Exception:
            fingerprint = ""
    try:
        size = manifest.get("map_size", None)
        if not isinstance(size, dict):
            if snapshot is not None:
                try:
                    size = {"width": getattr(snapshot, "width", 0), "height": getattr(snapshot, "height", 0)}
                except Exception:
                    size = {}
            else:
                size = {}
    except Exception:
        size = {}
    try:
        stable = manifest.get("counts", None)
        if not isinstance(stable, dict):
            stable = _stable_counts(plan, snapshot)
    except Exception:
        try:
            stable = _stable_counts(plan, snapshot)
        except Exception:
            stable = {"province_ids": 0, "province_max": 0, "map_pixels": 0, "managers": {}}
    payload = {
        "lock_schema": LOCK_SCHEMA,
        "lock_version": LOCK_VERSION,
        "manifest_schema": MANIFEST_SCHEMA,
        "manifest_version": MANIFEST_VERSION,
        "metadata": {
            "tool_version": metadata_tool,
            "created_at": _utc_now_iso(),
            "generator": MANIFEST_GENERATOR,
        },
        "tool_version": metadata_tool,
        "identity": {
            "identity_hash": identity_hash,
            "algorithm": identity_algorithm,
        },
        "profile": profile_name,
        "lifecycle": lifecycle_name,
        "project": _deepcopy_value(project),
        "game_profile": game_profile_id,
        "game_profile_detail": _deepcopy_value(detail),
        "target": {
            "identity": _deepcopy_value(target_identity),
        },
        "snapshot_fingerprint": fingerprint,
        "map_size": _deepcopy_value(size),
        "counts": _deepcopy_value(stable),
    }
    path = os.path.join(output_dir, lock_name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    return path


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _comparison_target_identity(data: dict) -> dict:
    try:
        node = data.get("target") if isinstance(data, dict) else None
    except Exception:
        node = None
    if isinstance(node, dict):
        try:
            inner = node.get("identity")
        except Exception:
            inner = None
        if isinstance(inner, dict):
            return dict(inner)
        portable = {}
        found = False
        for key in PORTABLE_TARGET_KEYS + ("game_profile",):
            try:
                if key in node:
                    portable[key] = node.get(key)
                    found = True
            except Exception:
                continue
        if found:
            return portable
    return {}


def compare_with_lock(manifest: dict | str, lock: dict | str) -> dict:
    try:
        if isinstance(manifest, str):
            manifest_data = _load_json(manifest)
        elif isinstance(manifest, dict):
            manifest_data = dict(manifest)
        else:
            manifest_data = {}
    except Exception:
        manifest_data = {}
    try:
        if isinstance(lock, str):
            lock_data = _load_json(lock)
        elif isinstance(lock, dict):
            lock_data = dict(lock)
        else:
            lock_data = {}
    except Exception:
        lock_data = {}
    if not isinstance(manifest_data, dict):
        manifest_data = {}
    if not isinstance(lock_data, dict):
        lock_data = {}
    differences = []
    def _record(field, old, new, breaking):
        try:
            old_copy = _deepcopy_value(old)
        except Exception:
            old_copy = old
        try:
            new_copy = _deepcopy_value(new)
        except Exception:
            new_copy = new
        differences.append({"field": field, "lock": old_copy, "manifest": new_copy, "breaking": bool(breaking)})
    for key in ("snapshot_fingerprint", "profile", "game_profile"):
        try:
            old = lock_data.get(key)
        except Exception:
            old = None
        try:
            new = manifest_data.get(key)
        except Exception:
            new = None
        if old != new:
            _record(key, old, new, key == "snapshot_fingerprint")
    try:
        old_size = lock_data.get("map_size") or {}
    except Exception:
        old_size = {}
    try:
        new_size = manifest_data.get("map_size") or {}
    except Exception:
        new_size = {}
    if old_size != new_size:
        _record("map_size", old_size, new_size, True)
    if "lifecycle" in lock_data:
        try:
            old_life = lock_data.get("lifecycle")
        except Exception:
            old_life = None
        try:
            new_life = manifest_data.get("lifecycle")
        except Exception:
            new_life = None
        if old_life != new_life:
            _record("lifecycle", old_life, new_life, False)
    if "identity" in lock_data:
        try:
            lock_ident = lock_data.get("identity") or {}
            if not isinstance(lock_ident, dict):
                lock_ident = {}
        except Exception:
            lock_ident = {}
        try:
            manifest_ident = manifest_data.get("identity") or {}
            if not isinstance(manifest_ident, dict):
                manifest_ident = {}
        except Exception:
            manifest_ident = {}
        try:
            old_hash = lock_ident.get("identity_hash")
        except Exception:
            old_hash = None
        try:
            new_hash = manifest_ident.get("identity_hash")
        except Exception:
            new_hash = None
        if old_hash != new_hash:
            _record("identity.identity_hash", old_hash, new_hash, True)
        try:
            old_algo = lock_ident.get("algorithm")
        except Exception:
            old_algo = None
        try:
            new_algo = manifest_ident.get("algorithm")
        except Exception:
            new_algo = None
        if old_algo != new_algo:
            _record("identity.algorithm", old_algo, new_algo, True)
    if "target" in lock_data:
        lock_ti = _comparison_target_identity(lock_data)
        manifest_ti = _comparison_target_identity(manifest_data)
        for key in sorted(set(PORTABLE_TARGET_KEYS) | {"game_profile"}):
            try:
                old = lock_ti.get(key)
            except Exception:
                old = None
            try:
                new = manifest_ti.get(key)
            except Exception:
                new = None
            if old != new:
                _record("target.identity." + key, old, new, True)
    if "project" in lock_data:
        try:
            lock_proj = lock_data.get("project") or {}
            if not isinstance(lock_proj, dict):
                lock_proj = {}
        except Exception:
            lock_proj = {}
        try:
            manifest_proj = manifest_data.get("project") or {}
            if not isinstance(manifest_proj, dict):
                manifest_proj = {}
        except Exception:
            manifest_proj = {}
        for key in sorted(("generator_version", "profile_id", "schema_version")):
            try:
                old = lock_proj.get(key)
            except Exception:
                old = None
            try:
                new = manifest_proj.get(key)
            except Exception:
                new = None
            if old != new:
                _record("project." + key, old, new, True)
    if "counts" in lock_data:
        try:
            lock_counts = lock_data.get("counts") or {}
            if not isinstance(lock_counts, dict):
                lock_counts = {}
        except Exception:
            lock_counts = {}
        try:
            manifest_counts = manifest_data.get("counts") or {}
            if not isinstance(manifest_counts, dict):
                manifest_counts = {}
        except Exception:
            manifest_counts = {}
        for key in sorted(("map_pixels", "province_ids", "province_max")):
            try:
                old = lock_counts.get(key)
            except Exception:
                old = None
            try:
                new = manifest_counts.get(key)
            except Exception:
                new = None
            if old != new:
                _record("counts." + key, old, new, True)
        try:
            lock_mgr = lock_counts.get("managers") or {}
            if not isinstance(lock_mgr, dict):
                lock_mgr = {}
        except Exception:
            lock_mgr = {}
        try:
            manifest_mgr = manifest_counts.get("managers") or {}
            if not isinstance(manifest_mgr, dict):
                manifest_mgr = {}
        except Exception:
            manifest_mgr = {}
        for key in sorted(MANAGER_KEYS):
            try:
                old = lock_mgr.get(key)
            except Exception:
                old = None
            try:
                new = manifest_mgr.get(key)
            except Exception:
                new = None
            if old != new:
                _record("counts.managers." + key, old, new, True)
    try:
        differences.sort(key=lambda item: str(item.get("field", "")))
    except Exception:
        pass
    try:
        breaking = any(bool(item.get("breaking")) for item in differences)
    except Exception:
        breaking = False
    try:
        lock_fp = lock_data.get("snapshot_fingerprint")
    except Exception:
        lock_fp = None
    try:
        manifest_fp = manifest_data.get("snapshot_fingerprint")
    except Exception:
        manifest_fp = None
    try:
        lock_node = lock_data.get("identity")
        lock_ident_hash = lock_node.get("identity_hash") if isinstance(lock_node, dict) else None
    except Exception:
        lock_ident_hash = None
    try:
        manifest_node = manifest_data.get("identity")
        manifest_ident_hash = manifest_node.get("identity_hash") if isinstance(manifest_node, dict) else None
    except Exception:
        manifest_ident_hash = None
    if breaking:
        status = "breaking"
    elif differences:
        status = "mismatch"
    else:
        status = "compatible"
    return {
        "breaking": breaking,
        "differences": differences,
        "lock_fingerprint": lock_fp,
        "manifest_fingerprint": manifest_fp,
        "lock_identity": lock_ident_hash,
        "manifest_identity": manifest_ident_hash,
        "status": status,
    }
