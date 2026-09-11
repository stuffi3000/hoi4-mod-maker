"""Main window action processing - province generation/verification/country dialog/river/terrain/continent/strategic area/logistics.
Split from views/main_window.py and used as a mixin.

File operations (new/open/save/import/export/test export) are in views/main_window_file_ops.py."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PyQt5.QtWidgets import (
    QMessageBox, QApplication, QInputDialog, QColorDialog, QFileDialog,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor

from ui.i18n import tr
from views.main_window_file_ops import MainWindowFileOpsMixin

if TYPE_CHECKING:
    from controllers.country import CountryController
    from controllers.default_map import DefaultMapController
    from controllers.logistics import LogisticsController


# ── Background thread ──

class _GenerateThread(QThread):
    """Background thread generates provinces"""
    finished = pyqtSignal(object, int)
    error = pyqtSignal(str)

    def __init__(self, tile_map, count, province_map=None, incremental=False,
                 sea_scale=0.15, lake_scale=0.3, density_map=None,
                 skip_mismatch_clear=False, generation_scope="all"):
        super().__init__()
        self._tile_map = tile_map.copy()
        self._count = count
        self._province_map = province_map.copy() if province_map is not None else None
        self._incremental = incremental
        self._generation_scope = generation_scope
        self._sea_scale = sea_scale
        self._lake_scale = lake_scale
        self._density_map = density_map.copy() if density_map is not None else None
        self._skip_mismatch_clear = skip_mismatch_clear

    def run(self):
        try:
            if self._incremental and self._province_map is not None:
                from domain.generators.province import generate_provinces_incremental
                pm, cnt = generate_provinces_incremental(
                    self._tile_map, self._province_map,
                    skip_mismatch_clear=self._skip_mismatch_clear,
                )
            elif self._generation_scope != "all":
                from data.constants import TILE_LAKE, TILE_LAND, TILE_SEA
                from domain.generators.province import generate_provinces_for_type

                type_by_scope = {
                    "land": TILE_LAND,
                    "sea": TILE_SEA,
                    "lake": TILE_LAKE,
                }
                tile_type = type_by_scope.get(self._generation_scope)
                if tile_type is None:
                    raise ValueError(f"Unknown province generation scope: {self._generation_scope}")
                existing = (
                    self._province_map
                    if self._province_map is not None
                    else np.zeros_like(self._tile_map, dtype=np.int32)
                )
                pm, cnt = generate_provinces_for_type(
                    self._tile_map,
                    existing,
                    tile_type,
                    self._count,
                    density_map=self._density_map,
                )
            else:
                from domain.generators.province import generate_provinces
                pm, cnt = generate_provinces(
                    self._tile_map, self._count,
                    sea_scale=self._sea_scale,
                    lake_scale=self._lake_scale,
                    density_map=self._density_map,
                )
            self.finished.emit(pm, cnt)
        except Exception as e:
            self.error.emit(str(e))


class _ValidateThread(QThread):
    """Background thread verification province"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, tile_map, province_map):
        super().__init__()
        self._tile_map = tile_map.copy()
        self._province_map = province_map.copy()

    def run(self):
        try:
            from domain.validators.province import validate_provinces
            results = validate_provinces(self._tile_map, self._province_map)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class MainWindowActionsMixin(MainWindowFileOpsMixin):
    """Province generation/validation/country dialog/rivers/terrain/continent/strategic areas/logistics."""

    # ═══════════════════════ State Auto Grouping ═══════════════════

    def _on_auto_states_with_confirm(self, per_state: int) -> None:
        """Confirm before automatic grouping (will clear existing state data). Can be undone (Ctrl+Z)."""
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        existing = len(self._project.state_mgr.states)
        if existing > 0:
            reply = QMessageBox.question(
                self,
                "Confirm Automatic State Grouping",
                f"There are currently {existing} states.\nAutomatic grouping will clear all existing state data and regroup provinces at {per_state} provinces per state.\n\nContinue?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        # Undo snapshot: state_mgr internal field
        state_mgr = self._project.state_mgr
        snap_fields = [f for f in ("_states", "_next_id") if hasattr(state_mgr, f)]
        cmd = ManagerSnapshotCommand("Automatically group states", state_mgr, snap_fields)
        self._controllers["state"].auto_states(per_state)
        cmd.capture_after()
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()

    # ═══════════════════════ Strategic area automatically generated ═══════════════════

    def _on_auto_sr_with_confirm(self) -> None:
        """Confirm before automatically generating strategic areas. Can be undone (Ctrl+Z)."""
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        existing = self._project.strategic_region_mgr.count()
        if existing > 0:
            reply = QMessageBox.question(
                self,
                "Confirm Automatic Generation",
                f"There are currently {existing} strategic regions.\nAutomatic generation will clear all existing strategic-region data.\n\nContinue?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        # Undo snapshot: strategic_region_mgr internal field
        sr_mgr = self._project.strategic_region_mgr
        snap_fields = [f for f in ("_regions", "_next_id") if hasattr(sr_mgr, f)]
        cmd = ManagerSnapshotCommand("Automatically generate strategic regions", sr_mgr, snap_fields)
        self._controllers["strategic_region"].auto_generate()
        cmd.capture_after()
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()
        self._refresh_sr_list()
        self._event_bus.emit("sr_colors_dirty")

    # ═══════════════════════ Province generation and verification ═══════════════════

    @staticmethod
    def _reference_image_filter() -> str:
        return "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All Files (*)"

    def _pick_reference_image(self, title: str) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self, title, "", self._reference_image_filter()
        )
        return path

    def _choose_reference_colors(self, path: str, operation: str):
        """Open the shared image palette editor after a reference is picked."""
        from views.reference_color_dialog import ReferenceColorMappingDialog

        return ReferenceColorMappingDialog.choose(self, path, operation)

    def _run_reference_analysis(self, callback):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            QApplication.processEvents()
            return callback()
        finally:
            QApplication.restoreOverrideCursor()

    def _on_auto_land_from_reference(self) -> None:
        """Replace land/sea tiles from a full-map image as one undo step."""
        path = self._pick_reference_image(tr("land_auto_ref_dialog"))
        if not path:
            return
        try:
            from services.reference_map_service import (
                load_reference_rgb, generate_land_water_from_rgb,
            )
            from commands.map.apply_reference import ApplyReferenceLayersCommand
            map_data = self._project.map_data
            selection = self._choose_reference_colors(path, "land")
            if selection is None:
                return
            new_tiles = self._run_reference_analysis(
                lambda: generate_land_water_from_rgb(
                    load_reference_rgb(path, map_data.tile_map.shape),
                    land_colors=selection.colors.get("land"),
                    sea_colors=selection.colors.get("sea"),
                    lake_colors=selection.colors.get("lake"),
                    color_tolerance=selection.tolerance,
                )
            )
            self._cmd_history.execute(ApplyReferenceLayersCommand(
                map_data, {"tile_map": new_tiles}, tr("land_auto_ref_dialog")
            ))
            self._canvas.new_land_mask[:] = False
            self._project.mark_dirty()
            self._project.mark_assets_dirty(
                "map/terrain/colormap_rgb_cityemissivemask_a.dds",
                "map/terrain/colormap_water_0.dds",
                "map/terrain/colormap_water_1.dds",
                "map/terrain/colormap_water_2.dds",
                "map/terrain/fow_rgb_waterspec_a.dds",
                "map/world_normal.bmp",
            )
            self._canvas.refresh_display()
            counts = map_data.get_tile_counts()
            self._status_info.setText(tr(
                "land_auto_ref_done",
                land=counts["land"],
                sea=counts["sea"],
                lake=counts["lake"],
            ))
        except Exception as exc:
            QMessageBox.critical(self, tr("dlg_error"), str(exc))

    def _on_auto_provinces_from_reference(self) -> None:
        """Replace province IDs with regions enclosed by reference outlines."""
        if int(self._project.map_data.province_map.max()) > 0:
            answer = QMessageBox.question(
                self,
                tr("province_auto_ref_confirm_title"),
                tr("province_auto_ref_confirm"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        path = self._pick_reference_image(tr("province_auto_ref_dialog"))
        if not path:
            return
        try:
            from services.reference_map_service import (
                load_reference_rgb,
                generate_provinces_from_rgb,
                validate_and_repair_generated_provinces,
            )
            from commands.map.apply_reference import ApplyReferenceLayersCommand
            map_data = self._project.map_data
            selection = self._choose_reference_colors(path, "province")
            if selection is None:
                return

            def generate():
                rgb = load_reference_rgb(path, map_data.province_map.shape)
                generated_map, _generated_count = generate_provinces_from_rgb(
                    rgb,
                    map_data.tile_map,
                    land_province_colors=selection.colors.get("land_province"),
                    sea_province_colors=selection.colors.get("sea_province"),
                    color_tolerance=selection.tolerance,
                )
                return validate_and_repair_generated_provinces(
                    map_data.tile_map,
                    generated_map,
                )

            province_map, report = self._run_reference_analysis(generate)
            self._cmd_history.execute(ApplyReferenceLayersCommand(
                map_data,
                {"province_map": province_map},
                tr("province_auto_ref_dialog"),
            ))
            self._project.mark_dirty()
            self._app.invalidate_province_cache()
            self._canvas.select_province(0)
            self._update_province_count()
            self._canvas.refresh_display()
            imported_total = int(report.get("imported_total", 0))
            self._status_info.setText(tr("province_auto_ref_done", count=imported_total))
            self._show_reference_province_report(report)
        except Exception as exc:
            QMessageBox.critical(self, tr("dlg_error"), str(exc))

    def _show_reference_province_report(self, report: dict) -> None:
        """Show imported type counts and the automatic validation repairs."""
        imported = report.get("imported_counts", {})
        repairs = report.get("repair_counts", {})
        message = tr(
            "province_auto_ref_report",
            land=int(imported.get("land", 0)),
            sea=int(imported.get("sea", 0)),
            lake=int(imported.get("lake", 0)),
            modified=int(report.get("modified_count", 0)),
            border_adjusted=int(repairs.get("border_adjusted", 0)),
            too_small_merged=int(repairs.get("too_small_merged", 0)),
            too_small_removed=int(repairs.get("too_small_removed", 0)),
            not_contiguous=int(repairs.get("not_contiguous", 0)),
            too_large_split=int(repairs.get("too_large_split", 0)),
            id_gaps=int(repairs.get("id_gaps", 0)),
            remaining=int(report.get("remaining_issue_count", 0)),
            coastal=int(report.get("validation_after", {}).get("coastal_mismatch", 0)),
        )
        QMessageBox.information(self, tr("province_auto_ref_report_title"), message)

    def _on_random_split_selected(self, target_count: int) -> None:
        """Split the current multi-selection into a requested total piece count."""
        selected = self._canvas.selected_province_ids()
        if not selected:
            QMessageBox.information(
                self, tr("province_btn_random_split"),
                "Select at least one province first.",
            )
            return
        if target_count <= len(selected):
            QMessageBox.information(
                self, tr("province_btn_random_split"),
                "Total pieces must be greater than the number of selected provinces.",
            )
            return
        try:
            from services.reference_map_service import split_selected_provinces_randomly
            from commands.province.random_split import RandomSplitProvincesCommand
            new_map, parents = self._run_reference_analysis(
                lambda: split_selected_provinces_randomly(
                    self._project.map_data.province_map,
                    selected,
                    target_count,
                )
            )
            command = RandomSplitProvincesCommand(self._project, new_map, parents)
            self._cmd_history.execute(command)
            self._project.mark_dirty()
            self._app.invalidate_province_cache()
            output_selection = selected | set(parents)
            self._canvas.select_province(0)
            for pid in sorted(output_selection):
                self._canvas.select_province(pid, additive=True)
            self._canvas.set_batch_selection_pids(output_selection)
            self._update_province_count()
            self._event_bus.emit("state_changed", state_id=0, action="refresh")
            self._event_bus.emit("continent_changed", action="refresh")
            self._event_bus.emit("sr_colors_dirty")
            self._canvas.refresh_display()
            self._status_info.setText(tr(
                "province_random_split_done",
                selected=len(selected),
                count=target_count,
            ))
        except Exception as exc:
            QMessageBox.critical(self, tr("dlg_error"), str(exc))

    def _on_auto_hydrology_from_reference(self) -> None:
        """Generate lake tiles and an indexed river layer together."""
        if int(self._project.map_data.province_map.max()) > 0:
            answer = QMessageBox.question(
                self,
                tr("river_auto_ref_dialog"),
                "Generating lakes changes tile types. Reimport or regenerate provinces afterwards so provinces do not cross land and lakes. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        path = self._pick_reference_image(tr("river_auto_ref_dialog"))
        if not path:
            return
        try:
            from services.reference_map_service import (
                load_reference_rgb, generate_hydrology_from_rgb,
            )
            from commands.map.apply_reference import ApplyReferenceLayersCommand
            map_data = self._project.map_data
            selection = self._choose_reference_colors(path, "hydrology")
            if selection is None:
                return

            def generate():
                rgb = load_reference_rgb(path, map_data.tile_map.shape)
                return generate_hydrology_from_rgb(
                    rgb,
                    map_data.tile_map,
                    lake_colors=selection.colors.get("lake"),
                    river_colors=selection.colors.get("river"),
                    color_tolerance=selection.tolerance,
                )

            new_tiles, river_map, stats = self._run_reference_analysis(generate)
            self._cmd_history.execute(ApplyReferenceLayersCommand(
                map_data,
                {"tile_map": new_tiles, "river_map": river_map},
                tr("river_auto_ref_dialog"),
            ))
            self._project.mark_dirty()
            self._project.mark_assets_dirty(
                "map/terrain/colormap_rgb_cityemissivemask_a.dds",
                "map/terrain/colormap_water_0.dds",
                "map/terrain/colormap_water_1.dds",
                "map/terrain/colormap_water_2.dds",
                "map/terrain/fow_rgb_waterspec_a.dds",
                "map/world_normal.bmp",
            )
            self._canvas.refresh_display()
            self._status_info.setText(tr(
                "river_auto_ref_done",
                lakes=stats["lake_pixels"],
                rivers=stats["river_pixels"],
                networks=stats["river_networks"],
            ))
        except Exception as exc:
            QMessageBox.critical(self, tr("dlg_error"), str(exc))

    def _on_clear_new_land_mask(self) -> None:
        """Clear the extended land mask (keep the painted land pixels)."""
        mask = self._canvas.new_land_mask
        if not mask.any():
            return
        mask[:] = False
        self._status_info.setText(tr("status_extend_mask_cleared"))

    def _on_generate_provinces(
        self, scope: str | int = "all", count: int | None = None
    ) -> None:
        # Keep the old one-argument call (used by the Tools menu and embedders)
        # as an alias for generating all province types.
        if isinstance(scope, int):
            count = scope
            scope = "all"
        scope = str(scope).lower()
        if scope not in {"all", "land", "sea", "lake"}:
            QMessageBox.critical(self, tr("dlg_error"), f"Unknown province generation scope: {scope}")
            return
        if count is None:
            from data.constants import DEFAULT_PROVINCES
            count = DEFAULT_PROVINCES
        count = max(1, int(count))

        incremental = False
        has_provinces = int(self._canvas.province_map.max()) > 0

        # R-NULL: Expanding the mask is meaningless when there are no provinces - automatically clear it to avoid misleading
        if not has_provinces and self._canvas.new_land_mask.any():
            self._canvas.new_land_mask[:] = False
            self._status_info.setText(tr("status_no_prov_mask_ignored"))

        if scope == "all" and has_provinces:
            reply = QMessageBox.question(
                self, tr("dlg_gen_mode_title"),
                tr("dlg_gen_mode_body"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            incremental = (reply == QMessageBox.StandardButton.Yes)

        if scope != "all":
            from data.constants import TILE_LAKE, TILE_LAND, TILE_SEA
            scope_tile_type = {
                "land": TILE_LAND,
                "sea": TILE_SEA,
                "lake": TILE_LAKE,
            }[scope]
            selected = self._canvas.tile_map == scope_tile_type
            if not np.any(selected):
                QMessageBox.information(
                    self,
                    tr("province_generation_empty_title"),
                    tr("province_generation_empty", scope=scope),
                )
                return
            if np.any(selected & (self._canvas.province_map > 0)):
                reply = QMessageBox.question(
                    self,
                    tr("province_generation_scope_confirm_title"),
                    tr("province_generation_scope_confirm", scope=scope),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

        scope_label = tr(f"province_scope_{scope}")
        self._status_info.setText(
            tr("status_generating_scope_bg", scope=scope_label)
        )
        QApplication.processEvents()

        # Read density parameters from the Provinces page.
        sea_scale = 0.15
        lake_scale = 0.3
        density_map = self._project.map_data.density_map
        if hasattr(self._tool_panel, '_province_page') and self._tool_panel._province_page is not None:
            params = self._tool_panel._province_page.get_generation_params()
            sea_scale = params.get("sea_scale", 0.15)
            lake_scale = params.get("lake_scale", 0.3)

        # Incremental mode: Preclear pixels with the new world brush mask
        province_map_for_thread = None
        if incremental:
            province_map_for_thread = self._canvas.province_map.copy()
            mask = self._canvas.new_land_mask
            if mask.any():
                # Save a copy for _on_generate_done to synchronize the terrain, and clear it immediately so the user can draw the next batch
                self._new_land_mask_copy = mask.copy()
                province_map_for_thread[mask] = 0
                self._canvas.new_land_mask[:] = False

        if scope != "all":
            # The type-specific generator keeps all other tile types and
            # allocates new IDs after the preserved map.
            province_map_for_thread = self._canvas.province_map.copy()

        has_new_land_mask = incremental and getattr(self, '_new_land_mask_copy', None) is not None and self._new_land_mask_copy.any()
        self._gen_thread = _GenerateThread(
            self._canvas.tile_map, count,
            province_map=province_map_for_thread,
            incremental=incremental,
            sea_scale=sea_scale,
            lake_scale=lake_scale,
            density_map=density_map,
            skip_mismatch_clear=has_new_land_mask,
            generation_scope=scope,
        )
        self._gen_thread.finished.connect(self._on_generate_done)
        self._gen_thread.error.connect(self._on_generate_error)
        self._gen_thread.start()

    def _on_generate_done(self, province_map, count: int) -> None:
        was_incremental = getattr(self._gen_thread, '_incremental', False)
        generation_scope = getattr(self._gen_thread, '_generation_scope', 'all')
        is_partial = generation_scope != "all"
        self._canvas.province_map = province_map
        self._project.mark_dirty()
        self._update_province_count()

        # When an event occurs, cascade cleanup is automatically handled by each controller.
        self._event_bus.emit(
            "province_map_regenerated",
            incremental=was_incremental or is_partial,
            scope=generation_scope,
        )

        # Force refresh the canvas (incremental mode does not switch mode, maintain the state of the New World brush tool)
        self._canvas.refresh_display()

        # After incremental generation: synchronize terrain + clean up swallowed provinces + automatic allocation + clear brush mask
        if was_incremental or is_partial:
            import numpy as np
            from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
            from data.terrain_types import TERRAIN_PALETTE_INDEX, DEFAULT_TERRAIN_FOR_TILE

            # Synchronize terrain_map (uses saved copy of mask, does not rely on canvas.new_land_mask)
            saved_mask = getattr(self, '_new_land_mask_copy', None) if was_incremental else None
            if saved_mask is not None and saved_mask.any():
                tm = self._canvas.tile_map
                terrain_map = self._project.map_data.terrain_map
                for tile_type in (TILE_LAND, TILE_SEA, TILE_LAKE):
                    t_name = DEFAULT_TERRAIN_FOR_TILE.get(tile_type)
                    if t_name and t_name in TERRAIN_PALETTE_INDEX:
                        t_mask = saved_mask & (tm == tile_type)
                        if np.any(t_mask):
                            terrain_map[t_mask] = TERRAIN_PALETTE_INDEX[t_name]
                self._new_land_mask_copy = None

            consumed = self._cleanup_consumed_provinces(province_map)
            assigned = (
                self._auto_assign_new_provinces(province_map)
                if generation_scope in {"all", "land"}
                else 0
            )
            msg = tr(
                "status_gen_scope_done",
                scope=tr(f"province_scope_{generation_scope}"),
                count=count,
            )
            msg += f" ({assigned} new provinces assigned automatically)"
            if consumed:
                ids_str = ", ".join(str(i) for i in sorted(consumed)[:10])
                if len(consumed) > 10:
                    ids_str += f" ... {len(consumed)} total"
                msg += f"\n⚠ Fully absorbed provinces: {ids_str}"
            self._status_info.setText(msg)
        else:
            self._status_info.setText(tr("status_gen_done").format(count=count))

    def _cleanup_consumed_provinces(self, province_map) -> set[int]:
        """Clean up fully annexed provinces: Remove non-existent province references from state/country/strategic area."""
        import numpy as np

        existing_pids = set(np.unique(province_map).tolist())
        existing_pids.discard(0)
        consumed: set[int] = set()

        state_mgr = self._project.state_mgr
        sr_mgr = self._project.strategic_region_mgr
        country_mgr = self._project.country_mgr

        # Clean up state references
        for sid, state in list(state_mgr.states.items()):
            old_provinces = state.provinces
            new_provinces = [p for p in old_provinces if p in existing_pids]
            removed = set(old_provinces) - set(new_provinces)
            if removed:
                consumed.update(removed)
                state.provinces = new_provinces
                if not new_provinces:
                    state_mgr.states.pop(sid, None)

        # Rebuild province_to_state index
        if consumed and hasattr(state_mgr, '_province_to_state'):
            state_mgr._province_to_state = {
                pid: sid for sid, s in state_mgr.states.items()
                for pid in s.provinces
            }

        # Clean up strategic area references
        if sr_mgr:
            for r in sr_mgr.regions.values():
                r.province_ids = [p for p in r.province_ids if p in existing_pids]

        # Clean up national capital citations
        if country_mgr:
            for tag, country in country_mgr.countries.items():
                if country.capital > 0 and country.capital not in existing_pids:
                    consumed.add(country.capital)
                    # Find another province in the country to use as the new capital
                    new_cap = 0
                    owned_states = country_mgr.get_states_of_country(tag)
                    if state_mgr and owned_states:
                        for osid in owned_states:
                            s = state_mgr.get_state(osid)
                            if s and s.provinces:
                                new_cap = s.provinces[0]
                                break
                    country.capital = new_cap

        return consumed

    def _auto_assign_new_provinces(self, province_map) -> int:
        """After incremental generation, land provinces without states are assigned to the nearest adjacent state/strategic area."""
        import numpy as np
        from data.constants import TILE_LAND

        state_mgr = self._project.state_mgr
        sr_mgr = self._project.strategic_region_mgr
        tile_map = self._canvas.tile_map
        pm = province_map

        # Find land provinces without assigned state
        max_pid = int(pm.max())
        if max_pid == 0:
            return 0

        assigned_count = 0
        # Precomputed centroid
        flat = pm.ravel()
        n = max_pid + 1
        pid_count = np.bincount(flat, minlength=n)
        ys, xs = np.mgrid[0:pm.shape[0], 0:pm.shape[1]]
        sum_y = np.bincount(flat, weights=ys.ravel().astype(np.float64), minlength=n)
        sum_x = np.bincount(flat, weights=xs.ravel().astype(np.float64), minlength=n)

        # Provinces with state → centroid
        state_centers: dict[int, tuple[float, float]] = {}  # state_id → (cy, cx)
        for sid, state in state_mgr.states.items():
            total_y, total_x, cnt = 0.0, 0.0, 0
            for p in state.provinces:
                if 0 < p < n and pid_count[p] > 0:
                    total_y += sum_y[p] / pid_count[p]
                    total_x += sum_x[p] / pid_count[p]
                    cnt += 1
            if cnt > 0:
                state_centers[sid] = (total_y / cnt, total_x / cnt)

        # For each unallocated land province, find the nearest state
        for pid in range(1, max_pid + 1):
            if pid_count[pid] == 0:
                continue
            # Check if it is land
            cy = int(sum_y[pid] / pid_count[pid])
            cx = int(sum_x[pid] / pid_count[pid])
            cy = min(cy, pm.shape[0] - 1)
            cx = min(cx, pm.shape[1] - 1)
            if int(tile_map[cy, cx]) != TILE_LAND:
                continue
            # Existing state → skip
            if state_mgr.get_state_of_province(pid) > 0:
                continue

            # Find the latest state
            best_sid, best_dist = 0, float('inf')
            py = sum_y[pid] / pid_count[pid]
            px = sum_x[pid] / pid_count[pid]
            for sid, (sy, sx) in state_centers.items():
                d = (py - sy) ** 2 + (px - sx) ** 2
                if d < best_dist:
                    best_dist = d
                    best_sid = sid
            if best_sid > 0:
                state = state_mgr.get_state(best_sid)
                if state:
                    state.provinces.append(pid)
                    state_mgr._province_to_state[pid] = best_sid
                    assigned_count += 1

            # The same goes for strategic areas
            if sr_mgr.get_region_of_province(pid) == 0:
                # Find the nearest strategic area
                best_rid, best_dist = 0, float('inf')
                for rid, region in sr_mgr._regions.items():
                    if not region.province_ids:
                        continue
                    # Calculate the distance using the first province with pixels
                    for rp in region.province_ids[:5]:
                        if 0 < rp < n and pid_count[rp] > 0:
                            ry = sum_y[rp] / pid_count[rp]
                            rx = sum_x[rp] / pid_count[rp]
                            d = (py - ry) ** 2 + (px - rx) ** 2
                            if d < best_dist:
                                best_dist = d
                                best_rid = rid
                            break
                if best_rid > 0:
                    sr_mgr._regions[best_rid].province_ids.append(pid)

        return assigned_count

    def _on_generate_error(self, msg: str) -> None:
        QMessageBox.critical(self, tr("dlg_error"), msg)
        self._status_info.setText(tr("status_ready"))

    def _on_land_paint_confirm(self) -> None:
        """Draw land and sea for the first time after the province has been generated → pop up the confirmation box.

        The canvas calls this method synchronously via a direct signal, and the result has been written back when it returns.
        canvas._land_paint_confirmed, the canvas decides whether to draw this stroke accordingly."""
        ret = QMessageBox.warning(
            self, tr("land_paint_after_gen_title"),
            tr("land_paint_after_gen_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self._canvas._land_paint_confirmed = True

    def _on_smooth_coast(self) -> None:
        """Smooth coastline. If there is a selection, only the selected area will be smoothed, otherwise the entire image will be smoothed. Can be undone (Ctrl+Z)."""
        from domain.generators.coastline import smooth_coastline
        from commands.land.brush_stroke import BrushStrokeCommand
        map_data = self._project.map_data

        # Check whether there is a selection on the canvas (the area selected by the transform tool)
        sel = getattr(self._canvas, '_selection_rect', None)
        has_provinces = int(self._canvas.province_map.max()) > 0

        # Strong warning when already having provinces: Smoothing will dislocate tile/province boundaries
        if has_provinces:
            ret = QMessageBox.warning(
                self, tr("smooth_coast_after_gen_title"),
                tr("smooth_coast_after_gen_msg"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return
        elif not sel:
            # No provinces + full map: regular confirmation
            ret = QMessageBox.question(
                self, tr("smooth_coast_confirm_title"),
                tr("smooth_coast_confirm_msg"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return
        if sel:
            x0, y0, x1, y1 = sel
            # Convert to integer pixel coordinates (region parameters are y0, x0, y1, x1)
            region = (int(y0), int(x0), int(y1), int(x1))
        else:
            region = None

        # Undo Snapshot: Before Operation
        snap_arrays = {"tile_map": map_data.tile_map}
        before = BrushStrokeCommand.snapshot_arrays(snap_arrays)

        new_tile = smooth_coastline(map_data.tile_map, region=region)
        map_data.tile_map[:] = new_tile

        # Undo snapshot: after operation + push to stack
        if BrushStrokeCommand.has_changes(before, snap_arrays):
            after = BrushStrokeCommand.snapshot_arrays(snap_arrays)
            cmd = BrushStrokeCommand("Smooth coastline", before, after)
            cmd.set_target_arrays(self._app._get_all_arrays())
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()

        self._canvas.tile_map = map_data.tile_map
        self._canvas._full_render()
        self._project.mark_dirty()
        if region:
            self._status_info.setText(tr("status_coast_smoothed_region"))
        else:
            self._status_info.setText(tr("status_coast_smoothed"))

    def _on_density_clear(self) -> None:
        """Clear the density map and restore uniformity. Density masks retain their current visibility."""
        # Fool-proof: double confirmation (clearing data cannot be undone)
        ret = QMessageBox.question(
            self, tr("density_clear_confirm_title"),
            tr("density_clear_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._project.map_data.density_map = None
        # Refresh the mask content (overlay will be automatically hidden when density_map=None)
        self._canvas._render_density_overlay()
        self._status_info.setText(tr("status_density_cleared"))

    def _on_quick_init(self) -> None:
        """One-click initialization: automatically generate states + strategic regions + default countries. Can be undone (Ctrl+Z)."""
        from commands.map.quick_init import QuickInitCommand
        pm = self._canvas.province_map
        if int(pm.max()) == 0:
            QMessageBox.warning(self, tr("dlg_quick_init_title"), tr("dlg_quick_init_no_provinces"))
            return

        reply = QMessageBox.question(
            self, tr("dlg_quick_init_title"),
            tr("dlg_quick_init_body"),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._status_info.setText(tr("status_initializing"))
        QApplication.processEvents()

        # Undo snapshot: before operation (capture the initial state of the three managers)
        cmd = QuickInitCommand(
            self._project.state_mgr,
            self._project.country_mgr,
            self._project.strategic_region_mgr,
        )

        try:
            from views.export_dialog import auto_complete_project

            class _FakeCanvas:
                def __init__(self, md):
                    self.map_data = md
                    self.province_map = md.province_map
                    self.tile_map = md.tile_map
                    self.terrain_map = md.terrain_map
                    self.height_map = md.height_map
                    self.river_map = md.river_map

            fc = _FakeCanvas(self._project.map_data)
            log = auto_complete_project(self._project, fc)

            # Capture after state + push to undo stack
            cmd.capture_after()
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()

            self._canvas.refresh_display()
            msg = tr("dlg_quick_init_done") + "\n".join(f"- {l}" for l in log)
            self._status_info.setText(tr("status_init_done"))
            QMessageBox.information(self, tr("dlg_quick_init_title"), msg)
        except Exception as e:
            import traceback
            QMessageBox.critical(self, tr("dlg_init_failed"), f"{e}\n\n{traceback.format_exc()}")

    def _on_validate(self) -> None:
        self._status_info.setText(tr("status_validating"))
        QApplication.processEvents()

        self._validate_thread = _ValidateThread(
            self._canvas.tile_map, self._canvas.province_map
        )
        self._validate_thread.finished.connect(self._on_validate_done)
        self._validate_thread.error.connect(self._on_validate_error)
        self._validate_thread.start()

    def _on_validate_done(self, results: dict) -> None:
        self._show_validation_results(results)
        self._status_info.setText(tr("status_ready"))

    def _on_validate_error(self, msg: str) -> None:
        QMessageBox.critical(self, tr("dlg_error"), msg)
        self._status_info.setText(tr("status_ready"))

    def _show_validation_results(self, results: dict) -> None:
        """Diagnostic dialog: clickable problem list, double-click to jump"""
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QListWidget, QListWidgetItem,
            QLabel, QDialogButtonBox,
        )
        from PyQt5.QtCore import Qt as _Qt

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("validate_title"))
        dlg.resize(520, 520)
        v = QVBoxLayout(dlg)

        province_count = int(self._canvas.province_map.max())
        coastal_count = results.get("coastal_mismatch", 0)
        warn = results.get("count_warning", "")
        info_text = tr("validate_info").format(total=province_count, coastal=coastal_count)
        if warn:
            info_text += f"\n⚠ {warn}"
        v.addWidget(QLabel(info_text))

        v.addWidget(QLabel(tr("validate_double_click_hint")))
        list_w = QListWidget()
        v.addWidget(list_w)

        def add_item(text: str, jump_type: str, data) -> None:
            it = QListWidgetItem(text)
            it.setData(_Qt.ItemDataRole.UserRole, (jump_type, data))
            list_w.addItem(it)

        x_positions = results.get("x_crossing_positions", [])
        for i, (y, x) in enumerate(x_positions[:50]):
            add_item(f"X-crossing #{i+1} at ({x}, {y})", "xy", (x, y))
        if len(x_positions) > 50:
            add_item(tr("validate_more_xcrossing").format(n=len(x_positions)-50), "none", None)

        for pid in results.get("too_small_ids", [])[:50]:
            add_item(tr("validate_too_small_item").format(pid=pid), "pid", pid)
        for pid in results.get("not_contiguous_ids", [])[:50]:
            add_item(tr("validate_not_contiguous_item").format(pid=pid), "pid", pid)
        for pid in results.get("too_large_ids", [])[:50]:
            add_item(tr("validate_too_large_item").format(pid=pid), "pid", pid)
        gaps = results.get("id_gaps", [])
        if gaps:
            add_item(tr("validate_id_gaps").format(n=len(gaps)), "none", None)
        if list_w.count() == 0:
            list_w.addItem(tr("validate_no_issues"))

        def on_double(item: QListWidgetItem) -> None:
            payload = item.data(_Qt.ItemDataRole.UserRole)
            if not payload:
                return
            jump_type, data = payload
            if jump_type == "xy":
                self._canvas.center_on_pixel(data[0], data[1], zoom=4.0)
            elif jump_type == "pid":
                self._canvas.center_on_province(data)

        list_w.itemDoubleClicked.connect(on_double)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)
        dlg.exec_()

    # ═══════════════════════ Country Dialog ═══════════════════

    def _on_create_country(self) -> None:
        tag, ok = QInputDialog.getText(self, tr("country_create_btn"), tr("dlg_country_tag_prompt"))
        if not ok or not tag:
            return
        tag = tag.upper().strip()[:3]
        if len(tag) != 3 or not tag.isalpha():
            QMessageBox.warning(self, tr("dlg_error"), tr("country_tag_invalid"))
            return

        name, ok = QInputDialog.getText(self, tr("country_create_btn"), tr("dlg_country_name_prompt").format(tag=tag))
        if not ok:
            return

        import random
        default_color = QColor(
            random.randint(60, 220), random.randint(60, 220), random.randint(60, 220)
        )
        chosen = QColorDialog.getColor(default_color, self, tr("dlg_country_pick_color").format(tag=tag))
        if not chosen.isValid():
            return
        color = (chosen.red(), chosen.green(), chosen.blue())

        ctrl: CountryController = self._controllers["country"]
        if not ctrl.create_country(tag, name or tag, color):
            QMessageBox.warning(self, tr("dlg_error"), tr("dlg_country_create_failed"))

    def _on_quick_create_country(self, tag: str, name: str, party: str) -> None:
        color = getattr(self._tool_panel, '_quick_create_color', (100, 100, 200))
        ctrl: CountryController = self._controllers["country"]
        if ctrl.create_country(tag, name, color, party):
            # After the founding of the country, it is natural to enclose territory → automatically turn on the territory allocation mode (button to move signal synchronization controller)
            self._tool_panel.set_country_assign_mode(True)

    def _on_country_highlight(self, tag: str) -> None:
        """When switching the selected country, pass the country's RGB to the canvas, and the country renderer will highlight the country's pixels."""
        if not tag:
            self._canvas.set_highlight_country(None)
            return
        country = self._project.country_mgr.get_country(tag)
        if country is None:
            self._canvas.set_highlight_country(None)
            return
        self._canvas.set_highlight_country(tuple(country.color))

    def _on_country_property_change(self, tag: str, prop: str, val) -> None:
        """Modify country attributes. Can be undone (Ctrl+Z)."""
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        cm = self._project.country_mgr
        cmd = ManagerSnapshotCommand(
            f"Change {tag} {prop}", cm,
            [f for f in ("_countries",) if hasattr(cm, f)],
        )
        self._controllers["country"].change_property(tag, prop, val)
        cmd.capture_after()
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()

    def _on_country_color_change(self, tag: str) -> None:
        """Change country colors. Can be undone (Ctrl+Z)."""
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        country = self._project.country_mgr.get_country(tag)
        if not country:
            return
        r, g, b = country.color
        chosen = QColorDialog.getColor(QColor(r, g, b), self, tr("dlg_country_change_color").format(tag=tag))
        if not chosen.isValid():
            return
        cm = self._project.country_mgr
        cmd = ManagerSnapshotCommand(
            f"Change {tag} color", cm,
            [f for f in ("_countries",) if hasattr(cm, f)],
        )
        ctrl: CountryController = self._controllers["country"]
        ctrl.change_color(tag, (chosen.red(), chosen.green(), chosen.blue()))
        cmd.capture_after()
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()

    # ═══════════════════════ River / Terrain / Height ═══════

    def _on_validate_river(self) -> None:
        from domain.managers.river import validate_rivers
        from ui.i18n import get_language
        warnings = validate_rivers(self._canvas.river_map, lang=get_language())
        QMessageBox.information(self, tr("dlg_river_validate_title"), "\n".join(warnings))

    def _on_auto_terrain(self) -> None:
        from services.terrain_service import smart_auto_terrain, TerrainGenConfig
        from commands.map.generate_terrain import GenerateTerrainCommand
        # Fool-proof: Double confirmation (will cover the entire terrain.bmp, and can only be restored by undoing)
        ret = QMessageBox.question(
            self, tr("auto_terrain_confirm_title"),
            tr("auto_terrain_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._status_info.setText(tr("status_auto_terrain"))
        self.repaint()
        map_data = self._project.map_data
        # Get configuration from terrain page (if available)
        config = None
        terrain_page = self._tool_panel._terrain_page
        if hasattr(terrain_page, 'get_gen_config'):
            config = terrain_page.get_gen_config()
        new_terrain = smart_auto_terrain(
            map_data.height_map, map_data.tile_map, config
        )
        cmd = GenerateTerrainCommand(map_data, new_terrain)
        self._cmd_history.execute(cmd)
        # Does not overwrite existing provincial_terrain, only fills gaps (processed internally by GenerateTerrainCommand).
        # Want to recalculate all attributes → "Resynchronize attributes from visual terrain" button in Terrain (Attribute) mode.
        self._project.mark_dirty()
        # Automatically generate terrain → colormap to regenerate
        self._project.mark_assets_dirty(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        )
        self._canvas.terrain_map = map_data.terrain_map
        self._status_info.setText(tr("status_auto_terrain_done"))

    def _on_realistic_height(self) -> None:
        """Generate photorealistic height maps in one click - Generator 2 (Mountain Chains/Plains/Continental Shelves).

        Change the random seed each time you click (if you are not satisfied, click again to re-wash); can be undone."""
        import random
        from domain.generators.heightmap import (
            RealisticHeightmapGenerator, HeightmapParams)
        from commands.map.apply_generator import ApplyGeneratorCommand
        # No need to confirm twice: the entrance is a multiple-choice dialog box, click on the card to clarify your intention, and it can be revoked
        self._status_info.setText(tr("status_realistic_height"))
        self.repaint()
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            map_data = self._project.map_data
            gen = RealisticHeightmapGenerator()
            seed = random.randrange(100000)
            new_height = gen.generate(map_data, HeightmapParams(seed=seed))
            cmd = ApplyGeneratorCommand(
                map_data, gen.target_layer, new_height,
                label=tr("realistic_height_confirm_title"))
            self._cmd_history.execute(cmd)
        finally:
            QApplication.restoreOverrideCursor()
        self._project.mark_dirty()
        from features.map.preview import renderer as preview_renderer
        preview_renderer.invalidate_cache(self._canvas)
        self._canvas.height_map = map_data.height_map
        self._status_info.setText(
            tr("status_realistic_height_done").format(seed=seed))

    def _on_detail_terrain(self, seed: int) -> None:
        """Automatic terrain refinement by climate — first UI entry for Route C generator.

        Latitude climate zone (jungle/desert/forest/snowfield) + altitude overlay (hills/mountains/snow line)
        + Noise patches. Can be revoked; can be reproduced with the same seed, or regenerated by changing the seed."""
        from domain.generators.terrain_detail import (
            TerrainDetailGenerator, TerrainDetailParams)
        from commands.map.generate_terrain import GenerateTerrainCommand
        # No need to confirm twice: the entrance is a multiple-choice dialog box, click on the card to clarify your intention, and it can be revoked
        self._status_info.setText(tr("status_detail_terrain"))
        self.repaint()
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            map_data = self._project.map_data
            gen = TerrainDetailGenerator()
            new_terrain = gen.generate(map_data, TerrainDetailParams(seed=seed))
            cmd = GenerateTerrainCommand(map_data, new_terrain)
            cmd.label = tr("detail_terrain_confirm_title")
            self._cmd_history.execute(cmd)
        finally:
            QApplication.restoreOverrideCursor()
        self._project.mark_dirty()
        # The terrain has changed → the colormap asset needs to be reborn, and the preview cache is invalidated
        self._project.mark_assets_dirty(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        )
        from features.map.preview import renderer as preview_renderer
        preview_renderer.invalidate_cache(self._canvas)
        self._canvas.terrain_map = map_data.terrain_map
        self._status_info.setText(tr("status_detail_terrain_done"))

    def _on_beautify_terrain(self, seed: int) -> None:
        """Conformally beautify the terrain: The layout drawn by the author remains unchanged, and the details are based on the original measured parameters."""
        from domain.generators.terrain_beautify import (
            TerrainBeautifyGenerator, TerrainBeautifyParams)
        from commands.map.generate_terrain import GenerateTerrainCommand
        # No need to confirm twice: the entrance is a multiple-choice dialog box, click on the card to clarify your intention, and it can be revoked
        self._status_info.setText(tr("status_beautify_terrain"))
        self.repaint()
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            map_data = self._project.map_data
            gen = TerrainBeautifyGenerator()
            new_terrain = gen.generate(map_data, TerrainBeautifyParams(seed=seed))
            cmd = GenerateTerrainCommand(map_data, new_terrain)
            cmd.label = tr("beautify_terrain_confirm_title")
            self._cmd_history.execute(cmd)
        finally:
            QApplication.restoreOverrideCursor()
        self._project.mark_dirty()
        self._project.mark_assets_dirty(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        )
        from features.map.preview import renderer as preview_renderer
        preview_renderer.invalidate_cache(self._canvas)
        self._canvas.terrain_map = map_data.terrain_map
        self._status_info.setText(tr("status_beautify_terrain_done"))

    def _on_downgrade_mountain(self, mask=None) -> None:
        """Degrade mountains (full map or selection). When mask=None, the whole image is used, otherwise only within the mask."""
        from commands.map.downgrade_mountain import DowngradeMountainCommand
        # Fool-proof: The pop-up window only appears in full-image mode (the selection is where the user has drawn a lasso, and the intention is clear)
        if mask is None:
            ret = QMessageBox.question(
                self, tr("downgrade_mountain_confirm_title"),
                tr("downgrade_mountain_confirm_msg"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return
        map_data = self._project.map_data
        strength = self._tool_panel._terrain_page.get_downgrade_strength()
        cmd = DowngradeMountainCommand(map_data, mask=mask, strength=strength)
        self._cmd_history.execute(cmd)
        self._canvas.terrain_map = map_data.terrain_map
        self._canvas.height_map = map_data.height_map
        self._canvas._full_render()
        self._project.mark_dirty()
        # Downgraded and changed terrain+height → colormap/fow/world_normal, all have to be reborn.
        self._project.mark_assets_dirty(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
            "map/terrain/fow_rgb_waterspec_a.dds",
            "map/world_normal.bmp",
        )
        self._status_info.setText(tr("status_downgrade_done"))

    def _on_downgrade_lasso_mode(self, enabled: bool) -> None:
        """Toggle selection downgrade lasso mode."""
        self._canvas._downgrade_lasso_mode = enabled
        if enabled:
            self._status_info.setText(tr("status_downgrade_lasso_mode"))
        else:
            self._canvas._refine_lasso_item.setVisible(False)

    def _on_terrain_underlay_toggle(self, enabled: bool) -> None:
        """Topographic basemap toggle in country/state mode — reference coasts/mountains when drawing borders."""
        self._canvas.set_terrain_underlay_visible(bool(enabled))

    def _on_terrain_underlay_opacity(self, value: int) -> None:
        """Slider 0..100 → 0.0..1.0 Opacity."""
        self._canvas.set_terrain_underlay_opacity(value / 100.0)

    def _on_terrain_underlay_source(self, source: str) -> None:
        """Toggle terrain basemap source: 'height' (color heightmap) or 'terrain' (terrain attribute provincial_terrain)."""
        if source == "terrain":
            # Make sure provincial_terrain RGB is built (users may have never entered province_terrain mode)
            if getattr(self._canvas, "_provincial_terrain_color_rgb", None) is None:
                app_ctrl = self._controllers.get("app")
                if app_ctrl is not None and hasattr(app_ctrl, "_refresh_provincial_terrain_colors"):
                    app_ctrl._refresh_provincial_terrain_colors()
        self._canvas.set_terrain_underlay_source(source)

    def _on_terrain_context_overlay(self, enabled: bool) -> None:
        """Show/hide the country color + state border overlay in terrain view.

        When enabled: cache mgrs + subscribe to state_changed/country_changed → automatic redraw (debounce 80ms).
        When closed: unsubscribe + hide."""
        if enabled:
            self._canvas.show_terrain_context_overlay(
                True,
                country_mgr=self._project.country_mgr,
                state_mgr=self._project.state_mgr,
            )
            bus = getattr(self._project, "event_bus", None)
            if bus is not None:
                bus.subscribe("state_changed", self._on_terrain_ctx_data_changed)
                bus.subscribe("country_changed", self._on_terrain_ctx_data_changed)
                bus.subscribe("province_map_changed", self._on_terrain_ctx_data_changed)
        else:
            self._canvas.show_terrain_context_overlay(False)
            bus = getattr(self._project, "event_bus", None)
            if bus is not None:
                bus.unsubscribe("state_changed", self._on_terrain_ctx_data_changed)
                bus.unsubscribe("country_changed", self._on_terrain_ctx_data_changed)
                bus.unsubscribe("province_map_changed", self._on_terrain_ctx_data_changed)

    def _on_terrain_ctx_data_changed(self, _event) -> None:
        """State/Country data changes → debounce refresh overlay (to avoid lags during drag-and-drop batch modification)."""
        from PyQt5.QtCore import QTimer
        timer = getattr(self, "_terrain_ctx_refresh_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(80)
            timer.timeout.connect(self._refresh_terrain_ctx_overlay_now)
            self._terrain_ctx_refresh_timer = timer
        timer.start()

    def _refresh_terrain_ctx_overlay_now(self) -> None:
        """Actual execution of overlay refresh (triggered by QTimer)."""
        if getattr(self._canvas, "_terrain_context_visible", False):
            # Project may have been reloaded, recaching mgrs
            self._canvas.show_terrain_context_overlay(
                True,
                country_mgr=self._project.country_mgr,
                state_mgr=self._project.state_mgr,
            )

    def _on_downgrade_lasso_drawn(self, points: list) -> None:
        """The lasso is drawn → polygon to mask → adjust _on_downgrade_mountain(mask)."""
        from PyQt5.QtWidgets import QMessageBox
        map_data = self._project.map_data
        h, w = map_data.terrain_map.shape
        mask = _polygon_to_mask(points, h, w)
        if mask.sum() < 400:
            QMessageBox.information(
                self, tr("terrain_btn_downgrade_region"),
                tr("refine_dlg_area_too_small"),
            )
            self._tool_panel._terrain_page.reset_downgrade_lasso_button()
            return
        self._on_downgrade_mountain(mask=mask)
        self._tool_panel._terrain_page.reset_downgrade_lasso_button()

    def _on_auto_height(self) -> None:
        """Automatically generate a height map (covering the entire image). Can be undone (Ctrl+Z)."""
        from services.terrain_service import smart_auto_height
        from commands.land.brush_stroke import BrushStrokeCommand
        # Fool-proof: double confirmation (covering the entire height map)
        ret = QMessageBox.question(
            self, tr("auto_height_confirm_title"),
            tr("auto_height_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._status_info.setText(tr("status_auto_height"))
        self.repaint()
        config = None
        height_page = self._tool_panel._height_page
        if hasattr(height_page, 'get_height_config'):
            config = height_page.get_height_config()
        map_data = self._project.map_data

        # Undo Snapshot: Before Operation
        snap_arrays = {"height_map": map_data.height_map}
        before = BrushStrokeCommand.snapshot_arrays(snap_arrays)

        new_height = smart_auto_height(map_data.tile_map, config)
        # Update map_data and canvas simultaneously (both sides share the same array)
        map_data.height_map[:] = new_height
        self._canvas.height_map = map_data.height_map

        # Undo snapshot: after operation + push to stack
        if BrushStrokeCommand.has_changes(before, snap_arrays):
            after = BrushStrokeCommand.snapshot_arrays(snap_arrays)
            cmd = BrushStrokeCommand("Automatically generate heightmap", before, after)
            cmd.set_target_arrays(self._app._get_all_arrays())
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()

        self._project.mark_dirty()
        # Automatically generate height → world_normal/colormap/fow to respawn
        self._project.mark_assets_dirty(
            "map/world_normal.bmp",
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
            "map/terrain/fow_rgb_waterspec_a.dds",
        )
        self._status_info.setText(tr("status_auto_height_done"))

    def _on_height_from_terrain(self) -> None:
        """Invert height_map from terrain (overwrite existing). Prioritize province attributes (provincial_terrain),
        fallback to pixel decoration (terrain_map). HOI4 actual game province attributes."""
        from services.terrain_service import auto_height_from_terrain
        map_data = self._project.map_data
        has_prov_terrain = bool(map_data.provincial_terrain)
        has_terrain = map_data.terrain_map is not None and int(map_data.terrain_map.max()) > 0
        if not has_prov_terrain and not has_terrain:
            QMessageBox.warning(self, tr("dlg_warning"), tr("height_from_terrain_no_terrain"))
            return
        ret = QMessageBox.question(
            self, tr("height_from_terrain_confirm_title"),
            tr("height_from_terrain_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._status_info.setText(tr("status_height_from_terrain"))
        self.repaint()
        new_height = auto_height_from_terrain(
            map_data.terrain_map, map_data.tile_map,
            provincial_terrain=map_data.provincial_terrain,
            province_map=map_data.province_map,
        )
        map_data.height_map[:] = new_height
        self._canvas.height_map = map_data.height_map
        self._project.mark_dirty()
        self._project.mark_assets_dirty(
            "map/world_normal.bmp",
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
            "map/terrain/fow_rgb_waterspec_a.dds",
        )
        self._status_info.setText(tr("status_height_from_terrain_done"))

    def _on_smooth_height(self) -> None:
        from services.terrain_service import smooth_height
        self._canvas.height_map = smooth_height(
            self._canvas.height_map, self._canvas.tile_map
        )
        self._status_info.setText(tr("status_height_smoothed"))

    # ── Mountain line drawing ──

    def _on_ridge_mode(self, enabled: bool) -> None:
        """Toggle mountain line drawing mode — sync to canvas."""
        self._ridge_mode = enabled
        self._canvas._ridge_mode = enabled
        if enabled:
            self._status_info.setText(tr("status_ridge_mode_on"))
        else:
            # Cancel preview when exiting mode
            if hasattr(self, '_ridge_backup'):
                self._on_ridge_cancel()
            self._status_info.setText(tr("status_ridge_mode_off"))

    def _on_ridge_drawn(self, points: list) -> None:
        """Canvas line drawing is completed → enter preview mode (not applied immediately)."""
        if len(points) < 2:
            return
        # interval sampling
        if len(points) > 100:
            step = len(points) // 100
            points = points[::step] + [points[-1]]

        # Save original heightmap + line drawing path
        self._ridge_backup = self._project.map_data.height_map.copy()
        self._ridge_points = points

        # Show confirm/cancel button
        self._tool_panel._height_page.show_ridge_confirm()

        # Generate preview now
        self._apply_ridge_preview()
        self._status_info.setText(tr("status_ridge_preview"))

    def _apply_ridge_preview(self) -> None:
        """Generate a mountain preview using current parameters (without modifying backup)."""
        if not hasattr(self, '_ridge_backup') or self._ridge_backup is None:
            return
        from services.terrain_service import apply_mountain_ridge
        map_data = self._project.map_data
        peak = getattr(self, '_ridge_peak', 220)
        falloff = getattr(self, '_ridge_falloff', 80)

        preview = apply_mountain_ridge(
            self._ridge_backup, map_data.tile_map,
            self._ridge_points, peak_height=peak, falloff_distance=float(falloff),
        )
        map_data.height_map[:] = preview
        self._canvas.height_map = map_data.height_map
        self._canvas._full_render()

    def _on_ridge_preview(self) -> None:
        """Slider changes → Refresh preview."""
        self._apply_ridge_preview()

    def _on_ridge_confirm(self) -> None:
        """Confirm mountains → Apply to heightmap, clean up preview state."""
        self._ridge_backup = None
        self._ridge_points = None
        self._tool_panel._height_page.hide_ridge_confirm()
        # The line has been drawn on the canvas, hide it
        self._canvas._split_line_item.setVisible(False)
        self._project.mark_dirty()
        self._status_info.setText(tr("status_ridge_applied"))

    def _on_ridge_cancel(self) -> None:
        """Undo Mountains → Restore original heightmap."""
        if hasattr(self, '_ridge_backup') and self._ridge_backup is not None:
            self._project.map_data.height_map[:] = self._ridge_backup
            self._canvas.height_map = self._project.map_data.height_map
            self._canvas._full_render()
        self._ridge_backup = None
        self._ridge_points = None
        self._tool_panel._height_page.hide_ridge_confirm()
        self._canvas._split_line_item.setVisible(False)
        self._status_info.setText(tr("status_ridge_mode_on"))

    # ── Conformal finishing (whole picture) ──

    def _on_refine_whole_map(self) -> None:
        """Conformally trim the height map: the layout you drew (which is higher and which is lower) remains unchanged, and the texture is superimposed on the entire image.

        mask = full map: the land is conformally refined, and the seafloor is unconditionally reconstructed as the continental shelf slope.
        (The seabed is not the creative content, the chaotic legacy data is taken over by algorithms).
        Check "Regenerate from scratch" in the dialog box to redo the entire image (equivalent to one-click generation)."""
        import numpy as np
        from data.constants import TILE_LAND
        map_data = self._project.map_data
        if not bool((map_data.tile_map == TILE_LAND).any()):
            QMessageBox.information(
                self, tr("refine_dlg_title"), tr("refine_whole_no_land"))
            return
        mask = np.ones(map_data.tile_map.shape, dtype=bool)
        self._run_refine_dialog(mask)

    def _run_refine_dialog(self, mask) -> None:
        """Open the Refinement Parameters dialog box and execute (local lasso / common to the entire image)."""
        import numpy as np
        from features.map.height.refine_dialog import RefineDialog
        from commands.map.refine_height_region import RefineHeightRegionCommand

        map_data = self._project.map_data
        # Back up the original image for dialog preview use
        original = map_data.height_map.copy()

        dlg = RefineDialog(
            self,
            height_map=original,
            mask=mask,
            tile_map=map_data.tile_map,
        )
        # Preview: Fill new_height back to canvas in real time
        def _update_preview(new_hm: np.ndarray) -> None:
            map_data.height_map[:] = new_hm
            self._canvas.height_map = map_data.height_map
            self._canvas._full_render()
        dlg.preview_updated.connect(_update_preview)

        accepted = dlg.exec_() == dlg.DialogCode.Accepted

        # After the dialog box ends, restore the original image (consistent starting point), and then push command as needed
        map_data.height_map[:] = original
        self._canvas.height_map = map_data.height_map

        if accepted:
            cmd = RefineHeightRegionCommand(map_data, mask, dlg.params)
            self._cmd_history.execute(cmd)
            from features.map.preview import renderer as preview_renderer
            preview_renderer.invalidate_cache(self._canvas)
            self._canvas.height_map = map_data.height_map
            self._canvas._full_render()
            self._project.mark_dirty()
            self._status_info.setText(tr("status_refine_done"))
        else:
            self._canvas._full_render()
            self._status_info.setText(tr("status_ready"))

    # ═══════════════════════ Continent ═══════════════════════

    def _on_continent_pick_toggled(self, on: bool) -> None:
        from controllers.continent import ContinentController
        ctrl: ContinentController = self._controllers["continent"]
        if on:
            item = self._tool_panel._continent_list.currentItem()
            if item is None:
                self._tool_panel._continent_pick_btn.setChecked(False)
                return
            row = self._tool_panel._continent_list.currentRow()
            ctrl.toggle_pick(True, row)
        else:
            ctrl.toggle_pick(False)

    def _on_continent_add(self, name: str) -> None:
        """Add continents. Can be undone (Ctrl+Z)."""
        from controllers.continent import ContinentController
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        ctrl: ContinentController = self._controllers["continent"]
        cm = self._project.continent_mgr
        cmd = ManagerSnapshotCommand(
            "Add continent", cm,
            [f for f in ("_names", "_province_continent") if hasattr(cm, f)],
        )
        if ctrl.add_continent(name):
            cmd.capture_after()
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()
            self._refresh_continent_list()
        else:
            QMessageBox.warning(self, tr("dlg_error"), tr("dlg_continent_add_failed"))

    def _on_continent_rename(self, index: int, name: str) -> None:
        """Rename continents. Can be undone (Ctrl+Z)."""
        from controllers.continent import ContinentController
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        ctrl: ContinentController = self._controllers["continent"]
        cm = self._project.continent_mgr
        cmd = ManagerSnapshotCommand(
            "Rename continent", cm,
            [f for f in ("_names",) if hasattr(cm, f)],
        )
        if ctrl.rename_continent(index, name):
            cmd.capture_after()
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()
            self._refresh_continent_list()
        else:
            QMessageBox.warning(self, tr("dlg_error"), tr("dlg_continent_rename_failed"))

    def _on_continent_remove(self, index: int) -> None:
        """Delete continent. Can be undone (Ctrl+Z)."""
        from controllers.continent import ContinentController
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        ctrl: ContinentController = self._controllers["continent"]
        cm = self._project.continent_mgr
        cmd = ManagerSnapshotCommand(
            "Delete continent", cm,
            [f for f in ("_names", "_province_continent") if hasattr(cm, f)],
        )
        if ctrl.remove_continent(index):
            cmd.capture_after()
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()
            self._refresh_continent_list()
        else:
            QMessageBox.warning(self, tr("dlg_error"), tr("dlg_continent_delete_failed"))

    def _refresh_continent_list(self) -> None:
        from PyQt5.QtWidgets import QListWidgetItem
        lst = self._tool_panel._continent_list
        lst.clear()
        cm = self._project.continent_mgr
        for i, name in enumerate(cm.names):
            count = sum(1 for ci in cm._province_continent.values() if ci == i)
            item = QListWidgetItem(f"{i+1}. {name}  ({count} {tr('unit_provinces')})")
            item.setData(Qt.UserRole, name)
            lst.addItem(item)

    # ═══════════════════════ Strategic Region ═══════════════

    def _on_sr_pick_toggled(self, on: bool) -> None:
        ctrl = self._controllers["strategic_region"]
        if on:
            lst = self._tool_panel._sr_list
            item = lst.currentItem()
            if item is None:
                self._tool_panel._sr_pick_btn.setChecked(False)
                return
            rid = int(item.data(Qt.UserRole) or 0)
            ctrl.toggle_pick(True, rid)
        else:
            ctrl.toggle_pick(False)

    def _track_sr_op(self, label: str):
        """Factory method: Create a snapshot Command for the current state of sr_mgr (cmd.capture_after()+ push after the operation)."""
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        sr_mgr = self._project.strategic_region_mgr
        return ManagerSnapshotCommand(
            label, sr_mgr,
            [f for f in ("_regions", "_next_id") if hasattr(sr_mgr, f)],
        )

    def _commit_cmd(self, cmd) -> None:
        """General: snapshot operation capture_after + push undo stack."""
        cmd.capture_after()
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()

    def _on_sr_new(self) -> None:
        """Create a new strategic area. Can be undone (Ctrl+Z)."""
        cmd = self._track_sr_op("Create strategic region")
        self._controllers["strategic_region"].create_region()
        self._commit_cmd(cmd)
        self._refresh_sr_list()

    def _on_sr_delete(self) -> None:
        """Delete strategic areas. Can be undone (Ctrl+Z)."""
        lst = self._tool_panel._sr_list
        item = lst.currentItem()
        if item is None:
            return
        rid = int(item.data(Qt.UserRole) or 0)
        cmd = self._track_sr_op(f"Delete strategic region #{rid}")
        self._controllers["strategic_region"].delete_region(rid)
        self._commit_cmd(cmd)
        self._refresh_sr_list()

    def _get_sr_current_rid(self) -> int:
        lst = self._tool_panel._sr_list
        item = lst.currentItem()
        return int(item.data(Qt.UserRole) or 0) if item else 0

    def _on_sr_selected(self, row: int) -> None:
        lst = self._tool_panel._sr_list
        item = lst.item(row)
        if item is None:
            return
        rid = int(item.data(Qt.UserRole) or 0)
        r = self._project.strategic_region_mgr.get(rid)
        if r is None:
            return
        # Highlight all provinces in the area
        self._controllers["strategic_region"].select_region(rid)
        # Update edit fields
        self._tool_panel._sr_name_edit.blockSignals(True)
        # The old data name may be in the form of STRATEGICREGION_{id} and is displayed as empty for the user to fill in.
        display_name = r.name if (r.name and r.name != f"STRATEGICREGION_{rid}") else ""
        self._tool_panel._sr_name_edit.setText(display_name)
        self._tool_panel._sr_name_edit.blockSignals(False)
        self._tool_panel._sr_name_en_edit.blockSignals(True)
        self._tool_panel._sr_name_en_edit.setText(getattr(r, "name_en", "") or "")
        self._tool_panel._sr_name_en_edit.blockSignals(False)
        idx = self._tool_panel._sr_weather_combo.findData(r.weather_preset)
        if idx >= 0:
            self._tool_panel._sr_weather_combo.blockSignals(True)
            self._tool_panel._sr_weather_combo.setCurrentIndex(idx)
            self._tool_panel._sr_weather_combo.blockSignals(False)
        nidx = self._tool_panel._sr_naval_combo.findData(r.naval_terrain or "")
        if nidx >= 0:
            self._tool_panel._sr_naval_combo.blockSignals(True)
            self._tool_panel._sr_naval_combo.setCurrentIndex(nidx)
            self._tool_panel._sr_naval_combo.blockSignals(False)
        self._tool_panel._sr_prov_count.setText(tr("sr_prov_count").format(len(r.province_ids)))

    def _on_sr_name_changed(self, name: str) -> None:
        """Change the name of the strategic area. Can be undone (Ctrl+Z)."""
        rid = self._get_sr_current_rid()
        if rid <= 0:
            return
        cmd = self._track_sr_op(f"Change strategic region #{rid} name")
        self._controllers["strategic_region"].set_name(rid, name)
        self._commit_cmd(cmd)
        self._refresh_sr_list()

    def _on_sr_name_en_changed(self, name_en: str) -> None:
        """Change the English name of the strategic area. Can be undone (Ctrl+Z)."""
        rid = self._get_sr_current_rid()
        if rid <= 0:
            return
        r = self._project.strategic_region_mgr.get(rid)
        if r is None:
            return
        cmd = self._track_sr_op(f"Change strategic region #{rid} English name")
        r.name_en = name_en
        self._commit_cmd(cmd)

    def _on_sr_weather_changed(self, preset: str) -> None:
        """Change the weather in strategic areas. Can be undone (Ctrl+Z)."""
        rid = self._get_sr_current_rid()
        if rid <= 0:
            return
        cmd = self._track_sr_op(f"Change strategic region #{rid} weather")
        self._controllers["strategic_region"].set_weather(rid, preset)
        self._commit_cmd(cmd)

    def _on_sr_naval_changed(self, naval: str) -> None:
        """Change the naval terrain of strategic areas. Can be undone (Ctrl+Z)."""
        rid = self._get_sr_current_rid()
        if rid <= 0:
            return
        cmd = self._track_sr_op(f"Change strategic region #{rid} naval terrain")
        self._controllers["strategic_region"].set_naval(rid, naval)
        self._commit_cmd(cmd)

    def _refresh_sr_list(self) -> None:
        from PyQt5.QtWidgets import QListWidgetItem
        from domain.managers.strategic_region import weather_preset_display_name
        lst = self._tool_panel._sr_list
        selected = lst.currentItem()
        selected_id = selected.data(Qt.UserRole) if selected else None
        was_blocked = lst.blockSignals(True)
        lst.clear()
        for r in sorted(self._project.strategic_region_mgr.regions.values(), key=lambda x: x.id):
            label = (
                f"#{r.id} {r.name}  ({len(r.province_ids)}{tr('unit_provinces')}, "
                f"{weather_preset_display_name(r.weather_preset)})"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r.id)
            lst.addItem(item)
            if r.id == selected_id:
                lst.setCurrentItem(item)
        lst.blockSignals(was_blocked)
        if lst.currentRow() < 0 and lst.count():
            lst.setCurrentRow(0)
        else:
            self._on_sr_selected(lst.currentRow())
        if hasattr(self, "_refresh_feature_statuses"):
            self._refresh_feature_statuses()

    def _refresh_logistics_counts(self) -> None:
        self._tool_panel._logi_adj_status.setText(tr("logistics_adj_count", self._project.adjacency_mgr.count()))
        self._tool_panel._logi_rail_status.setText(tr("logistics_rail_count", self._project.railway_mgr.count()))
        self._tool_panel._logi_sup_status.setText(tr("logistics_supply_count", self._project.supply_mgr.count()))
        if hasattr(self, "_refresh_feature_statuses"):
            self._refresh_feature_statuses()

    def _refresh_feature_statuses(self) -> None:
        """Refresh live completion dots for the logistics group tabs."""
        regions = self._project.strategic_region_mgr.regions.values()
        strategic_ready = any(bool(region.province_ids) for region in regions)
        logistics_ready = any(
            manager.count() > 0
            for manager in (
                self._project.adjacency_mgr,
                self._project.railway_mgr,
                self._project.supply_mgr,
            )
        )
        self._tool_panel.set_feature_ready("strategic_region", strategic_ready)
        self._tool_panel.set_feature_ready("logistics", logistics_ready)

    def _open_logistics_generation(self) -> None:
        from features.map.logistics.generation_dialog import LogisticsGenerationDialog
        LogisticsGenerationDialog(self._project, self._controllers["logistics"].history, self).exec_()

    # ═══════════════════════ Logistics Dialog ═══════════════

    _adjacency_dialog = None
    _railway_dialog = None
    _adjacency_rule_dialog = None

    def _open_adjacency_dialog(self) -> None:
        if self._adjacency_dialog is not None:
            self._adjacency_dialog.raise_()
            self._adjacency_dialog.activateWindow()
            return
        from features.map.logistics.adjacency_dialog import AdjacencyDialog
        dlg = AdjacencyDialog(
            self._project.adjacency_mgr, parent=self,
            province_map=self._canvas.province_map,
            tile_map=self._canvas.tile_map,
        )
        dlg.changed.connect(self._refresh_logistics_counts)
        dlg.pick_mode_changed.connect(self._on_adjacency_pick_mode)
        dlg.finished.connect(self._on_adjacency_dialog_closed)
        self._adjacency_dialog = dlg
        dlg.show()

    def _on_adjacency_pick_mode(self, on: bool, target: str) -> None:
        ctrl: LogisticsController = self._controllers["logistics"]
        ctrl.set_adjacency_pick(on, target)

    def _on_adjacency_dialog_closed(self, *_args) -> None:
        self._adjacency_dialog = None
        self._refresh_logistics_counts()
        ctrl: LogisticsController = self._controllers["logistics"]
        if ctrl.pick_target and ctrl.pick_target.startswith("adj_"):
            ctrl.pick_target = None

    def _open_railway_dialog(self) -> None:
        if self._railway_dialog is not None:
            self._railway_dialog.raise_()
            self._railway_dialog.activateWindow()
            return
        from features.map.logistics.railway_dialog import RailwayDialog
        dlg = RailwayDialog(self._project.railway_mgr, parent=self)
        dlg.changed.connect(self._refresh_logistics_counts)
        dlg.finished.connect(self._on_railway_dialog_closed)
        self._railway_dialog = dlg
        dlg.show()

    def _on_railway_dialog_closed(self, *_args) -> None:
        self._railway_dialog = None
        self._refresh_logistics_counts()

    # ═══════════════════════ Default Map ═══════════════════

    def _on_dm_tree_add(self) -> None:
        v, ok = QInputDialog.getInt(
            self, tr("defmap_add_btn"), tr("dlg_defmap_palette_prompt"), value=4, min=1, max=13
        )
        if ok:
            ctrl: DefaultMapController = self._controllers["default_map"]
            if ctrl.add_tree_index(v):
                self._refresh_dm_tree_list()

    def _on_dm_tree_del(self) -> None:
        lst = self._tool_panel._dm_tree_list
        row = lst.currentRow()
        ctrl: DefaultMapController = self._controllers["default_map"]
        if ctrl.remove_tree_index(row):
            self._refresh_dm_tree_list()

    def _on_dm_tree_reset(self) -> None:
        # Fool-proof: double confirmation (reset tree settings)
        ret = QMessageBox.question(
            self, tr("default_map_reset_confirm_title"),
            tr("default_map_reset_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        ctrl: DefaultMapController = self._controllers["default_map"]
        ctrl.reset_tree_indices()
        self._refresh_dm_tree_list()

    def _refresh_dm_tree_list(self) -> None:
        from PyQt5.QtWidgets import QListWidgetItem
        lst = self._tool_panel._dm_tree_list
        lst.clear()
        for idx in self._project.default_map_settings.tree_palette_indices:
            lst.addItem(QListWidgetItem(str(idx)))

    # ═══════════════════════ Miscellaneous ═══════════════════════════

    def _on_toggle_language(self) -> None:
        """Compatibility hook for older callers; the application is English-only."""
        return

    def _retranslate_ui(self) -> None:
        """Refresh the entire interface text after language switching (no need to restart)."""
        # window title
        self.setWindowTitle(tr("app_title"))
        # Rebuild menu bar
        self.menuBar().clear()
        self._init_menu()
        # Refresh tool panel
        self._tool_panel.retranslateUi()
        # Refresh welcome page
        if hasattr(self, '_welcome_page') and self._welcome_page:
            self._welcome_page.retranslateUi()

    def _on_about(self) -> None:
        QMessageBox.about(
            self, tr("action_about"),
            tr("dlg_about_body"),
        )


def _polygon_to_mask(points: list, h: int, w: int):
    """Convert [(y,x), ...] closed polygon to (h,w) bool mask.

    Use contains_points of matplotlib.path.Path — more stable than handwritten scan lines, already in the project
    Alternatives are available in the Pillow/NumPy ecosystem in requirements.txt. Pure numpy + ray method is used here."""
    import numpy as np
    if len(points) < 3:
        return np.zeros((h, w), dtype=bool)

    ys = np.array([p[0] for p in points], dtype=np.float32)
    xs = np.array([p[1] for p in points], dtype=np.float32)

    # Bounding box acceleration
    y_min = max(0, int(ys.min()) - 1)
    y_max = min(h, int(ys.max()) + 2)
    x_min = max(0, int(xs.min()) - 1)
    x_max = min(w, int(xs.max()) + 2)

    mask = np.zeros((h, w), dtype=bool)
    if y_max <= y_min or x_max <= x_min:
        return mask

    # Ray method (emitting to the right), scanning the pixels in the bbox line by line
    # For each side of the polygon (y0,x0)->(y1,x1), check whether the current scan line y passes through the side,
    # If it passes through, the intersection point x_cross is calculated, and the number of times x_cross < current column x is counted
    # odd number of times → within polygon
    n = len(points)
    for y in range(y_min, y_max):
        x_crossings = []
        for i in range(n):
            y0, x0 = ys[i], xs[i]
            y1, x1 = ys[(i + 1) % n], xs[(i + 1) % n]
            # Check if this edge passes through the horizontal line y + 0.5
            y_line = y + 0.5
            if (y0 <= y_line) == (y1 <= y_line):
                continue
            # Linear interpolation x
            if y1 == y0:
                continue
            t = (y_line - y0) / (y1 - y0)
            x_cross = x0 + t * (x1 - x0)
            x_crossings.append(x_cross)
        if not x_crossings:
            continue
        x_crossings.sort()
        row = mask[y]
        # Fill in pairs
        for i in range(0, len(x_crossings) - 1, 2):
            xa = max(x_min, int(np.ceil(x_crossings[i])))
            xb = min(x_max, int(np.floor(x_crossings[i + 1])) + 1)
            if xb > xa:
                row[xa:xb] = True
    return mask
