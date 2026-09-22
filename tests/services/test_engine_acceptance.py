"""Focused M7 assisted engine-acceptance harness tests."""
from __future__ import annotations

import importlib.util
import itertools
import json
import os
import shutil
import sys
import tempfile
import copy
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


def _snapshot_with_fresh_log(path: Path, text: str) -> dict:
    _write_text(path, "")
    snapshot = harness.snapshot_log_file(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
    return snapshot


def _active_dlc_log(names: list[str], declared_count: int | None = None) -> str:
    count = len(names) if declared_count is None else declared_count
    lines = [
        "[10:48:23][no_game_date][gameapplication.cpp:1508]: Active DLC Count: %s" % count
    ]
    lines.extend(
        "[10:48:23][no_game_date][gameapplication.cpp:1513]: Active DLC: %s" % name
        for name in names
    )
    return "\n".join(lines) + "\n"


def _missing_dlc_entity_line(entity: str) -> str:
    return (
        "[10:48:23][no_game_date][equipment_graphic_database.cpp:72]: "
        'Entity referenced in equipment graphic database does not exist: "%s"' % entity
    )


def _missing_dlc_rule_line(rule: str, script_line: int) -> str:
    return (
        "[10:48:23][no_game_date][triggerimplementation.cpp:9803]: "
        "common/scripted_effects/BLT_scripted_effects.txt:%s: "
        "has_game_rule: game rule %s does not exist" % (script_line, rule)
    )


def _collect_optional_dlc_probe(
    root: Path,
    error_lines: list[str],
    *,
    evidence_state: str = "provided",
    active_names: list[str] | None = None,
    declared_count: int | None = None,
) -> dict:
    error_text = "\n".join(error_lines) + "\n"
    snapshots = [_snapshot_with_fresh_log(root / "logs" / "error.log", error_text)]
    system_path = root / "logs" / "system.log"
    if evidence_state == "provided":
        snapshots.append(_snapshot_with_fresh_log(
            system_path,
            _active_dlc_log(active_names or [], declared_count=declared_count),
        ))
    elif evidence_state == "missing":
        snapshots.append(harness.snapshot_log_file(system_path))
    elif evidence_state == "unreadable":
        snapshot = harness.snapshot_log_file(system_path)
        snapshot.update({"exists": True, "status": "unreadable"})
        snapshots.append(snapshot)
    elif evidence_state != "not_observed":
        raise AssertionError("unknown DLC evidence fixture state: %s" % evidence_state)
    return harness.collect_fresh_findings(snapshots)


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


def _make_legacy_passed_report(root: Path) -> dict:
    """Build an R3-shaped completed report from before checklist attestations."""
    artifact = _make_artifact(root / "artifact")
    log_path = root / "logs" / "error.log"
    save_dir = root / "saves"
    save_path = save_dir / "acceptance_save.hoi4"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    save_dir.mkdir(parents=True, exist_ok=True)
    code = "open(%r, 'wb').close(); open(%r, 'wb').write(b'save')" % (str(log_path), str(save_path))
    launch = contract.LaunchConfig(
        executable=sys.executable,
        args=("-c", code),
        timeout_seconds=30.0,
    )
    result = harness.run_harness(
        artifact,
        target="test-game",
        profile="acceptance",
        game_version="1.19.3.0",
        log_paths=[str(log_path)],
        save_dir=str(save_dir),
        save_names=[save_path.name],
        launch_config=launch,
        execute=True,
        checked=contract.REQUIRED_CHECK_IDS,
        check_notes={
            "naval_route": "Created convoy-backed naval-invasion route with generated division",
        },
        created_at="2026-09-20T20:30:00+00:00",
    )
    assert result["status"] == "passed"

    # Match the legacy R3 schema: checked entries predate explicit waiver fields,
    # and the run identity predates checklist/source-identity attestations.
    result["identity_core"].pop("checklist_attestation")
    result["identity_core"].pop("foundation_source_identity")
    result["artifact"]["manifest"].pop("foundation_source_identity")
    for entry in result["checklist"]:
        entry.pop("waived")
        entry.pop("waiver_reason")
    for key in ("waived", "waived_checks", "all_complete"):
        result["checklist_summary"].pop(key, None)
    result["identity_hash"] = contract.compute_identity_hash(result["identity_core"])
    result["run_id"] = contract.compute_run_id(result["identity_core"])
    return result


def _make_hoi4_user_dir(root: Path, dlc_load_bytes: bytes | None = None) -> Path:
    """Create the existing HOI4 user-data directories needed for managed activation."""
    (root / "mod").mkdir(parents=True)
    (root / "logs").mkdir()
    if dlc_load_bytes is not None:
        (root / "dlc_load.json").write_bytes(dlc_load_bytes)
    return root


def _run_managed_active_mod_probe(root: Path, initial_system_log: str, fresh_system_log: str | None) -> dict:
    """Execute a tiny local process that writes fresh evidence for managed-run tests."""
    artifact = _make_artifact(root / "artifact")
    descriptor_name = "BelgiumAcceptanceM10"
    (artifact / "descriptor.mod").write_text('name="%s"\n' % descriptor_name, encoding="utf-8")
    log_dir = root / "logs"
    log_dir.mkdir(parents=True)
    error_log = log_dir / "error.log"
    system_log = log_dir / "system.log"
    if initial_system_log:
        _write_text(system_log, initial_system_log)
    code = "open(%r, 'wb').close()" % str(error_log)
    if fresh_system_log is not None:
        code += "; open(%r, 'a', encoding='utf-8').write(%r)" % (str(system_log), fresh_system_log)
    launch = contract.LaunchConfig(executable=sys.executable, args=("-c", code), timeout_seconds=20.0)
    return harness.run_harness(
        artifact,
        log_paths=[str(error_log), str(system_log)],
        launch_config=launch,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
        managed_activation={
            "descriptor_name": descriptor_name,
            "descriptor_reference": "mod/hoi4_map_maker_acceptance.mod",
        },
    )


def test_managed_activation_stages_descriptor_and_restores_exact_dlc_load(scratch_dir):
    """Managed activation changes only enabled_mods and restores original bytes."""
    artifact = _make_artifact(scratch_dir / "artifact")
    descriptor = (
        'version="1.0"\n'
        'name="BelgiumAcceptanceM10"\n'
        'supported_version="1.16.*"\n'
        'tags={ "Alternative History" }\n'
        'replace_path="history/countries"\n'
        'path="mod/old-location"\n'
    )
    (artifact / "descriptor.mod").write_text(descriptor, encoding="utf-8")
    original = (
        b'\xef\xbb\xbf{\r\n'
        b'  "enabled_mods": ["mod/fantasy.mod"],\r\n'
        b'  "disabled_dlcs": ["dlc1", "dlc2"],\r\n'
        b'  "custom_setting": {"keep": true}\r\n'
        b'}\r\n'
    )
    user_dir = _make_hoi4_user_dir(scratch_dir / "hoi4-user", original)
    staged_path = user_dir / "mod" / harness.MANAGED_DESCRIPTOR_FILENAME

    with harness.managed_artifact_activation(artifact, user_dir) as activation:
        assert activation["expected_mod_name"] == "BelgiumAcceptanceM10"
        assert activation["descriptor_reference"] == "mod/" + harness.MANAGED_DESCRIPTOR_FILENAME
        staged_text = staged_path.read_text(encoding="utf-8")
        assert 'name="BelgiumAcceptanceM10"' in staged_text
        assert 'version="1.0"' in staged_text
        assert 'supported_version="1.16.*"' in staged_text
        assert 'replace_path="history/countries"' in staged_text
        assert 'path="%s"' % artifact.resolve().as_posix() in staged_text
        assert "old-location" not in staged_text
        active_settings = json.loads((user_dir / "dlc_load.json").read_text(encoding="utf-8"))
        assert active_settings == {
            "enabled_mods": [activation["descriptor_reference"]],
            "disabled_dlcs": ["dlc1", "dlc2"],
            "custom_setting": {"keep": True},
        }

    assert (user_dir / "dlc_load.json").read_bytes() == original
    assert not staged_path.exists()


def test_managed_activation_restores_exact_bytes_after_exception(scratch_dir):
    """The finally path restores the old config and removes only its descriptor."""
    artifact = _make_artifact(scratch_dir / "artifact")
    original = b'{ "enabled_mods": [], "disabled_dlcs": ["keep-me"] }\n'
    user_dir = _make_hoi4_user_dir(scratch_dir / "hoi4-user", original)
    staged_path = user_dir / "mod" / harness.MANAGED_DESCRIPTOR_FILENAME

    with pytest.raises(RuntimeError, match="simulated launch exception"):
        with harness.managed_artifact_activation(artifact, user_dir):
            assert staged_path.is_file()
            raise RuntimeError("simulated launch exception")

    assert (user_dir / "dlc_load.json").read_bytes() == original
    assert not staged_path.exists()


def test_managed_activation_does_not_overwrite_concurrent_dlc_load_change(scratch_dir):
    """A concurrent edit is preserved and reported instead of silently overwritten."""
    artifact = _make_artifact(scratch_dir / "artifact")
    original = b'{"enabled_mods":["mod/fantasy.mod"],"disabled_dlcs":[]}\n'
    concurrent = b'{"enabled_mods":["mod/user-change.mod"],"disabled_dlcs":["keep"]}\n'
    user_dir = _make_hoi4_user_dir(scratch_dir / "hoi4-user", original)
    staged_path = user_dir / "mod" / harness.MANAGED_DESCRIPTOR_FILENAME
    dlc_load = user_dir / "dlc_load.json"

    with pytest.raises(OSError, match="changed concurrently; original bytes were left untouched"):
        with harness.managed_artifact_activation(artifact, user_dir):
            dlc_load.write_bytes(concurrent)

    assert dlc_load.read_bytes() == concurrent
    assert not staged_path.exists()


def test_managed_activation_removes_created_dlc_load_when_originally_absent(scratch_dir):
    """An absent dlc_load.json is removed again after the activation transaction."""
    artifact = _make_artifact(scratch_dir / "artifact")
    user_dir = _make_hoi4_user_dir(scratch_dir / "hoi4-user")
    dlc_load = user_dir / "dlc_load.json"
    staged_path = user_dir / "mod" / harness.MANAGED_DESCRIPTOR_FILENAME
    assert not dlc_load.exists()

    with harness.managed_artifact_activation(artifact, user_dir):
        assert json.loads(dlc_load.read_text(encoding="utf-8"))["enabled_mods"] == [
            "mod/" + harness.MANAGED_DESCRIPTOR_FILENAME
        ]

    assert not dlc_load.exists()
    assert not staged_path.exists()


def test_managed_activation_refuses_descriptor_collision_without_overwriting(scratch_dir):
    """A pre-existing staged descriptor is never overwritten or removed."""
    artifact = _make_artifact(scratch_dir / "artifact")
    original = b'{"enabled_mods":["mod/fantasy.mod"],"disabled_dlcs":[]}\n'
    user_dir = _make_hoi4_user_dir(scratch_dir / "hoi4-user", original)
    staged_path = user_dir / "mod" / harness.MANAGED_DESCRIPTOR_FILENAME
    collision_bytes = b"user-owned descriptor\n"
    staged_path.write_bytes(collision_bytes)

    with pytest.raises(ValueError, match="already exists; refusing to overwrite"):
        with harness.managed_artifact_activation(artifact, user_dir):
            pytest.fail("activation must reject the pre-existing descriptor")

    assert staged_path.read_bytes() == collision_bytes
    assert (user_dir / "dlc_load.json").read_bytes() == original


def test_managed_activation_rejects_relative_user_directory(scratch_dir):
    """Activation requires a clear absolute user-data directory."""
    artifact = _make_artifact(scratch_dir / "artifact")
    with pytest.raises(ValueError, match="absolute, unambiguous path"):
        with harness.managed_artifact_activation(artifact, Path("relative-user-dir")):
            pytest.fail("relative user-data paths must be rejected")


def test_log_snapshot_ignores_old_content(scratch_dir):
    """Only bytes appended after the snapshot are classified as evidence."""
    log_path = _write_text(scratch_dir / "error.log", "[ERROR] province 7 has no pixels in definition.csv\n")
    snapshot = harness.snapshot_log_file(log_path)
    assert snapshot["status"] == "snapshotted"
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write("[ERROR] Could not load map/terrain/colormap_test.dds\n")
        handle.write("plain progress line\n")
    collected = harness.collect_fresh_findings([snapshot])
    assert len(collected["findings"]) == 2
    assert collected["findings"][0]["category"] == "asset"
    assert collected["findings"][0]["severity"] == "error"
    assert collected["findings"][1]["category"] == "unknown"
    assert collected["findings"][1]["severity"] == "error"
    assert all("province 7" not in item["text"] for item in collected["findings"])


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


@pytest.mark.parametrize(("line", "expected_category"), [
    ("Sound effect with name 'raid_result_failure' already added", "audio_unrelated"),
    ("SoundEffect 'raid_result_failure' already has category 'UI', old category will be overwritten", "audio_unrelated"),
    ("Could not load pdx_audio/assetfactory_audio/sound/raid_result_failure.asset", "audio_unrelated"),
    ("Error: FMOD failed to load sound bank music.bank", "audio_unrelated"),
    ("Required DLC 'No Step Back' is not installed", "dlc_unrelated"),
    ("Operating system reports unsupported display resolution", "environment_unrelated"),
])
def test_error_log_audio_dlc_and_environment_lines_are_nonblocking(line, expected_category):
    """Source-aware error.log evidence keeps known non-map noise nonblocking."""
    assert contract.classify_error_line(line) == expected_category
    severity, category = contract.classify_line(line, source="logs/error.log")
    assert (severity, category) == ("error", expected_category)
    finding = contract.LogFinding(
        source="logs/error.log",
        line_number=1,
        category=category,
        severity=severity,
        text=line,
    ).to_dict()
    summary = harness.summarize_findings([finding])
    assert summary["errors"] == 1
    assert summary["blocker_count"] == 0
    assert summary["verdict"] == "clean"


@pytest.mark.parametrize(("line", "expected_category"), [
    ("Error: province map failed to load sound asset", "map"),
    ("Error: map/terrain/colormap.dds failed while loading audio", "asset"),
    ("Error: unexpected token in common/scripted_effects/test.txt for sound effect", "script"),
    ("Error: invalid country tag QQA references missing music", "country_tag"),
])
def test_blocker_classification_precedes_audio_noise(line, expected_category):
    """Audio wording cannot turn map, asset, script, or country errors clean."""
    assert contract.classify_error_line(line) == expected_category
    severity, category = contract.classify_line(line, source="logs/error.log")
    assert (severity, category) == ("error", expected_category)
    assert contract.is_blocker_finding(category, severity) is True


def test_generic_audio_word_without_known_signature_remains_blocking_unknown():
    """A bare audio word is insufficient to waive an otherwise unknown error."""
    line = "Error: unable to initialize audio configuration"
    severity, category = contract.classify_line(line, source="logs/error.log")
    assert (severity, category) == ("error", "unknown")
    assert contract.is_blocker_finding(category, severity) is True


def test_dlc_checksum_line_is_unknown_and_blocking_in_pure_classification():
    """The checksum signature is not nonblocking without collector evidence."""
    line = "[22:32:45][no_game_date][dlc.cpp:142]: incorrect checksum for DLC"
    assert contract.classify_error_line(line) == "unknown"
    severity, category = contract.classify_line(line, source="logs/error.log")
    assert (severity, category) == ("error", "unknown")
    finding = contract.LogFinding(
        source="logs/error.log",
        line_number=1,
        category=category,
        severity=severity,
        text=line,
    ).to_dict()
    summary = harness.summarize_findings([finding])
    assert summary["blocker_count"] == 1
    assert summary["blocker_categories"] == ["unknown"]
    assert summary["verdict"] == "failed"


def test_dlc_checksum_line_downgrades_with_complete_fresh_dlc_evidence(scratch_dir):
    """A complete fresh DLC catalog permits only the known checksum line downgrade."""
    line = "[22:32:45][no_game_date][dlc.cpp:142]: incorrect checksum for DLC"
    collected = _collect_optional_dlc_probe(
        scratch_dir,
        [line],
        active_names=["Fixture Active DLC"],
    )

    assert collected["active_dlc"]["status"] == "complete"
    assert collected["findings"][0]["category"] == "dlc_unrelated"
    assert collected["findings"][0]["severity"] == "error"
    assert harness.summarize_findings(collected["findings"])["blocker_count"] == 0


@pytest.mark.parametrize(("evidence_state", "active_names", "declared_count", "expected_status"), [
    ("not_observed", None, None, "not_observed"),
    ("missing", None, None, "missing"),
    ("unreadable", None, None, "unreadable"),
    ("provided", ["Fixture Active DLC"], 2, "incomplete"),
])
def test_dlc_checksum_line_stays_blocking_without_complete_fresh_evidence(
    evidence_state,
    active_names,
    declared_count,
    expected_status,
    scratch_dir,
):
    """Missing or incomplete fresh DLC catalogs cannot downgrade the checksum line."""
    line = "[22:32:45][no_game_date][dlc.cpp:142]: incorrect checksum for DLC"
    collected = _collect_optional_dlc_probe(
        scratch_dir,
        [line],
        evidence_state=evidence_state,
        active_names=active_names,
        declared_count=declared_count,
    )

    finding = collected["findings"][0]
    assert collected["active_dlc"]["status"] == expected_status
    assert finding["category"] == "unknown"
    assert contract.is_blocker_finding(finding["category"], finding["severity"])
    assert harness.summarize_findings(collected["findings"])["blocker_count"] == 1


def test_dlc_checksum_downgrade_requires_exact_signature(scratch_dir):
    """Other DLC source lines remain blockers even with a complete fresh catalog."""
    lines = [
        "[22:32:45][no_game_date][dlc.cpp:143]: incorrect checksum for DLC",
        "[22:32:45][no_game_date][dlc.cpp:142]: incorrect checksum for another DLC",
    ]
    collected = _collect_optional_dlc_probe(
        scratch_dir,
        lines,
        active_names=["Fixture Active DLC"],
    )

    assert collected["active_dlc"]["status"] == "complete"
    assert len(collected["findings"]) == 2
    assert all(item["category"] == "unknown" for item in collected["findings"])
    assert harness.summarize_findings(collected["findings"])["blocker_count"] == 2


def test_optional_dlc_findings_downgrade_only_with_a_complete_inactive_list(scratch_dir):
    """Only the five known entity and four known game-rule lines use DLC evidence."""
    lines = [
        _missing_dlc_entity_line("GER_super_heavy_armor_entity")
        for _ in range(4)
    ] + [_missing_dlc_entity_line("SOV_super_heavy_armor_entity")]
    lines.extend([
        _missing_dlc_rule_line("LIT_ai_behavior", 77),
        _missing_dlc_rule_line("LIT_ai_behavior", 83),
        _missing_dlc_rule_line("EST_ai_behavior", 213),
        _missing_dlc_rule_line("EST_ai_behavior", 219),
    ])
    active_names = ["Fixture Active DLC %02d" % index for index in range(14)]
    collected = _collect_optional_dlc_probe(
        scratch_dir,
        lines,
        active_names=active_names,
    )

    evidence = collected["active_dlc"]
    assert evidence["status"] == "complete"
    assert evidence["count"] == 14
    assert evidence["observed_names"] == active_names
    assert evidence["source"].endswith("system.log")
    assert evidence["fresh_lines"] == 15
    assert evidence["truncated"] is False
    assert len(collected["findings"]) == 9
    assert all(item["severity"] == "error" for item in collected["findings"])
    assert all(item["category"] == "dlc_unrelated" for item in collected["findings"])
    assert harness.summarize_findings(collected["findings"])["blocker_count"] == 0


@pytest.mark.parametrize(("line", "owner", "normal_category"), [
    (_missing_dlc_entity_line("GER_super_heavy_armor_entity"), "German Tanks Unit Pack", "unknown"),
    (_missing_dlc_entity_line("SOV_super_heavy_armor_entity"), "Soviet Tanks Unit Pack", "unknown"),
    (_missing_dlc_rule_line("LIT_ai_behavior", 77), "No Step Back", "script"),
    (_missing_dlc_rule_line("EST_ai_behavior", 213), "No Step Back", "script"),
])
def test_optional_dlc_findings_stay_blocking_when_owner_is_active(
    line, owner, normal_category, scratch_dir
):
    """An active owning DLC never masks the original blocker classification."""
    collected = _collect_optional_dlc_probe(
        scratch_dir,
        [line],
        active_names=[owner],
    )
    finding = collected["findings"][0]
    assert collected["active_dlc"]["status"] == "complete"
    assert finding["category"] == normal_category
    assert contract.is_blocker_finding(finding["category"], finding["severity"])
    assert harness.summarize_findings(collected["findings"])["blocker_count"] == 1


@pytest.mark.parametrize(("line", "normal_category"), [
    (_missing_dlc_entity_line("GER_super_heavy_armor_entity"), "unknown"),
    (_missing_dlc_rule_line("LIT_ai_behavior", 77), "script"),
])
@pytest.mark.parametrize(("evidence_state", "active_names", "declared_count", "expected_status"), [
    ("not_observed", None, None, "not_observed"),
    ("missing", None, None, "missing"),
    ("unreadable", None, None, "unreadable"),
    ("provided", ["An unrelated active DLC"], 2, "incomplete"),
])
def test_optional_dlc_findings_stay_blocking_without_complete_evidence(
    line,
    normal_category,
    evidence_state,
    active_names,
    declared_count,
    expected_status,
    scratch_dir,
):
    """Absent, unreadable, or incomplete DLC evidence leaves errors blocking."""
    collected = _collect_optional_dlc_probe(
        scratch_dir,
        [line],
        evidence_state=evidence_state,
        active_names=active_names,
        declared_count=declared_count,
    )
    finding = collected["findings"][0]
    assert collected["active_dlc"]["status"] == expected_status
    assert finding["category"] == normal_category
    assert contract.is_blocker_finding(finding["category"], finding["severity"])


@pytest.mark.parametrize(("line", "normal_category"), [
    (_missing_dlc_entity_line("USA_super_heavy_armor_entity"), "unknown"),
    (_missing_dlc_rule_line("LIT_other_ai_behavior", 77), "script"),
    (_missing_dlc_rule_line("LIT_ai_behavior", 78), "script"),
])
def test_optional_dlc_correlation_does_not_match_other_entities_or_rules(
    line, normal_category, scratch_dir
):
    """Near-miss entity, rule, and source-line signatures remain blockers."""
    collected = _collect_optional_dlc_probe(
        scratch_dir,
        [line],
        active_names=[],
    )
    finding = collected["findings"][0]
    assert collected["active_dlc"]["status"] == "complete"
    assert finding["category"] == normal_category
    assert contract.is_blocker_finding(finding["category"], finding["severity"])


def test_unrecognized_nonblank_error_log_line_is_a_blocker():
    """Unknown non-audio error.log lines remain blocking evidence without an error token."""
    for line in ("Unrecognized engine diagnostic detail", "[WARN] fallback engine detail"):
        severity, category = contract.classify_line(line, source="error.log")
        assert (severity, category) == ("error", "unknown")
        finding = contract.LogFinding(category=category, severity=severity).to_dict()
        assert harness.summarize_findings([finding])["blocker_count"] == 1


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


@pytest.mark.parametrize(("save_status", "reason_fragment"), [
    ("missing", "save file(s) missing"),
    ("stale", "predate the snapshot"),
    ("unreadable", "save file(s) are unreadable"),
    ("not_configured", "save directory is not configured"),
])
def test_nonfresh_expected_saves_prevent_acceptance(monkeypatch, scratch_dir, save_status, reason_fragment):
    """Every expected save must be fresh; all nonfresh evidence is explained."""
    artifact = _make_artifact(scratch_dir / "artifact")
    save_dir = scratch_dir / "saves"
    save_path = save_dir / "acceptance_save.hoi4"
    snapshot_ns = None
    if save_status != "not_configured":
        save_dir.mkdir()
    if save_status in ("stale", "unreadable"):
        _write_text(save_path, "save-bytes")
        file_mtime_ns = save_path.stat().st_mtime_ns
        snapshot_ns = file_mtime_ns + 1 if save_status == "stale" else file_mtime_ns - 1
    if save_status == "unreadable":
        original_hash = harness._sha256_file

        def fail_save_hash(path, limit_bytes=harness.SAVE_HASH_LIMIT_BYTES):
            if Path(path) == save_path:
                raise OSError("simulated unreadable save")
            return original_hash(Path(path), limit_bytes)

        monkeypatch.setattr(harness, "_sha256_file", fail_save_hash)

    error_log = scratch_dir / "error.log"
    code = "open(%r, 'wb').close()" % str(error_log)
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", code), timeout_seconds=30.0)
    result = harness.run_harness(
        artifact,
        log_paths=[str(error_log)],
        save_dir=None if save_status == "not_configured" else str(save_dir),
        save_names=["acceptance_save.hoi4"],
        launch_config=config,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
        snapshot_ns=snapshot_ns,
    )

    assert result["saves"][0]["status"] == save_status
    assert result["status"] == "incomplete"
    assert any(reason_fragment in reason for reason in result["reasons"])


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


def test_acceptance_report_carries_derived_foundation_source_identity(scratch_dir):
    """Future reports bind their run identity to the manifest's source payload."""
    artifact = _make_artifact(scratch_dir / "artifact")
    result = harness.run_harness(artifact, target="steam", profile="acceptance")
    evidence = result["artifact"]["manifest"]["foundation_source_identity"]

    assert len(evidence["identity_hash"]) == 64
    assert evidence["algorithm"]
    assert result["identity_core"]["foundation_source_identity"] == evidence["identity_hash"]


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


def test_disabling_error_log_requirement_needs_explicit_non_error_logs(scratch_dir):
    """The error.log opt-out is deliberate and cannot silently cover an empty set."""
    artifact = _make_artifact(scratch_dir / "artifact")
    error_log = scratch_dir / "error.log"
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", "pass"), timeout_seconds=30.0)
    with pytest.raises(ValueError, match="explicit non-error log set"):
        harness.run_harness(
            artifact,
            launch_config=config,
            execute=True,
            checked=list(contract.REQUIRED_CHECK_IDS),
            require_error_log=False,
        )
    with pytest.raises(ValueError, match="explicit non-error log set"):
        harness.run_harness(
            artifact,
            log_paths=[str(error_log)],
            launch_config=config,
            execute=True,
            checked=list(contract.REQUIRED_CHECK_IDS),
            require_error_log=False,
        )


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
    setup_log = _write_text(scratch_dir / "setup.log", "pre-run setup record\n")
    probe = contract.LaunchConfig(executable=sys.executable, args=("-c", "pass"), timeout_seconds=30.0)
    partial = harness.run_harness(
        artifact,
        log_paths=[str(setup_log)],
        launch_config=probe,
        execute=True,
        checked=["main_menu"],
        require_error_log=False,
    )
    assert partial["mode"] == "assisted"
    assert partial["status"] == "incomplete"
    assert "bookmark_map" in partial["checklist_summary"]["missing"]
    complete = harness.run_harness(
        artifact,
        log_paths=[str(setup_log)],
        launch_config=probe,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
        require_error_log=False,
    )
    assert complete["status"] == "passed"


@pytest.mark.parametrize(
    ("checked", "notes", "waived_checks", "message"),
    [
        (("naval_route",), None, {"naval_route": "not applicable"}, "both checked and waived"),
        (("unknown_check",), None, None, "Unknown checklist check id"),
        (("",), None, None, "cannot be empty"),
        ((), None, {"unknown_check": "not applicable"}, "Unknown checklist check id"),
        ((), {"unknown_check": "note"}, None, "Unknown checklist check id"),
        (("selection", "selection"), None, None, "more than once"),
        ((), {"selection": "one", " selection ": "two"}, None, "more than once"),
        ((), None, {"naval_route": "  "}, "reason cannot be empty"),
    ],
)
def test_checklist_selection_rejects_invalid_answers(checked, notes, waived_checks, message):
    """Invalid ids, duplicate answers, empty reasons, and conflicts fail early."""
    with pytest.raises(ValueError, match=message):
        harness.normalize_checklist(
            checked=checked,
            notes=notes,
            waived_checks=waived_checks,
        )


def test_waived_check_completes_assisted_run_and_is_identity_attested(scratch_dir):
    """A reasoned waiver completes status but remains distinct from a checked item."""
    artifact = _make_artifact(scratch_dir / "artifact")
    error_log = scratch_dir / "logs" / "error.log"
    error_log.parent.mkdir(parents=True, exist_ok=True)
    code = "open(%r, 'wb').close()" % str(error_log)
    launch = contract.LaunchConfig(executable=sys.executable, args=("-c", code), timeout_seconds=30.0)
    reason = "No usable port was available in this scenario."
    checked = [item for item in contract.REQUIRED_CHECK_IDS if item != "naval_route"]

    complete = harness.run_harness(
        artifact,
        log_paths=[str(error_log)],
        launch_config=launch,
        execute=True,
        checked=checked,
        waived_checks={"naval_route": reason},
        created_at="2026-09-20T20:30:00+00:00",
    )
    repeated = harness.run_harness(
        artifact,
        log_paths=[str(error_log)],
        launch_config=launch,
        execute=False,
        checked=checked,
        waived_checks={"naval_route": reason},
        created_at="2026-09-21T20:30:00+00:00",
    )
    all_checked = harness.run_harness(
        artifact,
        log_paths=[str(error_log)],
        launch_config=launch,
        checked=contract.REQUIRED_CHECK_IDS,
        created_at="2026-09-20T20:30:00+00:00",
    )

    assert complete["status"] == "passed"
    assert complete["checklist_summary"] == {
        "required": 10,
        "checked": 9,
        "waived": 1,
        "waived_checks": [{"check_id": "naval_route", "reason": reason}],
        "missing": [],
        "all_checked": False,
        "all_complete": True,
    }
    naval = next(item for item in complete["checklist"] if item["check_id"] == "naval_route")
    assert naval["checked"] is False
    assert naval["waived"] is True
    assert naval["waiver_reason"] == reason
    assert any("naval_route was explicitly waived" in item for item in complete["reasons"])
    assert complete["identity_core"]["checklist_attestation"] == contract.canonical_checklist_attestation(complete["checklist"])
    assert repeated["identity_hash"] == complete["identity_hash"]
    assert repeated["run_id"] == complete["run_id"]
    assert all_checked["identity_hash"] != complete["identity_hash"]
    assert all_checked["run_id"] != complete["run_id"]


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


def test_failed_status_retains_independent_checklist_and_save_reasons():
    """A primary failure must not hide other evidence still needed for acceptance."""
    status, reasons = contract.decide_status(
        mode="assisted",
        artifact_ok=True,
        blocker_errors=1,
        unchecked_required=["naval_route"],
        save_evidence=[{"name": "acceptance.hoi4", "status": "missing"}],
    )

    assert status == "failed"
    assert any("1 blocker-class" in reason for reason in reasons)
    assert any("naval_route" in reason for reason in reasons)
    assert any("save file(s) missing" in reason for reason in reasons)


def test_naval_check_describes_convoy_backed_land_route():
    """The operator checklist names the route the generated scenario supports."""
    naval = next(item for item in contract.REQUIRED_CHECKS if item[0] == "naval_route")
    assert "naval-invasion route" in naval[2]
    assert "generated land division" in naval[2]


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


def test_artifact_verification_rejects_source_identity_algorithm_mismatch(scratch_dir):
    artifact = _make_artifact(scratch_dir / "algorithm")
    manifest_path = artifact / "foundation_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    derived = harness._manifest_foundation_source_identity(manifest)
    manifest["foundation_source_identity"] = {
        "identity_hash": derived["identity_hash"],
        "algorithm": "sha512",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    evidence = harness.verify_artifact(artifact)
    assert any(
        item["field"] == "foundation_source_identity_algorithm"
        for item in evidence["mismatch"]
    )


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


def test_legacy_completed_report_amendment_preserves_captured_evidence(scratch_dir):
    """The pre-attestation R3 schema can be amended without changing captures."""
    source = _make_legacy_passed_report(scratch_dir / "legacy")
    before = copy.deepcopy(source)
    preserved_fields = ("target", "artifact", "launch", "logs", "saves", "created_at")
    reason = (
        "No usable port was visible and the isolated scenario had no legal wartime island target; "
        "naval invasion was not applicable."
    )

    amended = harness.amend_checklist_result(
        source,
        waived_checks={"naval_route": reason},
    )
    repeated = harness.amend_checklist_result(
        source,
        waived_checks={"naval_route": reason},
    )

    assert source == before
    for key in preserved_fields:
        assert amended[key] == before[key]
    assert amended["status"] == "passed"
    assert amended["checklist_summary"]["checked"] == 9
    assert amended["checklist_summary"]["waived"] == 1
    assert amended["checklist_summary"]["missing"] == []
    naval = next(item for item in amended["checklist"] if item["check_id"] == "naval_route")
    assert naval["checked"] is False
    assert naval["waived"] is True
    assert naval["waiver_reason"] == reason
    assert naval["notes"] == ""
    assert amended["identity_core"]["checklist_attestation"] == contract.canonical_checklist_attestation(amended["checklist"])
    assert amended["identity_hash"] == contract.compute_identity_hash(amended["identity_core"])
    assert amended["run_id"] == contract.compute_run_id(amended["identity_core"])
    assert amended["run_id"] != source["run_id"]
    assert repeated == amended


def _rehash_report_identity(report: dict) -> None:
    report["identity_hash"] = contract.compute_identity_hash(report["identity_core"])
    report["run_id"] = contract.compute_run_id(report["identity_core"])


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("non_assisted", "Only a completed assisted"),
        ("identity_hash", "identity hash does not match"),
        ("identity_capture_link", "conflicts with captured artifact_fingerprint"),
        ("stale_attestation", "checklist conflicts with its identity attestation"),
        ("summary", "summary conflicts with its checklist"),
        ("status", "status conflicts with its captured evidence"),
        ("unfinished", "did not finish normally"),
        ("malformed_boolean", "must be boolean"),
        ("missing_check", "missing required checklist entries"),
    ],
)
def test_amendment_rejects_malformed_or_inconsistent_report(scratch_dir, mutation, message):
    """Amendment refuses unsupported modes and internally inconsistent reports."""
    report = _make_legacy_passed_report(scratch_dir / "legacy")
    if mutation == "non_assisted":
        report["mode"] = "dry_run"
    elif mutation == "identity_hash":
        report["identity_hash"] = "tampered"
    elif mutation == "identity_capture_link":
        report["identity_core"]["artifact_fingerprint"] = "tampered"
        _rehash_report_identity(report)
    elif mutation == "stale_attestation":
        report["identity_core"]["checklist_attestation"] = []
        _rehash_report_identity(report)
    elif mutation == "summary":
        report["checklist_summary"]["checked"] = 9
    elif mutation == "status":
        report["status"] = "incomplete"
    elif mutation == "unfinished":
        report["launch"]["status"] = "timeout"
    elif mutation == "malformed_boolean":
        report["checklist"][0]["checked"] = "true"
    elif mutation == "missing_check":
        report["checklist"].pop()

    with pytest.raises(ValueError, match=message):
        harness.amend_checklist_result(report, waived_checks={"naval_route": "not applicable"})


