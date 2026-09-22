"""Searchable map entities for the editor's Find tool.

The service deliberately has no Qt dependency.  It turns the current project
data into a small search index and supports exact/substring matches together
with conservative fuzzy suggestions when an exact match is not found.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import numpy as np


_KIND_ORDER = {
    "province": 0,
    "state": 1,
    "strategic_region": 2,
}

_KIND_ALIASES = {
    "all": {"province", "state", "strategic_region"},
    "province": {"province"},
    "state": {"state"},
    "strategic_region": {"strategic_region"},
    "region": {"strategic_region"},
    "regions": {"strategic_region"},
    "strategic regions": {"strategic_region"},
}


@dataclass(frozen=True)
class FindResult:
    """A map entity that can be located by the UI."""

    kind: str
    entity_id: int
    name: str
    province_ids: tuple[int, ...] = ()
    aliases: tuple[str, ...] = ()

    @property
    def id(self) -> int:
        """Compatibility-friendly alias for callers that use ``result.id``."""
        return self.entity_id

    @property
    def search_text(self) -> str:
        """A query that identifies this result when used as a suggestion."""
        if self.kind == "province":
            return str(self.entity_id)
        if self.name and not self.name.casefold().startswith(("state_", "region ")):
            return self.name
        return f"{self.kind.replace('_', ' ')} {self.entity_id}"

    def display_name(self) -> str:
        """Return a compact, human-readable label for a result."""
        if self.kind == "province":
            return f"Province {self.entity_id}"
        if self.kind == "state":
            return f"State {self.entity_id} — {self.name}"
        return f"Strategic region {self.entity_id} — {self.name}"


class FindService:
    """Build and search an index over provinces, states, and regions."""

    def __init__(self, project: Any) -> None:
        self._project = project

    def search(self, query: str, scope: str = "all") -> list[FindResult]:
        """Return results matching ``query`` exactly or by name substring.

        Numeric queries match IDs exactly.  Text queries match names and the
        useful type/ID aliases (for example ``state 4`` or ``region 2``).
        """
        normalized = _normalize(query)
        if not normalized:
            return []

        results = []
        for result in self._results(scope):
            if _matches(result, normalized):
                results.append(result)
        return results

    def suggestions(
        self,
        query: str,
        scope: str = "all",
        limit: int = 6,
    ) -> list[FindResult]:
        """Return close results for a query that produced no exact matches."""
        normalized = _normalize(query)
        if not normalized or limit <= 0:
            return []

        scored: list[tuple[float, FindResult]] = []
        for result in self._results(scope):
            score = _similarity(result, normalized)
            if score >= _suggestion_threshold(normalized):
                scored.append((score, result))

        scored.sort(
            key=lambda pair: (
                -pair[0],
                _KIND_ORDER.get(pair[1].kind, 99),
                pair[1].entity_id,
            )
        )
        return [result for _, result in scored[:limit]]

    def _results(self, scope: str) -> list[FindResult]:
        kinds = _KIND_ALIASES.get(str(scope).strip().casefold(), _KIND_ALIASES["all"])
        results: list[FindResult] = []

        if "province" in kinds:
            results.extend(self._province_results())
        if "state" in kinds:
            results.extend(self._state_results())
        if "strategic_region" in kinds:
            results.extend(self._region_results())

        results.sort(key=lambda result: (_KIND_ORDER[result.kind], result.entity_id))
        return results

    def _province_results(self) -> list[FindResult]:
        map_data = getattr(self._project, "map_data", None)
        province_map = getattr(map_data, "province_map", None)
        if province_map is None:
            return []

        ids = sorted(int(pid) for pid in np.unique(province_map) if int(pid) > 0)
        return [
            FindResult(
                kind="province",
                entity_id=pid,
                name=f"Province {pid}",
                province_ids=(pid,),
                aliases=(
                    str(pid),
                    f"province {pid}",
                ),
            )
            for pid in ids
        ]

    def _state_results(self) -> list[FindResult]:
        manager = getattr(self._project, "state_mgr", None)
        states = getattr(manager, "states", {}) if manager is not None else {}
        results = []
        for raw_id, state in states.items():
            state_id = int(getattr(state, "id", raw_id))
            name = str(getattr(state, "name", "") or f"STATE_{state_id}").strip()
            name_en = str(getattr(state, "name_en", "") or "").strip()
            results.append(
                FindResult(
                    kind="state",
                    entity_id=state_id,
                    name=name,
                    province_ids=_positive_ids(getattr(state, "provinces", ())),
                    aliases=_aliases(
                        "state",
                        state_id,
                        name,
                        name_en,
                    ),
                )
            )
        return results

    def _region_results(self) -> list[FindResult]:
        manager = getattr(self._project, "strategic_region_mgr", None)
        regions = getattr(manager, "regions", {}) if manager is not None else {}
        results = []
        for raw_id, region in regions.items():
            region_id = int(getattr(region, "id", raw_id))
            name = str(getattr(region, "name", "") or f"Region {region_id}").strip()
            name_en = str(getattr(region, "name_en", "") or "").strip()
            results.append(
                FindResult(
                    kind="strategic_region",
                    entity_id=region_id,
                    name=name,
                    province_ids=_positive_ids(getattr(region, "province_ids", ())),
                    aliases=_aliases(
                        "strategic_region",
                        region_id,
                        name,
                        name_en,
                    ),
                )
            )
        return results


def _positive_ids(values: Any) -> tuple[int, ...]:
    """Normalize manager references and remove invalid/duplicate IDs."""
    result = set()
    for value in values or ():
        try:
            entity_id = int(value)
        except (TypeError, ValueError):
            continue
        if entity_id > 0:
            result.add(entity_id)
    return tuple(sorted(result))


def _aliases(kind: str, entity_id: int, name: str, name_en: str) -> tuple[str, ...]:
    aliases = {
        str(entity_id),
        name,
        name_en,
    }
    if kind == "state":
        aliases.update({
            f"state {entity_id}",
            f"state_{entity_id}",
        })
    else:
        aliases.update({
            f"region {entity_id}",
            f"strategic region {entity_id}",
            f"strategic_region_{entity_id}",
            f"strategicregion_{entity_id}",
        })
    return tuple(alias for alias in aliases if alias)


def _normalize(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _matches(result: FindResult, query: str) -> bool:
    if query.isdecimal():
        return str(result.entity_id) == query

    return any(
        query == _normalize(alias) or query in _normalize(alias)
        for alias in result.aliases
    )


def _similarity(result: FindResult, query: str) -> float:
    aliases = result.aliases
    if query.isdecimal():
        aliases = (str(result.entity_id),)
    return max(
        SequenceMatcher(None, query, _normalize(alias), autojunk=False).ratio()
        for alias in aliases
        if alias
    )


def _suggestion_threshold(query: str) -> float:
    # One- and two-character queries are too ambiguous to produce useful
    # suggestions.  Numeric IDs can be shorter because their edit distance is
    # meaningful; names need at least three characters.
    if len(query) < 2:
        return 1.1
    return 0.60 if query.isdecimal() else (0.62 if len(query) == 2 else 0.56)
