"""M3.2a legacy validation adapter tests."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from domain.export_contract import ValidationNote
from domain.validation import ValidationFinding, ValidationReport
from services.validation_service import (
    ARTIFACT_ERROR_CODE,
    ARTIFACT_WARNING_CODE,
    check_item_code,
    finding_from_check_item,
    finding_from_verifier_message,
    findings_from_check_items,
    findings_from_verifier_messages,
    report_from_check_items,
    report_from_findings,
    report_from_verifier_messages,
)

pytestmark = pytest.mark.unit


def _check(name="Provinces", status="ok", detail="", count=0, can_auto=False, **extra):
    """Build a duck-typed CheckItem-like object without Qt or numpy."""
    return SimpleNamespace(
        name=name, status=status, detail=detail, count=count, can_auto=can_auto, **extra
    )


def _check_attrs(items):
    """Snapshot check-like objects as plain tuples for mutation checks."""
    return [(item.name, item.status, item.detail, item.count, item.can_auto) for item in items]


def test_check_item_status_mapping():
    """Legacy statuses map to shared severities with warnings by default."""
    assert finding_from_check_item(_check(status="ok")).severity == "info"
    assert finding_from_check_item(_check(status="warning")).severity == "warning"
    assert finding_from_check_item(_check(status="missing")).severity == "error"
    assert finding_from_check_item(_check(status="bogus")).severity == "warning"


def test_check_item_stable_codes():
    """Identical names repeat codes and distinct names diverge."""
    assert check_item_code("Provinces") == check_item_code("Provinces")
    assert check_item_code("Provinces").startswith("readiness.")
    assert check_item_code("Provinces") != check_item_code("States")
    assert check_item_code("") == "readiness.check"
    first = findings_from_check_items([_check(name="Provinces"), _check(name="States")])
    second = findings_from_check_items([_check(name="Provinces"), _check(name="States")])
    assert [item.code for item in first] == [item.code for item in second]


def test_check_item_explicit_code_wins_over_display_name():
    """Future clients can provide locale-independent rule codes."""
    item = _check(name="Provinces", code="raster.province_ids")
    assert finding_from_check_item(item).code == "readiness.raster.province_ids"
    assert check_item_code("Translated Provinces", "readiness.raster.province_ids") == (
        "readiness.raster.province_ids"
    )


def test_check_items_preserve_detail_count_repair_and_order():
    """Details, counts, repair hints, and order survive conversion."""
    items = [
        _check(name="Provinces", status="warning", detail="3 gaps", count=5),
        _check(name="States", status="missing", detail="No states", count=0, can_auto=True),
    ]
    converted = findings_from_check_items(items)
    assert [item.code for item in converted] == [check_item_code("Provinces"), check_item_code("States")]
    assert converted[0].message == "3 gaps"
    assert "5" in converted[0].evidence
    assert converted[0].repair_code == ""
    assert converted[1].repair_code == "readiness.auto_fix"
    assert all(item.layer == "readiness" for item in converted)
    nameless = finding_from_check_item(_check(detail="", name="Terrain"))
    assert nameless.message == "Terrain"
    with pytest.raises(ValueError):
        finding_from_check_item(None)


def test_check_report_gates_clean_and_blocking_inputs():
    """All-ok reports stay green while missing checks block candidates."""
    ok_items = [
        _check(name="A", status="ok", detail="Fine", count=2),
        _check(name="B", status="ok", detail="Good"),
    ]
    snapshot = _check_attrs(ok_items)
    report = report_from_check_items(ok_items)
    assert isinstance(report, ValidationReport)
    assert _check_attrs(ok_items) == snapshot
    assert report.source == "readiness"
    assert report.info_count == 2
    assert report.evaluate("foundation_candidate").allowed is True
    assert report_from_check_items(None).total == 0
    blocking = report_from_check_items([_check(name="States", status="missing", detail="No states")])
    decision = blocking.evaluate("foundation_candidate")
    assert decision.allowed is False
    assert len(decision.blocking) == 1


def test_verifier_mapping_preserves_error_first_order():
    """Errors convert before warnings with stable artifact codes."""
    errors = ["provinces.bmp is not a valid BMP file", "definition.csv is empty"]
    warnings = ["definition.csv province 3: non-standard type"]
    converted = findings_from_verifier_messages(errors, warnings)
    assert [item.severity for item in converted] == ["error", "error", "warning"]
    assert converted[0].code == ARTIFACT_ERROR_CODE
    assert converted[2].code == ARTIFACT_WARNING_CODE
    assert all(item.layer == "artifact" for item in converted)
    report = report_from_verifier_messages(errors, warnings)
    assert report.source == "artifact"
    assert report.error_count == 2
    assert report.warning_count == 1
    assert report.evaluate("foundation_candidate").allowed is False
    warn_only = report_from_verifier_messages([], ["something odd"])
    visible = warn_only.evaluate("foundation_candidate")
    assert visible.allowed is True
    assert len(visible.visible_warnings) == 1
    with pytest.raises(ValueError):
        finding_from_verifier_message("   ")
    with pytest.raises(ValueError):
        finding_from_verifier_message("note", severity="fatal")


def test_verifier_extracts_relative_path():
    """Portable relative paths from messages become finding paths."""
    finding = finding_from_verifier_message("Missing required file: map/provinces.bmp (province map)")
    assert finding.path == "map/provinces.bmp"
    assert finding.to_dict()["path"] == "map/provinces.bmp"


def test_verifier_scrubs_absolute_machine_paths():
    """No serialized finding keeps a drive, UNC, POSIX home, or tilde path."""
    errors = [
        "Missing outer .mod file: C:\\Users\\tester\\mods\\MyMod\\mymod.mod",
        "Bad file: /home/tester/mods/MyMod/map/terrain.bmp",
        "UNC share: \\\\MACHINE\\share\\mod\\descriptor.mod",
        "Home path: ~/mods/MyMod/map/provinces.bmp",
    ]
    warnings = ["definition.csv province 3: non-standard type"]
    report = report_from_verifier_messages(errors, warnings)
    payload = report.to_dict()
    dumped = json.dumps(payload)
    assert "C:" not in dumped
    assert "/home/tester" not in dumped
    assert "MACHINE" not in dumped
    assert "~/" not in dumped
    for entry in payload["findings"]:
        path = entry["path"]
        assert "C:" not in path
        assert not path.startswith("/")
        assert not path.startswith("\\\\")
        assert ".." not in path
    for finding in report.findings:
        assert "C:\\Users" not in finding.message


def test_report_from_findings_accepts_mixed_legacy():
    """Finding, note, and mapping iterables share one report order."""
    note = ValidationNote(code="state.empty", severity="warning", message="No states", layer="states")
    mapping = {"code": "x.check", "severity": "info", "message": "X"}
    finding = ValidationFinding(code="y.check", severity="error", message="Y")
    report = report_from_findings([finding, note, mapping], source="mixed")
    assert [item.code for item in report.findings] == ["y.check", "state.empty", "x.check"]
    assert report.source == "mixed"
    assert report_from_findings(None).findings == ()
    assert report_from_findings([]).total == 0
    with pytest.raises(ValueError):
        report_from_findings("nope")


def test_adapters_are_quiet_deterministic_and_non_mutating(capsys):
    """Adapters print nothing, copy inputs, and repeat identical reports."""
    errors = ["definition.csv is empty", "provinces.bmp is not a valid BMP file"]
    warnings = ["odd thing happened"]
    checks = [_check(name="Provinces", status="warning", detail="gaps", count=2)]
    error_snapshot = list(errors)
    warning_snapshot = list(warnings)
    check_snapshot = _check_attrs(checks)
    first_verifier = report_from_verifier_messages(errors, warnings)
    second_verifier = report_from_verifier_messages(errors, warnings)
    assert first_verifier.to_dict() == second_verifier.to_dict()
    assert errors == error_snapshot
    assert warnings == warning_snapshot
    first_checks = report_from_check_items(checks)
    assert report_from_check_items(checks).to_dict() == first_checks.to_dict()
    assert _check_attrs(checks) == check_snapshot
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
