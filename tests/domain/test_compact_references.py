"""compact_with_references full reference synchronization test.

The map province ID is 1/3/5 (2 and 4 are the holes left by the merger), which should become 1/2/3 after compaction.
Verify that railways/supply nodes/adjacencies/adjacency rules/continent assignments/province-level terrain are all remapped,
And dead references pointing to deleted provinces (IDs not on the map) are cleaned up."""

import numpy as np
import pytest

from domain.map_data import MapData
from domain.managers.railway import RailwayManager
from domain.managers.supply_node import SupplyNodeManager
from domain.managers.adjacency import AdjacencyManager, AdjacencyEntry
from domain.managers.adjacency_rule import AdjacencyRuleManager, AdjacencyRule
from domain.managers.continent import ContinentManager
from data.constants import set_map_size
import data.constants as _constants


@pytest.fixture(autouse=True)
def _restore_map_size():
    """set_map_size(8, 4) is a global state that must be restored after testing, otherwise it will pollute subsequent tests."""
    w, h = _constants.MAP_WIDTH, _constants.MAP_HEIGHT
    yield
    set_map_size(w, h)


def _make_map_with_gaps() -> MapData:
    """Province ID 1, 3, 5 (2, 4 holes) → 1, 2, 3 after compaction."""
    set_map_size(8, 4)
    md = MapData()
    md.province_map = np.array([
        [0, 0, 1, 1, 3, 3, 5, 5],
        [0, 0, 1, 1, 3, 3, 5, 5],
        [0, 0, 1, 1, 3, 3, 5, 5],
        [0, 0, 1, 1, 3, 3, 5, 5],
    ], dtype=np.int32)
    md.tile_map = np.ones((4, 8), dtype=np.uint8)
    return md


def test_compact_remaps_railways():
    """Railway provinces are remapped; railways referencing deleted provinces are discarded entirely."""
    md = _make_map_with_gaps()
    rw = RailwayManager()
    rw.add(1, [1, 3, 5])
    rw.add(2, [1, 99])  # 99 Not on the map = dead reference

    md.compact_with_references(railway_mgr=rw)

    entries = rw.get_all()
    assert len(entries) == 1
    assert entries[0].province_ids == [1, 2, 3]


def test_compact_remaps_supply_nodes():
    """Supply nodes are remapped; dead reference nodes are discarded."""
    md = _make_map_with_gaps()
    sp = SupplyNodeManager()
    sp.add(3)
    sp.add(99)

    md.compact_with_references(supply_mgr=sp)

    pids = sorted(n.province_id for n in sp.get_all())
    assert pids == [2]


def test_compact_remaps_adjacencies():
    """Adjacency from/to/through remapping; if either end is a dead reference, the entire line is discarded."""
    md = _make_map_with_gaps()
    adj = AdjacencyManager()
    adj.add(AdjacencyEntry(from_id=1, to_id=5, type="sea", through_id=3))
    adj.add(AdjacencyEntry(from_id=1, to_id=99, type="sea"))

    md.compact_with_references(adjacency_mgr=adj)

    entries = adj.get_all()
    assert len(entries) == 1
    e = entries[0]
    assert (e.from_id, e.to_id, e.through_id) == (1, 3, 2)


def test_compact_remaps_adjacency_rules():
    """Adjacency rules required_provinces / icon_province remapping."""
    md = _make_map_with_gaps()
    rules = AdjacencyRuleManager()
    rules.add(AdjacencyRule(
        name="CANAL", required_provinces=[1, 3, 5], icon_province=3,
    ))
    rules.add(AdjacencyRule(
        name="DEAD", required_provinces=[1, 99], icon_province=1,
    ))

    md.compact_with_references(adjacency_rule_mgr=rules)

    rule = rules.get("CANAL")
    assert rule is not None
    assert rule.required_provinces == [1, 2, 3]
    assert rule.icon_province == 2
    assert rules.get("DEAD") is None


def test_compact_remaps_continents():
    """Province → continent assignments are remapped; dead reference assignments are discarded."""
    md = _make_map_with_gaps()
    cont = ContinentManager()
    asia = cont.add_continent("Asia")
    cont.assign_province(3, asia)
    cont.assign_province(99, asia)

    md.compact_with_references(continent_mgr=cont)

    assert cont.get_province_continent(2) == asia
    # The assignment of 99 was discarded, 3 is now another province (originally 5) and should fall back to the default of 0
    assert cont.get_province_continent(3) == 0


def test_compact_drops_zero_pid_references():
    """Dirty data referencing No. 0 (unallocated pixel) will be cleared during compaction and will not be penetrated as it is."""
    md = _make_map_with_gaps()
    sp = SupplyNodeManager()
    sp.add(0)
    cont = ContinentManager()
    cont.assign_province(0, 0)

    md.compact_with_references(supply_mgr=sp, continent_mgr=cont)

    assert sp.get_all() == []
    assert 0 not in cont._province_continent


def test_compact_remaps_provincial_terrain():
    """MapData.provincial_terrain(pid→terrain) remap."""
    md = _make_map_with_gaps()
    md.provincial_terrain = {3: "hills", 5: "mountain", 99: "plains"}

    md.compact_with_references()

    assert md.provincial_terrain == {2: "hills", 3: "mountain"}