def test_integrity_validation_reclassifies_stored_log_findings(scratch_dir):
    report = _make_legacy_passed_report(scratch_dir / "classification")
    report["logs"]["findings"] = [
        {
            "source": "logs/error.log",
            "line_number": 1,
            "category": "audio_unrelated",
            "severity": "error",
            "text": "Error: province map failed to load sound asset",
        }
    ]
    report["logs"]["summary"] = harness.summarize_findings(report["logs"]["findings"])
    with pytest.raises(ValueError, match="finding category conflicts"):
        harness.validate_result_integrity(report)


def test_integrity_validation_rejects_incomplete_active_dlc_proof(scratch_dir):
    report = _make_legacy_passed_report(scratch_dir / "dlc-integrity")
    report["logs"]["active_dlc"] = {"status": "complete"}
    report["logs"]["findings"] = [
        {
            "source": "logs/error.log",
            "line_number": 1,
            "category": "dlc_unrelated",
            "severity": "error",
            "text": _missing_dlc_entity_line("BRA_light_tank_destroyer_0_entity"),
        }
    ]
    report["logs"]["summary"] = harness.summarize_findings(report["logs"]["findings"])
    with pytest.raises(ValueError, match="active-DLC names"):
        harness.validate_result_integrity(report)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("duplicate_names", "names contain duplicates"),
        ("multiple_system_logs", "unambiguous captured system.log"),
    ],
)
def test_integrity_validation_rejects_ambiguous_active_dlc_proof(scratch_dir, case, message):
    report = _make_legacy_passed_report(scratch_dir / case)
    source = str(scratch_dir / case / "logs" / "system.log")
    report["logs"]["files"].append({
        "path": source,
        "status": "ok",
        "generated": True,
        "fresh_lines": 2,
        "fresh_bytes": 100,
        "new_offset": 100,
        "truncated": False,
        "rewritten": True,
    })
    names = ["DLC A", "dlc a"] if case == "duplicate_names" else ["DLC A"]
    report["logs"]["active_dlc"] = {
        "status": "complete",
        "source": source,
        "fresh_lines": 2,
        "truncated": False,
        "count": len(names),
        "observed_names": names,
    }
    if case == "multiple_system_logs":
        report["logs"]["files"].append({
            "path": str(scratch_dir / case / "other" / "system.log"),
            "status": "ok",
            "generated": True,
            "fresh_lines": 2,
            "fresh_bytes": 100,
            "new_offset": 100,
            "truncated": False,
            "rewritten": True,
        })
    with pytest.raises(ValueError, match=message):
        harness.validate_result_integrity(report)


