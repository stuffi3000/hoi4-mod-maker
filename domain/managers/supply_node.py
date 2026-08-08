"""
SupplyNode 管理器 — 初始补给节点.

HOI4 用 map/supply_nodes.txt 定义玩家/AI 的起始 supply node.
参考: 参考/Map modding.txt 行 528-532

每行格式 (空格分隔, 无分号):
Level Province

Level 默认上限 1, 很少用其他值.
示例:
1 1234

无效定义 (不存在的省份 / stateless 省份) 会崩.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SupplyNode:
    province_id: int
    level: int = 1

    def to_line(self) -> str:
        return f"{self.level} {self.province_id}"


class SupplyNodeManager:
    """管理所有 supply nodes. 按 province_id 去重."""

    def __init__(self) -> None:
        self._nodes: dict[int, SupplyNode] = {}

    def add(self, province_id: int, level: int = 1) -> None:
        """添加或更新一个 supply node."""
        if level < 1:
            raise ValueError(f"level must be at least 1; received {level}")
        self._nodes[province_id] = SupplyNode(province_id=province_id, level=level)

    def remove(self, province_id: int) -> bool:
        """删除指定省份的 supply node. 返回是否删掉."""
        if province_id in self._nodes:
            del self._nodes[province_id]
            return True
        return False

    def toggle(self, province_id: int, level: int = 1) -> bool:
        """切换 supply node. 存在则删, 不存在则加. 返回最终状态 (True = 存在)."""
        if province_id in self._nodes:
            del self._nodes[province_id]
            return False
        self._nodes[province_id] = SupplyNode(province_id=province_id, level=level)
        return True

    def contains(self, province_id: int) -> bool:
        return province_id in self._nodes

    def get_all(self) -> list[SupplyNode]:
        return list(self._nodes.values())

    def count(self) -> int:
        return len(self._nodes)

    def clear(self) -> None:
        self._nodes = {}

    # ─────────── 数据同步 ───────────

    def drop_provinces(self, pids: set[int]) -> None:
        for pid in pids:
            self._nodes.pop(pid, None)

    def remap_provinces(self, old_to_new: dict[int, int]) -> None:
        new_nodes: dict[int, SupplyNode] = {}
        for old_pid, node in self._nodes.items():
            new_pid = old_to_new.get(old_pid)
            if new_pid is not None:
                new_nodes[new_pid] = SupplyNode(province_id=new_pid, level=node.level)
        self._nodes = new_nodes

    # ─────────── 序列化 ───────────

    def to_dict(self) -> dict:
        return {
            "nodes": [
                {"province_id": n.province_id, "level": n.level}
                for n in self._nodes.values()
            ]
        }

    def from_dict(self, data: dict) -> None:
        self._nodes = {}
        for d in data.get("nodes", []):
            pid = int(d["province_id"])
            self._nodes[pid] = SupplyNode(province_id=pid, level=int(d.get("level", 1)))
