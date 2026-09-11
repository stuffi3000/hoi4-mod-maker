"""Feature registry — collects all Features when the application starts, and groups them by category for UI query.

Use:
    from app.registry import FeatureRegistry
    registry = FeatureRegistry()
    registry.register(LandFeature())
    registry.register(StateFeature())
    ...
    map_features = registry.by_category('map')"""

from __future__ import annotations

from features.base import Feature


class FeatureRegistry:
    """Global Feature registry. Remove duplicates by id and group by category."""

    def __init__(self) -> None:
        self._features: dict[str, Feature] = {}

    def register(self, feature: Feature) -> None:
        if not feature.id:
            raise ValueError("Feature must have a non-empty id")
        if feature.id in self._features:
            raise ValueError(f"Duplicate feature id: {feature.id}")
        self._features[feature.id] = feature

    def get(self, feature_id: str) -> Feature | None:
        return self._features.get(feature_id)

    def all(self) -> list[Feature]:
        return list(self._features.values())

    def by_category(self, category: str) -> list[Feature]:
        return [f for f in self._features.values() if f.category == category]

    def count(self) -> int:
        return len(self._features)

    def ids(self) -> list[str]:
        return list(self._features.keys())


class ExporterRegistry:
    """Export the writer registry. Each writer has order to determine the execution order, and group to determine the grouping."""

    def __init__(self) -> None:
        self._writers: list = []  # list of (order, group, name, callable)

    def register(self, name: str, group: str, writer, order: int = 100) -> None:
        if not name:
            raise ValueError("Writer must have a non-empty name")
        for _, _, existing_name, _ in self._writers:
            if existing_name == name:
                raise ValueError(f"Duplicate writer name: {name}")
        self._writers.append((order, group, name, writer))
        self._writers.sort(key=lambda x: (x[0], x[2]))

    def all(self) -> list:
        """Returns [(name, group, callable), ...] sorted by order"""
        return [(name, group, w) for order, group, name, w in self._writers]

    def by_group(self, group: str) -> list:
        return [(name, w) for order, g, name, w in self._writers if g == group]

    def count(self) -> int:
        return len(self._writers)
