"""Foundation-freeze workflow controls (M8).

Reusable Qt surface for the existing foundation-freeze backend. Safe by
design: uses explicit user-selected paths, the backend service only, and
standard Qt file/input/message dialogs. No subprocess, no network, no file
deletion, and no direct map mutation. Export semantics are unchanged.
"""
from __future__ import annotations

from pathlib import Path

from domain import foundation_freeze as freeze_contract

from PyQt5.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


def is_foundation_profile(profile_name: object) -> bool:
    return str(profile_name or "").strip() == "foundation"


def _clean_dir(value: object) -> str:
    try:
        text = str(value or "").strip()
    except Exception:
        return ""
    return text


def default_manifest_path(artifact_dir: object) -> str:
    base = _clean_dir(artifact_dir)
    if not base:
        return ""
    return str(Path(base) / freeze_contract.MANIFEST_FILENAME)


def default_lock_path(artifact_dir: object) -> str:
    base = _clean_dir(artifact_dir)
    if not base:
        return ""
    return str(Path(base) / freeze_contract.LOCK_FILENAME)


def default_handoff_path(artifact_dir: object) -> str:
    base = _clean_dir(artifact_dir)
    if not base:
        return ""
    return str(Path(base) / freeze_contract.HANDOFF_FILENAME)


def default_acceptance_path(artifact_dir: object) -> str:
    base = _clean_dir(artifact_dir)
    if not base:
        return ""
    return str(Path(base) / freeze_contract.ACCEPTANCE_FILENAME)


def handoff_path_for_lock(lock_path: object) -> str:
    try:
        text = str(lock_path or "").strip()
    except Exception:
        return ""
    if not text:
        return ""
    parent = Path(text).parent
    if str(parent) in ("", "."):
        return str(Path(freeze_contract.HANDOFF_FILENAME))
    return str(parent / freeze_contract.HANDOFF_FILENAME)


def audit_path_for_lock(lock_path: object) -> str:
    try:
        text = str(lock_path or "").strip()
    except Exception:
        return ""
    if not text:
        return ""
    parent = Path(text).parent
    if str(parent) in ("", "."):
        return str(Path(freeze_contract.AUDIT_FILENAME))
    return str(parent / freeze_contract.AUDIT_FILENAME)


def format_compare_result(result: object) -> str:
    if not isinstance(result, dict):
        return "Compare produced no result."
    lines: list[str] = []
    lines.append(
        "status: %s breaking=%s differences=%d"
        % (
            str(result.get("status", "?")),
            bool(result.get("breaking", False)),
            len(result.get("differences", []) or []),
        )
    )
    if str(result.get("lock_identity", "")):
        lines.append("lock_identity: %s" % str(result.get("lock_identity", "")))
    if str(result.get("manifest_identity", "")):
        lines.append("manifest_identity: %s" % str(result.get("manifest_identity", "")))
    for entry in result.get("differences", []) or []:
        if not isinstance(entry, dict):
            continue
        lines.append(
            "%s [%s breaking=%s] %s"
            % (
                str(entry.get("path", "?")),
                str(entry.get("change_class", "?")),
                bool(entry.get("breaking", False)),
                str(entry.get("summary", "")),
            )
        )
        if str(entry.get("rerun", "")):
            lines.append("  rerun: %s" % str(entry.get("rerun", "")))
    if len(lines) == 1:
        lines.append("No differences: manifest matches the frozen lock.")
    return "\n".join(lines)


def format_operation_result(result: object, kind: str) -> str:
    if not isinstance(result, dict):
        return "%s produced no result." % str(kind)
    lines: list[str] = []
    lines.append("%s ok=%s" % (str(kind), bool(result.get("ok", False))))
    if str(result.get("lock_path", "")):
        lines.append("lock: %s" % str(result.get("lock_path", "")))
    if str(result.get("handoff_path", "")):
        lines.append("handoff: %s" % str(result.get("handoff_path", "")))
    if str(result.get("audit_path", "")):
        lines.append("audit: %s" % str(result.get("audit_path", "")))
    if str(result.get("identity_hash", "")):
        lines.append("identity: %s" % str(result.get("identity_hash", "")))
    if str(result.get("reason", "")):
        lines.append("reason: %s" % str(result.get("reason", "")))
    if str(result.get("run_id", "")):
        lines.append("run: %s" % str(result.get("run_id", "")))
    for reason in result.get("reasons", []) or []:
        lines.append("reason: %s" % str(reason))
    return "\n".join(lines)


