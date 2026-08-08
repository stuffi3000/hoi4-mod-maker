"""
Continent 管理器 — 大陆数据结构、省份指派、导出

HOI4 规则（Map modding §Continents）:
- continent.txt 列出所有大陆名
- definition.csv 最后一列 continent 是整数索引 (1-based)
- 海/湖省份 continent = 0
- 所有陆地省份必须属于某个大陆, 否则报错

默认值: 一个大陆 "default_continent", 所有陆地省份全部归属它.
用户可在 UI 添加/重命名/删除大陆, 并把省份指派到指定大陆.
"""

from __future__ import annotations

import numpy as np


class ContinentManager:
    """管理大陆列表 + 省份→大陆映射"""

    DEFAULT_NAME = "default_continent"

    def __init__(self) -> None:
        # 大陆名列表, 索引从 0 开始; HOI4 continent ID = index + 1
        self._names: list[str] = [self.DEFAULT_NAME]
        # 省份 → 大陆索引 (0-based); 未在此 dict 的 land 省份默认指向 0
        self._province_continent: dict[int, int] = {}

    # ───────────── 大陆 CRUD ─────────────

    @property
    def names(self) -> list[str]:
        """返回大陆名列表 (顺序即 HOI4 ID 顺序, 1-based)"""
        return list(self._names)

    def count(self) -> int:
        return len(self._names)

    def get_name(self, index: int) -> str:
        """按 0-based 索引取名, 越界返回默认"""
        if 0 <= index < len(self._names):
            return self._names[index]
        return self.DEFAULT_NAME

    def add_continent(self, name: str) -> int:
        """添加大陆, 返回其 0-based 索引. 重名则返回现有索引."""
        name = name.strip()
        if not name:
            raise ValueError("Continent name cannot be empty")
        if name in self._names:
            return self._names.index(name)
        self._names.append(name)
        return len(self._names) - 1

    def rename_continent(self, index: int, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Continent name cannot be empty")
        if not (0 <= index < len(self._names)):
            raise IndexError(f"Continent index out of range: {index}")
        if new_name in self._names and self._names.index(new_name) != index:
            raise ValueError(f"Continent name already exists: {new_name}")
        self._names[index] = new_name

    def remove_continent(self, index: int) -> None:
        """删除大陆. 必须至少保留 1 个. 指向该大陆的省份改指向 0."""
        if len(self._names) <= 1:
            raise ValueError("At least one continent must remain")
        if not (0 <= index < len(self._names)):
            raise IndexError(f"Continent index out of range: {index}")
        self._names.pop(index)
        # 重新映射省份: 被删的 → 0, 后面的 → 前移 1
        new_map: dict[int, int] = {}
        for pid, ci in self._province_continent.items():
            if ci == index:
                new_map[pid] = 0
            elif ci > index:
                new_map[pid] = ci - 1
            else:
                new_map[pid] = ci
        self._province_continent = new_map

    # ───────────── 省份指派 ─────────────

    def assign_province(self, pid: int, continent_index: int) -> None:
        if not (0 <= continent_index < len(self._names)):
            raise IndexError(f"Continent index out of range: {continent_index}")
        self._province_continent[pid] = continent_index

    def assign_provinces(self, pids: list[int], continent_index: int) -> None:
        for pid in pids:
            self.assign_province(pid, continent_index)

    def get_province_continent(self, pid: int) -> int:
        """返回省份的 0-based 大陆索引, 未指派返回 0"""
        return self._province_continent.get(pid, 0)

    def get_province_continent_hoi4_id(self, pid: int, is_land: bool) -> int:
        """返回 HOI4 continent ID (1-based). 海/湖返回 0."""
        if not is_land:
            return 0
        return self.get_province_continent(pid) + 1

    # ───────────── 数据同步 ─────────────

    def drop_provinces(self, pids: set[int]) -> None:
        """删除一批省份的指派 (供 compact_with_references 调用)"""
        for pid in pids:
            self._province_continent.pop(pid, None)

    def remap_provinces(self, old_to_new: dict[int, int]) -> None:
        """按旧→新 ID 映射重写 (供 ID 压实调用)"""
        new_map: dict[int, int] = {}
        for old_pid, ci in self._province_continent.items():
            new_pid = old_to_new.get(old_pid)
            if new_pid is not None:
                new_map[new_pid] = ci
        self._province_continent = new_map

    def clear(self) -> None:
        self._names = [self.DEFAULT_NAME]
        self._province_continent = {}

    # ───────────── 序列化 ─────────────

    def to_dict(self) -> dict:
        return {
            "names": list(self._names),
            "province_continent": dict(self._province_continent),
        }

    def from_dict(self, data: dict) -> None:
        self._names = list(data.get("names", [self.DEFAULT_NAME]))
        if not self._names:
            self._names = [self.DEFAULT_NAME]
        raw = data.get("province_continent", {})
        # JSON 会把 int key 转成 str, 这里兼容
        self._province_continent = {int(k): int(v) for k, v in raw.items()}

    # ───────────── 可视化 ─────────────

    def build_continent_color_map(
        self,
        province_map: np.ndarray,
        tile_map: np.ndarray,
        state_manager=None,
    ) -> np.ndarray:
        """生成大陆颜色图（用于显示）。

        规则:
        - 有指派的陆地省份 → 该大陆的专属颜色（鲜艳，按 continent index 确定性生成）
        - 未指派的陆地省份 → state 色去饱和变暗（看清 state 边界）, 没 state 就深灰
        - 海/湖省份 → 深蓝灰

        参数:
            province_map: (H, W) uint16 / uint32 省份 ID 图
            tile_map: (H, W) uint8 地块类型（区分陆/海/湖）
            state_manager: 可选, 用于给未指派省份上 state 色
        """
        from data.constants import TILE_LAND

        max_pid = int(province_map.max())
        # 初始: 全部设成海色
        lut = np.full((max_pid + 1, 3), (30, 40, 70), dtype=np.uint8)

        # 大陆颜色（确定性: 按 continent index 取固定色轮）
        cont_palette = _generate_continent_palette(len(self._names))

        # state 颜色（和 StateManager 同种子, 保证一致）
        state_colors: dict[int, tuple[int, int, int]] = {}
        if state_manager is not None:
            rng = np.random.RandomState(123)
            for sid in state_manager.states:
                state_colors[sid] = (
                    int(rng.randint(60, 220)),
                    int(rng.randint(60, 220)),
                    int(rng.randint(60, 220)),
                )

        # 识别每个省份的"主体类型": 用**多数决**而不是"有一个陆地像素就算陆地"
        # 后者会把沾了几个陆地像素的海洋省误判成陆地 → 渲染成灰色块
        h, w = province_map.shape
        land_mask_flat = (tile_map == TILE_LAND).ravel()
        pid_flat = province_map.ravel()
        land_count = np.bincount(pid_flat, weights=land_mask_flat, minlength=max_pid + 1)
        total_count = np.bincount(pid_flat, minlength=max_pid + 1)
        # 陆地像素占比 > 50% 才算陆地省; 纯海/湖/混合沾边 都视为海
        is_land = land_count * 2 > total_count

        # 填 LUT — 未显式指派的陆地省份默认属于 continent 0 (default_continent)
        # 与 get_province_continent 的语义一致；docstring 明确规定"默认指向 0"。
        for pid in range(1, max_pid + 1):
            if not is_land[pid]:
                continue
            ci = self._province_continent.get(pid, 0)
            if 0 <= ci < len(cont_palette):
                lut[pid] = cont_palette[ci]
            else:
                # 索引越界（理论不应发生）: 灰色兜底
                lut[pid] = (70, 70, 70)

        flat_clipped = np.clip(pid_flat, 0, max_pid)
        rgb = lut[flat_clipped].reshape(h, w, 3)
        return rgb


def _generate_continent_palette(n: int) -> list[tuple[int, int, int]]:
    """为 n 个大陆生成确定性的鲜艳色轮。"""
    # 手选前几个大陆用 vanilla 感知友好的饱和色, 后面用 HSV 均分
    preset = [
        (90, 160, 220),   # 欧洲风 蓝
        (220, 180, 110),  # 北美 沙金
        (180, 210, 120),  # 南美 黄绿
        (200, 140, 200),  # 澳洲 紫粉
        (200, 120, 100),  # 非洲 橙红
        (110, 200, 180),  # 亚洲 青
    ]
    if n <= len(preset):
        return preset[:n]
    # 多于 6 个: 延续色轮
    import colorsys
    out = list(preset)
    extra = n - len(preset)
    for i in range(extra):
        h = (i / extra) * 0.83 + 0.08  # 避开已用的蓝色范围
        r, g, b = colorsys.hsv_to_rgb(h, 0.55, 0.85)
        out.append((int(r * 255), int(g * 255), int(b * 255)))
    return out
