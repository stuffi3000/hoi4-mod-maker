"""Application assembly container — creates all managers and Features and injects them into the UI.

Steps to add new features (refactoring goals):
1. Create a new directory in features/map/ or features/content/
2. __init__.py of the new directory defines the Feature subclass
3. Add a line register to _register_map_features / _register_content_features in this file
4. Zero changes elsewhere.

This is the core of the "single file extension point". Don't bypass it and change main_window / tool_panel directly."""

from __future__ import annotations

from app.registry import FeatureRegistry
from commands.bus import CommandBus

# domain managers
from domain.managers.state import StateManager
from domain.managers.country import CountryManager
from domain.managers.continent import ContinentManager
from domain.undo_manager import UndoManager

# map features
from features.map.land import LandFeature
from features.map.province import ProvinceFeature
from features.map.terrain import TerrainFeature
from features.map.height import HeightFeature
from features.map.state import StateFeature
from features.map.country import CountryFeature
from features.map.river import RiverFeature
from features.map.continent import ContinentFeature
from features.map.logistics import LogisticsFeature
from features.map.colormap import ColormapFeature
from features.map.default_map import DefaultMapFeature
from features.map.strategic_region import StrategicRegionFeature
from features.map.preview import PreviewFeature

# content features (2.0 empty shell, not currently exposed in the UI)
from features.content.tech_tree import TechTreeFeature
from features.content.focus_tree import FocusTreeFeature
from features.content.events import EventsFeature
from features.content.decisions import DecisionsFeature
from features.content.characters import CharactersFeature
from features.content.portraits import PortraitsFeature
from features.content.oob import OobFeature
from features.content.namelist import NamelistFeature
from features.content.flags import FlagsFeature
from features.content.ideas import IdeasFeature


class AppContainer:
    """Global application container. MainWindow holds an instance and all services are taken from here."""

    def __init__(self) -> None:
        # ─── domain data manager ───
        self.state_mgr = StateManager()
        self.country_mgr = CountryManager()
        self.continent_mgr = ContinentManager()
        self.undo_mgr = UndoManager(max_steps=30)

        # ─── Command bus (for new functions, old undo continues to use UndoManager) ───
        self.command_bus = CommandBus(max_history=30)

        # ─── Feature Registry ───
        self.features = FeatureRegistry()
        self._register_map_features()
        self._register_content_features()

    def _register_map_features(self) -> None:
        """Register for 1.0 map functionality."""
        for f in [
            LandFeature(),
            ProvinceFeature(),
            TerrainFeature(),
            HeightFeature(),
            StateFeature(),
            CountryFeature(),
            RiverFeature(),
            ContinentFeature(),
            LogisticsFeature(),
            ColormapFeature(),
            DefaultMapFeature(),
            StrategicRegionFeature(),
            PreviewFeature(),
        ]:
            self.features.register(f)

    def _register_content_features(self) -> None:
        """Register 2.0 content function (currently all empty shells, the UI is optional and not exposed)."""
        for f in [
            TechTreeFeature(),
            FocusTreeFeature(),
            EventsFeature(),
            DecisionsFeature(),
            CharactersFeature(),
            PortraitsFeature(),
            OobFeature(),
            NamelistFeature(),
            FlagsFeature(),
            IdeasFeature(),
        ]:
            self.features.register(f)

    def map_feature_count(self) -> int:
        return len(self.features.by_category("map"))

    def content_feature_count(self) -> int:
        return len(self.features.by_category("content"))