def test_active_dlc_evidence_serializes_and_is_summarized_when_relevant(scratch_dir, capsys):
    """Fresh active-DLC proof survives result serialization and explains a downgrade."""
    artifact = _make_artifact(scratch_dir / "artifact")
    log_dir = scratch_dir / "logs"
    log_dir.mkdir()
    error_log = log_dir / "error.log"
    system_log = log_dir / "system.log"
    error_text = _missing_dlc_entity_line("GER_super_heavy_armor_entity") + "\n"
    system_text = _active_dlc_log(["An unrelated active DLC"])
    code = (
        "open(%r, 'w', encoding='utf-8').write(%r); "
        "open(%r, 'w', encoding='utf-8').write(%r)"
    ) % (str(error_log), error_text, str(system_log), system_text)
    config = contract.LaunchConfig(
        executable=sys.executable,
        args=("-c", code),
        timeout_seconds=30.0,
    )
    result = harness.run_harness(
        artifact,
        log_paths=[str(error_log), str(system_log)],
        launch_config=config,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
    )

    evidence = result["logs"]["active_dlc"]
    assert evidence["status"] == "complete"
    assert result["logs"]["summary"]["by_category"]["dlc_unrelated"] == 1
    result_path = scratch_dir / "result" / "engine_acceptance.json"
    harness.write_result(result_path, result)
    loaded = harness.load_result(result_path)
    assert loaded["logs"]["active_dlc"] == evidence

    cli = _load_cli_module()
    cli.print_summary(loaded, str(result_path))
    assert "active DLC evidence: status=complete count=1 source=system.log" in capsys.readouterr().out


