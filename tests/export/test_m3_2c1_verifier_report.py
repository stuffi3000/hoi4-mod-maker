"""M3.2c1 artifact-verifier shared-report client tests (no game install)."""
from __future__ import annotations

import itertools
import json
import shutil
import struct
from pathlib import Path

import pytest

from domain.validation import ValidationReport
from export.verify_mod import ModVerifier
from services.validation_service import (
    ARTIFACT_ERROR_CODE,
    ARTIFACT_WARNING_CODE,
    report_from_verifier_messages,
)

pytestmark = pytest.mark.unit

_SCRATCH_ROOT = Path("tmp/m3-2c1-basetemp")
_CASE_COUNTER = itertools.count()


@pytest.fixture()
def scratch_dir():
    """Repo-local scratch directory (tmp_path needs os.chmod, which is blocked here)."""
    case = _SCRATCH_ROOT / f"case-{next(_CASE_COUNTER)}"
    case.mkdir(parents=True, exist_ok=True)
    yield case
    shutil.rmtree(case, ignore_errors=True)


def _write_minimal_bmp(path, width, height):
    row_bytes = width * 3
    padding = (4 - (row_bytes % 4)) % 4
    pixel_offset = 14 + 40
    with open(str(path), "wb") as handle:
        handle.write(b"BM")
        handle.write(struct.pack("<I", pixel_offset + (row_bytes + padding) * height))
        handle.write(struct.pack("<HH", 0, 0))
        handle.write(struct.pack("<I", pixel_offset))
        handle.write(struct.pack("<I", 40))
        handle.write(struct.pack("<i", width))
        handle.write(struct.pack("<i", height))
        handle.write(struct.pack("<HH", 1, 24))
        handle.write(struct.pack("<I", 0))
        handle.write(struct.pack("<I", (row_bytes + padding) * height))
        handle.write(struct.pack("<ii", 2835, 2835))
        handle.write(struct.pack("<II", 0, 0))
        row = bytes([1, 2, 3] * width)
        pad = b"\x00" * padding
        for _ in range(height):
            handle.write(row)
            if padding:
                handle.write(pad)


class _StubProfile:
    profile_id = "stub-profile"

    def __init__(self):
        self.seen = []

    def validate_dimensions(self, width, height):
        self.seen.append((width, height))
        return ["stub dimension failure"]


def test_verify_report_is_quiet_and_runs_checks_once(scratch_dir, capsys, monkeypatch):
    calls = []
    original = ModVerifier._run_all_checks

    def _counting(self):
        calls.append(1)
        return original(self)

    monkeypatch.setattr(ModVerifier, "_run_all_checks", _counting)
    report = ModVerifier.verify_report(str(scratch_dir))
    assert isinstance(report, ValidationReport)
    assert len(calls) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_verify_report_matches_verify_quiet_adapter(scratch_dir, capsys):
    errors, warnings = ModVerifier.verify_quiet(str(scratch_dir))
    assert isinstance(errors, list)
    assert isinstance(warnings, list)
    assert capsys.readouterr().out == ""
    error_snapshot = list(errors)
    warning_snapshot = list(warnings)
    report = ModVerifier.verify_report(str(scratch_dir))
    assert capsys.readouterr().out == ""
    assert report.source == "artifact"
    assert report.context == "draft_preview"
    assert report.error_count == len(errors)
    assert report.warning_count == len(warnings)
    assert report.to_dict() == report_from_verifier_messages(errors, warnings).to_dict()
    assert errors == error_snapshot
    assert warnings == warning_snapshot


def test_verify_quiet_and_verify_all_stay_compatible(scratch_dir, capsys):
    result = ModVerifier.verify_quiet(str(scratch_dir))
    assert type(result) is tuple
    assert len(result) == 2
    errors, warnings = result
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    ok = ModVerifier(str(scratch_dir), quiet=True).verify_all()
    out = capsys.readouterr().out
    assert ok == (len(errors) == 0)
    assert "Verifying mod" in out
    report = ModVerifier.verify_report(str(scratch_dir))
    assert (report.error_count == 0) == ok
    assert report.warning_count == len(warnings)


def test_verify_report_forwards_profile_dimensions_and_target(scratch_dir, monkeypatch):
    profile = object()
    target = object()
    seen = {}
    original = ModVerifier._run_all_checks

    def _spy(self):
        seen["profile"] = self.profile
        seen["expected_dimensions"] = self.expected_dimensions
        seen["game_target"] = self.game_target
        return original(self)

    monkeypatch.setattr(ModVerifier, "_run_all_checks", _spy)
    ModVerifier.verify_report(
        str(scratch_dir), profile=profile, expected_dimensions=(10, 20), game_target=target
    )
    assert seen["profile"] is profile
    assert seen["expected_dimensions"] == (10, 20)
    assert seen["game_target"] is target
    seen.clear()
    ModVerifier.verify_quiet(
        str(scratch_dir), profile=profile, expected_dimensions=(10, 20), game_target=target
    )
    assert seen["profile"] is profile
    assert seen["expected_dimensions"] == (10, 20)
    assert seen["game_target"] is target


def test_verify_report_consults_profile(scratch_dir):
    mod = scratch_dir / "mod"
    (mod / "map").mkdir(parents=True)
    _write_minimal_bmp(mod / "map" / "provinces.bmp", 8, 8)
    profile = _StubProfile()
    report = ModVerifier.verify_report(str(mod), profile=profile)
    assert profile.seen == [(8, 8)]
    assert any("stub dimension failure" in finding.message for finding in report.errors)
    errors, _warnings = ModVerifier.verify_quiet(str(mod), profile=profile)
    assert any("stub dimension failure" in message for message in errors)


def test_verify_report_context_source_and_gate(scratch_dir):
    report = ModVerifier.verify_report(str(scratch_dir), context="foundation_candidate")
    assert report.source == "artifact"
    assert report.context == "foundation_candidate"
    assert report.error_count > 0
    assert report.evaluate().allowed is False
    assert report.evaluate("draft_preview").allowed is True
    with pytest.raises(ValueError):
        ModVerifier.verify_report(str(scratch_dir), context="no_such_gate")


def test_verify_report_codes_order_and_serialization(scratch_dir):
    first = ModVerifier.verify_report(str(scratch_dir))
    assert first.total == first.error_count + first.warning_count
    assert [finding.severity for finding in first.findings] == (
        ["error"] * first.error_count + ["warning"] * first.warning_count
    )
    assert {finding.code for finding in first.findings} <= {
        ARTIFACT_ERROR_CODE,
        ARTIFACT_WARNING_CODE,
    }
    assert all(finding.layer == "artifact" for finding in first.findings)
    payload = first.to_dict()
    assert json.dumps(payload)
    assert ModVerifier.verify_report(str(scratch_dir)).to_dict() == payload
    assert ValidationReport.from_dict(payload).to_dict() == payload
    for entry in payload["findings"]:
        assert "C:" not in entry["path"]
        assert not entry["path"].startswith("/")
        assert ".." not in entry["path"]


def test_to_report_reuses_collected_messages_without_rerun(scratch_dir, monkeypatch):
    calls = []
    original = ModVerifier._run_all_checks

    def _counting(self):
        calls.append(1)
        return original(self)

    monkeypatch.setattr(ModVerifier, "_run_all_checks", _counting)
    verifier = ModVerifier(str(scratch_dir), quiet=True)
    verifier._run_all_checks()
    assert len(calls) == 1
    report = verifier.to_report()
    assert len(calls) == 1
    assert isinstance(report, ValidationReport)
    assert report.error_count == len(verifier.errors)
    assert report.warning_count == len(verifier.warnings)
