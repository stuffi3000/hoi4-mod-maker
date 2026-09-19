"""Pure placement transform contract for the M5.3 editing slice.

This module isolates the smallest editable unit shared by placement
records such as province slots, buildings, ports, and weather
positions. A transform carries only finite float values for horizontal
position, rotation, and height. Helpers read a transform from
duck-typed mapping or object records and derive updated transforms
without mutating their inputs, so controllers and managers can layer
selection, dragging, rotation, and undo on a deterministic foundation.

Neutral reset preserves the current horizontal position and resets
rotation and height to zero. MapPlacementManager keeps no persisted
original-position baseline, so reset means neutral orientation and
height at the current coordinates rather than restoring an earlier
authored or generated snapshot.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any

__all__ = [
    "PlacementTransform",
    "read_placement_transform",
    "reset_placement_transform",
    "update_placement_transform",
]

_UNSET: Any = object()
_MISSING: Any = object()
_FIELDS: tuple[str, ...] = ("x", "y", "rotation", "height")


def _coerce_coordinate(value: Any, field_name: str) -> float:
    """Validate one coordinate and return it as a finite float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number, got {value!r}")
    converted = float(value)
    if not isfinite(converted):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    return converted


def _raw_field(record: Any, field_name: str) -> Any:
    """Extract one raw coordinate from a mapping or object record."""
    if isinstance(record, Mapping):
        if field_name not in record:
            raise ValueError(f"placement record is missing {field_name!r}")
        return record[field_name]
    candidate = getattr(record, field_name, _MISSING)
    if candidate is _MISSING:
        raise ValueError(f"placement record is missing {field_name!r}")
    return candidate


@dataclass(frozen=True)
class PlacementTransform:
    """Immutable horizontal position plus rotation and height."""

    x: float
    y: float
    rotation: float
    height: float

    def __post_init__(self) -> None:
        """Coerce each field to a validated finite float."""
        object.__setattr__(self, "x", _coerce_coordinate(self.x, "x"))
        object.__setattr__(self, "y", _coerce_coordinate(self.y, "y"))
        object.__setattr__(self, "rotation", _coerce_coordinate(self.rotation, "rotation"))
        object.__setattr__(self, "height", _coerce_coordinate(self.height, "height"))


def read_placement_transform(record: Any) -> PlacementTransform:
    """Read a transform from a duck-typed mapping or object record.

    The record must expose finite numeric x, y, rotation, and height
    values either as mapping keys or as attributes. Bool values,
    non-numeric values, non-finite values, and missing fields raise
    ValueError. The input record is never mutated and the returned
    value is a new frozen PlacementTransform.
    """
    if isinstance(record, PlacementTransform):
        return PlacementTransform(
            x=record.x,
            y=record.y,
            rotation=record.rotation,
            height=record.height,
        )
    if record is None:
        raise ValueError("placement record must expose x, y, rotation, and height")
    if isinstance(record, (str, bytes, bytearray)):
        raise ValueError("placement record must expose x, y, rotation, and height")
    extracted = {field_name: _raw_field(record, field_name) for field_name in _FIELDS}
    return PlacementTransform(
        x=_coerce_coordinate(extracted["x"], "x"),
        y=_coerce_coordinate(extracted["y"], "y"),
        rotation=_coerce_coordinate(extracted["rotation"], "rotation"),
        height=_coerce_coordinate(extracted["height"], "height"),
    )


def _base_transform(source: Any) -> PlacementTransform:
    """Normalize a transform or duck-typed record to a transform."""
    if isinstance(source, PlacementTransform):
        return source
    return read_placement_transform(source)


def update_placement_transform(
    source: Any,
    *,
    x: Any = _UNSET,
    y: Any = _UNSET,
    rotation: Any = _UNSET,
    height: Any = _UNSET,
) -> PlacementTransform:
    """Derive an updated transform without mutating the input.

    The source may be a PlacementTransform or a duck-typed mapping or
    object record. Each keyword override is optional. Omitted fields
    keep the source value while supplied fields must be finite numeric
    values. Bool values, non-numeric values, and non-finite values
    raise ValueError. Fractional values are preserved as floats.
    """
    base = _base_transform(source)
    next_x = base.x if x is _UNSET else _coerce_coordinate(x, "x")
    next_y = base.y if y is _UNSET else _coerce_coordinate(y, "y")
    next_rotation = base.rotation if rotation is _UNSET else _coerce_coordinate(rotation, "rotation")
    next_height = base.height if height is _UNSET else _coerce_coordinate(height, "height")
    return PlacementTransform(
        x=next_x,
        y=next_y,
        rotation=next_rotation,
        height=next_height,
    )


def reset_placement_transform(source: Any) -> PlacementTransform:
    """Reset orientation and height while preserving position.

    This is a neutral reset. The current x and y values are preserved
    and rotation and height are set to 0.0. There is no persisted
    original-position baseline in MapPlacementManager, so this helper
    does not restore an earlier snapshot. The input is never mutated
    and the result is a new frozen PlacementTransform.
    """
    base = _base_transform(source)
    return PlacementTransform(
        x=base.x,
        y=base.y,
        rotation=0.0,
        height=0.0,
    )
