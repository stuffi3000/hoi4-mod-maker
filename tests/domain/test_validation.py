"""M3.1 shared validation contract, registry, and gate-policy tests."""
from __future__ import annotations

import copy

import pytest

from domain.export_contract import ValidationNote
from domain.validation import (
    GATE_CONTEXTS,
    GateDecision,
    ValidationFinding,
    ValidatorRegistry,
    coerce_finding,
    evaluate_gate,
)
from domain.validators import ValidationFinding as ReexportedFinding

pytestmark = pytest.mark.unit


def _finding(
    code: str = "raster.definition",
    severity: str = "error",
    **overrides,
) -> ValidationFinding:
    """Build a representative finding with portable test metadata."""
    payload = {
        "code": code,
        "severity": severity,
        "message": "Representative %s %s" % (code, severity),
        "layer": "provinces",
        "path": "map/provinces.bmp",
        "affected_ids": (1, 2),
        "coordinates": ((3, 4),),
        "evidence": "two pixels map to one definition",
        "repair_code": "province.compact_ids",
        "action": "open-province-page",
    }
    payload.update(overrides)
    return ValidationFinding(**payload)


def test_validator_package_reexports_shared_contract():
    """The validators package exposes the same shared finding contract."""
    assert ReexportedFinding is ValidationFinding


def test_finding_serialization_round_trip():
    """Every finding field survives a dict round trip unchanged."""
    original = _finding(
        waivable=True,
        exception_id="waiver-7",
        exception_reason="Island province is intentional",
        reviewed_by="reviewer",
        reviewed_at="2026-09-17T00:00:00+00:00",
    )
    payload = original.to_dict()
    assert payload["code"] == "raster.definition"
    assert payload["severity"] == "error"
    assert payload["path"] == "map/provinces.bmp"
    assert payload["affected_ids"] == [1, 2]
    assert payload["coordinates"] == [[3, 4]]
    assert payload["waivable"] is True
    assert payload["exception_id"] == "waiver-7"
    restored = ValidationFinding.from_dict(payload)
    assert restored == original
    assert restored.to_dict() == payload


def test_finding_rejects_machine_specific_paths_and_bad_metadata():
    """Absolute paths and unknown severities are rejected at construction."""
    with pytest.raises(ValueError):
        _finding(path="C:/Users/tester/mod/map/provinces.bmp")
    with pytest.raises(ValueError):
        _finding(path="/abs/mod/map/provinces.bmp")
    with pytest.raises(ValueError):
        _finding(path="../outside.bmp")
    with pytest.raises(ValueError):
        _finding(severity="fatal")
    with pytest.raises(ValueError):
        ValidationFinding(code="", severity="error", message="missing code")
    with pytest.raises(ValueError):
        ValidationFinding(code="raster.x", severity="error", message="   ")
    with pytest.raises(ValueError):
        ValidationFinding.from_dict({"code": "raster.x", "severity": "error"})


def test_finding_repair_and_acceptance_helpers():
    """Repair presence and acceptance copies behave immutably."""
    plain = _finding(repair_code="")
    assert plain.has_repair is False
    assert plain.is_accepted is False
    repaired = _finding()
    assert repaired.has_repair is True
    waived = repaired.with_acceptance("waiver-1", reason="Reviewed island")
    assert waived.is_accepted is True
    assert waived.exception_id == "waiver-1"
    assert waived.exception_reason == "Reviewed island"
    assert repaired.is_accepted is False
    with pytest.raises(ValueError):
        repaired.with_acceptance("   ")


def test_finding_preserves_validation_note_compatibility():
    """Legacy notes convert both directions without losing core fields."""
    note = ValidationNote(code="state.empty", severity="warning", message="No states", layer="states")
    converted = ValidationFinding.from_validation_note(note)
    assert converted.code == "state.empty"
    assert converted.severity == "warning"
    assert converted.message == "No states"
    assert converted.layer == "states"
    assert coerce_finding(note) == converted
    assert coerce_finding(converted) is converted
    round_note = converted.to_validation_note()
    assert isinstance(round_note, ValidationNote)
    assert round_note.code == note.code
    assert round_note.severity == note.severity
    assert round_note.message == note.message
    assert round_note.layer == note.layer
    assert ValidationFinding.from_dict(converted.to_dict()) == converted


def test_registry_runs_in_sorted_order_deterministically():
    """Registration order does not affect deterministic execution order."""
    def _alpha_validator():
        return [_finding(code="alpha.check", severity="info", message="alpha")]

    def _beta_validator():
        return [_finding(code="beta.check", severity="info", message="beta")]

    first_registry = ValidatorRegistry()
    first_registry.register("beta.check", _beta_validator)
    first_registry.register("alpha.check", _alpha_validator)
    second_registry = ValidatorRegistry()
    second_registry.register("alpha.check", _alpha_validator)
    second_registry.register("beta.check", _beta_validator)
    assert first_registry.names == ("alpha.check", "beta.check")
    assert second_registry.names == ("alpha.check", "beta.check")
    first_codes = [found.code for found in first_registry.run()]
    second_codes = [found.code for found in second_registry.run()]
    assert first_codes == ["alpha.check", "beta.check"]
    assert second_codes == first_codes


