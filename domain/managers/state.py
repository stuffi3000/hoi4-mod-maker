"""State data structures, province assignments, and automatic state grouping."""
import numpy as np
from dataclasses import dataclass, field
from scipy.ndimage import label
from data.constants import MAP_WIDTH, MAP_HEIGHT, TILE_LAND


# These are the state-category identifiers shipped by current HOI4 versions.
# ``tiny`` and ``small`` were used by an older editor preset, but are not
# valid game identifiers (the corresponding vanilla categories are
# ``pastoral`` and ``rural``).  Keep aliases so existing projects load safely.
VALID_STATE_CATEGORIES = frozenset({
    "wasteland",
    "enclave",
    "tiny_island",
    "small_island",
    "large_island",
    "pastoral",
    "rural",
    "town",
    "large_town",
    "city",
    "large_city",
    "metropolis",
    "megalopolis",
})

STATE_CATEGORY_ALIASES = {
    "tiny": "pastoral",
    "small": "rural",
}


def normalize_state_category(category: str) -> str:
    """Return a vanilla state-category key suitable for a history file.

    Projects created by older releases may still contain the retired editor
    aliases ``tiny`` and ``small``.  Unknown values intentionally fall back
    to ``rural`` rather than producing an invalid ``state_category`` that
    leaves the game without building-slot data.
    """
    value = str(category or "").strip().lower()
    value = STATE_CATEGORY_ALIASES.get(value, value)
    return value if value in VALID_STATE_CATEGORIES else "rural"


@dataclass
class StateData:
    """Store the provinces, ownership, buildings, and other state-level data."""
    id: int
    name: str = ""                      # Primary display name; exported to English localization
    name_en: str = ""                   # Optional English name used by English localization export
    provinces: list[int] = field(default_factory=list)
    manpower: int = 100000
    category: str = "town"
    owner_tag: str = ""
    victory_points: dict[int, int] = field(default_factory=dict)  # {province_id: vp_value}
    vp_names: dict[int, str] = field(default_factory=dict)  # {province_id: primary city name}
    vp_names_en: dict[int, str] = field(default_factory=dict)  # {province_id: English city name}

    # Advanced state fields following HOI4 state-modding conventions.
    impassable: bool = False  # The state cannot receive units or buildings
    controller_tag: str = ""  # Initial controller when it differs from the owner
    local_supplies: float = 0.0  # Local supply modifier
    # State resources: oil, aluminium, rubber, tungsten, steel, and chromium.
    resources: dict[str, int] = field(default_factory=dict)
    # State-level buildings such as infrastructure, factories, and dockyards.
    # air_base/anti_air_building/radar_station/synthetic_refinery/fuel_silo/
    # nuclear_reactor/rocket_site/mass_transit/supply_node (zero values are omitted)
    buildings: dict[str, int] = field(default_factory=dict)
    # Province-level buildings stored as {province_id: {building_name: level}}.
    # Used for bunker, coastal_bunker, and naval_base entries.
    province_buildings: dict[int, dict[str, int]] = field(default_factory=dict)
    # Additional country tags that receive cores when the state is exported.
    extra_cores: list[str] = field(default_factory=list)
    # Country tags that receive claims on the state.
    claims: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.name:
            self.name = f"STATE_{self.id}"
        self.category = normalize_state_category(self.category)


