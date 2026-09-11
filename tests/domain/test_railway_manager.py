"""RailwayManager unit tests."""

import pytest

from domain.managers.railway import RailwayManager, RailwayEntry


def test_add_and_line_format():
    m = RailwayManager()
    idx = m.add(level=4, province_ids=[693, 1444, 12, 11])
    assert idx == 0
    assert m.count() == 1
    line = m.get_all()[0].to_line()
    # Reference document L540 Example: "4 4 693 1444 12 11"
    assert line == "4 4 693 1444 12 11"


def test_level_out_of_range():
    m = RailwayManager()
    with pytest.raises(ValueError):
        m.add(level=0, province_ids=[1, 2])
    with pytest.raises(ValueError):
        m.add(level=6, province_ids=[1, 2])


def test_min_two_provinces():
    m = RailwayManager()
    with pytest.raises(ValueError):
        m.add(level=1, province_ids=[1])


def test_remove_at():
    m = RailwayManager()
    m.add(level=1, province_ids=[1, 2, 3])
    m.add(level=2, province_ids=[4, 5])
    assert m.remove_at(0)
    assert m.count() == 1
    assert m.get_all()[0].level == 2


def test_update_level():
    m = RailwayManager()
    m.add(level=1, province_ids=[1, 2])
    m.update_level(0, 5)
    assert m.get_all()[0].level == 5
    with pytest.raises(ValueError):
        m.update_level(0, 99)


def test_find_by_province():
    m = RailwayManager()
    m.add(level=1, province_ids=[1, 2, 3])
    m.add(level=2, province_ids=[4, 5])
    m.add(level=3, province_ids=[2, 6])
    assert m.find_by_province(2) == [0, 2]
    assert m.find_by_province(99) == []


def test_drop_provinces_removes_affected_railways():
    m = RailwayManager()
    m.add(level=1, province_ids=[1, 2, 3])
    m.add(level=2, province_ids=[4, 5])
    m.drop_provinces({2})  # Deleting province 2 will affect Article 1
    assert m.count() == 1
    assert m.get_all()[0].province_ids == [4, 5]


def test_remap_provinces():
    m = RailwayManager()
    m.add(level=1, province_ids=[1, 2, 3])
    m.remap_provinces({1: 11, 2: 22, 3: 33})
    assert m.get_all()[0].province_ids == [11, 22, 33]


def test_remap_drops_incomplete():
    """If any province in the map is missing, the entire map will be discarded."""
    m = RailwayManager()
    m.add(level=1, province_ids=[1, 2, 3])
    m.remap_provinces({1: 11, 3: 33})  # Province 2 is not mapped
    assert m.count() == 0


def test_serialize_roundtrip():
    m = RailwayManager()
    m.add(level=3, province_ids=[100, 200, 300])
    m.add(level=1, province_ids=[1, 2])
    data = m.to_dict()

    m2 = RailwayManager()
    m2.from_dict(data)
    assert m2.count() == 2
    assert m2.get_all()[0].level == 3
    assert m2.get_all()[1].province_ids == [1, 2]
