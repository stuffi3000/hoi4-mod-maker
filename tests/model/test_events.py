"""EventBus unit tests."""
import pytest

from model.events import EventBus, Event


class TestEventBus:
    """EventBus basic functionality."""

    def test_subscribe_and_emit(self) -> None:
        """After subscribing, emit can receive events."""
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("test", received.append)
        bus.emit("test", value=42)
        assert len(received) == 1
        assert received[0].type == "test"
        assert received[0].value == 42

    def test_multiple_subscribers(self) -> None:
        """Multiple subscribers can receive the same event."""
        bus = EventBus()
        results_a: list[Event] = []
        results_b: list[Event] = []
        bus.subscribe("ping", results_a.append)
        bus.subscribe("ping", results_b.append)
        bus.emit("ping", msg="hello")
        assert len(results_a) == 1
        assert len(results_b) == 1

    def test_unsubscribe(self) -> None:
        """You will no longer receive events after unsubscribing."""
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("test", received.append)
        bus.unsubscribe("test", received.append)
        bus.emit("test", value=1)
        assert len(received) == 0

    def test_unsubscribe_all(self) -> None:
        """unsubscribe_all clears subscriptions for all event types."""
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("a", received.append)
        bus.subscribe("b", received.append)
        bus.unsubscribe_all(received.append)
        bus.emit("a")
        bus.emit("b")
        assert len(received) == 0

    def test_emit_no_subscribers(self) -> None:
        """emit does not crash when there are no subscribers."""
        bus = EventBus()
        bus.emit("nonexistent", x=1)  # No exception should be thrown

    def test_duplicate_subscribe_ignored(self) -> None:
        """Repeated subscriptions to the same callback are only registered once."""
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("test", received.append)
        bus.subscribe("test", received.append)
        bus.emit("test")
        assert len(received) == 1

    def test_clear(self) -> None:
        """clear clears all subscriptions."""
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("test", received.append)
        bus.clear()
        bus.emit("test")
        assert len(received) == 0


class TestEvent:
    """Event data access."""

    def test_attribute_access(self) -> None:
        """Access the values of the data dictionary through properties."""
        event = Event("test", {"name": "hello", "count": 3})
        assert event.name == "hello"
        assert event.count == 3

    def test_missing_attribute_raises(self) -> None:
        """Accessing a non-existent attribute throws AttributeError."""
        event = Event("test", {})
        with pytest.raises(AttributeError, match="has no attribute 'missing'"):
            _ = event.missing

    def test_type_field(self) -> None:
        """The type field is accessed normally."""
        event = Event("my_event", {})
        assert event.type == "my_event"
