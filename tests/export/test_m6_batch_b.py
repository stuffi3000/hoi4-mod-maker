"""M6 Batch B: selected terrain truth and profile-aware tree contracts."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from data.constants import TILE_LAND
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.game_profile import GameProfile, load_profile_from_file, resolve_tree_dimensions
from domain.managers.default_map_settings import DefaultMapSettings
from domain.validators.terrain import validate_terrain_layers
from export.writers.map.default_map import write_default_map
from export.writers.map.trees_bmp import auto_generate_tree_map, write_trees_bmp
from services.terrain_registry import load_terrain_registry, parse_terrain_registry


pytestmark = pytest.mark.unit

PROFILE_PATH = "data/game_profiles/hoi4_1_19.json"


def _terrain_text():
    return """
terrain = {
    plains = { type = plains color = { 0 7 } texture = 1 }
    city = { type = urban color = { 13 } texture = 10 spawn_city = yes perm_snow = yes }
}
"""


def _bmp_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    return struct.unpack_from("<ii", data, 18)


def test_selected_registry_exposes_contract_fields_and_is_deterministic():
    first = parse_terrain_registry(_terrain_text(), source="custom/00_terrain.txt")
    second = parse_terrain_registry(_terrain_text(), source="custom/00_terrain.txt")

    assert first.to_dict() == second.to_dict()
    plains, city = first.entries
    assert plains.name == "plains"
    assert plains.terrain_type == "plains"
    assert plains.color_indices == (0, 7)
    assert plains.texture == 1
    assert city.spawn_city is True
    assert city.perm_snow is True
    assert city.snow is True
    assert first.legal_palette_indices == frozenset({0, 7, 13})


def test_terrain_registry_supports_custom_text_and_missing_file_diagnostics(tmp_path):
    missing = load_terrain_registry(str(tmp_path / "missing"))
    assert not missing.entries
    assert any("missing" in message or "cannot read" in message for message in missing.diagnostics)

    game = tmp_path / "game"
    terrain_file = game / "common" / "terrain" / "00_terrain.txt"
    terrain_file.parent.mkdir(parents=True)
    terrain_file.write_text(_terrain_text(), encoding="utf-8")
    registry = load_terrain_registry(str(game), extra_texts=[
        "terrain = { extra = { type = hills color = { 17 } texture = 2 } }"
    ])
    assert {entry.name for entry in registry.entries} == {"plains", "city", "extra"}
    assert 17 in registry.legal_palette_indices


def test_selected_registry_is_authoritative_for_terrain_validation():
    tile = np.full((3, 3), TILE_LAND, dtype=np.uint8)
    terrain = np.full((3, 3), 7, dtype=np.uint8)
    registry = parse_terrain_registry(
        "terrain = { plains = { type = plains color = { 0 } texture = 1 } }"
    )

    findings = validate_terrain_layers(tile, terrain, terrain_registry=registry)
    index_findings = [item for item in findings if item.code == "terrain.index"]
    assert len(index_findings) == 1
    assert index_findings[0].affected_ids == (7,)
    assert "selected-registry" in index_findings[0].evidence


def test_profile_tree_dimensions_cover_observed_and_custom_maps():
    profile = load_profile_from_file(PROFILE_PATH)
    assert resolve_tree_dimensions(profile, 5632, 2048) == (1650, 600)
    assert resolve_tree_dimensions(profile, 5632, 2304) == (1650, 675)
    assert resolve_tree_dimensions(profile, 3328, 3840) == (832, 960)


def test_tree_writer_and_generator_are_deterministic_and_profile_legal(tmp_path):
    profile = load_profile_from_file(PROFILE_PATH)
    terrain = np.full((16, 16), TERRAIN_PALETTE_INDEX["forest"], dtype=np.uint8)
    first = auto_generate_tree_map(terrain, profile=profile, map_width=16, map_height=16)
    second = auto_generate_tree_map(terrain, profile=profile, map_width=16, map_height=16)
    assert np.array_equal(first, second)
    assert set(np.unique(first)).issubset(set(profile.tree_indices))

    result = write_trees_bmp(
        str(tmp_path), map_width=5632, map_height=2048, profile=profile
    )
    assert result == (1650, 600)
    assert _bmp_dimensions(tmp_path / "map" / "trees.bmp") == (1650, 600)


def test_profile_aware_default_map_filters_illegal_tree_models(tmp_path):
    profile = load_profile_from_file(PROFILE_PATH)
    settings = DefaultMapSettings(tree_palette_indices=[3, 4, 7, 10])
    write_default_map(str(tmp_path / "profile"), settings=settings, profile=profile)
    text = (tmp_path / "profile" / "map" / "default.map").read_text(encoding="utf-8")
    assert "tree = { 3 }" in text

    write_default_map(str(tmp_path / "legacy"), settings=settings)
    legacy = (tmp_path / "legacy" / "map" / "default.map").read_text(encoding="utf-8")
    assert "tree = { 3 4 7 10 }" in legacy


def test_validator_accepts_an_explicit_profile_tree_override():
    profile = GameProfile(
        tree_indices=[0],
        tree_size_overrides={"8x4": [3, 2]},
    )
    tile = np.full((4, 8), TILE_LAND, dtype=np.uint8)
    terrain = np.full((4, 8), TERRAIN_PALETTE_INDEX["plains"], dtype=np.uint8)
    tree = np.zeros((2, 3), dtype=np.uint8)
    findings = validate_terrain_layers(tile, terrain, tree_map=tree, profile=profile)
    assert not [item for item in findings if item.code == "mask.shape"]