class StateManager:
    """Manage state records and the reverse index from provinces to states."""

    # State-category options accepted by the editor and exporter.
    CATEGORIES = [
        "wasteland", "enclave", "tiny_island", "small_island",
        "large_island", "pastoral", "rural", "town", "large_town",
        "city", "large_city", "metropolis", "megalopolis",
    ]

    def __init__(self):
        self._states: dict[int, StateData] = {}
        self._province_to_state: dict[int, int] = {}  # pid → state_id
        self._next_id = 1

    @property
    def states(self) -> dict[int, StateData]:
        return self._states

    def get_state(self, state_id: int) -> StateData | None:
        return self._states.get(state_id)

    def get_state_of_province(self, pid: int) -> int:
        """Return the owning state ID, or zero when the province is unassigned."""
        return self._province_to_state.get(pid, 0)

    def create_state(self, provinces: list[int] | None = None) -> StateData:
        """Create a state and index each supplied province under its new ID."""
        sid = self._next_id
        self._next_id += 1
        state = StateData(id=sid, provinces=provinces or [])
        self._states[sid] = state
        for pid in state.provinces:
            self._province_to_state[pid] = sid
        return state

    def assign_province(self, pid: int, state_id: int) -> None:
        """Move a province from its current state into the requested state."""
        # Remove the province from its previous state first.
        old_sid = self._province_to_state.get(pid, 0)
        if old_sid > 0 and old_sid in self._states:
            provs = self._states[old_sid].provinces
            if pid in provs:
                provs.remove(pid)

        # Add the province to the new state and update the reverse index.
        if state_id in self._states:
            if pid not in self._states[state_id].provinces:
                self._states[state_id].provinces.append(pid)
            self._province_to_state[pid] = state_id

    def set_vp(self, province_id: int, value: int, name: str = "") -> None:
        """Set a province's victory-point value and optional city name."""
        sid = self._province_to_state.get(province_id, 0)
        if sid > 0 and sid in self._states:
            self._states[sid].victory_points[province_id] = value
            if name:
                self._states[sid].vp_names[province_id] = name
            elif province_id not in self._states[sid].vp_names:
                self._states[sid].vp_names[province_id] = ""

    def remove_vp(self, province_id: int) -> None:
        """Remove victory points and the associated city name from a province."""
        sid = self._province_to_state.get(province_id, 0)
        if sid > 0 and sid in self._states:
            self._states[sid].victory_points.pop(province_id, None)
            self._states[sid].vp_names.pop(province_id, None)

    def clear(self) -> None:
        """Remove every state and reset the next generated state ID."""
        self._states.clear()
        self._province_to_state.clear()
        self._next_id = 1

    def delete_state(self, state_id: int) -> bool:
        """Delete a state and remove reverse-index entries for its provinces."""
        if state_id not in self._states:
            return False
        for pid in list(self._states[state_id].provinces):
            if self._province_to_state.get(pid) == state_id:
                self._province_to_state.pop(pid, None)
        del self._states[state_id]
        return True

    def find_empty_state_ids(self) -> list[int]:
        """Return IDs of states left without provinces after editing."""
        return [sid for sid, st in self._states.items() if not st.provinces]

    def compact_ids(self) -> dict[int, int]:
        """Renumber states contiguously and return the old-to-new ID mapping.

        HOI4 expects state IDs to be contiguous. Empty states created while
        provinces are merged can leave gaps, so exporters call this method
        before writing state history files. Predictable ``STATE_N`` names are
        updated along with their IDs.
        """
        old_ids = sorted(self._states.keys())
        if not old_ids:
            return {}
        if old_ids == list(range(1, len(old_ids) + 1)):
            return {}

        mapping = {old: new for new, old in enumerate(old_ids, start=1)}
        new_states: dict[int, StateData] = {}
        for old, state in self._states.items():
            new_id = mapping[old]
            if state.name == f"STATE_{old}":
                state.name = f"STATE_{new_id}"
            state.id = new_id
            new_states[new_id] = state
        self._states = new_states
        self._province_to_state = {
            pid: mapping[old_sid]
            for pid, old_sid in self._province_to_state.items()
            if old_sid in mapping
        }
        self._next_id = len(self._states) + 1
        return mapping

    def auto_split(
        self,
        province_map: np.ndarray,
        tile_map: np.ndarray,
        per_state: int = 15,
    ) -> None:
        """Group land provinces into geographically compact states.

        Connected landmasses are identified first; K-means clustering is then
        performed independently within each landmass so provinces separated
        by water are not placed in the same state.
        """
        self.clear()

        max_pid = int(province_map.max())
        if max_pid == 0:
            return

        # Vectorize province counts and land classification for the whole map.
        # This avoids scanning the complete image separately for each province.
        flat_pm = province_map.ravel()
        flat_tm = tile_map.ravel()
        flat_land = (flat_tm == TILE_LAND).astype(np.int32)

        # Count total pixels and land pixels for every province ID.
        pid_count = np.bincount(flat_pm, minlength=max_pid + 1)
        pid_land_count = np.bincount(flat_pm, weights=flat_land, minlength=max_pid + 1)

        # A land province contains more land pixels than non-land pixels.
        land_ids = []
        for pid in range(1, max_pid + 1):
            if pid_count[pid] > 0 and pid_land_count[pid] > pid_count[pid] / 2:
                land_ids.append(pid)

        if not land_ids:
            return

        # Compute province centroids using the actual map shape. The module-level
        # map-size constants may be stale after a project changes dimensions.
        map_h, map_w = province_map.shape
        ys_all, xs_all = np.mgrid[0:map_h, 0:map_w]
        flat_ys = ys_all.ravel().astype(np.float64)
        flat_xs = xs_all.ravel().astype(np.float64)

        sum_y = np.bincount(flat_pm, weights=flat_ys, minlength=max_pid + 1)
        sum_x = np.bincount(flat_pm, weights=flat_xs, minlength=max_pid + 1)

        centers = {}
        land_set = set(land_ids)
        for pid in land_ids:
            cnt = pid_count[pid]
            if cnt > 0:
                centers[pid] = (sum_y[pid] / cnt, sum_x[pid] / cnt)

        # Find connected components representing independent landmasses.
        land_binary = (tile_map == TILE_LAND).astype(np.int32)
        labeled_land, num_landmasses = label(land_binary)

        # Associate each province with the landmass containing its centroid.
        pid_to_landmass: dict[int, int] = {}
        for pid in land_ids:
            cy, cx = centers[pid]
            iy, ix = int(cy), int(cx)
            iy = min(max(iy, 0), map_h - 1)
            ix = min(max(ix, 0), map_w - 1)
            lm = int(labeled_land[iy, ix])
            if lm == 0:
                # A centroid can fall on water at an edge; use any land pixel instead.
                mask = (province_map == pid) & (tile_map == TILE_LAND)
                pts = np.where(mask)
                if len(pts[0]) > 0:
                    lm = int(labeled_land[pts[0][0], pts[1][0]])
            pid_to_landmass[pid] = lm

        # Group province IDs by their containing landmass.
        landmass_groups: dict[int, list[int]] = {}
        for pid in land_ids:
            lm = pid_to_landmass.get(pid, 0)
            if lm not in landmass_groups:
                landmass_groups[lm] = []
            landmass_groups[lm].append(pid)

        # Cluster centroids within each landmass to produce compact state blobs.
        from scipy.cluster.vq import kmeans2
        rng_seed = 42  # Fixed seed makes repeated generation deterministic.
        for lm_id, group_pids in landmass_groups.items():
            n_pids = len(group_pids)
            if n_pids == 0:
                continue
            # Target state count is ceil(number of provinces / requested size).
            n_states = max(1, (n_pids + per_state - 1) // per_state)
            # A single cluster or a tiny landmass needs no clustering.
            if n_states == 1 or n_pids <= 2:
                state = self.create_state(group_pids)
                state.manpower = n_pids * 50000
                continue

            # Build the centroid matrix with one [y, x] row per province.
            pts = np.array(
                [[centers[p][0], centers[p][1]] for p in group_pids],
                dtype=np.float64,
            )
            # ``points`` initialization chooses sample centroids as seeds.
            # Seed NumPy explicitly because SciPy changed its RNG keyword across versions.
            # This is the most compatible way to keep generation repeatable.
            np.random.seed(rng_seed)
            try:
                _, labels = kmeans2(pts, n_states, iter=20, minit='points')
            except Exception:
                # Degenerate input, such as many identical centroids, falls back to ordered chunks.
                labels = np.array([i * n_states // n_pids for i in range(n_pids)])

            # Group provinces by the resulting cluster label.
            cluster_to_pids: dict[int, list[int]] = {}
            for pid, lab in zip(group_pids, labels):
                cluster_to_pids.setdefault(int(lab), []).append(pid)
            for chunk in cluster_to_pids.values():
                if not chunk:
                    continue
                state = self.create_state(chunk)
                state.manpower = len(chunk) * 50000

    def build_state_color_map(
        self, province_map: np.ndarray,
        unassigned_highlight: bool = True,
    ) -> np.ndarray:
        """Build a deterministic RGB overlay for state assignments.

        Unassigned provinces are bright red when highlighting is enabled so
        missing state assignments are easy to spot on the map.
        """
        # Use a fixed seed so state colors do not change between redraws.
        rng = np.random.RandomState(123)
        colors = {}
        for sid in self._states:
            colors[sid] = (
                int(rng.randint(60, 220)),
                int(rng.randint(60, 220)),
                int(rng.randint(60, 220)),
            )

        # Build a province-ID lookup table containing each state's RGB color.
        max_pid = int(province_map.max())
        lut = np.zeros((max_pid + 1, 3), dtype=np.uint8)
        # Unassigned provinces use bright red for highlighting or dark gray otherwise.
        if unassigned_highlight:
            lut[:, :] = (220, 30, 30)  # Bright red marks an unassigned province.
        else:
            lut[:, :] = 40  # Dark gray leaves unassigned provinces unobtrusive.

        # Province ID zero represents ocean or otherwise unmapped pixels.
        lut[0] = (40, 40, 60)

        for pid, sid in self._province_to_state.items():
            if pid <= max_pid and sid in colors:
                lut[pid] = colors[sid]

        # Apply the lookup table to the complete province map.
        flat = province_map.ravel()
        flat_clipped = np.clip(flat, 0, max_pid)
        rgb = lut[flat_clipped].reshape(province_map.shape[0], province_map.shape[1], 3)
        return rgb

    def build_state_id_map(self, province_map: np.ndarray) -> np.ndarray:
        """Convert each province ID in a map to its assigned state ID."""
        max_pid = int(province_map.max())
        lut = np.zeros(max_pid + 1, dtype=np.int32)
        for pid, sid in self._province_to_state.items():
            if pid <= max_pid:
                lut[pid] = sid
        return lut[np.clip(province_map, 0, max_pid)]

    def count_unassigned_provinces(self, all_land_pids: set[int]) -> int:
        """Count land provinces that are not present in the reverse index."""
        assigned = set(self._province_to_state.keys())
        return len(all_land_pids - assigned)
