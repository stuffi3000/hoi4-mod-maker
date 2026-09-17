"""M1.2 game-profile contract tests (no game install required)."""
from __future__ import annotations

import json
import os

import pytest

from domain.game_profile import (
    PROFILE_ID_1_19,
    GameProfile,
    load_profile_from_file,
    profile_from_dict,
)

pytestmark = pytest.mark.unit

PROFILE_PATH = os.path.join("data", "game_profiles", "hoi4_1_19.json")


def _load_bundled() -> GameProfile:
    assert os.path.isfile(PROFILE_PATH), f"bundled profile missing: {PROFILE_PATH}"
    return load_profile_from_file(PROFILE_PATH)


def test_bundled_profile_identity():
    profile = _load_bundled()
    assert profile.profile_id == PROFILE_ID_1_19
    assert profile.supported_version_pattern == "1.19.*"
    assert profile.dimensions.divisibility == 256
    assert profile.dimensions.wrap_horizontal is True
    assert profile.dimensions.wrap_vertical is False
    assert profile.terrain_definition_source == "common/terrain/00_terrain.txt"
    assert profile.tree_palette_entries == 256


def test_ui_presets_are_conveniences_not_allowlist():
    profile = _load_bundled()
    assert profile.is_supported_dimension(2048, 1024)
    assert profile.is_supported_dimension(5632, 2048)
    assert profile.is_ui_preset(5632, 2048)
    # Custom mod dimensions must be representable when divisibility passes.
    assert profile.is_supported_dimension(5632, 2304)
    assert profile.is_supported_dimension(3328, 3840)
    assert not profile.is_ui_preset(5632, 2304)
    assert not profile.is_ui_preset(3328, 3840)
    # Observed mod dimensions from the plan are recorded but not required.
    assert [5632, 2304] in profile.dimensions.observed_mod_dimensions
    assert [3328, 3840] in profile.dimensions.observed_mod_dimensions


def test_dimension_rules_reject_bad_sizes():
    profile = _load_bundled()
    assert profile.validate_dimensions(5632, 2048) == []
    assert profile.validate_dimensions(5632, 2304) == []
    assert profile.validate_dimensions(3328, 3840) == []
    bad_width = profile.validate_dimensions(5633, 2048)
    assert any("multiple" in err for err in bad_width)
    bad_height = profile.validate_dimensions(5632, 2049)
    assert any("multiple" in err for err in bad_height)
    too_big = profile.validate_dimensions(8192, 8192)
    assert any("exceed" in err for err in too_big)


def test_asset_ratios_and_formats():
    profile = _load_bundled()
    assert profile.expected_bmp_size("map/provinces.bmp", 5632, 2048) == (5632, 2048)
    assert profile.expected_bmp_size("map/trees.bmp", 5632, 2048) == (1408, 512)
    assert profile.expected_bmp_size("map/world_normal.bmp", 5632, 2048) == (2816, 1024)
    assert profile.expected_dds_size("map/terrain/colormap_water_0.dds", 5632, 2048) == (2816, 1024)
    assert profile.expected_dds_size("map/terrain/colormap_water_1.dds", 5632, 2048) == (1408, 512)
    assert profile.expected_dds_size("map/terrain/colormap_water_2.dds", 5632, 2048) == (704, 256)
    assert profile.expected_dds_size("map/terrain/fow_rgb_waterspec_a.dds", 5632, 2048) == (2816, 1024)
    assert profile.bmp["map/provinces.bmp"].bits_per_pixel == 24
    assert profile.bmp["map/terrain.bmp"].bits_per_pixel == 8
    assert profile.dds["map/terrain/colormap_water_0.dds"].four_cc == "DXT5"
    assert profile.dds["map/terrain/fow_rgb_waterspec_a.dds"].mip_count == 12


def test_required_optional_inherited_and_terrain_tree_contracts():
    profile = _load_bundled()
    assert profile.asset_disposition("map/provinces.bmp") == "required"
    assert profile.asset_disposition("map/trees.bmp") == "required"
    assert profile.asset_disposition("descriptor.mod") == "required"
    assert profile.asset_disposition("map/world_normal.bmp") == "optional"
    assert profile.asset_disposition("map/terrain/atlas0.dds") == "inherited"
    assert profile.terrain_indices["ocean"] == 15
    assert profile.terrain_indices["urban"] == 13
    assert set([0, 2, 3, 5, 6, 11, 28, 29]).issubset(set(profile.tree_indices))
    assert "map/strategicregions" in profile.replace_paths
    assert "history/states" in profile.replace_paths


def test_province_guidance_uses_profile_values():
    profile = _load_bundled()
    assert profile.province_count_warning(1000) == ""
    assert "Warning" in profile.province_count_warning(15000)
    assert "Danger" in profile.province_count_warning(22000)


def test_profile_round_trip_through_dict():
    profile = _load_bundled()
    data = profile.to_dict()
    assert data["profile_id"] == PROFILE_ID_1_19
    restored = profile_from_dict(json.loads(json.dumps(data)))
    assert restored.profile_id == profile.profile_id
    assert restored.to_dict() == data