def test_cli_omits_active_dlc_evidence_when_no_dlc_findings(capsys):
    """Routine summaries stay concise when active-DLC context adds no value."""
    cli = _load_cli_module()
    cli.print_summary({
        "logs": {
            "summary": {"by_category": {"dlc_unrelated": 0}},
            "active_dlc": {"status": "complete", "count": 14, "source": "system.log"},
        },
    }, "engine_acceptance.json")
    assert "active DLC evidence:" not in capsys.readouterr().out


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
    assert "allow-non-error-log-set" in rendered


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


def test_cli_managed_activation_rejects_invalid_modes_and_mod_argument(capsys, scratch_dir):
    """Managed activation is opt-in only for direct executed runs without -mod."""
    cli = _load_cli_module()
    artifact = _make_artifact(scratch_dir / "artifact")
    user_dir = _make_hoi4_user_dir(scratch_dir / "hoi4-user")
    common = [
        "--artifact-dir", str(artifact),
        "--game-executable", sys.executable,
        "--activate-artifact",
        "--hoi4-user-dir", str(user_dir),
    ]

    assert cli.main(common) == 2  # no --execute
    assert "requires --execute" in capsys.readouterr().err
    assert cli.main([
        "--artifact-dir", str(artifact),
        "--game-executable", sys.executable,
        "--activate-artifact",
        "--execute",
    ]) == 2  # no user-data directory
    assert "requires --hoi4-user-dir" in capsys.readouterr().err
    assert cli.main([
        "--artifact-dir", str(artifact),
        "--hoi4-user-dir", str(user_dir),
    ]) == 2  # user-data option alone
    assert "only valid with --activate-artifact" in capsys.readouterr().err
    assert cli.main(common + ["--execute", "--launch-via", "steam", "--steam-executable", sys.executable]) == 2
    assert "direct launch or --launch-via steam --skip-launcher" in capsys.readouterr().err
    assert cli.main(common + ["--execute", "--game-arg=-mod", "--game-arg=mod/fantasy.mod"]) == 2
    assert "do not pass the unsupported -mod argument" in capsys.readouterr().err


