"""Import MOD Map — Reads map layers from the HOI4 mod/vanilla directory.

Read from the map/ subdirectory:
- provinces.bmp (24-bit) → province_map + color→ID mapping
- definition.csv → tile_map (land/sea/lake) + provincial_terrain
- terrain.bmp (8-bit indexed) → terrain_map
- heightmap.bmp (8-bit grayscale) → height_map
- rivers.bmp (8-bit indexed) → river_map"""

from __future__ import annotations

import csv
import os
import re
from typing import Any

import numpy as np
from PIL import Image

from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE

# definition.csv type name → internal constant
_TYPE_MAP = {
    "land": TILE_LAND,
    "sea": TILE_SEA,
    "lake": TILE_LAKE,
}


def validate_mod_directory(mod_dir: str) -> list[str]:
    """Check the directory structure and return a list of missing files.

    If the MOD does not have map/provinces.bmp, try to fill it from the vanilla directory.
    Many MODs do not contain map files (only history/common is changed), in this case use vanilla maps."""
    from data.constants import DEFAULT_HOI4_PATH
    provinces_path = os.path.join(mod_dir, "map", "provinces.bmp")
    if not os.path.isfile(provinces_path):
        # Try vanilla fallback
        vanilla_provinces = os.path.join(DEFAULT_HOI4_PATH, "map", "provinces.bmp")
        if os.path.isfile(vanilla_provinces):
            return [f"map/provinces.bmp is not included in this mod (it uses the vanilla map).\nTo import the map, select the vanilla directory directly:\n{DEFAULT_HOI4_PATH}"]
        return ["map/provinces.bmp was not found in either the mod or the vanilla game"]
    return []


def _parse_definition_csv(csv_path: str) -> dict[tuple[int, int, int], dict[str, Any]]:
    """Parse definition.csv and return {(R,G,B): {id, type, terrain}} mapping.

    Format: ID;R;G;B;type;coastal;terrain;continent"""
    color_info: dict[tuple[int, int, int], dict[str, Any]] = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")
        for row in reader:
            if len(row) < 5:
                continue
            try:
                pid = int(row[0])
                r, g, b = int(row[1]), int(row[2]), int(row[3])
                ptype = row[4].strip().lower()
                terrain = row[6].strip() if len(row) > 6 else ""
            except (ValueError, IndexError):
                continue
            if pid <= 0:
                continue
            color_info[(r, g, b)] = {
                "id": pid,
                "type": ptype,
                "terrain": terrain,
            }
    return color_info


def _read_provinces_bmp(bmp_path: str) -> tuple[np.ndarray, dict[tuple[int, int, int], int]]:
    """Read provinces.bmp and return (rgb_array[H,W,3], color→auto_id mapping).

    PIL automatically handles the bottom-up line ordering of BMPs."""
    img = Image.open(bmp_path).convert("RGB")
    rgb = np.array(img, dtype=np.uint8)
    # Scan for unique colors, skipping (0,0,0)
    h, w = rgb.shape[:2]
    flat = rgb.reshape(-1, 3)
    # Use structured array to make unique
    flat_view = flat.view(np.dtype([("r", np.uint8), ("g", np.uint8), ("b", np.uint8)]))
    unique_colors = np.unique(flat_view)

    auto_map: dict[tuple[int, int, int], int] = {}
    next_id = 1
    for c in unique_colors:
        r, g, b = int(c["r"]), int(c["g"]), int(c["b"])
        if (r, g, b) == (0, 0, 0):
            continue
        auto_map[(r, g, b)] = next_id
        next_id += 1

    return rgb, auto_map


def _build_province_map(
    rgb: np.ndarray,
    color_to_id: dict[tuple[int, int, int], int],
) -> np.ndarray:
    """Build province_map (int32) from RGB array and color map.

    Implement O(N) mapping using a 24-bit direct lookup table (16M entries = 64MB),
    Replaces the previous np.unique + inverse (O(N log N), 20 seconds for 11.5 million pixels)."""
    h, w = rgb.shape[:2]

    # RGB → 24-bit int
    flat = rgb.reshape(-1, 3).astype(np.int32)
    keys = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]

    # Direct lookup table: 24-bit key → province ID
    lut = np.zeros(1 << 24, dtype=np.int32)
    for (r, g, b), pid in color_to_id.items():
        lut[(r << 16) | (g << 8) | b] = pid

    province_map = lut[keys].reshape(h, w)
    return province_map


