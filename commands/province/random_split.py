"""Undoable random multi-province split with metadata inheritance."""
from __future__ import annotations

import copy
import zlib

import numpy as np

from commands.base import Command


class RandomSplitProvincesCommand(Command):
    label = "Randomly split selected provinces"

    def __init__(self, project, new_map: np.ndarray, parent_by_new_id: dict[int, int]) -> None:
        self._project = project
        self._new_map = np.asarray(new_map, dtype=np.int32).copy()
        self._parents = dict(parent_by_new_id)
        self._old_map: tuple[bytes, tuple[int, ...], np.dtype] | None = None
        self._before: dict[str, object] | None = None
        self._after: dict[str, object] | None = None

    def _metadata_snapshot(self) -> dict[str, object]:
        p = self._project
        return {
            "states": copy.deepcopy(p.state_mgr.__dict__),
            "regions": copy.deepcopy(p.strategic_region_mgr.__dict__),
            "continents": copy.deepcopy(p.continent_mgr.__dict__),
            "terrain": copy.deepcopy(p.map_data.provincial_terrain),
        }

    def _restore_metadata(self, snapshot: dict[str, object]) -> None:
        p = self._project
        p.state_mgr.__dict__.clear()
        p.state_mgr.__dict__.update(copy.deepcopy(snapshot["states"]))
        p.strategic_region_mgr.__dict__.clear()
        p.strategic_region_mgr.__dict__.update(copy.deepcopy(snapshot["regions"]))
        p.continent_mgr.__dict__.clear()
        p.continent_mgr.__dict__.update(copy.deepcopy(snapshot["continents"]))
        p.map_data.provincial_terrain = copy.deepcopy(snapshot["terrain"])

    def _inherit_metadata(self) -> None:
        p = self._project
        for new_id, parent_id in self._parents.items():
            state_id = p.state_mgr.get_state_of_province(parent_id)
            if state_id:
                p.state_mgr.assign_province(new_id, state_id)
            region_id = p.strategic_region_mgr.get_region_of_province(parent_id)
            if region_id:
                p.strategic_region_mgr.assign_province(new_id, region_id)
            continent = p.continent_mgr.get_province_continent(parent_id)
            p.continent_mgr.assign_province(new_id, continent)
            if parent_id in p.map_data.provincial_terrain:
                p.map_data.provincial_terrain[new_id] = p.map_data.provincial_terrain[parent_id]

    def execute(self) -> None:
        map_data = self._project.map_data
        if self._old_map is None:
            old = map_data.province_map
            self._old_map = (zlib.compress(old.tobytes(), 1), old.shape, old.dtype)
            self._before = self._metadata_snapshot()
            map_data.province_map[:] = self._new_map
            self._inherit_metadata()
            self._after = self._metadata_snapshot()
        else:
            map_data.province_map[:] = self._new_map
            if self._after is not None:
                self._restore_metadata(self._after)
        map_data.invalidate_centroid_cache()

    def undo(self) -> None:
        if self._old_map is None:
            return
        compressed, shape, dtype = self._old_map
        old = np.frombuffer(zlib.decompress(compressed), dtype=dtype).reshape(shape)
        self._project.map_data.province_map[:] = old
        if self._before is not None:
            self._restore_metadata(self._before)
        self._project.map_data.invalidate_centroid_cache()