class FoundationWorkflowWidget(QGroupBox):
    def __init__(self, artifact_dir: str = "", parent=None) -> None:
        super().__init__("Foundation freeze workflow", parent)
        self._artifact_edit = QLineEdit(self)
        self._manifest_edit = QLineEdit(self)
        self._lock_edit = QLineEdit(self)
        self._acceptance_edit = QLineEdit(self)
        self._handoff_edit = QLineEdit(self)
        self._log = QTextEdit(self)
        self._btn_candidate = QPushButton("Create candidate", self)
        self._btn_freeze = QPushButton("Freeze foundation", self)
        self._btn_accept = QPushButton("Record engine acceptance", self)
        self._btn_compare = QPushButton("Compare with frozen", self)
        self._btn_unfreeze = QPushButton("Unfreeze...", self)
        self._btn_handoff = QPushButton("Generate handoff", self)
        self._build_ui()
        if _clean_dir(artifact_dir):
            self.set_artifact_dir(str(artifact_dir))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        info = QLabel(
            "Uses explicit manifest/lock paths. Defaults point at the "
            "selected artifact directory. No map data is changed."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        self._artifact_edit.setPlaceholderText("Artifact directory (export output)")
        self._manifest_edit.setPlaceholderText(default_manifest_path("<artifact>"))
        self._lock_edit.setPlaceholderText(default_lock_path("<artifact>"))
        self._acceptance_edit.setPlaceholderText("Optional engine_acceptance.json (optional)")
        self._handoff_edit.setPlaceholderText("Optional FOUNDATION-HANDOFF.md output (optional)")
        for label_text, edit, browse_slot in (
            ("Artifact dir:", self._artifact_edit, self._browse_artifact_dir),
            ("Manifest:", self._manifest_edit, self._browse_manifest),
            ("Lock:", self._lock_edit, self._browse_lock),
            ("Acceptance (optional):", self._acceptance_edit, self._browse_acceptance),
            ("Handoff output (optional):", self._handoff_edit, self._browse_handoff),
        ):
            row = QHBoxLayout()
            label = QLabel(label_text, self)
            label.setMinimumWidth(140)
            row.addWidget(label)
            row.addWidget(edit, 1)
            browse = QPushButton("Browse...", self)
            browse.clicked.connect(browse_slot)
            row.addWidget(browse)
            layout.addLayout(row)
        row_one = QHBoxLayout()
        row_one.addWidget(self._btn_candidate)
        row_one.addWidget(self._btn_freeze)
        row_one.addWidget(self._btn_compare)
        layout.addLayout(row_one)
        row_two = QHBoxLayout()
        row_two.addWidget(self._btn_accept)
        row_two.addWidget(self._btn_unfreeze)
        row_two.addWidget(self._btn_handoff)
        layout.addLayout(row_two)
        self._btn_candidate.clicked.connect(self._on_create_candidate)
        self._btn_freeze.clicked.connect(self._on_freeze)
        self._btn_accept.clicked.connect(self._on_record_acceptance)
        self._btn_compare.clicked.connect(self._on_compare)
        self._btn_unfreeze.clicked.connect(self._on_unfreeze)
        self._btn_handoff.clicked.connect(self._on_generate_handoff)
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(110)
        self._log.setPlaceholderText("Workflow results appear here.")
        layout.addWidget(self._log)

    def set_artifact_dir(self, artifact_dir: str) -> None:
        self._artifact_edit.setText(_clean_dir(artifact_dir))
        self._sync_defaults()

    def artifact_dir(self) -> str:
        return self._artifact_edit.text().strip()

    def manifest_path(self) -> str:
        return self._manifest_edit.text().strip()

    def lock_path(self) -> str:
        return self._lock_edit.text().strip()

    def _sync_defaults(self) -> None:
        artifact = self._artifact_edit.text().strip()
        if not artifact:
            return
        if not self._manifest_edit.text().strip():
            self._manifest_edit.setText(default_manifest_path(artifact))
        if not self._lock_edit.text().strip():
            self._lock_edit.setText(default_lock_path(artifact))
        if not self._handoff_edit.text().strip():
            self._handoff_edit.setText(default_handoff_path(artifact))

    def _append_log(self, text: str) -> None:
        try:
            self._log.append(str(text))
        except Exception:
            try:
                self._log.setPlainText(
                    "%s\n%s" % (str(self._log.toPlainText()), str(text))
                )
            except Exception:
                pass

    def _report(self, ok: bool, title: str, detail: str) -> None:
        self._append_log(detail)
        try:
            if ok:
                QMessageBox.information(self, title, detail)
            else:
                QMessageBox.warning(self, title, detail)
        except Exception:
            pass

    def _browse_artifact_dir(self) -> None:
        start = self._artifact_edit.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self, "Select foundation artifact directory", start
        )
        if selected:
            self._artifact_edit.setText(selected)
            self._sync_defaults()

    def _browse_manifest(self) -> None:
        self._sync_defaults()
        start = self._manifest_edit.text().strip() or self._artifact_edit.text().strip()
        path, _ = QFileDialog.getOpenFileName(
            self, "Select foundation_manifest.json", start, "JSON (*.json)"
        )
        if path:
            self._manifest_edit.setText(path)

    def _browse_lock(self) -> None:
        self._sync_defaults()
        start = self._lock_edit.text().strip() or self._artifact_edit.text().strip()
        path, _ = QFileDialog.getSaveFileName(
            self, "Select foundation.lock.json", start, "JSON (*.json)"
        )
        if path:
            self._lock_edit.setText(path)

    def _browse_acceptance(self) -> None:
        start = (
            self._acceptance_edit.text().strip()
            or default_acceptance_path(self._artifact_edit.text().strip())
            or self._artifact_edit.text().strip()
        )
        path, _ = QFileDialog.getOpenFileName(
            self, "Select engine_acceptance.json", start, "JSON (*.json)"
        )
        if path:
            self._acceptance_edit.setText(path)

    def _browse_handoff(self) -> None:
        self._sync_defaults()
        start = (
            self._handoff_edit.text().strip()
            or default_handoff_path(self._artifact_edit.text().strip())
            or self._artifact_edit.text().strip()
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Select FOUNDATION-HANDOFF.md output", start, "Markdown (*.md)"
        )
        if path:
            self._handoff_edit.setText(path)

    def _resolve_manifest(self, require_existing: bool = True) -> str:
        self._sync_defaults()
        path = self._manifest_edit.text().strip()
        if not path:
            artifact = self._artifact_edit.text().strip()
            if artifact:
                path = default_manifest_path(artifact)
                self._manifest_edit.setText(path)
        if not path:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select foundation_manifest.json",
                self._artifact_edit.text().strip(),
                "JSON (*.json)",
            )
            if selected:
                self._manifest_edit.setText(selected)
                path = selected
        return path.strip()

    def _resolve_lock(self, for_save: bool = False) -> str:
        self._sync_defaults()
        path = self._lock_edit.text().strip()
        if not path:
            artifact = self._artifact_edit.text().strip()
            if artifact:
                path = default_lock_path(artifact)
                self._lock_edit.setText(path)
        if not path:
            start = self._artifact_edit.text().strip()
            if for_save:
                selected, _ = QFileDialog.getSaveFileName(
                    self, "Select foundation.lock.json", start, "JSON (*.json)"
                )
            else:
                selected, _ = QFileDialog.getOpenFileName(
                    self, "Select foundation.lock.json", start, "JSON (*.json)"
                )
            if selected:
                self._lock_edit.setText(selected)
                path = selected
        return path.strip()

    def _resolve_artifact(self, manifest_path: str = "") -> str:
        artifact = self._artifact_edit.text().strip()
        if artifact:
            return artifact
        if manifest_path:
            try:
                return str(Path(manifest_path).parent)
            except Exception:
                return ""
        return ""

    def _on_create_candidate(self) -> None:
        from services import foundation_freeze_service as freeze_service

        manifest = self._resolve_manifest()
        if not manifest:
            self._report(False, "Create candidate", "Select a foundation_manifest.json first.")
            return
        lock = self._resolve_lock(for_save=True)
        if not lock:
            self._report(False, "Create candidate", "Select a foundation.lock.json output first.")
            return
        artifact = self._resolve_artifact(manifest) or None
        try:
            result = freeze_service.create_candidate(manifest, lock, artifact_dir=artifact)
        except Exception as exc:
            detail = "Create candidate failed: %s" % exc
            self._report(False, "Create candidate", detail)
            return
        detail = format_operation_result(result, "Create candidate")
        self._report(bool(result.get("ok")), "Create candidate", detail)

    def _on_freeze(self) -> None:
        from services import foundation_freeze_service as freeze_service

        manifest = self._resolve_manifest()
        if not manifest:
            self._report(False, "Freeze foundation", "Select a foundation_manifest.json first.")
            return
        lock = self._resolve_lock(for_save=True)
        if not lock:
            self._report(False, "Freeze foundation", "Select a foundation.lock.json first.")
            return
        artifact = self._resolve_artifact(manifest) or None
        acceptance = self._acceptance_edit.text().strip() or None
        handoff = self._handoff_edit.text().strip() or None
        try:
            result = freeze_service.freeze_foundation(
                manifest,
                lock,
                artifact_dir=artifact,
                acceptance_path=acceptance,
                handoff_path=handoff,
            )
        except Exception as exc:
            self._report(False, "Freeze foundation", "Freeze failed: %s" % exc)
            return
        detail = format_operation_result(result, "Freeze foundation")
        self._report(bool(result.get("ok")), "Freeze foundation", detail)

    def _on_record_acceptance(self) -> None:
        from services import foundation_freeze_service as freeze_service

        lock = self._resolve_lock()
        if not lock:
            self._report(False, "Record acceptance", "Select a frozen foundation.lock.json first.")
            return
        manifest = self._resolve_manifest()
        if not manifest:
            self._report(False, "Record acceptance", "Select a foundation_manifest.json first.")
            return
        acceptance = self._acceptance_edit.text().strip()
        if not acceptance:
            start = (
                default_acceptance_path(self._artifact_edit.text().strip())
                or self._artifact_edit.text().strip()
            )
            selected, _ = QFileDialog.getOpenFileName(
                self, "Select engine_acceptance.json", start, "JSON (*.json)"
            )
            if not selected:
                self._report(False, "Record acceptance", "Select an engine_acceptance.json first.")
                return
            self._acceptance_edit.setText(selected)
            acceptance = selected
        handoff = self._handoff_edit.text().strip() or None
        try:
            result = freeze_service.record_engine_acceptance(
                lock, manifest, acceptance, handoff_path=handoff
            )
        except Exception as exc:
            self._report(False, "Record acceptance", "Record acceptance failed: %s" % exc)
            return
        detail = format_operation_result(result, "Record acceptance")
        self._report(bool(result.get("ok")), "Record acceptance", detail)

    def _on_compare(self) -> None:
        from services import foundation_freeze_service as freeze_service

        manifest = self._resolve_manifest()
        if not manifest:
            self._report(False, "Compare", "Select a foundation_manifest.json first.")
            return
        lock = self._resolve_lock()
        if not lock:
            self._report(False, "Compare", "Select a frozen foundation.lock.json first.")
            return
        artifact = self._resolve_artifact(manifest) or None
        acceptance = self._acceptance_edit.text().strip() or None
        try:
            result = freeze_service.compare_with_frozen_lock(
                manifest, lock, artifact_dir=artifact, acceptance_path=acceptance
            )
        except Exception as exc:
            self._report(False, "Compare", "Compare failed: %s" % exc)
            return
        detail = format_compare_result(result)
        self._append_log(detail)
        try:
            QMessageBox.information(self, "Compare", detail[:2000])
        except Exception:
            pass

    def _on_unfreeze(self) -> None:
        from services import foundation_freeze_service as freeze_service

        lock = self._resolve_lock()
        if not lock:
            self._report(False, "Unfreeze", "Select a frozen foundation.lock.json first.")
            return
        reason, accepted = QInputDialog.getText(
            self, "Unfreeze reason", "Reason (required):"
        )
        if not accepted:
            return
        reason = str(reason or "").strip()
        if not reason:
            try:
                QMessageBox.warning(self, "Unfreeze", "Unfreeze requires a non-empty reason.")
            except Exception:
                pass
            self._append_log("Unfreeze cancelled: reason is required.")
            return
        try:
            result = freeze_service.unfreeze_lock(lock, reason)
        except Exception as exc:
            self._report(False, "Unfreeze", "Unfreeze failed: %s" % exc)
            return
        detail = format_operation_result(result, "Unfreeze")
        self._report(bool(result.get("ok")), "Unfreeze", detail)

    def _on_generate_handoff(self) -> None:
        from services import foundation_freeze_service as freeze_service

        lock = self._resolve_lock()
        if not lock:
            self._report(False, "Generate handoff", "Select a foundation.lock.json first.")
            return
        manifest_text = self._manifest_edit.text().strip()
        output = self._handoff_edit.text().strip()
        if not output:
            output = handoff_path_for_lock(lock) or default_handoff_path(
                self._artifact_edit.text().strip()
            )
        if not output:
            selected, _ = QFileDialog.getSaveFileName(
                self,
                "Select FOUNDATION-HANDOFF.md output",
                self._artifact_edit.text().strip(),
                "Markdown (*.md)",
            )
            if not selected:
                self._report(False, "Generate handoff", "Select a handoff output path first.")
                return
            self._handoff_edit.setText(selected)
            output = selected
        try:
            lock_data = freeze_service.load_lock(lock)
        except Exception as exc:
            self._report(False, "Generate handoff", "Cannot read lock: %s" % exc)
            return
        manifest_data = None
        if manifest_text:
            try:
                manifest_data = freeze_service.load_manifest(manifest_text)
            except Exception as exc:
                self._report(False, "Generate handoff", "Cannot read manifest: %s" % exc)
                return
        try:
            text = freeze_service.generate_handoff(lock_data, manifest_data)
        except Exception as exc:
            self._report(False, "Generate handoff", "Generate handoff failed: %s" % exc)
            return
        try:
            destination = Path(output)
            if str(destination.parent) not in ("", "."):
                destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        except Exception as exc:
            self._report(False, "Generate handoff", "Cannot write handoff: %s" % exc)
            return
        detail = "Generate handoff ok=True\noutput: %s" % str(destination)
        self._report(True, "Generate handoff", detail)
