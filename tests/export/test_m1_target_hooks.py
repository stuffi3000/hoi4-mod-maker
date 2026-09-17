"""M1.4 target/profile-aware entry-point tests (no game install)."""
from __future__ import annotations

import os
import struct

import numpy as np
import pytest

from domain.validators.province import detect_x_crossings, validate_provinces
from export.verify_mod import ModVerifier
from export.writers.map.descriptor import write_descriptor
from services import game_profile_service as profiles
from services.export_service import validate_before_export
from services.game_assets import resolve_game_target

pytestmark = pytest.mark.unit


def _fake_target(tmp_path):
    game = tmp_path / "game"
    terrain_dir = game / "common" / "terrain"
    terrain_dir.mkdir(parents=True)
    (terrain_dir / "00_terrain.txt").write_text(
        "terrain = { t = { type = plains color = { 0 } texture = 1 } }",
        encoding="utf-8",
    )
    import json

    (game / "launcher-settings.json").write_text(
        json.dumps({"rawVersion": "1.19.3.0"}), encoding="utf-8"
    )
    return resolve_game_target(str(game))


def test_descriptor_prefers_explicit_target(tmp_path):
    target = _fake_target(tmp_path)
    out = tmp_path / "mod"
    out.mkdir()
    write_descriptor("M1Mod", str(out), game_target=target)
    text = (out / "descriptor.mod").read_text(encoding="utf-8")
    assert "supported_version=\"1.19.*\"" in text
    out2 = tmp_path / "mod2"
    out2.mkdir()
    write_descriptor("M1Mod", str(out2), supported_version="1.19.*")
    assert "supported_version=\"1.19.*\"" in (out2 / "descriptor.mod").read_text(encoding="utf-8")


def test_validate_before_export_accepts_profile_kwargs():
    profile = profiles.get_default_profile()

    class _Canvas:
        province_map = np.array([[1, 1], [1, 1]], dtype=np.int32)
        tile_map = np.ones((2, 2), dtype=np.uint8)
        terrain_map = np.zeros((2, 2), dtype=np.uint8)
        river_map = np.full((2, 2), 255, dtype=np.uint8)
        height_map = np.ones((2, 2), dtype=np.float32)

        class map_data:
            provincial_terrain = {}

    from domain.managers.country import CountryManager
    from domain.managers.state import StateManager

    states, countries = StateManager(), CountryManager()
    warnings = validate_before_export(_Canvas(), states, countries)
    assert isinstance(warnings, list)
    custom_warnings = validate_before_export(
        _Canvas(), states, countries, profile=profile, dimensions=(5632, 2304)
    )
    assert isinstance(custom_warnings, list)
    bad = validate_before_export(
        _Canvas(), states, countries, profile=profile, dimensions=(100, 100)
    )
    assert any("multiple" in w or "minimum" in w or "positive" in w for w in bad)


def test_validators_accept_explicit_profile_and_dimensions():
    tile = np.ones((4, 4), dtype=np.uint8)
    prov = np.array(
        [[1, 1, 2, 2], [1, 1, 2, 2], [3, 3, 4, 4], [3, 3, 4, 4]], dtype=np.int32
    )
    profile = profiles.get_default_profile()
    base = validate_provinces(tile, prov)
    explicit = validate_provinces(tile, prov, profile=profile, map_width=4, map_height=4)
    # Explicit profile enables seam coverage for custom widths, so it may report
    # one additional wrap-edge crossing compared to the legacy global-width path.
    assert explicit["x_crossings"] >= base["x_crossings"]
    assert set(base["x_crossing_positions"]).issubset(set(explicit["x_crossing_positions"]))
    assert isinstance(detect_x_crossings(prov, profile=profile), list)


def _write_minimal_provinces_bmp(path: str, width: int, height: int, rows: int = 10):
    row_bytes = width * 3
    padding = (4 - (row_bytes % 4)) % 4
    pixel_offset = 14 + 40
    with open(path, "wb") as handle:
        handle.write(b"BM")
        handle.write(struct.pack("<I", pixel_offset + (row_bytes + padding) * height))
        handle.write(struct.pack("<HH", 0, 0))
        handle.write(struct.pack("<I", pixel_offset))
        handle.write(struct.pack("<I", 40))
        handle.write(struct.pack("<i", width))
        handle.write(struct.pack("<i", height))
        handle.write(struct.pack("<HH", 1, 24))
        handle.write(struct.pack("<I", 0))
        handle.write(struct.pack("<I", (row_bytes + padding) * height))
        handle.write(struct.pack("<ii", 2835, 2835))
        handle.write(struct.pack("<II", 0, 0))
        row = bytes([1, 2, 3] * width)
        pad = b"\x00" * padding
        for _ in range(rows):
            handle.write(row)
            if padding:
                handle.write(pad)


def test_verify_allows_custom_valid_dimensions_as_warning(tmp_path):
    mod = tmp_path / "custom_mod"
    (mod / "map").mkdir(parents=True)
    _write_minimal_provinces_bmp(str(mod / "map" / "provinces.bmp"), 5632, 2304)
    profile = profiles.get_default_profile()
    verifier = ModVerifier(str(mod), quiet=True, profile=profile)
    verifier._check_provinces_bmp()
    assert not [e for e in verifier.errors if "provinces.bmp size" in e]
    assert any("not a standard preset" in w for w in verifier.warnings)


def test_verify_rejects_invalid_dimensions(tmp_path):
    mod = tmp_path / "bad_mod"
    (mod / "map").mkdir(parents=True)
    _write_minimal_provinces_bmp(str(mod / "map" / "provinces.bmp"), 100, 100)
    profile = profiles.get_default_profile()
    verifier = ModVerifier(str(mod), quiet=True, profile=profile)
    verifier._check_provinces_bmp()
    assert any("provinces.bmp" in e for e in verifier.errors)


def test_verify_expected_dimensions_mismatch(tmp_path):
    mod = tmp_path / "mismatch_mod"
    (mod / "map").mkdir(parents=True)
    _write_minimal_provinces_bmp(str(mod / "map" / "provinces.bmp"), 2048, 1024)
    profile = profiles.get_default_profile()
    verifier = ModVerifier(
        str(mod), quiet=True, profile=profile, expected_dimensions=(5632, 2048)
    )
    verifier._check_provinces_bmp()
    assert any("explicit dimensions" in e for e in verifier.errors)


def test_export_rejects_dimensions_that_do_not_match_map_arrays(tmp_path):
    from export.mod_exporter import export_full_mod

    tile = np.ones((4, 4), dtype=np.uint8)
    province = np.ones((4, 4), dtype=np.int32)
    with pytest.raises(ValueError, match="do not match map arrays"):
        export_full_mod(
            tile_map=tile,
            province_map=province,
            output_dir=str(tmp_path / "mod"),
            dimensions=(5632, 2304),
        )
