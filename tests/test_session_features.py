"""Testing of new features in this session.

Coverage:
- Railway import parsing (count field repair)
- railway set_province_level + undo
- Supply node add/remove
- Strategic area weather/naval import
- VP import analysis
- Centroid caching performance
- SR color map vectorization"""

import numpy as np
import pytest
import tempfile
import os


# ── Railway import analysis ──

def test_parse_railways_skips_count_field():
    """The second field in railways.txt is count, not province ID."""
    from services.import_service import _parse_railways

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    tmp.write("4 4 693 1444 12 11\n")
    tmp.write("2 3 100 200 300\n")
    tmp.write("# comment\n")
    tmp.write("1 2 50 60\n")
    tmp.close()

    result = _parse_railways(tmp.name)
    os.unlink(tmp.name)

    assert len(result) == 3
    # The first line: level=4, count=4, pids=[693,1444,12,11]
    assert result[0]["level"] == 4
    assert result[0]["province_ids"] == [693, 1444, 12, 11]
    # Should not contain count value (4) as province
    assert 4 not in result[0]["province_ids"]
    # Second line: level=2, pids=[100,200,300]
    assert result[1]["province_ids"] == [100, 200, 300]
    # The third line: level=1, pids=[50,60]
    assert result[2]["province_ids"] == [50, 60]


# ── Railway Command + Undo ──

def test_railway_set_level_command():
    """SetRailwayLevelCommand execution and cancellation."""
    from domain.managers.railway import RailwayManager
    from commands.map.set_railway import SetRailwayLevelCommand

    mgr = RailwayManager()
    cmd = SetRailwayLevelCommand(mgr, pid=100, old_level=0, new_level=3)
    cmd.execute()
    assert mgr.province_levels().get(100, 0) == 3

    cmd.undo()
    assert mgr.province_levels().get(100, 0) == 0


def test_railway_set_level_via_history():
    """Perform rail level setup + undo via CommandHistory."""
    from domain.managers.railway import RailwayManager
    from commands.map.set_railway import SetRailwayLevelCommand
    from commands.history import CommandHistory

    mgr = RailwayManager()
    history = CommandHistory()

    cmd = SetRailwayLevelCommand(mgr, pid=50, old_level=0, new_level=5)
    history.execute(cmd)
    assert mgr.province_levels().get(50) == 5

    history.undo()
    assert mgr.province_levels().get(50, 0) == 0

    history.redo()
    assert mgr.province_levels().get(50) == 5


# ── Supply Node ──

def test_supply_node_add_remove():
    """Supply node addition and deletion."""
    from domain.managers.supply_node import SupplyNodeManager

    mgr = SupplyNodeManager()
    mgr.add(100)
    assert mgr.contains(100)
    assert mgr.count() == 1

    mgr.remove(100)
    assert not mgr.contains(100)
    assert mgr.count() == 0


# ── Strategic area introduction ──

def test_parse_sr_weather_and_naval():
    """The strategic terrain parser reads weather and naval_terrain."""
    from services.import_service import _parse_strategic_region_file

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    tmp.write("""strategic_region={
    id=42
    name="STRATEGICREGION_42"
    provinces={ 100 200 300 }
    naval_terrain=water_deep_ocean
    weather={
        period={
            between={ 0.0 30.0 }
            temperature={ 25.0 40.0 }
            no_phenomenon=0.6
            rain_light=0.05
            rain_heavy=0.0
            snow=0.0
            blizzard=0.0
            arctic_water=0.0
            mud=0.0
            sandstorm=0.3
            min_snow_level=0.0
        }
    }
}
""")
    tmp.close()

    r = _parse_strategic_region_file(tmp.name)
    os.unlink(tmp.name)

    assert r is not None
    assert r["id"] == 42
    assert r["provinces"] == [100, 200, 300]
    assert r["naval_terrain"] == "water_deep_ocean"
    assert r["weather_preset"] == "desert"  # sandstorm > 0.1


def test_parse_sr_cold_weather():
    """Cold zone temperature inference."""
    from services.import_service import _guess_weather_preset

    text = """
        temperature={ -20.0 5.0 }
        temperature={ -15.0 8.0 }
        temperature={ -10.0 10.0 }
        sandstorm=0.0
    """
    assert _guess_weather_preset(text) == "cold"


# ── VP import ──

def test_parse_state_victory_points():
    """The State parser reads victory_points."""
    from services.import_service import _parse_state_file

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    tmp.write("""state={
    id=1
    name="STATE_1"
    manpower=50000
    state_category=city
    history={
        owner=GER
        victory_points = { 100 10 }
        victory_points = { 200 5 }
        buildings={
            infrastructure=3
        }
    }
    provinces={ 100 200 300 }
}
""")
    tmp.close()

    r = _parse_state_file(tmp.name)
    os.unlink(tmp.name)

    assert r is not None
    assert r["victory_points"] == {100: 10, 200: 5}


# ── Centroid cache ──

def test_centroid_cache_performance():
    """Centroid cache construction and querying."""
    from domain.map_data import MapData

    md = MapData.__new__(MapData)
    # Minimap: 3 provinces
    md.province_map = np.array([
        [1, 1, 2, 2],
        [1, 1, 2, 3],
        [0, 0, 3, 3],
    ], dtype=np.int32)

    md.build_centroid_cache()

    assert md.get_province_centroid(1) == (0, 0)  # x=mean(0,1,0,1)=0.5→0, y=mean(0,0,1,1)=0.5→0
    assert md.get_province_centroid(2) is not None
    assert md.get_province_centroid(3) is not None
    assert md.get_province_centroid(999) is None


# ── SR color map vectorization ──

def test_sr_color_map_no_crash():
    """SR color map generation is not stuck (vectorized version)."""
    from domain.managers.strategic_region import StrategicRegionManager

    mgr = StrategicRegionManager()
    r = mgr.create_region("TestRegion")
    r.province_ids = [1, 2, 3]

    pm = np.array([[0, 1, 2], [3, 1, 0]], dtype=np.int32)
    tm = np.array([[1, 2, 2], [2, 2, 1]], dtype=np.uint8)  # 1=land, 2=sea

    rgb = mgr.build_sr_color_map(pm, tm)
    assert rgb.shape == (2, 3, 3)
    # Unassigned provinces (0) should be dark gray
    assert rgb[0, 0, 0] == 50


# ── VP Data Storage ──

def test_state_vp_names():
    """StateData stores the VP name."""
    from domain.managers.state import StateData

    s = StateData(id=1, provinces=[10, 20])
    s.victory_points = {10: 5}
    s.vp_names = {10: "Berlin"}

    assert s.vp_names[10] == "Berlin"
