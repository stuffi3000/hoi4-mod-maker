"""default.map configures feature.

Controls the map loading behavior of the HOI4 engine. Open via the menu "Tools → Map Configuration..."."""

from features.base import BaseFeature


class DefaultMapFeature(BaseFeature):
    id = "map.default_map"
    display_name = "Map configuration"
    category = "map"
