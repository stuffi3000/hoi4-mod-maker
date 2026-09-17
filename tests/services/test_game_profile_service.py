"""M1.2 profile-service tests (no game install required)."""
from __future__ import annotations

import pytest

from services import game_profile_service as svc

pytestmark = pytest.mark.unit


def test_get_default_profile_is_1_19():
    profile = svc.get_default_profile()
    assert profile.profile_id == "hoi4-1.19"
    assert profile.supported_version_pattern == "1.19.*"


def test_get_profile_falls_back_for_unknown():
    default = svc.get_default_profile()
    assert svc.get_profile(None) is default
    assert svc.get_profile("hoi4-1.19") is default
    assert svc.get_profile("unknown-future") is default


def test_validate_map_dimensions_allows_custom():
    assert svc.validate_map_dimensions(5632, 2048) == []
    assert svc.validate_map_dimensions(5632, 2304) == []
    assert svc.validate_map_dimensions(3328, 3840) == []
    assert svc.is_supported_dimension(5632, 2304)
    assert not svc.is_supported_dimension(100, 100)
    errors = svc.validate_map_dimensions(100, 100)
    assert errors


def test_expected_asset_size_helpers():
    assert svc.expected_asset_size("map/provinces.bmp", 5632, 2048) == (5632, 2048)
    assert svc.expected_asset_size("map/trees.bmp", 5632, 2048) == (1408, 512)
    assert svc.expected_asset_size("map/terrain/colormap_water_0.dds", 5632, 2048) == (2816, 1024)
    assert svc.expected_asset_size("no/such/asset.bmp", 5632, 2048) is None


def test_profile_id_for_version():
    assert svc.profile_id_for_version("1.19.3.0") == "hoi4-1.19"
    assert svc.profile_id_for_version("1.20.0.0") == "hoi4-1.20"
    assert svc.profile_id_for_version(None) == "hoi4-1.19"
    assert svc.profile_id_for_version("bad") == "hoi4-1.19"


def test_load_profile_for_target_uses_target_profile():
    class _Target:
        profile_id = "hoi4-1.19"

    assert svc.load_profile_for_target(_Target()) is svc.get_default_profile()
    assert svc.load_profile_for_target(None) is svc.get_default_profile()
