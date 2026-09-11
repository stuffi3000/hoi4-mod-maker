"""Starting force editor (2.0 feature, empty shell).

The starting OOB for future editing of history/units/*.txt.
Read 1.0 map data (state_mgr / country_mgr, etc.), and implement it according to the Feature protocol extension."""

from features.base import BaseFeature


class OobFeature(BaseFeature):
    id = "content.oob"
    display_name = "Order of battle"
    category = "content"
    # Empty shell: No implementation yet, just let FeatureRegistry list available 2.0 features
