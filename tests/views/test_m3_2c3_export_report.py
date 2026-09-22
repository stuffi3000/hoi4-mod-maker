"""M3.2c3 export-dialog shared-report client tests (no game install)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication

from domain.export_contract import ValidationNote
from domain.validation import ValidationReport
from services.validation_service import report_from_findings, report_from_verifier_messages

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_dialog(output_dir="fake/output/dir", worker=None):
    from views.export_dialog import ExportDialog

    dialog = ExportDialog.__new__(ExportDialog)
    dialog._output_dir = output_dir
    dialog._worker = worker if worker is not None else SimpleNamespace(
        profile=None, dimensions=None, game_target=None
    )
    dialog._progress_bar = MagicMock()
    dialog._progress_label = MagicMock()
    captured = {}
    dialog._show_export_result = lambda lines, verify_errors: captured.update(
        lines=list(lines), verify_errors=list(verify_errors)
    )
    return dialog, captured


def _forbid_verify_quiet(*args, **kwargs):
    raise AssertionError("verify_quiet must not run; use verify_report once")


def test_on_export_done_uses_verify_report_once_with_context(qapp, monkeypatch):
    from export import verify_mod as verify_mod_mod

    profile = object()
    target = object()
    calls = []
    fake_report = report_from_verifier_messages(["boom failure"], ["careful warning"])

    @classmethod
    def _fake_verify_report(cls, mod_dir, *, profile=None, expected_dimensions=None,
                             game_target=None, **kwargs):
        calls.append(
            {
                "mod_dir": mod_dir,
                "profile": profile,
                "expected_dimensions": expected_dimensions,
                "game_target": game_target,
            }
        )
        return fake_report

    monkeypatch.setattr(verify_mod_mod.ModVerifier, "verify_report", _fake_verify_report)
    monkeypatch.setattr(verify_mod_mod.ModVerifier, "verify_quiet", _forbid_verify_quiet)

    worker = SimpleNamespace(profile=profile, dimensions=(30, 40), game_target=target)
    dialog, captured = _make_dialog(output_dir="some/mod/dir", worker=worker)
    dialog._on_export_done(SimpleNamespace(stats={}, fixed=[], warnings=[]))

    assert len(calls) == 1
    assert calls[0]["mod_dir"] == "some/mod/dir"
    assert calls[0]["profile"] is profile
    assert calls[0]["expected_dimensions"] == (30, 40)
    assert calls[0]["game_target"] is target
    assert captured["verify_errors"] == ["boom failure"]
    assert any("boom failure" in line for line in captured["lines"])
    assert any("careful warning" in line for line in captured["lines"])


def test_on_export_done_preserves_result_display(qapp, monkeypatch):
    from export import verify_mod as verify_mod_mod

    @classmethod
    def _ok_report(cls, mod_dir, **kwargs):
        return report_from_verifier_messages([], [])

    monkeypatch.setattr(verify_mod_mod.ModVerifier, "verify_report", _ok_report)
    monkeypatch.setattr(verify_mod_mod.ModVerifier, "verify_quiet", _forbid_verify_quiet)

    dialog, captured = _make_dialog()
    dialog._on_export_done(
        SimpleNamespace(
            stats={"provinces": 3, "states": 1, "countries": 1, "files": 2},
            fixed=["repaired terrain"],
            warnings=["plan note"],
        )
    )
    assert captured["verify_errors"] == []
    text = "\n".join(captured["lines"])
    assert "repaired terrain" in text
    assert "plan note" in text
    assert "3" in text

    @classmethod
    def _bad_report(cls, mod_dir, **kwargs):
        return report_from_verifier_messages(["bad thing"], [])

    monkeypatch.setattr(verify_mod_mod.ModVerifier, "verify_report", _bad_report)
    dialog2, captured2 = _make_dialog()
    dialog2._on_export_done(SimpleNamespace(stats={}, fixed=[], warnings=[]))
    assert captured2["verify_errors"] == ["bad thing"]
    assert any("bad thing" in line for line in captured2["lines"])


def _patch_worker_plan(monkeypatch, plan):
    import services.export_planner as planner_mod
    import services.export_service as service_mod
    import services.game_profile_service as profile_service_mod

    monkeypatch.setattr(profile_service_mod, "load_profile_for_target", lambda target: object())
    monkeypatch.setattr(planner_mod, "plan_export_from_project", lambda *args, **kwargs: plan)
    monkeypatch.setattr(planner_mod, "format_plan_summary", lambda plan_arg: "plan summary")
    monkeypatch.setattr(
        service_mod,
        "export_planned_mod",
        lambda plan_arg, output_dir, **kwargs: SimpleNamespace(written_files=["a.txt", "b.txt"]),
    )


def _run_worker(monkeypatch, findings):
    from views.export_dialog import ExportWorker

    province_map = np.zeros((4, 6), dtype=np.int32)
    province_map[0, 0] = 5
    snapshot = SimpleNamespace(
        province_map=province_map,
        state_mgr=SimpleNamespace(states={1: object(), 2: object()}),
        country_mgr=SimpleNamespace(countries={"AAA": object()}),
    )
    plan = SimpleNamespace(findings=list(findings), applied_repairs=[], snapshot=snapshot)
    _patch_worker_plan(monkeypatch, plan)
    project = SimpleNamespace(resolve_game_target=lambda: "fake-target")
    canvas = SimpleNamespace(province_map=np.zeros((8, 16), dtype=np.int32))
    worker = ExportWorker("fake/out", canvas, project)
    emitted = {}
    worker.finished.connect(lambda report: emitted.update(report=report))
    worker.failed.connect(lambda message: emitted.update(failed=message))
    worker.run()
    assert "failed" not in emitted, emitted.get("failed")
    return emitted["report"]


def test_export_worker_carries_shared_plan_report(qapp, monkeypatch):
    notes = [
        ValidationNote("export.test.warning", "warning", "plan warning one", layer="map"),
        ValidationNote("export.test.error", "error", "plan error one", layer="map"),
        ValidationNote("export.test.info", "info", "plan info one", layer="map"),
    ]
    report = _run_worker(monkeypatch, notes)
    assert isinstance(report.validation_report, ValidationReport)
    assert report.validation_report.to_dict() == report_from_findings(notes).to_dict()
    assert report.warnings == ["plan warning one", "plan error one"]
    assert report.stats == {"provinces": 5, "states": 2, "countries": 1, "files": 2}


def test_export_worker_empty_findings_yields_empty_report(qapp, monkeypatch):
    report = _run_worker(monkeypatch, [])
    assert isinstance(report.validation_report, ValidationReport)
    assert report.validation_report.total == 0
    assert report.warnings == []


def test_export_dialog_blocks_nonempty_destination_without_replacement_policy(
    qapp, monkeypatch, tmp_path
):
    from views import export_dialog as export_dialog_mod

    destination = tmp_path / "existing-mod"
    destination.mkdir()
    (destination / "keep.txt").write_text("keep", encoding="utf-8")

    dialog = export_dialog_mod.ExportDialog.__new__(export_dialog_mod.ExportDialog)
    dialog._scope_checks = {"compact_ids": SimpleNamespace(isChecked=lambda: True)}
    dialog._overwrite_check = SimpleNamespace(isChecked=lambda: False)
    dialog._backup_check = SimpleNamespace(isChecked=lambda: False)
    warning = {}

    monkeypatch.setattr(
        export_dialog_mod.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(destination),
    )
    monkeypatch.setattr(
        export_dialog_mod.QMessageBox,
        "warning",
        lambda *args, **kwargs: warning.update(title=args[1], text=args[2]),
    )

    dialog._do_export()

    assert warning["title"] == "Export Blocked"
    assert "not empty" in warning["text"]
    assert "_worker" not in vars(dialog)
