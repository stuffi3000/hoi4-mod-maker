"""Tech tree editor (2.0 functionality, empty shell).

The technology tree used to edit common/technologies/*.txt in the future.
Read 1.0 map data (state_mgr / country_mgr, etc.), and implement it according to the Feature protocol extension."""

from features.base import BaseFeature


class TechTreeFeature(BaseFeature):
    id = "content.tech_tree"
    display_name = "Technology tree"
    category = "content"
    # Empty shell: No implementation yet, just let FeatureRegistry list available 2.0 features
