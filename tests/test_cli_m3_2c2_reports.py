"""M3.2c2 CLI shared validation report tests (no game install)."""
from __future__ import annotations

import itertools
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

import cli_export
from domain.export_contract import ExportPlan, ExportResult, ValidationNote
from domain.validation import ValidationReport
from services.validation_service import report_from_findings, report_from_verifier_messages

pytestmark = pytest.mark.unit

_SCRATCH_ROOT = Path("tmp/m3-2c2-basetemp")
_CASE_COUNTER = itertools.count()


@pytest.fixture()
def scratch_dir():
    case = _SCRATCH_ROOT / f"case-{next(_CASE_COUNTER)}"
    case.mkdir(parents=True, exist_ok=True)
    yield case
    shutil.rmtree(case, ignore_errors=True)


def _fake_maps():
    tile = np.ones((2, 2), dtype=np.uint8)
    prov = np.ones((2, 2), dtype=np.int32)
    terr = np.zeros((2, 2), dtype=np.uint8)
    height = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    return tile, prov, terr, height, None, {}, None


def _patch_planner(monkeypatch, plan, missing, result=None, export_stub=None):
    monkeypatch.setattr(cli_export, "configure_console_streams", lambda: None)
    monkeypatch.setattr(cli_export, "load_project", lambda *a, **k: _fake_maps())
    monkeypatch.setattr(cli_export, "read_project_meta", lambda *a, **k: None)
    import services.export_planner as planner_mod
    import services.export_service as svc_mod
    calls = {"plan": 0}
    def _fake_plan(*a, **k):
        calls["plan"] += 1
        return plan
    monkeypatch.setattr(planner_mod, "plan_export", _fake_plan)
    monkeypatch.setattr(planner_mod, "format_plan_summary", lambda p: "PLAN SUMMARY")
    if export_stub is not None:
        monkeypatch.setattr(svc_mod, "export_planned_mod", export_stub)
    elif result is not None:
        monkeypatch.setattr(svc_mod, "export_planned_mod", lambda *a, **k: result)
    monkeypatch.setattr(cli_export, "_verify_planned_export", lambda out, prof: list(missing))
    return calls


def _planner_argv(project, output, json_path=None):
    argv = [str(project), str(output), "--profile", "foundation"]
    if json_path is not None:
        argv += ["--json-report", str(json_path)]
    return argv


def test_plan_report_reuses_shared_adapter():
    plan = ExportPlan(
        profile_name="foundation",
        findings=[
            ValidationNote(code="province.count.soft_max", severity="warning", message="many provinces", layer="map"),
            ValidationNote(code="country.omitted", severity="info", message="no countries", layer="geo"),
        ],
    )
    report = cli_export._plan_validation_report(plan)
    assert isinstance(report, ValidationReport)
    assert report.source == "planner"
    assert report.context == "draft_preview"
    expected = report_from_findings(plan.findings, source="planner", context="draft_preview")
    assert report.to_dict() == expected.to_dict()
    assert report.total == 2
    assert report.warning_count == 1
    assert report.info_count == 1
    json.dumps(report.to_dict())
    for entry in report.to_dict()["findings"]:
        assert "C:" not in entry["path"]
        assert not entry["path"].startswith("/")
        assert ".." not in entry["path"]


def test_human_readable_shows_plan_and_artifact_reports(monkeypatch, scratch_dir, capsys):
    project = scratch_dir / "proj.hoi4proj"
    project.write_bytes(b"fake")
    output = scratch_dir / "output"
    plan = ExportPlan(
        profile_name="foundation",
        findings=[
            ValidationNote(code="province.count.soft_max", severity="warning", message="many provinces", layer="map"),
        ],
    )
    result = ExportResult(output_dir=str(output), profile_name="foundation", success=True, message="ok")
    _patch_planner(monkeypatch, plan, [], result=result)
    code = cli_export.main(_planner_argv(project, output))
    out = capsys.readouterr().out
    assert code == cli_export.EXIT_SUCCESS
    assert "PLAN SUMMARY" in out
    assert "Validation report (plan)" in out
    assert "province.count.soft_max" in out
    assert "many provinces" in out
    assert "Validation report (artifact)" in out
    assert "Final verification passed" in out


