"""Focused M8 foundation-freeze tests."""
from __future__ import annotations
import copy
import json
import shutil
import uuid
from pathlib import Path
import pytest
from domain import foundation_freeze as freeze_contract
from domain.export_contract import WrittenFile
from services import foundation_freeze_service as freeze_service
from services.export_manifest import build_manifest_dict
from tests.export.test_m3_4_manifest import _base_plan
pytestmark = pytest.mark.unit
FIXED_AT = "2026-09-19T00:00:00+00:00"
@pytest.fixture
def m8_tmp(request, tmp_path_factory=None):
    import tempfile, os
    base = Path(tempfile.gettempdir()) / ("m8_freeze_%d_%s" % (os.getpid(), uuid.uuid4().hex[:8]))
    base.mkdir(parents=True, exist_ok=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)
def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
def _good_manifest_dict(**overrides):
    plan = _base_plan(**overrides) if overrides else _base_plan()
    manifest = build_manifest_dict(plan, [])
    assert manifest["validation"]["gate"]["allowed"] is True
    assert manifest["validation"]["gate"]["blocking"] == []
    return manifest
def _manifest_with_files():
    plan = _base_plan()
    files = [WrittenFile("map/provinces.bmp", 10, "a" * 64), WrittenFile("map/terrain.bmp", 10, "b" * 64), WrittenFile("map/buildings.txt", 5, "c" * 64), WrittenFile("map/supply_nodes.txt", 5, "d" * 64), WrittenFile("history/states/1-Foo.txt", 3, "e" * 64)]
    from domain.export_contract import StageResult
    stages = [__import__("domain.export_contract", fromlist=["StageResult"]).StageResult(stage="core_rasters", owned_files=("map/",), written=[WrittenFile("map/provinces.bmp", 10, "a" * 64), WrittenFile("map/terrain.bmp", 10, "b" * 64)]), __import__("domain.export_contract", fromlist=["StageResult"]).StageResult(stage="placements", owned_files=("map/buildings.txt",), written=[WrittenFile("map/buildings.txt", 5, "c" * 64)]), __import__("domain.export_contract", fromlist=["StageResult"]).StageResult(stage="logistics", owned_files=("map/supply_nodes.txt",), written=[WrittenFile("map/supply_nodes.txt", 5, "d" * 64)]), __import__("domain.export_contract", fromlist=["StageResult"]).StageResult(stage="state_geography", owned_files=("history/states/",), written=[WrittenFile("history/states/1-Foo.txt", 3, "e" * 64)])]
    return build_manifest_dict(plan, files, stages)
def test_expanded_lock_has_complete_fields_and_excludes_acceptance_values():
    manifest = _good_manifest_dict()
    manifest["asset_resolutions"] = [{"rel_path": "map/provinces.bmp", "disposition": "generated", "source_sha256": "a" * 64, "output_sha256": "b" * 64, "output_owner": "core_rasters", "profile_rule": "gen"}, {"rel_path": "history/countries/TST - Test.txt", "disposition": "generated", "source_sha256": "c" * 64, "output_sha256": "d" * 64, "output_owner": "acceptance_content", "profile_rule": "x"}, {"rel_path": "localisation/test_l_english.yml", "disposition": "generated", "source_sha256": "e" * 64, "output_sha256": "f" * 64, "output_owner": "acceptance_content", "profile_rule": "x"}, {"rel_path": "gfx/flags/TST.tga", "disposition": "generated", "source_sha256": "1" * 64, "output_sha256": "2" * 64, "output_owner": "acceptance_content", "profile_rule": "x"}]
    manifest["written_files"] = [{"rel_path": "map/provinces.bmp", "size": 10, "sha256": "a" * 64, "stage": "core_rasters"}, {"rel_path": "history/countries/TST - Test.txt", "size": 5, "sha256": "b" * 64, "stage": "acceptance_content"}]
    lock = freeze_service.build_expanded_lock(manifest, created_at=FIXED_AT)
    for key in ("lock_schema", "freeze_schema", "identity", "profile", "target", "project", "snapshot_fingerprint", "map_size", "sources", "counts", "geography", "assets", "outputs", "validation", "engine_acceptance", "history"):
        assert key in lock, key
    assert lock["profile"] == "foundation"
    assert lock["identity"]["identity_hash"] == manifest["identity"]["identity_hash"]
    assert lock["map_size"] == manifest["map_size"]
    assert lock["sources"]["arrays"] == manifest["sources"]["arrays"]
    assert "country_mgr" not in lock["sources"]["managers"]
    assert "assets" not in lock["sources"]["auxiliary"]
    assert "dirty_assets" not in lock["sources"]["auxiliary"]
    assert "country_mgr" not in lock["counts"]["managers"]
    assert lock["geography"]["province_ids"] == manifest["counts"]["province_ids"]
    assert "country_mgr" not in lock["geography"]["managers"]
    asset_paths = [a["rel_path"] for a in lock["assets"]]
    output_paths = [o["rel_path"] for o in lock["outputs"]]
    assert "map/provinces.bmp" in asset_paths
    assert not any(p.startswith("history/countries") or p.startswith("localisation") or p.startswith("gfx/flags") for p in asset_paths)
    assert not any(p.startswith("history/countries") or p.startswith("localisation") or p.startswith("gfx/flags") for p in output_paths)
    blob = json.dumps(lock, sort_keys=True)
    assert "history/countries" not in blob or "acceptance-only content" in freeze_service.generate_handoff(lock)
    assert "localisation/test_l_english.yml" not in blob
