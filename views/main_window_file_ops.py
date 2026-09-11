"""Main window file operations - New/Open/Save/Import/Export.
Split from views/main_window_actions.py and used as a mixin."""
from __future__ import annotations

import numpy as np
from PyQt5.QtWidgets import (
    QFileDialog, QMessageBox, QApplication, QInputDialog,
)
from PyQt5.QtGui import QColor

from ui.i18n import tr
from data.constants import (
    TILE_SEA, TILE_LAND,
    DEFAULT_MOD_OUTPUT_PATH,
)


_VANILLA_REFERENCE_RELPATHS = (
    ("map", "provinces.bmp"),
    ("map", "terrain", "colormap_rgb_cityemissivemask_a.dds"),
)


def _find_vanilla_reference(game_dir: str | None) -> str | None:
    """Return the first usable vanilla reference image in *game_dir*."""
    if not game_dir:
        return None
    import os

    for parts in _VANILLA_REFERENCE_RELPATHS:
        path = os.path.join(game_dir, *parts)
        if os.path.isfile(path):
            return path
    return None


def _populate_imported_data(project, result: dict) -> None:
    """Populate the imported states and strategic regions data into the project manager."""
    from domain.managers.state import StateData

    # populate states
    for sd in result.get("states", []):
        state = StateData(
            id=sd["id"],
            name=sd.get("name", f"STATE_{sd['id']}"),
            provinces=sd.get("provinces", []),
            manpower=sd.get("manpower", 100000),
            category=sd.get("category", "town"),
            owner_tag=sd.get("owner", ""),
            victory_points=sd.get("victory_points", {}),
            vp_names=sd.get("vp_names", {}),
        )
        project.state_mgr.states[sd["id"]] = state
        for pid in state.provinces:
            project.state_mgr._province_to_state[pid] = sd["id"]
    # update_next_id
    if project.state_mgr.states:
        project.state_mgr._next_id = max(project.state_mgr.states.keys()) + 1

    # Populate strategic regions — construct the object directly without using create_region (auto_id will conflict)
    from domain.managers.strategic_region import StrategicRegion
    sr_mgr = project.strategic_region_mgr
    for rd in result.get("strategic_regions", []):
        r = StrategicRegion(
            id=rd["id"],
            name=rd.get("name", f"STRATEGICREGION_{rd['id']}"),
            province_ids=rd.get("provinces", []),
            weather_preset=rd.get("weather_preset", "temperate"),
            naval_terrain=rd.get("naval_terrain", ""),
        )
        sr_mgr._regions[r.id] = r
    if sr_mgr._regions:
        sr_mgr._next_id = max(sr_mgr._regions.keys()) + 1

    # Populate country (extracted from owner of states)
    # Colors come from colors.txt; Country name search localization (GER → "Germany"/"German Reich");
    # Capital/Government comes from history/countries/ (note that the original capital is State ID,
    # Our CountryData.capital is the province ID, converted here)
    country_colors = result.get("country_colors", {})
    country_history = result.get("country_history", {})
    loc_map = result.get("localisation", {})
    states_by_id = {sd["id"]: sd for sd in result.get("states", [])}
    owners = set(sd.get("owner", "") for sd in result.get("states", []))
    owners.discard("")
    for tag in sorted(owners):
        # Skip invalid tags (localized text, excessive length, special characters, and similar input).
        if len(tag) != 3 or not tag.isascii():
            continue
        if tag not in project.country_mgr.countries:
            color = country_colors.get(tag, None)
            if color is None:
                import hashlib
                h = int(hashlib.md5(tag.encode()).hexdigest()[:6], 16)
                color = (
                    max(60, min(220, (h >> 16) & 0xFF)),
                    max(60, min(220, (h >> 8) & 0xFF)),
                    max(60, min(220, h & 0xFF)),
                )
            try:
                # The imported country is originally a vanilla/MOD TAG and must be allowed.
                project.country_mgr.create_country(
                    tag, name=loc_map.get(tag, tag), color=color,
                    allow_vanilla_tag=True)
            except ValueError:
                continue  # Illegal TAG is skipped directly
            ch = country_history.get(tag)
            if ch:
                if ch.get("ruling_party") in (
                        "democratic", "fascism", "communism", "neutrality"):
                    project.country_mgr.set_ruling_party(tag, ch["ruling_party"])
                # Capital: State ID → Province within the State (priority is given to the VP with the highest score, which is the capital city)
                cap_state = states_by_id.get(ch.get("capital_state", 0))
                if cap_state and cap_state.get("provinces"):
                    vps = cap_state.get("victory_points", {})
                    cap_pid = max(vps, key=vps.get) if vps else cap_state["provinces"][0]
                    project.country_mgr.set_capital(tag, int(cap_pid))
        # Assign state to country
        for sd in result.get("states", []):
            if sd.get("owner") == tag:
                project.country_mgr.assign_state(sd["id"], tag)

    # Fill railways
    for rd in result.get("railways", []):
        try:
            project.railway_mgr.add(rd["level"], rd["province_ids"])
        except (ValueError, KeyError):
            pass  # Skip rails with illegal formats

    # Populate supply_nodes
    for sd in result.get("supply_nodes", []):
        try:
            project.supply_mgr.add(sd["province_id"], sd["level"])
        except (ValueError, KeyError):
            pass

    # Fill in adjacencies
    from domain.managers.adjacency import AdjacencyEntry
    for ad in result.get("adjacencies", []):
        entry = AdjacencyEntry(
            from_id=ad["from_id"],
            to_id=ad["to_id"],
            type=ad.get("type", "sea"),
            through_id=ad.get("through_id", -1),
            start_x=ad.get("start_x", -1),
            start_y=ad.get("start_y", -1),
            stop_x=ad.get("stop_x", -1),
            stop_y=ad.get("stop_y", -1),
            rule_name=ad.get("rule", ""),
            comment=ad.get("comment", ""),
        )
        project.adjacency_mgr.add(entry)


