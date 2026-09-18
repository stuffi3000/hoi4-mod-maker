"""Deterministic port proposal generator tests."""

from __future__ import annotations

import math

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_LAKE, TILE_SEA
from domain.generators.placement import generate_port_proposals

pytestmark = pytest.mark.unit


def _clean_coastal_map():
    province = np.array(
        [[1, 1, 1, 2], [1, 1, 1, 2], [1, 1, 1, 2]], dtype=np.int32
    )
    tile = np.full(province.shape, TILE_LAND, dtype=np.uint8)
    tile[province == 2] = TILE_SEA
    return province, tile


def _two_sea_map():
    province = np.array(
        [[1, 1, 2, 3], [1, 1, 2, 3], [1, 1, 2, 3]], dtype=np.int32
    )
    tile = np.full(province.shape, TILE_LAND, dtype=np.uint8)
    tile[province == 2] = TILE_SEA
    tile[province == 3] = TILE_SEA
    return province, tile


def test_clean_exact_connection_emits_single_port():
    province, tile = _clean_coastal_map()
    result = generate_port_proposals(province, tile, {1: 2}, province_ids=[1], seed=3)
    assert len(result.ports) == 1
    assert result.diagnostics == []
    port = result.ports[0]
    assert port.province_id == 1
    assert port.sea_province == 2
    col = int(port.x - 0.5)
    row = int(port.y - 0.5)
    assert province[row, col] == 1
    assert tile[row, col] == TILE_LAND
    neighbours = [(row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)]
    assert any(
        0 <= nrow < province.shape[0]
        and 0 <= ncol < province.shape[1]
        and province[nrow, ncol] == 2
        and tile[nrow, ncol] == TILE_SEA
        for nrow, ncol in neighbours
    )


def test_wrong_sea_never_falls_back_to_adjacent_sea():
    province, tile = _two_sea_map()
    result = generate_port_proposals(province, tile, {1: 3}, province_ids=[1])
    assert result.ports == []
    assert [(diag.province_id, diag.code) for diag in result.diagnostics] == [
        (1, "no_adjacency")
    ]
    assert "3" in result.diagnostics[0].message


def test_absent_sea_reports_unknown_sea():
    province, tile = _clean_coastal_map()
    result = generate_port_proposals(province, tile, {1: 99}, province_ids=[1])
    assert result.ports == []
    assert [(diag.province_id, diag.code) for diag in result.diagnostics] == [
        (1, "unknown_sea")
    ]


def test_non_coastal_land_reports_no_adjacency():
    province = np.array(
        [[1, 1, 0, 0], [1, 1, 0, 0], [0, 0, 2, 2], [0, 0, 2, 2]], dtype=np.int32
    )
    tile = np.full(province.shape, TILE_SEA, dtype=np.uint8)
    tile[province == 1] = TILE_LAND
    tile[province == 2] = TILE_SEA
    result = generate_port_proposals(province, tile, {1: 2}, province_ids=[1])
    assert result.ports == []
    assert [(diag.province_id, diag.code) for diag in result.diagnostics] == [
        (1, "no_adjacency")
    ]


def test_diagonal_touch_does_not_count_as_adjacency():
    province = np.array([[1, 0], [0, 2]], dtype=np.int32)
    tile = np.array(
        [[TILE_LAND, TILE_SEA], [TILE_SEA, TILE_SEA]], dtype=np.uint8
    )
    result = generate_port_proposals(province, tile, {1: 2}, province_ids=[1])
    assert result.ports == []
    assert [(diag.province_id, diag.code) for diag in result.diagnostics] == [
        (1, "no_adjacency")
    ]


def test_deterministic_output_and_canonical_order():
    province = np.array(
        [
            [1, 1, 2, 3, 3],
            [1, 1, 2, 3, 3],
            [1, 1, 2, 3, 3],
        ],
        dtype=np.int32,
    )
    tile = np.full(province.shape, TILE_LAND, dtype=np.uint8)
    tile[province == 2] = TILE_SEA
    tile[province == 3] = TILE_SEA
    province[0, 3] = 4
    province[1, 3] = 4
    province[2, 3] = 4
    tile[province == 4] = TILE_LAND
    mapping = {1: 2, 4: 3}
    first = generate_port_proposals(province, tile, mapping, province_ids=[4, 1], seed=11)
    second = generate_port_proposals(province, tile, mapping, province_ids=[1, 4], seed=11)
    assert first == second
    assert [port.province_id for port in first.ports] == sorted(
        port.province_id for port in first.ports
    )
    assert len(first.ports) == 2
    assert first.diagnostics == []
    repeat = generate_port_proposals(province, tile, mapping, province_ids=[1, 4], seed=11)
    assert repeat == first


