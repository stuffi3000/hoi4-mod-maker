"""Pure logistics graph analysis (M4.4 slice).

Dependency-light, deterministic analysis over duck-typed railway and supply
managers. This module never touches Qt, game files, or global map dimensions,
never mutates its inputs, and returns the same logical content for the same
graph regardless of manager insertion order.

Public entry points are :func:`build_logistics_graph` and
:func:`analyze_logistics_graph`; the latter is the documented analysis alias
and returns the same :class:`LogisticsGraph` value.

Model:

- vertices are valid railway provinces plus valid supply-node provinces;
- edges join consecutive distinct provinces of usable railway routes, so a
  repeated consecutive province ID is reported as self-loop evidence and
  never becomes a graph edge;
- connected components group vertices joined by edges, while isolated
  supply-only provinces form singleton components;
- each component carries a stable identity derived from canonical province,
  edge, and supply content, so the identifier survives manager reordering
  and can key intentional-exception records later;
- duplicate routes group identical province sequences where a reversed
  sequence counts as the same path, preserving route index and level
  evidence;
- nearest connection candidates pair provinces from different components
  using an explicit distance callback, explicit coordinates, or plain
  province-ID distance as the dependency-free default;
- port, convoy, state, continent, and strategic-region metadata stay
  explicit through optional sets, mappings, or callbacks.

Manager arguments are read-only duck-typed views: any object exposing
``get_all()`` works, including the repository railway and supply managers as
well as mapping or attribute style test fakes. Absent managers behave like
empty ones.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Any

__all__ = [
    "ConnectionCandidate",
    "DuplicateRoute",
    "GraphEdge",
    "LogisticsEdge",
    "LogisticsComponent",
    "LogisticsGraph",
    "SelfLoop",
    "analyze_logistics_graph",
    "build_logistics_graph",
    "component_id_for",
]

_COMPONENT_ID_LENGTH = 12


@dataclass(frozen=True)
class GraphEdge:
    """Undirected railway edge with route evidence.

    ``first`` is always the smaller province ID. ``route_indices`` holds the
    sorted railway route positions that contain this consecutive pair, and
    ``levels`` holds each of those routes raw level values in the same order.
    """

    first: int
    second: int
    route_indices: tuple[int, ...] = ()
    levels: tuple[Any, ...] = ()


# Descriptive alias for callers that prefer the domain name over the concise
# graph-local name.  Both names intentionally refer to the same frozen type.
LogisticsEdge = GraphEdge


@dataclass(frozen=True)
class SelfLoop:
    """Repeated-province evidence inside one railway route.

    ``kind`` is ``consecutive`` for an immediately repeated province ID and
    ``revisit`` for a province seen again later in the same route.
    ``position`` is the route offset where the repeat was observed.
    """

    province_id: int
    route_index: int
    level: Any = None
    kind: str = "consecutive"
    position: int = 0


@dataclass(frozen=True)
class DuplicateRoute:
    """One railway path defined more than once.

    ``path_key`` is the canonical orientation, meaning the lexicographically
    smaller of the province sequence and its reversal. ``route_indices`` are
    the sorted route positions sharing that path and ``levels`` are their raw
    level values in the same order.
    """

    path_key: tuple[int, ...]
    route_indices: tuple[int, ...] = ()
    levels: tuple[Any, ...] = ()

    @property
    def occurrences(self) -> int:
        """Number of routes sharing this path."""
        return len(self.route_indices)


@dataclass(frozen=True)
class ConnectionCandidate:
    """Nearest-province proposal joining two components.

    ``from_province`` is always the smaller province ID so mirrored pairs
    compare equal. ``distance`` comes from the explicit distance callback,
    explicit coordinates, or plain province-ID distance.
    """

    from_province: int
    to_province: int
    from_component: str
    to_component: str
    distance: float


@dataclass(frozen=True)
class LogisticsComponent:
    """One connected set of logistics vertices with summaries."""

    component_id: str
    provinces: tuple[int, ...] = ()
    railway_provinces: tuple[int, ...] = ()
    supply_provinces: tuple[int, ...] = ()
    supply_only_provinces: tuple[int, ...] = ()
    edges: tuple[tuple[int, int], ...] = ()
    route_indices: tuple[int, ...] = ()
    levels: tuple[Any, ...] = ()
    state_ids: tuple[int, ...] = ()
    state_counts: tuple[tuple[int, int], ...] = ()
    continent_ids: tuple[int, ...] = ()
    continent_counts: tuple[tuple[int, int], ...] = ()
    strategic_region_ids: tuple[int, ...] = ()
    strategic_region_counts: tuple[tuple[int, int], ...] = ()
    port_provinces: tuple[int, ...] = ()
    convoy_provinces: tuple[int, ...] = ()
    has_port: bool = False
    has_convoy: bool = False


@dataclass(frozen=True)
class LogisticsGraph:
    """Complete deterministic logistics graph result."""

    vertices: tuple[int, ...] = ()
    railway_provinces: tuple[int, ...] = ()
    supply_provinces: tuple[int, ...] = ()
    supply_on_rail: tuple[int, ...] = ()
    supply_off_rail: tuple[int, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    edge_pairs: tuple[tuple[int, int], ...] = ()
    components: tuple[LogisticsComponent, ...] = ()
    duplicates: tuple[DuplicateRoute, ...] = ()
    self_loops: tuple[SelfLoop, ...] = ()
    candidates: tuple[ConnectionCandidate, ...] = ()
    supply_levels: tuple[tuple[int, int], ...] = ()
    route_count: int = 0
    usable_route_count: int = 0

    @property
    def component_ids(self) -> tuple[str, ...]:
        """Stable component identities in component order."""
        return tuple(component.component_id for component in self.components)

    @property
    def component_count(self) -> int:
        """Number of connected components."""
        return len(self.components)
def _entries(manager: Any) -> list[Any]:
    """Return ``manager.get_all()`` as a fresh list without mutating it."""
    if manager is None:
        return []
    getter = getattr(manager, "get_all", None)
    if callable(getter):
        try:
            items = getter()
        except Exception:
            return []
    else:
        # The validator and small, dependency-free callers can provide a
        # snapshot list instead of manufacturing a manager wrapper.
        items = manager
    if items is None:
        return []
    try:
        return list(items)
    except TypeError:
        return []


def _field(entry: Any, name: str, default: Any = None) -> Any:
    """Read mapping or attribute style entry fields without mutating."""
    if isinstance(entry, Mapping):
        return entry.get(name, default)
    return getattr(entry, name, default)


def _as_int(value: Any) -> int | None:
    """Return integer-like values as int, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        if math.isfinite(value) and value.is_integer():
            return int(value)
        return None
    return None