def _build_tile_map(
    province_map: np.ndarray,
    color_to_id: dict[tuple[int, int, int], int],
    definition_info: dict[tuple[int, int, int], dict[str, Any]] | None,
) -> tuple[np.ndarray, dict[int, str]]:
    """Build tile_map (land/sea/lake) and provincial_terrain dictionaries.

    Use LUT to directly map province_id → tile_type, O(pixels) without scanning province by province."""
    h, w = province_map.shape
    provincial_terrain: dict[int, str] = {}

    if definition_info is None:
        return np.full((h, w), TILE_LAND, dtype=np.uint8), provincial_terrain

    # Build province_id → tile_type lookup table
    max_pid = int(province_map.max())
    type_lut = np.full(max_pid + 1, TILE_LAND, dtype=np.uint8)
    for color, info in definition_info.items():
        pid = info["id"]
        if pid <= 0 or pid > max_pid:
            continue
        ptype = _TYPE_MAP.get(info["type"], TILE_LAND)
        type_lut[pid] = ptype
        if info.get("terrain"):
            provincial_terrain[pid] = info["terrain"]

    # Direct LUT mapping — O(pixels), no province-by-province
    tile_map = type_lut[province_map]
    return tile_map, provincial_terrain


def _read_indexed_bmp(bmp_path: str) -> np.ndarray:
    """Reads an 8-bit indexed BMP, returning an array of palette indices (uint8)."""
    img = Image.open(bmp_path)
    if img.mode == "P":
        # Get palette index directly
        data = np.array(img, dtype=np.uint8)
    elif img.mode == "L":
        # Use grayscale images directly
        data = np.array(img, dtype=np.uint8)
    else:
        # Convert to grayscale as fallback
        data = np.array(img.convert("L"), dtype=np.uint8)
    return data


