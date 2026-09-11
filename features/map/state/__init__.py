"""State feature - State grouping + advanced field editing."""

from features.base import BaseFeature


class StateFeature(BaseFeature):
    id = "map.state"
    display_name = "State"
    category = "map"
    # 1.0 has been implemented, page/renderer is in the same directory
