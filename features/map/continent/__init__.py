"""Continental partition feature - multi-continent definition + province assignment."""

from features.base import BaseFeature


class ContinentFeature(BaseFeature):
    id = "map.continent"
    display_name = "Continents"
    category = "map"
    # 1.0 has been implemented, page/renderer is in the same directory
