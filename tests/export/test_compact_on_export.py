"""Province ID compaction test when exporting - only the exported copy is compacted, with zero changes to the project data.

The project has deliberately numbered holes (province 1/5/9, holes 2-4/6-8):
1. After exporting, the project body (province_map / each manager) is the same byte by byte as before exporting.
2. The exported definition.csv numbers are consecutive (0..N without holes)
3. Railway/supply nodes are remapped according to new numbers in the export file"""

import os
import shutil
import tempfile

import numpy as np
import pytest

from domain.managers.state import StateManager, StateData
from domain.managers.country import CountryManager
from domain.managers.continent import ContinentManager
from domain.managers.railway import RailwayManager
from domain.managers.supply_node import SupplyNodeManager
from export.mod_exporter import export_full_mod
from data.constants import MAP_WIDTH, MAP_HEIGHT, TILE_LAND, TILE_SEA


def _build_gappy_project():
    """Mini project: Province ID 1/5/9 with holes (simulating the state after merging 2-4/6-8)."""
    tile_map = np.full((MAP_HEIGHT, MAP_WIDTH), TILE_LAND, dtype=np.uint8)
    tile_map[0, :] = TILE_SEA
    tile_map[-1, :] = TILE_SEA
    tile_map[:, 0] = TILE_SEA
    tile_map[:, -1] = TILE_SEA

    province_map = np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=np.int32)
    mid = MAP_WIDTH // 2
    province_map[1:-1, 1:mid] = 1       # Zuo Banlu
    province_map[1:-1, mid:-1] = 5      # Right half of the continent (holes 2-4)
    province_map[tile_map == TILE_SEA] = 9  # Border Sea (voids 6-8)

    state_mgr = StateManager()
    s1 = StateData(id=1, name="TestState", provinces=[1, 5],
                   manpower=100000, category="town", owner_tag="TST")
    state_mgr._states[1] = s1
    state_mgr._province_to_state = {1: 1, 5: 1}
    state_mgr._next_id = 2

    country_mgr = CountryManager()
    country_mgr.create_country("TST", "TestLand", (100, 100, 200))
    country_mgr.set_capital("TST", 1)
    country_mgr.assign_state(1, "TST")

    continent_mgr = ContinentManager()

    railway_mgr = RailwayManager()
    railway_mgr.add(1, [1, 5])

    supply_mgr = SupplyNodeManager()
    supply_mgr.add(5)

    return (tile_map, province_map, state_mgr, country_mgr,
            continent_mgr, railway_mgr, supply_mgr)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


@pytest.mark.slow
def test_export_compacts_copy_without_mutating_project():
    (tile_map, province_map, state_mgr, country_mgr,
     continent_mgr, railway_mgr, supply_mgr) = _build_gappy_project()

    pm_before = province_map.copy()

    tmpdir = tempfile.mkdtemp(prefix="hoi4_compact_test_")
    try:
        export_full_mod(
            tile_map=tile_map,
            province_map=province_map,
            output_dir=tmpdir,
            mod_name="CompactTest",
            tag="TST",
            state_mgr=state_mgr,
            country_mgr=country_mgr,
            continent_mgr=continent_mgr,
            railway_mgr=railway_mgr,
            supply_mgr=supply_mgr,
        )

        # ── 1. Zero changes to the project body ──
        assert np.array_equal(province_map, pm_before), \
            "Export must not modify the project's province_map"
        assert state_mgr._states[1].provinces == [1, 5], \
            "Export must not modify the state's province list"
        assert country_mgr.get_country("TST").capital == 1
        assert railway_mgr.get_all()[0].province_ids == [1, 5], \
            "Export must not modify railway data"
        assert [n.province_id for n in supply_mgr.get_all()] == [5], \
            "Export must not modify supply-node data"

        # ── 2. definition.csv numbers are consecutive (1→1, 5→2, 9→3) ──
        defn = _read(os.path.join(tmpdir, "map", "definition.csv"))
        ids = [int(line.split(";")[0])
               for line in defn.strip().splitlines() if line.strip()]
        assert ids == list(range(len(ids))), \
            f"definition.csv IDs must be consecutive from 0: got {ids[:10]}..."
        assert max(ids) == 3  # 0 + 3 provinces

        # ── 3. The exported file is remapped according to the new number ──
        # railways.txt line format: level number of provinces province... → railways [1,5] after compaction = "1 2 1 2"
        railways = _read(os.path.join(tmpdir, "map", "railways.txt"))
        assert "1 2 1 2" in railways, \
            f"Railway provinces should be remapped to 1,2: got {railways!r}"
        # supply_nodes.txt line format: level province → node in province 5 (new number 2) = "1 2"
        supply = _read(os.path.join(tmpdir, "map", "supply_nodes.txt"))
        assert "1 2" in supply, \
            f"Supply node should be remapped to province 2: got {supply!r}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
