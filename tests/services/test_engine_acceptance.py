"""Focused M7 assisted engine-acceptance harness tests."""
from __future__ import annotations

import importlib.util
import itertools
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from domain import engine_acceptance as contract
from services import engine_acceptance_service as harness

pytestmark = pytest.mark.unit

_SCRATCH_COUNTER = itertools.count()


@pytest.fixture
def scratch_dir():
    """Provide an isolated scratch directory without mode-restricted creation.

    The sandbox Python applies owner-only ACLs to mode 0o700 directories
    (tempfile.mkdtemp and pytest tmp_path), which blocks child creation, so
    this fixture uses plain creation with default permissions instead.
    """
    parent = Path(tempfile.gettempdir())
    candidate = parent / ("m7_acceptance_%d_%d" % (os.getpid(), next(_SCRATCH_COUNTER)))
    candidate.mkdir(parents=False, exist_ok=False)
    yield candidate
    shutil.rmtree(candidate, ignore_errors=True)


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_artifact(root: Path, manifest_identity: str = "manifest-hash", lock_identity: str = "manifest-hash") -> Path:
    _write_text(root / "map" / "definition.csv", "0;0;0;0;land;false;none;0\n")
    _write_text(root / "descriptor.mod", 'name="Acceptance Probe"\n')
    manifest = {
        "profile": "acceptance",
        "identity": {"identity_hash": manifest_identity},
        "target": {"identity": {"game": "hoi4", "version": "1.19.1"}},
    }
    _write_text(root / "foundation_manifest.json", json.dumps(manifest))
    lock = {"identity": {"identity_hash": lock_identity}}
    _write_text(root / "foundation.lock.json", json.dumps(lock))
    return root


def test_log_snapshot_ignores_old_content(scratch_dir):
    """Only bytes appended after the snapshot are classified as evidence."""
    log_path = _write_text(scratch_dir / "error.log", "[ERROR] province 7 has no pixels in definition.csv\n")
    snapshot = harness.snapshot_log_file(log_path)
    assert snapshot["status"] == "snapshotted"
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write("[ERROR] Could not load map/terrain/colormap_test.dds\n")
        handle.write("plain progress line\n")
    collected = harness.collect_fresh_findings([snapshot])
    assert len(collected["findings"]) == 1
    finding = collected["findings"][0]
    assert finding["category"] == "asset"
    assert finding["severity"] == "error"
    assert "province 7" not in finding["text"]


def test_log_classification_covers_all_categories():
    """Every M7.3 category is reachable through deterministic rules."""
    cases = [
        ("[ERROR] province 12 has no pixels in definition.csv", "map"),
        ("Error: Could not load map/terrain/colormap_rgb_cityemissivemask_a.dds", "asset"),
        ("Error: unexpected token in common/bookmarks/99_acceptance.txt", "script"),
        ("Error: invalid tag QQA in history/countries/QQA - Acceptance Test.txt", "country_tag"),
        ("Error: FMOD failed to load sound bank music.bank", "audio_unrelated"),
        ("Error: something completely unrecognized happened here", "unknown"),
    ]
    for line, expected in cases:
        assert contract.classify_line(line) == ("error", expected)


def test_audio_errors_never_block_but_unknown_errors_do():
    """Unrelated audio failures stay clean while unknown errors stay blockers."""
    audio = contract.LogFinding(source="error.log", line_number=1, category="audio_unrelated", severity="error", text="sound")
    unknown = contract.LogFinding(source="error.log", line_number=2, category="unknown", severity="error", text="weird")
    clean_summary = harness.summarize_findings([audio.to_dict()])
    assert clean_summary["verdict"] == "clean"
    assert clean_summary["blocker_count"] == 0
    blocked_summary = harness.summarize_findings([audio.to_dict(), unknown.to_dict()])
    assert blocked_summary["verdict"] == "failed"
    assert blocked_summary["blocker_count"] == 1


