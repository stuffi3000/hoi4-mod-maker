"""M6.7 optional structural text preservation (map/colors/airports/rocket/cities).

Preserve-or-omit policy, never empty-file generation by default:

- clean imported bytes (present in assets and not dirty) are written back
  byte-for-byte when the profile allows the path;
- otherwise the file is omitted and an explicit omitted/unsupported
  AssetResolution plus a planner finding already describe the drop;
- ``map/cities.txt`` is the only structural text with a vanilla generator:
  when no clean bytes exist the vanilla city groups are generated so city
  visuals keep working; all other structural texts are omitted when absent.

Both rocket spellings (``map/rocketsites.txt`` and ``map/rocket_sites.txt``)
are handled independently under their own rel paths. ``map/colors.txt`` is
deprecated by default and is only preserved when the active profile does not
list it as deprecated; otherwise it stays omitted.
"""
from __future__ import annotations
import os
STRUCTURAL_TEXT_PATHS = (
    "map/colors.txt",
    "map/airports.txt",
    "map/rocketsites.txt",
    "map/rocket_sites.txt",
    "map/cities.txt",
)
def _is_deprecated(rel_path, game_profile=None):
    try:
        if game_profile is not None:
            dep = getattr(game_profile, "deprecated_files", None)
            if dep is None and isinstance(game_profile, dict):
                dep = game_profile.get("deprecated_files")
            if dep:
                return str(rel_path) in set(dep)
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        from services.export_manifest import DEPRECATED_PATHS_FALLBACK as _fallback
        return str(rel_path) in set(_fallback or ())
    except (ImportError, AttributeError, TypeError, ValueError):
        return str(rel_path) == "map/colors.txt"
def _clean_bytes(rel_path, assets, dirty_assets):
    try:
        if assets is None:
            return None
        if rel_path not in assets:
            return None
        if dirty_assets is not None and rel_path in set(dirty_assets or ()):
            return None
        raw = assets.get(rel_path)
        if isinstance(raw, (bytes, bytearray, memoryview)):
            return bytes(raw)
        return None
    except (AttributeError, TypeError, ValueError):
        return None
def write_structural_text_assets(output_dir, assets=None, dirty_assets=None, game_profile=None, profile_name=None):
    actions = []
    if assets is None:
        assets = {}
    if dirty_assets is None:
        dirty_assets = set()
    else:
        try:
            dirty_assets = set(dirty_assets)
        except (TypeError, ValueError):
            dirty_assets = set()
    for rel_path in STRUCTURAL_TEXT_PATHS:
        if rel_path == "map/cities.txt":
            continue
        raw = _clean_bytes(rel_path, assets, dirty_assets)
        if raw is not None and not _is_deprecated(rel_path, game_profile):
            dst = os.path.join(str(output_dir), rel_path.replace("/", os.sep))
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as handle:
                    handle.write(raw)
                actions.append((rel_path, "preserved"))
            except OSError:
                actions.append((rel_path, "omitted"))
        else:
            if raw is not None and _is_deprecated(rel_path, game_profile):
                actions.append((rel_path, "omitted"))
            else:
                actions.append((rel_path, "omitted"))
    return actions
def write_cities_txt_preserve_or_generate(output_dir, assets=None, dirty_assets=None, game_profile=None, profile_name=None):
    raw = _clean_bytes("map/cities.txt", assets, dirty_assets)
    if raw is not None:
        dst = os.path.join(str(output_dir), "map", "cities.txt")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as handle:
            handle.write(raw)
        return "preserved"
    from export.writers.map.cities_bmp import write_cities_txt as _write_default
    _write_default(str(output_dir))
    return "generated"
