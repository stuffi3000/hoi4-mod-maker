"""River feature - River drawing + HOI4 color palette."""

from features.base import BaseFeature


class RiverFeature(BaseFeature):
    id = "map.river"
    display_name = "Rivers"
    category = "map"
    # 1.0 has been implemented, page/renderer is in the same directory
