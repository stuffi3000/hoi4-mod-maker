"""Focus tree editor (2.0 functionality, empty shell).

The national policy tree will be used to edit common/national_focus/*.txt in the future.
Read 1.0 map data (state_mgr / country_mgr, etc.), and implement it according to the Feature protocol extension."""

from features.base import BaseFeature


class FocusTreeFeature(BaseFeature):
    id = "content.focus_tree"
    display_name = "Focus tree"
    category = "content"
    # Empty shell: No implementation yet, just let FeatureRegistry list available 2.0 features
