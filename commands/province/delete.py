"""Undoable deletion of one or more provinces and their dependent data."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import numpy as np

from commands.base import Command

if TYPE_CHECKING:
    from model.project import Project


class DeleteProvincesCommand(Command):
    """Replace province pixels with ID 0 and remove dangling references."""

    label = "Delete provinces"

    _MANAGER_NAMES = (
        "state_mgr",
        "country_mgr",
        "continent_mgr",
        "adjacency_mgr",
        "railway_mgr",
        "supply_mgr",
        "adjacency_rule_mgr",
        "strategic_region_mgr",
    )

    def __init__(self, project: "Project", province_ids) -> None:
        self._project = project
        self._province_ids = {
            int(pid) for pid in province_ids if int(pid) > 0
        }
        self._affected_pixels: np.ndarray | None = None
        self._affected_original_ids: np.ndarray | None = None
        self._manager_snapshots: dict[str, dict] | None = None
        self._terrain_snapshot: dict[int, str] | None = None

    @property
    def province_ids(self) -> set[int]:
        return set(self._province_ids)

    def execute(self) -> None:
        if not self._province_ids:
            return

        map_data = self._project.map_data
        province_map = map_data.province_map

        if self._affected_pixels is None:
            self._affected_pixels = np.isin(
                province_map, tuple(sorted(self._province_ids))
            )
            self._affected_original_ids = province_map[self._affected_pixels].copy()
            self._manager_snapshots = {
                name: deepcopy(getattr(self._project, name).__dict__)
                for name in self._MANAGER_NAMES
            }
            self._terrain_snapshot = {
                pid: map_data.provincial_terrain[pid]
                for pid in self._province_ids
                if pid in map_data.provincial_terrain
            }

        province_map[self._affected_pixels] = 0
        self._drop_references()

    def _drop_references(self) -> None:
        project = self._project
        removed = self._province_ids

        # State membership and every province-keyed state field must agree.
        state_mgr = project.state_mgr
        for state in state_mgr.states.values():
            state.provinces = [pid for pid in state.provinces if pid not in removed]
            for field in (
                "victory_points", "vp_names", "vp_names_en", "province_buildings"
            ):
                values = getattr(state, field, None)
                if values is not None:
                    for pid in removed:
                        values.pop(pid, None)
        state_mgr._province_to_state = {
            pid: sid
            for pid, sid in state_mgr._province_to_state.items()
            if pid not in removed
        }

        # A deleted capital moves to another surviving province owned by the
        # same country where possible; otherwise it becomes unset.
        country_mgr = project.country_mgr
        for tag, country in country_mgr.countries.items():
            if country.capital not in removed:
                continue
            replacement = 0
            for sid in country_mgr.get_states_of_country(tag):
                state = state_mgr.get_state(sid)
                if state is not None and state.provinces:
                    replacement = state.provinces[0]
                    break
            country.capital = replacement

        for region in project.strategic_region_mgr._regions.values():
            region.province_ids = [
                pid for pid in region.province_ids if pid not in removed
            ]

        for manager_name in (
            "continent_mgr",
            "adjacency_mgr",
            "railway_mgr",
            "supply_mgr",
            "adjacency_rule_mgr",
        ):
            getattr(project, manager_name).drop_provinces(removed)

        for pid in removed:
            project.map_data.provincial_terrain.pop(pid, None)

    def undo(self) -> None:
        if (
            self._affected_pixels is None
            or self._affected_original_ids is None
            or self._manager_snapshots is None
        ):
            return

        province_map = self._project.map_data.province_map
        province_map[self._affected_pixels] = self._affected_original_ids

        for name, snapshot in self._manager_snapshots.items():
            manager = getattr(self._project, name)
            manager.__dict__.clear()
            manager.__dict__.update(deepcopy(snapshot))

        if self._terrain_snapshot:
            self._project.map_data.provincial_terrain.update(self._terrain_snapshot)