def _extract_block_value(text: str, key: str) -> str:
    """Extract key={...} or key=value from Clausewitz script."""
    import re
    # key = { ... }
    m = re.search(rf'{key}\s*=\s*\{{([^}}]*)\}}', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # key = value
    m = re.search(rf'{key}\s*=\s*(\S+)', text)
    if m:
        return m.group(1).strip().strip('"')
    return ""


def _parse_state_file(path: str) -> dict | None:
    """Parse history/states/*.txt and return {id, name, provinces, owner, manpower, category}."""
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        text = f.read()

    sid_str = _extract_block_value(text, "id")
    if not sid_str:
        return None
    try:
        sid = int(sid_str)
    except ValueError:
        return None

    name = _extract_block_value(text, "name") or f"STATE_{sid}"
    owner = _extract_block_value(text, "owner") or ""
    manpower_str = _extract_block_value(text, "manpower")
    manpower = int(manpower_str) if manpower_str.isdigit() else 100000
    category = _extract_block_value(text, "state_category") or "town"

    # Province list
    provinces_str = _extract_block_value(text, "provinces")
    province_ids = []
    for token in provinces_str.split():
        try:
            province_ids.append(int(token))
        except ValueError:
            pass

    if not province_ids:
        return None

    # Parse victory_points = { pid value } (possibly multiple)
    import re
    victory_points: dict[int, int] = {}
    for m in re.finditer(r'victory_points\s*=\s*\{\s*(\d+)\s+(\d+)\s*\}', text):
        vp_pid, vp_val = int(m.group(1)), int(m.group(2))
        if vp_val > 0:
            victory_points[vp_pid] = vp_val

    return {
        "id": sid,
        "name": name,
        "provinces": province_ids,
        "owner": owner,
        "manpower": manpower,
        "category": category,
        "victory_points": victory_points,
    }


def _parse_strategic_region_file(path: str) -> dict | None:
    """Parse map/strategicregions/*.txt and return {id, name, provinces, weather_preset, naval_terrain}."""
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        text = f.read()

    rid_str = _extract_block_value(text, "id")
    if not rid_str:
        return None
    try:
        rid = int(rid_str)
    except ValueError:
        return None

    name = _extract_block_value(text, "name") or f"STRATEGICREGION_{rid}"
    provinces_str = _extract_block_value(text, "provinces")
    province_ids = []
    for token in provinces_str.split():
        try:
            province_ids.append(int(token))
        except ValueError:
            pass

    # Read naval_terrain (vanilla legal values: water_deep_ocean/water_shallow_sea/water_fjords)
    naval_terrain = ""
    import re
    nt_match = re.search(r'naval_terrain\s*=\s*(\S+)', text)
    if nt_match:
        raw = nt_match.group(1).strip().strip('"')
        if raw in ("water_deep_ocean", "water_shallow_sea", "water_fjords"):
            naval_terrain = raw
        # Compatible with short names left over from old MODs
        elif raw in ("deep_ocean", "ocean"):
            naval_terrain = "water_deep_ocean"
        elif raw == "shallow_sea":
            naval_terrain = "water_shallow_sea"
        elif raw == "fjords":
            naval_terrain = "water_fjords"

    # Infer weather preset from temperature of weather
    weather_preset = _guess_weather_preset(text)

    return {
        "id": rid,
        "name": name,
        "provinces": province_ids,
        "weather_preset": weather_preset,
        "naval_terrain": naval_terrain,
    }


def _guess_weather_preset(text: str) -> str:
    """Infer the closest weather preset from the weather block's temperature value."""
    import re
    temps = re.findall(r'temperature\s*=\s*\{\s*([-\d.]+)\s+([-\d.]+)\s*\}', text)
    if not temps:
        return "temperate"

    # Take the average high temperature of all months
    avg_high = sum(float(t[1]) for t in temps) / len(temps)
    avg_low = sum(float(t[0]) for t in temps) / len(temps)

    # Check out sandstorms (desert features)
    sandstorms = re.findall(r'sandstorm\s*=\s*([\d.]+)', text)
    has_sandstorm = any(float(s) > 0.1 for s in sandstorms)

    if has_sandstorm:
        return "desert"
    if avg_high >= 28 and avg_low >= 15:
        return "tropical"
    if avg_high <= 5:
        return "polar"
    if avg_high <= 15:
        return "cold"
    return "temperate"


def import_mod_map(mod_dir: str) -> dict[str, Any]:
    """Import map layers from the HOI4 mod/vanilla directory.

    Parameters:
        mod_dir: root directory containing the map/ subdirectory

    Return:
        {
            "width": int,
            "height": int,
            "tile_map": np.ndarray,
            "province_map": np.ndarray,
            "terrain_map": np.ndarray,
            "height_map": np.ndarray,
            "river_map": np.ndarray,
            "province_count": int,
            "provincial_terrain": dict[int, str],
            "warnings": list[str],
        }

    Exception:
        FileNotFoundError: provinces.bmp does not exist
        ValueError: BMP format error"""
    mod_dir = os.path.normpath(mod_dir)
    map_dir = os.path.join(mod_dir, "map")
    provinces_path = os.path.join(map_dir, "provinces.bmp")

    # Case-insensitive lookup (user file might be Provinces.bmp/PROVINCES.BMP)
    if not os.path.isfile(provinces_path) and os.path.isdir(map_dir):
        for f in os.listdir(map_dir):
            if f.lower() == "provinces.bmp":
                provinces_path = os.path.join(map_dir, f)
                break

    if not os.path.isfile(provinces_path):
        raise FileNotFoundError(f"provinces.bmp does not exist: {provinces_path}")

    warnings: list[str] = []

    # 1. Read provinces.bmp (only read RGB, do not scan unique colors - that O(N log N) is too slow)
    img = Image.open(provinces_path).convert("RGB")
    rgb = np.array(img, dtype=np.uint8)
    h, w = rgb.shape[:2]

    # 2. Read definition.csv (optional) - if there is a csv, use its color→ID directly, skipping pixel scanning
    definition_path = os.path.join(map_dir, "definition.csv")
    definition_info: dict[tuple[int, int, int], dict[str, Any]] | None = None
    if os.path.isfile(definition_path):
        definition_info = _parse_definition_csv(definition_path)
        color_to_id: dict[tuple[int, int, int], int] = {
            c: info["id"] for c, info in definition_info.items()
        }
    else:
        # no definition.csv → fallback scanning unique colors auto-assign ID (slow path)
        _, color_to_id = _read_provinces_bmp(provinces_path)
        warnings.append("definition.csv was not found; all province types were set to land")

    # 3. Build province_map
    province_map = _build_province_map(rgb, color_to_id)
    province_count = int(province_map.max())

    # 4. Build tile_map + provincial_terrain
    tile_map, provincial_terrain = _build_tile_map(
        province_map, color_to_id, definition_info
    )

    # 5. Read terrain.bmp (optional)
    terrain_path = os.path.join(map_dir, "terrain.bmp")
    if os.path.isfile(terrain_path):
        terrain_map = _read_indexed_bmp(terrain_path)
        if terrain_map.shape != (h, w):
            warnings.append(
                f"terrain.bmp size {terrain_map.shape[1]}x{terrain_map.shape[0]} did not match provinces.bmp {w}x{h} and was resized"
            )
            img = Image.fromarray(terrain_map)
            img = img.resize((w, h), Image.Resampling.NEAREST)
            terrain_map = np.array(img, dtype=np.uint8)
    else:
        terrain_map = np.zeros((h, w), dtype=np.uint8)
        warnings.append("terrain.bmp was not found; the terrain layer was left empty")

    # 6. Read heightmap.bmp (optional)
    heightmap_path = os.path.join(map_dir, "heightmap.bmp")
    if os.path.isfile(heightmap_path):
        height_map = _read_indexed_bmp(heightmap_path)
        if height_map.shape != (h, w):
            warnings.append(
                f"heightmap.bmp size {height_map.shape[1]}x{height_map.shape[0]} did not match provinces.bmp {w}x{h} and was resized"
            )
            img = Image.fromarray(height_map)
            img = img.resize((w, h), Image.Resampling.NEAREST)
            height_map = np.array(img, dtype=np.uint8)
    else:
        height_map = np.full((h, w), 40, dtype=np.uint8)
        warnings.append("heightmap.bmp was not found; the height layer was set to its default value")

    # 7. Read rivers.bmp (optional)
    rivers_path = os.path.join(map_dir, "rivers.bmp")
    if os.path.isfile(rivers_path):
        river_map = _read_indexed_bmp(rivers_path)
        if river_map.shape != (h, w):
            warnings.append(
                f"rivers.bmp size {river_map.shape[1]}x{river_map.shape[0]} did not match provinces.bmp {w}x{h} and was resized"
            )
            img = Image.fromarray(river_map)
            img = img.resize((w, h), Image.Resampling.NEAREST)
            river_map = np.array(img, dtype=np.uint8)
    else:
        river_map = np.full((h, w), 255, dtype=np.uint8)
        warnings.append("rivers.bmp was not found; the river layer was left empty")

    # 8. Read states (optional)
    states_dir = os.path.join(mod_dir, "history", "states")
    states_data: list[dict] = []
    if os.path.isdir(states_dir):
        for fn in sorted(os.listdir(states_dir)):
            if not fn.endswith(".txt"):
                continue
            try:
                sd = _parse_state_file(os.path.join(states_dir, fn))
                if sd:
                    states_data.append(sd)
            except Exception:
                pass
        if states_data:
            warnings.append(f"Read {len(states_data)} state files")
    else:
        warnings.append("history/states/ directory was not found")

    # 9a. Scan art assets (colormap / world_normal and other files that HOI4 can read but the tool does not generate)
    assets = _collect_art_assets(mod_dir)
    if assets:
        warnings.append(f"Preserved {len(assets)} original art assets (they will not be overwritten during export)")

    # 9. Read strategic regions (optional)
    sr_dir = os.path.join(mod_dir, "map", "strategicregions")
    sr_data: list[dict] = []
    if os.path.isdir(sr_dir):
        for fn in sorted(os.listdir(sr_dir)):
            if not fn.endswith(".txt"):
                continue
            try:
                rd = _parse_strategic_region_file(os.path.join(sr_dir, fn))
                if rd:
                    sr_data.append(rd)
            except Exception:
                pass
        if sr_data:
            warnings.append(f"Read {len(sr_data)} strategic-region files")
    else:
        warnings.append("map/strategicregions/ directory was not found")

    # 9c. Read localization → replace state name (STATE_1 → "Corsica")
    loc_map = _scan_localisation(mod_dir)
    if loc_map:
        for sd in states_data:
            key = sd.get("name", "")
            if key in loc_map:
                sd["name"] = loc_map[key]
            # VP city name
            vp_names: dict[int, str] = {}
            for vp_pid in sd.get("victory_points", {}):
                vp_key = f"VICTORY_POINTS_{vp_pid}"
                if vp_key in loc_map:
                    vp_names[vp_pid] = loc_map[vp_key]
            if vp_names:
                sd["vp_names"] = vp_names
        # strategic area name
        for rd in sr_data:
            key = rd.get("name", "")
            if key in loc_map:
                rd["name"] = loc_map[key]
        warnings.append(f"Read {len(loc_map)} localization entries")

    # 10. Read railways (optional)
    railways_data: list[dict] = []
    railways_path = os.path.join(map_dir, "railways.txt")
    if os.path.isfile(railways_path):
        railways_data = _parse_railways(railways_path)
        if railways_data:
            warnings.append(f"Read {len(railways_data)} railways")

    # 11. Read supply_nodes (optional)
    supply_data: list[dict] = []
    supply_path = os.path.join(map_dir, "supply_nodes.txt")
    if os.path.isfile(supply_path):
        supply_data = _parse_supply_nodes(supply_path)
        if supply_data:
            warnings.append(f"Read {len(supply_data)} supply hubs")

    # 12. Read adjacencies (optional)
    adjacencies_data: list[dict] = []
    adj_path = os.path.join(map_dir, "adjacencies.csv")
    if os.path.isfile(adj_path):
        adjacencies_data = _parse_adjacencies(adj_path)
        if adjacencies_data:
            warnings.append(f"Read {len(adjacencies_data)} adjacencies")

    # 13. Read country colors (optional)
    country_colors: dict[str, tuple[int, int, int]] = {}
    colors_path = os.path.join(mod_dir, "common", "countries", "colors.txt")
    if os.path.isfile(colors_path):
        country_colors = _parse_country_colors(colors_path)
        if country_colors:
            warnings.append(f"Read colors for {len(country_colors)} countries")

    # 14. Read country history (capital/government, optional)
    country_history = _parse_country_history_dir(mod_dir)
    if country_history:
        warnings.append(f"Read {len(country_history)} country-history files")

    return {
        "width": w,
        "height": h,
        "tile_map": tile_map,
        "province_map": province_map,
        "terrain_map": terrain_map,
        "height_map": height_map,
        "river_map": river_map,
        "province_count": province_count,
        "provincial_terrain": provincial_terrain,
        "states": states_data,
        "strategic_regions": sr_data,
        "railways": railways_data,
        "supply_nodes": supply_data,
        "adjacencies": adjacencies_data,
        "assets": assets,
        "country_colors": country_colors,
        "country_history": country_history,
        # TAG → Localized country names, etc. (states/strategic area names have been replaced locally, country names are checked when filling in)
        "localisation": loc_map,
        "warnings": warnings,
    }


# ── National Color Analysis ───────────────────────────────────────────


def _parse_country_colors(path: str) -> dict[str, tuple[int, int, int]]:
    """Parse common/countries/colors.txt → {TAG: (R, G, B)}."""
    import re
    colors: dict[str, tuple[int, int, int]] = {}
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        text = f.read()
    for m in re.finditer(
        r'(\b[A-Z]{3})\s*=\s*\{[^}]*?color\s*=\s*rgb\s*\{\s*(\d+)\s+(\d+)\s+(\d+)',
        text, re.DOTALL,
    ):
        tag = m.group(1)
        r, g, b = int(m.group(2)), int(m.group(3)), int(m.group(4))
        colors[tag] = (r, g, b)
    return colors


# ── Localized scanning ────────────────────────────────────────────


def _scan_localisation(mod_dir: str) -> dict[str, str]:
    """Scan all .yml files under MOD's localization/ and extract KEY: "value" mapping.

    Read the english/ subdirectory first (the most complete), then the root directory.
    Returns a dictionary of {KEY: value}, used to replace state name, etc."""
    import re
    result: dict[str, str] = {}
    loc_dir = os.path.join(mod_dir, "localisation")
    if not os.path.isdir(loc_dir):
        return result

    def _scan_dir(d: str) -> None:
        if not os.path.isdir(d):
            return
        for root, _dirs, files in os.walk(d):
            for fn in files:
                if not fn.endswith(".yml"):
                    continue
                try:
                    with open(os.path.join(root, fn), "r", encoding="utf-8-sig", errors="ignore") as f:
                        for line in f:
                            # Format: " KEY:0 \"value\"" or " KEY: \"value\""
                            m = re.match(r'\s+(\S+?):\d*\s+"([^"]*)"', line)
                            if m:
                                result[m.group(1)] = m.group(2)
                except OSError:
                    pass

    # English preferred
    _scan_dir(os.path.join(loc_dir, "english"))
    # Scan the root directory again (some MODs are placed directly under localization/)
    for fn in os.listdir(loc_dir):
        full = os.path.join(loc_dir, fn)
        if os.path.isfile(full) and fn.endswith(".yml"):
            try:
                with open(full, "r", encoding="utf-8-sig", errors="ignore") as f:
                    for line in f:
                        import re as _re
                        m = _re.match(r'\s+(\S+?):\d*\s+"([^"]*)"', line)
                        if m and m.group(1) not in result:
                            result[m.group(1)] = m.group(2)
            except OSError:
                pass

    return result


# ── Logistics document analysis ───────────────────────────────────────────


def _parse_railways(path: str) -> list[dict]:
    """Parse map/railways.txt. Each line: level count pid1 pid2 pid3 ..."""
    result = []
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tokens = line.split()
            if len(tokens) < 4:  # level + count + at least 2 provinces
                continue
            try:
                level = int(tokens[0])
                count = int(tokens[1])
                pids = [int(t) for t in tokens[2:2 + count]]
                if len(pids) >= 2:
                    result.append({"level": level, "province_ids": pids})
            except ValueError:
                continue
    return result


def _parse_supply_nodes(path: str) -> list[dict]:
    """Parse map/supply_nodes.txt. Each row: level province_id"""
    result = []
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tokens = line.split()
            if len(tokens) < 2:
                continue
            try:
                level = int(tokens[0])
                pid = int(tokens[1])
                result.append({"level": level, "province_id": pid})
            except ValueError:
                continue
    return result


def _parse_adjacencies(path: str) -> list[dict]:
    """Parse map/adjacencies.csv. Format: From;To;Type;Through;start_x;start_y;stop_x;stop_y;rule;Comment"""
    result = []
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("From"):
                continue
            parts = line.split(";")
            if len(parts) < 4:
                continue
            try:
                from_id = int(parts[0])
                to_id = int(parts[1])
                if from_id < 0 or to_id < 0:
                    continue  # Sentinel Row -1;-1;...
                adj_type = parts[2].strip() or "sea"
                through = int(parts[3]) if len(parts) > 3 and parts[3].strip().lstrip('-').isdigit() else -1
                start_x = int(parts[4]) if len(parts) > 4 and parts[4].strip().lstrip('-').isdigit() else -1
                start_y = int(parts[5]) if len(parts) > 5 and parts[5].strip().lstrip('-').isdigit() else -1
                stop_x = int(parts[6]) if len(parts) > 6 and parts[6].strip().lstrip('-').isdigit() else -1
                stop_y = int(parts[7]) if len(parts) > 7 and parts[7].strip().lstrip('-').isdigit() else -1
                rule = parts[8].strip() if len(parts) > 8 else ""
                comment = parts[9].strip() if len(parts) > 9 else ""
                result.append({
                    "from_id": from_id, "to_id": to_id,
                    "type": adj_type, "through_id": through,
                    "start_x": start_x, "start_y": start_y,
                    "stop_x": stop_x, "stop_y": stop_y,
                    "rule": rule, "comment": comment,
                })
            except (ValueError, IndexError):
                continue
    return result


# ── Art asset scan ───────────────────────────────────────────
# "Structured file" = file that the tool will regenerate from the data (original bytes are not retained)
# Other files = art assets (retain original bytes, unless user editing triggers dirty)

# These map/ file tools will be regenerated from MapData / managers → do not include assets
_STRUCTURAL_MAP_FILES = {
    "provinces.bmp",
    "heightmap.bmp",
    "terrain.bmp",
    "rivers.bmp",
    "trees.bmp",
    "cities.bmp",
    "definition.csv",
    "default.map",
    "continent.txt",
    "adjacencies.csv",
    "adjacency_rules.txt",
    "ambient_object.txt",
    "buildings.txt",
    "positions.txt",
    "railways.txt",
    "supply_nodes.txt",
    "unitstacks.txt",
    "airports.txt",
    "rocket_sites.txt",
    "weatherpositions.txt",
    "seasons.txt",
    "cities.txt",
    "colors.txt",
}


def _collect_art_assets(mod_dir: str) -> dict[str, bytes]:
    """Scan all non-structural files under map/ and map/terrain/ of MOD and return {rel_path: bytes}.

    Structural files (provinces/heightmap/terrain, etc.) are regenerated from the data by the tool and are not collected.
    Art assets (colormap_*.dds, world_normal.bmp, etc.) are left intact.

    The key of the return value is in the form of "map/terrain/colormap_rgb_cityemissivemask_a.dds" (slash separated)."""
    assets: dict[str, bytes] = {}
    map_dir = os.path.join(mod_dir, "map")
    if not os.path.isdir(map_dir):
        return assets

    def _add_file(full_path: str, rel_to_mod: str) -> None:
        try:
            with open(full_path, "rb") as f:
                assets[rel_to_mod.replace(os.sep, "/")] = f.read()
        except OSError:
            pass

    # Scan the map/ root directory
    for fn in os.listdir(map_dir):
        full = os.path.join(map_dir, fn)
        if not os.path.isfile(full):
            continue
        if fn in _STRUCTURAL_MAP_FILES:
            continue
        # Collect unstructured files (world_normal.bmp, etc.)
        _add_file(full, f"map/{fn}")

    # Scan all .dds / .bmp under map/terrain/ (all art, vanilla generated, no structured files)
    terrain_dir = os.path.join(map_dir, "terrain")
    if os.path.isdir(terrain_dir):
        for fn in os.listdir(terrain_dir):
            full = os.path.join(terrain_dir, fn)
            if not os.path.isfile(full):
                continue
            _add_file(full, f"map/terrain/{fn}")

    return assets


# ──National History───────────────────────────────────────────

_CAPITAL_RE = re.compile(r"^\s*capital\s*=\s*(\d+)", re.M)
_RULING_PARTY_RE = re.compile(r"ruling_party\s*=\s*(\w+)")


def _parse_country_history_dir(mod_dir: str) -> dict[str, dict]:
    """Parse history/countries/*.txt → {TAG: {capital_state, ruling_party}}.

    The file name convention is "TAG - Name.txt". Extract only the two most commonly used fields:
    - capital: Note that HOI4 here is the State ID, not the province ID.
      Must be converted before filling into CountryData (see _populate_imported_data)
    - ruling_party in set_politics block"""
    out: dict[str, dict] = {}
    hist_dir = os.path.join(mod_dir, "history", "countries")
    if not os.path.isdir(hist_dir):
        return out
    for fn in sorted(os.listdir(hist_dir)):
        if not fn.endswith(".txt"):
            continue
        tag = fn[:3].upper()
        if len(tag) != 3 or not tag.isascii() or not tag.isalnum():
            continue
        try:
            with open(os.path.join(hist_dir, fn), "r",
                      encoding="utf-8-sig", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        cap_m = _CAPITAL_RE.search(text)
        party_m = _RULING_PARTY_RE.search(text)
        out[tag] = {
            "capital_state": int(cap_m.group(1)) if cap_m else 0,
            "ruling_party": party_m.group(1) if party_m else "",
        }
    return out
