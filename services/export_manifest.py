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



def build_manifest_dict(plan, written_files: list, stage_results: list | None = None,
                        placeholders: list | None = None, provenance: list | None = None) -> dict:
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
    }


def write_manifest(output_dir: str, plan, written_files: list, stage_results: list | None = None,
                   placeholders: list | None = None, provenance: list | None = None,
                   manifest_name: str = "foundation_manifest.json") -> str:
    payload = build_manifest_dict(plan, written_files, stage_results, placeholders, provenance)
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
    payload = {
        "tool_version": _tool_version(),
        "created_at": _utc_now_iso(),
        "profile": getattr(plan, "profile_name", ""),
        "snapshot_fingerprint": getattr(snapshot, "fingerprint", "") if snapshot is not None else "",
        "map_size": {"width": getattr(snapshot, "width", 0), "height": getattr(snapshot, "height", 0)}
        if snapshot is not None else {},
        "game_profile": getattr(getattr(plan, "game_profile", None), "profile_id", None),
    }
    path = os.path.join(output_dir, lock_name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def compare_with_lock(manifest: dict | str, lock: dict | str) -> dict:
    manifest_data = _load_json(manifest) if isinstance(manifest, str) else dict(manifest or {})
    lock_data = _load_json(lock) if isinstance(lock, str) else dict(lock or {})
    differences = []
    for key in ("snapshot_fingerprint", "profile", "game_profile"):
        old, new = lock_data.get(key), manifest_data.get(key)
        if old != new:
            differences.append({"field": key, "lock": old, "manifest": new,
                                "breaking": key in ("snapshot_fingerprint",)})
    old_size = lock_data.get("map_size") or {}
    new_size = manifest_data.get("map_size") or {}
    if old_size != new_size:
        differences.append({"field": "map_size", "lock": old_size, "manifest": new_size, "breaking": True})
    breaking = any(item.get("breaking") for item in differences)
    return {"breaking": breaking, "differences": differences,
            "lock_fingerprint": lock_data.get("snapshot_fingerprint"),
            "manifest_fingerprint": manifest_data.get("snapshot_fingerprint")}
