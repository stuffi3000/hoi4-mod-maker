"""MapData — Map data center.

Put all numpy layers (tile_map / province_map / terrain_map / height_map / river_map)
Concentrated into one object to provide advanced query and modification methods.

Design principles:
1. **Direct array access still works**: MapData.tile_map returns numpy array, the old code does not need to be changed
2. **Advanced methods as a supplement**: get_neighbors / get_province_mask, etc. to avoid repeated implementation in multiple places
3. **Does not hold UI reference**: MapData is a pure data layer and does not know the existence of canvas/widget
4. **No undoing/rendering**: That is the responsibility of the upper layer

Migration strategy:
- The first step: MapData exists as a container, canvas/main_window is accessed through canvas.map_data.tile_map
- Step 2: Gradually migrate scattered auxiliary functions (get_neighbors, etc.)
- Step 3: High-frequency reading and writing of MapData methods to facilitate adding hooks in the future"""

from __future__ import annotations

import numpy as np

from data.constants import MAP_WIDTH, MAP_HEIGHT, TILE_LAND, TILE_SEA, TILE_LAKE


class MapData:
    """All map layers + advanced query interface."""

    def __init__(self) -> None:
        # Read the current size at runtime (set_map_size may have been modified)
        import data.constants as _c
        h, w = _c.MAP_HEIGHT, _c.MAP_WIDTH
        self.tile_map = np.full((h, w), TILE_SEA, dtype=np.uint8)
        self.province_map = np.zeros((h, w), dtype=np.int32)
        self.terrain_map = np.zeros((h, w), dtype=np.uint8)
        self.height_map = np.full((h, w), 40, dtype=np.uint8)
        self.river_map = np.full((h, w), 255, dtype=np.uint8)  # 255=white background, 0=source!
        self.density_map: np.ndarray | None = None  # (H,W) float32 0~1, None=uniform
        # A snapshot of the tile_map when the province was generated, used to detect "newly drawn land"
        self.tile_snapshot: np.ndarray | None = None
        # Province-level terrain: province_id → terrain type string
        # Independent of terrain_map (graphical terrain), combat attributes for definition.csv
        self.provincial_terrain: dict[int, str] = {}

    # ───────────── Reset/Replace ─────────────

    def reset(self) -> None:
        """All layers are restored to their original state."""
        self.tile_map[:] = TILE_SEA
        self.province_map[:] = 0
        self.terrain_map[:] = 0
        self.height_map[:] = 40
        self.river_map[:] = 255  # white background
        self.density_map = None
        self.tile_snapshot = None
        self.provincial_terrain.clear()

    def replace_all(
        self,
        tile_map: np.ndarray | None = None,
        province_map: np.ndarray | None = None,
        terrain_map: np.ndarray | None = None,
        height_map: np.ndarray | None = None,
        river_map: np.ndarray | None = None,
    ) -> None:
        """Batch replace layers from external data (used when loading a project). Write in place to keep references stable."""
        if tile_map is not None:
            self.tile_map[:] = tile_map
        if province_map is not None:
            self.province_map[:] = province_map
        if terrain_map is not None:
            self.terrain_map[:] = terrain_map
        if height_map is not None:
            self.height_map[:] = height_map
        if river_map is not None:
            self.river_map[:] = river_map

    # ───────────── Dictionary interface (for undo/serialize) ─────────────

    def as_dict(self) -> dict[str, np.ndarray]:
        return {
            "tile_map": self.tile_map,
            "province_map": self.province_map,
            "terrain_map": self.terrain_map,
            "height_map": self.height_map,
            "river_map": self.river_map,
        }

    def apply_dict(self, data: dict[str, np.ndarray]) -> None:
        """Restore from dictionary (used when undoing). Write in place to keep references."""
        for k, v in data.items():
            arr = getattr(self, k, None)
            if arr is not None and v is not None:
                arr[:] = v

    # ───────────── Province query ─────────────

    @property
    def province_count(self) -> int:
        return int(self.province_map.max())

    def get_province_mask(self, pid: int) -> np.ndarray:
        """Returns a Boolean mask, where True is the pixel of this province."""
        return self.province_map == pid

    def get_province_pixel_count(self, pid: int) -> int:
        return int((self.province_map == pid).sum())

    def get_province_bbox(self, pid: int) -> tuple[int, int, int, int] | None:
        """Returns (x_min, y_min, x_max, y_max), returns None if the province does not exist."""
        ys, xs = np.where(self.province_map == pid)
        if len(ys) == 0:
            return None
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

    def get_province_centroid(self, pid: int) -> tuple[int, int] | None:
        """Returns the province center of gravity (x, y), returns None if it does not exist. Use cache first."""
        cache = getattr(self, '_centroid_cache', None)
        if cache is not None and pid in cache:
            return cache[pid]
        ys, xs = np.where(self.province_map == pid)
        if len(ys) == 0:
            return None
        result = (int(xs.mean()), int(ys.mean()))
        if cache is not None:
            cache[pid] = result
        return result

    def build_centroid_cache(self) -> None:
        """Calculate the centroids of all provinces at once, O(number of pixels) instead of O(number of provinces × number of pixels)."""
        pm = self.province_map
        max_pid = int(pm.max())
        if max_pid <= 0:
            self._centroid_cache = {}
            return
        h, w = pm.shape
        flat = pm.ravel()
        ys, xs = np.mgrid[0:h, 0:w]
        count = np.bincount(flat, minlength=max_pid + 1)
        sum_x = np.bincount(flat, weights=xs.ravel().astype(np.float64), minlength=max_pid + 1)
        sum_y = np.bincount(flat, weights=ys.ravel().astype(np.float64), minlength=max_pid + 1)
        cache: dict[int, tuple[int, int]] = {}
        for pid in range(1, max_pid + 1):
            if count[pid] > 0:
                cache[pid] = (int(sum_x[pid] / count[pid]), int(sum_y[pid] / count[pid]))
        self._centroid_cache = cache

    def invalidate_centroid_cache(self) -> None:
        """Clear cache after province change."""
        self._centroid_cache = None

    def get_province_tile_type(self, pid: int) -> int:
        """Returns the province's land type (land/sea/lake).
        Implementation: Get the tile_map value of any pixel in the province."""
        ys, xs = np.where(self.province_map == pid)
        if len(ys) == 0:
            return 0
        return int(self.tile_map[ys[0], xs[0]])

    def get_province_neighbors(self, pid: int) -> set[int]:
        """Returns the set of all direct neighbor IDs for province pid.
        Detection with 4-adjacency expansion. Consider horizontal wrap."""
        from scipy.ndimage import binary_dilation
        if pid <= 0:
            return set()
        mask = self.province_map == pid
        if not mask.any():
            return set()
        # 4 connected dilation 1 pixel
        struct = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
        dilated = binary_dilation(mask, structure=struct)
        # Horizontal wrap: consider the right edge and the left edge together
        # Simplified processing: directly perform union on border neighbors (in rare cases, the function will not be affected)
        border = dilated & ~mask
        neighbor_ids = set(int(x) for x in np.unique(self.province_map[border]))
        neighbor_ids.discard(0)
        neighbor_ids.discard(pid)
        return neighbor_ids

    def get_neighborhood_mask(self, pid: int) -> np.ndarray:
        """Returns pid self + the combined mask of all direct neighbors.
        For lasso/boundary editing - limit the maximum range of the operation."""
        neighbors = self.get_province_neighbors(pid)
        mask = self.province_map == pid
        for nid in neighbors:
            mask |= self.province_map == nid
        return mask

    # ───────────── Land statistics ─────────────

    def compact_with_references(
        self,
        state_mgr=None,
        country_mgr=None,
        strategic_region_mgr=None,
        tracked_pids: list[int] | None = None,
        continent_mgr=None,
        adjacency_mgr=None,
        railway_mgr=None,
        supply_mgr=None,
        adjacency_rule_mgr=None,
    ) -> dict[int, int]:
        """Compact the ID of province_map and update all places referencing the province ID simultaneously.

        This is the "safe end" of modifying provinces - any operation that would delete provinces (merge/expand eat up neighbors)
        This must be adjusted after completion to avoid the attribute string bit disaster caused by ID gap and HOI4 document warning.

        self.provincial_terrain (provincial terrain, keyed by pid) will also be remapped synchronously.

        Parameters:
            state_mgr: StateManager — update state.provinces / victory_points / province_to_state
            country_mgr: CountryManager — updates country.capital
            strategic_region_mgr: StrategicRegionManager — update region.province_ids
            tracked_pids: List of additional pids that the caller wants to track (such as selected provinces)
            continent_mgr: ContinentManager — Update province → continent assignment
            adjacency_mgr: AdjacencyManager — Update adjacency from/to/through
            railway_mgr: RailwayManager — Update the provinces that the railway passes through
            supply_mgr: SupplyNodeManager — Update supply node province
            adjacency_rule_mgr: AdjacencyRuleManager — Update the required/icon province of the rule

        Return:
            {old_id: new_id} mapping, which the caller uses to update the pid reference it holds"""
        from domain.generators.province import compact_province_ids

        # List of old IDs before compaction
        old_unique = np.unique(self.province_map).tolist()

        # compaction
        compact_province_ids(self.province_map)

        # Compacted new ID list (the order corresponds to old_unique one-to-one)
        new_unique = np.unique(self.province_map).tolist()

        # Build mapping {old: new}
        if len(old_unique) != len(new_unique):
            # Should not happen (compact is a stable ordering)
            raise RuntimeError("compact_province_ids produced an inconsistent ID list")
        mapping = dict(zip(old_unique, new_unique))

        # Update state_mgr
        # Note: The deleted provinces (not in the mapping) must be completely discarded from the list/dict,
        # Dead references cannot be retained, otherwise state will point to a non-existent province
        if state_mgr is not None:
            for state in state_mgr.states.values():
                # Filter out dead references (deleted provinces) and remove duplicates at the same time
                seen = set()
                new_provinces = []
                for p in state.provinces:
                    if p in mapping and mapping[p] != 0 and mapping[p] not in seen:
                        seen.add(mapping[p])
                        new_provinces.append(mapping[p])
                state.provinces = new_provinces

                # VP Dictionary: Throw away dead quotes
                new_vp = {}
                for old_pid, value in state.victory_points.items():
                    if old_pid in mapping and mapping[old_pid] != 0:
                        new_vp[mapping[old_pid]] = value
                state.victory_points = new_vp

            # Rebuild province_to_state index
            new_p2s = {}
            for sid, state in state_mgr.states.items():
                for pid in state.provinces:
                    new_p2s[pid] = sid
            state_mgr._province_to_state = new_p2s

        # Update country_mgr
        if country_mgr is not None:
            for country in country_mgr.countries.values():
                if country.capital > 0:
                    if country.capital in mapping and mapping[country.capital] != 0:
                        country.capital = mapping[country.capital]
                    else:
                        # The capital has been deleted and cleared.
                        country.capital = 0

        # Update strategic_region_mgr
        if strategic_region_mgr is not None:
            for region in strategic_region_mgr._regions.values():
                seen = set()
                new_provs = []
                for p in region.province_ids:
                    if p in mapping and mapping[p] != 0 and mapping[p] not in seen:
                        seen.add(mapping[p])
                        new_provs.append(mapping[p])
                region.province_ids = new_provs

        # Update continent / adjacency / railway / supply / adjacency_rule
        # Their remap_provinces comes with dead reference cleanup: provinces not in the mapping are discarded.
        # Mapping may contain 0:0 (unallocated pixels), and the dirty data referencing No. 0 will also be cleared after culling.
        ref_mapping = {o: n for o, n in mapping.items() if o != 0}
        for mgr in (continent_mgr, adjacency_mgr, railway_mgr,
                    supply_mgr, adjacency_rule_mgr):
            if mgr is not None:
                mgr.remap_provinces(ref_mapping)

        # Province-level terrain (definition.csv combat attributes) is also keyed by pid
        if self.provincial_terrain:
            self.provincial_terrain = {
                mapping[pid]: t
                for pid, t in self.provincial_terrain.items()
                if mapping.get(pid, 0) != 0
            }

        return mapping

    def get_tile_counts(self) -> dict[str, int]:
        """Count the number of pixels on land/sea/lake."""
        return {
            "land": int((self.tile_map == TILE_LAND).sum()),
            "sea":  int((self.tile_map == TILE_SEA).sum()),
            "lake": int((self.tile_map == TILE_LAKE).sum()),
        }