def test_provenance_is_generated_unreviewed():
    province, tile = _clean_coastal_map()
    result = generate_port_proposals(province, tile, {1: 2})
    assert len(result.ports) == 1
    port = result.ports[0]
    assert port.provenance == "generated"
    assert port.review_status == "unreviewed"


def test_float_pixel_centers_and_local_height_preserved():
    province, tile = _clean_coastal_map()
    height = np.full(province.shape, 12.0, dtype=np.float64)
    height[1, 1] = 77.5
    result = generate_port_proposals(
        province, tile, {1: 2}, height_map=height, province_ids=[1], seed=5
    )
    assert len(result.ports) == 1
    port = result.ports[0]
    assert isinstance(port.x, float)
    assert isinstance(port.y, float)
    assert isinstance(port.rotation, float)
    assert isinstance(port.height, float)
    assert math.isfinite(port.x)
    assert math.isfinite(port.y)
    assert math.isfinite(port.height)
    assert port.rotation == 0.0
    col = int(port.x - 0.5)
    row = int(port.y - 0.5)
    assert port.x == float(col) + 0.5
    assert port.y == float(row) + 0.5
    assert port.height == float(height[row, col])


def test_non_finite_height_is_replaced_with_zero():
    province, tile = _clean_coastal_map()
    height = np.full(province.shape, float("inf"), dtype=np.float64)
    result = generate_port_proposals(
        province, tile, {1: 2}, height_map=height, province_ids=[1]
    )
    assert len(result.ports) == 1
    assert result.ports[0].height == 0.0
    assert math.isfinite(result.ports[0].height)


def test_unknown_land_missing_and_invalid_mapping_are_explicit():
    province, tile = _clean_coastal_map()
    unknown = generate_port_proposals(province, tile, {99: 2}, province_ids=[99])
    assert unknown.ports == []
    assert [(diag.province_id, diag.code) for diag in unknown.diagnostics] == [
        (99, "unknown_province")
    ]
    missing = generate_port_proposals(province, tile, {}, province_ids=[1])
    assert missing.ports == []
    assert [(diag.province_id, diag.code) for diag in missing.diagnostics] == [
        (1, "missing_mapping")
    ]
    invalid = generate_port_proposals(province, tile, {1: 0}, province_ids=[1])
    assert invalid.ports == []
    assert [(diag.province_id, diag.code) for diag in invalid.diagnostics] == [
        (1, "invalid_mapping")
    ]
    invalid_type = generate_port_proposals(province, tile, {1: "harbor"}, province_ids=[1])
    assert invalid_type.ports == []
    assert [(diag.province_id, diag.code) for diag in invalid_type.diagnostics] == [
        (1, "invalid_mapping")
    ]


def test_non_land_and_non_sea_are_explicit():
    province = np.array([[1, 1, 2], [1, 1, 2]], dtype=np.int32)
    tile = np.full(province.shape, TILE_SEA, dtype=np.uint8)
    tile[province == 2] = TILE_SEA
    non_land = generate_port_proposals(province, tile, {1: 2}, province_ids=[1])
    assert non_land.ports == []
    assert [(diag.province_id, diag.code) for diag in non_land.diagnostics] == [
        (1, "non_land")
    ]
    province_lake = np.array([[1, 1, 2], [1, 1, 2]], dtype=np.int32)
    tile_lake = np.full(province_lake.shape, TILE_LAND, dtype=np.uint8)
    tile_lake[province_lake == 2] = TILE_LAKE
    non_sea = generate_port_proposals(province_lake, tile_lake, {1: 2}, province_ids=[1])
    assert non_sea.ports == []
    assert [(diag.province_id, diag.code) for diag in non_sea.diagnostics] == [
        (1, "non_sea")
    ]


def test_inputs_are_not_mutated():
    province, tile = _clean_coastal_map()
    height = np.full(province.shape, 9.0, dtype=np.float64)
    province_copy = province.copy()
    tile_copy = tile.copy()
    height_copy = height.copy()
    mapping = {1: 2}
    generate_port_proposals(province, tile, mapping, height_map=height, province_ids=[1])
    assert np.array_equal(province, province_copy)
    assert np.array_equal(tile, tile_copy)
    assert np.array_equal(height, height_copy)
    assert mapping == {1: 2}
