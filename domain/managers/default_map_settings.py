"""default.map configuration.

HOI4 uses map/default.map to tell the engine where to find various map files + tree palette and other configurations.
Reference Reference/Map modding.txt §Default.map (lines 56-83).

Our tool automatically generates BMP/CSV files with vanilla standard filenames, without changing the path.
But users can customize:
- tree_palette_indices: which trees.bmp palette indices count as "trees"
- river_max_level: river maximum width level (default 5)
- max_provinces automatically = actual number of provinces + 1 (required for HOI4)"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field




_FALLBACK_TREE_LEGAL: frozenset[int] = frozenset({0, 2, 3, 5, 6, 11, 28, 29})


def _extract_int_candidates(values) -> set[int]:
    out: set[int] = set()
    if values is None:
        return out
    if isinstance(values, Mapping):
        items: list = []
        items.extend(list(values.keys()))
        items.extend(list(values.values()))
    elif isinstance(values, (str, bytes)):
        return out
    else:
        try:
            items = list(values)
        except TypeError:
            items = [values]
    for item in items:
        try:
            if isinstance(item, bool):
                continue
            number = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= number <= 255:
            out.add(number)
    return out


def resolve_profile_tree_indices(profile) -> frozenset[int] | None:
    if profile is None:
        return None
    try:
        getter = getattr(profile, "legal_tree_indices", None)
        if callable(getter):
            try:
                legal = getter()
                extracted = _extract_int_candidates(legal)
                if extracted:
                    return frozenset(extracted)
            except Exception:
                pass
    except Exception:
        pass
    candidate = None
    try:
        if hasattr(profile, "tree_indices"):
            candidate = getattr(profile, "tree_indices")
        elif isinstance(profile, Mapping) and "tree_indices" in profile:
            candidate = profile["tree_indices"]
    except Exception:
        candidate = None
    if candidate is not None:
        extracted = _extract_int_candidates(candidate)
        if extracted:
            return frozenset(extracted)
    try:
        if isinstance(profile, Mapping) and "tree_indices" in profile:
            extracted = _extract_int_candidates(profile["tree_indices"])
            if extracted:
                return frozenset(extracted)
    except Exception:
        pass
    return frozenset(_FALLBACK_TREE_LEGAL)


def filter_tree_indices(indices, profile) -> tuple[list[int], list[int], str]:
    try:
        requested = [int(v) for v in list(indices or ())]
    except (TypeError, ValueError):
        try:
            requested = [int(indices)]
        except (TypeError, ValueError):
            requested = []
    seen: set[int] = set()
    ordered: list[int] = []
    for value in requested:
        try:
            if isinstance(value, bool):
                continue
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number not in seen:
            seen.add(number)
            ordered.append(number)
    if profile is None:
        return (list(ordered), [], "settings")
    legal = resolve_profile_tree_indices(profile)
    if legal is None:
        return (list(ordered), [], "settings")
    legal_set = set(legal)
    effective = sorted(v for v in ordered if v in legal_set)
    dropped = sorted(v for v in ordered if v not in legal_set)
    return (effective, dropped, "profile")

@dataclass
class DefaultMapSettings:
    """default.map configuration."""

    # Tree palette indices: trees.bmp These indices are counted as trees (default vanilla values)
    # Refer to Map modding.txt §Trees: 0=no tree, 1-13 are different densities/types
    tree_palette_indices: list[int] = field(default_factory=lambda: [3, 4, 7, 10])

    # Maximum river width (1-5, vanilla default 5)
    river_max_level: int = 5

    # These fields cannot be edited, and the vanilla file name is hard-coded (changed and cannot be found in HOI4)
    # But it is exposed in settings to facilitate future expansion.
    definitions: str = "definition.csv"
    provinces: str = "provinces.bmp"
    positions: str = "positions.txt"
    terrain: str = "terrain.bmp"
    rivers: str = "rivers.bmp"
    heightmap: str = "heightmap.bmp"
    tree_definition: str = "trees.bmp"
    continent: str = "continent.txt"
    adjacency_rules: str = "adjacency_rules.txt"
    adjacencies: str = "adjacencies.csv"
    ambient_object: str = "ambient_object.txt"
    seasons: str = "seasons.txt"

    @classmethod
    def default(cls) -> "DefaultMapSettings":
        return cls()

    def effective_tree_indices(self, profile=None) -> list[int]:
        effective, _dropped, _source = filter_tree_indices(self.tree_palette_indices, profile)
        return list(effective)

    def tree_index_report(self, profile=None) -> dict:
        try:
            requested = [int(v) for v in list(self.tree_palette_indices or ())]
        except (TypeError, ValueError):
            requested = []
        effective, dropped, source = filter_tree_indices(self.tree_palette_indices, profile)
        return {
            "requested": list(requested),
            "effective": list(effective),
            "dropped": list(dropped),
            "source": str(source),
        }

    def to_dict(self) -> dict:
        return {
            "tree_palette_indices": list(self.tree_palette_indices),
            "river_max_level": int(self.river_max_level),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DefaultMapSettings":
        return cls(
            tree_palette_indices=list(data.get("tree_palette_indices", [3, 4, 7, 10])),
            river_max_level=int(data.get("river_max_level", 5)),
        )