def _parse_id_list(raw: Any) -> list[int] | None:
    """Parse a province ID sequence, returning None when unusable.

    A usable sequence is a non-string iterable whose items are all positive
    integers. Callers additionally require at least two IDs.
    """
    if raw is None or isinstance(raw, (str, bytes)):
        return None
    try:
        items = list(raw)
    except TypeError:
        return None
    parsed: list[int] = []
    for value in items:
        pid = _as_int(value)
        if pid is None or pid <= 0:
            return None
        parsed.append(pid)
    return parsed


def _make_known_checker(known: Any) -> Callable[[int], bool]:
    """Build a province-membership test from a set, mapping, or callback."""
    if known is None:
        return lambda pid: True
    if isinstance(known, Mapping):
        known_ids = set()
        for key in known.keys():
            parsed = _as_int(key)
            if parsed is not None and parsed > 0:
                known_ids.add(parsed)
        return lambda pid: pid in known_ids
    if callable(known):
        def check_callback(province_id: int) -> bool:
            try:
                return bool(known(province_id))
            except Exception:
                return False
        return check_callback
    known_ids = set()
    try:
        values = list(known)
    except TypeError:
        values = []
    for value in values:
        parsed = _as_int(value)
        if parsed is not None and parsed > 0:
            known_ids.add(parsed)
    return lambda pid: pid in known_ids