def test_missing_logs_recorded_explicitly(scratch_dir):
    """Absent log files produce a missing status instead of silent success."""
    missing_path = scratch_dir / "absent.log"
    snapshot = harness.snapshot_log_file(missing_path)
    assert snapshot["status"] == "missing"
    assert snapshot["exists"] is False
    collected = harness.collect_fresh_findings([snapshot])
    assert collected["findings"] == []
    assert collected["files"][0]["status"] == "missing"


def test_snapshot_archive_copies_without_modifying(scratch_dir):
    """Archiving copies pre-run bytes aside while the live log stays intact."""
    log_path = _write_text(scratch_dir / "error.log", "[ERROR] stale province line\n")
    archive = scratch_dir / "archive"
    before = log_path.stat().st_size
    snapshot = harness.snapshot_log_file(log_path, archive_dir=archive)
    assert snapshot["status"] == "snapshotted"
    assert log_path.stat().st_size == before
    archived = Path(snapshot["archived_to"])
    assert archived.is_file()
    assert archived.read_text(encoding="utf-8") == "[ERROR] stale province line\n"


def test_save_freshness_reports_fresh_stale_and_missing(scratch_dir):
    """Saves are fresh only when written at or after the snapshot instant."""
    save_dir = scratch_dir / "saves"
    save_dir.mkdir()
    candidate = _write_text(save_dir / "acceptance_save.hoi4", "save-bytes")
    moment_ns = candidate.stat().st_mtime_ns
    fresh = harness.detect_expected_saves(save_dir, ["acceptance_save.hoi4"], snapshot_ns=moment_ns - 1_000_000_000)
    assert fresh[0]["status"] == "fresh"
    assert len(fresh[0]["sha256"]) == 64
    stale = harness.detect_expected_saves(save_dir, ["acceptance_save.hoi4"], snapshot_ns=moment_ns + 1_000_000_000)
    assert stale[0]["status"] == "stale"
    assert stale[0]["sha256"] == ""
    missing = harness.detect_expected_saves(save_dir, ["nope.hoi4"], snapshot_ns=moment_ns)
    assert missing[0]["status"] == "missing"


def test_save_detection_without_directory_is_explicit(scratch_dir):
    """Expected saves without a save directory are reported, not invented."""
    evidence = harness.detect_expected_saves(None, ["acceptance_save.hoi4"], snapshot_ns=0)
    assert evidence[0]["status"] == "not_configured"


def test_run_identity_ignores_timestamps(scratch_dir):
    """Identical artifacts and metadata share a run id across timestamps."""
    artifact = _make_artifact(scratch_dir / "artifact")
    first = harness.run_harness(artifact, target="steam", profile="acceptance", game_version="1.19.1", created_at="2026-01-01T00:00:00+00:00")
    second = harness.run_harness(artifact, target="steam", profile="acceptance", game_version="1.19.1", created_at="2026-06-01T00:00:00+00:00")
    assert first["run_id"] == second["run_id"]
    assert first["identity_hash"] == second["identity_hash"]
    assert len(first["run_id"]) == 16
    other = _make_artifact(scratch_dir / "other")
    _write_text(other / "extra.txt", "different")
    third = harness.run_harness(other, target="steam", profile="acceptance", game_version="1.19.1")
    assert third["run_id"] != first["run_id"]


def test_dry_run_records_launch_without_executing(scratch_dir):
    """The default mode records the exact argv list and never launches."""
    artifact = _make_artifact(scratch_dir / "artifact")
    config = harness.build_launch_config(executable="hoi4.exe", args=("--mod", "acceptance"), cwd="C:/games", timeout_seconds=60.0)
    assert config.argv() == ["hoi4.exe", "--mod", "acceptance"]
    result = harness.run_harness(artifact, launch_config=config)
    assert result["mode"] == "dry_run"
    assert result["status"] == "dry_run"
    assert result["launch"]["executed"] is False
    assert result["launch"]["argv"] == ["hoi4.exe", "--mod", "acceptance"]


def test_launch_config_validates_input():
    """Negative timeouts are rejected before anything is recorded."""
    with pytest.raises(ValueError):
        harness.build_launch_config(executable="hoi4.exe", timeout_seconds=-1.0)


