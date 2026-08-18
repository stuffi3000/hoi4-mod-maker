"""Manual province drawing tests."""
from __future__ import annotations

import numpy as np

from data.constants import TILE_LAND, TILE_SEA
from domain.map_data import MapData
from domain.tools.base import ToolContext
from domain.tools.province_paint import ProvincePaintTool


class _FakeUndo:
    pass


def _context(province_map: np.ndarray, tile_map: np.ndarray) -> ToolContext:
    md = MapData.__new__(MapData)
    md.province_map = province_map
    md.tile_map = tile_map
    md._centroid_cache = None
    return ToolContext(map_data=md, undo_mgr=_FakeUndo(), brush_size=1)


def _stroke(tool: ProvincePaintTool, ctx: ToolContext, points) -> None:
    x, y = points[0]
    tool.on_press(ctx, x, y)
    for x, y in points[1:]:
        tool.on_drag(ctx, x, y)
    tool.on_release(ctx, x, y)
    tool.run_cleanup(ctx)


def test_new_province_uses_gap_and_infers_tile_type():
    pm = np.ones((12, 12), dtype=np.int32)
    pm[:, 6:] = 3  # ID 2 is intentionally missing
    tm = np.full_like(pm, TILE_LAND, dtype=np.uint8)
    tm[:, 10:] = TILE_SEA
    ctx = _context(pm, tm)
    tool = ProvincePaintTool()

    pid = tool.begin_new_province(ctx)
    assert pid == 2
    tool.configure(ctx, mode="brush", brush_size=3)
    _stroke(tool, ctx, [(5, 5), (6, 5), (7, 5)])

    assert (pm == 2).any()
    assert np.all(tm[pm == 2] == TILE_LAND)
    assert not np.any(pm[:, 10:] == 2)


def test_brush_refines_generated_border_and_keeps_target_contiguous():
    pm = np.ones((14, 18), dtype=np.int32)
    pm[:, 9:] = 2
    tm = np.full(pm.shape, TILE_LAND, dtype=np.uint8)
    ctx = _context(pm, tm)
    tool = ProvincePaintTool()
    tool.configure(ctx, mode="brush", brush_size=5, pid=1, tile_type=TILE_LAND)

    before = int(np.sum(pm == 1))
    _stroke(tool, ctx, [(8, 7), (10, 7), (12, 7)])

    from domain.validators.province import detect_non_contiguous

    assert int(np.sum(pm == 1)) > before
    assert detect_non_contiguous(pm) == []


def test_distant_click_cannot_create_disconnected_copy():
    pm = np.full((12, 20), 2, dtype=np.int32)
    pm[:, :5] = 1
    tm = np.full(pm.shape, TILE_LAND, dtype=np.uint8)
    ctx = _context(pm, tm)
    tool = ProvincePaintTool()
    tool.configure(ctx, mode="brush", brush_size=3, pid=1, tile_type=TILE_LAND)
    original = pm.copy()

    _stroke(tool, ctx, [(17, 6)])

    assert np.array_equal(pm, original)


def test_brush_treats_horizontal_map_seam_as_adjacent():
    pm = np.full((8, 12), 2, dtype=np.int32)
    pm[:, -1] = 1
    tm = np.full(pm.shape, TILE_LAND, dtype=np.uint8)
    ctx = _context(pm, tm)
    tool = ProvincePaintTool()
    tool.configure(ctx, mode="brush", brush_size=1, pid=1, tile_type=TILE_LAND)

    _stroke(tool, ctx, [(0, 4)])
    assert pm[4, 0] == 1


def test_fill_assigns_only_blank_area_and_protects_existing_province():
    pm = np.zeros((10, 12), dtype=np.int32)
    pm[:, :3] = 1
    pm[:, 9:] = 2
    tm = np.full(pm.shape, TILE_LAND, dtype=np.uint8)
    ctx = _context(pm, tm)
    tool = ProvincePaintTool()
    tool.configure(ctx, mode="fill", brush_size=9, pid=1, tile_type=TILE_LAND)

    _stroke(tool, ctx, [(5, 5)])
    assert np.all(pm[:, 3:9] == 1)
    assert np.all(pm[:, 9:] == 2)

    after_blank_fill = pm.copy()
    _stroke(tool, ctx, [(10, 5)])
    assert np.array_equal(pm, after_blank_fill)


def test_fill_cannot_create_a_disconnected_province():
    pm = np.full((8, 14), 2, dtype=np.int32)
    pm[:, 1:3] = 1
    pm[:, 3:5] = 2
    pm[:, 5:13] = 0
    tm = np.full(pm.shape, TILE_LAND, dtype=np.uint8)
    ctx = _context(pm, tm)
    tool = ProvincePaintTool()
    tool.configure(ctx, mode="fill", pid=1, tile_type=TILE_LAND)
    original = pm.copy()

    _stroke(tool, ctx, [(10, 4)])
    assert np.array_equal(pm, original)


def test_manual_pixels_are_preserved_by_incremental_generation():
    pm = np.zeros((16, 24), dtype=np.int32)
    tm = np.full(pm.shape, TILE_LAND, dtype=np.uint8)
    ctx = _context(pm, tm)
    tool = ProvincePaintTool()
    new_pid = tool.begin_new_province(ctx)
    tool.configure(ctx, mode="brush", brush_size=5)
    _stroke(tool, ctx, [(4, 8), (6, 8)])
    manual_mask = pm == new_pid

    from domain.generators.province import generate_provinces_incremental

    generated, _ = generate_provinces_incremental(
        tm, pm, target_density=40.0, lloyd_iterations=0
    )
    assert np.all(generated[manual_mask] == new_pid)
    assert np.all(generated > 0)


def test_x_crossing_cleanup_never_moves_id_between_tile_types():
    pm = np.array([[1, 2], [3, 4]], dtype=np.int32)
    tm = np.array([[TILE_LAND, TILE_SEA], [TILE_LAND, TILE_SEA]], dtype=np.uint8)
    ctx = _context(pm, tm)
    ctx.dirty_bbox = (0, 0, 2, 2)
    tool = ProvincePaintTool()

    assert tool._fix_type_safe_x_crossings(ctx) == 1
    # The duplicated IDs must still occupy only one tile type each.
    for pid in np.unique(pm):
        assert len(np.unique(tm[pm == pid])) == 1


def test_incremental_x_crossing_cleanup_protects_manual_pixels():
    from domain.validators.province import fix_x_crossings_preserving

    pm = np.array([[1, 2], [3, 4]], dtype=np.int32)
    before = pm.copy()
    protected = np.array([[True, True], [True, False]])
    tm = np.full(pm.shape, TILE_LAND, dtype=np.uint8)

    assert fix_x_crossings_preserving(pm, protected, tm) == 1
    assert np.array_equal(pm[protected], before[protected])
