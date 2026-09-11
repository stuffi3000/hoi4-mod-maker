"""Feature base class — a unified interface for feature modules.

Each feature (map/land, map/state, content/tech_tree, etc.) implements this interface,
Register in app/container.py. Adding new features = creating a new feature directory + registering one line, leaving no changes in other places.

Interface convention:
- id: globally unique identifier, for example 'map.land' 'content.tech_tree'
- display_name: user visible name
- category: 'map' or 'content', corresponding to top mode switching
- build_page(parent) -> QWidget | None: Sidebar tab content, returning None means that the function is not exposed in the sidebar
- build_renderer() -> object | None: canvas renderer, returning None means reusing the previous feature
- build_tools() -> list[Tool]: canvas tool used by this function
- register_menu(menu_bar): optional, register actions in the menu bar
- on_activate(ctx) / on_deactivate(ctx): hook when switching to/leaving this feature"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class FeatureContext:
    """All application-level objects accessible by Feature. Injected by container."""
    # Data manager (domain layer)
    map_data: object = None
    state_mgr: object = None
    country_mgr: object = None
    continent_mgr: object = None
    river_mgr: object = None
    undo_mgr: object = None
    # UI root object (for feature to pop up dialog box/get status bar when needed)
    main_window: object = None
    canvas: object = None
    # Can be added in the future: strategic_region_mgr, railway_mgr, command_bus, etc.
    extras: dict = field(default_factory=dict)


class Feature(Protocol):
    """Feature protocol — every feature module must implement it."""

    id: str
    display_name: str
    category: str  # 'map' | 'content'

    def build_page(self, ctx: FeatureContext):
        """Returns the sidebar QWidget, or None for no UI panel."""
        ...

    def build_renderer(self, ctx: FeatureContext):
        """Return canvas Renderer, or None to reuse the default."""
        ...

    def build_tools(self, ctx: FeatureContext) -> list:
        """Returns the list of canvas Tools used by this function."""
        ...

    def on_activate(self, ctx: FeatureContext) -> None:
        """Called when switching to this feature (refreshing UI, connecting signals, etc.)."""
        ...

    def on_deactivate(self, ctx: FeatureContext) -> None:
        """Called when leaving the feature (cleaning up temporary state)."""
        ...


class BaseFeature:
    """The default empty implementation of Feature, subclasses can override as needed."""

    id: str = ""
    display_name: str = ""
    category: str = "map"

    def build_page(self, ctx: FeatureContext):
        return None

    def build_renderer(self, ctx: FeatureContext):
        return None

    def build_tools(self, ctx: FeatureContext) -> list:
        return []

    def on_activate(self, ctx: FeatureContext) -> None:
        pass

    def on_deactivate(self, ctx: FeatureContext) -> None:
        pass