def test_execute_launch_captures_bounded_output():
    """Explicit execution runs without a shell and bounds captured streams."""
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", "print('acceptance-probe')"), timeout_seconds=30.0)
    outcome = harness.execute_launch(config, env_values={}, capture_limit=64)
    assert outcome["executed"] is True
    assert outcome["status"] == "exited"
    assert outcome["returncode"] == 0
    assert "acceptance-probe" in outcome["stdout"]
    loud = contract.LaunchConfig(executable=sys.executable, args=("-c", "import sys; sys.stdout.write('y' * 1000)"), timeout_seconds=30.0)
    bounded = harness.execute_launch(loud, env_values={}, capture_limit=10)
    assert bounded["stdout"] == "y" * 10
    assert bounded["stdout_truncated"] is True


def test_execute_launch_rejects_bad_capture_limit():
    """Non-positive capture bounds are rejected before any execution."""
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", "print(1)"))
    with pytest.raises(ValueError):
        harness.execute_launch(config, env_values={}, capture_limit=0)


def test_checklist_gating_prevents_pass(scratch_dir):
    """Unchecked required checks and missing saves block an accepted result."""
    artifact = _make_artifact(scratch_dir / "artifact")
    probe = contract.LaunchConfig(executable=sys.executable, args=("-c", "pass"), timeout_seconds=30.0)
    partial = harness.run_harness(artifact, launch_config=probe, execute=True, checked=["main_menu"])
    assert partial["mode"] == "assisted"
    assert partial["status"] == "incomplete"
    assert "bookmark_map" in partial["checklist_summary"]["missing"]
    complete = harness.run_harness(artifact, launch_config=probe, execute=True, checked=list(contract.REQUIRED_CHECK_IDS))
    assert complete["status"] == "passed"


def test_blocker_log_errors_fail_assisted_run(scratch_dir):
    """Fresh blocker errors fail the run instead of passing silently."""
    artifact = _make_artifact(scratch_dir / "artifact")
    log_path = _write_text(scratch_dir / "error.log", "clean start\n")
    snapshot = harness.snapshot_log_file(log_path)
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write("[ERROR] province 3 has no pixels in definition.csv\n")
    fresh = harness.collect_fresh_findings([snapshot])
    summary = harness.summarize_findings(fresh["findings"])
    assert summary["blocker_count"] == 1
    status, _reasons = contract.decide_status(mode="assisted", artifact_ok=True, blocker_errors=1, unchecked_required=[])
    assert status == "failed"


def test_artifact_mismatch_and_missing_block(scratch_dir):
    """Identity mismatches and missing directories block acceptance."""
    artifact = _make_artifact(scratch_dir / "artifact")
    mismatched = harness.run_harness(artifact, execute=True, checked=list(contract.REQUIRED_CHECK_IDS), expected_identity_hash="different-hash")
    assert mismatched["status"] == "blocked"
    assert mismatched["artifact"]["mismatch"][0]["field"] == "manifest_identity"
    absent = harness.run_harness(scratch_dir / "does-not-exist", execute=True, checked=list(contract.REQUIRED_CHECK_IDS))
    assert absent["status"] == "blocked"
    assert absent["artifact"]["status"] == "missing"


def test_artifact_requires_readable_manifest_identity(scratch_dir):
    """A bare or malformed directory cannot become an accepted artifact."""
    bare = scratch_dir / "bare"
    _write_text(bare / "descriptor.mod", 'name="Acceptance Probe"\n')
    bare_result = harness.run_harness(
        bare,
        execute=True,
        launch_config=contract.LaunchConfig(
            executable=sys.executable,
            args=("-c", "pass"),
            timeout_seconds=30.0,
        ),
        checked=list(contract.REQUIRED_CHECK_IDS),
    )
    assert bare_result["status"] == "blocked"
    assert bare_result["artifact"]["manifest"]["present"] is False

    malformed = scratch_dir / "malformed"
    _write_text(malformed / "foundation_manifest.json", "not-json")
    malformed_result = harness.run_harness(
        malformed,
        execute=True,
        launch_config=contract.LaunchConfig(
            executable=sys.executable,
            args=("-c", "pass"),
            timeout_seconds=30.0,
        ),
        checked=list(contract.REQUIRED_CHECK_IDS),
    )
    assert malformed_result["status"] == "blocked"
    assert malformed_result["artifact"]["manifest"]["status"] == "unreadable"


