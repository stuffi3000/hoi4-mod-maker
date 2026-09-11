"""ResplitStateCommand — Resplit provinces within a state.

Effect: Clear all provinces in the state and regenerate them according to the target number within the original pixel range of the state.
     The new province automatically returns to the state (owner/national territory remains unchanged).
Applies to: State mode "Redivide this state into provinces" button.
Call: cmd = ResplitStateCommand(map_data, state_mgr, sid, target_count);
     cmd_history.execute(cmd) — supports undo/redo.

Implementation points:
- Existing unallocated pixels outside the state (newly painted land, etc.) are temporarily marked -1 for protection, and then restored after generation.
  Ensure incremental generators only break ground within the state
- The first execute run generates and caches the result (zlib), redo plays it directly, and the result is determined
- The state's VP/province-level buildings are cleared together with the old province ID (undo can be restored)"""

from __future__ import annotations

import zlib

import numpy as np

from commands.base import Command


class ResplitStateCommand(Command):
    label = "Resplit state provinces"

    def __init__(self, map_data, state_mgr, state_id: int, target_count: int) -> None:
        self._map_data = map_data
        self._state_mgr = state_mgr
        self._sid = int(state_id)
        self._target = max(1, int(target_count))
        # Populate when execute
        self._old_pm: bytes = b""
        self._new_pm: bytes = b""
        self._shape: tuple[int, ...] = ()
        self._old_state_snap: dict | None = None
        self._new_state_snap: dict | None = None
        self._old_p2s: dict[int, int] = {}
        self._new_pids: list[int] = []

    # ── Status Snapshot Tool ──

    def _snap_state(self) -> dict:
        s = self._state_mgr.get_state(self._sid)
        return {
            "provinces": list(s.provinces),
            "victory_points": dict(s.victory_points),
            "vp_names": dict(s.vp_names),
            "vp_names_en": dict(getattr(s, "vp_names_en", {}) or {}),
            "province_buildings": {k: dict(v) for k, v in s.province_buildings.items()},
        }

    def _apply_state_snap(self, snap: dict, pids_in_map: list[int]) -> None:
        s = self._state_mgr.get_state(self._sid)
        s.provinces = list(snap["provinces"])
        s.victory_points = dict(snap["victory_points"])
        s.vp_names = dict(snap["vp_names"])
        s.vp_names_en = dict(snap["vp_names_en"])
        s.province_buildings = {k: dict(v) for k, v in snap["province_buildings"].items()}
        # province → state reverse lookup table synchronization
        p2s = self._state_mgr._province_to_state
        for pid in pids_in_map:
            p2s.pop(pid, None)
        for pid in s.provinces:
            p2s[pid] = self._sid

    # ──Command interface──

    def execute(self) -> None:
        pm = self._map_data.province_map
        if self._new_pm:
            # redo: Directly play back the first generated results
            pm[:] = self._decompress(self._new_pm)
            self._apply_state_snap(self._new_state_snap, self._old_state_snap["provinces"])
            return

        state = self._state_mgr.get_state(self._sid)
        old_pids = [p for p in state.provinces if p > 0]
        if not old_pids:
            return

        self._shape = pm.shape
        self._old_pm = zlib.compress(pm.tobytes(), level=1)
        self._old_state_snap = self._snap_state()

        mask = np.isin(pm, old_pids)
        n_pixels = int(mask.sum())
        if n_pixels == 0:
            return
        prev_max = int(pm.max())  # The maximum id of the entire image before clearing, the new id must come after it

        # Protect existing unallocated pixels outside the state and only let the generator process them within the state
        protect = pm == 0
        pm[mask] = 0
        if protect.any():
            pm[protect] = -1

        from domain.generators.province import generate_provinces_incremental
        density = max(1.0, n_pixels / self._target)
        new_pm, _total = generate_provinces_incremental(
            self._map_data.tile_map, pm,
            target_density=density, skip_mismatch_clear=True,
        )
        if protect.any():
            new_pm[protect] = 0
        pm[:] = new_pm

        # The newly generated ID in the state may reuse the old number that was just deleted (the generator starts from the current max+1)
        # → Unified translation to the maximum ID of the entire map before clearing to avoid misconnection of old references such as railways/supplies etc.
        gen_ids = sorted(int(i) for i in np.unique(pm[mask]) if i > 0)
        lut = np.arange(int(pm.max()) + 1, dtype=np.int32)
        for i, gid in enumerate(gen_ids):
            lut[gid] = prev_max + 1 + i
        pm[mask] = lut[pm[mask]]
        self._new_pids = [prev_max + 1 + i for i in range(len(gen_ids))]

        # The new province returns to the state; VP/provincial-level buildings are invalidated with the old ID.
        state.provinces = list(self._new_pids)
        state.victory_points = {}
        state.vp_names = {}
        state.vp_names_en = {}
        state.province_buildings = {}
        p2s = self._state_mgr._province_to_state
        for pid in old_pids:
            p2s.pop(pid, None)
        for pid in self._new_pids:
            p2s[pid] = self._sid

        self._new_pm = zlib.compress(pm.tobytes(), level=1)
        self._new_state_snap = self._snap_state()

    def undo(self) -> None:
        if not self._old_pm:
            return
        self._map_data.province_map[:] = self._decompress(self._old_pm)
        self._apply_state_snap(self._old_state_snap, self._new_pids)

    def _decompress(self, blob: bytes) -> np.ndarray:
        raw = zlib.decompress(blob)
        return np.frombuffer(raw, dtype=np.int32).reshape(self._shape)
