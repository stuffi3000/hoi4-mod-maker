"""AdjacencyManager unit tests."""

import pytest

from domain.managers.adjacency import AdjacencyManager, AdjacencyEntry


def test_add_and_count():
    m = AdjacencyManager()
    assert m.count() == 0
    m.add(AdjacencyEntry(1, 2, "sea", through_id=10))
    assert m.count() == 1


def test_add_duplicate_overwrites():
    m = AdjacencyManager()
    m.add(AdjacencyEntry(1, 2, "sea", through_id=10))
    m.add(AdjacencyEntry(1, 2, "sea", through_id=20))
    assert m.count() == 1
    assert m.get_all()[0].through_id == 20


def test_remove_by_pair():
    m = AdjacencyManager()
    m.add(AdjacencyEntry(1, 2, "sea"))
    m.add(AdjacencyEntry(3, 4, "impassable"))
    ok = m.remove(1, 2)
    assert ok
    assert m.count() == 1
    assert m.get_all()[0].from_id == 3


def test_remove_bidirectional():
    m = AdjacencyManager()
    m.add(AdjacencyEntry(1, 2, "sea"))
    # Delete (2,1) should also be deleted to (1,2) (HOI4 thinks the direction is not important)
    ok = m.remove(2, 1)
    assert ok
    assert m.count() == 0


def test_find_by_province():
    m = AdjacencyManager()
    m.add(AdjacencyEntry(1, 2, "sea"))
    m.add(AdjacencyEntry(3, 4, "sea"))
    m.add(AdjacencyEntry(2, 5, "impassable"))
    result = m.find_by_province(2)
    assert len(result) == 2


def test_to_csv_line_sea():
    e = AdjacencyEntry(
        from_id=6891, to_id=3838, type="sea", through_id=5579,
        comment="Sardinia-Corsica",
    )
    line = e.to_csv_line()
    assert line == "6891;3838;sea;5579;-1;-1;-1;-1;;Sardinia-Corsica"


def test_to_csv_line_impassable_forces_defaults():
    """impassable must set all through/coordinates/rule to -1 and empty."""
    e = AdjacencyEntry(
        from_id=10910, to_id=12807, type="impassable",
        through_id=999, rule_name="bogus_rule",  # should be ignored
        comment="Himalayas",
    )
    line = e.to_csv_line()
    assert line == "10910;12807;impassable;-1;-1;-1;-1;-1;;Himalayas"


def test_drop_provinces():
    m = AdjacencyManager()
    m.add(AdjacencyEntry(1, 2, "sea", through_id=100))
    m.add(AdjacencyEntry(3, 4, "impassable"))
    m.drop_provinces({2, 999})
    assert m.count() == 1
    assert m.get_all()[0].from_id == 3


def test_remap_provinces():
    m = AdjacencyManager()
    m.add(AdjacencyEntry(1, 2, "sea", through_id=100))
    m.remap_provinces({1: 11, 2: 22, 100: 1100})
    assert m.count() == 1
    e = m.get_all()[0]
    assert (e.from_id, e.to_id, e.through_id) == (11, 22, 1100)


def test_remap_drops_entries_with_deleted_endpoint():
    m = AdjacencyManager()
    m.add(AdjacencyEntry(1, 2, "sea"))
    m.remap_provinces({1: 11})  # Province 2 was deleted
    assert m.count() == 0


def test_serialize_roundtrip():
    m = AdjacencyManager()
    m.add(AdjacencyEntry(1, 2, "sea", through_id=100, rule_name="dardanelles"))
    m.add(AdjacencyEntry(5, 6, "impassable", comment="mountain"))
    data = m.to_dict()

    m2 = AdjacencyManager()
    m2.from_dict(data)
    assert m2.count() == 2
    all_entries = m2.get_all()
    assert all_entries[0].rule_name == "dardanelles"
    assert all_entries[1].type == "impassable"
