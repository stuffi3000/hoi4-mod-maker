"""Project — The project data center that holds all manager and map data.

A Project = the entire contents of a .hoi4proj file.
All controllers access data through Project and do not directly hold manager references."""
from __future__ import annotations

import os
import time
import shutil
import threading

from model.events import EventBus
from domain.map_data import MapData
from domain.managers.state import StateManager
from domain.managers.country import CountryManager
from domain.managers.continent import ContinentManager
from domain.managers.adjacency import AdjacencyManager
from domain.managers.railway import RailwayManager
from domain.managers.supply_node import SupplyNodeManager
from domain.managers.adjacency_rule import AdjacencyRuleManager
from domain.managers.strategic_region import StrategicRegionManager
from domain.managers.colormap_settings import ColormapSettings
from domain.managers.default_map_settings import DefaultMapSettings


class Project:
    """Project data center."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or EventBus()
        self.map_data = MapData()
        self.state_mgr = StateManager()
        self.country_mgr = CountryManager()
        self.continent_mgr = ContinentManager()
        self.adjacency_mgr = AdjacencyManager()
        self.railway_mgr = RailwayManager()
        self.supply_mgr = SupplyNodeManager()
        self.adjacency_rule_mgr = AdjacencyRuleManager()
        self.strategic_region_mgr = StrategicRegionManager()
        self.colormap_settings = ColormapSettings.default()
        self.default_map_settings = DefaultMapSettings()

        self._path: str | None = None  # current save path
        self._dirty = False  # unsaved changes
        self._autosave_interval = 300  # seconds (5 min)
        self._autosave_timer: threading.Timer | None = None
        self._last_save_time = 0.0

        # ── Art asset system ──
        # assets: relative mod path → raw file bytes (read from imported mod)
        # Example: {"map/terrain/colormap_rgb_cityemissivemask_a.dds": b"..."}
        # When exporting, if path is in assets and not in dirty_assets → write back the original bytes directly
        # Not in assets or in dirty_assets → go writer Regenerate
        self.assets: dict[str, bytes] = {}
        self.dirty_assets: set[str] = set()

    # ── Art Asset Management API ─────────────────────────────────────
    def set_asset(self, rel_path: str, data: bytes) -> None:
        """Record an original art file when importing."""
        self.assets[rel_path] = data
        # The imported assets are clean by default (original, no need to regenerate)
        self.dirty_assets.discard(rel_path)

    def mark_asset_dirty(self, rel_path: str) -> None:
        """Flags an art asset that needs to be regenerated on export."""
        if rel_path in self.assets:
            self.dirty_assets.add(rel_path)

    def mark_assets_dirty(self, *rel_paths: str) -> None:
        """Mark multiple art assets dirty in batches."""
        for p in rel_paths:
            self.mark_asset_dirty(p)

    def is_asset_clean(self, rel_path: str) -> bool:
        """The asset exists and is not marked dirty → the original bytes can be written back directly."""
        return rel_path in self.assets and rel_path not in self.dirty_assets

    def clean_asset_count(self) -> int:
        """The original number of bytes of assets will be retained when exporting."""
        return len(self.assets) - len(self.dirty_assets & self.assets.keys())

    def dirty_asset_count(self) -> int:
        """The number of assets that will be regenerated on export."""
        return len(self.dirty_assets & self.assets.keys())

    @property
    def path(self) -> str | None:
        return self._path

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> None:
        """Marked with unsaved changes."""
        self._dirty = True

    def mark_clean(self) -> None:
        self._dirty = False

    def new_project(self, width: int, height: int) -> None:
        """Create new project."""
        from data.constants import set_map_size

        set_map_size(width, height)
        self.map_data = MapData()
        self.state_mgr = StateManager()
        self.country_mgr = CountryManager()
        self.continent_mgr = ContinentManager()
        self.adjacency_mgr = AdjacencyManager()
        self.railway_mgr = RailwayManager()
        self.supply_mgr = SupplyNodeManager()
        self.adjacency_rule_mgr = AdjacencyRuleManager()
        self.strategic_region_mgr = StrategicRegionManager()
        self.colormap_settings = ColormapSettings.default()
        self.default_map_settings = DefaultMapSettings()
        self.assets = {}
        self.dirty_assets = set()
        self._path = None
        self._dirty = False

    def save(self, path: str | None = None) -> None:
        """Save project to file."""
        save_path = path or self._path
        if not save_path:
            raise ValueError("No save path was specified")
        from domain.project_io import save_project

        save_project(
            save_path,
            tile_map=self.map_data.tile_map,
            province_map=self.map_data.province_map,
            terrain_map=self.map_data.terrain_map,
            height_map=self.map_data.height_map,
            state_mgr=self.state_mgr,
            country_mgr=self.country_mgr,
            river_map=self.map_data.river_map,
            continent_mgr=self.continent_mgr,
            adjacency_mgr=self.adjacency_mgr,
            railway_mgr=self.railway_mgr,
            supply_mgr=self.supply_mgr,
            adjacency_rule_mgr=self.adjacency_rule_mgr,
            strategic_region_mgr=self.strategic_region_mgr,
            provincial_terrain=self.map_data.provincial_terrain,
            tile_snapshot=self.map_data.tile_snapshot,
        )
        # At the same time, persist art assets to the sidecar directory
        self._save_assets_sidecar(save_path)
        self._path = save_path
        self._dirty = False
        self._last_save_time = time.time()

    # ── Art asset sidecar (accompanying .hoi4proj’s _assets directory with the same name) ──
    @staticmethod
    def _sidecar_dir(proj_path: str) -> str:
        """Returns the asset directory path corresponding to .hoi4proj."""
        return proj_path + "_assets"

    def _save_assets_sidecar(self, proj_path: str) -> None:
        """Write all bytes in self.assets to the sidecar directory."""
        sidecar = self._sidecar_dir(proj_path)
        # If there are no assets, no directory will be created.
        if not self.assets:
            # If the sidecar directory already exists but assets is empty, clear it (the user may have deleted all imported assets)
            if os.path.isdir(sidecar):
                shutil.rmtree(sidecar, ignore_errors=True)
            return
        os.makedirs(sidecar, exist_ok=True)
        # write a list
        manifest_lines = []
        for rel_path, data in self.assets.items():
            # Use rel_path directly as the relative path within the sidecar
            dst = os.path.join(sidecar, rel_path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            dirty_mark = "DIRTY" if rel_path in self.dirty_assets else "CLEAN"
            manifest_lines.append(f"{dirty_mark}\t{rel_path}\t{len(data)}")
        # Manifest file (convenient for manual viewing + recording dirty status)
        with open(os.path.join(sidecar, "_manifest.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(manifest_lines))

    def _load_assets_sidecar(self, proj_path: str) -> None:
        """Read back the assets and dirty status from the sidecar directory."""
        self.assets = {}
        self.dirty_assets = set()
        sidecar = self._sidecar_dir(proj_path)
        manifest_path = os.path.join(sidecar, "_manifest.txt")
        if not os.path.isfile(manifest_path):
            return  # Old projects or projects started from 0 do not have sidecars
        with open(manifest_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                dirty_mark, rel_path = parts[0], parts[1]
                src = os.path.join(sidecar, rel_path)
                if not os.path.isfile(src):
                    continue
                with open(src, "rb") as bf:
                    self.assets[rel_path] = bf.read()
                if dirty_mark == "DIRTY":
                    self.dirty_assets.add(rel_path)

    def load(self, path: str) -> None:
        """Load project files."""
        from domain.project_io import load_project

        result = load_project(
            path,
            state_mgr=self.state_mgr,
            country_mgr=self.country_mgr,
            continent_mgr=self.continent_mgr,
            adjacency_mgr=self.adjacency_mgr,
            railway_mgr=self.railway_mgr,
            supply_mgr=self.supply_mgr,
            adjacency_rule_mgr=self.adjacency_rule_mgr,
            strategic_region_mgr=self.strategic_region_mgr,
        )
        tile_map, province_map, terrain_map, height_map, river_map, provincial_terrain, tile_snapshot = result

        # Update map size from loaded data
        from data.constants import set_map_size

        h, w = tile_map.shape
        set_map_size(w, h)

        self.map_data = MapData()
        self.map_data.replace_all(
            tile_map=tile_map,
            province_map=province_map,
            terrain_map=terrain_map,
            height_map=height_map,
        )
        if river_map is not None:
            self.map_data.river_map[:] = river_map
        self.map_data.provincial_terrain = provincial_terrain or {}
        self.map_data.tile_snapshot = tile_snapshot if tile_snapshot is not None else tile_map.copy()

        # Read art assets from sidecar
        self._load_assets_sidecar(path)

        self._path = path
        self._dirty = False

    def start_autosave(self) -> None:
        """Start the autosave timer."""
        self._stop_autosave()
        if self._path and self._autosave_interval > 0:
            self._autosave_timer = threading.Timer(
                self._autosave_interval, self._do_autosave
            )
            self._autosave_timer.daemon = True
            self._autosave_timer.start()

    def _stop_autosave(self) -> None:
        if self._autosave_timer:
            self._autosave_timer.cancel()
            self._autosave_timer = None

    def _do_autosave(self) -> None:
        """Auto save callback."""
        if self._dirty and self._path:
            try:
                # Save to autosave path (not overwrite main file)
                autosave_path = self._path + ".autosave"
                self.save(autosave_path)
                self._path = self._path.replace(".autosave", "")  # restore original path
                self.event_bus.emit("status_message", text="Autosave complete")
            except Exception:
                pass  # autosave failure is silent
        # Reschedule
        self.start_autosave()

    def close(self) -> None:
        """Close the project and clean up resources."""
        self._stop_autosave()
