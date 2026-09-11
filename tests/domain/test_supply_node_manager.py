"""SupplyNodeManager unit test."""

import pytest

from domain.managers.supply_node import SupplyNodeManager, SupplyNode


def test_add_and_count():
    m = SupplyNodeManager()
    assert m.count() == 0
    m.add(1234)
    assert m.count() == 1
    assert m.contains(1234)


def test_add_duplicate_updates():
    m = SupplyNodeManager()
    m.add(1234, level=1)
    m.add(1234, level=2)
    assert m.count() == 1
    assert m.get_all()[0].level == 2


def test_toggle():
    m = SupplyNodeManager()
    assert m.toggle(100) is True   # add
    assert m.contains(100)
    assert m.toggle(100) is False  # delete
    assert not m.contains(100)
    assert m.count() == 0


def test_remove():
    m = SupplyNodeManager()
    m.add(1)
    assert m.remove(1)
    assert not m.remove(1)  # Cannot be deleted the second time
    assert m.count() == 0


def test_line_format():
    """Reference L530: Level Province."""
    node = SupplyNode(province_id=1234, level=1)
    assert node.to_line() == "1 1234"


def test_level_must_be_positive():
    m = SupplyNodeManager()
    with pytest.raises(ValueError):
        m.add(1, level=0)


def test_drop_provinces():
    m = SupplyNodeManager()
    m.add(1)
    m.add(2)
    m.add(3)
    m.drop_provinces({2, 99})
    assert m.count() == 2
    assert not m.contains(2)


def test_remap_provinces():
    m = SupplyNodeManager()
    m.add(1, level=1)
    m.add(2, level=1)
    m.remap_provinces({1: 11, 2: 22})
    assert m.contains(11)
    assert m.contains(22)
    assert not m.contains(1)


def test_remap_drops_unmapped():
    m = SupplyNodeManager()
    m.add(1)
    m.add(2)
    m.remap_provinces({1: 11})  # 2 not mapped
    assert m.count() == 1
    assert m.contains(11)


def test_serialize_roundtrip():
    m = SupplyNodeManager()
    m.add(100)
    m.add(200, level=1)
    data = m.to_dict()

    m2 = SupplyNodeManager()
    m2.from_dict(data)
    assert m2.count() == 2
    assert m2.contains(100)
    assert m2.contains(200)
