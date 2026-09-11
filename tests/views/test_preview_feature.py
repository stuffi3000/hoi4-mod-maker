"""Preview feature integration testing - renderer cache/downgrade/mode access.

Game files are not included in CI: fake assets are synthesized, and real asset-related behaviors are covered by test_game_assets."""

from types import SimpleNamespace

import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication

import services.game_assets as ga
from features.map.preview import renderer as preview_renderer


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def canvas(qapp):
    """Construct canvas after aligning global dimensions (same defense as test_render_registry)."""
    import views.canvas.widget as widget_mod
    import data.constants as constants
    from data.constants import set_map_size

    old_w, old_h = constants.MAP_WIDTH, constants.MAP_HEIGHT
    set_map_size(widget_mod.MAP_WIDTH, widget_mod.MAP_HEIGHT)
    try:
        yield widget_mod.MapCanvas()
    finally:
        set_map_size(old_w, old_h)


@pytest.fixture()
def fake_assets(monkeypatch):
    """Inject 16 tiles fake assets, and restore the default singleton when the test is over."""
    tiles = np.zeros((16, 4, 4, 4), dtype=np.uint8)
    tiles[:, :, :, 1] = 200          # All green tiles
    tiles[:, :, :, 3] = 255
    fake = SimpleNamespace(
        atlas_tiles=lambda: tiles,
        terrain_to_texture=lambda: {0: 1},
        available=lambda: True,
        install_dir="<fake>",
        last_error="",
    )
    monkeypatch.setattr(ga, "_default_assets", fake)
    yield fake


def test_preview_mode_is_valid_and_registered(canvas):
    """preview is a legal display mode and has a registered renderer."""
    from views.canvas.render_registry import DEFAULT_RENDERERS
    canvas.display_mode = "preview"
    assert canvas.display_mode == "preview"
    assert DEFAULT_RENDERERS["preview"] == "features.map.preview.renderer"


def test_render_composes_and_caches(canvas, fake_assets):
    """The composition is rendered and cached for the first time; the cache is used directly for subsequent renderings."""
    preview_renderer.render(canvas)
    cache1 = canvas._preview_cache
    assert cache1 is not None
    assert cache1.shape == (*canvas._tile_map.shape, 3)

    preview_renderer.render(canvas)
    assert canvas._preview_cache is cache1     # Same object = no resynthesis


def test_invalidate_cache_forces_recompose(canvas, fake_assets):
    """resynthesize after invalidate_cache (path to refresh button)."""
    preview_renderer.render(canvas)
    cache1 = canvas._preview_cache
    preview_renderer.invalidate_cache(canvas)
    preview_renderer.render(canvas)
    assert canvas._preview_cache is not cache1


def test_degrades_to_land_when_assets_unavailable(canvas, monkeypatch):
    """Game assets are unavailable: not crashing, downgraded land rendering, reason available for page display."""
    broken = SimpleNamespace(
        atlas_tiles=lambda: None,
        terrain_to_texture=lambda: None,
        available=lambda: False,
        install_dir=None,
        last_error="HOI4 installation directory was not found",
    )
    monkeypatch.setattr(ga, "_default_assets", broken)
    preview_renderer.invalidate_cache(canvas)

    preview_renderer.render(canvas)            # Don't throw exception

    assert canvas._preview_cache is None
    assert canvas._preview_error != ""


def test_preview_mode_enables_smooth_scaling(canvas):
    """Preview mode turns on smooth scaling (texture map), editing mode keeps nearest neighbors (pixel hard edges)."""
    from PyQt5.QtGui import QPainter
    canvas.display_mode = "preview"
    assert canvas.renderHints() & QPainter.RenderHint.SmoothPixmapTransform
    canvas.display_mode = "land"
    assert not (canvas.renderHints() & QPainter.RenderHint.SmoothPixmapTransform)


def test_renderer_has_no_partial_render():
    """The preview renderer intentionally does not provide partial_render (the canvas will rewind the full amount)."""
    assert not hasattr(preview_renderer, "partial_render")
