"""Railway Manager — Railway line data.

HOI4 uses map/railways.txt to define initial railways.
Reference: Reference/Map modding.txt lines 534-540

Format per line (space separated, no semicolon):
Level Amount_of_provinces List_of_provinces

Example:
4 4 693 1444 12 11 # level 4, 4 provinces, passing through 693/1444/12/11 in sequence

Level capped at 5 (default, see NDefines.NSupply.MAX_RAILWAY_LEVEL).
Invalid definitions will cause HOI4 to crash:
- Pass through a non-existent province
- Pass through stateless provinces
- Definition of severe discontinuity"""

from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np


@dataclass
class RailwayEntry:
    """a railway."""
    level: int  # 1-5
    province_ids: list[int] = field(default_factory=list)
    # Province clicks are stored as a temporary, single-province selection
    # until an adjacent clicked province completes a link.  Keep this marker
    # separate from the province IDs so validators can distinguish that editor
    # state from an authored self-loop, which is invalid in HOI4 data.
    brush_placeholder: bool = False

    def to_line(self) -> str:
        """Serialized to railways.txt one line."""
        ids_str = " ".join(str(p) for p in self.province_ids)
        return f"{self.level} {len(self.province_ids)} {ids_str}"


def adjacent_railway_segments(
    levels: dict[int, int],
    province_map: np.ndarray,
) -> list[tuple[int, int, int]]:
    """Return deterministic ``(level, first_pid, second_pid)`` map links.

    The province brush represents a railway as a level on each selected
    province.  This helper turns touching selected provinces into the same
    pairwise links used by the export writer and the live logistics overlay.
    It intentionally uses raster adjacency only; special sea adjacencies are
    edited separately.
    """
    if not levels:
        return []
    try:
        pm = np.asarray(province_map)
    except Exception:
        return []
    if pm.ndim != 2 or pm.size == 0:
        return []

    pairs: set[tuple[int, int]] = set()
    for first_array, second_array in (
        (pm[:-1, :], pm[1:, :]),
        (pm[:, :-1], pm[:, 1:]),
    ):
        mask = (first_array != second_array) & (first_array > 0) & (second_array > 0)
        ys, xs = np.where(mask)
        for y, x in zip(ys.tolist(), xs.tolist()):
            first = int(first_array[y, x])
            second = int(second_array[y, x])
            if first in levels and second in levels:
                pairs.add((min(first, second), max(first, second)))

    return [
        (min(int(levels[first]), int(levels[second])), first, second)
        for first, second in sorted(pairs)
    ]


class RailwayManager:
    """Manage all rail lines. Stored in sequence, allowing duplicate routes."""

    MAX_LEVEL = 5

    def __init__(self) -> None:
        self._entries: list[RailwayEntry] = []

    # ─────────── CRUD ───────────

    def add(self, level: int, province_ids: list[int]) -> int:
        """Add a railway, return index."""
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
        """Returns the index of all railways passing through the specified province."""
        return [
            i for i, e in enumerate(self._entries)
            if province_id in e.province_ids
        ]

    # ─────────── Data synchronization ───────────

    def drop_provinces(self, pids: set[int]) -> None:
        """Removed railways that referenced the deleted province (discarded in their entirety)."""
        self._entries = [
            e for e in self._entries
            if not any(p in pids for p in e.province_ids)
        ]

    def remap_provinces(self, old_to_new: dict[int, int]) -> None:
        """Rewrite according to the old → new ID mapping. If a new ID cannot be found in any province, the entire entry will be discarded."""
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
                new_entries.append(RailwayEntry(
                    level=e.level,
                    province_ids=new_ids,
                    brush_placeholder=bool(e.brush_placeholder),
                ))
        self._entries = new_entries

    # ─────────── Province level query/coloring ───────────

    def province_levels(self) -> dict[int, int]:
        """Maximum rail grade for each province."""
        levels: dict[int, int] = {}
        for e in self._entries:
            for pid in e.province_ids:
                levels[pid] = max(levels.get(pid, 0), e.level)
        return levels

    def set_province_level(self, pid: int, level: int) -> None:
        """Set provincial railway level (0=delete). Updated all rail links passing through the province."""
        if level == 0:
            # Remove this province from all railroads
            for e in self._entries:
                if pid in e.province_ids:
                    e.province_ids.remove(pid)
            # clear empty railway
            self._entries = [e for e in self._entries if len(e.province_ids) >= 2]
        else:
            found = False
            for e in self._entries:
                if pid in e.province_ids:
                    e.level = max(e.level, level)
                    found = True
            if not found:
                # Create a new single province placeholder (will be merged with neighbors when exported)
                self._entries.append(
                    RailwayEntry(
                        level=level,
                        province_ids=[pid, pid],
                        brush_placeholder=True,
                    )
                )

    def build_railway_color_map(self, province_map: np.ndarray) -> np.ndarray:
        """Generates a railway shading map (H, W, 3). Level 0=grey, 1=light gray, 5=red."""
        # Grade color (RGB)
        LEVEL_COLORS = {
            0: (50, 50, 50),      # No rails - dark gray
            1: (100, 100, 120),   # gray blue
            2: (80, 140, 80),     # green
            3: (200, 170, 50),    # golden
            4: (210, 120, 50),    # Orange
            5: (210, 50, 50),     # red
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

    # ─────────── Serialization ───────────

    def to_dict(self) -> dict:
        return {
            "entries": [
                {
                    "level": e.level,
                    "province_ids": list(e.province_ids),
                    **({"brush_placeholder": True} if e.brush_placeholder else {}),
                }
                for e in self._entries
            ]
        }

    def from_dict(self, data: dict) -> None:
        self._entries = []
        for d in data.get("entries", []):
            province_ids = [int(p) for p in d.get("province_ids", [])]
            self._entries.append(
                RailwayEntry(
                    level=int(d["level"]),
                    province_ids=province_ids,
                    # Projects saved before the marker was introduced used
                    # [pid, pid] for the same brush state.  Migrate that
                    # representation while leaving manually-authored entries
                    # created in memory distinguishable for validation.
                    brush_placeholder=bool(
                        d.get(
                            "brush_placeholder",
                            len(province_ids) == 2
                            and province_ids[0] == province_ids[1],
                        )
                    ),
                )
            )
