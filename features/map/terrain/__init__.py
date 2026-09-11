"""Terrain feature - 10 types of terrain assigned values by province."""

from features.base import BaseFeature


class TerrainFeature(BaseFeature):
    id = "map.terrain"
    display_name = "Terrain"
    category = "map"
    # 1.0 has been implemented, page/renderer is in the same directory
