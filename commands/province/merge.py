"""MergeProvincesCommand — merge two provinces.

Store affected pixel location, old province ID, old state/country reference,
for complete revocation."""

from __future__ import annotations

import numpy as np

from commands.base import Command
from domain.map_data import MapData


class MergeProvincesCommand(Command):
    """Merge Provinces: Merge all pixels of pid_remove into pid_keep."""

    label = "Merge provinces"

    def __init__(
        self,
        map_data: MapData,
        pid_keep: int,
        pid_remove: int,
        state_mgr=None,
        country_mgr=None,
        strategic_region_mgr=None,
    ) -> None:
        """Parameters:
            map_data: map data object
            pid_keep: reserved province ID
            pid_remove: removed province ID
            state_mgr: StateManager (optional, used to update state reference)
            country_mgr: CountryManager (optional, used to update the country reference)
            strategic_region_mgr: StrategicRegionManager (optional, clean up region residual pid)"""
        self._map_data = map_data
        self._pid_keep = pid_keep
        self._pid_remove = pid_remove
        self._state_mgr = state_mgr
        self._country_mgr = country_mgr
        self._strategic_region_mgr = strategic_region_mgr

        # undo data (populated when execute)
        self._affected_pixels: np.ndarray | None = None  # bool mask
        self._old_state_of_removed: int = 0
        self._old_vp_of_removed: dict[int, int] = {}
        self._compact_mapping: dict[int, int] = {}
        # The strategic_region id that the annexed pid originally belonged to (0 = not allocated)
        self._old_region_of_removed: int = 0
        # If pid_remove was once the capital of a country, record (tag, old_capital_pid); otherwise ("", 0)
        self._old_capital_of_country: tuple[str, int] = ("", 0)

    def execute(self) -> None:
        """Merge province pixels, update state/country references, compact IDs."""
        province_map = self._map_data.province_map

        # Record the pixel position of the removed province
        self._affected_pixels = (province_map == self._pid_remove)

        # Save state reference
        if self._state_mgr is not None:
            self._old_state_of_removed = (
                self._state_mgr.get_state_of_province(self._pid_remove)
            )
            old_state = self._state_mgr.get_state(self._old_state_of_removed)
            if old_state is not None:
                # Save the VP of the removed province
                if self._pid_remove in old_state.victory_points:
                    self._old_vp_of_removed = dict(old_state.victory_points)

        # Perform binning: pixels changed to pid_keep
        province_map[self._affected_pixels] = self._pid_keep

        # Update state: remove pid_remove from old state
        if self._state_mgr is not None:
            sid = self._old_state_of_removed
            state = self._state_mgr.get_state(sid) if sid > 0 else None
            if state is not None:
                if self._pid_remove in state.provinces:
                    state.provinces.remove(self._pid_remove)
                state.victory_points.pop(self._pid_remove, None)

        # Clean up strategic_region: The ID of pid_remove will be cut/incrementally generated and reused.
        # Failure to clear it will cause the new pid to be incorrectly "inherited" to the old strategic_region.
        if self._strategic_region_mgr is not None:
            for r in self._strategic_region_mgr.regions.values():
                if self._pid_remove in r.province_ids:
                    self._old_region_of_removed = r.id
                    r.province_ids.remove(self._pid_remove)
                    break

        # country.capital: pid_remove If it is the capital of a country, capital will point to the dead ID
        # → Crash when starting the game set_controller. Move the capital to pid_keep (the same country) or another province in the country.
        if self._country_mgr is not None:
            for tag, country in self._country_mgr.countries.items():
                if country.capital == self._pid_remove:
                    self._old_capital_of_country = (tag, self._pid_remove)
                    country.capital = self._pick_replacement_capital(tag)
                    break  # The capital can only belong to one country

        # No compaction of IDs - leaves holes open for the user to fill in with cuts/incremental generation
        # Check ID continuity when exporting, and prompt if there are holes.
        self._compact_mapping = {}

    def _pick_replacement_capital(self, tag: str) -> int:
        """Select a new capital for the country tag. Prioritize pid_keep (if the same country), otherwise any non-pid_remove province in the country."""
        # Prioritize pid_keep — it physically takes over pid_remove's pixels, most consecutively
        if self._state_mgr is not None:
            keep_sid = self._state_mgr.get_state_of_province(self._pid_keep)
            if keep_sid > 0:
                owner = self._country_mgr.get_owner_of_state(keep_sid)
                if owner == tag:
                    return self._pid_keep
        # Otherwise, pick one of the country’s owned states
        owned = self._country_mgr.get_states_of_country(tag)
        if self._state_mgr is not None:
            for sid in owned:
                s = self._state_mgr.get_state(sid)
                if s is None:
                    continue
                for p in s.provinces:
                    if p != self._pid_remove:
                        return p
        return 0

    def undo(self) -> None:
        """Restore pixels and references of merged provinces."""
        if self._affected_pixels is None:
            return

        province_map = self._map_data.province_map

        # Back compaction: find the current mapping of pid_keep and pid_remove
        # You need to restore the pixels first and then process the references
        # Since compaction may have changed the ID, we need to reverse the mapping
        reverse_map = {v: k for k, v in self._compact_mapping.items()}

        # restore pixels
        province_map[self._affected_pixels] = self._pid_remove

        # Restore state reference
        if self._state_mgr is not None and self._old_state_of_removed > 0:
            state = self._state_mgr.get_state(self._old_state_of_removed)
            if state is not None:
                if self._pid_remove not in state.provinces:
                    state.provinces.append(self._pid_remove)
                if self._old_vp_of_removed:
                    state.victory_points.update(self._old_vp_of_removed)
            # Rebuild index
            self._state_mgr._province_to_state[self._pid_remove] = (
                self._old_state_of_removed
            )

        # Restore strategic_region reference
        if (
            self._strategic_region_mgr is not None
            and self._old_region_of_removed > 0
        ):
            r = self._strategic_region_mgr.get(self._old_region_of_removed)
            if r is not None and self._pid_remove not in r.province_ids:
                r.province_ids.append(self._pid_remove)

        # Restore country.capital
        if self._country_mgr is not None and self._old_capital_of_country[0]:
            tag, old_cap = self._old_capital_of_country
            country = self._country_mgr.get_country(tag)
            if country is not None:
                country.capital = old_cap