def test_manifest_lock_agreement_recorded(scratch_dir):
    """Matching manifest and lock identities stay quiet while conflicts surface."""
    agreed = harness.verify_artifact(_make_artifact(scratch_dir / "agreed"))
    assert agreed["mismatch"] == []
    conflicted = harness.verify_artifact(_make_artifact(scratch_dir / "conflicted", lock_identity="other-hash"))
    assert conflicted["mismatch"][0]["field"] == "manifest_vs_lock_identity"


def test_result_file_excluded_from_inventory(scratch_dir):
    """Writing the harness output never changes the artifact fingerprint."""
    artifact = _make_artifact(scratch_dir / "artifact")
    before = harness.verify_artifact(artifact)["fingerprint"]
    _write_text(artifact / "engine_acceptance.json", '{"schema": "engine-acceptance/1"}')
    after = harness.verify_artifact(artifact)["fingerprint"]
    assert before == after


def test_json_round_trip_is_stable(scratch_dir):
    """Results serialize deterministically and load back unchanged."""
    artifact = _make_artifact(scratch_dir / "artifact")
    result = harness.run_harness(artifact, target="steam", profile="acceptance")
    first_path = harness.write_result(scratch_dir / "first" / "engine_acceptance.json", result)
    second_path = harness.write_result(scratch_dir / "second" / "engine_acceptance.json", result)
    assert Path(first_path).read_text(encoding="utf-8") == Path(second_path).read_text(encoding="utf-8")
    loaded = harness.load_result(first_path)
    assert loaded == result
    assert contract.compute_run_id(result["identity_core"]) == result["run_id"]