@pytest.mark.parametrize("launch_kind", ["direct", "skip_launcher"])
def test_cli_managed_activation_stages_config_for_direct_launch(monkeypatch, scratch_dir, launch_kind):
    """The CLI wraps its direct launch in the activation transaction, without -mod."""
    cli = _load_cli_module()
    artifact = _make_artifact(scratch_dir / "artifact")
    descriptor_name = "BelgiumAcceptanceM10"
    (artifact / "descriptor.mod").write_text('name="%s"\n' % descriptor_name, encoding="utf-8")
    original = b'{"enabled_mods":["mod/fantasy.mod"],"disabled_dlcs":["dlc1"]}\r\n'
    user_dir = _make_hoi4_user_dir(scratch_dir / "hoi4-user", original)
    staged_path = user_dir / "mod" / harness.MANAGED_DESCRIPTOR_FILENAME
    output = scratch_dir / "result.json"
    captured = {}

    def fake_run_harness(**kwargs):
        captured.update(kwargs)
        settings = json.loads((user_dir / "dlc_load.json").read_text(encoding="utf-8"))
        assert settings["enabled_mods"] == ["mod/" + harness.MANAGED_DESCRIPTOR_FILENAME]
        assert settings["disabled_dlcs"] == ["dlc1"]
        assert staged_path.is_file()
        assert 'path="%s"' % artifact.resolve().as_posix() in staged_path.read_text(encoding="utf-8")
        return {
            "mode": "assisted",
            "status": "passed",
            "launch": {},
            "artifact": {},
            "logs": {},
            "saves": [],
            "checklist": [],
            "reasons": [],
        }

    monkeypatch.setattr(cli.harness, "run_harness", fake_run_harness)
    argv = [
        "--artifact-dir", str(artifact),
        "--activate-artifact",
        "--hoi4-user-dir", str(user_dir),
        "--output", str(output),
        "--execute",
    ]
    if launch_kind == "direct":
        argv.extend(["--launch-via", "direct", "--game-executable", sys.executable])
    else:
        target = scratch_dir / "game"
        target.mkdir()
        executable = target / "hoi4.exe"
        executable.write_bytes(b"test executable placeholder")
        monkeypatch.setattr(cli.harness, "discover_game_executable", lambda _target: str(executable))
        argv.extend(["--launch-via", "steam", "--skip-launcher", "--target", str(target)])

    assert cli.main(argv) == 0
    assert captured["managed_activation"] == {
        "descriptor_name": descriptor_name,
        "descriptor_reference": "mod/" + harness.MANAGED_DESCRIPTOR_FILENAME,
    }
    assert captured["log_paths"].count(str(user_dir / "logs" / "system.log")) == 1
    assert captured["launch_config"].executable
    assert all("-mod" not in argument.casefold() for argument in captured["launch_config"].args)
    if launch_kind == "skip_launcher":
        assert Path(captured["launch_config"].executable) == executable
        assert captured["launch_config"].wait_for_process == "hoi4.exe"
    assert (user_dir / "dlc_load.json").read_bytes() == original
    assert not staged_path.exists()
    assert output.is_file()


