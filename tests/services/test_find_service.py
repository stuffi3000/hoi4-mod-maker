"""Search-index tests for the map Find tool."""

import numpy as np

from domain.managers.state import StateData
from model.project import Project
from services.find_service import FindService


def _project_with_entities() -> Project:
    project = Project()
    project.map_data.province_map = np.array(
        [
            [0, 1, 1, 2, 2],
            [0, 1, 1, 2, 2],
        ],
        dtype=np.int32,
    )

    project.state_mgr._states = {
        4: StateData(id=4, name="Northern Coast", provinces=[1]),
        8: StateData(id=8, name="Southern Plain", provinces=[2]),
    }
    region = project.strategic_region_mgr.create_region("Atlantic")
    region.province_ids = [1]
    return project


def test_numeric_search_covers_all_entity_types() -> None:
    service = FindService(_project_with_entities())

    results = service.search("1")

    assert [(result.kind, result.id) for result in results] == [
        ("province", 1),
        ("strategic_region", 1),
    ]


def test_state_and_region_names_are_case_insensitive() -> None:
    service = FindService(_project_with_entities())

    assert [result.id for result in service.search("nOrThErN")] == [4]
    assert [result.id for result in service.search("ATLANTIC")] == [1]


def test_typo_returns_similar_result() -> None:
    service = FindService(_project_with_entities())

    suggestions = service.suggestions("Northrn Coast", scope="state")

    assert [result.name for result in suggestions] == ["Northern Coast"]
