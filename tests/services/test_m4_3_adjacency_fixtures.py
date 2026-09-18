"""M4.3 adjacency fixture coverage with synthetic logistics data."""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import numpy as np
import pytest

from domain.managers.adjacency import AdjacencyEntry, AdjacencyManager
from domain.managers.adjacency_rule import AdjacencyRuleManager
from domain.validators.logistics import validate_logistics_references
from export.writers.map.adjacencies import write_adjacencies_csv
from export.writers.map.adjacency_rules import write_adjacency_rules_txt
from services.adjacency_io import (
    adjacency_geometry,
    adjacency_wraps_horizontal,
    parse_adjacencies_csv,
    parse_adjacency_rules,
)

pytestmark = pytest.mark.unit

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "logistics" / "adjacency"


def _codes(findings):
    return [item.code for item in findings]


def _workspace_tmpdir(prefix: str) -> Path:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    tmpdir = FIXTURE_DIR / (prefix + uuid.uuid4().hex[:8])
    os.makedirs(tmpdir, exist_ok=True)
    return tmpdir


def test_simple_strait_fields_and_round_trip():
    entries = parse_adjacencies_csv(FIXTURE_DIR / "simple_strait.csv")
    assert len(entries) == 1
    entry = entries[0]
    assert (entry.from_id, entry.to_id) == (101, 102)
    assert entry.type == "sea"
    assert entry.through_id == -1
    assert (entry.start_x, entry.start_y, entry.stop_x, entry.stop_y) == (0, 0, 1, 0)
    assert entry.rule_name == ""
    assert "synthetic strait" in entry.comment

    header = "From;To;Type;Through;start_x;start_y;stop_x;stop_y;adjacency_rule_name;Comment"
    reparsed_memory = parse_adjacencies_csv(header + "\n" + entry.to_csv_line() + "\n")
    assert reparsed_memory == [entry]

    mgr = AdjacencyManager()
    mgr.add(entry)
    tmpdir = _workspace_tmpdir("m43w-strait-")
    try:
        write_adjacencies_csv(str(tmpdir), mgr)
        reparsed = parse_adjacencies_csv(tmpdir / "map" / "adjacencies.csv")
        assert reparsed == mgr.get_all()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    prov = np.array([[101, 102], [103, 104]], dtype=np.int32)
    findings = validate_logistics_references(prov, adjacency_mgr=mgr)
    assert _codes(findings) == []


def test_impassable_semantics_and_contract():
    entries = parse_adjacencies_csv(FIXTURE_DIR / "impassable_border.csv")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.type == "impassable"
    assert entry.through_id == -1
    assert (entry.start_x, entry.start_y, entry.stop_x, entry.stop_y) == (-1, -1, -1, -1)
    assert entry.rule_name == ""
    assert "ridge" in entry.comment
    assert entry.to_csv_line() == (
        "101;103;impassable;-1;-1;-1;-1;-1;;synthetic ridge blocks the valley pass"
    )

    mgr = AdjacencyManager()
    mgr.add(entry)
    prov = np.array([[101, 102], [103, 104]], dtype=np.int32)
    findings = validate_logistics_references(prov, adjacency_mgr=mgr)
    assert _codes(findings) == []


def test_canal_rule_required_provinces_and_access():
    rules = parse_adjacency_rules(FIXTURE_DIR / "canal_access_rules.txt")
    assert len(rules) == 1
    rule = rules[0]
    assert rule.name == "SYNTH_CANAL"
    assert rule.required_provinces == [101, 102]
    assert rule.icon_province == 201
    assert rule.enemy["navy"] is False
    assert rule.friend["navy"] is True
    assert rule.neutral["navy"] is False
    assert rule.contested["army"] is False
    assert "canal passage" in rule.comment

    entries = parse_adjacencies_csv(FIXTURE_DIR / "canal_access.csv")
    assert len(entries) == 1
    assert entries[0].rule_name == "SYNTH_CANAL"
    assert entries[0].through_id == 201
    assert "canal crossing" in entries[0].comment

    adj_mgr = AdjacencyManager()
    adj_mgr.add(entries[0])
    rule_mgr = AdjacencyRuleManager()
    rule_mgr.add(rule)
    prov = np.array([[101, 102, 201]], dtype=np.int32)
    findings = validate_logistics_references(
        prov, adjacency_mgr=adj_mgr, adjacency_rule_mgr=rule_mgr
    )
    assert _codes(findings) == []