def test_expanded_lock_and_handoff_are_deterministic():
    manifest = _manifest_with_files()
    first = freeze_service.build_expanded_lock(manifest, created_at=FIXED_AT)
    second = freeze_service.build_expanded_lock(manifest, created_at=FIXED_AT)
    first_json = json.dumps(first, ensure_ascii=False, indent=2, sort_keys=True)
    second_json = json.dumps(second, ensure_ascii=False, indent=2, sort_keys=True)
    assert first_json == second_json
    assert freeze_service.freeze_canonical_json(first) == freeze_service.freeze_canonical_json(second)
    first_md = freeze_service.generate_handoff(first, manifest)
    second_md = freeze_service.generate_handoff(second, manifest)
    assert first_md == second_md


def test_foundation_export_writes_expanded_lock(m8_tmp):
    from services.export_service import export_planned_mod

    plan = _base_plan()
    result = export_planned_mod(plan, str(m8_tmp / "export"))
    lock = json.loads((Path(result.output_dir) / "foundation.lock.json").read_text(encoding="utf-8"))
    assert lock["freeze_schema"] == freeze_contract.FREEZE_SCHEMA
    assert lock["profile"] == "foundation"
    assert "country_mgr" not in lock["sources"]["managers"]
    assert "country_mgr" not in lock["counts"]["managers"]
    assert lock["outputs"]
def test_classify_each_change_class():
    cases = [("map_size.width", "breaking_identity", True), ("sources.arrays.province", "breaking_identity", True), ("identity.identity_hash", "breaking_identity", True), ("project.profile_id", "breaking_identity", True), ("sources.managers.state_mgr", "breaking_topology", True), ("counts.managers.state_mgr", "breaking_topology", True), ("outputs.map/supply_nodes.txt.size", "breaking_topology", True), ("outputs.history/states/1-Foo.txt.size", "breaking_topology", True), ("sources.arrays.terrain", "foundation_visual", False), ("sources.auxiliary.colormap_settings", "foundation_visual", False), ("outputs.map/terrain.bmp.sha256", "foundation_visual", False), ("assets.map/terrain.bmp.output_sha256", "foundation_visual", False), ("outputs.map/buildings.txt.sha256", "placement", False), ("outputs.map/positions.txt.size", "placement", False), ("counts.managers.country_mgr", "non_foundation_content", False), ("validation.accepted_keys", "non_foundation_content", False), ("engine_acceptance.status", "non_foundation_content", False), ("lifecycle", "non_foundation_content", False)]
    for path, expected_class, expected_breaking in cases:
        info = freeze_contract.classify_lock_path(path)
        assert info["change_class"] == expected_class, path
        assert info["breaking"] is expected_breaking, path
        assert info["rerun"] == freeze_contract.RERUN_GUIDANCE[expected_class]
        assert freeze_contract.explain_difference(path, "a", "b")
def _freeze_roundtrip(m8_tmp: Path, manifest: dict):
    manifest_path = _write_json(m8_tmp / "foundation_manifest.json", manifest)
    lock_path = m8_tmp / "foundation.lock.json"
    candidate = freeze_service.create_candidate(str(manifest_path), str(lock_path), created_at=FIXED_AT)
    assert candidate["ok"] is True, candidate["reasons"]
    frozen = freeze_service.freeze_foundation(str(manifest_path), str(lock_path), handoff_path=str(m8_tmp / "FOUNDATION-HANDOFF.md"), created_at=FIXED_AT)
    assert frozen["ok"] is True, frozen["reasons"]
    return manifest_path, lock_path
