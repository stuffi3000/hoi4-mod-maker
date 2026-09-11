"""Name list editor (2.0 functionality, empty shell).

In the future, it will be used to edit common/names/*.txt and unit naming.
Read 1.0 map data (state_mgr / country_mgr, etc.), and implement it according to the Feature protocol extension."""

from features.base import BaseFeature


class NamelistFeature(BaseFeature):
    id = "content.namelist"
    display_name = "Name lists"
    category = "content"
    # Empty shell: No implementation yet, just let FeatureRegistry list available 2.0 features
