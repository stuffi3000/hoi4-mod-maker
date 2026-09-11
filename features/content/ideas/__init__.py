"""National policy/idea editor (2.0 functionality, empty shell).

Ideas for editing common/ideas/*.txt in the future.
Read 1.0 map data (state_mgr / country_mgr, etc.), and implement it according to the Feature protocol extension."""

from features.base import BaseFeature


class IdeasFeature(BaseFeature):
    id = "content.ideas"
    display_name = "Ideas"
    category = "content"
    # Empty shell: No implementation yet, just let FeatureRegistry list available 2.0 features