def test_compare_reports_breaking_and_rerun_guidance(m8_tmp):
    manifest = _manifest_with_files()
    manifest_path, lock_path = _freeze_roundtrip(m8_tmp, manifest)
    changed = copy.deepcopy(manifest)
    changed["map_size"] = {"width": int(manifest["map_size"]["width"]) + 8, "height": manifest["map_size"]["height"]}
    result = freeze_service.compare_with_frozen_lock(changed, str(lock_path))
    assert result["status"] == "breaking"
    assert result["breaking"] is True
    by_path = {d["path"]: d for d in result["differences"]}
    assert "map_size.width" in by_path
    assert by_path["map_size.width"]["change_class"] == "breaking_identity"
    assert by_path["map_size.width"]["breaking"] is True
    assert by_path["map_size.width"]["rerun"]
    topo = copy.deepcopy(manifest)
    topo_sources = copy.deepcopy(topo["sources"])
    topo_sources["managers"]["state_mgr"] = "deadbeef"
    topo["sources"] = topo_sources
    topo_result = freeze_service.compare_with_frozen_lock(topo, str(lock_path))
    assert topo_result["status"] == "breaking"
    assert any(d["change_class"] == "breaking_topology" and d["breaking"] for d in topo_result["differences"])
    visual = copy.deepcopy(manifest)
    visual_sources = copy.deepcopy(visual["sources"])
    visual_sources["arrays"]["terrain"] = "00" * 32
    visual["sources"] = visual_sources
    visual_result = freeze_service.compare_with_frozen_lock(visual, str(lock_path))
    assert visual_result["status"] in ("mismatch", "breaking")
    visual_diffs = [d for d in visual_result["differences"] if d["path"] == "sources.arrays.terrain"]
    assert visual_diffs and visual_diffs[0]["change_class"] == "foundation_visual" and not visual_diffs[0]["breaking"]
    placement = copy.deepcopy(manifest)
    for entry in placement["written_files"]:
        if entry["rel_path"] == "map/buildings.txt":
            entry["sha256"] = "f" * 64
    placement_result = freeze_service.compare_with_frozen_lock(placement, str(lock_path))
    placement_diffs = [d for d in placement_result["differences"] if "buildings" in d["path"]]
    assert placement_diffs and placement_diffs[0]["change_class"] == "placement" and not placement_diffs[0]["breaking"]
    content = copy.deepcopy(manifest)
    content_counts = copy.deepcopy(content["counts"])
    content_counts["managers"]["country_mgr"] = int(content_counts["managers"].get("country_mgr", 0) or 0) + 5
    content["counts"] = content_counts
    content_result = freeze_service.compare_with_frozen_lock(content, str(lock_path))
    assert content_result["differences"] == []
    assert content_result["status"] == "compatible"
    assert content_result["breaking"] is False
def test_compare_is_compatible_when_unchanged(m8_tmp):
    manifest = _good_manifest_dict()
    manifest_path, lock_path = _freeze_roundtrip(m8_tmp, manifest)
    result = freeze_service.compare_with_frozen_lock(str(manifest_path), str(lock_path))
    assert result["status"] == "compatible"
    assert result["differences"] == []
    assert result["breaking"] is False
def test_candidate_gates(m8_tmp):
    manifest = _good_manifest_dict()
    manifest_path = _write_json(m8_tmp / "a.json", manifest)
    lock_path = m8_tmp / "a.lock.json"
    ok_result = freeze_service.create_candidate(str(manifest_path), str(lock_path), created_at=FIXED_AT)
    assert ok_result["ok"] is True
    assert Path(lock_path).is_file()
    stored = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    assert stored["lifecycle"] == "candidate"
    blocked_manifest = copy.deepcopy(manifest)
    blocked_manifest["validation"]["gate"]["allowed"] = False
    blocked_manifest["validation"]["gate"]["blocking"] = [{"code": "map.broken"}]
    blocked_path = _write_json(m8_tmp / "blocked.json", blocked_manifest)
    blocked = freeze_service.create_candidate(str(blocked_path), str(m8_tmp / "blocked.lock.json"), created_at=FIXED_AT)
    assert blocked["ok"] is False
    assert blocked["reasons"]
    assert not Path(m8_tmp / "blocked.lock.json").exists()
    _plan_nf = _base_plan(profile_name="acceptance")
    non_foundation = build_manifest_dict(_plan_nf, [])
    non_path = _write_json(m8_tmp / "non.json", non_foundation)
    rejected = freeze_service.create_candidate(str(non_path), str(m8_tmp / "non.lock.json"), created_at=FIXED_AT)
    assert rejected["ok"] is False
    assert any("foundation" in r for r in rejected["reasons"])


