"""M4.2 adjacency CSV/Clausewitz parser and round-trip coverage."""
from __future__ import annotations

from pathlib import Path

import pytest

from domain.managers.adjacency import AdjacencyEntry, AdjacencyManager
from domain.managers.adjacency_rule import AdjacencyRule, AdjacencyRuleManager
from export.writers.map.adjacencies import write_adjacencies_csv
from export.writers.map.adjacency_rules import write_adjacency_rules_txt
from services.adjacency_io import (
    adjacency_geometry,
    parse_adjacencies_csv,
    parse_adjacency_rules,
)
from services.import_service import _parse_adjacency_rules


pytestmark = pytest.mark.unit


def test_csv_parser_preserves_supported_fields_and_comments():
    text = (
        "From;To;Type;Through;start_x;start_y;stop_x;stop_y;"
        "adjacency_rule_name;Comment\n"
        "10;20;sea;30;0;40;99;41;CANAL;comment;with:semicolon\n"
        "20;21;impassable;-1;-1;-1;-1;-1;;mountain wall\n"
        "-1;-1;-1;-1;-1;-1;-1;-1;-1\n"
    )

    entries = parse_adjacencies_csv(text)

    assert entries == [
        AdjacencyEntry(
            10, 20, "sea", 30, 0, 40, 99, 41, "CANAL", "comment;with:semicolon"
        ),
        AdjacencyEntry(20, 21, "impassable", -1, -1, -1, -1, -1, "", "mountain wall"),
    ]


def test_rule_parser_reads_relations_required_provinces_icon_and_comments():
    text = """# Geographic review: canal access
adjacency_rule = {
    name = "TEST_CANAL"
    contested = { army=no navy=no submarine=no trade=no }
    enemy = { army=no navy=yes submarine=no trade=no }
    friend = { army=yes navy=yes submarine=yes trade=yes }
    neutral = { army=yes navy=no submarine=yes trade=yes }
    required_provinces = { 10 20 30 }
    icon = 30
}
"""

    rules = parse_adjacency_rules(text)

    assert len(rules) == 1
    rule = rules[0]
    assert rule.name == "TEST_CANAL"
    assert rule.enemy["navy"] is True
    assert rule.neutral["navy"] is False
    assert rule.required_provinces == [10, 20, 30]
    assert rule.icon_province == 30
    assert rule.comment == "Geographic review: canal access"


def test_import_service_rule_adapter_returns_manager_records(tmp_path: Path):
    path = tmp_path / "adjacency_rules.txt"
    path.write_text(
        'adjacency_rule = { name = "CANAL" required_provinces = { 1 2 } icon = 2 }\n',
        encoding="utf-8",
    )

    records = _parse_adjacency_rules(str(path))

    assert records[0]["name"] == "CANAL"
    assert records[0]["required_provinces"] == [1, 2]
    assert records[0]["icon_province"] == 2


def test_writer_parser_round_trip_keeps_manager_data_and_comments(tmp_path: Path):
    adjacency_mgr = AdjacencyManager()
    adjacency_mgr.add(AdjacencyEntry(1, 2, "sea", through_id=3, comment="strait"))
    rule_mgr = AdjacencyRuleManager()
    rule_mgr.add(AdjacencyRule(
        name="CANAL",
        required_provinces=[1, 2, 3],
        icon_province=3,
        comment="reviewed route",
    ))

    write_adjacencies_csv(str(tmp_path), adjacency_mgr)
    write_adjacency_rules_txt(str(tmp_path), rule_mgr)

    parsed_entries = parse_adjacencies_csv(tmp_path / "map" / "adjacencies.csv")
    parsed_rules = parse_adjacency_rules(tmp_path / "map" / "adjacency_rules.txt")

    assert parsed_entries == adjacency_mgr.get_all()
    assert parsed_rules == rule_mgr.get_all()


def test_geometry_identifies_map_wrap_crossing_and_bounds():
    entry = AdjacencyEntry(1, 2, "sea", start_x=0, start_y=5, stop_x=99, stop_y=6)
    geometry = adjacency_geometry(entry, width=100, height=20)
    assert geometry["wrap_horizontal"] is True
    assert geometry["in_bounds"] is True

    invalid = AdjacencyEntry(1, 2, "sea", start_x=100, start_y=5, stop_x=2, stop_y=6)
    assert adjacency_geometry(invalid, width=100, height=20)["in_bounds"] is False