def _load_cli_module():
    cli_path = Path(__file__).resolve().parents[2] / "tools" / "run_engine_acceptance.py"
    spec = importlib.util.spec_from_file_location("run_engine_acceptance_cli", cli_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_help_contains_short_checklist():
    """The command help embeds the required M7.4 checklist."""
    cli = _load_cli_module()
    rendered = cli.build_parser().format_help()
    assert "main_menu" in rendered
    assert "save_reload" in rendered
    assert "dry-run" in rendered.lower()


def test_cli_dry_run_writes_result(scratch_dir):
    """The CLI dry-run path writes a result without launching anything."""
    cli = _load_cli_module()
    artifact = _make_artifact(scratch_dir / "artifact")
    output = scratch_dir / "out" / "engine_acceptance.json"
    code = cli.main(["--artifact-dir", str(artifact), "--output", str(output), "--check", "main_menu"])
    assert code == 0
    stored = json.loads(output.read_text(encoding="utf-8"))
    assert stored["mode"] == "dry_run"
    assert stored["status"] == "dry_run"
    assert stored["launch"]["executed"] is False


def test_cli_execute_requires_executable(scratch_dir):
    """Requesting execution without a game command fails with a usage error."""
    cli = _load_cli_module()
    artifact = _make_artifact(scratch_dir / "artifact")
    code = cli.main(["--artifact-dir", str(artifact), "--execute"])
    assert code == 2


def test_cli_skip_launcher_observes_hoi4_by_default(monkeypatch, scratch_dir):
    """The direct skip-launcher path still waits for the game process."""
    cli = _load_cli_module()
    artifact = _make_artifact(scratch_dir / "artifact")
    target = scratch_dir / "game"
    target.mkdir()
    executable = target / "hoi4.exe"
    executable.write_bytes(b"fake executable")
    captured = {}

    def fake_run_harness(**kwargs):
        captured["launch"] = kwargs["launch_config"]
        return {"status": "dry_run", "launch": {}}

    monkeypatch.setattr(cli.harness, "run_harness", fake_run_harness)
    code = cli.main([
        "--artifact-dir", str(artifact),
        "--target", str(target),
        "--launch-via", "steam",
        "--skip-launcher",
        "--execute",
    ])

    assert code == 0
    assert captured["launch"].executable == str(executable)
    assert captured["launch"].wait_for_process == "hoi4.exe"


def test_execute_collects_post_launch_log_error(scratch_dir):
    """An opt-in launch appending a fresh error fails the run."""
    artifact = _make_artifact(scratch_dir / "artifact")
    log_path = _write_text(scratch_dir / "error.log", "clean start\n")
    code = "open(%r, 'a', encoding='utf-8').write('[ERROR] province 9 has no pixels in definition.csv\\n')" % str(log_path)
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", code), timeout_seconds=30.0)
    result = harness.run_harness(
        artifact,
        log_paths=[str(log_path)],
        launch_config=config,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
    )
    assert result["mode"] == "assisted"
    assert result["launch"]["executed"] is True
    assert result["status"] == "failed"
    findings = result["logs"]["findings"]
    assert any("province 9" in item.get("text", "") for item in findings)
    assert any(item.get("category") == "map" for item in findings)
    assert result["logs"]["summary"]["blocker_count"] >= 1


def test_execute_collects_post_launch_save(scratch_dir):
    """An opt-in launch creating a save after the snapshot records it fresh."""
    artifact = _make_artifact(scratch_dir / "artifact")
    save_dir = scratch_dir / "saves"
    save_dir.mkdir()
    target = save_dir / "acceptance_save.hoi4"
    assert not target.exists()
    code = "open(%r, 'w', encoding='utf-8').write('save-bytes')" % str(target)
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", code), timeout_seconds=30.0)
    result = harness.run_harness(
        artifact,
        save_dir=str(save_dir),
        save_names=["acceptance_save.hoi4"],
        launch_config=config,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
    )
    assert result["launch"]["executed"] is True
    assert result["saves"][0]["status"] == "fresh"
    assert result["saves"][0]["sha256"] != ""
    assert result["status"] == "passed"


def test_execute_failures_never_pass(scratch_dir):
    """Non-zero, timeout, and missing-command launches never pass."""
    artifact = _make_artifact(scratch_dir / "artifact")
    all_checks = list(contract.REQUIRED_CHECK_IDS)
    bad = contract.LaunchConfig(executable=sys.executable, args=("-c", "import sys; sys.exit(3)"), timeout_seconds=30.0)
    bad_result = harness.run_harness(artifact, launch_config=bad, execute=True, checked=all_checks)
    assert bad_result["mode"] == "assisted"
    assert bad_result["status"] == "failed"
    assert bad_result["launch"]["returncode"] == 3
    assert any("return code" in item.lower() for item in bad_result["reasons"])
    slow = contract.LaunchConfig(executable=sys.executable, args=("-c", "import time; time.sleep(5)"), timeout_seconds=0.2)
    slow_result = harness.run_harness(artifact, launch_config=slow, execute=True, checked=all_checks)
    assert slow_result["status"] == "failed"
    assert slow_result["launch"]["status"] == "timeout"
    missing = harness.run_harness(artifact, launch_config=None, execute=True, checked=all_checks)
    assert missing["status"] != "passed"
    assert missing["status"] in ("failed", "blocked", "incomplete")
    assert any("game command" in item.lower() for item in missing["reasons"])


def test_dry_run_never_executes(scratch_dir):
    """Dry-run records the plan without executing the configured command."""
    artifact = _make_artifact(scratch_dir / "artifact")
    log_path = _write_text(scratch_dir / "error.log", "clean start\n")
    sentinel = scratch_dir / "should_not_exist.txt"
    code = "open(%r, 'w', encoding='utf-8').write('x')" % str(sentinel)
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", code), timeout_seconds=30.0)
    result = harness.run_harness(
        artifact,
        log_paths=[str(log_path)],
        launch_config=config,
        execute=False,
        checked=list(contract.REQUIRED_CHECK_IDS),
    )
    assert result["mode"] == "dry_run"
    assert result["status"] == "dry_run"
    assert result["launch"]["executed"] is False
    assert not sentinel.exists()
    assert result["logs"]["summary"]["blocker_count"] == 0