def test_candidate_requires_exact_artifact_manifest_when_directory_is_supplied(m8_tmp):
    manifest = _good_manifest_dict()
    manifest_path = _write_json(m8_tmp / "source.json", manifest)
    artifact_dir = m8_tmp / "artifact"
    artifact_dir.mkdir()
    missing = freeze_service.create_candidate(
        str(manifest_path),
        str(m8_tmp / "missing.lock.json"),
        artifact_dir=str(artifact_dir),
        created_at=FIXED_AT,
    )
    assert missing["ok"] is False
    assert any("manifest is missing" in reason for reason in missing["reasons"])
    _write_json(artifact_dir / "foundation_manifest.json", manifest)
    present = freeze_service.create_candidate(
        str(manifest_path),
        str(m8_tmp / "present.lock.json"),
        artifact_dir=str(artifact_dir),
        created_at=FIXED_AT,
    )
    assert present["ok"] is True
def test_freeze_gates_and_exact_identity(m8_tmp):
    manifest = _good_manifest_dict()
    manifest_path = _write_json(m8_tmp / "foundation_manifest.json", manifest)
    lock_path = m8_tmp / "foundation.lock.json"
    direct = freeze_service.freeze_foundation(str(manifest_path), str(lock_path), handoff_path=str(m8_tmp / "FOUNDATION-HANDOFF.md"), created_at=FIXED_AT)
    assert direct["ok"] is False
    assert any("candidate" in r for r in direct["reasons"])
    candidate = freeze_service.create_candidate(str(manifest_path), str(lock_path), created_at=FIXED_AT)
    assert candidate["ok"] is True
    drifted = copy.deepcopy(manifest)
    drifted["snapshot_fingerprint"] = "0" * 64
    drifted_path = _write_json(m8_tmp / "drifted.json", drifted)
    mismatch = freeze_service.freeze_foundation(str(drifted_path), str(lock_path), handoff_path=str(m8_tmp / "FOUNDATION-HANDOFF.md"), created_at=FIXED_AT)
    assert mismatch["ok"] is False
    assert any("identity" in r for r in mismatch["reasons"])
    frozen = freeze_service.freeze_foundation(str(manifest_path), str(lock_path), handoff_path=str(m8_tmp / "FOUNDATION-HANDOFF.md"), created_at=FIXED_AT)
    assert frozen["ok"] is True
    stored = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    assert stored["lifecycle"] == "frozen"
    assert Path(frozen["handoff_path"]).is_file()
def test_freeze_acceptance_consistency(m8_tmp):
    manifest = _good_manifest_dict()
    manifest_path = _write_json(m8_tmp / "foundation_manifest.json", manifest)
    lock_path = m8_tmp / "foundation.lock.json"
    assert freeze_service.create_candidate(str(manifest_path), str(lock_path), created_at=FIXED_AT)["ok"] is True
    identity = manifest["identity"]["identity_hash"]
    good_acceptance = {"schema": "engine-acceptance/1", "run_id": "abc123", "identity_hash": "run-hash", "identity_core": {"manifest_identity": identity}, "status": "passed", "artifact": {"manifest": {"identity_hash": identity}}}
    good_path = _write_json(m8_tmp / "engine_acceptance.json", good_acceptance)
    frozen = freeze_service.freeze_foundation(str(manifest_path), str(lock_path), acceptance_path=str(good_path), handoff_path=str(m8_tmp / "FOUNDATION-HANDOFF.md"), created_at=FIXED_AT)
    assert frozen["ok"] is True, frozen["reasons"]
    stored = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    assert stored["engine_acceptance"]["present"] is True
    assert freeze_service.create_candidate(str(manifest_path), str(m8_tmp / "second.lock.json"), created_at=FIXED_AT)["ok"] is True
    bad_acceptance = {"schema": "engine-acceptance/1", "run_id": "bad", "identity_hash": "run-hash", "identity_core": {"manifest_identity": "0" * 64}, "status": "passed", "artifact": {"manifest": {"identity_hash": "0" * 64}}}
    bad_path = _write_json(m8_tmp / "bad_acceptance.json", bad_acceptance)
    second_manifest = copy.deepcopy(manifest)
    second_path = _write_json(m8_tmp / "second_manifest.json", second_manifest)
    assert freeze_service.create_candidate(str(second_path), str(m8_tmp / "third.lock.json"), created_at=FIXED_AT)["ok"] is True
    bad_freeze = freeze_service.freeze_foundation(str(second_path), str(m8_tmp / "third.lock.json"), acceptance_path=str(bad_path), handoff_path=str(m8_tmp / "third.md"), created_at=FIXED_AT)
    assert bad_freeze["ok"] is False
    assert any("acceptance" in r for r in bad_freeze["reasons"])

    failed_acceptance = dict(good_acceptance)
    failed_acceptance["status"] = "failed"
    failed_path = _write_json(m8_tmp / "failed_acceptance.json", failed_acceptance)
    assert freeze_service.create_candidate(str(second_path), str(m8_tmp / "failed.lock.json"), created_at=FIXED_AT)["ok"] is True
    failed_freeze = freeze_service.freeze_foundation(
        str(second_path),
        str(m8_tmp / "failed.lock.json"),
        acceptance_path=str(failed_path),
        handoff_path=str(m8_tmp / "failed.md"),
        created_at=FIXED_AT,
    )
    assert failed_freeze["ok"] is False
    assert any("not successful" in reason for reason in failed_freeze["reasons"])


