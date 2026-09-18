"""Pure M4.5 logistics-exception model.

Intentional waivers for disconnected logistics components and supply nodes.

This module is stdlib/domain-only: it never touches Qt, game files, the
project model, exporters, or validators, and it never mutates the graph or
manager inputs it evaluates.

Identity model:

- A component exception is keyed by the stable component identity produced
  by ``domain.logistics_graph.component_id_for`` (twelve lowercase hex
  characters). Use :func:`component_key` to build the ``"component:<id>"``
  key.
- A supply exception is keyed by its supply province
  (``"supply:<province_id>"`` built with :func:`supply_key`) and stores the
  containing component identity at waiver time in ``component_id``.

Reason categories are exactly ``island``, ``overseas_convoy``,
``intentional_isolation``, and ``future_content``; anything else is rejected
instead of being silently accepted.

A component exception is valid only while its stored component identity is
present in the current graph. A supply exception is valid only while its
supply province still exists and the province's current containing
component matches the stored identity.
:meth:`LogisticsExceptionManager.evaluate` reports both sides
deterministically without mutating anything, while
:meth:`LogisticsExceptionManager.prune_stale` removes stale records in
sorted key order.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from numbers import Integral
from typing import Any

__all__ = [
    "COMPONENT_KIND",
    "REASON_FUTURE_CONTENT",
    "REASON_INTENTIONAL_ISOLATION",
    "REASON_ISLAND",
    "REASON_OVERSEAS_CONVOY",
    "REASONS",
    "SUPPLY_KIND",
    "VALID_REASONS",
    "ExceptionEvaluation",
    "ExceptionCoverage",
    "ExceptionStatus",
    "LogisticsException",
    "LogisticsExceptionManager",
    "component_identity_for",
    "component_key",
    "evaluate_exception",
    "evaluate_exceptions",
    "evaluate_exception_coverage",
    "relevant_exception_keys",
    "exception_kind",
    "is_component_key",
    "is_supply_key",
    "supply_key",
    "supply_province_for",
]

REASON_ISLAND = "island"
REASON_OVERSEAS_CONVOY = "overseas_convoy"
REASON_INTENTIONAL_ISOLATION = "intentional_isolation"
REASON_FUTURE_CONTENT = "future_content"

REASONS = (
    REASON_ISLAND,
    REASON_OVERSEAS_CONVOY,
    REASON_INTENTIONAL_ISOLATION,
    REASON_FUTURE_CONTENT,
)

VALID_REASONS = frozenset(REASONS)

COMPONENT_KIND = "component"
SUPPLY_KIND = "supply"

_COMPONENT_PREFIX = "component:"
_SUPPLY_PREFIX = "supply:"
_COMPONENT_ID_RE = re.compile(r"[0-9a-f]{12}")

_DETAIL_COMPONENT_PRESENT = "component-present"
_DETAIL_UNKNOWN_COMPONENT = "unknown-component"
_DETAIL_SUPPLY_PRESENT = "supply-present"
_DETAIL_UNKNOWN_SUPPLY = "unknown-supply"
_DETAIL_SUPPLY_WITHOUT_COMPONENT = "supply-without-component"
_DETAIL_SUPPLY_MOVED_COMPONENT = "supply-moved-component"

_KNOWN_RECORD_FIELDS = frozenset({"key", "reason", "note", "component_id"})


def _component_identity_from(value: Any) -> str:
    """Validate a stable twelve-character component identity."""
    if not isinstance(value, str):
        raise ValueError("component identity must be a string: %r" % (value,))
    if _COMPONENT_ID_RE.fullmatch(value) is None:
        raise ValueError("component identity must be twelve lowercase hex characters: %r" % (value,))
    return value


def _province_id_from(value: Any) -> int:
    """Validate a supply province id, accepting only canonical input."""
    if isinstance(value, bool):
        raise ValueError("province id must be a positive integer: %r" % (value,))
    if isinstance(value, Integral):
        province_id = int(value)
    elif isinstance(value, str):
        if not value.isascii() or not value.isdigit():
            raise ValueError("province id must be a positive integer: %r" % (value,))
        province_id = int(value, 10)
        if str(province_id) != value:
            raise ValueError("province id must use canonical digits: %r" % (value,))
    else:
        raise ValueError("province id must be a positive integer: %r" % (value,))
    if province_id <= 0:
        raise ValueError("province id must be a positive integer: %r" % (value,))
    return province_id


def component_key(component_id: str) -> str:
    """Build the stable key for a component exception."""
    return _COMPONENT_PREFIX + _component_identity_from(component_id)


def supply_key(province_id: int) -> str:
    """Build the stable key for a supply-node exception."""
    return _SUPPLY_PREFIX + str(_province_id_from(province_id))


def exception_kind(key: Any) -> str:
    """Return ``"component"`` or ``"supply"`` for a valid exception key."""
    if not isinstance(key, str):
        raise ValueError("exception key must be a string: %r" % (key,))
    if key.startswith(_COMPONENT_PREFIX):
        _component_identity_from(key[len(_COMPONENT_PREFIX):])
        return COMPONENT_KIND
    if key.startswith(_SUPPLY_PREFIX):
        _province_id_from(key[len(_SUPPLY_PREFIX):])
        return SUPPLY_KIND
    raise ValueError("unknown exception key prefix: %r" % (key,))


def is_component_key(key: Any) -> bool:
    """Return True only for well-formed component exception keys."""
    try:
        return exception_kind(key) == COMPONENT_KIND
    except ValueError:
        return False


def is_supply_key(key: Any) -> bool:
    """Return True only for well-formed supply exception keys."""
    try:
        return exception_kind(key) == SUPPLY_KIND
    except ValueError:
        return False


def component_identity_for(key: str) -> str:
    """Return the component identity embedded in a component key."""
    if exception_kind(key) != COMPONENT_KIND:
        raise ValueError("not a component exception key: %r" % (key,))
    return key[len(_COMPONENT_PREFIX):]


def supply_province_for(key: str) -> int:
    """Return the supply province embedded in a supply key."""
    if exception_kind(key) != SUPPLY_KIND:
        raise ValueError("not a supply exception key: %r" % (key,))
    return int(key[len(_SUPPLY_PREFIX):], 10)


@dataclass(frozen=True)
class LogisticsException:
    """One intentional logistics waiver.

    ``key`` is a component or supply key built with :func:`component_key`
    or :func:`supply_key`. ``reason`` must be one of :data:`REASONS`.
    ``note`` is free text preserved through serialization. ``component_id``
    is the stored graph identity: for component records it always equals
    the identity embedded in the key, while for supply records it is the
    containing component identity observed when the waiver was filed.
    """

    key: str
    reason: str
    note: str = ""
    component_id: str = ""

    def __post_init__(self) -> None:
        kind = exception_kind(self.key)
        if not isinstance(self.reason, str) or self.reason not in VALID_REASONS:
            raise ValueError("unknown logistics reason: %r" % (self.reason,))
        if not isinstance(self.note, str):
            raise ValueError("exception note must be a string: %r" % (self.note,))
        if not isinstance(self.component_id, str):
            raise ValueError("stored component identity must be a string: %r" % (self.component_id,))
        if kind == COMPONENT_KIND:
            expected = self.key[len(_COMPONENT_PREFIX):]
            if self.component_id == "":
                object.__setattr__(self, "component_id", expected)
            elif self.component_id != expected:
                raise ValueError(
                    "component record identity %r does not match key %r"
                    % (self.component_id, self.key)
                )
        elif _COMPONENT_ID_RE.fullmatch(self.component_id) is None:
            raise ValueError(
                "supply record requires the containing component identity: %r"
                % (self.component_id,)
            )

    @property
    def kind(self) -> str:
        """Return ``"component"`` or ``"supply"`` for this record."""
        return exception_kind(self.key)

    @property
    def is_component(self) -> bool:
        """Return True for component-keyed records."""
        return self.kind == COMPONENT_KIND

    @property
    def is_supply(self) -> bool:
        """Return True for supply-keyed records."""
        return self.kind == SUPPLY_KIND

    @property
    def supply_province(self) -> int | None:
        """Return the supply province, or None for component records."""
        if not self.is_supply:
            return None
        return int(self.key[len(_SUPPLY_PREFIX):], 10)

    @property
    def component_identity(self) -> str:
        """Return the stored graph identity for this record."""
        return self.component_id

    def to_dict(self) -> dict[str, str]:
        """Serialize this record to plain string-keyed data."""
        return {
            "key": self.key,
            "reason": self.reason,
            "note": self.note,
            "component_id": self.component_id,
        }

    @classmethod
    def from_dict(cls, data: Any) -> LogisticsException:
        """Rebuild a record, rejecting unknown reasons, keys, and fields."""
        if not isinstance(data, Mapping):
            raise ValueError("exception record must be a mapping: %r" % (data,))
        unknown = set(data.keys()) - _KNOWN_RECORD_FIELDS
        if unknown:
            raise ValueError(
                "unknown exception fields: %s"
                % (sorted(repr(field) for field in unknown),)
            )
        if "key" not in data or "reason" not in data:
            raise ValueError("exception record requires 'key' and 'reason': %r" % (data,))
        return cls(
            key=data["key"],
            reason=data["reason"],
            note=data.get("note", ""),
            component_id=data.get("component_id", ""),
        )


@dataclass(frozen=True)
class ExceptionStatus:
    """Validity of one exception record against one graph snapshot."""

    exception: LogisticsException
    valid: bool
    detail: str = ""


@dataclass(frozen=True)
class ExceptionEvaluation:
    """Deterministic per-record report for one graph snapshot."""

    statuses: tuple[ExceptionStatus, ...] = ()

    @property
    def valid(self) -> tuple[LogisticsException, ...]:
        """Records still matching the evaluated graph, in key order."""
        return tuple(status.exception for status in self.statuses if status.valid)

    @property
    def stale(self) -> tuple[LogisticsException, ...]:
        """Records no longer matching the evaluated graph, in key order."""
        return tuple(status.exception for status in self.statuses if not status.valid)

    @property
    def valid_keys(self) -> tuple[str, ...]:
        """Keys of the valid records, in key order."""
        return tuple(record.key for record in self.valid)

    @property
    def stale_keys(self) -> tuple[str, ...]:
        """Keys of the stale records, in key order."""
        return tuple(record.key for record in self.stale)

    @property
    def is_clean(self) -> bool:
        """Return True when every evaluated record is still valid."""
        return all(status.valid for status in self.statuses)

    def __len__(self) -> int:
        return len(self.statuses)


@dataclass(frozen=True)
class ExceptionCoverage:
    """Coverage of the graph cases that need an intentional exception."""

    relevant_keys: tuple[str, ...] = ()
    accepted_keys: tuple[str, ...] = ()
    missing_keys: tuple[str, ...] = ()
    stale_keys: tuple[str, ...] = ()

    @property
    def is_clean(self) -> bool:
        """Return True when every relevant case is accepted and none are stale."""
        return not self.missing_keys and not self.stale_keys


def relevant_exception_keys(graph: Any) -> tuple[str, ...]:
    """Return stable keys for disconnected components and off-rail supply.

    Components are ordered by the graph builder from largest to smallest;
    the largest component is the connected baseline and the remaining
    components are the intentional-isolation candidates.
    """
    components = list(getattr(graph, "components", ()) or ())
    keys: set[str] = set()
    for component in components[1:]:
        identity = getattr(component, "component_id", None)
        # A supply-only component is represented by its supply-node key;
        # requiring both a component and supply waiver would double-count the
        # same missing railway connection.
        railway_provinces = tuple(getattr(component, "railway_provinces", ()) or ())
        if isinstance(identity, str) and railway_provinces:
            keys.add(component_key(identity))
    for province in tuple(getattr(graph, "supply_off_rail", ()) or ()):
        keys.add(supply_key(province))
    return tuple(sorted(keys))


def _graph_index(graph: Any) -> tuple[set[str], set[int], dict[int, str]]:
    """Copy component, supply, and province lookup sets from a graph.

    Only reads the supplied graph and returns fresh containers, so callers
    can evaluate records without mutating graph state.
    """
    components = getattr(graph, "components", None)
    supply_provinces = getattr(graph, "supply_provinces", None)
    if components is None or supply_provinces is None:
        raise TypeError("graph must expose components and supply_provinces")
    try:
        component_list = list(components)
    except TypeError:
        raise TypeError("graph components must be iterable")
    try:
        supply_list = list(supply_provinces)
    except TypeError:
        raise TypeError("graph supply provinces must be iterable")
    component_ids: set[str] = set()
    province_to_component: dict[int, str] = {}
    for component in component_list:
        identity = getattr(component, "component_id", None)
        provinces = getattr(component, "provinces", None)
        if not isinstance(identity, str) or provinces is None:
            raise TypeError("graph components must carry component_id and provinces")
        component_ids.add(identity)
        try:
            province_list = list(provinces)
        except TypeError:
            raise TypeError("component provinces must be iterable")
        for province in province_list:
            if isinstance(province, bool) or not isinstance(province, Integral):
                continue
            province_to_component.setdefault(int(province), identity)
    supply_set: set[int] = set()
    for province in supply_list:
        if isinstance(province, bool) or not isinstance(province, Integral):
            continue
        supply_set.add(int(province))
    return component_ids, supply_set, province_to_component


def _check_record(
    record: LogisticsException,
    component_ids: set[str],
    supply_set: set[int],
    province_to_component: dict[int, str],
) -> tuple[bool, str]:
    """Decide validity of one record against copied graph lookups."""
    if record.is_component:
        if record.component_id in component_ids:
            return True, _DETAIL_COMPONENT_PRESENT
        return False, _DETAIL_UNKNOWN_COMPONENT
    province = record.supply_province
    if province is None or province not in supply_set:
        return False, _DETAIL_UNKNOWN_SUPPLY
    current = province_to_component.get(province)
    if current is None:
        return False, _DETAIL_SUPPLY_WITHOUT_COMPONENT
    if current != record.component_id:
        return False, _DETAIL_SUPPLY_MOVED_COMPONENT
    return True, _DETAIL_SUPPLY_PRESENT


def evaluate_exception(exception: LogisticsException | Mapping[str, Any], graph: Any) -> ExceptionStatus:
    """Evaluate one record against a graph without mutating either input."""
    if isinstance(exception, LogisticsException):
        record = exception
    else:
        record = LogisticsException.from_dict(exception)
    component_ids, supply_set, province_to_component = _graph_index(graph)
    valid, detail = _check_record(record, component_ids, supply_set, province_to_component)
    return ExceptionStatus(exception=record, valid=valid, detail=detail)


def evaluate_exceptions(
    exceptions: Iterable[LogisticsException | Mapping[str, Any]],
    graph: Any,
) -> ExceptionEvaluation:
    """Evaluate several records against one graph in deterministic key order."""
    if exceptions is None:
        raise ValueError("exceptions must be iterable")
    try:
        items = list(exceptions)
    except TypeError:
        raise ValueError("exceptions must be iterable")
    records: list[LogisticsException] = []
    for item in items:
        if isinstance(item, LogisticsException):
            records.append(item)
        else:
            records.append(LogisticsException.from_dict(item))
    records.sort(key=lambda record: record.key)
    component_ids, supply_set, province_to_component = _graph_index(graph)
    statuses_list: list[ExceptionStatus] = []
    for record in records:
        valid, detail = _check_record(record, component_ids, supply_set, province_to_component)
        statuses_list.append(ExceptionStatus(exception=record, valid=valid, detail=detail))
    statuses = tuple(statuses_list)
    return ExceptionEvaluation(statuses=statuses)


class LogisticsExceptionManager:
    """Deterministic in-memory store for logistics exception records."""

    def __init__(
        self,
        entries: Iterable[LogisticsException | Mapping[str, Any]] | None = None,
    ) -> None:
        self._records: dict[str, LogisticsException] = {}
        if entries is None:
            return
        try:
            items = list(entries)
        except TypeError:
            raise ValueError("entries must be iterable")
        for item in items:
            self.add(item)

    @staticmethod
    def _coerce(value: LogisticsException | Mapping[str, Any]) -> LogisticsException:
        if isinstance(value, LogisticsException):
            return value
        return LogisticsException.from_dict(value)

    def add(self, exception: LogisticsException | Mapping[str, Any]) -> LogisticsException:
        """Insert one record, rejecting duplicate keys and invalid content."""
        record = self._coerce(exception)
        if record.key in self._records:
            raise ValueError("duplicate logistics exception key: %r" % (record.key,))
        self._records[record.key] = record
        return record

    def upsert(self, exception: LogisticsException | Mapping[str, Any]) -> LogisticsException | None:
        """Insert or replace one record, returning the previous record or None."""
        record = self._coerce(exception)
        previous = self._records.get(record.key)
        self._records[record.key] = record
        return previous

    def add_component(self, component_id: str, reason: str, note: str = "") -> LogisticsException:
        """File a component exception for one stable component identity."""
        return self.add(
            LogisticsException(
                key=component_key(component_id),
                reason=reason,
                note=note,
                component_id=component_id,
            )
        )

    def add_supply(
        self,
        province_id: int,
        component_id: str,
        reason: str,
        note: str = "",
    ) -> LogisticsException:
        """File a supply exception with its containing component identity."""
        return self.add(
            LogisticsException(
                key=supply_key(province_id),
                reason=reason,
                note=note,
                component_id=component_id,
            )
        )

    def get(self, key: str) -> LogisticsException | None:
        """Return the record for one key, or None when absent."""
        exception_kind(key)
        return self._records.get(key)

    def remove(self, key: str) -> bool:
        """Delete the record for one key, reporting whether one existed."""
        exception_kind(key)
        if key in self._records:
            del self._records[key]
            return True
        return False

    def clear(self) -> None:
        """Delete every record."""
        self._records.clear()

    def keys(self) -> tuple[str, ...]:
        """Return every stored key in sorted order."""
        return tuple(sorted(self._records))

    def get_all(self) -> list[LogisticsException]:
        """Return every stored record in sorted key order."""
        return [self._records[key] for key in sorted(self._records)]

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        """Serialize every record in sorted key order."""
        return {"exceptions": [record.to_dict() for record in self.get_all()]}

    @classmethod
    def from_dict(cls, data: Any) -> LogisticsExceptionManager:
        """Rebuild a manager, rejecting duplicates and invalid content."""
        if not isinstance(data, Mapping):
            raise ValueError("exception store must be a mapping: %r" % (data,))
        unknown = set(data.keys()) - {"exceptions"}
        if unknown:
            raise ValueError(
                "unknown exception store fields: %s"
                % (sorted(repr(field) for field in unknown),)
            )
        if "exceptions" not in data:
            raise ValueError("exception store requires 'exceptions': %r" % (data,))
        raw = data["exceptions"]
        if not isinstance(raw, list):
            raise ValueError("exception store 'exceptions' must be a list")
        manager = cls()
        for item in raw:
            manager.add(item)
        return manager

    def evaluate(self, graph: Any) -> ExceptionEvaluation:
        """Report record validity against one graph without mutating inputs."""
        component_ids, supply_set, province_to_component = _graph_index(graph)
        statuses: list[ExceptionStatus] = []
        for record in self.get_all():
            valid, detail = _check_record(
                record, component_ids, supply_set, province_to_component
            )
            statuses.append(ExceptionStatus(exception=record, valid=valid, detail=detail))
        return ExceptionEvaluation(statuses=tuple(statuses))

    def prune_stale(self, graph: Any) -> tuple[LogisticsException, ...]:
        """Remove records that no longer match the graph, in key order."""
        report = self.evaluate(graph)
        removed: list[LogisticsException] = []
        for status in report.statuses:
            if not status.valid:
                removed.append(status.exception)
                del self._records[status.exception.key]
        return tuple(removed)

    remove_stale = prune_stale

    def __contains__(self, key: Any) -> bool:
        try:
            exception_kind(key)
        except ValueError:
            return False
        return key in self._records

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self):
        return iter(self.keys())


def evaluate_exception_coverage(
    manager: LogisticsExceptionManager | None,
    graph: Any,
) -> ExceptionCoverage:
    """Evaluate accepted coverage for the graph's disconnected cases.

    Missing records and stale records remain separate: a stale waiver cannot
    silently count as acceptance for a newly changed topology.
    """
    relevant = relevant_exception_keys(graph)
    if manager is None:
        return ExceptionCoverage(relevant_keys=relevant, missing_keys=relevant)
    evaluation = manager.evaluate(graph)
    valid = set(evaluation.valid_keys)
    stale = set(evaluation.stale_keys)
    missing = tuple(sorted(set(relevant) - valid - stale))
    return ExceptionCoverage(
        relevant_keys=relevant,
        accepted_keys=tuple(sorted(valid & set(relevant))),
        missing_keys=missing,
        stale_keys=tuple(sorted(stale)),
    )
