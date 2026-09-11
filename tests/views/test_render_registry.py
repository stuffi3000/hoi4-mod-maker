"""Canvas rendering dispatches registered tests.

Verification 2026-06 Architecture cleanup: display mode → renderer module is driven by the registry,
New modes (such as preview) are accessed through register_renderer, and widget.py will no longer be modified."""

from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QApplication

from views.canvas.render_registry import DEFAULT_RENDERERS


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def canvas(qapp):
    """Align the global dimensions to the constants bound to the widget module before constructing the canvas.

    The buffer of MapCanvas is bound to MAP_WIDTH/MAP_HEIGHT when importing,
    And MapData reads the global size at runtime - if the size has been changed by previous tests, it will be misaligned."""
    import views.canvas.widget as widget_mod
    import data.constants as constants
    from data.constants import set_map_size

    old_w, old_h = constants.MAP_WIDTH, constants.MAP_HEIGHT
    set_map_size(widget_mod.MAP_WIDTH, widget_mod.MAP_HEIGHT)
    try:
        yield widget_mod.MapCanvas()
    finally:
        set_map_size(old_w, old_h)


def test_default_registry_covers_all_valid_modes():
    """All legal display modes have registered renderers."""
    for mode in ("land", "terrain", "height", "province", "state", "country",
                 "river", "logistics", "continent", "strategic_region",
                 "colormap", "default_map", "province_terrain"):
        assert mode in DEFAULT_RENDERERS


# partial_render is an optional convention — full-image compositing renderers are explicitly exempt (canvas fallback to full amount)
_NO_PARTIAL_MODES = {"preview"}


def test_all_registered_renderer_modules_import():
    """Each module path in the registry can be truly imported and conform to the renderer convention."""
    import importlib
    for mode, path in DEFAULT_RENDERERS.items():
        mod = importlib.import_module(path)
        assert callable(mod.render), f"{mode}: {path} is missing render()"
        if mode in _NO_PARTIAL_MODES:
            assert not hasattr(mod, "partial_render"), \
                f"{mode} declares full composition and must not provide partial_render"
        else:
            assert callable(mod.partial_render), f"{mode}: {path} is missing partial_render()"


def test_resolve_renderer_imports_and_caches(canvas):
    """The land renderer can be parsed into real modules, and the secondary parsing is cached."""
    r1 = canvas._resolve_renderer("land")
    assert callable(r1.render)
    assert canvas._resolve_renderer("land") is r1


def test_registered_mode_dispatches_full_render(canvas):
    """Registered new patterns are dispatched by _full_render to (access path to preview patterns)."""
    calls = []
    fake = SimpleNamespace(render=lambda c: calls.append("full"))
    canvas._renderer_paths["fake_mode"] = "<test>"
    canvas._renderer_cache["fake_mode"] = fake
    canvas._display_mode = "fake_mode"

    canvas._full_render()

    assert calls == ["full"]


def test_partial_render_falls_back_to_full_when_unsupported(canvas):
    """The renderer does not have partial_render → partial rendering falls back to the full amount (whole image composition mode)."""
    calls = []
    fake = SimpleNamespace(render=lambda c: calls.append("full"))  # None partial_render
    canvas._renderer_paths["fake_mode"] = "<test>"
    canvas._renderer_cache["fake_mode"] = fake
    canvas._display_mode = "fake_mode"

    canvas._partial_render(0, 0, 4, 4)

    assert calls == ["full"]


def test_unknown_mode_falls_back_to_land(canvas):
    """Unregistered mode falls back to the land renderer without crashing."""
    canvas._display_mode = "no_such_mode"
    canvas._full_render()  # Pass without throwing exception


def test_register_renderer_overrides_and_invalidates_cache(canvas):
    """register_renderer overwrites the old registration and clears the cache."""
    canvas._renderer_cache["land"] = SimpleNamespace(render=lambda c: None)
    canvas.register_renderer("land", "features.map.land.renderer")
    assert "land" not in canvas._renderer_cache
    assert canvas._renderer_paths["land"] == "features.map.land.renderer"


def test_dead_merge_provinces_removed(canvas):
    """The dead code merge_provinces has been deleted (the current merge goes through MergeProvincesCommand)."""
    assert not hasattr(canvas, "merge_provinces")
