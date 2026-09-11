"""Province feature - merge/cut/lasso expansion."""

from features.base import BaseFeature


class ProvinceFeature(BaseFeature):
    id = "map.province"
    display_name = "Provinces"
    category = "map"
    # 1.0 has been implemented, page/renderer is in the same directory
