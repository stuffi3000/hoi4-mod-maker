"""M8 foundation-workflow widget tests (Qt offscreen, no game install)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit
pytest.importorskip("PyQt5.QtWidgets")


def test_is_foundation_profile():
    from views.foundation_workflow import is_foundation_profile

    assert is_foundation_profile("foundation") is True
    assert is_foundation_profile("legacy_full") is False
    assert is_foundation_profile("acceptance") is False
    assert is_foundation_profile("") is False
    assert is_foundation_profile(None) is False
    assert is_foundation_profile(" foundation ") is True


def test_default_paths_point_at_artifact_dir():
    from views.foundation_workflow import (
        default_acceptance_path,
        default_handoff_path,
        default_lock_path,
        default_manifest_path,
    )

    assert default_manifest_path("some/dir").replace("\\", "/").endswith(
        "some/dir/foundation_manifest.json"
    )
    assert default_lock_path("some/dir").replace("\\", "/").endswith(
        "some/dir/foundation.lock.json"
    )
    assert default_handoff_path("some/dir").replace("\\", "/").endswith(
        "some/dir/FOUNDATION-HANDOFF.md"
    )
    assert default_acceptance_path("some/dir").replace("\\", "/").endswith(
        "some/dir/engine_acceptance.json"
    )


def test_default_paths_empty_without_artifact():
    from views.foundation_workflow import (
        default_acceptance_path,
        default_handoff_path,
        default_lock_path,
        default_manifest_path,
    )

    assert default_manifest_path("") == ""
    assert default_lock_path(None) == ""
    assert default_handoff_path("   ") == ""
    assert default_acceptance_path("") == ""


def test_handoff_and_audit_for_lock():
    from views.foundation_workflow import audit_path_for_lock, handoff_path_for_lock

    assert handoff_path_for_lock("a/b/foundation.lock.json").replace(
        "\\", "/"
    ) == "a/b/FOUNDATION-HANDOFF.md"
    assert audit_path_for_lock("a/b/foundation.lock.json").replace(
        "\\", "/"
    ) == "a/b/foundation-freeze-audit.json"
    assert handoff_path_for_lock("") == ""
    assert audit_path_for_lock("") == ""


def test_format_compare_compatible():
    from views.foundation_workflow import format_compare_result

    text = format_compare_result(
        {
            "status": "compatible",
            "breaking": False,
            "differences": [],
            "lock_identity": "abc",
            "manifest_identity": "abc",
        }
    )
    assert "compatible" in text
    assert "abc" in text


def test_format_compare_lists_differences_and_rerun():
    from views.foundation_workflow import format_compare_result

    text = format_compare_result(
        {
            "status": "breaking",
            "breaking": True,
            "differences": [
                {
                    "path": "geography.province_max",
                    "change_class": "breaking_identity",
                    "breaking": True,
                    "summary": "Changed geography.province_max.",
                    "rerun": "Re-run full validation.",
                }
            ],
            "lock_identity": "old",
            "manifest_identity": "new",
        }
    )
    assert "geography.province_max" in text
    assert "breaking_identity" in text
    assert "Re-run full validation." in text


def test_format_operation_result():
    from views.foundation_workflow import format_operation_result

    text = format_operation_result(
        {"ok": False, "reasons": ["boom"], "lock_path": "x.lock"}, "Freeze foundation"
    )
    assert "ok=False" in text
    assert "boom" in text
    assert "x.lock" in text


def test_workflow_module_has_no_unsafe_imports():
    from pathlib import Path

    text = Path("views/foundation_workflow.py").read_text(encoding="utf-8")
    for banned in (
        "import subprocess",
        "import socket",
        "from socket",
        "import urllib",
        "from urllib",
        "shutil.rmtree",
        "os.remove",
        "Path.unlink",
        ".unlink(",
    ):
        assert banned not in text


@pytest.fixture(scope="module")
def qapp():
    qt_widgets = pytest.importorskip("PyQt5.QtWidgets")
    QApplication = qt_widgets.QApplication

    return QApplication.instance() or QApplication([])


def _make_widget(qapp, artifact_dir="", monkeypatch=None):
    from views import foundation_workflow as wf

    if monkeypatch is not None:
        monkeypatch.setattr(wf.QMessageBox, "information", lambda *a, **k: None)
        monkeypatch.setattr(wf.QMessageBox, "warning", lambda *a, **k: None)
    widget = wf.FoundationWorkflowWidget(artifact_dir=artifact_dir)
    return widget


def test_widget_syncs_defaults(qapp, monkeypatch):
    _make_widget(qapp, monkeypatch=monkeypatch)
    from views import foundation_workflow as wf

    monkeypatch.setattr(wf.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(wf.QMessageBox, "warning", lambda *a, **k: None)
    widget = wf.FoundationWorkflowWidget(artifact_dir="some/artifact")
    assert widget.manifest_path().replace("\\", "/").endswith(
        "some/artifact/foundation_manifest.json"
    )
    assert widget.lock_path().replace("\\", "/").endswith(
        "some/artifact/foundation.lock.json"
    )


def test_create_candidate_reports_success(qapp, monkeypatch):
    from views import foundation_workflow as wf

    monkeypatch.setattr(wf.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(wf.QMessageBox, "warning", lambda *a, **k: None)
    import services.foundation_freeze_service as svc

    calls = {}

    def _fake_candidate(manifest, lock, artifact_dir=None, **kwargs):
        calls["manifest"] = manifest
        calls["lock"] = lock
        calls["artifact"] = artifact_dir
        return {"ok": True, "reasons": [], "lock_path": lock, "identity_hash": "id1"}

    monkeypatch.setattr(svc, "create_candidate", _fake_candidate)
    widget = wf.FoundationWorkflowWidget(artifact_dir="some/artifact")
    widget._on_create_candidate()
    assert calls["manifest"].replace("\\", "/").endswith("foundation_manifest.json")
    assert calls["lock"].replace("\\", "/").endswith("foundation.lock.json")
    assert "ok=True" in widget._log.toPlainText()


def test_compare_displays_differences(qapp, monkeypatch):
    from views import foundation_workflow as wf

    monkeypatch.setattr(wf.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(wf.QMessageBox, "warning", lambda *a, **k: None)
    import services.foundation_freeze_service as svc

    def _fake_compare(manifest, lock, artifact_dir=None, acceptance_path=None):
        return {
            "status": "mismatch",
            "breaking": False,
            "differences": [
                {
                    "path": "outputs.map/definition.csv.hash",
                    "change_class": "breaking_identity",
                    "breaking": True,
                    "summary": "Changed outputs.map/definition.csv.hash.",
                    "rerun": "Check it.",
                }
            ],
            "lock_identity": "old",
            "manifest_identity": "new",
        }

    monkeypatch.setattr(svc, "compare_with_frozen_lock", _fake_compare)
    widget = wf.FoundationWorkflowWidget(artifact_dir="some/artifact")
    widget._on_compare()
    text = widget._log.toPlainText()
    assert "outputs.map/definition.csv.hash" in text
    assert "mismatch" in text


def test_unfreeze_requires_non_empty_reason(qapp, monkeypatch):
    from views import foundation_workflow as wf

    warned = {}
    monkeypatch.setattr(wf.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(
        wf.QMessageBox, "warning", lambda *a, **k: warned.update(called=True)
    )
    monkeypatch.setattr(
        wf.QInputDialog, "getText", lambda *a, **k: ("   ", True)
    )
    import services.foundation_freeze_service as svc

    def _forbid(*a, **k):
        raise AssertionError("service must not be called with empty reason")

    monkeypatch.setattr(svc, "unfreeze_lock", _forbid)
    widget = wf.FoundationWorkflowWidget(artifact_dir="some/artifact")
    widget._lock_edit.setText("some/artifact/foundation.lock.json")
    widget._on_unfreeze()
    assert warned.get("called") is True
    assert "reason is required" in widget._log.toPlainText().lower()


def test_unfreeze_success_records_audit(qapp, monkeypatch):
    from views import foundation_workflow as wf

    monkeypatch.setattr(wf.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(wf.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(wf.QInputDialog, "getText", lambda *a, **k: ("fix typo", True))
    import services.foundation_freeze_service as svc

    def _fake_unfreeze(lock_path, reason, audit_path=None, **kwargs):
        assert reason == "fix typo"
        return {
            "ok": True,
            "reasons": [],
            "lock_path": lock_path,
            "audit_path": "some/artifact/foundation-freeze-audit.json",
            "reason": reason,
        }

    monkeypatch.setattr(svc, "unfreeze_lock", _fake_unfreeze)
    widget = wf.FoundationWorkflowWidget(artifact_dir="some/artifact")
    widget._lock_edit.setText("some/artifact/foundation.lock.json")
    widget._on_unfreeze()
    assert "ok=True" in widget._log.toPlainText()
    assert "foundation-freeze-audit.json" in widget._log.toPlainText()
