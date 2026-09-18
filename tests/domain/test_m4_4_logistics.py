from __future__ import annotations

import numpy as np

from domain.managers.railway import RailwayManager
from domain.managers.supply_node import SupplyNodeManager
from domain.validators.logistics import validate_logistics_references
from export.csv_writer import write_supply_files
from export.writers.map.railways import write_railways_txt
from export.writers.map.supply import write_railways


def test_valid_supply_without_railway_produces_graph_finding() -> None:
    province_map = np.array([[1, 2]], dtype=np.int32)
    supply = SupplyNodeManager()
    supply.add(1)

    findings = validate_logistics_references(
        province_map,
        supply_mgr=supply,
    )

    assert [finding.code for finding in findings] == ["logistics.graph"]
    assert findings[0].waivable is True
    assert "missing_railway_graph=true" in findings[0].evidence


def test_railway_writers_never_emit_self_loop_fallback(tmp_path) -> None:
    province_map = np.array([[1, 2]], dtype=np.int32)
    empty_railway = RailwayManager()

    write_railways_txt(str(tmp_path / "direct"), empty_railway, province_map)
    direct = (tmp_path / "direct" / "map" / "railways.txt").read_text()
    assert direct.strip() == "1 2 1 2"
    assert "1 1" not in direct

    write_railways({1: [1, 2]}, province_map, str(tmp_path / "legacy"))
    legacy = (tmp_path / "legacy" / "map" / "railways.txt").read_text()
    assert legacy.strip() == "1 2 1 2"
    assert "1 1" not in legacy

    write_supply_files(str(tmp_path / "csv"), 1)
    assert (tmp_path / "csv" / "map" / "railways.txt").read_text() == ""
