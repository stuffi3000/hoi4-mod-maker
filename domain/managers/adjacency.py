"""Adjacency manager — special connections between provinces.

HOI4 uses map/adjacencies.csv to define three relationships:
- sea: strait/canal (two provinces are connected across the sea)
- impassable: impassable (blocking directly adjacent borders)
- (unspecified type): default sea

Reference: Reference/Map modding.txt lines 485-502

10 fields per line:
Start;End;Type;Through;start_x;start_y;stop_x;stop_y;rule;Comment

There must be a sentinel line at the end: -1;-1;-1;-1;-1;-1;-1;-1;-1;-1 (line 502)"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


AdjacencyType = Literal["sea", "impassable"]


@dataclass
class AdjacencyEntry:
    """An adjacency relationship."""
    from_id: int
    to_id: int
    type: AdjacencyType = "sea"
    through_id: int = -1  # Only used for sea type, impassable remains -1
    start_x: int = -1
    start_y: int = -1
    stop_x: int = -1
    stop_y: int = -1
    rule_name: str = ""  # rule name defined in adjacency_rules.txt, empty = no rule
    comment: str = ""

    def to_csv_line(self) -> str:
        """Serialize to CSV rows (10 fields, ; separated).

        Note: impassable types must have rule/coordinates set to -1 (line 497)."""
        if self.type == "impassable":
            return (
                f"{self.from_id};{self.to_id};impassable;-1;"
                f"-1;-1;-1;-1;;{self.comment}"
            )
        return (
            f"{self.from_id};{self.to_id};{self.type};{self.through_id};"
            f"{self.start_x};{self.start_y};{self.stop_x};{self.stop_y};"
            f"{self.rule_name};{self.comment}"
        )


class AdjacencyManager:
    """Manage all adjacency entries. Press (from,to) to remove duplicates."""

    def __init__(self) -> None:
        self._entries: list[AdjacencyEntry] = []

    # ─────────── CRUD ───────────

    def add(self, entry: AdjacencyEntry) -> None:
        """Added. Repeating (from,to,type) will overwrite the old one."""
        self.remove(entry.from_id, entry.to_id, entry.type)
        self._entries.append(entry)

    def remove(self, from_id: int, to_id: int, type: AdjacencyType | None = None) -> bool:
        """Delete the specified entry. type=None means to delete all matching (from,to). Returns whether to delete it."""
        before = len(self._entries)
        if type is None:
            self._entries = [
                e for e in self._entries
                if not ((e.from_id == from_id and e.to_id == to_id)
                        or (e.from_id == to_id and e.to_id == from_id))
            ]
        else:
            self._entries = [
                e for e in self._entries
                if not ((e.from_id == from_id and e.to_id == to_id and e.type == type)
                        or (e.from_id == to_id and e.to_id == from_id and e.type == type))
            ]
        return len(self._entries) < before

    def get_all(self) -> list[AdjacencyEntry]:
        return list(self._entries)

    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries = []

    def find_by_province(self, province_id: int) -> list[AdjacencyEntry]:
        """Returns all adjacencies involving the specified province (regardless of origin and destination)."""
        return [
            e for e in self._entries
            if e.from_id == province_id or e.to_id == province_id
        ]

    # ─────────── Data synchronization (for compact_with_references) ───────────

    def drop_provinces(self, pids: set[int]) -> None:
        """Remove adjacency that references the deleted province."""
        self._entries = [
            e for e in self._entries
            if e.from_id not in pids
               and e.to_id not in pids
               and e.through_id not in pids
        ]

    def remap_provinces(self, old_to_new: dict[int, int]) -> None:
        """Rewrite by old→new ID mapping."""
        new_entries: list[AdjacencyEntry] = []
        for e in self._entries:
            new_from = old_to_new.get(e.from_id)
            new_to = old_to_new.get(e.to_id)
            if new_from is None or new_to is None:
                continue  # If either end is deleted, discard it.
            new_through = old_to_new.get(e.through_id, e.through_id) if e.through_id >= 0 else -1
            new_entries.append(
                AdjacencyEntry(
                    from_id=new_from,
                    to_id=new_to,
                    type=e.type,
                    through_id=new_through,
                    start_x=e.start_x, start_y=e.start_y,
                    stop_x=e.stop_x, stop_y=e.stop_y,
                    rule_name=e.rule_name,
                    comment=e.comment,
                )
            )
        self._entries = new_entries

    # ─────────── Serialization ───────────

    def to_dict(self) -> dict:
        return {
            "entries": [
                {
                    "from_id": e.from_id,
                    "to_id": e.to_id,
                    "type": e.type,
                    "through_id": e.through_id,
                    "start_x": e.start_x,
                    "start_y": e.start_y,
                    "stop_x": e.stop_x,
                    "stop_y": e.stop_y,
                    "rule_name": e.rule_name,
                    "comment": e.comment,
                }
                for e in self._entries
            ]
        }

    def from_dict(self, data: dict) -> None:
        self._entries = []
        for d in data.get("entries", []):
            self._entries.append(
                AdjacencyEntry(
                    from_id=int(d["from_id"]),
                    to_id=int(d["to_id"]),
                    type=d.get("type", "sea"),
                    through_id=int(d.get("through_id", -1)),
                    start_x=int(d.get("start_x", -1)),
                    start_y=int(d.get("start_y", -1)),
                    stop_x=int(d.get("stop_x", -1)),
                    stop_y=int(d.get("stop_y", -1)),
                    rule_name=d.get("rule_name", ""),
                    comment=d.get("comment", ""),
                )
            )
