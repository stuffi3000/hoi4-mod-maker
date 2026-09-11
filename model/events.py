"""Event bus - the core of decoupled communication between modules.

All cross-module communication is via EventBus publish/subscribe, no direct calls."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from collections import defaultdict


class EventBus:
    """Simple publish/subscribe event bus."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Subscribe to events. callback receives event data object."""
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Unsubscribe."""
        subs = self._subscribers[event_type]
        if callback in subs:
            subs.remove(callback)

    def unsubscribe_all(self, callback: Callable) -> None:
        """Cancel all subscriptions to a callback (for cleanup)."""
        for subs in self._subscribers.values():
            if callback in subs:
                subs.remove(callback)

    def emit(self, event_type: str, **data: Any) -> None:
        """Publish an event and all subscribers receive it in the order they registered."""
        event = Event(event_type, data)
        for callback in self._subscribers[event_type][:]:  # copy to allow modify during iteration
            callback(event)

    def clear(self) -> None:
        """Clear all subscriptions."""
        self._subscribers.clear()


@dataclass
class Event:
    """Event data carrier."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        if name in ("type", "data") or name.startswith("_"):
            raise AttributeError(name)
        try:
            return self.data[name]
        except KeyError:
            raise AttributeError(f"Event '{self.type}' has no attribute '{name}'")


# ──Event type constant──

# Layer changes
LAYER_CHANGED = "layer_changed"  # layer_name, bbox=(x0,y0,x1,y1) or None
PROVINCE_MAP_CHANGED = "province_map_changed"

# user interaction
PROVINCE_CLICKED = "province_clicked"  # pid, x, y
PROVINCE_RIGHT_CLICKED = "province_right_clicked"  # pid, x, y
PROVINCE_DOUBLE_CLICKED = "province_double_clicked"  # pid

# mode
MODE_CHANGED = "mode_changed"  # old_mode, new_mode

# Data changes
STATE_CHANGED = "state_changed"  # state_id, action ("created"/"deleted"/"modified")
COUNTRY_CHANGED = "country_changed"  # tag, action
VP_CHANGED = "vp_changed"  # pid, value

# Undo/Redo
UNDO_STATE_CHANGED = "undo_state_changed"  # can_undo, can_redo

# UI
STATUS_MESSAGE = "status_message"  # text
PROVINCE_COUNT_CHANGED = "province_count_changed"  # count
REQUEST_RENDER = "request_render"  # full=True/False, bbox=(x0,y0,x1,y1)
