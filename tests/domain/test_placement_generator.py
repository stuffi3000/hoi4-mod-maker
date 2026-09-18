"""M5.2 deterministic placement proposal generator tests."""
from __future__ import annotations

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_LAKE, TILE_SEA
from domain.generators.placement import generate_placement_proposals

pytestmark = pytest.mark.unit


def _concave_land_map():
    province = np.zeros((9, 11), dtype=np.int32)
    province[1:8, 1:10] = 1
    province[4:8, 5:10] = 0  # make an inward corner
    province[2:6, 6:10] = 2
    tile = np.full(province.shape, TILE_SEA, dtype=np.uint8)
    tile[province == 1] = TILE_LAND
    tile[province == 2] = TILE_LAND
    return province, tile


def test_proposals_stay_inside_land_and_preserve_generated_state():
    province, tile = _concave_land_map()
    result = generate_placement_proposals(
        province, tile, province_ids=[1], slot_count=6,
        min_separation=1.1, seed=7,
    )

    assert [record.slot for record in result.slots] == list(range(6))
    assert result.diagnostics == []
    points = {(record.x, record.y) for record in result.slots}
    assert len(points) == 6
    for record in result.slots:
        row = int(record.y - 0.5)
        col = int(record.x - 0.5)
        assert province[row, col] == 1
        assert tile[row, col] == TILE_LAND
        assert record.provenance == "generated"
        assert record.review_status == "unreviewed"
        assert all(isinstance(value, float) for value in (
            record.x, record.y, record.rotation, record.height,
        ))


def test_coast_weight_prefers_interior_pixels():
    province = np.ones((7, 9), dtype=np.int32)
    tile = np.full(province.shape, TILE_LAND, dtype=np.uint8)
    tile[0, :] = TILE_SEA
    tile[-1, :] = TILE_SEA
    tile[:, 0] = TILE_SEA
    tile[:, -1] = TILE_SEA

    result = generate_placement_proposals(
        province, tile, province_ids=[1], slot_count=1,
        border_weight=0.0, coast_weight=5.0, min_separation=0.0,
    )
    record = result.slots[0]
    row = int(record.y - 0.5)
    col = int(record.x - 0.5)
    assert 2 <= row <= 4
    assert 2 <= col <= 6


def test_height_and_slope_are_used_and_one_pixel_dimension_is_safe():
    province = np.ones((1, 7), dtype=np.int32)
    tile = np.full(province.shape, TILE_LAND, dtype=np.uint8)
    height = np.array([[10.0, 10.0, 10.0, 200.0, 10.0, 10.0, 10.0]])
    result = generate_placement_proposals(
        province, tile, height, province_ids=[1], slot_count=2,
        min_separation=1.0, height_weight=1.0, slope_weight=3.0,
    )

    assert len(result.slots) == 2
    assert all(np.isfinite(record.height) for record in result.slots)
    assert all(record.height == height[0, int(record.x - 0.5)] for record in result.slots)


def test_same_seed_is_stable_and_output_order_is_canonical():
    province, tile = _concave_land_map()
    first = generate_placement_proposals(
        province, tile, province_ids=[2, 1], slot_count=3, seed=123,
    )
    second = generate_placement_proposals(
        province, tile, province_ids=[1, 2], slot_count=3, seed=123,
    )
    assert first == second
    assert [(record.province_id, record.slot) for record in first.slots] == sorted(
        (record.province_id, record.slot) for record in first.slots
    )


def test_sea_unknown_and_insufficient_space_are_explicit():
    province = np.array([[2, 2, 0], [3, 1, 0]], dtype=np.int32)
    tile = np.array(
        [[TILE_SEA, TILE_SEA, TILE_SEA],
         [TILE_LAKE, TILE_LAND, TILE_SEA]],
        dtype=np.uint8,
    )
    result = generate_placement_proposals(
        province, tile, province_ids=[1, 2, 3, 99], slot_count=2,
        min_separation=2.0,
    )

    assert [(record.province_id, record.slot) for record in result.slots] == [(1, 0)]
    assert [(diagnostic.province_id, diagnostic.code) for diagnostic in result.diagnostics] == [
        (1, "insufficient_space"),
        (2, "non_land"),
        (3, "non_land"),
        (99, "unknown_province"),
    ]
