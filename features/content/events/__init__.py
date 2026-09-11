"""Event Editor (2.0 feature, empty shell).

Events for future editing of events/*.txt.
Read 1.0 map data (state_mgr / country_mgr, etc.), and implement it according to the Feature protocol extension."""

from features.base import BaseFeature


class EventsFeature(BaseFeature):
    id = "content.events"
    display_name = "Events"
    category = "content"
    # Empty shell: No implementation yet, just let FeatureRegistry list available 2.0 features
