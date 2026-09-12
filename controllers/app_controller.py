"""ApplicationController — Application-level scheduler.

Business logic extracted from MainWindow:
- Mode switching side effects
- Calculation of province information
- State/Country color map refresh
- VP data collection
- List refresh
- Undo/redo management

MainWindow only does UI construction and signal routing, and all logic is delegated here."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from ui.i18n import tr

if TYPE_CHECKING:
    from model.project import Project
    from model.events import EventBus
    from commands.history import CommandHistory
    from views.canvas.widget import MapCanvas
    from ui.tool_panel import ToolPanel

from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
from commands.land.brush_stroke import BrushStrokeCommand


class ApplicationController:
    """Application-level scheduler — coordinates controllers, canvas, tool_panel."""

    def __init__(
        self,
        project: "Project",
        canvas: "MapCanvas",
        tool_panel: "ToolPanel",
        cmd_history: "CommandHistory",
        controllers: dict[str, Any],
        undo_mgr: Any,
    ) -> None:
        self._project = project
        self._canvas = canvas
        self._panel = tool_panel
        self._cmd_history = cmd_history
        self._controllers = controllers
        self._undo_mgr = undo_mgr
        self._event_bus: "EventBus" = project.event_bus
        self._current_controller = None
        self._province_info_cache: dict[int, dict] = {}

        # Brush stroke state (for BrushStrokeCommand)
        self._stroke_before: dict | None = None

        # Subscribe to EventBus events
        self._subscribe_events()

    # ═══════════════════════ EventBus Subscription ═══════════════════

    def _subscribe_events(self) -> None:
        bus = self._event_bus
        bus.subscribe("request_render", self._on_render)
        bus.subscribe("province_count_changed", self._on_province_count)
        bus.subscribe("state_changed", self._on_state_changed)
        bus.subscribe("country_changed", self._on_country_changed)
        bus.subscribe("continent_changed", self._on_continent_changed)
        bus.subscribe("vp_changed", self._on_vp_changed)
        bus.subscribe("province_map_regenerated", self._on_province_regen)
        bus.subscribe("clear_batch_selection", lambda e: self._canvas.set_batch_selection_pids([]))
        bus.subscribe("batch_highlight_pids", lambda e: self._canvas.set_batch_selection_pids(e.data.get("pids", [])))
        bus.subscribe("railway_changed", self._on_railway_changed)
        bus.subscribe("sr_colors_dirty", self._on_sr_colors_dirty)
        bus.subscribe("province_gaps_changed", self._on_province_gaps)

    # ═══════════════════════ Mode switch ═══════════════════════

    # Schema name mapping
    _MODE_KEYS = {
        "land": "mode_land", "province": "mode_province",
        "terrain": "mode_terrain", "height": "mode_height",
        "state": "mode_state", "country": "mode_country",
        "river": "mode_river", "continent": "mode_continent",
        "logistics": "mode_logistics",
        "strategic_region": "mode_strategic_region",
        "colormap": "mode_colormap", "default_map": "mode_default_map",
        "density": "mode_density", "province_terrain": "tab_province_terrain",
        "preview": "nav_preview",
    }

    def on_mode_changed(self, mode: str) -> str:
        """Mode switching: deactivate the old controller, activate the new controller, and refresh related data.
        Returns the display name of the pattern."""
        if self._current_controller is not None:
            self._current_controller.deactivate()

        self._canvas.cleanup_mode_state()
        # The density mode basemap is land (stacked density mask)
        if mode == "density":
            self._canvas.display_mode = "land"
        else:
            self._canvas.display_mode = mode

        # Density mode special: borrow LandController but enable density_mode
        # The density map is overlaid on the land view as a mask
        if mode == "density":
            md = self._project.map_data
            if md.density_map is None:
                md.density_map = np.full(
                    (md.tile_map.shape[0], md.tile_map.shape[1]),
                    0.5, dtype=np.float32,
                )
            self._canvas.set_density_overlay_visible(True)
            self._current_controller = self._controllers.get("land")
            if self._current_controller is not None:
                self._current_controller.density_mode = True
                self._current_controller.activate()
                self._current_controller._emit_status("Province density brush mode")
        else:
            # When switching to other modes, make sure the land controller exits density mode and hides the density mask
            self._canvas.set_density_overlay_visible(False)
            land_ctrl = self._controllers.get("land")
            if land_ctrl is not None:
                land_ctrl.density_mode = False
            self._current_controller = self._controllers.get(mode)
            if self._current_controller is not None:
                self._current_controller.activate()

        # Refresh colormap by mode
        if mode == "state":
            self._refresh_state_colors()
            # state mode overlays country borders + owner highlighting, requires country_rgb + assigned_mask
            self._refresh_country_colors()
            # Clear remaining country highlighting when entering state mode (when switching from country mode)
            self._canvas.set_highlight_country(None)
        elif mode == "country":
            self._refresh_country_colors()
        elif self._canvas._highlight_country_rgb is not None:
            # Clear country highlighting when leaving state / country mode
            self._canvas.set_highlight_country(None)
        elif mode == "strategic_region":
            self._refresh_sr_colors()
        elif mode == "logistics":
            self._refresh_railway_colors()
            self._canvas.refresh_logistics_overlay()
        elif mode == "province_terrain":
            self._refresh_provincial_terrain_colors()
        elif mode == "continent":
            self._refresh_continent_colors()

        # Hide state border overlay when leaving strategic area mode
        if mode != "strategic_region":
            self._canvas.show_state_borders(False)

        key = self._MODE_KEYS.get(mode)
        return tr(key) if key else mode

    @property
    def current_controller(self):
        return self._current_controller

    # ═══════════════════════ Province Information ═══════════════════════

    def invalidate_province_cache(self) -> None:
        """Clear province information cache."""
        self._province_info_cache.clear()

    def calculate_province_info(self, pid: int) -> dict | None:
        """Calculate province information (type/terrain/number of pixels/coastal) with caching.
        Returns a dict or None."""
        if pid in self._province_info_cache:
            return self._province_info_cache[pid]

        pm = self._canvas.province_map
        tm = self._canvas.tile_map
        mask = pm == pid
        pixels = int(np.sum(mask))

        ys, xs = np.where(mask)
        if len(ys) == 0:
            return None

        tiles = tm[mask]
        land_n = int(np.sum(tiles == TILE_LAND))
        sea_n = int(np.sum(tiles == TILE_SEA))
        lake_n = int(np.sum(tiles == TILE_LAKE))
        if sea_n >= land_n and sea_n >= lake_n:
            ptype = tr("tile_sea")
        elif lake_n >= land_n:
            ptype = tr("tile_lake")
        else:
            ptype = tr("tile_land")

        # coastal inspection
        _adj = False
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ny = np.clip(ys + dy, 0, tm.shape[0] - 1)
            nx = np.clip(xs + dx, 0, tm.shape[1] - 1)
            if np.any(tm[ny, nx] == TILE_SEA):
                _adj = True
                break
        coastal = _adj and land_n > sea_n and land_n > lake_n

        # Read provincial_terrain dict first (attribute layer = gameplay true value)
        # Return terrain.bmp majority pixels only if none (visual layer inference)
        from data.terrain_types import (
            GRAPHICAL_TERRAIN_BY_INDEX, TERRAIN_TYPES,
            terrain_display_name, graphical_terrain_display_name,
        )
        prov_terrain = self._project.map_data.provincial_terrain
        if pid in prov_terrain:
            ptype_key = prov_terrain[pid]
            terrain_obj = TERRAIN_TYPES.get(ptype_key)
            terrain_name = terrain_display_name(terrain_obj) if terrain_obj else ptype_key
        else:
            terrain_data = self._canvas.terrain_map[mask]
            if len(terrain_data) > 0:
                counts = np.bincount(terrain_data)
                # Skip index 0 (background/ocean), giving priority to non-zero terrain
                if len(counts) > 1 and counts[1:].max() > 0:
                    terrain_idx = int(counts[1:].argmax()) + 1
                else:
                    terrain_idx = int(counts.argmax())
                gt = GRAPHICAL_TERRAIN_BY_INDEX.get(terrain_idx)
                terrain_name = graphical_terrain_display_name(gt) if gt else tr("terrain_unknown")
            else:
                terrain_name = tr("terrain_unknown")

        info = {
            "ptype": ptype, "terrain": terrain_name,
            "pixels": pixels, "coastal": coastal,
        }
        self._province_info_cache[pid] = info
        return info

    # ═══════════════════════ State/Country Refresh ═══════════════

    def _refresh_state_list(self) -> None:
        country_mgr = self._project.country_mgr
        items = [
            (sid, s.name, len(s.provinces), country_mgr.get_owner_of_state(sid))
            for sid, s in self._project.state_mgr.states.items()
        ]
        self._panel.update_state_list(items)

    def _refresh_state_colors(self) -> None:
        if int(self._canvas.province_map.max()) == 0:
            return
        rgb = self._project.state_mgr.build_state_color_map(self._canvas.province_map)
        self._canvas.set_state_colors(rgb)
        # Name tag: Pass lazy provider, id graph construction is postponed until canvas anti-shake expires
        state_mgr = self._project.state_mgr
        self._canvas.set_name_label_data("state", lambda: (
            state_mgr.build_state_id_map(self._canvas.province_map),
            {sid: s.name for sid, s in state_mgr.states.items()},
        ))
        self._refresh_vp_data()
        # Statistics of unallocated land province → status bar prompt
        self._emit_unassigned_count()

    def _emit_unassigned_count(self) -> None:
        """Count the number of land provinces not allocated to state and send it to the status bar."""
        from data.constants import TILE_LAND
        tm = self._project.map_data.tile_map
        pm = self._canvas.province_map
        if pm is None or pm.max() == 0:
            return
        # All land province IDs
        land_pids = set(np.unique(pm[tm == TILE_LAND]).tolist())
        land_pids.discard(0)
        count = self._project.state_mgr.count_unassigned_provinces(land_pids)
        if count > 0:
            self._project.event_bus.emit(
                "status_message",
                text=tr("status_unassigned_warning", count)
            )
        else:
            self._project.event_bus.emit(
                "status_message", text=tr("status_all_assigned")
            )

    def _refresh_provincial_terrain_colors(self) -> None:
        """Calculate the gameplay terrain color of each province and pass it to canvas.
        Pixel color = the color corresponding to the province's provincial_terrain[pid].
        Provinces with no type specified are grayed out."""
        province_map = self._canvas.province_map
        if int(province_map.max()) == 0:
            return
        from data.terrain_types import TERRAIN_TYPES
        prov_terrain = self._project.map_data.provincial_terrain
        n = int(province_map.max()) + 1
        # pid → RGB (0=gray fallback)
        lookup = np.full((n, 3), 80, dtype=np.uint8)
        for pid, ptype in prov_terrain.items():
            if pid < n and ptype in TERRAIN_TYPES:
                r, g, b = TERRAIN_TYPES[ptype].color
                lookup[pid] = (r, g, b)
        # Color by province_map index
        rgb = lookup[province_map]
        self._canvas.set_provincial_terrain_colors(rgb)

    def _refresh_vp_data(self) -> None:
        vp_dict: dict[int, int] = {}
        name_dict: dict[int, str] = {}
        for state in self._project.state_mgr.states.values():
            for pid, vp_val in state.victory_points.items():
                if vp_val > 0:
                    vp_dict[pid] = vp_val
            for pid, name in state.vp_names.items():
                if name:
                    name_dict[pid] = name
        self._canvas.set_vp_data(vp_dict, name_dict)

    def set_vp_overlay_visible(self, mode: str, visible: bool) -> None:
        """Hydrate the canvas VP layer before a terrain editor shows it."""
        if visible:
            self._refresh_vp_data()
        self._canvas.set_vp_overlay_visible(mode, visible)

    def _refresh_country_list(self) -> None:
        self._panel.update_country_list(self._project.country_mgr.get_country_list())

    def _refresh_country_colors(self) -> None:
        if int(self._canvas.province_map.max()) == 0:
            return
        # Pass tile_map → let the builder use majority rule to identify land provinces and avoid ocean provinces being colored
        # Returns (rgb, assigned_mask): assigned_mask land pixels marked "Assigned Country"
        # → state renderer accordingly only draws white borders between allocated areas, skipping ocean/unallocated state
        rgb, assigned_mask = self._project.country_mgr.build_country_color_map(
            self._canvas.province_map,
            self._project.state_mgr,
            tile_map=self._canvas.tile_map,
        )
        self._canvas.set_country_colors(rgb, assigned_mask)
        # Name tag: Pass a lazy provider, and the serial number graph construction is postponed until the canvas anti-shake expires.
        country_mgr = self._project.country_mgr
        state_mgr = self._project.state_mgr
        self._canvas.set_name_label_data("country", lambda: (
            country_mgr.build_country_index_map(self._canvas.province_map, state_mgr)
        ))

    def _refresh_sr_colors(self) -> None:
        if int(self._canvas.province_map.max()) == 0:
            return
        rgb = self._project.strategic_region_mgr.build_sr_color_map(
            self._canvas.province_map, self._canvas.tile_map
        )
        self._canvas.set_sr_colors(rgb)

    def _refresh_continent_colors(self) -> None:
        if int(self._canvas.province_map.max()) == 0:
            return
        rgb = self._project.continent_mgr.build_continent_color_map(
            self._canvas.province_map,
            self._canvas.tile_map,
            state_manager=self._project.state_mgr,
        )
        self._canvas.set_continent_colors(rgb)

    def _on_railway_changed(self, event=None) -> None:
        if self._canvas.display_mode == "logistics":
            self._refresh_railway_colors()
            self._canvas.refresh_logistics_overlay()

    def _on_sr_colors_dirty(self, event=None) -> None:
        if self._canvas.display_mode == "strategic_region":
            self._refresh_sr_colors()
            self._canvas.refresh_display()

    def _refresh_railway_colors(self) -> None:
        if int(self._canvas.province_map.max()) == 0:
            return
        rgb = self._project.railway_mgr.build_railway_color_map(
            self._canvas.province_map
        )
        self._canvas.set_railway_colors(rgb)

    def update_province_count(self) -> int:
        """Returns the current number of provinces."""
        return int(self._canvas.province_map.max())

    # ═══════════════════════ EventBus Processor ═══════════════════

    def _on_render(self, event) -> None:
        full = event.data.get("full", False)
        bbox = event.data.get("bbox")
        self._canvas._rebind_aliases()
        # In province_terrain mode, refresh the color before rendering (attribute changes must be reflected immediately)
        if self._canvas.display_mode == "province_terrain":
            self._refresh_provincial_terrain_colors()
        if full or bbox is None:
            # Clear province boundary cache to ensure boundary lines are refreshed after merging/cutting
            self._canvas._border_cache = None
            if hasattr(self._canvas, '_border_base_pixmap'):
                self._canvas._border_base_pixmap = None
            self._canvas._full_render()
            self._canvas._render_province_overlay()
        else:
            x0, y0, x1, y1 = bbox
            self._canvas._partial_render(x0, y0, x1, y1)

    def _on_province_count(self, event) -> None:
        # Status bar updates are handled by MainWindow
        pass

    def _on_province_gaps(self, event) -> None:
        """Province ID hole change → Update tool panel + status bar prompt."""
        gap_ids = event.data.get("gap_ids", [])
        self._panel.update_province_gaps(gap_ids)
        # The status bar also prompts (you can see it no matter which page you are currently on)
        if gap_ids:
            self._event_bus.emit(
                "status_message",
                text=f"Missing province IDs: {len(gap_ids)} (splitting can restore them automatically)",
            )

    def _on_state_changed(self, event) -> None:
        """State data changes → Refresh UI."""
        action = event.data.get("action", "")
        if action == "refresh":
            self.invalidate_province_cache()
            self._refresh_state_list()
            self._refresh_state_colors()
        elif action == "modified":
            sid = event.data.get("state_id", 0)
            state = self._project.state_mgr.get_state(sid)
            if state:
                self._panel.update_state_info(
                    state.name, state.manpower, state.category
                )
            prop = event.data.get("property", "")
            if prop in ("", "provinces", "assign"):
                self._refresh_state_colors()
                # The province count [id] name (N) in the list item must also be refreshed, otherwise the allocation will not be updated when clicking on it.
                self._refresh_state_list()
        elif action == "selected":
            sid = event.data.get("state_id", 0)
            state = self._project.state_mgr.get_state(sid)
            if state:
                self._panel.update_state_info(
                    state.name, state.manpower, state.category
                )
                # Highlight all provinces in selected state
                self._canvas.set_batch_selection_pids(list(state.provinces))
                # Select the corresponding row in the list + update the _current_state_id of the page
                self._panel.select_state_in_list(sid)
                # Highlight the country that is the owner of the state on the canvas (state mode rendering will be overlaid with warm yellow)
                owner = self._project.country_mgr.get_owner_of_state(sid)
                country = self._project.country_mgr.get_country(owner) if owner else None
                if country is not None:
                    self._canvas.set_highlight_country(tuple(country.color))
                else:
                    self._canvas.set_highlight_country(None)
            else:
                self._canvas.set_batch_selection_pids([])
                self._canvas.set_highlight_country(None)

    def _on_country_changed(self, event) -> None:
        """Country data changes → Refresh UI."""
        action = event.data.get("action", "")
        tag = event.data.get("tag", "")
        if action in ("refresh", "created", "modified"):
            self._refresh_country_list()
            self._refresh_country_colors()
            if tag:
                self._update_country_info_panel(tag)
        elif action == "selected" and tag:
            self._update_country_info_panel(tag)
            # Click on the map (information mode) to select the country → list highlight + canvas highlight the country’s territory
            self._panel.select_country_in_list(tag)
            country = self._project.country_mgr.get_country(tag)
            if country and self._canvas.display_mode == "country":
                self._canvas.set_highlight_country(tuple(country.color))
        elif action == "assign_mode_reset":
            # Switch out of country mode → "Assign territories mode" button reset
            self._panel.reset_country_assign_mode()

    def _update_country_info_panel(self, tag: str) -> None:
        country = self._project.country_mgr.get_country(tag)
        if country:
            capital_name = f"Province {country.capital}" if country.capital > 0 else ""
            self._panel.update_country_info(
                country.tag, country.name, country.ruling_party,
                country.color, capital_name,
            )

    def _on_vp_changed(self, event) -> None:
        self._refresh_vp_data()

    def _on_continent_changed(self, event) -> None:
        """Continent list/assignment changes → Refresh colormap immediately if in continent mode."""
        if self._canvas.display_mode == "continent":
            self._refresh_continent_colors()
            self._canvas.refresh_display()

    def _on_province_regen(self, event) -> None:
        """Province Regeneration → Clear all color caches and force rebuilding the next time you switch modes."""
        self.invalidate_province_cache()
        self._canvas._state_color_rgb = None
        self._canvas._country_color_rgb = None
        self._canvas._sr_color_rgb = None
        self._canvas._railway_color_rgb = None
        self._canvas._provincial_terrain_color_rgb = None
        self._canvas._continent_color_rgb = None
        # Immediately refresh the color of the current mode (otherwise what you see before switching modes is the old one)
        mode = self._canvas.display_mode
        if mode == "state":
            self._refresh_state_colors()
        elif mode == "country":
            self._refresh_country_colors()
        elif mode == "strategic_region":
            self._refresh_sr_colors()
        elif mode == "logistics":
            self._refresh_railway_colors()
            self._canvas.refresh_logistics_overlay()

    # ═══════════════════════ Undo/Redo ═══════════════════════

    def _get_stroke_arrays(self) -> dict[str, np.ndarray]:
        """Get the array corresponding to the current mode, used for brush snapshots."""
        mode = self._canvas.display_mode
        if mode == "land":
            # When the density mask is turned on, the brush changes to density_map (overlayed on the land mode base map)
            md = self._project.map_data
            if (getattr(self._canvas, '_density_overlay_visible', False)
                    and md.density_map is not None):
                return {"density_map": md.density_map}
            return {"tile_map": self._canvas.tile_map}
        elif mode == "terrain":
            return {"terrain_map": self._canvas.terrain_map}
        elif mode == "height":
            return {"height_map": self._canvas.height_map}
        elif mode == "province":
            return {"province_map": self._canvas.province_map}
        elif mode == "river":
            return {"river_map": self._canvas.river_map}
        return {}

    def _get_all_arrays(self) -> dict[str, np.ndarray]:
        """Get all array references (required for undo/redo)."""
        arrays = {
            "tile_map": self._canvas.tile_map,
            "province_map": self._canvas.province_map,
            "terrain_map": self._canvas.terrain_map,
            "height_map": self._canvas.height_map,
            "river_map": self._canvas.river_map,
        }
        md = self._project.map_data
        if md.density_map is not None:
            arrays["density_map"] = md.density_map
        return arrays

    def on_stroke_started(self) -> None:
        """Brush Start — Record a pre-operation snapshot."""
        arrays = self._get_stroke_arrays()
        self._stroke_before = BrushStrokeCommand.snapshot_arrays(arrays)

    def on_stroke_ended(self) -> None:
        """Brush End - Compare changes, create Command and push to CommandHistory."""
        if self._stroke_before is None:
            return
        arrays = self._get_stroke_arrays()
        if BrushStrokeCommand.has_changes(self._stroke_before, arrays):
            after = BrushStrokeCommand.snapshot_arrays(arrays)
            mode = self._canvas.display_mode
            cmd = BrushStrokeCommand(f"Paint {mode}", self._stroke_before, after)
            cmd.set_target_arrays(self._get_all_arrays())
            # Push directly into the stack without calling execute (because the brush has been drawn)
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            if len(self._cmd_history._undo_stack) > self._cmd_history._max_size:
                self._cmd_history._undo_stack.pop(0)
            self._cmd_history._notify()
            self._project.mark_dirty()
            if mode == "province":
                self.invalidate_province_cache()
                pm = self._canvas.province_map
                max_pid = int(pm.max())
                existing = set(int(v) for v in np.unique(pm) if int(v) > 0)
                gaps = sorted(set(range(1, max_pid + 1)) - existing)
                self._event_bus.emit("province_count_changed", count=max_pid)
                self._event_bus.emit("province_gaps_changed", gap_ids=gaps)
        self._stroke_before = None

    def _refresh_brush_targets(self, cmd) -> None:
        """Recursively brush BrushStrokeCommands (including those nested within CompositeCommands) to the latest array reference."""
        from commands.composite import CompositeCommand
        if isinstance(cmd, BrushStrokeCommand):
            cmd.set_target_arrays(self._get_all_arrays())
        elif isinstance(cmd, CompositeCommand):
            for child in cmd.children:
                self._refresh_brush_targets(child)

    def undo(self) -> str:
        """Perform undo. Return status message."""
        # If there is an unfinished stroke, submit it first
        if self._stroke_before is not None:
            self.on_stroke_ended()

        if not self._cmd_history.can_undo:
            return "Nothing to undo"

        # Ensure that BrushStrokeCommand (within composite) has the latest array reference
        self._refresh_brush_targets(self._cmd_history._undo_stack[-1])

        self._cmd_history.undo()
        self._post_undo_redo_refresh()
        return "Undone"

    def redo(self) -> str:
        """Perform redo. Return status message."""
        if self._stroke_before is not None:
            self.on_stroke_ended()

        if not self._cmd_history.can_redo:
            return "Nothing to redo"

        self._refresh_brush_targets(self._cmd_history._redo_stack[-1])

        self._cmd_history.redo()
        self._post_undo_redo_refresh()
        return "Redone"

    def _post_undo_redo_refresh(self) -> None:
        """Refresh canvas after undo/redo + rebuild colormap by mode + notify all list refreshes."""
        mode = self._canvas.display_mode
        if mode == "logistics":
            self._refresh_railway_colors()
            self._canvas.refresh_logistics_overlay()
        elif mode == "state":
            self._refresh_state_colors()
        elif mode == "country":
            self._refresh_country_colors()
        elif mode == "strategic_region":
            self._refresh_sr_colors()
        elif mode == "continent":
            self._refresh_continent_colors()
        self._canvas.refresh_display()

        # Undo/redo may have changed the manager data - comprehensive emit to refresh all lists (low frequency operation, acceptable)
        bus = self._event_bus
        bus.emit("state_changed", state_id=0, action="refresh")
        bus.emit("country_changed", tag="", action="refresh")
        bus.emit("continent_changed", action="refresh")
        bus.emit("sr_colors_dirty")
        bus.emit("railway_changed")
        # The number of provinces and missing IDs may also change (such as partial rebirth)
        pm_max = int(self._canvas.province_map.max())
        bus.emit("province_count_changed", count=pm_max)
        import numpy as np
        if pm_max > 0:
            existing = set(np.unique(self._canvas.province_map).tolist()) - {0}
            gap_ids = sorted(set(range(1, pm_max + 1)) - existing)
            bus.emit("province_gaps_changed", gap_ids=gap_ids)

    # ═══════════════════════ Province click route ═══════════════════

    def on_province_clicked(self, pid: int) -> dict | None:
        """Province is clicked: calculation information + forwarded to current controller. Return province information dict."""
        if pid <= 0:
            return None
        info = self.calculate_province_info(pid)
        if self._current_controller is not None:
            self._current_controller.on_province_clicked(pid)
        return info

    def on_province_double_clicked(self, pid: int) -> None:
        if pid <= 0:
            return
        if self._current_controller is not None:
            self._current_controller.on_province_double_clicked(pid)
