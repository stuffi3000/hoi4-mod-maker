"""Validator package with shared M3.1/M3.2a contracts."""
from domain.validation import (
    GATE_CONTEXTS,
    FINDING_SEVERITIES,
    SEVERITY_RANK,
    GateDecision,
    ValidationFinding,
    ValidationReport,
    ValidatorRegistry,
    coerce_finding,
    evaluate_gate,
)

__all__ = [
    "FINDING_SEVERITIES",
    "GATE_CONTEXTS",
    "SEVERITY_RANK",
    "GateDecision",
    "ValidationFinding",
    "ValidationReport",
    "ValidatorRegistry",
    "coerce_finding",
    "evaluate_gate",
]
