"""Deterministic logistics proposals built from the actual province graph."""
from collections import deque
from dataclasses import dataclass

import numpy as np

from data.constants import TILE_LAND


@dataclass
class LogisticsProposal:
    edges: list[tuple[int, int]]
    hubs: list[int]


class LogisticsGenerationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def reference_route_mask(path, shape, color=(255, 0, 0), tolerance=40):
    """Read an aligned reference; match route color, ignoring transparent pixels."""
    from PIL import Image
    with Image.open(path) as source:
        rgba = np.asarray(source.convert("RGBA").resize(
            (shape[1], shape[0]), Image.Resampling.NEAREST))
    distance = np.max(np.abs(rgba[:, :, :3].astype(np.int16) - np.array(color)), axis=2)
    return (distance <= tolerance) & (rgba[:, :, 3] > 0)


def generate_logistics(project, route_mask=None):
    """Connect hubs through state-assigned land; never bridge water or missing IDs.

    Map mode uses capitals, victory points, existing hubs/rails and one fallback
    hub per state. Reference mode uses only provinces touched by the route mask.
    Each disconnected land component gets its own network.
    """
    pm = project.map_data.province_map
    tm = project.map_data.tile_map
    if pm.size == 0 or not np.any(pm > 0):
        raise LogisticsGenerationError("no_provinces", "Generate provinces first.")
    if route_mask is not None and route_mask.shape != pm.shape:
        raise LogisticsGenerationError("reference_size", "Reference mask must match the map dimensions.")
    ids, counts = np.unique(pm, return_counts=True)
    land_ids, land_counts = np.unique(pm[tm == TILE_LAND], return_counts=True)
    land = dict(zip(land_ids.tolist(), land_counts.tolist()))
    eligible = {int(p) for p, n in zip(ids, counts) if p > 0 and land.get(p, 0) * 2 > n}
    states = project.state_mgr.states.values()
    assigned = {p for s in states for p in s.provinces}
    eligible &= assigned
    if not eligible:
        raise LogisticsGenerationError(
            "no_state_land", "Assign land provinces to states before generating logistics.")
    if route_mask is not None:
        eligible &= set(np.unique(pm[route_mask]).tolist())
        if not eligible:
            raise LogisticsGenerationError(
                "no_reference_match",
                "No state-assigned land provinces match the reference route color.")
    graph = {p: set() for p in eligible}
    blocked = {tuple(sorted((e.from_id, e.to_id)))
               for e in project.adjacency_mgr.get_all() if e.type == "impassable"}
    for a, b in ((pm[:-1], pm[1:]), (pm[:, :-1], pm[:, 1:])):
        different = a != b
        pairs = np.unique(np.stack((a[different], b[different]), axis=1), axis=0)
        for p, q in pairs.tolist():
            if p in graph and q in graph and tuple(sorted((p, q))) not in blocked:
                graph[p].add(q)
                graph[q].add(p)
    targets = {n.province_id for n in project.supply_mgr.get_all()}
    targets |= set(project.railway_mgr.province_levels())
    targets |= {c.capital for c in project.country_mgr.countries.values()}
    for state in states:
        candidates = sorted(set(state.provinces) & eligible)
        if candidates:
            targets.add(max(candidates, key=lambda p: (state.victory_points.get(p, 0), -p)))
        targets.update(p for p, value in state.victory_points.items() if value > 0)
    targets &= eligible
    edges = set()
    hubs = set()
    remaining = set(graph)
    while remaining:
        root = min(remaining)
        parent = {root: None}
        queue = deque([root])
        while queue:
            p = queue.popleft()
            for q in sorted(graph[p]):
                if q not in parent:
                    parent[q] = p
                    queue.append(q)
        component = set(parent)
        remaining -= component
        terminals = component & targets
        if route_mask is not None:
            for p in component:
                edges.update((min(p, q), max(p, q)) for q in graph[p])
            terminals |= {p for p in component if len(graph[p]) <= 1}
        elif terminals:
            # Re-root at a terminal and keep only branches needed to reach hubs.
            root = min(terminals)
            parent = {root: None}
            queue = deque([root])
            while queue:
                p = queue.popleft()
                for q in sorted(graph[p]):
                    if q not in parent:
                        parent[q] = p
                        queue.append(q)
            for p in sorted(terminals):
                while parent[p] is not None:
                    q = parent[p]
                    edge = (min(p, q), max(p, q))
                    if edge in edges:
                        break
                    edges.add(edge)
                    p = q
        hubs.update(terminals or {root})
    return LogisticsProposal(sorted(edges), sorted(hubs))