@pytest.mark.parametrize(("case", "initial_system_log", "fresh_system_log", "expected_status", "run_status"), [
    (
        "matched",
        "",
        "Active Mod Count: 1\nActive Mod: BelgiumAcceptanceM10\n",
        "matched",
        "passed",
    ),
    (
        "wrong_name",
        "",
        "Active Mod Count: 1\nActive Mod: Fantasy World\n",
        "mismatch",
        "failed",
    ),
    (
        "stale_only",
        "Active Mod Count: 1\nActive Mod: BelgiumAcceptanceM10\n",
        "",
        "missing",
        "failed",
    ),
    (
        "system_log_absent",
        "",
        None,
        "missing",
        "failed",
    ),
    (
        "count_mismatch",
        "",
        "Active Mod Count: 2\nActive Mod: BelgiumAcceptanceM10\n",
        "mismatch",
        "failed",
    ),
])
def test_managed_run_requires_exact_fresh_active_mod_evidence(
    case,
    initial_system_log,
    fresh_system_log,
    expected_status,
    run_status,
    scratch_dir,
    capsys,
):
    """Only fresh system.log records can prove one exact active descriptor name."""
    result = _run_managed_active_mod_probe(scratch_dir / case, initial_system_log, fresh_system_log)
    evidence = result["logs"]["active_mod"]

    assert evidence["required"] is True
    assert evidence["expected_name"] == "BelgiumAcceptanceM10"
    assert evidence["status"] == expected_status
    assert result["status"] == run_status
    if expected_status == "mismatch":
        assert any("expected exactly one active mod" in reason for reason in result["reasons"])
    if expected_status == "missing":
        assert any("fresh system.log lacks a complete" in reason for reason in result["reasons"])

    if expected_status == "matched":
        assert evidence["count"] == 1
        assert evidence["observed_names"] == ["BelgiumAcceptanceM10"]
        result_path = scratch_dir / "roundtrip" / "engine_acceptance.json"
        harness.write_result(result_path, result)
        loaded = harness.load_result(result_path)
        assert loaded["logs"]["active_mod"] == evidence
        cli = _load_cli_module()
        cli.print_summary(loaded, str(result_path))
        assert "active mod proof: status=matched" in capsys.readouterr().out


