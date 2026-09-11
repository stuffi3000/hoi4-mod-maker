"""Country Manager — create/edit countries, assign territories, set capital"""
import numpy as np
from dataclasses import dataclass, field


@dataclass
class NationalSpirit:
    """national spirit / national idea"""
    id: str                       # idea ID (TAG_xxx format recommended)
    name: str                     # Display name (localized)
    desc: str = ""                # Description (localized)
    modifiers: dict[str, float] = field(default_factory=dict)  # {modifier_key: value}
    picture: str = "generic_pp_unaligned"


@dataclass
class CountryData:
    """data for a country"""
    tag: str                     # 3-letter code such as KAR
    name: str = ""               # display name
    color: tuple[int, int, int] = (100, 100, 200)  # RGB color
    capital: int = 0             # Capital Province ID
    ruling_party: str = "neutrality"  # neutrality/democratic/fascism/communism
    popularities: dict[str, int] = field(default_factory=lambda: {
        "democratic": 10,
        "fascism": 5,
        "communism": 5,
        "neutrality": 80,
    })
    national_spirits: list[NationalSpirit] = field(default_factory=list)

    def __post_init__(self):
        if not self.name:
            self.name = self.tag


RULING_PARTIES = ["neutrality", "democratic", "fascism", "communism"]


