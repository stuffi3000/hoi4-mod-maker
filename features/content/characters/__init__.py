"""Character Editor (2.0 feature, empty shell).

Characters to be used to edit common/characters/*.txt in the future.
Read 1.0 map data (state_mgr / country_mgr, etc.), and implement it according to the Feature protocol extension."""

from features.base import BaseFeature


class CharactersFeature(BaseFeature):
    id = "content.characters"
    display_name = "Characters"
    category = "content"
    # Empty shell: No implementation yet, just let FeatureRegistry list available 2.0 features