def _make_flag_checker(explicit: Any, predicate: Any) -> Callable[[int], bool]:
    """Build a port/convoy flag test from an explicit set and a callback.

    ``explicit`` may be an iterable of province IDs, a mapping of province ID
    to truthy flag, or itself a predicate callback. ``predicate`` is an extra
    optional callback. A province is flagged when any source accepts it.
    """
    explicit_ids: set[int] = set()
    fallback: Callable[[int], bool] | None = None
    if explicit is not None:
        if isinstance(explicit, Mapping):
            for key, value in explicit.items():
                parsed = _as_int(key)
                if parsed is not None and parsed > 0 and bool(value):
                    explicit_ids.add(parsed)
        elif callable(explicit):
            fallback = explicit
        else:
            try:
                listed = list(explicit)
            except TypeError:
                listed = []
            for value in listed:
                parsed = _as_int(value)
                if parsed is not None and parsed > 0:
                    explicit_ids.add(parsed)

    def check(province_id: int) -> bool:
        if province_id in explicit_ids:
            return True
        if predicate is not None:
            try:
                if bool(predicate(province_id)):
                    return True
            except Exception:
                pass
        if fallback is not None:
            try:
                if bool(fallback(province_id)):
                    return True
            except Exception:
                pass
        return False

    return check


def _lookup_value(source: Any, province_id: int) -> Any:
    """Read an optional mapping-or-callback source without mutating it."""
    if source is None:
        return None
    if isinstance(source, Mapping):
        return source.get(province_id)
    if callable(source):
        try:
            return source(province_id)
        except Exception:
            return None
    return None


def _lookup_coords(source: Any, province_id: int) -> tuple[float, float] | None:
    """Read an (x, y) coordinate pair for distance measurement."""
    raw = _lookup_value(source, province_id)
    if raw is None or isinstance(raw, (str, bytes)):
        return None
    try:
        parts = list(raw)
    except TypeError:
        return None
    if len(parts) != 2:
        return None
    try:
        first = float(parts[0])
        second = float(parts[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(first) or not math.isfinite(second):
        return None
    return (first, second)


def _make_distance(distance_fn: Any, coord_source: Any) -> Callable[[int, int], float]:
    """Build the deterministic province distance measure.

    An explicit callback wins when it returns a finite non-negative number.
    Explicit coordinates supply Euclidean distance next. Plain province-ID
    distance is the dependency-free fallback.
    """
    has_coords = coord_source is not None

    def measure(first: int, second: int) -> float:
        if distance_fn is not None:
            try:
                number = float(distance_fn(first, second))
            except Exception:
                number = None
            if number is not None and math.isfinite(number) and number >= 0:
                return float(number)
        if has_coords:
            first_xy = _lookup_coords(coord_source, first)
            second_xy = _lookup_coords(coord_source, second)
            if first_xy is not None and second_xy is not None:
                return math.hypot(first_xy[0] - second_xy[0], first_xy[1] - second_xy[1])
        return float(abs(first - second))

    return measure


def _summarize_regions(
    provinces: tuple[int, ...],
    source: Any,
) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...]]:
    """Return sorted distinct region IDs and sorted (region, count) pairs."""
    if source is None:
        return (), ()
    counts: dict[int, int] = {}
    for pid in provinces:
        region = _as_int(_lookup_value(source, pid))
        if region is None:
            continue
        counts[region] = counts.get(region, 0) + 1
    ordered = tuple(sorted(counts))
    pairs = tuple((region, counts[region]) for region in sorted(counts))
    return ordered, pairs


def component_id_for(
    provinces: Iterable[int],
    edges: Iterable[tuple[int, int]],
    supply: Iterable[int] = (),
) -> str:
    """Return the stable identity for one component content triple.

    The identity hashes canonical sorted province, edge, and supply content,
    so equal topology maps to equal identities regardless of the order the
    content was discovered in. Route indices and levels are evidence rather
    than identity and are deliberately excluded.
    """
    province_ids: list[int] = []
    try:
        province_items = list(provinces)
    except TypeError:
        province_items = []
    for value in province_items:
        parsed = _as_int(value)
        if parsed is not None and parsed > 0 and parsed not in province_ids:
            province_ids.append(parsed)
    province_ids.sort()
    normalized_edges: set[tuple[int, int]] = set()
    try:
        edge_items = list(edges)
    except TypeError:
        edge_items = []
    for pair in edge_items:
        try:
            ends = tuple(pair)
        except TypeError:
            continue
        if len(ends) != 2:
            continue
        first = _as_int(ends[0])
        second = _as_int(ends[1])
        if first is None or second is None or first <= 0 or second <= 0:
            continue
        if first == second:
            continue
        normalized_edges.add((min(first, second), max(first, second)))
    supply_ids: list[int] = []
    try:
        supply_items = list(supply)
    except TypeError:
        supply_items = []
    for value in supply_items:
        parsed = _as_int(value)
        if parsed is not None and parsed > 0 and parsed not in supply_ids:
            supply_ids.append(parsed)
    supply_ids.sort()
    province_text = ",".join(str(pid) for pid in province_ids)
    edge_text = ",".join("%d-%d" % (first, second) for first, second in sorted(normalized_edges))
    supply_text = ",".join(str(pid) for pid in supply_ids)
    payload = "provinces=%s;edges=%s;supply=%s" % (province_text, edge_text, supply_text)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return digest[:_COMPONENT_ID_LENGTH]