class CountryManager:
    """Manage all countries"""

    def __init__(self):
        self._countries: dict[str, CountryData] = {}
        self._state_owner: dict[int, str] = {}  # state_id → tag

    @property
    def countries(self) -> dict[str, CountryData]:
        return self._countries

    def get_country(self, tag: str) -> CountryData | None:
        return self._countries.get(tag)

    def get_owner_of_state(self, state_id: int) -> str:
        """Get the owner TAG of State, empty string = not assigned"""
        return self._state_owner.get(state_id, "")

    def create_country(
        self, tag: str, name: str = "", color: tuple[int, int, int] = (100, 100, 200),
        allow_vanilla_tag: bool = False,
    ) -> CountryData:
        """Create a country.

        allow_vanilla_tag: must be False when the user creates a new country from scratch (vanilla TAG crashes
        will be overwritten by game data); True when importing vanilla/MOD — the imported country is already
        vanilla TAG, rejecting them will result in no country being built."""
        tag = tag.upper()[:3]
        if len(tag) != 3:
            raise ValueError("TAG must contain exactly 3 characters")
        if not tag.isalnum():
            raise ValueError("TAG can contain letters and numbers only")
        # BUG-6b: Reject vanilla TAG (avoiding Genoa→Krakow type crashes)
        if not allow_vanilla_tag:
            from data.constants import is_vanilla_tag
            if is_vanilla_tag(tag):
                raise ValueError(
                    f"TAG '{tag}' conflicts with a vanilla country, so HOI4 would overwrite "
                    f"your country's data (including name, color, and ideas). Choose another "
                    f"3-character combination, preferably containing a number, such as X01, K42, or Z99."
                )
        country = CountryData(tag=tag, name=name or tag, color=color)
        self._countries[tag] = country
        return country

    def remove_country(self, tag: str) -> None:
        """Delete country"""
        self._countries.pop(tag, None)
        # Clear the country's territory
        to_remove = [sid for sid, t in self._state_owner.items() if t == tag]
        for sid in to_remove:
            del self._state_owner[sid]

    def assign_state(self, state_id: int, tag: str) -> None:
        """Assign State to country"""
        if tag and tag in self._countries:
            self._state_owner[state_id] = tag
        elif not tag:
            self._state_owner.pop(state_id, None)

    def remap_state_ids(self, mapping: dict[int, int]) -> None:
        """Cooperate with StateManager.compact_ids: Replace the state ID in _state_owner by mapping.

        State IDs that do not appear in the old → new mapping are considered to have been deleted and removed from _state_owner together."""
        if not mapping:
            return
        new_owner: dict[int, str] = {}
        for old_sid, tag in self._state_owner.items():
            new_sid = mapping.get(old_sid)
            if new_sid is not None:
                new_owner[new_sid] = tag
        self._state_owner = new_owner

    def set_capital(self, tag: str, province_id: int) -> None:
        """Set capital"""
        if tag in self._countries:
            self._countries[tag].capital = province_id

    def set_ruling_party(self, tag: str, party: str) -> None:
        """Set up the ruling party"""
        if tag in self._countries and party in RULING_PARTIES:
            self._countries[tag].ruling_party = party

    def set_popularity(self, tag: str, party: str, value: int) -> None:
        """Set the support rate of a political party"""
        if tag in self._countries:
            self._countries[tag].popularities[party] = max(0, min(100, value))

    def get_states_of_country(self, tag: str) -> list[int]:
        """Get all State IDs of a country"""
        return [sid for sid, t in self._state_owner.items() if t == tag]

    def clear(self) -> None:
        """Clear all data"""
        self._countries.clear()
        self._state_owner.clear()

    def build_country_color_map(
        self,
        province_map: np.ndarray,
        state_manager,  # StateManager instance
        tile_map: np.ndarray | None = None,
    ) -> np.ndarray:
        """Generates a country color map (for display).

        state not assigned to a country uses the state's own color (**desaturate + darken**),
        Avoid confusion with national colors, and allow users to see the state boundaries clearly in national mode.
        Know at a glance which state still needs to be allocated."""
        from data.constants import TILE_LAND

        max_pid = int(province_map.max())
        # Default: sea/unreturned state provinces = dark blue (consistent with the continent model, to avoid confusion with gray land)
        lut = np.full((max_pid + 1, 3), (30, 40, 70), dtype=np.uint8)

        # Identify land provinces (majority rule to avoid misjudgment of adjacent pixels) - only land provinces will be painted with national colors/state colors
        is_land_arr: np.ndarray | None = None
        if tile_map is not None:
            pid_flat = province_map.ravel()
            land_flat = (tile_map == TILE_LAND).ravel()
            land_count = np.bincount(pid_flat, weights=land_flat, minlength=max_pid + 1)
            total_count = np.bincount(pid_flat, minlength=max_pid + 1)
            is_land_arr = land_count * 2 > total_count

        # The same seed as the state manager to ensure the state color is stable
        rng = np.random.RandomState(123)
        state_colors: dict[int, tuple[int, int, int]] = {}
        for sid in state_manager.states:
            state_colors[sid] = (
                int(rng.randint(60, 220)),
                int(rng.randint(60, 220)),
                int(rng.randint(60, 220)),
            )

        # Mark whether the pid belongs to the land province of "allocated country" (for country renderer to filter when drawing white borders)
        assigned_lut = np.zeros(max_pid + 1, dtype=bool)
        for sid, state in state_manager.states.items():
            tag = self._state_owner.get(sid, "")
            assigned = bool(tag and tag in self._countries)
            if assigned:
                color = self._countries[tag].color
            else:
                sr, sg, sb = state_colors.get(sid, (100, 100, 100))
                gray = (sr + sg + sb) // 3
                mix = 0.6
                color = (
                    int((sr * (1 - mix) + gray * mix) * 0.7),
                    int((sg * (1 - mix) + gray * mix) * 0.7),
                    int((sb * (1 - mix) + gray * mix) * 0.7),
                )
            for pid in state.provinces:
                if pid <= max_pid:
                    # Only the land province is painted true; the ocean province is mistakenly added to state and remains blue
                    if is_land_arr is None or is_land_arr[pid]:
                        lut[pid] = color
                        if assigned:
                            assigned_lut[pid] = True

        flat = province_map.ravel()
        flat_clipped = np.clip(flat, 0, max_pid)
        rgb = lut[flat_clipped].reshape(province_map.shape[0], province_map.shape[1], 3)
        # The second one returns: assigned mask (H, W) — True indicating that the pixel is an "assigned country" land
        assigned_mask = assigned_lut[flat_clipped].reshape(rgb.shape[0], rgb.shape[1])
        return rgb, assigned_mask

    def build_country_index_map(
        self, province_map: np.ndarray, state_manager,
    ) -> tuple[np.ndarray, dict[int, str]]:
        """Province map → Country serial number map (0=unallocated) + {serial number: country name}, for name tag layout."""
        tags = sorted(self._countries)
        tag_idx = {t: i + 1 for i, t in enumerate(tags)}
        names = {i + 1: (self._countries[t].name or t) for i, t in enumerate(tags)}
        max_pid = int(province_map.max())
        lut = np.zeros(max_pid + 1, dtype=np.int32)
        for sid, state in state_manager.states.items():
            idx = tag_idx.get(self._state_owner.get(sid, ""), 0)
            if idx:
                for pid in state.provinces:
                    if pid <= max_pid:
                        lut[pid] = idx
        idx_map = lut[np.clip(province_map, 0, max_pid)]
        return idx_map, names

    def get_country_list(self) -> list[tuple[str, str, tuple[int, int, int]]]:
        """Returns [(tag, name, color), ...] for UI lists"""
        return [(c.tag, c.name, c.color) for c in self._countries.values()]
