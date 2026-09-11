"""Flag Editor (2.0 functionality, empty shell).

Used to import and manage gfx/flags/*.tga in the future.
Read 1.0 map data (state_mgr / country_mgr, etc.), and implement it according to the Feature protocol extension."""

from features.base import BaseFeature


class FlagsFeature(BaseFeature):
    id = "content.flags"
    display_name = "Flags"
    category = "content"
    # Empty shell: No implementation yet, just let FeatureRegistry list available 2.0 features
