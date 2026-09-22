"""Province surface split detection and normalization tests."""
from __future__ import annotations

import numpy as np

from data.constants import TILE_LAKE, TILE_LAND, TILE_SEA
from domain.province_surface import (
    find_land_lake_splits,
    normalize_land_lake_splits,
)


def test_land_lake_split_is_detected_and_normalized_to_dominant_surface():
    province = np.array(
        [[1, 1, 1, 2], [1, 1, 1, 2], [1, 1, 1, 2]], dtype=np.int32
    )
    tile = np.full(province.shape, TILE_LAKE, dtype=np.uint8)
    tile[:, :1] = TILE_LAND
    tile[:, 3:] = TILE_SEA

    splits = find_land_lake_splits(tile, province)
    assert [(item.province_id, item.land, item.sea, item.lake) for item in splits] == [
        (1, 3, 0, 6)
    ]

    normalized = normalize_land_lake_splits(tile, province)
    assert [(item.province_id, item.target_surface, item.changed_pixels) for item in normalized] == [
        (1, "lake", 3)
    ]
    assert np.all(tile[province == 1] == TILE_LAKE)
    assert np.all(tile[province == 2] == TILE_SEA)
    assert find_land_lake_splits(tile, province) == ()


def test_land_majority_split_normalizes_to_land():
    province = np.ones((2, 4), dtype=np.int32)
    tile = np.array(
        [[TILE_LAND, TILE_LAND, TILE_LAND, TILE_LAKE],
         [TILE_LAND, TILE_LAND, TILE_LAND, TILE_LAKE]],
        dtype=np.uint8,
    )

    normalized = normalize_land_lake_splits(tile, province)
    assert normalized[0].target_surface == "land"
    assert normalized[0].changed_pixels == 2
    assert np.all(tile == TILE_LAND)
