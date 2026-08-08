"""
Railway 管理器 — 铁路线数据.

HOI4 用 map/railways.txt 定义初始铁路.
参考: 参考/Map modding.txt 行 534-540

每行格式 (空格分隔, 无分号):
Level Amount_of_provinces List_of_provinces

示例:
4 4 693 1444 12 11   # level 4, 4 个省份, 依次经过 693/1444/12/11

Level 上限 5 (默认, 见 NDefines.NSupply.MAX_RAILWAY_LEVEL).
无效定义会导致 HOI4 崩溃:
- 经过不存在的省份
- 经过 stateless 省份
- 严重不连续的定义
"""

from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np


@dataclass
class RailwayEntry:
    """一条铁路."""
    level: int  # 1-5
    province_ids: list[int] = field(default_factory=list)

    def to_line(self) -> str:
        """序列化为 railways.txt 一行."""
        ids_str = " ".join(str(p) for p in self.province_ids)
        return f"{self.level} {len(self.province_ids)} {ids_str}"


class RailwayManager:
    """管理所有铁路线. 按顺序存储, 允许重复路径."""

    MAX_LEVEL = 5

    def __init__(self) -> None:
        self._entries: list[RailwayEntry] = []

    # ─────────── CRUD ───────────

    def add(self, level: int, province_ids: list[int]) -> int:
        """添加一条铁路, 返回索引."""
        if not (1 <= level <= self.MAX_LEVEL):
            raise ValueError(f"level must be between 1 and {self.MAX_LEVEL}; received {level}")
        if len(province_ids) < 2:
            raise ValueError(f"A railway must pass through at least 2 provinces; received {len(province_ids)}")
        self._entries.append(RailwayEntry(level=level, province_ids=list(province_ids)))
        return len(self._entries) - 1

    def remove_at(self, index: int) -> bool:
        if 0 <= index < len(self._entries):
            self._entries.pop(index)
            return True
        return False

    def update_level(self, index: int, level: int) -> None:
        if not (1 <= level <= self.MAX_LEVEL):
            raise ValueError(f"level must be between 1 and {self.MAX_LEVEL}")
        if 0 <= index < len(self._entries):
            self._entries[index].level = level

    def get_all(self) -> list[RailwayEntry]:
        return list(self._entries)

    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries = []

    def find_by_province(self, province_id: int) -> list[int]:
        """返回所有经过指定省份的铁路索引."""
        return [
            i for i, e in enumerate(self._entries)
            if province_id in e.province_ids
        ]

    # ─────────── 数据同步 ───────────

    def drop_provinces(self, pids: set[int]) -> None:
        """删除引用了被删省份的铁路 (整条丢弃)."""
        self._entries = [
            e for e in self._entries
            if not any(p in pids for p in e.province_ids)
        ]

    def remap_provinces(self, old_to_new: dict[int, int]) -> None:
        """按旧→新 ID 映射重写. 任一省份找不到新 ID 就丢弃整条."""
        new_entries: list[RailwayEntry] = []
        for e in self._entries:
            new_ids = []
            broken = False
            for p in e.province_ids:
                new_p = old_to_new.get(p)
                if new_p is None:
                    broken = True
                    break
                new_ids.append(new_p)
            if not broken and len(new_ids) >= 2:
                new_entries.append(RailwayEntry(level=e.level, province_ids=new_ids))
        self._entries = new_entries

    # ─────────── 省份级别查询/着色 ───────────

    def province_levels(self) -> dict[int, int]:
        """每个省份的最大铁路等级。"""
        levels: dict[int, int] = {}
        for e in self._entries:
            for pid in e.province_ids:
                levels[pid] = max(levels.get(pid, 0), e.level)
        return levels

    def set_province_level(self, pid: int, level: int) -> None:
        """设置省份铁路等级（0=删除）。更新所有经过该省份的铁路链。"""
        if level == 0:
            # 从所有铁路中移除该省份
            for e in self._entries:
                if pid in e.province_ids:
                    e.province_ids.remove(pid)
            # 清理空铁路
            self._entries = [e for e in self._entries if len(e.province_ids) >= 2]
        else:
            found = False
            for e in self._entries:
                if pid in e.province_ids:
                    e.level = max(e.level, level)
                    found = True
            if not found:
                # 新建单省份占位（导出时会和邻居合并）
                self._entries.append(RailwayEntry(level=level, province_ids=[pid, pid]))

    def build_railway_color_map(self, province_map: np.ndarray) -> np.ndarray:
        """生成铁路着色图 (H, W, 3)。等级 0=灰, 1=浅灰, 5=红。"""
        # 等级颜色 (RGB)
        LEVEL_COLORS = {
            0: (50, 50, 50),      # 无铁路 — 深灰
            1: (100, 100, 120),   # 灰蓝
            2: (80, 140, 80),     # 绿
            3: (200, 170, 50),    # 金黄
            4: (210, 120, 50),    # 橙
            5: (210, 50, 50),     # 红
        }
        max_pid = int(province_map.max())
        lut = np.full((max_pid + 1, 3), 50, dtype=np.uint8)

        levels = self.province_levels()
        for pid, lvl in levels.items():
            if 0 < pid <= max_pid:
                r, g, b = LEVEL_COLORS.get(lvl, LEVEL_COLORS[0])
                lut[pid] = (r, g, b)

        flat = np.clip(province_map.ravel(), 0, max_pid)
        return lut[flat].reshape(province_map.shape[0], province_map.shape[1], 3)

    # ─────────── 序列化 ───────────

    def to_dict(self) -> dict:
        return {
            "entries": [
                {"level": e.level, "province_ids": list(e.province_ids)}
                for e in self._entries
            ]
        }

    def from_dict(self, data: dict) -> None:
        self._entries = []
        for d in data.get("entries", []):
            self._entries.append(
                RailwayEntry(
                    level=int(d["level"]),
                    province_ids=[int(p) for p in d.get("province_ids", [])],
                )
            )