def test_registry_decorator_duplicate_and_aggregate_behavior(capsys):
    """Registry aggregates iterables, singletons, and mappings quietly."""
    registry = ValidatorRegistry()

    @registry.register("decorated.check")
    def _decorated_validator(inputs):
        assert inputs == {"marker": 1}
        return [_finding(code="decorated.check", severity="warning", message="decorated")]

    def _singleton_validator(inputs):
        return _finding(code="singleton.check", severity="info", message="singleton")

    def _mapping_validator(inputs):
        return {
            "code": "mapping.check",
            "severity": "info",
            "message": "mapping finding",
        }

    def _empty_validator(inputs):
        return None

    registry.register("singleton.check", _singleton_validator)
    registry.register("mapping.check", _mapping_validator)
    registry.register("empty.check", _empty_validator)
    with pytest.raises(ValueError):
        registry.register("decorated.check", _decorated_validator)
    assert len(registry) == 4
    assert "decorated.check" in registry
    caller_inputs = {"marker": 1}
    snapshot_inputs = copy.deepcopy(caller_inputs)
    aggregated = registry.run(caller_inputs)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert caller_inputs == snapshot_inputs
    assert [found.code for found in aggregated] == [
        "decorated.check",
        "mapping.check",
        "singleton.check",
    ]
    assert all(isinstance(found, ValidationFinding) for found in aggregated)
    assert registry.unregister("empty.check") is True
    assert "empty.check" not in registry
    assert registry.unregister("empty.check") is False


def test_gate_exposes_all_required_contexts():
    """All five plan contexts are explicitly represented."""
    assert set(GATE_CONTEXTS) == {
        "draft_preview",
        "foundation_candidate",
        "freeze",
        "acceptance",
        "accepted_lock",
    }
    with pytest.raises(ValueError):
        evaluate_gate([], "unknown_context")


def test_gate_draft_preview_reports_without_blocking():
    """Draft preview never blocks, even for errors and blockers."""
    findings = [
        _finding(code="province.empty", severity="blocker", message="No provinces"),
        _finding(code="map.dimensions", severity="error", message="Bad size"),
        _finding(code="state.empty", severity="warning", message="No states"),
        _finding(code="country.omitted", severity="info", message="Foundation omits countries"),
    ]
    decision = evaluate_gate(findings, "draft_preview")
    assert isinstance(decision, GateDecision)
    assert decision.context == "draft_preview"
    assert decision.allowed is True
    assert decision.blocking == ()
    assert [warn.code for warn in decision.visible_warnings] == ["state.empty"]
    assert decision.waived == ()


def test_gate_candidate_blocks_errors_but_keeps_warnings_visible():
    """Candidate publication blocks on errors while warnings stay visible."""
    findings = [
        _finding(code="map.dimensions", severity="error", message="Bad size"),
        _finding(code="province.empty", severity="blocker", message="No provinces"),
        _finding(code="state.empty", severity="warning", message="No states"),
        _finding(code="country.omitted", severity="info", message="FYI"),
    ]
    decision = evaluate_gate(findings, "foundation_candidate")
    assert decision.allowed is False
    assert {found.code for found in decision.blocking} == {"map.dimensions", "province.empty"}
    assert [found.code for found in decision.visible_warnings] == ["state.empty"]
    clean = evaluate_gate(findings[2:], "foundation_candidate")
    assert clean.allowed is True
    assert clean.blocking == ()
    assert [found.code for found in clean.visible_warnings] == ["state.empty"]


def test_gate_acceptance_blocks_relevant_errors_and_retains_warnings():
    """Acceptance blocks generation on errors without hiding warnings."""
    findings = [
        _finding(code="map.dimensions", severity="error", message="Bad size"),
        _finding(code="state.empty", severity="warning", message="No states"),
    ]
    decision = evaluate_gate(findings, "acceptance")
    assert decision.allowed is False
    assert [found.code for found in decision.blocking] == ["map.dimensions"]
    assert [found.code for found in decision.visible_warnings] == ["state.empty"]
    warnings_only = evaluate_gate(findings[1:], "acceptance")
    assert warnings_only.allowed is True
    assert warnings_only.blocking == ()


