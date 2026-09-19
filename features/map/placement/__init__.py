"""Placement review feature (M5.2/M5.3 UI slice).

Standalone review page; the parent wires it to PlacementController later.
"""

from features.map.placement.page import PlacementPage, parse_sea_mapping

__all__ = ["PlacementPage", "parse_sea_mapping"]