def build_logistics_graph(
    railway_mgr: Any = None,
    supply_mgr: Any = None,
    *,
    known_provinces: Iterable[int] | Mapping[int, Any] | Callable[[int], bool] | None = None,
    province_to_state: Mapping[int, int] | Callable[[int], Any] | None = None,
    province_to_continent: Mapping[int, int] | Callable[[int], Any] | None = None,
    province_to_strategic_region: Mapping[int, int] | Callable[[int], Any] | None = None,
    port_provinces: Iterable[int] | Mapping[int, Any] | Callable[[int], bool] | None = None,
    is_port: Callable[[int], bool] | None = None,
    convoy_provinces: Iterable[int] | Mapping[int, Any] | Callable[[int], bool] | None = None,
    has_convoy_access: Callable[[int], bool] | None = None,
    province_coords: Mapping[int, tuple[float, float]] | Callable[[int], Any] | None = None,
    distance_fn: Callable[[int, int], float] | None = None,
    max_candidates: int | None = None,
) -> LogisticsGraph:
    """Build a deterministic logistics graph from railway and supply managers.

    Railway routes are usable for graph content when their province IDs form
    a positive-integer sequence of at least two entries and every province
    passes the optional ``known_provinces`` filter. Supply nodes join the
    graph when their province ID is positive, their level is at least one,
    and the province passes the same filter. Structural reports for
    self-loops and duplicate routes ignore the ``known_provinces`` filter so
    repeated or mirrored sequences stay visible even for unknown provinces.

    Optional region sources may be mappings or callbacks from province ID to
    region ID. Port and convoy sources may be explicit ID sets, mappings of
    ID to truthy flag, predicate callbacks, or a combination of the explicit
    source plus its companion callback. ``province_coords`` and
    ``distance_fn`` tune connection-candidate measurement; ``max_candidates``
    caps the candidate list after deterministic ordering.

    Managers and mappings are only read and never mutated.
    """
    railway_entries = _entries(railway_mgr)
    supply_entries = _entries(supply_mgr)
    known_ok = _make_known_checker(known_provinces)

    route_paths: list[tuple[int, ...] | None] = []
    route_levels: list[Any] = []
    route_usable: list[bool] = []
    for entry in railway_entries:
        level = _field(entry, "level", None)
        route_levels.append(level)
        parsed = _parse_id_list(_field(entry, "province_ids", []))
        if parsed is None or len(parsed) < 2:
            route_paths.append(None)
            route_usable.append(False)
            continue
        path = tuple(parsed)
        route_paths.append(path)
        usable = True
        for pid in path:
            if not known_ok(pid):
                usable = False
                break
        route_usable.append(usable)

    supply_best: dict[int, int] = {}
    for entry in supply_entries:
        pid = _as_int(_field(entry, "province_id", None))
        level = _as_int(_field(entry, "level", None))
        if pid is None or pid <= 0 or level is None or level < 1:
            continue
        if not known_ok(pid):
            continue
        previous = supply_best.get(pid)
        if previous is None or level > previous:
            supply_best[pid] = level

    railway_set: set[int] = set()
    for path, usable in zip(route_paths, route_usable):
        if usable and path is not None:
            railway_set.update(path)
    railway_provinces = tuple(sorted(railway_set))
    supply_set = set(supply_best)
    vertices = tuple(sorted(railway_set | supply_set))
    supply_on_rail = tuple(sorted(supply_set & railway_set))
    supply_off_rail = tuple(sorted(supply_set - railway_set))

    edge_routes: dict[tuple[int, int], dict[int, Any]] = {}
    loops: list[SelfLoop] = []
    for index, path in enumerate(route_paths):
        if path is None:
            continue
        level = route_levels[index]
        seen: set[int] = set()
        for position, pid in enumerate(path):
            if position > 0 and path[position - 1] == pid:
                loops.append(SelfLoop(
                    province_id=pid,
                    route_index=index,
                    level=level,
                    kind="consecutive",
                    position=position - 1,
                ))
            elif pid in seen:
                loops.append(SelfLoop(
                    province_id=pid,
                    route_index=index,
                    level=level,
                    kind="revisit",
                    position=position,
                ))
            seen.add(pid)
        if not route_usable[index]:
            continue
        for position in range(len(path) - 1):
            first = path[position]
            second = path[position + 1]
            if first == second:
                continue
            pair = (first, second) if first < second else (second, first)
            bucket = edge_routes.setdefault(pair, {})
            if index not in bucket:
                bucket[index] = level

    grouped_routes: dict[tuple[int, ...], list[int]] = {}
    for index, path in enumerate(route_paths):
        if path is None:
            continue
        reversed_path = path[::-1]
        key = path if path <= reversed_path else reversed_path
        grouped_routes.setdefault(key, []).append(index)
    duplicates: list[DuplicateRoute] = []
    for key in sorted(grouped_routes):
        indices = sorted(grouped_routes[key])
        if len(indices) < 2:
            continue
        levels = tuple(route_levels[index] for index in indices)
        duplicates.append(DuplicateRoute(
            path_key=key,
            route_indices=tuple(indices),
            levels=levels,
        ))

    edges: list[GraphEdge] = []
    for pair in sorted(edge_routes):
        bucket = edge_routes[pair]
        indices = tuple(sorted(bucket))
        levels = tuple(bucket[index] for index in indices)
        edges.append(GraphEdge(
            first=pair[0],
            second=pair[1],
            route_indices=indices,
            levels=levels,
        ))
    edge_pairs = tuple((edge.first, edge.second) for edge in edges)

    parent = {vertex: vertex for vertex in vertices}

    def find_root(vertex: int) -> int:
        root = vertex
        while parent[root] != root:
            root = parent[root]
        pending = vertex
        while parent[pending] != root:
            parent[pending], pending = root, parent[pending]
        return root

    for first, second in edge_pairs:
        root_first = find_root(first)
        root_second = find_root(second)
        if root_first != root_second:
            parent[root_second] = root_first
    grouped: dict[int, list[int]] = {}
    for vertex in vertices:
        grouped.setdefault(find_root(vertex), []).append(vertex)
    ordered = sorted(
        (tuple(sorted(members)) for members in grouped.values()),
        key=lambda members: (-len(members), members),
    )

    check_port = _make_flag_checker(port_provinces, is_port)
    check_convoy = _make_flag_checker(convoy_provinces, has_convoy_access)
    components: list[LogisticsComponent] = []
    member_sets: list[set[int]] = []
    for members in ordered:
        member_set = set(members)
        member_sets.append(member_set)
        rail_here = tuple(sorted(member_set & railway_set))
        supply_here = tuple(sorted(member_set & supply_set))
        supply_only_here = tuple(sorted(pid for pid in supply_here if pid not in railway_set))
        edges_here = tuple(pair for pair in edge_pairs if pair[0] in member_set and pair[1] in member_set)
        routes_here: list[int] = []
        for index, path in enumerate(route_paths):
            if path is not None and route_usable[index] and path[0] in member_set:
                routes_here.append(index)
        routes_here.sort()
        levels_here = tuple(route_levels[index] for index in routes_here)
        component_id = component_id_for(members, edges_here, supply_here)
        state_ids, state_counts = _summarize_regions(members, province_to_state)
        continent_ids, continent_counts = _summarize_regions(members, province_to_continent)
        region_ids, region_counts = _summarize_regions(members, province_to_strategic_region)
        port_here = tuple(sorted(pid for pid in members if check_port(pid)))
        convoy_here = tuple(sorted(pid for pid in members if check_convoy(pid)))
        components.append(LogisticsComponent(
            component_id=component_id,
            provinces=members,
            railway_provinces=rail_here,
            supply_provinces=supply_here,
            supply_only_provinces=supply_only_here,
            edges=edges_here,
            route_indices=tuple(routes_here),
            levels=levels_here,
            state_ids=state_ids,
            state_counts=state_counts,
            continent_ids=continent_ids,
            continent_counts=continent_counts,
            strategic_region_ids=region_ids,
            strategic_region_counts=region_counts,
            port_provinces=port_here,
            convoy_provinces=convoy_here,
            has_port=len(port_here) > 0,
            has_convoy=len(convoy_here) > 0,
        ))

    measure = _make_distance(distance_fn, province_coords)
    keyed_candidates: list[tuple[tuple[float, int, int], ConnectionCandidate]] = []
    for left_pos in range(len(components)):
        for right_pos in range(left_pos + 1, len(components)):
            left = components[left_pos]
            right = components[right_pos]
            left_set = member_sets[left_pos]
            best_key: tuple[float, int, int] | None = None
            best_candidate: ConnectionCandidate | None = None
            for left_pid in left.provinces:
                for right_pid in right.provinces:
                    dist = measure(left_pid, right_pid)
                    low = left_pid if left_pid <= right_pid else right_pid
                    high = right_pid if left_pid <= right_pid else left_pid
                    key = (float(dist), low, high)
                    if best_key is None or key < best_key:
                        if low in left_set:
                            from_comp = left.component_id
                            to_comp = right.component_id
                        else:
                            from_comp = right.component_id
                            to_comp = left.component_id
                        best_key = key
                        best_candidate = ConnectionCandidate(
                            from_province=low,
                            to_province=high,
                            from_component=from_comp,
                            to_component=to_comp,
                            distance=float(dist),
                        )
            if best_candidate is not None and best_key is not None:
                keyed_candidates.append((best_key, best_candidate))
    keyed_candidates.sort(key=lambda keyed: keyed[0])
    if max_candidates is None:
        limit = len(keyed_candidates)
    else:
        try:
            limit = int(max_candidates)
        except (TypeError, ValueError):
            limit = 0
        limit = max(0, min(limit, len(keyed_candidates)))
    candidates = tuple(candidate for unused_key, candidate in keyed_candidates[:limit])

    ordered_loops = sorted(
        loops,
        key=lambda loop: (loop.province_id, loop.route_index, loop.position, loop.kind),
    )
    return LogisticsGraph(
        vertices=vertices,
        railway_provinces=railway_provinces,
        supply_provinces=tuple(sorted(supply_best)),
        supply_on_rail=supply_on_rail,
        supply_off_rail=supply_off_rail,
        edges=tuple(edges),
        edge_pairs=edge_pairs,
        components=tuple(components),
        duplicates=tuple(duplicates),
        self_loops=tuple(ordered_loops),
        candidates=candidates,
        supply_levels=tuple(sorted(supply_best.items())),
        route_count=len(railway_entries),
        usable_route_count=sum(1 for usable in route_usable if usable),
    )


