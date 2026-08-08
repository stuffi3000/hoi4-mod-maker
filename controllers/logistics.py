"""LogisticsController — 后勤编辑控制器。

处理铁路画笔、补给节点拾取、adjacency/adjacency_rule 对话框拾取。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from controllers.base import BaseController

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class LogisticsController(BaseController):
    """后勤编辑：铁路/补给/adjacency/adjacency_rule。"""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        # 拾取目标: 'adj_from'/'adj_to'/'adj_through'/'supply'/'supply_erase'/'rule_required'/'rule_icon'
        self.pick_target: str | None = None
        # 铁路等级 (0=擦除, 1-5)
        self.railway_level: int = 3

    def activate(self) -> None:
        """进入后勤模式。"""
        self.pick_target = None
        self._emit_status("后勤编辑模式: 点击省份设置铁路等级", "Logistics editing mode: click provinces to set railway levels")

    def deactivate(self) -> None:
        """离开后勤模式，清理所有临时状态。"""
        self.pick_target = None

    def on_province_clicked(self, pid: int) -> None:
        """省份点击分发：补给/adjacency 拾取 或 铁路等级设置。"""
        if pid <= 0:
            return

        # 补给/adjacency 拾取模式
        if self.pick_target in ("supply", "supply_erase",
                                "adj_from", "adj_to", "adj_through",
                                "rule_required", "rule_icon"):
            self._handle_pick(pid)
            return

        # 其他情况：设置铁路等级
        from commands.map.set_railway import SetRailwayLevelCommand

        mgr = self.project.railway_mgr
        current = mgr.province_levels().get(pid, 0)
        new_level = self.railway_level
        if current == new_level:
            new_level = 0  # 点同等级 = 擦除

        if current == new_level:
            return  # 无变化

        cmd = SetRailwayLevelCommand(mgr, pid, current, new_level)
        self.history.execute(cmd)
        self.project.mark_dirty()
        self.event_bus.emit("railway_changed")

        if new_level > 0:
            self._emit_status(f"省份 {pid} 铁路等级 → {new_level}", f"Province {pid} railway level → {new_level}")
        else:
            self._emit_status(f"省份 {pid} 铁路已移除", f"Railway removed from province {pid}")

    def set_railway_level(self, level: int) -> None:
        """设置铁路等级。"""
        self.railway_level = level

    def toggle_supply_pick(self, on: bool, erase: bool = False) -> None:
        """开关补给节点拾取模式。erase=True 时为擦除模式。"""
        if on:
            self.pick_target = "supply_erase" if erase else "supply"
            mode_text = "删除" if erase else "放置"
            mode_text_en = "remove a" if erase else "place a"
            self._emit_status(f"点击陆地省份{mode_text}补给节点", f"Click a land province to {mode_text_en} supply hub")
        else:
            if self.pick_target in ("supply", "supply_erase"):
                self.pick_target = None
            self._emit_status("补给模式已关闭", "Supply hub mode disabled")

    def set_adjacency_pick(self, on: bool, target: str = "") -> None:
        """设置 adjacency 对话框拾取模式。"""
        if on and target:
            self.pick_target = f"adj_{target}"
            self._emit_status(f"点击画布省份填入 adjacency {target}", f"Click a map province to fill adjacency {target}")
        else:
            self.pick_target = None
            self._emit_status("拾取模式关闭", "Picking mode disabled")

    def set_rule_pick(self, on: bool, target: str = "") -> None:
        """设置 adjacency_rule 对话框拾取模式。"""
        if on and target:
            self.pick_target = target  # 'rule_required' or 'rule_icon'
            self._emit_status(f"点击画布省份 → 加入 {target}", f"Click a map province → add to {target}")
        else:
            self.pick_target = None
            self._emit_status("拾取模式关闭", "Picking mode disabled")

    def _handle_pick(self, pid: int) -> None:
        """统一的拾取分发。"""
        target = self.pick_target

        if target in ("supply", "supply_erase"):
            self._pick_supply(pid, erase=(target == "supply_erase"))
            # supply 模式���持续的，不重置 target
        elif target in ("adj_from", "adj_to", "adj_through"):
            # 通知 UI 回填省份 ID
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
        """补给节点拾取：放置或删除。"""
        import numpy as np
        from data.constants import TILE_LAND

        map_data = self.project.map_data
        province_map = map_data.province_map
        tile_map = map_data.tile_map

        ys, xs = np.where(province_map == pid)
        if len(ys) == 0:
            return

        if int(tile_map[ys[0], xs[0]]) != TILE_LAND:
            self._emit_status(f"省份 {pid} 不是陆地, 跳过", f"Province {pid} is not land; skipped")
            return

        mgr = self.project.supply_mgr
        if erase:
            if mgr.contains(pid):
                mgr.remove(pid)
                self.project.mark_dirty()
                self.event_bus.emit("railway_changed")
                self._emit_status(f"补给节点已删除: 省份 {pid}", f"Supply hub removed from province {pid}")
            else:
                self._emit_status(f"省份 {pid} 无补给节点", f"Province {pid} has no supply hub")
        else:
            if not mgr.contains(pid):
                mgr.add(pid)
                self.project.mark_dirty()
                self.event_bus.emit("railway_changed")
                self._emit_status(f"补给节点已添加: 省份 {pid}", f"Supply hub added to province {pid}")
            else:
                self._emit_status(f"省份 {pid} 已有补给节点", f"Province {pid} already has a supply hub")
