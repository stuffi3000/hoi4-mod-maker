"""Release-candidate metadata and documentation guardrails for M9.3."""
from __future__ import annotations

from pathlib import Path

import pytest

from version import VERSION, VERSION_DATE

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_is_1_4_1():
    assert VERSION == "1.4.1"
    assert VERSION_DATE == "2026-09-22"
    assert (ROOT / "CHANGELOG.md").is_file()


def test_release_docs_describe_foundation_lifecycle_and_credits():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    tutorial = (ROOT / "docs" / "TUTORIAL.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    for text in (readme, tutorial, changelog):
        assert "foundation" in text.lower()
        assert "acceptance" in text.lower()
    assert "AmonStreeling" in readme
    assert "Stuffi3000" in readme
    assert "1.4.1" in changelog


def test_english_release_screenshots_are_present():
    screenshot_dir = ROOT / "docs" / "screenshots"
    for filename in (
        "welcome_page.png",
        "tool_panel_land.png",
        "guide_step2.png",
        "guide_step6.png",
    ):
        image = screenshot_dir / filename
        assert image.is_file()
        assert image.stat().st_size > 1000