@pytest.mark.parametrize("launch_failure", ["missing_executable", "timeout"])
def test_cli_managed_activation_restores_after_launch_failure_or_timeout(scratch_dir, launch_failure):
    """Managed files are restored after the executed launch reports failure or timeout."""
    cli = _load_cli_module()
    artifact = _make_artifact(scratch_dir / "artifact")
    original = b'{"enabled_mods":["mod/fantasy.mod"],"disabled_dlcs":[]}\n'
    user_dir = _make_hoi4_user_dir(scratch_dir / "hoi4-user", original)
    staged_path = user_dir / "mod" / harness.MANAGED_DESCRIPTOR_FILENAME
    output = scratch_dir / "result.json"
    if launch_failure == "missing_executable":
        executable = str(scratch_dir / "does-not-exist.exe")
        game_args: list[str] = []
        timeout = "0"
    else:
        executable = sys.executable
        game_args = ["--game-arg=-c", "--game-arg=import time; time.sleep(2)"]
        timeout = "0.2"

    code = cli.main([
        "--artifact-dir", str(artifact),
        "--activate-artifact",
        "--hoi4-user-dir", str(user_dir),
        "--launch-via", "direct",
        "--game-executable", executable,
        "--timeout-seconds", timeout,
        "--output", str(output),
        "--execute",
    ] + game_args)

    assert code == 1
    result = harness.load_result(output)
    assert result["launch"]["status"] == ("launch_failed" if launch_failure == "missing_executable" else "timeout")
    assert (user_dir / "dlc_load.json").read_bytes() == original
    assert not staged_path.exists()


def test_cli_non_error_log_option_is_explicit(monkeypatch, scratch_dir):
    """The CLI opt-out is wired to the service as an explicit non-error log contract."""
    cli = _load_cli_module()
    artifact = _make_artifact(scratch_dir / "artifact")
    custom_log = scratch_dir / "setup.log"
    captured = {}

    def fake_run_harness(**kwargs):
        captured.update(kwargs)
        return {"status": "dry_run", "launch": {}}

    monkeypatch.setattr(cli.harness, "run_harness", fake_run_harness)
    code = cli.main([
        "--artifact-dir", str(artifact),
        "--game-executable", sys.executable,
        "--log", str(custom_log),
        "--allow-non-error-log-set",
        "--execute",
    ])

    assert code == 0
    assert captured["require_error_log"] is False
    assert captured["log_paths"] == [str(custom_log)]