class MainWindowFileOpsMixin:
    """File/Import/Export/Test export operations, mixed into MainWindow."""

    # Current project file path; None = Not saved yet (new/imported project) → Save and save as
    _current_project_path: str | None = None

    # ═══════════════════════ Export ═══════════════════════════

    def _on_export_mod(self) -> None:
        from views.export_dialog import ExportDialog
        dlg = ExportDialog(self._project, self._canvas, parent=self)
        dlg.exec_()

    # ═══════════════════════ New/Open/Save ═══════════════

    def _on_new_project(self) -> None:
        reply = QMessageBox.question(
            self, tr("dlg_confirm"),
            tr("file_ops_new_confirm"),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from data.constants import set_map_size
        preset_items = [
            ("Small (2048×1024)", (2048, 1024)),
            ("Medium (3072×1536)", (3072, 1536)),
            ("Large (4096×2048)", (4096, 2048)),
            ("Vanilla (5632×2048)", (5632, 2048)),
        ]
        presets = [label for label, _ in preset_items]
        default_idx = len(presets) - 1

        chosen, ok = QInputDialog.getItem(
            self, tr("file_ops_map_size_title"), tr("file_ops_map_size_prompt"),
            presets, default_idx, False,
        )
        if not ok:
            return

        size_by_label = dict(preset_items)
        new_w, new_h = size_by_label[chosen]
        set_map_size(new_w, new_h)

        from domain.map_data import MapData
        md = MapData()
        md.tile_map = np.full((new_h, new_w), TILE_SEA, dtype=np.uint8)
        md.province_map = np.zeros((new_h, new_w), dtype=np.int32)
        md.terrain_map = np.zeros((new_h, new_w), dtype=np.uint8)
        md.height_map = np.full((new_h, new_w), 40, dtype=np.uint8)
        md.river_map = np.full((new_h, new_w), 255, dtype=np.uint8)  # 255=land background, 0 is the source mark and cannot be used as blank
        self._project.map_data = md
        self._canvas.set_map_data(md)
        self._canvas._scene.setSceneRect(0, 0, new_w, new_h)
        # Reset LandController's mask
        land_ctrl = self._controllers.get("land")
        if land_ctrl:
            land_ctrl.reset_mask_size()
        self._project.state_mgr.clear()
        self._project.country_mgr.clear()
        self._project.strategic_region_mgr.clear()
        self._project.railway_mgr.clear()
        self._project.supply_mgr.clear()
        self._cmd_history.clear()
        self._refresh_sr_list()
        self._refresh_logistics_counts()
        self._update_province_count()
        self._canvas.refresh_display()
        self._current_project_path = None  # The new project has no files yet. When saving, save it as
        self._status_info.setText(tr("file_ops_new_created", new_w, new_h))
        if hasattr(self, '_show_editor'):
            self._show_editor()

    def _on_save_project(self) -> None:
        """Save: Existing project files are directly overwritten; the first time a new/imported project is saved, save it as."""
        import os
        path = self._current_project_path
        if path and os.path.isfile(path):
            self._save_project_to(path)
        else:
            self._on_save_project_as()

    def _on_save_project_as(self) -> None:
        """Save as: Pop-up window to select path."""
        path, _ = QFileDialog.getSaveFileName(
            self, tr("file_ops_save_title"), "", tr("file_ops_proj_filter")
        )
        if not path:
            return
        self._save_project_to(path)

    def _save_project_to(self, path: str) -> None:
        """Write the project file to the specified path. After success, the path will be remembered for direct overwriting next time."""
        try:
            from services.project_service import save_project
            save_project(
                path, self._canvas, self._project.state_mgr,
                self._project.country_mgr, self._project.continent_mgr,
                adjacency_mgr=self._project.adjacency_mgr,
                railway_mgr=self._project.railway_mgr,
                supply_mgr=self._project.supply_mgr,
                adjacency_rule_mgr=self._project.adjacency_rule_mgr,
                strategic_region_mgr=self._project.strategic_region_mgr,
            )
            self._current_project_path = path
            self._status_info.setText(tr("file_ops_saved", path))
            # Record recent projects
            from views.welcome_page import save_recent_project
            save_recent_project(path)
        except Exception as e:
            QMessageBox.critical(self, tr("file_ops_save_fail"), str(e))

    def _on_open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("file_ops_open_title"), "", tr("file_ops_proj_filter")
        )
        if not path:
            return
        self._load_project_file(path)

    def _load_project_file(self, path: str) -> None:
        """Load the project file from the specified path."""
        try:
            from services.project_service import load_project
            load_project(
                path, self._canvas, self._project.state_mgr,
                self._project.country_mgr, self._project.continent_mgr,
                adjacency_mgr=self._project.adjacency_mgr,
                railway_mgr=self._project.railway_mgr,
                supply_mgr=self._project.supply_mgr,
                adjacency_rule_mgr=self._project.adjacency_rule_mgr,
                strategic_region_mgr=self._project.strategic_region_mgr,
            )
            self._cmd_history.clear()
            # After loading, detect province ID holes and prompt
            import numpy as np
            pm = self._canvas.province_map
            max_id = int(pm.max())
            gap_count = 0
            if max_id > 0:
                existing = set(np.unique(pm).tolist())
                existing.discard(0)
                gap_count = max_id - len(existing)

            self._update_province_count()
            self._app._refresh_state_list()
            self._app._refresh_country_list()
            self._refresh_sr_list()
            self._refresh_logistics_counts()
            if gap_count > 0:
                self._status_info.setText(
                    tr("file_ops_loaded_gaps", path, gap_count)
                )
            else:
                self._status_info.setText(tr("file_ops_loaded", path))
            # Remember path (overwrite directly with "Save" later) + record to recent project + switch to editor
            self._current_project_path = path
            from views.welcome_page import save_recent_project
            save_recent_project(path)
            if hasattr(self, '_show_editor'):
                self._show_editor()
        except Exception as e:
            QMessageBox.critical(self, tr("file_ops_load_fail"), str(e))

    # ═══════════════════════ Reference Picture/Import ═══════════════════════

    def _choose_hoi4_install_dir(self) -> str | None:
        """Prompt for and persist a valid Hearts of Iron IV installation."""
        import os
        from services.game_assets import (
            TERRAIN_DEF_RELPATH,
            find_hoi4_install,
            set_default_install_dir,
        )

        current_dir = find_hoi4_install() or ""
        path = QFileDialog.getExistingDirectory(
            self,
            tr("preview_choose_dir_title"),
            current_dir,
        )
        if not path:
            return None
        if not os.path.isfile(os.path.join(path, TERRAIN_DEF_RELPATH)):
            QMessageBox.warning(
                self, tr("dlg_error"), tr("preview_game_dir_invalid")
            )
            return None

        set_default_install_dir(path)
        from features.map.preview import renderer as preview_renderer
        preview_renderer.invalidate_cache(self._canvas)
        return path

    def _on_choose_hoi4_install_dir(self) -> None:
        path = self._choose_hoi4_install_dir()
        if path:
            self._status_info.setText(
                tr("preview_game_dir_found").format(path=path)
            )

    def _on_load_vanilla_ref(self) -> None:
        import os
        from services.game_assets import find_hoi4_install

        game_dir = find_hoi4_install()
        reference_path = _find_vanilla_reference(game_dir)
        if reference_path is None:
            game_dir = self._choose_hoi4_install_dir()
            if game_dir is None:
                return
            reference_path = _find_vanilla_reference(game_dir)

        if reference_path and self._canvas.load_vanilla_reference(reference_path):
            self._status_info.setText(
                tr("file_ops_vanilla_loaded", os.path.basename(reference_path))
            )
            return

        QMessageBox.warning(
            self, tr("dlg_error"),
            tr("file_ops_vanilla_not_found", game_dir or ""),
        )

    def _on_import_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("action_import_image"), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tga);;All Files (*)",
        )
        if file_path:
            if self._canvas.load_reference_image(file_path):
                self._status_info.setText(tr("file_ops_ref_loaded", file_path))
            else:
                QMessageBox.warning(self, tr("dlg_error"), tr("file_ops_ref_fail"))

    def _on_import_landmask(self) -> None:
        """Extract land and sea from real maps"""
        from PIL import Image

        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("file_ops_landmask_title"), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All Files (*)",
        )
        if not file_path:
            return

        threshold, ok = QInputDialog.getInt(
            self, tr("file_ops_threshold_title"),
            tr("file_ops_threshold_prompt"),
            value=1, min=0, max=255,
        )
        if not ok:
            return

        invert_reply = QMessageBox.question(
            self, tr("file_ops_invert_title"), tr("file_ops_invert_prompt"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        invert = (invert_reply == QMessageBox.StandardButton.Yes)

        try:
            img = Image.open(file_path).convert("L")
            from data.constants import MAP_WIDTH, MAP_HEIGHT
            img = img.resize((MAP_WIDTH, MAP_HEIGHT), Image.Resampling.LANCZOS)
            arr = np.array(img, dtype=np.uint8)
            land_mask = (arr < threshold) if invert else (arr >= threshold)
        except Exception as e:
            QMessageBox.warning(self, tr("dlg_error"), tr("file_ops_img_read_fail", e))
            return

        # Record snapshots through BrushStrokeCommand (unify CommandHistory)
        from commands.land.brush_stroke import BrushStrokeCommand
        before = BrushStrokeCommand.snapshot_arrays({"tile_map": self._canvas.tile_map})

        new_tm = np.where(land_mask, TILE_LAND, TILE_SEA).astype(np.uint8)
        self._canvas.tile_map[:] = new_tm
        from domain.generators.province import auto_classify_water
        auto_classify_water(self._canvas.tile_map)

        # Submit a revocation order
        after = BrushStrokeCommand.snapshot_arrays({"tile_map": self._canvas.tile_map})
        cmd = BrushStrokeCommand("Extract land and sea from image", before, after)
        cmd.set_target_arrays({"tile_map": self._canvas.tile_map})
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()

        self._canvas.refresh_display()

        from data.constants import MAP_WIDTH, MAP_HEIGHT
        land_n = int(land_mask.sum())
        total = MAP_WIDTH * MAP_HEIGHT
        land_pct = f"{land_n/total*100:.1f}"
        sea_pct = f"{(1-land_n/total)*100:.1f}"
        self._status_info.setText(
            tr("file_ops_landmask_done", land_pct, sea_pct)
        )

    def _on_import_mod_map(self) -> None:
        """Import map layers from the HOI4 mod/vanilla directory"""
        reply = QMessageBox.question(
            self, tr("dlg_confirm"),
            tr("file_ops_import_confirm"),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        mod_dir = QFileDialog.getExistingDirectory(
            self, tr("file_ops_select_mod_dir"),
            "", QFileDialog.Option.ShowDirsOnly,
        )
        if not mod_dir:
            return

        from services.import_service import validate_mod_directory, import_mod_map

        missing = validate_mod_directory(mod_dir)
        if missing:
            QMessageBox.warning(
                self, tr("dlg_error"),
                tr("file_ops_missing_files") + "\n".join(missing),
            )
            return

        try:
            result = import_mod_map(mod_dir)
        except Exception as e:
            QMessageBox.warning(self, tr("dlg_error"), tr("file_ops_import_fail", e))
            return

        new_w, new_h = result["width"], result["height"]

        # Update global map dimensions
        from data.constants import set_map_size
        set_map_size(new_w, new_h)

        # Unified updates through Project (keeping the map_data of canvas and project synchronized)
        from domain.map_data import MapData
        md = MapData()
        # Replace array reference directly (dimensions may be different, cannot be written in place using [:] )
        md.tile_map = result["tile_map"]
        md.province_map = result["province_map"]
        md.terrain_map = result["terrain_map"]
        md.height_map = result["height_map"]
        if result["river_map"] is not None:
            md.river_map = result["river_map"]
        md.provincial_terrain = result.get("provincial_terrain", {})

        self._project.map_data = md
        self._project.state_mgr.clear()
        self._project.country_mgr.clear()
        self._project.continent_mgr.clear()
        self._project.strategic_region_mgr.clear()
        self._project.railway_mgr.clear()
        self._project.supply_mgr.clear()
        self._project.adjacency_mgr.clear()
        self._cmd_history.clear()

        # Imported art assets (colormap/world_normal, etc.) are retained and will not be overwritten when exporting
        imported_assets = result.get("assets", {})
        self._project.assets = dict(imported_assets)
        self._project.dirty_assets = set()

        # Populate states data
        _populate_imported_data(self._project, result)

        # Let canvas use the same map_data
        self._canvas.set_map_data(md)
        self._canvas._scene.setSceneRect(0, 0, new_w, new_h)
        self._canvas.refresh_display()
        self._update_province_count()
        # Refresh State/Country coloring (the color can only be seen after importing the cut mode)
        self._app._refresh_state_colors()
        self._app._refresh_country_colors()
        self._app._refresh_country_list()
        self._app._refresh_state_list()
        self._refresh_sr_list()
        self._refresh_logistics_counts()
        self._project.mark_dirty()

        state_count = len(self._project.state_mgr.states)
        sr_count = self._project.strategic_region_mgr.count()
        asset_count = len(self._project.assets)
        info_text = tr("file_ops_mod_imported", new_w, new_h,
                       result['province_count'], state_count, sr_count, asset_count)
        self._status_info.setText(info_text)

        warnings_text = ""
        if result["warnings"]:
            warnings_text = "\n\n" + tr("file_ops_import_warnings") + "\n".join(f"- {w}" for w in result["warnings"])
        QMessageBox.information(
            self, tr("file_ops_import_done"), info_text + warnings_text
        )

    # ═══════════════════════ Test export ═══════════════════════

    @staticmethod
    def _get_test_levels():
        return [
            (tr("file_ops_test_lv1_title"), tr("file_ops_test_lv1_desc")),
            (tr("file_ops_test_lv2_title"), tr("file_ops_test_lv2_desc")),
            (tr("file_ops_test_lv3_title"), tr("file_ops_test_lv3_desc")),
            (tr("file_ops_test_lv4_title"), tr("file_ops_test_lv4_desc")),
        ]

    def _on_test_export(self) -> None:
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QRadioButton,
            QDialogButtonBox, QLabel, QGroupBox,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("file_ops_test_dialog_title"))
        dlg.setMinimumWidth(500)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel(tr("file_ops_test_select_level")))

        test_levels = self._get_test_levels()
        group = QGroupBox()
        group_layout = QVBoxLayout(group)
        radios = []
        for i, (title, desc) in enumerate(test_levels):
            rb = QRadioButton(f"{title}\n    {desc}")
            rb.setStyleSheet("QRadioButton { padding: 6px 0; }")
            if i == 0:
                rb.setChecked(True)
            radios.append(rb)
            group_layout.addWidget(rb)
        layout.addWidget(group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        level = 1
        for i, rb in enumerate(radios):
            if rb.isChecked():
                level = i + 1
                break

        output_dir = QFileDialog.getExistingDirectory(
            self, tr("file_ops_test_output_dir"), DEFAULT_MOD_OUTPUT_PATH,
        )
        if not output_dir:
            return

        self._status_info.setText(tr("file_ops_test_generating", level))
        QApplication.processEvents()

        try:
            from export.test_exporter import export_test_mod
            export_test_mod(output_dir, level)
            QMessageBox.information(
                self, tr("file_ops_test_export_title"),
                tr("file_ops_test_export_ok", level, output_dir,
                   test_levels[level-1][0]),
            )
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self, tr("file_ops_export_fail"), f"{e}\n\n{traceback.format_exc()}"
            )
        finally:
            self._status_info.setText(tr("status_ready"))