def test_gate_freeze_blocks_warnings_unless_explicitly_waived():
    """Freeze requires warnings to be resolved or accepted with reason."""
    warning = _finding(code="state.empty", severity="warning", message="No states")
    blocked = evaluate_gate([warning], "freeze")
    assert blocked.allowed is False
    assert [found.code for found in blocked.blocking] == ["state.empty"]
    assert blocked.visible_warnings == ()
    non_waivable = warning.with_acceptance(
        "waiver-1", reason="Reviewed", reviewed_at="2026-09-17T00:00:00+00:00"
    )
    still_blocked = evaluate_gate([non_waivable], "freeze", accepted={"waiver-1"})
    assert still_blocked.allowed is False
    waivable_unreasoned = ValidationFinding(
        code="state.empty",
        severity="warning",
        message="No states",
        waivable=True,
    ).with_acceptance("waiver-2", reviewed_at="2026-09-17T00:00:00+00:00")
    missing_reason = evaluate_gate([waivable_unreasoned], "freeze", accepted={"waiver-2"})
    assert missing_reason.allowed is False
    waivable_reasoned = ValidationFinding(
        code="state.empty",
        severity="warning",
        message="No states",
        waivable=True,
    ).with_acceptance(
        "waiver-3",
        reason="Intentional for this fixture",
        reviewed_at="2026-09-17T00:00:00+00:00",
    )
    accepted_decision = evaluate_gate([waivable_reasoned], "freeze", accepted={"waiver-3"})
    assert accepted_decision.allowed is True
    assert accepted_decision.blocking == ()
    assert [found.code for found in accepted_decision.waived] == ["state.empty"]


def test_gate_accepted_lock_permits_only_recorded_warning_exceptions():
    """Accepted lock forbids errors entirely and warnings unless recorded."""
    warning = ValidationFinding(
        code="logistics.island",
        severity="warning",
        message="Isolated network",
        waivable=True,
    ).with_acceptance(
        "island-1",
        reason="Intentional island",
        reviewed_by="qa",
        reviewed_at="2026-09-17T00:00:00+00:00",
    )
    accepted_warning = evaluate_gate([warning], "accepted_lock", accepted={"island-1"})
    assert accepted_warning.allowed is True
    assert accepted_warning.blocking == ()
    assert [found.code for found in accepted_warning.waived] == ["logistics.island"]
    unrecorded = evaluate_gate([warning], "accepted_lock", accepted={"other-waiver"})
    assert unrecorded.allowed is False
    assert [found.code for found in unrecorded.blocking] == ["logistics.island"]
    assert unrecorded.waived == ()
    plain_warning = _finding(code="state.empty", severity="warning", message="No states")
    assert evaluate_gate([plain_warning], "accepted_lock").allowed is False
    blocker = _finding(code="province.empty", severity="blocker", message="No provinces")
    blocker_waived = blocker.with_acceptance("blocker-1", reason="Should not excuse blockers")
    assert evaluate_gate([blocker_waived], "accepted_lock", accepted={"blocker-1"}).allowed is False
    error = _finding(code="map.dimensions", severity="error", message="Bad size")
    error_waived = error.with_acceptance(
        "error-1",
        reason="Should not excuse errors",
        reviewed_at="2026-09-17T00:00:00+00:00",
    )
    assert evaluate_gate([error_waived], "accepted_lock", accepted={"error-1"}).allowed is False


def test_gate_accepted_exceptions_require_recorded_keys():
    """Only waivers present in the accepted record excuse candidate findings."""
    error = _finding(code="map.dimensions", severity="error", message="Bad size")
    waived_error = error.with_acceptance(
        "size-1", reason="Tested custom size", reviewed_at="2026-09-17T00:00:00+00:00"
    )
    assert evaluate_gate([waived_error], "foundation_candidate").allowed is False
    assert evaluate_gate([waived_error], "foundation_candidate", accepted={"other"}).allowed is False
    by_id = evaluate_gate([waived_error], "foundation_candidate", accepted={"size-1"})
    assert by_id.allowed is False
    assert [found.code for found in by_id.blocking] == ["map.dimensions"]
    by_code = evaluate_gate([waived_error], "foundation_candidate", accepted={"map.dimensions"})
    assert by_code.allowed is False
    legacy_shape = [{"code": "map.dimensions", "reason": "Recorded in project meta"}]
    legacy = evaluate_gate([error], "foundation_candidate", accepted=legacy_shape)
    assert legacy.allowed is False
    assert [found.code for found in legacy.blocking] == ["map.dimensions"]
    accepted_warning = _finding(code="state.empty", severity="warning", message="No states").with_acceptance(
        "state-1", reason="Intentional", reviewed_at="2026-09-17T00:00:00+00:00"
    )
    acceptance = evaluate_gate([accepted_warning], "acceptance", accepted={"state-1"})
    assert acceptance.allowed is True
    assert [found.code for found in acceptance.visible_warnings] == ["state.empty"]
    assert acceptance.waived == ()


def test_gate_decision_serializes_without_machine_paths():
    """Gate decisions serialize findings without absolute filesystem paths."""
    findings = [_finding(), _finding(code="state.empty", severity="warning", message="No states")]
    decision = evaluate_gate(findings, "foundation_candidate")
    payload = decision.to_dict()
    assert payload["context"] == "foundation_candidate"
    assert payload["allowed"] is False
    assert len(payload["blocking"]) == 1
    assert len(payload["visible_warnings"]) == 1
    assert payload["waived"] == []
    for section in ("blocking", "visible_warnings", "waived"):
        for entry in payload[section]:
            assert entry["path"] == "map/provinces.bmp"
            assert "C:" not in entry["path"]
            assert not entry["path"].startswith("/")
