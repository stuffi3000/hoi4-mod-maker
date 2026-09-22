"""Regression tests for ExportDialog background-worker lifecycle."""
from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
from PyQt5.QtCore import QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import QDialog


class _SlowPreflightWorker(QThread):
    readiness_ready = pyqtSignal(object)
    completed = pyqtSignal(object, object, str)
    failed = pyqtSignal(str)

    def run(self) -> None:
        # Simulate the part of the Belgium preflight that cannot stop
        # immediately after requestInterruption() is received.
        time.sleep(0.25)


def _make_dialog_shell() -> object:
    from views.export_dialog import ExportDialog

    dialog = ExportDialog.__new__(ExportDialog)
    QDialog.__init__(dialog)
    dialog._preflight_worker = None
    dialog._preflight_request = 0
    dialog._preflight_pending = False
    dialog._closing = False
    dialog._check_timer = QTimer(dialog)
    return dialog


def test_reject_does_not_wait_for_running_preflight_worker(qtbot) -> None:
    dialog = _make_dialog_shell()
    qtbot.addWidget(dialog)

    worker = _SlowPreflightWorker(dialog)
    dialog._preflight_worker = worker
    worker.finished.connect(
        lambda w=worker: dialog._on_preflight_thread_finished(w)
    )

    worker.start()
    dialog.show()
    QTimer.singleShot(0, dialog.reject)
    started = time.perf_counter()
    result = dialog.exec_()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.15
    assert result == QDialog.Rejected
    assert dialog._preflight_worker is None
    assert not dialog.isVisible()

    from views import export_dialog as export_dialog_module

    qtbot.waitUntil(
        lambda: worker not in export_dialog_module._DETACHED_PREFLIGHT_WORKERS,
        timeout=2000,
    )


def test_preflight_worker_reuses_cached_readiness(qtbot, monkeypatch) -> None:
    from services import export_planner, game_profile_service
    from views import export_dialog as export_dialog_module

    readiness_calls = []
    readiness_item = object()
    completed = []
    readiness_emissions = []

    monkeypatch.setattr(
        export_dialog_module,
        "check_project_readiness",
        lambda *args, **kwargs: readiness_calls.append(True),
    )
    monkeypatch.setattr(
        game_profile_service,
        "load_profile_for_target",
        lambda _target: object(),
    )
    monkeypatch.setattr(
        export_planner,
        "plan_export_from_project",
        lambda *args, **kwargs: SimpleNamespace(blockers=["cached blocker"]),
    )
    monkeypatch.setattr(
        export_planner,
        "format_plan_summary",
        lambda _plan: "cached plan summary",
    )

    project = SimpleNamespace(resolve_game_target=lambda: "target")
    canvas = SimpleNamespace(province_map=np.zeros((2, 3), dtype=np.uint8))
    worker = export_dialog_module.PreflightWorker(
        project,
        canvas,
        profile_name="scaffold",
        repair_policy="apply-safe",
        scope={},
        readiness_items=[readiness_item],
    )
    worker.readiness_ready.connect(readiness_emissions.append)
    worker.completed.connect(
        lambda items, plan, summary: completed.append((items, plan, summary))
    )

    worker.run()

    assert readiness_calls == []
    assert readiness_emissions == []
    assert completed[0][0] == [readiness_item]
    assert completed[0][2] == "cached plan summary"
