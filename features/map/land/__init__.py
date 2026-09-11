"""Continent feature - Land, sea and lake brush + Voronoi province generation."""

from features.base import BaseFeature


class LandFeature(BaseFeature):
    id = "map.land"
    display_name = "Land"
    category = "map"
    # 1.0 has been implemented, page/renderer is in the same directory
