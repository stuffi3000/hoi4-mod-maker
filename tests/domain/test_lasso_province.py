"""LassoProvinceTool (province expansion) behavioral test.

Verification 2026-04-09 Correction:
- active must change to False after releasing the mouse
- Next time you click on the same province, you should go to Case 2 again (activate + draw the first stroke)
- A single stroke cannot span the current allowed_mask"""

import numpy as np
import pytest


def _make_ctx_with_map():
    """Construct a minimal MapData + ToolContext to drive LassoProvinceTool."""
    from domain.map_data import MapData
    from domain.tools.base import ToolContext
    from data.constants import TILE_LAND

    # 10x10 full land, 3 provinces: 1 on the left half, 2 on the right half, 3 in the corners
    pm = np.zeros((10, 10), dtype=np.int32)
    pm[:, :5] = 1
    pm[:, 5:] = 2
    pm[0:2, 0:2] = 3  # A small piece in the corner
    tm = np.full((10, 10), TILE_LAND, dtype=np.uint8)

    md = MapData.__new__(MapData)
    md.province_map = pm
    md.tile_map = tm

    class _FakeUndo:
        def push_snapshot(self, *a, **k): pass

    ctx = ToolContext(map_data=md, undo_mgr=_FakeUndo())
    return ctx


def test_release_deactivates_expand_mode():
    """active should be False after releasing the mouse to prevent further expansion to new neighbors."""
    from domain.tools.lasso_province import LassoProvinceTool
    tool = LassoProvinceTool()
    ctx = _make_ctx_with_map()

    # Click province 1 for the first time (position 5, 5 is province 2, we click 3, 3 should be province 1)
    tool.on_press(ctx, 3, 3)
    assert ctx.state.get("pid") == 1
    assert ctx.state.get("active") is False

    # Click the same province for the second time to enter the expansion
    tool.on_press(ctx, 3, 3)
    assert ctx.state.get("active") is True
    assert ctx.state.get("painting") is True

    # Drag a few times
    tool.on_drag(ctx, 4, 4)

    # Release → active must become False
    tool.on_release(ctx, 4, 4)
    assert ctx.state.get("painting") is False
    assert ctx.state.get("active") is False, (
        "active must be False after release; otherwise one drag can consume the whole landmass"
    )


def test_next_press_on_same_province_reactivates():
    """If you click on the same province again after releasing it, you should go to Case 2 to reactivate (instead of Case 3 to continue drawing)."""
    from domain.tools.lasso_province import LassoProvinceTool
    tool = LassoProvinceTool()
    ctx = _make_ctx_with_map()

    tool.on_press(ctx, 3, 3)   # Case 1: Selected
    tool.on_press(ctx, 3, 3)   # Case 2: Activation
    tool.on_release(ctx, 3, 3)
    assert not ctx.state.get("active")

    # The next click on the same province should activate again (Case 2), not continue (Case 3)
    tool.on_press(ctx, 3, 3)
    assert ctx.state.get("active") is True
    assert ctx.state.get("painting") is True
