"""readiness_service test — Business rules for readiness checks.

This set of standards is shared by the export preflight and production progress panels (M2), and behavioral changes will affect both at the same time."""

from types import SimpleNamespace

import numpy as np
import pytest

from services.readiness_service import check_project_readiness, CheckItem
from domain.managers.state import StateManager, StateData
from domain.managers.country import CountryManager
from domain.managers.continent import ContinentManager
from domain.managers.strategic_region import StrategicRegionManager
from domain.managers.adjacency import AdjacencyManager
from domain.managers.adjacency_rule import AdjacencyRuleManager
from domain.managers.railway import RailwayEntry, RailwayManager
from domain.managers.supply_node import SupplyNodeManager
from domain.project_meta import default_meta
from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE


def _map_source(h=8, w=16):
    """Minimum map data source: upper half of the sea, lower half of the land, two provinces."""
    tile_map = np.full((h, w), TILE_SEA, dtype=np.uint8)
    tile_map[h // 2:, :] = TILE_LAND
    province_map = np.zeros((h, w), dtype=np.int32)
    province_map[:h // 2, :] = 1                   # maritime provinces
    province_map[h // 2:, :] = 2                   # mainland provinces
    terrain_map = np.ones((h, w), dtype=np.uint8)
    height_map = np.full((h, w), 90, dtype=np.uint8)
    height_map[h // 2:, :] = 120
    return SimpleNamespace(
        tile_map=tile_map, province_map=province_map,
        terrain_map=terrain_map, height_map=height_map,
    )


def _project(with_state=True, with_country=True):
    state_mgr = StateManager()
    country_mgr = CountryManager()
    if with_state:
        state_mgr._states[1] = StateData(
            id=1, name="S1", provinces=[2], owner_tag="TST")
        state_mgr._province_to_state = {2: 1}
        state_mgr._next_id = 2
    if with_country:
        country_mgr.create_country("TST", "Test", (10, 20, 30))
        country_mgr.set_capital("TST", 2)
        country_mgr.assign_state(1, "TST")
    sr_mgr = StrategicRegionManager()
    sr_mgr.create_region()
    cont_mgr = ContinentManager()
    return SimpleNamespace(
        state_mgr=state_mgr, country_mgr=country_mgr,
        strategic_region_mgr=sr_mgr, continent_mgr=cont_mgr,
        assets={},
    )


def _by_status(items: list[CheckItem]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i.status] = out.get(i.status, 0) + 1
    return out


def test_empty_map_short_circuits():
    """There is no province: only one missing is reported, and no follow-up checks are performed."""
    src = _map_source()
    src.province_map[:] = 0
    items = check_project_readiness(_project(), src)
    assert len(items) == 1
    assert items[0].status == "missing"


def test_complete_project_all_ok():
    """Complete items: There are no missing items."""
    items = check_project_readiness(_project(), _map_source())
    statuses = _by_status(items)
    assert statuses.get("missing", 0) == 0


def test_missing_state_and_country_flagged_auto_fixable():
    """Missing State/Country: Report missing and the mark can be automatically completed."""
    items = check_project_readiness(
        _project(with_state=False, with_country=False), _map_source())
    missing = [i for i in items if i.status == "missing"]
    assert len(missing) >= 2
    assert all(i.can_auto for i in missing)


def test_id_gap_reported_as_warning():
    """Province number hole: warning (export will be automatically compacted and not blocked)."""
    src = _map_source()
    src.province_map[src.province_map == 2] = 9   # Creates 2-8 holes
    proj = _project(with_state=False, with_country=False)
    items = check_project_readiness(proj, src)
    assert items[0].status == "warning"


def test_land_lake_split_is_reported_as_auto_fixable_surface_warning():
    src = _map_source()
    src.tile_map[4, :4] = TILE_LAKE
    items = check_project_readiness(_project(), src)

    surface = [item for item in items if item.code == "readiness.province_surfaces"]
    assert len(surface) == 1
    assert surface[0].status == "warning"
    assert surface[0].can_auto is True
    assert surface[0].count == 1
    assert "2" in surface[0].detail


def test_accepts_mapdata_as_source():
    """MapData objects are available directly (the panel side does not have to go through the canvas)."""
    import data.constants as constants
    from data.constants import set_map_size
    from domain.map_data import MapData

    old = (constants.MAP_WIDTH, constants.MAP_HEIGHT)
    set_map_size(16, 8)
    try:
        md = MapData()
        src = _map_source()
        md.tile_map[:] = src.tile_map
        md.province_map[:] = src.province_map
        md.terrain_map[:] = src.terrain_map
        md.height_map[:] = src.height_map
        items = check_project_readiness(_project(), md)
        assert _by_status(items).get("missing", 0) == 0
    finally:
        set_map_size(*old)


def test_readiness_reports_logistics_provinces_before_export():
    project = _project()
    project.adjacency_mgr = AdjacencyManager()
    project.adjacency_rule_mgr = AdjacencyRuleManager()
    project.railway_mgr = RailwayManager()
    project.railway_mgr._entries = [RailwayEntry(level=1, province_ids=[1, 99])]
    project.supply_mgr = SupplyNodeManager()

    items = check_project_readiness(project, _map_source())
    railway = [item for item in items if item.code == "readiness.logistics.railway_route"]

    assert len(railway) == 1
    assert railway[0].status == "missing"
    assert "Affected provinces: 1, 99" in railway[0].detail


def test_readiness_exposes_unreviewed_empty_adjacency_layer():
    project = _project()
    project.adjacency_mgr = AdjacencyManager()
    project.adjacency_rule_mgr = AdjacencyRuleManager()
    project.railway_mgr = RailwayManager()
    project.supply_mgr = SupplyNodeManager()
    project.project_meta = default_meta()

    items = check_project_readiness(project, _map_source())
    review = [item for item in items if item.code == "readiness.adjacency_review"]

    assert len(review) == 1
    assert review[0].status == "warning"
    assert "mark none_intended" in review[0].detail


def test_marked_brush_placeholders_are_not_reported_as_authored_self_loops():
    from domain.validators.logistics import validate_logistics_references

    project = _project()
    project.railway_mgr = RailwayManager()
    project.railway_mgr.set_province_level(1, 3)
    project.railway_mgr.set_province_level(2, 3)
    source = _map_source()
    source.tile_map[:] = TILE_LAND

    findings = validate_logistics_references(
        source.province_map,
        source.tile_map,
        railway_mgr=project.railway_mgr,
    )

    assert not any(item.code == "logistics.railway_route" for item in findings)

def _manager_complete_reviewed():
    from domain.managers.map_placement import MapPlacementManager
    mgr = MapPlacementManager()
    for slot in range(6):
        mgr.set_province_slot(2, slot, float(slot) + 0.5, 1.5, provenance="authored", review_status="reviewed")
    return mgr


def _manager_incomplete_unreviewed():
    from domain.managers.map_placement import MapPlacementManager
    mgr = MapPlacementManager()
    for slot in range(5):
        status = "unreviewed" if slot == 0 else "reviewed"
        mgr.set_province_slot(2, slot, float(slot) + 0.5, 0.5, provenance="generated", review_status=status)
    return mgr


def _project_with_lifecycle(lifecycle):
    proj = _project()
    proj.project_meta = SimpleNamespace(lifecycle=lifecycle)
    return proj


def test_draft_manager_reports_warning_without_auto():
    proj = _project_with_lifecycle("draft")
    proj.map_placement_mgr = _manager_incomplete_unreviewed()
    items = check_project_readiness(proj, _map_source())
    assert len(items) >= 1
    last = items[-1]
    assert last.code == "readiness.placements"
    assert last.status == "warning"
    assert last.can_auto is False
    assert "Placement" in last.detail
    assert sum(1 for i in items if i.code == "readiness.placements") == 1


def test_frozen_and_accepted_manager_reports_missing():
    for lifecycle in ["frozen", "accepted"]:
        proj = _project_with_lifecycle(lifecycle)
        proj.map_placement_mgr = _manager_incomplete_unreviewed()
        items = check_project_readiness(proj, _map_source())
        last = items[-1]
        assert last.code == "readiness.placements"
        assert last.status == "missing"
        assert last.can_auto is False
        assert "Placement" in last.detail


def test_reviewed_complete_manager_reports_ok():
    for lifecycle in ["draft", "frozen"]:
        proj = _project_with_lifecycle(lifecycle)
        proj.map_placement_mgr = _manager_complete_reviewed()
        items = check_project_readiness(proj, _map_source())
        last = items[-1]
        assert last.code == "readiness.placements"
        assert last.status == "ok"
        assert last.can_auto is False


def test_foundation_without_manager_reports_missing():
    proj = _project()
    assert not hasattr(proj, "map_placement_mgr")
    items = check_project_readiness(proj, _map_source(), profile_name="foundation")
    assert items[-1].code == "readiness.placements"
    assert items[-1].status == "missing"
    assert items[-1].can_auto is False
    assert "Placement" in items[-1].detail


def test_no_manager_legacy_and_non_foundation_has_no_placements():
    for pname in [None, "legacy_full", "scaffold", "acceptance"]:
        proj = _project()
        if pname is None:
            items = check_project_readiness(proj, _map_source())
        else:
            items = check_project_readiness(proj, _map_source(), profile_name=pname)
        assert all(i.code != "readiness.placements" for i in items)
        assert {i.code for i in items} == {"readiness.provinces", "readiness.states", "readiness.countries", "readiness.strategic_regions", "readiness.continents", "readiness.terrain", "readiness.heightmap"}


def test_placement_check_does_not_mutate_manager():
    proj = _project_with_lifecycle("frozen")
    mgr = _manager_incomplete_unreviewed()
    proj.map_placement_mgr = mgr
    before = mgr.to_dict()
    first = check_project_readiness(proj, _map_source())
    second = check_project_readiness(proj, _map_source())
    assert mgr.to_dict() == before
    assert [i.detail for i in first] == [i.detail for i in second]


def test_readiness_report_forwards_profile_and_codes():
    from services.readiness_service import check_project_readiness_report
    proj = _project_with_lifecycle("draft")
    proj.map_placement_mgr = _manager_incomplete_unreviewed()
    report = check_project_readiness_report(proj, _map_source(), profile_name="foundation")
    assert "readiness.placements" in [f.code for f in report.findings]
    assert report.findings[-1].code == "readiness.placements"
    legacy = check_project_readiness_report(_project(), _map_source())
    assert all(f.code != "readiness.placements" for f in legacy.findings)
