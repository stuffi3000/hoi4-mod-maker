"""Strategy overview map color feature.

Control the land/sea/lake color of map/terrain/colormap_rgb_cityemissivemask_a.dds,
Make the overhead MOD no longer look like the Earth. Open the dialog via the menu "Tools → Overview Map Colors..."."""

from features.base import BaseFeature


class ColormapFeature(BaseFeature):
    id = "map.colormap"
    display_name = "Colormap"
    category = "map"
    # Triggered through menu, not exposed in mode tab
