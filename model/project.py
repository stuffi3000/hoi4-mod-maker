"""Project — 项目数据中心，持有所有 manager 和地图数据。

一个 Project = 一个 .hoi4proj 文件的全部内容。
所有 controller 通过 Project 访问数据，不直接持有 manager 引用。
"""
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
    """项目数据中心。"""

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

        # ── 美术资产系统 ──
        # assets: 相对 MOD 路径 → 原始文件字节（从导入的 MOD 读取）
        # 例：{"map/terrain/colormap_rgb_cityemissivemask_a.dds": b"..."}
        # 导出时如果 path 在 assets 且不在 dirty_assets → 直接写回原始字节
        # 不在 assets 或在 dirty_assets → 走 writer 重新生成
        self.assets: dict[str, bytes] = {}
        self.dirty_assets: set[str] = set()

    # ── 美术资产管理 API ──────────────────────────────────────
    def set_asset(self, rel_path: str, data: bytes) -> None:
        """导入时记录一个原始美术文件。"""
        self.assets[rel_path] = data
        # 导入的资产默认是 clean（原始、无需重生）
        self.dirty_assets.discard(rel_path)

    def mark_asset_dirty(self, rel_path: str) -> None:
        """标记某个美术资产需要在导出时重新生成。"""
        if rel_path in self.assets:
            self.dirty_assets.add(rel_path)

    def mark_assets_dirty(self, *rel_paths: str) -> None:
        """批量标记多个美术资产 dirty。"""
        for p in rel_paths:
            self.mark_asset_dirty(p)

    def is_asset_clean(self, rel_path: str) -> bool:
        """asset 存在且未被标记 dirty → 可以直接写回原字节。"""
        return rel_path in self.assets and rel_path not in self.dirty_assets

    def clean_asset_count(self) -> int:
        """导出时将保留原字节的资产数。"""
        return len(self.assets) - len(self.dirty_assets & self.assets.keys())

    def dirty_asset_count(self) -> int:
        """导出时将重新生成的资产数。"""
        return len(self.dirty_assets & self.assets.keys())

    @property
    def path(self) -> str | None:
        return self._path

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> None:
        """标记有未保存的修改。"""
        self._dirty = True

    def mark_clean(self) -> None:
        self._dirty = False

    def new_project(self, width: int, height: int) -> None:
        """创建新项目。"""
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
        """保存项目到文件。"""
        save_path = path or self._path
        if not save_path:
            from ui.i18n import tr_pair
            raise ValueError(tr_pair("没有指定保存路径", "No save path was specified"))
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
        # 同时持久化美术资产到 sidecar 目录
        self._save_assets_sidecar(save_path)
        self._path = save_path
        self._dirty = False
        self._last_save_time = time.time()

    # ── 美术资产 sidecar（伴随 .hoi4proj 的同名 _assets 目录） ──
    @staticmethod
    def _sidecar_dir(proj_path: str) -> str:
        """返回 .hoi4proj 对应的资产目录路径。"""
        return proj_path + "_assets"

    def _save_assets_sidecar(self, proj_path: str) -> None:
        """把 self.assets 里所有字节写到 sidecar 目录。"""
        sidecar = self._sidecar_dir(proj_path)
        # 没有资产就不建目录
        if not self.assets:
            # 如果 sidecar 目录已存在但 assets 空，清掉（用户可能删光了导入资产）
            if os.path.isdir(sidecar):
                shutil.rmtree(sidecar, ignore_errors=True)
            return
        os.makedirs(sidecar, exist_ok=True)
        # 写清单
        manifest_lines = []
        for rel_path, data in self.assets.items():
            # 用 rel_path 直接作为 sidecar 内相对路径
            dst = os.path.join(sidecar, rel_path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            dirty_mark = "DIRTY" if rel_path in self.dirty_assets else "CLEAN"
            manifest_lines.append(f"{dirty_mark}\t{rel_path}\t{len(data)}")
        # 清单文件（方便人工查看 + 记 dirty 状态）
        with open(os.path.join(sidecar, "_manifest.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(manifest_lines))

    def _load_assets_sidecar(self, proj_path: str) -> None:
        """从 sidecar 目录读回 assets 和 dirty 状态。"""
        self.assets = {}
        self.dirty_assets = set()
        sidecar = self._sidecar_dir(proj_path)
        manifest_path = os.path.join(sidecar, "_manifest.txt")
        if not os.path.isfile(manifest_path):
            return  # 旧项目或从 0 开始的项目没 sidecar
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
        """加载项目文件。"""
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

        # 从 sidecar 读取美术资产
        self._load_assets_sidecar(path)

        self._path = path
        self._dirty = False

    def start_autosave(self) -> None:
        """启动自动保存定时器。"""
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
        """自动保存回调。"""
        if self._dirty and self._path:
            try:
                # Save to autosave path (not overwrite main file)
                autosave_path = self._path + ".autosave"
                self.save(autosave_path)
                self._path = self._path.replace(".autosave", "")  # restore original path
                from ui.i18n import tr_pair
                self.event_bus.emit("status_message", text=tr_pair("自动保存完成", "Autosave complete"))
            except Exception:
                pass  # autosave failure is silent
        # Reschedule
        self.start_autosave()

    def close(self) -> None:
        """关闭项目，清理资源。"""
        self._stop_autosave()
