"""Phase 0 Acceptance Test - Skeleton + Base Class + Registry + CommandBus work properly.
These tests ensure that the core infrastructure is not damaged during the refactoring process."""

import pytest

from features.base import BaseFeature, FeatureContext
from app.registry import FeatureRegistry, ExporterRegistry
from commands.base import Command
from commands.bus import CommandBus


# ──────────────── Feature + Registry ────────────────

class _DummyMapFeature(BaseFeature):
    id = "map.dummy"
    display_name = "Test map feature"
    category = "map"


class _DummyContentFeature(BaseFeature):
    id = "content.dummy"
    display_name = "Test content feature"
    category = "content"


def test_feature_registry_register_and_get():
    reg = FeatureRegistry()
    f1 = _DummyMapFeature()
    reg.register(f1)
    assert reg.count() == 1
    assert reg.get("map.dummy") is f1
    assert reg.get("nonexistent") is None


def test_feature_registry_rejects_duplicate_id():
    reg = FeatureRegistry()
    reg.register(_DummyMapFeature())
    with pytest.raises(ValueError):
        reg.register(_DummyMapFeature())


def test_feature_registry_rejects_empty_id():
    reg = FeatureRegistry()

    class Bad(BaseFeature):
        id = ""

    with pytest.raises(ValueError):
        reg.register(Bad())


def test_feature_registry_by_category():
    reg = FeatureRegistry()
    reg.register(_DummyMapFeature())
    reg.register(_DummyContentFeature())
    maps = reg.by_category("map")
    contents = reg.by_category("content")
    assert len(maps) == 1 and maps[0].id == "map.dummy"
    assert len(contents) == 1 and contents[0].id == "content.dummy"


def test_base_feature_defaults_return_none_and_empty():
    f = _DummyMapFeature()
    ctx = FeatureContext()
    assert f.build_page(ctx) is None
    assert f.build_renderer(ctx) is None
    assert f.build_tools(ctx) == []


# ──────────────── ExporterRegistry ────────────────

def test_exporter_registry_orders_by_order_field():
    reg = ExporterRegistry()
    calls = []
    reg.register("second", "map", lambda: calls.append("second"), order=20)
    reg.register("first", "map", lambda: calls.append("first"), order=10)
    reg.register("third", "history", lambda: calls.append("third"), order=30)
    names = [name for name, group, w in reg.all()]
    assert names == ["first", "second", "third"]


def test_exporter_registry_by_group():
    reg = ExporterRegistry()
    reg.register("a", "map", lambda: None)
    reg.register("b", "history", lambda: None)
    reg.register("c", "map", lambda: None)
    map_writers = reg.by_group("map")
    assert len(map_writers) == 2
    assert {name for name, _ in map_writers} == {"a", "c"}


def test_exporter_registry_rejects_duplicate_name():
    reg = ExporterRegistry()
    reg.register("x", "map", lambda: None)
    with pytest.raises(ValueError):
        reg.register("x", "history", lambda: None)


# ──────────────── CommandBus ────────────────

class _IncrementCommand(Command):
    """Test command: Add 1 to the count of state dict."""

    def __init__(self, state: dict):
        self.state = state
        self.label = "increment"

    def execute(self) -> None:
        self.state["count"] = self.state.get("count", 0) + 1

    def undo(self) -> None:
        self.state["count"] = self.state.get("count", 0) - 1


def test_command_bus_execute_updates_state():
    state = {"count": 0}
    bus = CommandBus()
    bus.execute(_IncrementCommand(state))
    bus.execute(_IncrementCommand(state))
    assert state["count"] == 2
    assert bus.undo_depth() == 2


def test_command_bus_undo_redo():
    state = {"count": 0}
    bus = CommandBus()
    bus.execute(_IncrementCommand(state))
    bus.execute(_IncrementCommand(state))
    assert state["count"] == 2

    bus.undo()
    assert state["count"] == 1
    bus.undo()
    assert state["count"] == 0
    assert bus.undo_depth() == 0

    bus.redo()
    assert state["count"] == 1
    bus.redo()
    assert state["count"] == 2
    assert bus.redo_depth() == 0


def test_command_bus_new_execute_clears_redo_stack():
    state = {"count": 0}
    bus = CommandBus()
    bus.execute(_IncrementCommand(state))
    bus.undo()
    assert bus.can_redo()
    bus.execute(_IncrementCommand(state))
    assert not bus.can_redo()


def test_command_bus_listeners_called_on_change():
    state = {"count": 0}
    bus = CommandBus()
    calls = []
    bus.on_change(lambda: calls.append("changed"))
    bus.execute(_IncrementCommand(state))
    bus.undo()
    bus.redo()
    bus.clear()
    assert len(calls) == 4


def test_command_bus_respects_max_history():
    state = {"count": 0}
    bus = CommandBus(max_history=3)
    for _ in range(10):
        bus.execute(_IncrementCommand(state))
    assert bus.undo_depth() == 3  # Only keep the latest 3 items
    assert state["count"] == 10  # But the data changes have been implemented
