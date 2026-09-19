"""M10 regression checks for the isolated acceptance profile contract."""
from __future__ import annotations

import pytest

from domain.managers.state import StateManager
from export.stages.acceptance_content import run
from export.stages.base import StageContext


pytestmark = pytest.mark.unit


def test_acceptance_content_is_self_contained_and_uses_isolated_owners(tmp_path):
    states = StateManager()
    first = states.create_state("First")
    first.provinces = [1]
    first.owner_tag = "BEL"
    second = states.create_state("Second")
    second.provinces = [2]
    second.owner_tag = "FRA"
    third = states.create_state("Third")
    third.provinces = [3]
    third.owner_tag = "GER"

    context = StageContext(
        profile_name="acceptance",
        output_dir=str(tmp_path),
        state_mgr=states,
        acceptance_tags=("QAA", "QAB"),
        scratch={"states": {1: [1], 2: [2], 3: [3]}},
    )

    result = run(context)

    assert result.stage == "acceptance_content"
    assert (tmp_path / "common/country_tags/99_acceptance_tags.txt").is_file()
    tags = (tmp_path / "common/country_tags/99_acceptance_tags.txt").read_text(
        encoding="utf-8"
    )
    assert 'QAA = "countries/QAA.txt"' in tags
    assert 'QAB = "countries/QAB.txt"' in tags
    for tag in ("QAA", "QAB"):
        assert (tmp_path / f"common/countries/{tag}.txt").is_file()
        assert (tmp_path / f"history/countries/{tag}.txt").is_file()
        oob = tmp_path / f"history/units/{tag}_1936.txt"
        assert oob.is_file()
        assert 'division_template = "Infantry Division"' in oob.read_text(
            encoding="utf-8"
        )
    bookmark = (tmp_path / "common/bookmarks/99_acceptance.txt").read_text(
        encoding="utf-8"
    )
    assert "randomize_weather = yes" in bookmark
    assert {states.get_state(sid).owner_tag for sid in (1, 2, 3)} == {"QAA", "QAB"}
