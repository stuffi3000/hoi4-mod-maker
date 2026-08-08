"""
Strategic Region 管理器 — 战略区域数据.

参考: 参考/Strategic region modding .txt

每个 region:
- id: 连续整数 (跳号崩)
- name: 本地化 key
- province_ids: 所属省份 (每个省份只能属一个 region)
- weather_preset: 'polar'/'cold'/'temperate'/'tropical'/'desert' — 自动填天气
- naval_terrain: 仅海洋 region, 下拉选
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.ndimage import label as _ndimage_label


WeatherPreset = Literal["polar", "cold", "temperate", "tropical", "desert"]

# 天气预设 → 12 个 period（每月一个），与 vanilla 格式一致
# between 格式: {START_DAY.MONTH END_DAY.MONTH}，period 不能跨月
# 月末日: Jan/Mar/May/Jul/Aug/Oct/Dec=30, Feb=27, Apr/Jun/Sep/Nov=29
# 写错月末日会导致 HOI4 报 "overlapping temperature intervals"

# 月份末日表（每月合法的最大 day 值，day 从 0 起算）
_MONTH_LAST_DAY = [30, 27, 30, 29, 30, 29, 30, 30, 29, 30, 29, 30]

# 每种气候的 12 个月参数（冬冷夏暖）— 季节性强度按预设调整
# 索引 0=Jan ... 11=Dec
def _make_seasonal(winter: dict, spring: dict, summer: dict, autumn: dict) -> list[dict]:
    """给定 4 季参数，展开成 12 个月 period 列表。
    冬=Dec/Jan/Feb, 春=Mar/Apr/May, 夏=Jun/Jul/Aug, 秋=Sep/Oct/Nov。
    """
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
    "polar": "极地", "cold": "寒带", "temperate": "温带",
    "tropical": "热带", "desert": "沙漠",
}
PRESET_LABELS_EN = {
    "polar": "Polar", "cold": "Cold", "temperate": "Temperate",
    "tropical": "Tropical", "desert": "Desert",
}


def weather_preset_display_name(preset: str) -> str:
    """Return a localized label for a strategic-region weather preset."""
    from ui.i18n import tr_pair
    return tr_pair(
        PRESET_LABELS.get(preset, preset),
        PRESET_LABELS_EN.get(preset, preset),
    )


def _split_connected(province_map: np.ndarray, pids: set[int]) -> list[list[int]]:
    """把一组省份按**像素 4-邻接**拆成若干连通分量。

    HOI4 要求战略区域内所有省份地理相连。这里用 scipy 的 label 函数算像素级
    连通分量，然后把属于同一分量的省份归为一组。
    （像素邻接 = HOI4 的省份邻接，两者等价。）
    """
    if not pids:
        return []
    sub_mask = np.isin(province_map, list(pids))
    labeled, num_features = _ndimage_label(sub_mask)
    if num_features == 0:
        return []

    sub_pixels = sub_mask.ravel()
    flat_pm = province_map.ravel()[sub_pixels]
    flat_lb = labeled.ravel()[sub_pixels]

    # 每个省份取第一个像素的 component_id（同一省份所有像素在同一连通分量）
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


# 旧名保留一个别名，避免外部调用炸掉
_split_connected_sea = _split_connected


@dataclass
class StrategicRegion:
    id: int
    name: str = ""                 # 用户输入的主显示名（任何语言，可含中文）
    name_en: str = ""              # 可选英文名（本地化英文 yml 用；空则默认 "Region {id}"）
    province_ids: list[int] = field(default_factory=list)
    weather_preset: str = "temperate"
    naval_terrain: str = ""  # vanilla 合法值: "" / water_deep_ocean / water_shallow_sea / water_fjords

    # 注意: 不要再在 __post_init__ 里把 name 填成 STRATEGICREGION_{id}
    # name 是显示名（可中文），key 在导出时独立生成（strategic_regions writer）


class StrategicRegionManager:
    """管理所有战略区域. ID 必须连续从 1 开始."""

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
        """新建空 region, 返回它."""
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
        """把省份分配给 region. 自动从旧 region 移除."""
        for r in self._regions.values():
            if pid in r.province_ids:
                r.province_ids.remove(pid)
        if rid in self._regions:
            self._regions[rid].province_ids.append(pid)

    def get_region_of_province(self, pid: int) -> int:
        """查省份属于哪个 region. 0 = 未分配."""
        for r in self._regions.values():
            if pid in r.province_ids:
                return r.id
        return 0

    def auto_generate(
        self,
        province_map: np.ndarray,
        tile_map: np.ndarray,
        state_mgr=None,        # 保留参数兼容旧调用方, 但不再使用
        grid_cols: int = 6,
        grid_rows: int = 4,
    ) -> None:
        """自动生成战略区域 (覆盖现有数据).

        策略 — 纯网格 + 海陆分开 + 连通拆分 (vanilla 风格的大块 region).
        旧版本按 state 一对一生成 region (590+ 次连通分量计算) 在大地图上极慢
        且产生过多碎 region; 新算法只跑 grid_cols*grid_rows*2 次连通分量,
        生成 vanilla 风格的大块 region (典型 30-100 个).

        **铁律**: 每个 region 内省份必须地理 4-邻接连通, 且海陆不能混 — 否则
        HOI4 加载时引擎死循环 / 除零崩溃.
        """
        from data.constants import TILE_LAND

        self._regions = {}
        self._next_id = 1

        province_count = int(province_map.max())
        if province_count == 0:
            return

        # 用实际 province_map 尺寸 (项目可能不是原版分辨率)
        MAP_HEIGHT, MAP_WIDTH = province_map.shape[0], province_map.shape[1]

        flat_pm = province_map.ravel()
        n = province_count + 1
        pid_count = np.bincount(flat_pm, minlength=n)
        ys, xs = np.mgrid[0:MAP_HEIGHT, 0:MAP_WIDTH]
        sum_y = np.bincount(flat_pm, weights=ys.ravel().astype(np.float64), minlength=n)
        sum_x = np.bincount(flat_pm, weights=xs.ravel().astype(np.float64), minlength=n)

        # 多数决判断陆地省份
        land_flat = (tile_map == TILE_LAND).ravel()
        land_count = np.bincount(flat_pm, weights=land_flat, minlength=n)
        is_land_per_pid = land_count * 2 > pid_count

        # 按质心把 province 分到 grid_rows×grid_cols 个网格
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

        # 每格分海陆, 各自按连通性拆成若干 region
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

        # 自动分配 weather preset (按质心纬度)
        for r in self._regions.values():
            if not r.province_ids:
                continue
            total_y = sum(float(sum_y[p]) / max(pid_count[p], 1) for p in r.province_ids)
            avg_y = total_y / len(r.province_ids)
            # 纬度映射: y=0 北极, y=MAP_HEIGHT 南极, 中间赤道
            lat_fraction = avg_y / MAP_HEIGHT  # 0=北极, 0.5=赤道, 1=南极
            dist_from_equator = abs(lat_fraction - 0.5) * 2  # 0=赤道, 1=极地
            if dist_from_equator > 0.8:
                r.weather_preset = "polar"
            elif dist_from_equator > 0.6:
                r.weather_preset = "cold"
            elif dist_from_equator > 0.3:
                r.weather_preset = "temperate"
            else:
                # 赤道附近: 检查是否沙漠 (如果大部分省份是沙漠地形)
                r.weather_preset = "tropical"

    def auto_assign_weather_by_latitude(
        self, province_map: np.ndarray,
    ) -> int:
        """按纬度自动分配天气预设, 返回修改的 region 数量.

        HOI4 地图: 图像 y=0 是最北(极地), y=MAP_HEIGHT 是最南(极地),
        中间是赤道. 用距赤道的归一化距离分带:
          0-0.15 (赤道附近): tropical
          0.15-0.35: desert
          0.35-0.60: temperate
          0.60-0.80: cold
          0.80-1.0 (极地): polar
        """
        map_height = province_map.shape[0]
        if map_height == 0 or not self._regions:
            return 0

        # 向量化质心计算
        flat = province_map.ravel()
        n = int(province_map.max()) + 1
        pid_count = np.bincount(flat, minlength=n)
        ys = np.mgrid[0:province_map.shape[0], 0:province_map.shape[1]][0]
        sum_y = np.bincount(flat, weights=ys.ravel().astype(np.float64), minlength=n)

        changed = 0
        for r in self._regions.values():
            if not r.province_ids:
                continue
            # region 质心 y（只用有像素的省份）
            total_y = 0.0
            valid = 0
            for p in r.province_ids:
                if p < n and pid_count[p] > 0:
                    total_y += sum_y[p] / pid_count[p]
                    valid += 1
            if valid == 0:
                continue
            avg_y = total_y / valid
            # 归一化到 [0,1]: 0=北极, 0.5=赤道, 1=南极
            lat_frac = avg_y / map_height
            dist = abs(lat_frac - 0.5) * 2  # 0=赤道, 1=极地

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
        """生成战略区域着色图 (H, W, 3) — 每个 region 一种颜色.

        如果提供 tile_map, 海洋省份用蓝色系、陆地省份用暖色系,
        避免相邻的海洋/陆地区域颜色接近而无法区分.
        """
        from data.constants import TILE_SEA, TILE_LAKE

        max_pid = int(province_map.max())
        lut = np.full((max_pid + 1, 3), 50, dtype=np.uint8)  # 未分配=深灰

        # 向量化判断每个省份是否为海洋/湖泊
        is_sea = set()
        if tile_map is not None:
            flat_pm = province_map.ravel()
            flat_tm = tile_map.ravel()
            # 统计每个 pid 的海洋像素数和总像素数
            sea_mask = np.isin(flat_tm, [TILE_SEA, TILE_LAKE])
            total_count = np.bincount(flat_pm, minlength=max_pid + 1)
            sea_count = np.bincount(flat_pm, weights=sea_mask.astype(np.float64), minlength=max_pid + 1)
            # 海洋像素 > 50% 的省份视为海洋
            for pid in range(1, max_pid + 1):
                if total_count[pid] > 0 and sea_count[pid] > total_count[pid] * 0.5:
                    is_sea.add(pid)

        for rid, region in self._regions.items():
            # 判断该 region 是海洋还是陆地（按多数省份）
            if is_sea and region.province_ids:
                sea_count = sum(1 for p in region.province_ids if p in is_sea)
                region_is_sea = sea_count > len(region.province_ids) // 2
            else:
                region_is_sea = False

            rng = np.random.RandomState(rid * 7 + 13)
            if region_is_sea:
                # 蓝色系: R=40-100, G=60-140, B=150-230
                r = rng.randint(40, 100)
                g = rng.randint(60, 140)
                b = rng.randint(150, 230)
            else:
                # 暖色系: R=120-230, G=80-200, B=40-120
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

    # ─────────── 序列化 ───────────

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
        # 老项目兼容: 把短名/非法名迁移到 vanilla 完整名
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
