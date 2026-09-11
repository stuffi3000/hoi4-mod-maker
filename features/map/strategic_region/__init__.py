"""Strategic regions feature - manually group provinces into regions + weather presets + naval_terrain."""

from features.base import BaseFeature


class StrategicRegionFeature(BaseFeature):
    id = "map.strategic_region"
    display_name = "Strategic regions"
    category = "map"
