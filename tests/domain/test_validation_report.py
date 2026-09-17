"""M3.2a ValidationReport aggregate tests."""
from __future__ import annotations

import copy
import json

import pytest

from domain.export_contract import ValidationNote
from domain.validation import ValidationFinding, ValidationReport, evaluate_gate

pytestmark = pytest.mark.unit


def _finding(code="report.case", severity="error", **overrides):
    """Build a representative finding with portable test metadata."""
    payload = {
        "code": code,
        "severity": severity,
        "message": "Report %s %s" % (code, severity),
        "layer": "provinces",
        "path": "map/provinces.bmp",
    }
    payload.update(overrides)
    return ValidationFinding(**payload)


def test_report_normalizes_mixed_inputs_in_order():
    """Findings, legacy notes, and mappings coerce in caller order."""
    note = ValidationNote(code="state.empty", severity="warning", message="No states", layer="states")
    mapping = {
        "code": "artifact.error",
        "severity": "error",
        "message": "Bad file",
        "layer": "artifact",
        "path": "map/definition.csv",
    }
    report = ValidationReport(findings=[_finding(), note, mapping], source="test")
    assert isinstance(report.findings, tuple)
    assert [item.code for item in report.findings] == ["report.case", "state.empty", "artifact.error"]
    assert [item.severity for item in report.findings] == ["error", "warning", "error"]
    assert all(isinstance(item, ValidationFinding) for item in report.findings)


def test_report_does_not_mutate_caller_input():
    """Caller sequences keep their contents and equal inputs repeat."""
    inputs = [
        {"code": "a.check", "severity": "info", "message": "Alpha"},
        {"code": "b.check", "severity": "warning", "message": "Beta"},
    ]
    snapshot = copy.deepcopy(inputs)
    report = ValidationReport(findings=inputs)
    assert inputs == snapshot
    assert report.findings is not inputs
    assert ValidationReport(findings=inputs) == ValidationReport(findings=inputs)


def test_report_accepts_none_and_single_finding():
    """None means empty and a lone finding wraps to one entry."""
    assert ValidationReport().findings == ()
    assert ValidationReport(findings=None).total == 0
    single = ValidationReport(findings=_finding(code="solo.check", severity="info", message="Solo"))
    assert [item.code for item in single.findings] == ["solo.check"]


def test_report_rejects_unknown_context_and_garbage():
    """Bad contexts, garbage items, strings, and machine paths fail."""
    with pytest.raises(ValueError):
        ValidationReport(findings=[], context="nope")
    with pytest.raises(ValueError):
        ValidationReport(findings=[object()])
    with pytest.raises(ValueError):
        ValidationReport(findings="just-a-string")
    with pytest.raises(ValueError):
        ValidationReport(
            findings=[{"code": "x", "severity": "error", "message": "M", "path": "C:/abs/path.bmp"}]
        )


def test_report_counts_and_severity_helpers():
    """Counts and severity views stay stable and ordered."""
    report = ValidationReport(
        findings=[
            _finding(code="a", severity="info", message="A"),
            _finding(code="b", severity="warning", message="B"),
            _finding(code="c", severity="error", message="C"),
            _finding(code="d", severity="blocker", message="D"),
            _finding(code="e", severity="warning", message="E"),
        ]
    )
    assert report.total == 5
    assert len(report) == 5
    assert report.counts == {"info": 1, "warning": 2, "error": 1, "blocker": 1}
    assert (report.info_count, report.warning_count, report.error_count, report.blocker_count) == (1, 2, 1, 1)
    assert report.has_info and report.has_warnings and report.has_errors and report.has_blockers
    assert [item.code for item in report.infos] == ["a"]
    assert [item.code for item in report.warnings] == ["b", "e"]
    assert [item.code for item in report.errors] == ["c"]
    assert [item.code for item in report.blockers] == ["d"]
    assert [item.code for item in report.by_severity("error")] == ["c"]
    assert list(iter(report)) == list(report.findings)
    assert report[0].code == "a"
    assert not ValidationReport().has_blockers
    with pytest.raises(ValueError):
        report.by_severity("fatal")


def test_report_serialization_round_trip():
    """Reports serialize to JSON-compatible data and rebuild equally."""
    report = ValidationReport(
        findings=[_finding(), _finding(code="state.empty", severity="warning", message="No states")],
        source="readiness",
        context="foundation_candidate",
    )
    payload = report.to_dict()
    json.dumps(payload)
    assert payload["source"] == "readiness"
    assert payload["context"] == "foundation_candidate"
    assert payload["total"] == 2
    assert payload["counts"] == {"info": 0, "warning": 1, "error": 1, "blocker": 0}
    restored = ValidationReport.from_dict(payload)
    assert restored == report
    assert restored.to_dict() == payload
    assert ValidationReport.from_dict({}).findings == ()
    assert ValidationReport.from_dict({}).context == "draft_preview"
    with pytest.raises(ValueError):
        ValidationReport.from_dict("nope")


def test_report_exposes_source_and_context():
    """Source and context survive construction and serialization."""
    report = ValidationReport(findings=[], source="artifact", context="acceptance")
    assert report.source == "artifact"
    assert report.context == "acceptance"
    assert ValidationReport.from_dict(report.to_dict()).context == "acceptance"


def test_report_evaluate_delegates_to_gate_policy():
    """Report evaluation matches evaluate_gate instead of redefining it."""
    findings = [_finding(), _finding(code="state.empty", severity="warning", message="No states")]
    report = ValidationReport(findings=findings, source="x", context="foundation_candidate")
    decision = report.evaluate()
    expected = evaluate_gate(findings, "foundation_candidate")
    assert decision == expected
    assert decision.allowed is False
    assert [item.code for item in decision.blocking] == ["report.case"]
    assert [item.code for item in decision.visible_warnings] == ["state.empty"]
    assert report.evaluate("draft_preview").allowed is True
    waivable = ValidationFinding(
        code="state.empty", severity="warning", message="No states", waivable=True
    ).with_acceptance("w-1", reason="Intentional", reviewed_at="2026-09-17T00:00:00+00:00")
    waived_report = ValidationReport(findings=[waivable], context="freeze")
    waived = waived_report.evaluate(accepted={"w-1"})
    assert waived.allowed is True
    assert [item.code for item in waived.waived] == ["state.empty"]