def test_canal_rule_round_trip_keeps_data_and_comment():
    rules = parse_adjacency_rules(FIXTURE_DIR / "canal_access_rules.txt")
    mgr = AdjacencyRuleManager()
    mgr.add(rules[0])
    reparsed_memory = parse_adjacency_rules(rules[0].to_block())
    assert reparsed_memory[0].name == "SYNTH_CANAL"
    assert reparsed_memory[0].required_provinces == [101, 102]
    tmpdir = _workspace_tmpdir("m43w-rule-")
    try:
        write_adjacency_rules_txt(str(tmpdir), mgr)
        reparsed = parse_adjacency_rules(tmpdir / "map" / "adjacency_rules.txt")
        assert reparsed == mgr.get_all()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_through_sea_ids_known_and_unknown():
    entries = parse_adjacencies_csv(FIXTURE_DIR / "through_sea.csv")
    assert len(entries) == 1
    assert entries[0].through_id == 205
    assert entries[0].type == "sea"

    mgr = AdjacencyManager()
    mgr.add(entries[0])
    good = np.array([[101, 102, 205]], dtype=np.int32)
    assert validate_logistics_references(good, adjacency_mgr=mgr) == []

    bad = np.array([[101, 102]], dtype=np.int32)
    findings = validate_logistics_references(bad, adjacency_mgr=mgr)
    assert _codes(findings) == ["logistics.adjacency_endpoint"]
    assert "205" in findings[0].evidence


def test_wrap_geometry_map_edge_crossing():
    entries = parse_adjacencies_csv(FIXTURE_DIR / "map_edge_crossing.csv")
    assert len(entries) == 1
    entry = entries[0]
    assert (entry.start_x, entry.start_y, entry.stop_x, entry.stop_y) == (0, 1, 5, 1)
    assert adjacency_wraps_horizontal(entry, 6) is True
    geometry = adjacency_geometry(entry, width=6, height=2)
    assert geometry["wrap_horizontal"] is True
    assert geometry["in_bounds"] is True
    assert geometry["start"] == (0, 1)
    assert geometry["stop"] == (5, 1)

    plain = AdjacencyEntry(101, 102, "sea", start_x=0, start_y=0, stop_x=1, stop_y=0)
    assert adjacency_wraps_horizontal(plain, 6) is False

    mgr = AdjacencyManager()
    mgr.add(entry)
    prov = np.array(
        [[103, 103, 103, 104, 104, 104], [103, 103, 103, 104, 104, 104]],
        dtype=np.int32,
    )
    findings = validate_logistics_references(prov, adjacency_mgr=mgr)
    assert _codes(findings) == []


def test_broken_rule_reference_reports_missing_rule():
    entries = parse_adjacencies_csv(FIXTURE_DIR / "broken_rule_reference.csv")
    assert len(entries) == 1
    assert entries[0].rule_name == "MISSING_SYNTH_RULE"

    mgr = AdjacencyManager()
    mgr.add(entries[0])
    prov = np.array([[101, 102], [103, 104]], dtype=np.int32)
    findings = validate_logistics_references(
        prov, adjacency_mgr=mgr, adjacency_rule_mgr=AdjacencyRuleManager()
    )
    assert _codes(findings) == ["logistics.adjacency_endpoint"]
    assert "MISSING_SYNTH_RULE" in findings[0].evidence
    assert "unknown" in findings[0].evidence
