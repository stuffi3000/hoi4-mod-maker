"""Resolution Editor (2.0 functionality, empty shell).

Used to edit future resolutions in common/decisions/*.txt.
Read 1.0 map data (state_mgr / country_mgr, etc.), and implement it according to the Feature protocol extension."""

from features.base import BaseFeature


class DecisionsFeature(BaseFeature):
    id = "content.decisions"
    display_name = "Decisions"
    category = "content"
    # Empty shell: No implementation yet, just let FeatureRegistry list available 2.0 features
