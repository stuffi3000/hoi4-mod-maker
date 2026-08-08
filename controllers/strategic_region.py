"""StrategicRegionController — 战略区域编辑控制器。

处理战略区域的自动生成、创建/删除、省份拾取。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from controllers.base import BaseController

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class StrategicRegionController(BaseController):
    """战略区域编辑。"""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.pick_on: bool = False
        self.pick_rid: int = 0
        self.assign_mode: bool = False
        # 始终监听省份重新生成
        self.event_bus.subscribe("province_map_regenerated", self._on_province_regen)

    def _on_province_regen(self, event) -> None:
        """省份全量重新生成 → 清除战略区域。"""
        if not event.data.get("incremental"):
            self.project.strategic_region_mgr.clear()

    def activate(self) -> None:
        """进入战略区域模式。"""
        self.pick_on = False
        self.pick_rid = 0
        self._emit_status("战略区域编辑模式", "Strategic region editing mode")

    def deactivate(self) -> None:
        """离开战略区域模式，清除高亮。"""
        self.pick_on = False
        self.pick_rid = 0
        self.event_bus.emit("clear_batch_selection")

    def on_province_clicked(self, pid: int) -> None:
        """点击省份：分配模式 → 分配到选中区域；查看模式 → 高亮所属区域。"""
        if pid <= 0:
            return

        sr_mgr = self.project.strategic_region_mgr

        # 分配模式：把省份分配到当前选中区域
        if self.assign_mode and self.pick_rid > 0:
            sr_mgr.assign_province(pid, self.pick_rid)
            self.project.mark_dirty()
            region = sr_mgr.get(self.pick_rid)
            if region:
                self.event_bus.emit("batch_highlight_pids", pids=list(region.province_ids))
            self.event_bus.emit("sr_colors_dirty")
            self._emit_status(f"省份 {pid} → 战略区域 #{self.pick_rid}", f"Province {pid} → strategic region #{self.pick_rid}")
            return

        if self.assign_mode and self.pick_rid <= 0:
            self._emit_status("请先在列表中选中一个区域", "Select a region in the list first")
            return

        # 查看模式：点击省份 → 高亮所属战略区 + 在列表中选中
        rid = sr_mgr.get_region_of_province(pid)
        if rid > 0:
            self.select_region(rid)
            self.event_bus.emit("sr_select_in_list", rid=rid)
        else:
            self._emit_status(f"省份 {pid} 未分配到任何战略区域", f"Province {pid} is not assigned to a strategic region")

    def set_assign_mode(self, on: bool) -> None:
        """开关分配模式。"""
        self.assign_mode = on
        if on:
            self._emit_status("分配模式: 点击省份加入选中区域", "Assign mode: click provinces to add them to the selected region")
        else:
            self._emit_status("查看模式: 点击省份查看所属区域", "View mode: click a province to inspect its region")

    def toggle_pick(self, on: bool, rid: int = 0) -> None:
        """开关拾取模式。"""
        self.pick_on = on
        self.pick_rid = rid if on else 0
        if on:
            self._emit_status(f"战略区拾取: 点击省份 → 加入 Region #{rid}", f"Strategic region picking: click a province → add to Region #{rid}")
        else:
            self._emit_status("战略区拾取关闭", "Strategic region picking disabled")

    def auto_generate(self) -> None:
        """自动生成战略区域。"""
        map_data = self.project.map_data
        province_map = map_data.province_map

        if int(province_map.max()) == 0:
            self._emit_status("请先生成省份", "Generate provinces first")
            return

        sr_mgr = self.project.strategic_region_mgr
        sr_mgr.auto_generate(
            province_map,
            map_data.tile_map,
            state_mgr=self.project.state_mgr,
        )
        self.project.mark_dirty()
        self._emit_status(f"已生成 {sr_mgr.count()} 个战略区域", f"Generated {sr_mgr.count()} strategic regions")

    def auto_assign_weather(self) -> None:
        """按纬度自动分配所有战略区域的天气预设."""
        sr_mgr = self.project.strategic_region_mgr
        if sr_mgr.count() == 0:
            self._emit_status("没有战略区域，请先生成", "No strategic regions exist; generate them first")
            return

        province_map = self.project.map_data.province_map
        changed = sr_mgr.auto_assign_weather_by_latitude(province_map)
        self.project.mark_dirty()
        self._emit_status(f"已按纬度分配 {changed} 个战略区域的天气预设", f"Assigned weather presets to {changed} strategic regions by latitude")

    def select_region(self, rid: int) -> None:
        """选中战略区域 → 高亮其所有省份。"""
        self.pick_rid = rid
        region = self.project.strategic_region_mgr.get(rid)
        if region:
            self.event_bus.emit("batch_highlight_pids", pids=list(region.province_ids))
            self._emit_status(
                f"战略区 #{rid} \"{region.name}\" "
                f"({len(region.province_ids)} 省份, {region.weather_preset})",
                f"Strategic region #{rid} \"{region.name}\" "
                f"({len(region.province_ids)} provinces, {region.weather_preset})",
            )
        else:
            self.event_bus.emit("batch_highlight_pids", pids=[])

    def create_region(self) -> None:
        """创建新战略区域。"""
        self.project.strategic_region_mgr.create_region()
        self.project.mark_dirty()

    def delete_region(self, rid: int) -> None:
        """删除战略区域。"""
        if rid > 0:
            self.project.strategic_region_mgr.remove_region(rid)
            self.project.mark_dirty()

    def set_name(self, rid: int, name: str) -> None:
        """设置战略区域名称。"""
        r = self.project.strategic_region_mgr.get(rid)
        if r:
            r.name = name.strip() or f"STRATEGICREGION_{rid}"
            self.project.mark_dirty()

    def set_weather(self, rid: int, preset: str) -> None:
        """设置战略区域天气预设。"""
        r = self.project.strategic_region_mgr.get(rid)
        if r:
            r.weather_preset = preset
            self.project.mark_dirty()

    def set_naval(self, rid: int, naval: str) -> None:
        """设置战略区域海军地形。"""
        r = self.project.strategic_region_mgr.get(rid)
        if r:
            r.naval_terrain = naval
            self.project.mark_dirty()

    def create_from_states(self, state_ids: list[int]) -> int:
        """把选中的州合并成一个战略区域。返回新 region ID。"""
        if not state_ids:
            return 0

        sr_mgr = self.project.strategic_region_mgr
        state_mgr = self.project.state_mgr

        # 收集选中州的所有省份
        province_ids: list[int] = []
        for sid in state_ids:
            state = state_mgr.get_state(sid)
            if state:
                province_ids.extend(state.provinces)

        if not province_ids:
            self._emit_status("选中的州没有省份", "The selected states contain no provinces")
            return 0

        # 从旧战略区域移除这些省份
        for pid in province_ids:
            old_rid = sr_mgr.get_region_of_province(pid)
            if old_rid > 0:
                old_r = sr_mgr.get(old_rid)
                if old_r and pid in old_r.province_ids:
                    old_r.province_ids.remove(pid)

        # 创建新战略区域
        r = sr_mgr.create_region()
        r.province_ids = province_ids
        self.project.mark_dirty()

        state_names = ", ".join(str(s) for s in state_ids[:5])
        if len(state_ids) > 5:
            state_names += f"... (+{len(state_ids)-5})"
        self._emit_status(f"创建战略区域 #{r.id}（包含州 {state_names}，{len(province_ids)} 个省份）", f"Created strategic region #{r.id} (states {state_names}, {len(province_ids)} provinces)")
        return r.id
