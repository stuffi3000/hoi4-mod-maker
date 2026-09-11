"""Strategic Region Manager — strategic region data.

Reference: Reference/Strategic region modding .txt

Each region:
- id: continuous integer (number jump collapse)
- name: localization key
- province_ids: province (each province can only belong to one region)
- weather_preset: 'polar'/'cold'/'temperate'/'tropical'/'desert' — automatically fill in the weather
- naval_terrain: only ocean region, drop-down selection"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.ndimage import label as _ndimage_label


WeatherPreset = Literal["polar", "cold", "temperate", "tropical", "desert"]

# Weather presets → 12 periods (one per month), consistent with vanilla format
# between format: {START_DAY.MONTH END_DAY.MONTH}, period cannot span months
# Last day of the month: Jan/Mar/May/Jul/Aug/Oct/Dec=30, Feb=27, Apr/Jun/Sep/Nov=29
# Writing the wrong end of the month will cause HOI4 to report "overlapping temperature intervals"

# End of month table (maximum legal day value per month, day starts from 0)
_MONTH_LAST_DAY = [30, 27, 30, 29, 30, 29, 30, 30, 29, 30, 29, 30]

# 12-month parameters for each climate (cold in winter, warm in summer) - seasonal intensity adjusted by preset
# Index 0=Jan ... 11=Dec
def _make_seasonal(winter: dict, spring: dict, summer: dict, autumn: dict) -> list[dict]:
    """Given 4 quarter parameters, expand into a list of 12 month periods.
    Winter=Dec/Jan/Feb, Spring=Mar/Apr/May, Summer=Jun/Jul/Aug, Autumn=Sep/Oct/Nov."""
    season_by_month = [winter, winter, spring, spring, spring, summer,
                       summer, summer, autumn, autumn, autumn, winter]
    periods = []
    for m, s in enumerate(season_by_month):
        periods.append({
            "between": f"0.{m} {_MONTH_LAST_DAY[m]}.{m}",
            **s,
        })
    return periods


WEATHER_PRESETS: dict[str, list[dict]] = {
    "polar": _make_seasonal(
        winter={"temp": "-35.0 -10.0", "no": 0.2, "snow": 0.4, "blizzard": 0.35,
                "rain_light": 0.0, "rain_heavy": 0.0, "mud": 0.0, "sandstorm": 0.0, "min_snow": 0.6},
        spring={"temp": "-25.0 -5.0", "no": 0.25, "snow": 0.35, "blizzard": 0.25,
                "rain_light": 0.05, "rain_heavy": 0.0, "mud": 0.05, "sandstorm": 0.0, "min_snow": 0.5},
        summer={"temp": "-15.0 5.0", "no": 0.35, "snow": 0.2, "blizzard": 0.1,
                "rain_light": 0.15, "rain_heavy": 0.05, "mud": 0.1, "sandstorm": 0.0, "min_snow": 0.3},
        autumn={"temp": "-25.0 -5.0", "no": 0.25, "snow": 0.35, "blizzard": 0.25,
                "rain_light": 0.05, "rain_heavy": 0.0, "mud": 0.05, "sandstorm": 0.0, "min_snow": 0.5},
    ),
    "cold": _make_seasonal(
        winter={"temp": "-15.0 0.0", "no": 0.3, "snow": 0.3, "blizzard": 0.15,
                "rain_light": 0.1, "rain_heavy": 0.05, "mud": 0.05, "sandstorm": 0.0, "min_snow": 0.2},
        spring={"temp": "0.0 15.0", "no": 0.4, "snow": 0.1, "blizzard": 0.0,
                "rain_light": 0.2, "rain_heavy": 0.1, "mud": 0.15, "sandstorm": 0.0, "min_snow": 0.0},
        summer={"temp": "10.0 25.0", "no": 0.5, "snow": 0.0, "blizzard": 0.0,
                "rain_light": 0.2, "rain_heavy": 0.1, "mud": 0.1, "sandstorm": 0.0, "min_snow": 0.0},
        autumn={"temp": "-5.0 10.0", "no": 0.35, "snow": 0.2, "blizzard": 0.05,
                "rain_light": 0.2, "rain_heavy": 0.1, "mud": 0.1, "sandstorm": 0.0, "min_snow": 0.1},
    ),
    "temperate": _make_seasonal(
        winter={"temp": "-5.0 10.0", "no": 0.4, "snow": 0.15, "blizzard": 0.05,
                "rain_light": 0.2, "rain_heavy": 0.1, "mud": 0.1, "sandstorm": 0.0, "min_snow": 0.0},
        spring={"temp": "5.0 20.0", "no": 0.5, "snow": 0.05, "blizzard": 0.0,
                "rain_light": 0.25, "rain_heavy": 0.1, "mud": 0.1, "sandstorm": 0.0, "min_snow": 0.0},
        summer={"temp": "15.0 30.0", "no": 0.6, "snow": 0.0, "blizzard": 0.0,
                "rain_light": 0.2, "rain_heavy": 0.15, "mud": 0.05, "sandstorm": 0.0, "min_snow": 0.0},
        autumn={"temp": "5.0 18.0", "no": 0.5, "snow": 0.05, "blizzard": 0.0,
                "rain_light": 0.25, "rain_heavy": 0.1, "mud": 0.1, "sandstorm": 0.0, "min_snow": 0.0},
    ),
    "tropical": _make_seasonal(
        winter={"temp": "18.0 30.0", "no": 0.35, "snow": 0.0, "blizzard": 0.0,
                "rain_light": 0.25, "rain_heavy": 0.25, "mud": 0.15, "sandstorm": 0.0, "min_snow": 0.0},
        spring={"temp": "20.0 33.0", "no": 0.3, "snow": 0.0, "blizzard": 0.0,
                "rain_light": 0.25, "rain_heavy": 0.25, "mud": 0.2, "sandstorm": 0.0, "min_snow": 0.0},
        summer={"temp": "22.0 35.0", "no": 0.3, "snow": 0.0, "blizzard": 0.0,
                "rain_light": 0.2, "rain_heavy": 0.3, "mud": 0.2, "sandstorm": 0.0, "min_snow": 0.0},
        autumn={"temp": "20.0 33.0", "no": 0.3, "snow": 0.0, "blizzard": 0.0,
                "rain_light": 0.25, "rain_heavy": 0.25, "mud": 0.2, "sandstorm": 0.0, "min_snow": 0.0},
    ),
    "desert": _make_seasonal(
        winter={"temp": "5.0 25.0", "no": 0.65, "snow": 0.0, "blizzard": 0.0,
                "rain_light": 0.05, "rain_heavy": 0.0, "mud": 0.0, "sandstorm": 0.2, "min_snow": 0.0},
        spring={"temp": "15.0 35.0", "no": 0.6, "snow": 0.0, "blizzard": 0.0,
                "rain_light": 0.05, "rain_heavy": 0.0, "mud": 0.0, "sandstorm": 0.3, "min_snow": 0.0},
        summer={"temp": "25.0 50.0", "no": 0.55, "snow": 0.0, "blizzard": 0.0,
                "rain_light": 0.02, "rain_heavy": 0.0, "mud": 0.0, "sandstorm": 0.35, "min_snow": 0.0},
        autumn={"temp": "15.0 35.0", "no": 0.6, "snow": 0.0, "blizzard": 0.0,
                "rain_light": 0.05, "rain_heavy": 0.0, "mud": 0.0, "sandstorm": 0.3, "min_snow": 0.0},
    ),
}

PRESET_LABELS = {
    "polar": "Polar", "cold": "Cold", "temperate": "Temperate",
    "tropical": "Tropical", "desert": "Desert",
}


def weather_preset_display_name(preset: str) -> str:
    """Return the English label for a strategic-region weather preset."""
    return PRESET_LABELS.get(preset, preset)


def _split_connected(province_map: np.ndarray, pids: set[int]) -> list[list[int]]:
    """Split a group of provinces into several connected components based on **pixel 4-adjacency**.

    HOI4 requires that all provinces within a strategic area are geographically connected. Here we use scipy’s label function to calculate the pixel level
    Connect the components, and then group provinces belonging to the same component.
    (Pixel adjacency = HOI4 province adjacency, both are equivalent.)"""
    if not pids:
        return []
    sub_mask = np.isin(province_map, list(pids))
    labeled, num_features = _ndimage_label(sub_mask)
    if num_features == 0:
        return []

    sub_pixels = sub_mask.ravel()
    flat_pm = province_map.ravel()[sub_pixels]
    flat_lb = labeled.ravel()[sub_pixels]

    # Get the component_id of the first pixel in each province (all pixels in the same province are in the same connected component)
    pid_to_comp: dict[int, int] = {}
    for i in range(len(flat_pm)):
        pid = int(flat_pm[i])
        if pid not in pid_to_comp:
            pid_to_comp[pid] = int(flat_lb[i])

    groups: dict[int, list[int]] = {}
    for pid, comp in pid_to_comp.items():
        if comp > 0:
            groups.setdefault(comp, []).append(pid)

    return [sorted(g) for g in groups.values() if g]


# Keep an alias for the old name to avoid external calls from blowing up.
_split_connected_sea = _split_connected


@dataclass
class StrategicRegion:
    id: int
    name: str = ""                 # Primary display name entered by the user; may contain non-ASCII text.
    name_en: str = ""              # Optional English name (for localized English yml; if empty, the default is "Region {id}")
    province_ids: list[int] = field(default_factory=list)
    weather_preset: str = "temperate"
    naval_terrain: str = ""  # vanilla legal values: "" / water_deep_ocean / water_shallow_sea / water_fjords

    # Note: Do not fill in name as STRATEGICREGION_{id} in __post_init__
    # name is the display name; the export key is generated independently by the strategic-regions writer.


class StrategicRegionManager:
    """Manage all strategic areas. IDs must start from 1 consecutively."""

    def __init__(self) -> None:
        self._regions: dict[int, StrategicRegion] = {}
        self._next_id = 1

    @property
    def regions(self) -> dict[int, StrategicRegion]:
        return dict(self._regions)

    def count(self) -> int:
        return len(self._regions)

    def get(self, rid: int) -> StrategicRegion | None:
        return self._regions.get(rid)

    def create_region(self, name: str = "") -> StrategicRegion:
        """Create a new empty region and return it."""
        r = StrategicRegion(id=self._next_id, name=name)
        self._regions[self._next_id] = r
        self._next_id += 1
        return r

    def remove_region(self, rid: int) -> bool:
        if rid in self._regions:
            del self._regions[rid]
            return True
        return False

    def assign_province(self, pid: int, rid: int) -> None:
        """Assign provinces to regions. Automatically remove from old regions."""
        for r in self._regions.values():
            if pid in r.province_ids:
                r.province_ids.remove(pid)
        if rid in self._regions:
            self._regions[rid].province_ids.append(pid)

    def get_region_of_province(self, pid: int) -> int:
        """Check which region the province belongs to. 0 = not assigned."""
        for r in self._regions.values():
            if pid in r.province_ids:
                return r.id
        return 0

    def auto_generate(
        self,
        province_map: np.ndarray,
        tile_map: np.ndarray,
        state_mgr=None,        # Parameters retained for compatibility with older callers, but no longer used
        grid_cols: int = 6,
        grid_rows: int = 4,
    ) -> None:
        """Automatic generation of strategic areas (overwriting existing data).

        Strategy — pure mesh + land and sea separation + connected split (vanilla style large regions).
        The old version generates regions one-to-one by state (590+ connected component calculations), which is extremely slow on large maps.
        And there are too many broken regions; the new algorithm only runs grid_cols*grid_rows*2 times for connected components,
        Generate vanilla-style large regions (typically 30-100).

        **Iron Rule**: Provinces in each region must be geographically 4-adjacent and connected, and land and sea cannot be mixed — otherwise
        Engine infinite loop/divide-by-zero crash when loading HOI4."""
        from data.constants import TILE_LAND

        self._regions = {}
        self._next_id = 1

        province_count = int(province_map.max())
        if province_count == 0:
            return

        # Use actual province_map dimensions (project may not be in original resolution)
        MAP_HEIGHT, MAP_WIDTH = province_map.shape[0], province_map.shape[1]

        flat_pm = province_map.ravel()
        n = province_count + 1
        pid_count = np.bincount(flat_pm, minlength=n)
        ys, xs = np.mgrid[0:MAP_HEIGHT, 0:MAP_WIDTH]
        sum_y = np.bincount(flat_pm, weights=ys.ravel().astype(np.float64), minlength=n)
        sum_x = np.bincount(flat_pm, weights=xs.ravel().astype(np.float64), minlength=n)

        # Majority rule determines land provinces
        land_flat = (tile_map == TILE_LAND).ravel()
        land_count = np.bincount(flat_pm, weights=land_flat, minlength=n)
        is_land_per_pid = land_count * 2 > pid_count

        # Divide province into grid_rows×grid_cols grids according to centroid
        cell_h = MAP_HEIGHT / max(1, grid_rows)
        cell_w = MAP_WIDTH / max(1, grid_cols)
        buckets: dict[int, list[int]] = {}
        for pid in range(1, province_count + 1):
            if pid_count[pid] == 0:
                continue
            cy = sum_y[pid] / pid_count[pid]
            cx = sum_x[pid] / pid_count[pid]
            row = min(int(cy / cell_h), grid_rows - 1)
            col = min(int(cx / cell_w), grid_cols - 1)
            key = row * grid_cols + col
            buckets.setdefault(key, []).append(pid)

        # Each grid is divided into sea and land, and each is divided into several regions according to connectivity.
        for provs in buckets.values():
            sea_provs = [p for p in provs if not is_land_per_pid[p]]
            land_provs = [p for p in provs if is_land_per_pid[p]]
            for group in _split_connected(province_map, set(sea_provs)):
                r = self.create_region()
                r.province_ids = list(group)
                r.naval_terrain = "water_deep_ocean"
            for group in _split_connected(province_map, set(land_provs)):
                r = self.create_region()
                r.province_ids = list(group)
                r.naval_terrain = ""

        # Automatically assign weather preset (by centroid latitude)
        for r in self._regions.values():
            if not r.province_ids:
                continue
            total_y = sum(float(sum_y[p]) / max(pid_count[p], 1) for p in r.province_ids)
            avg_y = total_y / len(r.province_ids)
            # Latitude mapping: y=0 North Pole, y=MAP_HEIGHT South Pole, middle equator
            lat_fraction = avg_y / MAP_HEIGHT  # 0=North Pole, 0.5=Equator, 1=South Pole
            dist_from_equator = abs(lat_fraction - 0.5) * 2  # 0=equator, 1=polar
            if dist_from_equator > 0.8:
                r.weather_preset = "polar"
            elif dist_from_equator > 0.6:
                r.weather_preset = "cold"
            elif dist_from_equator > 0.3:
                r.weather_preset = "temperate"
            else:
                # Near the equator: Check if it is a desert (if most of the province is desert terrain)
                r.weather_preset = "tropical"

    def auto_assign_weather_by_latitude(
        self, province_map: np.ndarray,
    ) -> int:
        """Automatically assign weather presets by latitude, returning the number of modified regions.

        HOI4 map: image y=0 is the northernmost (polar), y=MAP_HEIGHT is the southernmost (polar),
        In the middle is the equator. Bands are divided by normalized distance from the equator:
          0-0.15 (near the equator): tropical
          0.15-0.35: desert
          0.35-0.60: temperate
          0.60-0.80: cold
          0.80-1.0 (polar): polar"""
        map_height = province_map.shape[0]
        if map_height == 0 or not self._regions:
            return 0

        # Vectorized centroid calculation
        flat = province_map.ravel()
        n = int(province_map.max()) + 1
        pid_count = np.bincount(flat, minlength=n)
        ys = np.mgrid[0:province_map.shape[0], 0:province_map.shape[1]][0]
        sum_y = np.bincount(flat, weights=ys.ravel().astype(np.float64), minlength=n)

        changed = 0
        for r in self._regions.values():
            if not r.province_ids:
                continue
            # region centroid y (only provinces with pixels are used)
            total_y = 0.0
            valid = 0
            for p in r.province_ids:
                if p < n and pid_count[p] > 0:
                    total_y += sum_y[p] / pid_count[p]
                    valid += 1
            if valid == 0:
                continue
            avg_y = total_y / valid
            # Normalized to [0,1]: 0=North Pole, 0.5=Equator, 1=South Pole
            lat_frac = avg_y / map_height
            dist = abs(lat_frac - 0.5) * 2  # 0=equator, 1=polar

            if dist > 0.80:
                preset = "polar"
            elif dist > 0.60:
                preset = "cold"
            elif dist > 0.35:
                preset = "temperate"
            elif dist > 0.15:
                preset = "desert"
            else:
                preset = "tropical"

            r.weather_preset = preset
            changed += 1
        return changed

    def build_sr_color_map(
        self, province_map: np.ndarray, tile_map: np.ndarray | None = None,
    ) -> np.ndarray:
        """Generate strategic region coloring map (H, W, 3) — one color per region.

        If tile_map is provided, ocean provinces use blue and land provinces use warm colors.
        Avoid adjacent ocean/land areas that are so close in color that they are indistinguishable."""
        from data.constants import TILE_SEA, TILE_LAKE

        max_pid = int(province_map.max())
        lut = np.full((max_pid + 1, 3), 50, dtype=np.uint8)  # Unallocated = dark gray

        # Vectorization determines whether each province is an ocean/lake
        is_sea = set()
        if tile_map is not None:
            flat_pm = province_map.ravel()
            flat_tm = tile_map.ravel()
            # Count the number of ocean pixels and total number of pixels for each pid
            sea_mask = np.isin(flat_tm, [TILE_SEA, TILE_LAKE])
            total_count = np.bincount(flat_pm, minlength=max_pid + 1)
            sea_count = np.bincount(flat_pm, weights=sea_mask.astype(np.float64), minlength=max_pid + 1)
            # Ocean pixels > 50% of provinces considered ocean
            for pid in range(1, max_pid + 1):
                if total_count[pid] > 0 and sea_count[pid] > total_count[pid] * 0.5:
                    is_sea.add(pid)

        for rid, region in self._regions.items():
            # Determine whether the region is ocean or land (based on the majority of provinces)
            if is_sea and region.province_ids:
                sea_count = sum(1 for p in region.province_ids if p in is_sea)
                region_is_sea = sea_count > len(region.province_ids) // 2
            else:
                region_is_sea = False

            rng = np.random.RandomState(rid * 7 + 13)
            if region_is_sea:
                # Blue: R=40-100, G=60-140, B=150-230
                r = rng.randint(40, 100)
                g = rng.randint(60, 140)
                b = rng.randint(150, 230)
            else:
                # Warm colors: R=120-230, G=80-200, B=40-120
                r = rng.randint(120, 230)
                g = rng.randint(80, 200)
                b = rng.randint(40, 120)
            color = np.array([r, g, b], dtype=np.uint8)

            for pid in region.province_ids:
                if 0 < pid <= max_pid:
                    lut[pid] = color

        flat = np.clip(province_map.ravel(), 0, max_pid)
        return lut[flat].reshape(province_map.shape[0], province_map.shape[1], 3)

    def clear(self) -> None:
        self._regions = {}
        self._next_id = 1

    # ─────────── Serialization ───────────

    def to_dict(self) -> dict:
        return {
            "next_id": self._next_id,
            "regions": [
                {
                    "id": r.id,
                    "name": r.name,
                    "province_ids": list(r.province_ids),
                    "weather_preset": r.weather_preset,
                    "naval_terrain": r.naval_terrain,
                }
                for r in self._regions.values()
            ],
        }

    def from_dict(self, data: dict) -> None:
        self._regions = {}
        self._next_id = int(data.get("next_id", 1))
        # Old project compatibility: migrate short/illegal names to vanilla full names
        _NAVAL_MIGRATE = {
            "ocean": "water_deep_ocean",
            "deep_ocean": "water_deep_ocean",
            "shallow_sea": "water_shallow_sea",
            "fjords": "water_fjords",
        }
        for d in data.get("regions", []):
            nt = d.get("naval_terrain", "")
            nt = _NAVAL_MIGRATE.get(nt, nt)
            r = StrategicRegion(
                id=int(d["id"]),
                name=d.get("name", ""),
                province_ids=[int(p) for p in d.get("province_ids", [])],
                weather_preset=d.get("weather_preset", "temperate"),
                naval_terrain=nt,
            )
            self._regions[r.id] = r
            self._next_id = max(self._next_id, r.id + 1)
