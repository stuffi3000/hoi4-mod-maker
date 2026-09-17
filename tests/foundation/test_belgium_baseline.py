"""Regression evidence for the repository-owned Belgium foundation project."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.foundation_baseline import (
    capture_summary,
    inventory_signature,
)


ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PATH = ROOT / "tests" / "fixtures" / "foundation" / "belgium_v1_1_summary.json"
PROJECT_PATH = ROOT / "projects" / "Belgium_Map_v1_1.hoi4proj"

pytestmark = pytest.mark.integration


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def test_committed_belgium_fixture_has_expected_sections():
    fixture = _load_json(SUMMARY_PATH)

    assert fixture["fixture_kind"] == "metadata_only"
    assert fixture["project"]["dimensions"] == {"width": 5632, "height": 2048}
    assert fixture["project"]["province_ids"] == {
        "min": 1,
        "max": 12521,
        "count": 12521,
    }
    assert fixture["project"]["province_types"]["majority_counts"]["land"] == 12100
    assert fixture["project"]["coverage"]["strategic_regions"] == 48
    assert fixture["output_inventory"]["file_count"] == 1074
    assert len(fixture["bmp_headers"]["files"]) == 7
    assert fixture["known_review_findings"]
    assert all(
        finding.get("code") and finding.get("desired")
        for finding in fixture["known_review_findings"]
    )


@pytest.mark.slow
def test_current_belgium_project_matches_metadata_baseline():
    if not PROJECT_PATH.is_file():
        pytest.fail(f"Repository Belgium project is missing: {PROJECT_PATH}")

    expected = _load_json(SUMMARY_PATH)
    actual = capture_summary(PROJECT_PATH)

    assert actual["project"] == expected["project"]


def test_output_inventory_signature_detects_path_changes():
    fixture = _load_json(SUMMARY_PATH)
    expected = fixture["output_inventory"]
    assert expected["file_count"] == 1074
    assert len(expected["path_sha256"]) == 64
    assert inventory_signature(["map/a.txt", "map/b.txt"]) != (
        expected["path_sha256"]
    )


def test_game_profile_and_dds_fixtures_are_metadata_only():
    game_profile = _load_json(
        ROOT / "tests" / "fixtures" / "game_profiles" / "hoi4_1_19_3_headers.json"
    )
    dds_contracts = _load_json(
        ROOT / "tests" / "fixtures" / "assets" / "dds_contracts.json"
    )

    assert game_profile["raw_version"] == "1.19.3.0"
    assert game_profile["source_kind"] == "user_selected_install"
    assert game_profile["files"]["map/provinces.bmp"]["width"] == 5632
    assert game_profile["files"]["map/provinces.bmp"]["bits_per_pixel"] == 24
    assert dds_contracts["contracts"]["map/terrain/colormap_water_0.dds"]["four_cc"] == "DXT5"
    assert all("data" not in value for value in game_profile["files"].values())
