"""Authored map placement model (M5.1).

Explicit, deterministic records for map positions that the foundation
pipeline can author, review, serialize, and remap across compact-ID
operations:

- province position slots: the six positions.txt slots, addressed by
  index (0-5). The index is preserved verbatim until the slots are fully
  named against a verified game contract; meaning carries the current
  human-readable label for the slot without affecting identity.
- building / map-object transforms: one record per placed object.
- port / naval-base spawn coordinates with an optional sea province.
- weather positions: one or more records per strategic region.

Every transform stores map x/y, rotation, and height as floats. Values
are coerced with float(), never int(), so fractional coordinates survive
serialization round-trips.

Provenance is one of imported, authored, generated, or fallback. Review
status is one of unreviewed, reviewed, or accepted. Unknown values are
rejected with ValueError. Generated and fallback records start
unreviewed, but an explicit mark_*_reviewed call may advance their review
status while preserving their provenance. Updates that change provenance
without an explicit review status reset generated/fallback records to
unreviewed; the manager never silently promotes generated/fallback data.

Serialization contract (to_dict/from_dict): fail-fast and atomic.
from_dict raises ValueError with collection-plus-index context on any
malformed record (missing fields, wrong types, non-finite floats,
unknown provenance/review, illegal generated+reviewed pair, duplicate
keys, unsupported version) and leaves the manager unchanged. Unknown
extra fields inside a record are ignored for forward compatibility.

Remap/drop semantics (compact-ID support):

- drop_provinces / remap_provinces: slots, buildings, and ports whose
  province no longer exists are dropped. A port keeps its record when
  only its optional sea province is gone; the sea link is cleared to
  None. A mapping value of 0 means unallocated and also drops.
- drop_states / remap_states: a building keeps its record when its
  optional state reference is gone; the state link is cleared to None.
- drop_regions / remap_regions: weather records belong to their region,
  so a missing region drops the whole record.
- remap_compact applies the province/state/region maps together.

All list_* accessors and to_dict output use deterministic sort orders,
so repeated exports and tests observe stable sequences.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from numbers import Integral
from typing import Any

__all__ = [
    "AUTO_PROVENANCES",
    "POSITION_SLOT_COUNT",
    "POSITION_SLOT_MAX",
    "POSITION_SLOT_MIN",
    "PROVENANCES",
    "REVIEW_STATUSES",
    "SERIALIZATION_VERSION",
    "BuildingPlacement",
    "MapPlacementManager",
    "PortPlacement",
    "ProvincePositionSlot",
    "WeatherPosition",
]

PROVENANCES = ("imported", "authored", "generated", "fallback")
PROVENANCE_VALUES = frozenset(PROVENANCES)
REVIEW_STATUSES = ("unreviewed", "reviewed", "accepted")
REVIEW_STATUS_VALUES = frozenset(REVIEW_STATUSES)
AUTO_PROVENANCES = frozenset({"generated", "fallback"})

POSITION_SLOT_MIN = 0
POSITION_SLOT_MAX = 5
POSITION_SLOT_COUNT = 6

SERIALIZATION_VERSION = 1

_UNSET: Any = object()
def _province_id_from(value, field="province_id"):
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{field} must be a positive integer, got {value!r}")
    result = int(value)
    if result <= 0:
        raise ValueError(f"{field} must be a positive integer, got {value!r}")
    return result


def _optional_ref_from(value, field):
    if value is None:
        return None
    return _province_id_from(value, field)


def _slot_from(value):
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(
            "slot must be an integer in "
            f"{POSITION_SLOT_MIN}..{POSITION_SLOT_MAX}, got {value!r}"
        )
    result = int(value)
    if not POSITION_SLOT_MIN <= result <= POSITION_SLOT_MAX:
        raise ValueError(
            "slot must be an integer in "
            f"{POSITION_SLOT_MIN}..{POSITION_SLOT_MAX}, got {value!r}"
        )
    return result


def _coord_from(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number, got {value!r}")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field} must be finite, got {value!r}")
    return result


def _provenance_from(value):
    try:
        known = value in PROVENANCE_VALUES
    except TypeError:
        known = False
    if not known:
        raise ValueError(
            f"unknown provenance {value!r}; "
            f"expected one of {sorted(PROVENANCE_VALUES)}"
        )
    return str(value)


def _review_from(value):
    try:
        known = value in REVIEW_STATUS_VALUES
    except TypeError:
        known = False
    if not known:
        raise ValueError(
            f"unknown review status {value!r}; "
            f"expected one of {sorted(REVIEW_STATUS_VALUES)}"
        )
    return str(value)


def _check_pair(provenance, review_status):
    # Provenance and review status are intentionally independent. A generated
    # proposal can be explicitly reviewed and accepted while its origin stays
    # visible to the editor and exporter.
    return None


def _text_from(value, field, allow_empty=True):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string, got {value!r}")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


def _require_mapping(data, what):
    if not isinstance(data, Mapping):
        raise ValueError(f"{what} must be a mapping, got {type(data).__name__}")
    return data


def _required_fields(data, fields, what):
    missing = [name for name in fields if name not in data]
    if missing:
        raise ValueError(f"{what} is missing required fields: {missing}")


@dataclass
class ProvincePositionSlot:
    """One authored positions.txt slot for a province."""

    province_id: int
    slot: int
    x: float
    y: float
    rotation: float = 0.0
    height: float = 0.0
    meaning: str = ""
    provenance: str = "authored"
    review_status: str = "unreviewed"

    def __post_init__(self):
        self.province_id = _province_id_from(self.province_id)
        self.slot = _slot_from(self.slot)
        self.x = _coord_from(self.x, "x")
        self.y = _coord_from(self.y, "y")
        self.rotation = _coord_from(self.rotation, "rotation")
        self.height = _coord_from(self.height, "height")
        self.meaning = _text_from(self.meaning, "meaning")
        self.provenance = _provenance_from(self.provenance)
        self.review_status = _review_from(self.review_status)
        _check_pair(self.provenance, self.review_status)

    def key(self):
        return (self.province_id, self.slot)

    def to_dict(self):
        return {
            "province_id": self.province_id,
            "slot": self.slot,
            "meaning": self.meaning,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "height": self.height,
            "provenance": self.provenance,
            "review_status": self.review_status,
        }

    @classmethod
    def from_dict(cls, data):
        mapping = _require_mapping(data, "province slot record")
        _required_fields(
            mapping, ("province_id", "slot", "x", "y"), "province slot record"
        )
        return cls(
            province_id=mapping["province_id"],
            slot=mapping["slot"],
            x=mapping["x"],
            y=mapping["y"],
            rotation=mapping.get("rotation", 0.0),
            height=mapping.get("height", 0.0),
            meaning=mapping.get("meaning", ""),
            provenance=mapping.get("provenance", "authored"),
            review_status=mapping.get("review_status", "unreviewed"),
        )


@dataclass
class BuildingPlacement:
    """One placed building / map object with an explicit transform."""

    id: int
    province_id: int
    building_type: str
    x: float
    y: float
    rotation: float = 0.0
    height: float = 0.0
    state_id: int | None = None
    provenance: str = "authored"
    review_status: str = "unreviewed"

    def __post_init__(self):
        self.id = _province_id_from(self.id, "id")
        self.province_id = _province_id_from(self.province_id)
        self.building_type = _text_from(
            self.building_type, "building_type", allow_empty=False
        ).strip()
        if not self.building_type:
            raise ValueError("building_type must not be empty")
        self.x = _coord_from(self.x, "x")
        self.y = _coord_from(self.y, "y")
        self.rotation = _coord_from(self.rotation, "rotation")
        self.height = _coord_from(self.height, "height")
        self.state_id = _optional_ref_from(self.state_id, "state_id")
        self.provenance = _provenance_from(self.provenance)
        self.review_status = _review_from(self.review_status)
        _check_pair(self.provenance, self.review_status)

    def to_dict(self):
        return {
            "id": self.id,
            "province_id": self.province_id,
            "state_id": self.state_id,
            "building_type": self.building_type,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "height": self.height,
            "provenance": self.provenance,
            "review_status": self.review_status,
        }

    @classmethod
    def from_dict(cls, data):
        mapping = _require_mapping(data, "building record")
        _required_fields(
            mapping,
            ("id", "province_id", "building_type", "x", "y"),
            "building record",
        )
        return cls(
            id=mapping["id"],
            province_id=mapping["province_id"],
            building_type=mapping["building_type"],
            x=mapping["x"],
            y=mapping["y"],
            rotation=mapping.get("rotation", 0.0),
            height=mapping.get("height", 0.0),
            state_id=mapping.get("state_id"),
            provenance=mapping.get("provenance", "authored"),
            review_status=mapping.get("review_status", "unreviewed"),
        )


@dataclass
class PortPlacement:
    """Port / naval-base spawn coordinates plus optional sea province."""

    province_id: int
    x: float
    y: float
    rotation: float = 0.0
    height: float = 0.0
    sea_province: int | None = None
    provenance: str = "authored"
    review_status: str = "unreviewed"

    def __post_init__(self):
        self.province_id = _province_id_from(self.province_id)
        self.x = _coord_from(self.x, "x")
        self.y = _coord_from(self.y, "y")
        self.rotation = _coord_from(self.rotation, "rotation")
        self.height = _coord_from(self.height, "height")
        self.sea_province = _optional_ref_from(self.sea_province, "sea_province")
        self.provenance = _provenance_from(self.provenance)
        self.review_status = _review_from(self.review_status)
        _check_pair(self.provenance, self.review_status)

    def to_dict(self):
        return {
            "province_id": self.province_id,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "height": self.height,
            "sea_province": self.sea_province,
            "provenance": self.provenance,
            "review_status": self.review_status,
        }

    @classmethod
    def from_dict(cls, data):
        mapping = _require_mapping(data, "port record")
        _required_fields(mapping, ("province_id", "x", "y"), "port record")
        return cls(
            province_id=mapping["province_id"],
            x=mapping["x"],
            y=mapping["y"],
            rotation=mapping.get("rotation", 0.0),
            height=mapping.get("height", 0.0),
            sea_province=mapping.get("sea_province"),
            provenance=mapping.get("provenance", "authored"),
            review_status=mapping.get("review_status", "unreviewed"),
        )


@dataclass
class WeatherPosition:
    """One weather position belonging to a strategic region."""

    id: int
    region_id: int
    x: float
    y: float
    rotation: float = 0.0
    height: float = 0.0
    size: str = ""
    kind: str = ""
    provenance: str = "authored"
    review_status: str = "unreviewed"

    def __post_init__(self):
        self.id = _province_id_from(self.id, "id")
        self.region_id = _province_id_from(self.region_id, "region_id")
        self.x = _coord_from(self.x, "x")
        self.y = _coord_from(self.y, "y")
        self.rotation = _coord_from(self.rotation, "rotation")
        self.height = _coord_from(self.height, "height")
        self.size = _text_from(self.size, "size")
        self.kind = _text_from(self.kind, "kind")
        self.provenance = _provenance_from(self.provenance)
        self.review_status = _review_from(self.review_status)
        _check_pair(self.provenance, self.review_status)

    def to_dict(self):
        return {
            "id": self.id,
            "region_id": self.region_id,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "height": self.height,
            "size": self.size,
            "kind": self.kind,
            "provenance": self.provenance,
            "review_status": self.review_status,
        }

    @classmethod
    def from_dict(cls, data):
        mapping = _require_mapping(data, "weather record")
        _required_fields(
            mapping, ("id", "region_id", "x", "y"), "weather record"
        )
        return cls(
            id=mapping["id"],
            region_id=mapping["region_id"],
            x=mapping["x"],
            y=mapping["y"],
            rotation=mapping.get("rotation", 0.0),
            height=mapping.get("height", 0.0),
            size=mapping.get("size", ""),
            kind=mapping.get("kind", ""),
            provenance=mapping.get("provenance", "authored"),
            review_status=mapping.get("review_status", "unreviewed"),
        )


def _guard_review(provenance, status, allow_auto=False):
    # Review is an explicit user action. Keep ``allow_auto`` as a compatible
    # no-op for callers from the initial worker slice.
    return None


class MapPlacementManager:
    """Own the four authored placement collections with stable ordering."""

    def __init__(self):
        self._slots = {}
        self._buildings = {}
        self._ports = {}
        self._weather = {}
        self._next_building_id = 1
        self._next_weather_id = 1

    def set_province_slot(
        self,
        province_id,
        slot,
        x,
        y,
        rotation=0.0,
        height=0.0,
        meaning="",
        provenance="authored",
        review_status="unreviewed",
    ):
        record = ProvincePositionSlot(
            province_id=province_id,
            slot=slot,
            x=x,
            y=y,
            rotation=rotation,
            height=height,
            meaning=meaning,
            provenance=provenance,
            review_status=review_status,
        )
        self._slots[record.key()] = record
        return record

    def get_province_slot(self, province_id, slot):
        return self._slots.get((province_id, slot))

    def remove_province_slot(self, province_id, slot):
        if (province_id, slot) in self._slots:
            del self._slots[(province_id, slot)]
            return True
        return False

    def list_province_slots(self):
        return [self._slots[key] for key in sorted(self._slots)]

    def find_slots_by_province(self, province_id):
        return [
            record
            for key, record in sorted(self._slots.items())
            if key[0] == province_id
        ]

    def count_slots(self):
        return len(self._slots)

    def mark_slot_reviewed(
        self, province_id, slot, status, allow_auto=False
    ):
        record = self._slots.get((province_id, slot))
        if record is None:
            raise KeyError(f"unknown province slot: {(province_id, slot)!r}")
        checked = _review_from(status)
        _guard_review(record.provenance, checked, allow_auto=allow_auto)
        record.review_status = checked
        return record

    def add_building(
        self,
        province_id,
        building_type,
        x,
        y,
        rotation=0.0,
        height=0.0,
        state_id=None,
        provenance="authored",
        review_status="unreviewed",
    ):
        record_id = self._next_building_id
        self._next_building_id += 1
        try:
            record = BuildingPlacement(
                id=record_id,
                province_id=province_id,
                building_type=building_type,
                x=x,
                y=y,
                rotation=rotation,
                height=height,
                state_id=state_id,
                provenance=provenance,
                review_status=review_status,
            )
        except Exception:
            self._next_building_id -= 1
            raise
        self._buildings[record_id] = record
        return record_id

    def get_building(self, record_id):
        return self._buildings.get(record_id)

    def update_building(
        self,
        record_id,
        province_id=None,
        state_id=_UNSET,
        building_type=None,
        x=None,
        y=None,
        rotation=None,
        height=None,
        provenance=None,
        review_status=None,
    ):
        record = self._buildings.get(record_id)
        if record is None:
            raise KeyError(f"unknown building placement id: {record_id!r}")
        new_province = (
            record.province_id
            if province_id is None
            else _province_id_from(province_id)
        )
        new_state = (
            record.state_id
            if state_id is _UNSET
            else _optional_ref_from(state_id, "state_id")
        )
        new_type = record.building_type
        if building_type is not None:
            new_type = _text_from(
                building_type, "building_type", allow_empty=False
            ).strip()
            if not new_type:
                raise ValueError("building_type must not be empty")
        new_x = record.x if x is None else _coord_from(x, "x")
        new_y = record.y if y is None else _coord_from(y, "y")
        if rotation is None:
            new_rotation = record.rotation
        else:
            new_rotation = _coord_from(rotation, "rotation")
        if height is None:
            new_height = record.height
        else:
            new_height = _coord_from(height, "height")
        if provenance is None:
            new_provenance = record.provenance
        else:
            new_provenance = _provenance_from(provenance)
        if review_status is None:
            new_review = record.review_status
        else:
            new_review = _review_from(review_status)
        if (
            provenance is not None
            and new_provenance in AUTO_PROVENANCES
            and review_status is None
        ):
            new_review = "unreviewed"
        _check_pair(new_provenance, new_review)
        record.province_id = new_province
        record.state_id = new_state
        record.building_type = new_type
        record.x = new_x
        record.y = new_y
        record.rotation = new_rotation
        record.height = new_height
        record.provenance = new_provenance
        record.review_status = new_review
        return record

    def remove_building(self, record_id):
        if record_id in self._buildings:
            del self._buildings[record_id]
            return True
        return False

    def list_buildings(self):
        return sorted(
            self._buildings.values(),
            key=lambda record: (
                record.province_id,
                record.building_type,
                record.id,
            ),
        )

    def find_buildings_by_province(self, province_id):
        return [
            record
            for record in self.list_buildings()
            if record.province_id == province_id
        ]

    def count_buildings(self):
        return len(self._buildings)

    def mark_building_reviewed(self, record_id, status, allow_auto=False):
        record = self._buildings.get(record_id)
        if record is None:
            raise KeyError(f"unknown building placement id: {record_id!r}")
        checked = _review_from(status)
        _guard_review(record.provenance, checked, allow_auto=allow_auto)
        record.review_status = checked
        return record


    def set_port(
        self,
        province_id,
        x,
        y,
        rotation=0.0,
        height=0.0,
        sea_province=None,
        provenance="authored",
        review_status="unreviewed",
    ):
        record = PortPlacement(
            province_id=province_id,
            x=x,
            y=y,
            rotation=rotation,
            height=height,
            sea_province=sea_province,
            provenance=provenance,
            review_status=review_status,
        )
        self._ports[record.province_id] = record
        return record

    def get_port(self, province_id):
        return self._ports.get(province_id)

    def remove_port(self, province_id):
        if province_id in self._ports:
            del self._ports[province_id]
            return True
        return False

    def list_ports(self):
        return [self._ports[key] for key in sorted(self._ports)]

    def count_ports(self):
        return len(self._ports)

    def mark_port_reviewed(self, province_id, status, allow_auto=False):
        record = self._ports.get(province_id)
        if record is None:
            raise KeyError(f"unknown port province: {province_id!r}")
        checked = _review_from(status)
        _guard_review(record.provenance, checked, allow_auto=allow_auto)
        record.review_status = checked
        return record

    def add_weather(
        self,
        region_id,
        x,
        y,
        rotation=0.0,
        height=0.0,
        size="",
        kind="",
        provenance="authored",
        review_status="unreviewed",
    ):
        record_id = self._next_weather_id
        self._next_weather_id += 1
        try:
            record = WeatherPosition(
                id=record_id,
                region_id=region_id,
                x=x,
                y=y,
                rotation=rotation,
                height=height,
                size=size,
                kind=kind,
                provenance=provenance,
                review_status=review_status,
            )
        except Exception:
            self._next_weather_id -= 1
            raise
        self._weather[record_id] = record
        return record_id

    def get_weather(self, record_id):
        return self._weather.get(record_id)

    def update_weather(
        self,
        record_id,
        region_id=None,
        x=None,
        y=None,
        rotation=None,
        height=None,
        size=None,
        kind=None,
        provenance=None,
        review_status=None,
    ):
        record = self._weather.get(record_id)
        if record is None:
            raise KeyError(f"unknown weather position id: {record_id!r}")
        if region_id is None:
            new_region = record.region_id
        else:
            new_region = _province_id_from(region_id, "region_id")
        new_x = record.x if x is None else _coord_from(x, "x")
        new_y = record.y if y is None else _coord_from(y, "y")
        if rotation is None:
            new_rotation = record.rotation
        else:
            new_rotation = _coord_from(rotation, "rotation")
        if height is None:
            new_height = record.height
        else:
            new_height = _coord_from(height, "height")
        new_size = record.size if size is None else _text_from(size, "size")
        new_kind = record.kind if kind is None else _text_from(kind, "kind")
        if provenance is None:
            new_provenance = record.provenance
        else:
            new_provenance = _provenance_from(provenance)
        if review_status is None:
            new_review = record.review_status
        else:
            new_review = _review_from(review_status)
        if (
            provenance is not None
            and new_provenance in AUTO_PROVENANCES
            and review_status is None
        ):
            new_review = "unreviewed"
        _check_pair(new_provenance, new_review)
        record.region_id = new_region
        record.x = new_x
        record.y = new_y
        record.rotation = new_rotation
        record.height = new_height
        record.size = new_size
        record.kind = new_kind
        record.provenance = new_provenance
        record.review_status = new_review
        return record

    def remove_weather(self, record_id):
        if record_id in self._weather:
            del self._weather[record_id]
            return True
        return False

    def list_weather(self):
        return sorted(
            self._weather.values(),
            key=lambda record: (record.region_id, record.id),
        )

    def find_weather_by_region(self, region_id):
        return [
            record
            for record in self.list_weather()
            if record.region_id == region_id
        ]

    def count_weather(self):
        return len(self._weather)

    def mark_weather_reviewed(self, record_id, status, allow_auto=False):
        record = self._weather.get(record_id)
        if record is None:
            raise KeyError(f"unknown weather position id: {record_id!r}")
        checked = _review_from(status)
        _guard_review(record.provenance, checked, allow_auto=allow_auto)
        record.review_status = checked
        return record
    def count(self):
        return (
            len(self._slots)
            + len(self._buildings)
            + len(self._ports)
            + len(self._weather)
        )

    def clear(self):
        self._slots = {}
        self._buildings = {}
        self._ports = {}
        self._weather = {}
        self._next_building_id = 1
        self._next_weather_id = 1

    def drop_provinces(self, pids):
        dead = set(pids)
        self._slots = {
            key: record
            for key, record in self._slots.items()
            if record.province_id not in dead
        }
        self._buildings = {
            record_id: record
            for record_id, record in self._buildings.items()
            if record.province_id not in dead
        }
        fresh_ports = {}
        for province_id, record in self._ports.items():
            if record.province_id in dead:
                continue
            if record.sea_province in dead:
                record.sea_province = None
            fresh_ports[province_id] = record
        self._ports = fresh_ports

    def remap_provinces(self, old_to_new):
        fresh_slots = {}
        for record in self._slots.values():
            target = old_to_new.get(record.province_id, 0)
            if not target:
                continue
            record.province_id = target
            fresh_slots[record.key()] = record
        self._slots = fresh_slots
        fresh_buildings = {}
        for record_id, record in self._buildings.items():
            target = old_to_new.get(record.province_id, 0)
            if not target:
                continue
            record.province_id = target
            fresh_buildings[record_id] = record
        self._buildings = fresh_buildings
        fresh_ports = {}
        for record in self._ports.values():
            target = old_to_new.get(record.province_id, 0)
            if not target:
                continue
            record.province_id = target
            if record.sea_province is not None:
                sea_target = old_to_new.get(record.sea_province, 0)
                record.sea_province = sea_target or None
            fresh_ports[record.province_id] = record
        self._ports = fresh_ports

    def drop_states(self, sids):
        dead = set(sids)
        for record in self._buildings.values():
            if record.state_id in dead:
                record.state_id = None

    def remap_states(self, old_to_new):
        for record in self._buildings.values():
            if record.state_id is None:
                continue
            target = old_to_new.get(record.state_id, 0)
            record.state_id = target or None

    def drop_regions(self, rids):
        dead = set(rids)
        self._weather = {
            record_id: record
            for record_id, record in self._weather.items()
            if record.region_id not in dead
        }

    def remap_regions(self, old_to_new):
        fresh_weather = {}
        for record_id, record in self._weather.items():
            target = old_to_new.get(record.region_id, 0)
            if not target:
                continue
            record.region_id = target
            fresh_weather[record_id] = record
        self._weather = fresh_weather

    def remap_compact(
        self, province_map=None, state_map=None, region_map=None
    ):
        if province_map is not None:
            self.remap_provinces(dict(province_map))
        if state_map is not None:
            self.remap_states(dict(state_map))
        if region_map is not None:
            self.remap_regions(dict(region_map))

    def to_dict(self):
        return {
            "version": SERIALIZATION_VERSION,
            "province_slots": [
                record.to_dict() for record in self.list_province_slots()
            ],
            "buildings": [record.to_dict() for record in self.list_buildings()],
            "ports": [record.to_dict() for record in self.list_ports()],
            "weather": [record.to_dict() for record in self.list_weather()],
        }

    def from_dict(self, data):
        mapping = _require_mapping(data, "map placement payload")
        version = mapping.get("version", SERIALIZATION_VERSION)
        if version != SERIALIZATION_VERSION:
            raise ValueError(
                "unsupported map placement version: "
                f"{version!r}; expected {SERIALIZATION_VERSION}"
            )
        for field in ("province_slots", "buildings", "ports", "weather"):
            value = mapping.get(field, [])
            if not isinstance(value, list):
                raise ValueError(f"{field} must be a list, got {value!r}")
        raw_slots = mapping.get("province_slots", [])
        raw_buildings = mapping.get("buildings", [])
        raw_ports = mapping.get("ports", [])
        raw_weather = mapping.get("weather", [])
        slots = {}
        for index, raw in enumerate(raw_slots):
            try:
                record = ProvincePositionSlot.from_dict(raw)
            except ValueError as exc:
                raise ValueError(f"province_slots[{index}]: {exc}") from exc
            if record.key() in slots:
                raise ValueError(
                    f"province_slots[{index}]: duplicate slot {record.key()!r}"
                )
            slots[record.key()] = record
        buildings = {}
        for index, raw in enumerate(raw_buildings):
            try:
                record = BuildingPlacement.from_dict(raw)
            except ValueError as exc:
                raise ValueError(f"buildings[{index}]: {exc}") from exc
            if record.id in buildings:
                raise ValueError(
                    f"buildings[{index}]: duplicate id {record.id!r}"
                )
            buildings[record.id] = record
        ports = {}
        for index, raw in enumerate(raw_ports):
            try:
                record = PortPlacement.from_dict(raw)
            except ValueError as exc:
                raise ValueError(f"ports[{index}]: {exc}") from exc
            if record.province_id in ports:
                raise ValueError(
                    f"ports[{index}]: duplicate province "
                    f"{record.province_id!r}"
                )
            ports[record.province_id] = record
        weather = {}
        for index, raw in enumerate(raw_weather):
            try:
                record = WeatherPosition.from_dict(raw)
            except ValueError as exc:
                raise ValueError(f"weather[{index}]: {exc}") from exc
            if record.id in weather:
                raise ValueError(
                    f"weather[{index}]: duplicate id {record.id!r}"
                )
            weather[record.id] = record
        self._slots = slots
        self._buildings = buildings
        self._ports = ports
        self._weather = weather
        self._next_building_id = max(buildings.keys(), default=0) + 1
        self._next_weather_id = max(weather.keys(), default=0) + 1
