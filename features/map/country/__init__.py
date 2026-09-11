"""Country feature - Country CRUD + color/party/capital."""

from features.base import BaseFeature


class CountryFeature(BaseFeature):
    id = "map.country"
    display_name = "Countries"
    category = "map"
    # 1.0 has been implemented, page/renderer is in the same directory
