"""Continent Manager — Continent data structures, province assignments, exports

HOI4 rules (Map modding §Continents):
- continent.txt lists all continent names
- The last column continent in definition.csv is an integer index (1-based)
- sea/lake province continent = 0
- All land provinces must belong to a certain continent, otherwise an error will be reported

Default: a continent "default_continent" to which all land provinces belong.
Users can add/rename/delete continents in the UI, and assign provinces to specified continents."""

from __future__ import annotations

import numpy as np


class ContinentManager:
    """Manage continent list + province → continent map"""

    DEFAULT_NAME = "default_continent"

    def __init__(self) -> None:
        # List of continent names, index starts from 0; HOI4 continent ID = index + 1
        self._names: list[str] = [self.DEFAULT_NAME]
        # province → continent index (0-based); land provinces not in this dict default to 0
        self._province_continent: dict[int, int] = {}

    # ───────────── Mainland CRUD ─────────────

    @property
    def names(self) -> list[str]:
        """Return the list of continent names (the order is HOI4 ID order, 1-based)"""
        return list(self._names)

    def count(self) -> int:
        return len(self._names)

    def get_name(self, index: int) -> str:
        """Name according to 0-based index, return to default if out of bounds"""
        if 0 <= index < len(self._names):
            return self._names[index]
        return self.DEFAULT_NAME

    def add_continent(self, name: str) -> int:
        """Add a continent and return its 0-based index. If the name is the same, return the existing index."""
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
        """Delete continent. Must keep at least 1. Provinces pointing to this continent point to 0 instead."""
        if len(self._names) <= 1:
            raise ValueError("At least one continent must remain")
        if not (0 <= index < len(self._names)):
            raise IndexError(f"Continent index out of range: {index}")
        self._names.pop(index)
        # Remap provinces: deleted → 0, later → moved forward 1
        new_map: dict[int, int] = {}
        for pid, ci in self._province_continent.items():
            if ci == index:
                new_map[pid] = 0
            elif ci > index:
                new_map[pid] = ci - 1
            else:
                new_map[pid] = ci
        self._province_continent = new_map

    # ──────────── Provincial assignment ─────────────

    def assign_province(self, pid: int, continent_index: int) -> None:
        if not (0 <= continent_index < len(self._names)):
            raise IndexError(f"Continent index out of range: {continent_index}")
        self._province_continent[pid] = continent_index

    def assign_provinces(self, pids: list[int], continent_index: int) -> None:
        for pid in pids:
            self.assign_province(pid, continent_index)

    def get_province_continent(self, pid: int) -> int:
        """Returns the 0-based continent index of the province, or 0 if not assigned"""
        return self._province_continent.get(pid, 0)

    def get_province_continent_hoi4_id(self, pid: int, is_land: bool) -> int:
        """Returns HOI4 continent ID (1-based). Sea/Lake returns 0."""
        if not is_land:
            return 0
        return self.get_province_continent(pid) + 1

    # ───────────── Data synchronization ──────────────

    def drop_provinces(self, pids: set[int]) -> None:
        """Delete a batch of province assignments (called by compact_with_references)"""
        for pid in pids:
            self._province_continent.pop(pid, None)

    def remap_provinces(self, old_to_new: dict[int, int]) -> None:
        """Rewrite according to old→new ID mapping (called for ID compaction)"""
        new_map: dict[int, int] = {}
        for old_pid, ci in self._province_continent.items():
            new_pid = old_to_new.get(old_pid)
            if new_pid is not None:
                new_map[new_pid] = ci
        self._province_continent = new_map

    def clear(self) -> None:
        self._names = [self.DEFAULT_NAME]
        self._province_continent = {}

    # ───────────── Serialization ─────────────

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
        # JSON will convert int key to str, which is compatible here
        self._province_continent = {int(k): int(v) for k, v in raw.items()}

    # ───────────── Visualization ─────────────

    def build_continent_color_map(
        self,
        province_map: np.ndarray,
        tile_map: np.ndarray,
        state_manager=None,
    ) -> np.ndarray:
        """Generate continent color map (for display).

        Rules:
        - Assigned land provinces → exclusive colors for the continent (bright, deterministically generated according to continent index)
        - Unassigned land provinces → The state color is desaturated and darkened (to see the state boundary clearly), without state it is dark gray
        - Sea/Lake provinces → dark blue gray

        Parameters:
            province_map: (H, W) uint16 / uint32 province ID map
            tile_map: (H, W) uint8 tile type (differentiate between land/sea/lake)
            state_manager: optional, used to add state color to unassigned provinces"""
        from data.constants import TILE_LAND

        max_pid = int(province_map.max())
        # Initial: Set all to sea color
        lut = np.full((max_pid + 1, 3), (30, 40, 70), dtype=np.uint8)

        # Continent color (deterministic: take the fixed color wheel according to continent index)
        cont_palette = _generate_continent_palette(len(self._names))

        # state color (same seed as StateManager, guaranteed to be consistent)
        state_colors: dict[int, tuple[int, int, int]] = {}
        if state_manager is not None:
            rng = np.random.RandomState(123)
            for sid in state_manager.states:
                state_colors[sid] = (
                    int(rng.randint(60, 220)),
                    int(rng.randint(60, 220)),
                    int(rng.randint(60, 220)),
                )

        # Identify the "subject type" of each province: use majority rule instead of "one land pixel counts as land"
        # The latter will misjudge an ocean province with a few land pixels as land → render it as a gray block
        h, w = province_map.shape
        land_mask_flat = (tile_map == TILE_LAND).ravel()
        pid_flat = province_map.ravel()
        land_count = np.bincount(pid_flat, weights=land_mask_flat, minlength=max_pid + 1)
        total_count = np.bincount(pid_flat, minlength=max_pid + 1)
        # Land pixels account for >50% to be considered a land province; pure sea/lake/mixed areas are considered sea
        is_land = land_count * 2 > total_count

        # Fill LUT — Continental provinces not explicitly assigned default to continent 0 (default_continent)
        # Consistent with the semantics of get_province_continent; the docstring clearly states "default points to 0".
        for pid in range(1, max_pid + 1):
            if not is_land[pid]:
                continue
            ci = self._province_continent.get(pid, 0)
            if 0 <= ci < len(cont_palette):
                lut[pid] = cont_palette[ci]
            else:
                # Index out of bounds (theoretically should not happen): gray cover
                lut[pid] = (70, 70, 70)

        flat_clipped = np.clip(pid_flat, 0, max_pid)
        rgb = lut[flat_clipped].reshape(h, w, 3)
        return rgb


def _generate_continent_palette(n: int) -> list[tuple[int, int, int]]:
    """Generate a deterministic vivid color wheel for n continents."""
    # Hand-select the first few continents using vanilla perception-friendly saturated colors, and use HSV to divide them evenly.
    preset = [
        (90, 160, 220),   # European style blue
        (220, 180, 110),  # North America Alluvial Gold
        (180, 210, 120),  # south america yellow green
        (200, 140, 200),  # Australia Purple Pink
        (200, 120, 100),  # africa orange red
        (110, 200, 180),  # asian green
    ]
    if n <= len(preset):
        return preset[:n]
    # More than 6: Continue color wheel
    import colorsys
    out = list(preset)
    extra = n - len(preset)
    for i in range(extra):
        h = (i / extra) * 0.83 + 0.08  # Avoid used blue range
        r, g, b = colorsys.hsv_to_rgb(h, 0.55, 0.85)
        out.append((int(r * 255), int(g * 255), int(b * 255)))
    return out