def test_json_report_contains_shared_plan_and_artifact(monkeypatch, scratch_dir, capsys):
    project = scratch_dir / "proj.hoi4proj"
    project.write_bytes(b"fake")
    output = scratch_dir / "output"
    json_path = scratch_dir / "report.json"
    plan = ExportPlan(
        profile_name="foundation",
        findings=[
            ValidationNote(code="country.omitted", severity="info", message="no countries here", layer="geo"),
        ],
    )
    result = ExportResult(output_dir=str(output), profile_name="foundation", success=True, message="ok")
    _patch_planner(monkeypatch, plan, [], result=result)
    code = cli_export.main(_planner_argv(project, output, json_path))
    assert code == cli_export.EXIT_SUCCESS
    capsys.readouterr()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "plan" in payload and "result" in payload
    assert payload["result"]["message"] == "ok"
    assert "validation_reports" in payload
    assert payload["validation_reports"]["plan"] == cli_export._plan_validation_report(plan).to_dict()
    assert payload["validation_reports"]["artifact"]["total"] == 0
    assert payload["validation_reports"]["artifact"]["counts"]["error"] == 0
    json.dumps(payload)
    for section in ("plan", "artifact"):
        for entry in payload["validation_reports"][section]["findings"]:
            assert "C:" not in entry["path"]
            assert not entry["path"].startswith("/")
            assert ".." not in entry["path"]


def test_missing_artifact_reporting_uses_verifier_adapter(monkeypatch, scratch_dir, capsys):
    project = scratch_dir / "proj.hoi4proj"
    project.write_bytes(b"fake")
    output = scratch_dir / "output"
    json_path = scratch_dir / "report.json"
    plan = ExportPlan(profile_name="foundation", findings=[])
    result = ExportResult(output_dir=str(output), profile_name="foundation", success=True, message="ok")
    missing = ["map/default.map", "descriptor.mod", str(output) + ".mod"]
    _patch_planner(monkeypatch, plan, missing, result=result)
    code = cli_export.main(_planner_argv(project, output, json_path))
    captured = capsys.readouterr()
    assert code == cli_export.EXIT_VALIDATION_ERROR
    assert "Validation report (artifact)" in captured.out
    assert "artifact.error" in captured.out
    assert "[MISSING/EMPTY] map/default.map" in captured.out
    report = cli_export._artifact_validation_report(missing)
    expected = report_from_verifier_messages(
        ["missing or empty: %s" % path for path in missing], (), source="artifact", context="draft_preview"
    )
    assert report.to_dict() == expected.to_dict()
    assert report.error_count == len(missing)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["validation_reports"]["artifact"]["counts"]["error"] == len(missing)
    for entry in payload["validation_reports"]["artifact"]["findings"]:
        assert "C:" not in entry["message"]
        assert "C:" not in entry["path"]
        assert not entry["path"].startswith("/")
        assert ".." not in entry["path"]


def test_blocked_plan_keeps_validation_error_and_reports(monkeypatch, scratch_dir, capsys):
    project = scratch_dir / "proj.hoi4proj"
    project.write_bytes(b"fake")
    output = scratch_dir / "output"
    json_path = scratch_dir / "report.json"
    plan = ExportPlan(
        profile_name="foundation",
        findings=[
            ValidationNote(code="province.empty", severity="blocker", message="no provinces", layer="map"),
        ],
        blockers=["no provinces"],
    )
    def _must_not_export(*a, **k):
        raise AssertionError("export must not run for blocked plans")
    _patch_planner(monkeypatch, plan, [], result=None, export_stub=_must_not_export)
    code = cli_export.main(_planner_argv(project, output, json_path))
    captured = capsys.readouterr()
    assert code == cli_export.EXIT_VALIDATION_ERROR
    assert "[BLOCKER] no provinces" in captured.err
    assert "Validation report (plan)" in captured.out
    assert "province.empty" in captured.out
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["result"] is None
    assert payload["validation_reports"]["plan"]["total"] == 1
    assert payload["validation_reports"]["artifact"] is None


def test_exception_still_returns_command_error(monkeypatch, scratch_dir, capsys):
    project = scratch_dir / "proj.hoi4proj"
    project.write_bytes(b"fake")
    output = scratch_dir / "output"
    plan = ExportPlan(profile_name="foundation", findings=[])
    def _fail_export(*a, **k):
        raise RuntimeError("writer failed")
    _patch_planner(monkeypatch, plan, [], result=None, export_stub=_fail_export)
    code = cli_export.main(_planner_argv(project, output))
    captured = capsys.readouterr()
    assert code == cli_export.EXIT_COMMAND_ERROR
    assert "writer failed" in captured.err