def test_cli_prints_assisted_preflight_before_launch(monkeypatch, capsys, scratch_dir):
    """The human receives checks and evidence requirements before the blocking run starts."""
    cli = _load_cli_module()
    artifact = _make_artifact(scratch_dir / "artifact")
    error_log = scratch_dir / "logs" / "error.log"
    save_dir = scratch_dir / "saves"
    captured = {}

    def fake_run_harness(**_kwargs):
        captured["preflight"] = capsys.readouterr().out
        return {
            "run_id": "preflight-probe",
            "mode": "assisted",
            "status": "incomplete",
            "artifact": {},
            "launch": {"mode": "executed", "executed": False, "argv": []},
            "logs": {},
            "saves": [],
            "checklist": [],
            "reasons": ["preflight test result"],
        }

    monkeypatch.setattr(cli.harness, "run_harness", fake_run_harness)
    code = cli.main([
        "--artifact-dir", str(artifact),
        "--game-executable", sys.executable,
        "--log", str(error_log),
        "--save-dir", str(save_dir),
        "--save-name", "acceptance_save.hoi4",
        "--execute",
    ])

    assert code == 1
    preflight = captured["preflight"]
    assert "Assisted-session preflight" in preflight
    for check_id, title, _detail in contract.REQUIRED_CHECKS:
        assert "- [ ] %s: %s" % (check_id, title) in preflight
    assert "Required error.log policy" in preflight
    assert str(error_log) in preflight
    assert "acceptance_save.hoi4" in preflight
    assert str(save_dir) in preflight


def test_execute_collects_post_launch_log_error(scratch_dir):
    """An opt-in launch appending a fresh error fails without counting stale lines."""
    artifact = _make_artifact(scratch_dir / "artifact")
    log_path = _write_text(scratch_dir / "error.log", "[ERROR] stale pre-run province 2\n")
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
    assert result["logs"]["required_error_log"]["status"] == "generated"
    findings = result["logs"]["findings"]
    assert any("province 9" in item.get("text", "") for item in findings)
    assert all("stale pre-run" not in item.get("text", "") for item in findings)
    assert any(item.get("category") == "map" for item in findings)
    assert result["logs"]["summary"]["blocker_count"] >= 1


def test_execute_fails_when_error_log_is_missing(scratch_dir):
    """An executed acceptance cannot pass without a readable post-run error.log."""
    artifact = _make_artifact(scratch_dir / "artifact")
    error_log = scratch_dir / "logs" / "error.log"
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", "pass"), timeout_seconds=30.0)
    result = harness.run_harness(
        artifact,
        log_paths=[str(error_log)],
        launch_config=config,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
    )

    assert result["status"] == "failed"
    assert result["logs"]["required_error_log"]["status"] == "missing"
    assert any("error.log is missing" in reason for reason in result["reasons"])


def test_unchanged_pre_run_error_log_is_stale(scratch_dir):
    """A readable but unchanged old error.log does not satisfy the run contract."""
    artifact = _make_artifact(scratch_dir / "artifact")
    error_log = _write_text(scratch_dir / "error.log", "old log with no fresh evidence\n")
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", "pass"), timeout_seconds=30.0)
    result = harness.run_harness(
        artifact,
        log_paths=[str(error_log)],
        launch_config=config,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
    )

    assert result["status"] == "failed"
    assert result["logs"]["required_error_log"]["status"] == "stale"
    assert result["logs"]["findings"] == []
    assert any("not generated or modified" in reason for reason in result["reasons"])


def test_newly_created_empty_error_log_satisfies_run_contract(scratch_dir):
    """A newly created empty error.log is readable and proves the game generated it."""
    artifact = _make_artifact(scratch_dir / "artifact")
    error_log = scratch_dir / "error.log"
    code = "open(%r, 'wb').close()" % str(error_log)
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", code), timeout_seconds=30.0)
    result = harness.run_harness(
        artifact,
        log_paths=[str(error_log)],
        launch_config=config,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
    )

    assert result["status"] == "passed"
    assert result["logs"]["required_error_log"]["status"] == "generated"
    assert result["logs"]["files"][0]["status"] == "ok"
    assert result["logs"]["files"][0]["generated"] is True
    assert result["logs"]["files"][0]["fresh_bytes"] == 0


def test_rewritten_empty_error_log_satisfies_run_contract(scratch_dir):
    """Truncating a pre-existing error.log to empty is still a fresh rewrite."""
    artifact = _make_artifact(scratch_dir / "artifact")
    error_log = _write_text(scratch_dir / "error.log", "pre-run content that HOI4 will truncate\n")
    code = "open(%r, 'wb').close()" % str(error_log)
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", code), timeout_seconds=30.0)
    result = harness.run_harness(
        artifact,
        log_paths=[str(error_log)],
        launch_config=config,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
    )

    assert result["status"] == "passed"
    assert result["logs"]["required_error_log"]["status"] == "generated"
    assert result["logs"]["files"][0]["rewritten"] is True
    assert result["logs"]["files"][0]["fresh_bytes"] == 0


def test_rewritten_and_regrown_error_log_is_read_from_byte_zero(scratch_dir):
    """A replacement log larger than the old offset keeps its opening findings."""
    artifact = _make_artifact(scratch_dir / "artifact")
    error_log = _write_text(
        scratch_dir / "error.log",
        "[ERROR] stale pre-run province 8\n" + ("old filler line\n" * 5000),
    )
    old_size = error_log.stat().st_size
    new_prefix = "[ERROR] province 99 has no pixels in definition.csv\n"
    code = "open(%r, 'w', encoding='utf-8').write(%r + ('replacement padding ' * 10000))" % (str(error_log), new_prefix)
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", code), timeout_seconds=30.0)
    result = harness.run_harness(
        artifact,
        log_paths=[str(error_log)],
        launch_config=config,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
    )

    assert error_log.stat().st_size > old_size
    assert result["status"] == "failed"
    assert result["logs"]["required_error_log"]["status"] == "generated"
    assert result["logs"]["required_error_log"]["paths"][0]["rewritten"] is True
    assert any("province 99" in item["text"] for item in result["logs"]["findings"])
    assert all("stale pre-run" not in item["text"] for item in result["logs"]["findings"])


def test_execute_collects_post_launch_save(scratch_dir):
    """An opt-in launch creating a save after the snapshot records it fresh."""
    artifact = _make_artifact(scratch_dir / "artifact")
    save_dir = scratch_dir / "saves"
    save_dir.mkdir()
    target = save_dir / "acceptance_save.hoi4"
    error_log = scratch_dir / "error.log"
    assert not target.exists()
    code = "open(%r, 'w', encoding='utf-8').write('save-bytes'); open(%r, 'wb').close()" % (str(target), str(error_log))
    config = contract.LaunchConfig(executable=sys.executable, args=("-c", code), timeout_seconds=30.0)
    result = harness.run_harness(
        artifact,
        log_paths=[str(error_log)],
        save_dir=str(save_dir),
        save_names=["acceptance_save.hoi4"],
        launch_config=config,
        execute=True,
        checked=list(contract.REQUIRED_CHECK_IDS),
    )
    assert result["launch"]["executed"] is True
    assert result["logs"]["required_error_log"]["status"] == "generated"
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