def test_record_engine_acceptance_requires_frozen_exact_lock(m8_tmp):
    manifest = _good_manifest_dict()
    manifest_path, lock_path = _freeze_roundtrip(m8_tmp, manifest)
    identity = manifest["identity"]["identity_hash"]
    acceptance = {
        "schema": "engine-acceptance/1",
        "run_id": "run-1",
        "identity_hash": "acceptance-hash",
        "identity_core": {
            "manifest_identity": identity,
            "lock_identity": identity,
        },
        "status": "passed",
    }
    acceptance_path = _write_json(m8_tmp / "record.json", acceptance)
    result = freeze_service.record_engine_acceptance(
        str(lock_path),
        str(manifest_path),
        str(acceptance_path),
        created_at=FIXED_AT,
    )
    assert result["ok"] is True, result["reasons"]
    stored = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    assert stored["engine_acceptance"]["status"] == "passed"
    assert stored["engine_acceptance"]["lock_identity"] == identity
    assert any(event.get("event") == "record_engine_acceptance" for event in stored["history"])
    comparison = freeze_service.compare_with_frozen_lock(str(manifest_path), str(lock_path))
    assert comparison["status"] == "compatible"

    candidate_path = m8_tmp / "candidate.lock.json"
    assert freeze_service.create_candidate(str(manifest_path), str(candidate_path), created_at=FIXED_AT)["ok"] is True
    rejected = freeze_service.record_engine_acceptance(
        str(candidate_path),
        str(manifest_path),
        str(acceptance_path),
        created_at=FIXED_AT,
    )
    assert rejected["ok"] is False
    assert any("frozen" in reason for reason in rejected["reasons"])
def test_unfreeze_requires_reason_and_audits(m8_tmp):
    manifest = _good_manifest_dict()
    manifest_path, lock_path = _freeze_roundtrip(m8_tmp, manifest)
    with pytest.raises(freeze_service.FoundationFreezeError):
        freeze_service.unfreeze_lock(str(lock_path), "   ")
    before = Path(lock_path).read_bytes()
    before_lock = json.loads(before.decode("utf-8"))
    before_identity = before_lock["identity"]["identity_hash"]
    audit_path = m8_tmp / "audit.json"
    result = freeze_service.unfreeze_lock(str(lock_path), "rework provinces", audit_path=str(audit_path), created_at=FIXED_AT)
    assert result["ok"] is True
    assert result["reason"] == "rework provinces"
    after_lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    assert after_lock["lifecycle"] == "candidate"
    assert after_lock["identity"]["identity_hash"] == before_identity
    assert after_lock["sources"] == before_lock["sources"]
    assert any(e.get("reason") == "rework provinces" for e in after_lock.get("history", []))
    audit = json.loads(Path(audit_path).read_text(encoding="utf-8"))
    assert any(e.get("reason") == "rework provinces" for e in audit)
    second = freeze_service.unfreeze_lock(str(lock_path), "again", audit_path=str(audit_path), created_at=FIXED_AT)
    assert second["ok"] is False
