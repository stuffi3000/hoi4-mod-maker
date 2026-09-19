"""M10 regression checks for profile-aware staged artifact validation."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from services.export_manifest import validate_staged_artifacts


pytestmark = pytest.mark.unit


_MAP_PRODUCTS = (
    "map/provinces.bmp",
    "map/heightmap.bmp",
    "map/terrain.bmp",
    "map/rivers.bmp",
    "map/definition.csv",
    "map/default.map",
    "map/continent.txt",
    "map/adjacencies.csv",
    "map/adjacency_rules.txt",
    "map/seasons.txt",
    "map/ambient_object.txt",
    "map/buildings.txt",
    "map/positions.txt",
)


def _write_map_products(root: Path, profile: str) -> SimpleNamespace:
    for relative in _MAP_PRODUCTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if profile == "foundation" and relative in {
            "map/buildings.txt",
            "map/positions.txt",
        }:
            path.write_text("", encoding="utf-8")
        else:
            path.write_text("valid\n", encoding="utf-8")
    (root / "map" / "strategicregions").mkdir(parents=True, exist_ok=True)
    (root / "map" / "strategicregions" / "1.txt").write_text(
        "valid\n", encoding="utf-8"
    )
    (root / "map" / "supply_nodes.txt").write_text("valid\n", encoding="utf-8")
    (root / "map" / "railways.txt").write_text("valid\n", encoding="utf-8")
    (root / "history" / "states").mkdir(parents=True, exist_ok=True)
    (root / "history" / "states" / "1.txt").write_text("valid\n", encoding="utf-8")
    (root / "descriptor.mod").write_text("valid\n", encoding="utf-8")
    return SimpleNamespace(
        profile_name=profile,
        scope={
            "map": True,
            "strategic_regions": True,
            "supply": True,
            "states": True,
            "descriptor": True,
        },
    )


def test_foundation_allows_intentionally_empty_unreviewed_placements(tmp_path):
    plan = _write_map_products(tmp_path, "foundation")

    assert validate_staged_artifacts(str(tmp_path), plan) == []


def test_playable_profiles_still_require_non_empty_placements(tmp_path):
    plan = _write_map_products(tmp_path, "acceptance")
    (tmp_path / "map" / "buildings.txt").write_text("", encoding="utf-8")
    (tmp_path / "map" / "positions.txt").write_text("", encoding="utf-8")

    errors = validate_staged_artifacts(str(tmp_path), plan)

    assert "missing or empty staged file: map/buildings.txt" in errors
    assert "missing or empty staged file: map/positions.txt" in errors
