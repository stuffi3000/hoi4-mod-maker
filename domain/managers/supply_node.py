"""SupplyNode manager — initial supply node.

HOI4 uses map/supply_nodes.txt to define the starting supply node of the player/AI.
Reference: Reference/Map modding.txt lines 528-532

Format per line (space separated, no semicolon):
Level Province

Level has a default upper limit of 1, other values are rarely used.
Example:
1 1234

Invalid definitions (non-existent provinces / stateless provinces) will crash."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SupplyNode:
    province_id: int
    level: int = 1

    def to_line(self) -> str:
        return f"{self.level} {self.province_id}"


class SupplyNodeManager:
    """Manage all supply nodes. Remove duplicates by province_id."""

    def __init__(self) -> None:
        self._nodes: dict[int, SupplyNode] = {}

    def add(self, province_id: int, level: int = 1) -> None:
        """Add or update a supply node."""
        if level < 1:
            raise ValueError(f"level must be at least 1; received {level}")
        self._nodes[province_id] = SupplyNode(province_id=province_id, level=level)

    def remove(self, province_id: int) -> bool:
        """Delete the supply node of the specified province. Returns whether to delete it."""
        if province_id in self._nodes:
            del self._nodes[province_id]
            return True
        return False

    def toggle(self, province_id: int, level: int = 1) -> bool:
        """Switch the supply node. If it exists, delete it, if it does not exist, add it. Return the final state (True = exists)."""
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

    # ─────────── Data synchronization ───────────

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

    # ─────────── Serialization ───────────

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