def test_handoff_contains_required_sections(m8_tmp):
    manifest = _good_manifest_dict()
    manifest_path, lock_path = _freeze_roundtrip(m8_tmp, manifest)
    handoff_path = m8_tmp / "FOUNDATION-HANDOFF.md"
    assert handoff_path.is_file()
    text = handoff_path.read_text(encoding="utf-8")
    for heading in ("## Target, profile, version, and dependencies", "## Dimensions and stable ID ranges", "## Ownership and inheritance", "## Accepted exceptions", "## Geography versus content boundary", "## Author reference rules", "## Prohibited post-freeze operations", "## Change and migration procedure"):
        assert heading in text, heading
    assert manifest["identity"]["identity_hash"] in text
def test_malformed_missing_and_identityless_inputs_are_rejected(m8_tmp):
    missing = m8_tmp / "does-not-exist.json"
    with pytest.raises(freeze_service.FoundationFreezeError):
        freeze_service.load_manifest(str(missing))
    with pytest.raises(freeze_service.FoundationFreezeError):
        freeze_service.load_lock(str(missing))
    malformed = m8_tmp / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    with pytest.raises(freeze_service.FoundationFreezeError):
        freeze_service.load_manifest(str(malformed))
    no_identity = {"profile": "foundation", "map_size": {"width": 1, "height": 1}, "identity": {}}
    no_identity_path = _write_json(m8_tmp / "no_identity.json", no_identity)
    with pytest.raises(freeze_service.FoundationFreezeError):
        freeze_service.load_manifest(str(no_identity_path))
    with pytest.raises(freeze_service.FoundationFreezeError):
        freeze_service.load_lock(str(no_identity_path))
    not_object = m8_tmp / "list.json"
    not_object.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(freeze_service.FoundationFreezeError):
        freeze_service.load_manifest(str(not_object))
    with pytest.raises(freeze_service.FoundationFreezeError):
        freeze_service.compare_with_frozen_lock([], {})
def test_cli_help_and_exit_behavior(m8_tmp):
    from tools import foundation_freeze as cli
    parser = cli.build_parser()
    assert {"candidate", "freeze", "record-acceptance", "compare", "unfreeze", "handoff"} <= {"candidate", "freeze", "record-acceptance", "compare", "unfreeze", "handoff"}
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0
    manifest = _good_manifest_dict()
    manifest_path = _write_json(m8_tmp / "foundation_manifest.json", manifest)
    lock_path = m8_tmp / "foundation.lock.json"
    assert cli.main(["candidate", "--manifest", str(manifest_path), "--lock", str(lock_path), "--format", "json"]) == 0
    assert cli.main(["compare", "--manifest", str(manifest_path), "--lock", str(lock_path), "--format", "json"]) == 0
    drifted = copy.deepcopy(manifest)
    drifted["map_size"] = {"width": 9999, "height": 9999}
    drifted_path = _write_json(m8_tmp / "drifted.json", drifted)
    assert cli.main(["compare", "--manifest", str(drifted_path), "--lock", str(lock_path)]) == 1
    assert cli.main(["candidate", "--manifest", str(m8_tmp / "missing.json"), "--lock", str(m8_tmp / "out.json")]) == 2
    blocked = copy.deepcopy(manifest)
    blocked["validation"]["gate"]["allowed"] = False
    blocked["validation"]["gate"]["blocking"] = [{"code": "x.bad"}]
    blocked_path = _write_json(m8_tmp / "blocked.json", blocked)
    assert cli.main(["candidate", "--manifest", str(blocked_path), "--lock", str(m8_tmp / "blocked.lock.json")]) == 1
    assert cli.main(["freeze", "--manifest", str(manifest_path), "--lock", str(lock_path), "--handoff", str(m8_tmp / "FOUNDATION-HANDOFF.md")]) == 0
    identity = manifest["identity"]["identity_hash"]
    acceptance_path = _write_json(m8_tmp / "cli-acceptance.json", {"run_id": "cli-run", "identity_hash": "cli-hash", "identity_core": {"manifest_identity": identity, "lock_identity": identity}, "status": "passed"})
    assert cli.main(["record-acceptance", "--manifest", str(manifest_path), "--lock", str(lock_path), "--acceptance", str(acceptance_path), "--format", "json"]) == 0
    assert cli.main(["unfreeze", "--lock", str(lock_path), "--reason", "cli check", "--audit", str(m8_tmp / "cli-audit.json")]) == 0
    assert cli.main(["unfreeze", "--lock", str(lock_path), "--reason", "   "]) == 2
    assert cli.main(["handoff", "--lock", str(m8_tmp / "missing-lock.json"), "--output", str(m8_tmp / "out.md")]) == 2
