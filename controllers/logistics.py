"""LogisticsController — Logistics editing controller.

Handle rail brush, supply node picking, adjacency/adjacency_rule dialog picking."""
from __future__ import annotations

from typing import TYPE_CHECKING

from controllers.base import BaseController

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class LogisticsController(BaseController):
    """Logistics Editor: railways/supplies/adjacency/adjacency_rule."""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        # Pickup target: 'adj_from'/'adj_to'/'adj_through'/'supply'/'supply_erase'/'rule_required'/'rule_icon'
        self.pick_target: str | None = None
        # Rail grade (0=wipe, 1-5)
        self.railway_level: int = 3

    def activate(self) -> None:
        """Enter logistics mode."""
        self.pick_target = None
        self._emit_status("Logistics editing mode: click provinces to set railway levels")

    def deactivate(self) -> None:
        """Exit logistics mode and clear all temporary status."""
        self.pick_target = None

    def on_province_clicked(self, pid: int) -> None:
        """Province click distribution: supply/adjacency pickup or rail level setting."""
        if pid <= 0:
            return

        # Supply/adjacency pickup mode
        if self.pick_target in ("supply", "supply_erase",
                                "adj_from", "adj_to", "adj_through",
                                "rule_required", "rule_icon"):
            self._handle_pick(pid)
            return

        # Other cases: Set rail grade
        from commands.map.set_railway import SetRailwayLevelCommand

        mgr = self.project.railway_mgr
        current = mgr.province_levels().get(pid, 0)
        new_level = self.railway_level
        if current == new_level:
            new_level = 0  # Click same level = erase

        if current == new_level:
            return  # No change

        cmd = SetRailwayLevelCommand(mgr, pid, current, new_level)
        self.history.execute(cmd)
        self.project.mark_dirty()
        self.event_bus.emit("railway_changed")

        if new_level > 0:
            self._emit_status(f"Province {pid} railway level → {new_level}")
        else:
            self._emit_status(f"Railway removed from province {pid}")

    def set_railway_level(self, level: int) -> None:
        """Set rail grade."""
        self.railway_level = level

    def toggle_supply_pick(self, on: bool, erase: bool = False) -> None:
        """Toggle supply node pickup mode. Erase mode when erase=True."""
        if on:
            self.pick_target = "supply_erase" if erase else "supply"
            mode_text_en = "remove a" if erase else "place a"
            self._emit_status(f"Click a land province to {mode_text_en} supply hub")
        else:
            if self.pick_target in ("supply", "supply_erase"):
                self.pick_target = None
            self._emit_status("Supply hub mode disabled")

    def set_adjacency_pick(self, on: bool, target: str = "") -> None:
        """Set adjacency dialog picking mode."""
        if on and target:
            self.pick_target = f"adj_{target}"
            self._emit_status(f"Click a map province to fill adjacency {target}")
        else:
            self.pick_target = None
            self._emit_status("Picking mode disabled")

    def set_rule_pick(self, on: bool, target: str = "") -> None:
        """Set adjacency_rule dialog picking mode."""
        if on and target:
            self.pick_target = target  # 'rule_required' or 'rule_icon'
            self._emit_status(f"Click a map province → add to {target}")
        else:
            self.pick_target = None
            self._emit_status("Picking mode disabled")

    def _handle_pick(self, pid: int) -> None:
        """Uniform pickup and distribution."""
        target = self.pick_target

        if target in ("supply", "supply_erase"):
            self._pick_supply(pid, erase=(target == "supply_erase"))
            # supply mode is continuous and does not reset the target
        elif target in ("adj_from", "adj_to", "adj_through"):
            # Notification UI backfills province ID
            self.event_bus.emit(
                "logistics_province_picked",
                pid=pid,
                target=target,
            )
            self.pick_target = None
        elif target in ("rule_required", "rule_icon"):
            self.event_bus.emit(
                "logistics_province_picked",
                pid=pid,
                target=target,
            )
            self.pick_target = None
        else:
            self.pick_target = None

    def _pick_supply(self, pid: int, erase: bool = False) -> None:
        """Supply node pickup: place or delete."""
        import numpy as np
        from data.constants import TILE_LAND

        map_data = self.project.map_data
        province_map = map_data.province_map
        tile_map = map_data.tile_map

        ys, xs = np.where(province_map == pid)
        if len(ys) == 0:
            return

        if int(tile_map[ys[0], xs[0]]) != TILE_LAND:
            self._emit_status(f"Province {pid} is not land; skipped")
            return

        mgr = self.project.supply_mgr
        if erase:
            if mgr.contains(pid):
                mgr.remove(pid)
                self.project.mark_dirty()
                self.event_bus.emit("railway_changed")
                self._emit_status(f"Supply hub removed from province {pid}")
            else:
                self._emit_status(f"Province {pid} has no supply hub")
        else:
            if not mgr.contains(pid):
                mgr.add(pid)
                self.project.mark_dirty()
                self.event_bus.emit("railway_changed")
                self._emit_status(f"Supply hub added to province {pid}")
            else:
                self._emit_status(f"Province {pid} already has a supply hub")