def analyze_logistics_graph(
    railway_mgr: Any = None,
    supply_mgr: Any = None,
    *,
    known_provinces: Iterable[int] | Mapping[int, Any] | Callable[[int], bool] | None = None,
    province_to_state: Mapping[int, int] | Callable[[int], Any] | None = None,
    province_to_continent: Mapping[int, int] | Callable[[int], Any] | None = None,
    province_to_strategic_region: Mapping[int, int] | Callable[[int], Any] | None = None,
    port_provinces: Iterable[int] | Mapping[int, Any] | Callable[[int], bool] | None = None,
    is_port: Callable[[int], bool] | None = None,
    convoy_provinces: Iterable[int] | Mapping[int, Any] | Callable[[int], bool] | None = None,
    has_convoy_access: Callable[[int], bool] | None = None,
    province_coords: Mapping[int, tuple[float, float]] | Callable[[int], Any] | None = None,
    distance_fn: Callable[[int, int], float] | None = None,
    max_candidates: int | None = None,
) -> LogisticsGraph:
    """Analyze railway and supply managers into a deterministic graph result.

    This is the documented M4.4 analysis entry point and currently returns
    exactly what :func:`build_logistics_graph` produces for the same inputs.
    """
    return build_logistics_graph(
        railway_mgr,
        supply_mgr,
        known_provinces=known_provinces,
        province_to_state=province_to_state,
        province_to_continent=province_to_continent,
        province_to_strategic_region=province_to_strategic_region,
        port_provinces=port_provinces,
        is_port=is_port,
        convoy_provinces=convoy_provinces,
        has_convoy_access=has_convoy_access,
        province_coords=province_coords,
        distance_fn=distance_fn,
        max_candidates=max_candidates,
    )
