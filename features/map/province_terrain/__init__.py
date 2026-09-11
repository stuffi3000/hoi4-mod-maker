"""Province attribute terrain feature — Displays the gameplay terrain (with color blocks) for each province.

Differentiate from terrain feature:
- terrain feature: display + edit terrain.bmp pixels (visual)
- province_terrain feature: display + edit the gameplay terrain type (attribute) of each province

The two modes are completely independent: in the province_terrain mode, clicking province only changes the attributes, not the visual."""

from features.base import BaseFeature


class ProvincialTerrainFeature(BaseFeature):
    id = "map.province_terrain"
    display_name = "Provincial terrain"
    category = "map"
