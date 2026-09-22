"""Foundation-freeze CLI (M8).

Source-control-friendly JSON and text output with subcommands for
candidate, freeze, compare, unfreeze, and handoff. Safe by default: no
process launch, no network, and no deletion. Explicit paths only.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from domain import foundation_freeze as freeze_contract
from services import foundation_freeze_service as freeze_service
EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_USAGE = 2
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="foundation_freeze", description="Foundation freeze, diff, and content handoff (M8). Safe by default: no process launch, no network, no deletion.")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format (default: text).")
    sub = parser.add_subparsers(dest="command", required=True)
    p_candidate = sub.add_parser("candidate", help="Create a foundation candidate lock after the validation gate passes.")
    p_candidate.add_argument("--manifest", required=True, type=Path, help="Path to foundation_manifest.json.")
    p_candidate.add_argument("--lock", required=True, type=Path, help="Path to write foundation.lock.json.")
    p_candidate.add_argument("--artifact-dir", type=Path, default=None, help="Artifact directory holding the exported mod.")
    p_candidate.add_argument("--created-at", default=None, help="Override created_at timestamp (for deterministic output).")
    p_candidate.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS, help="Output format (overrides global).")
    p_freeze = sub.add_parser("freeze", help="Freeze a candidate lock and write FOUNDATION-HANDOFF.md.")
    p_freeze.add_argument("--manifest", required=True, type=Path, help="Path to foundation_manifest.json.")
    p_freeze.add_argument("--lock", required=True, type=Path, help="Path to the candidate lock (overwritten as frozen).")
    p_freeze.add_argument("--artifact-dir", type=Path, default=None, help="Artifact directory holding the exported mod.")
    p_freeze.add_argument("--acceptance", type=Path, default=None, help="Path to engine_acceptance.json or its directory.")
    p_freeze.add_argument("--acceptance-manifest", type=Path, default=None, help="Legacy bridge: unchanged acceptance foundation_manifest.json captured by the acceptance report.")
    p_freeze.add_argument("--handoff", type=Path, default=None, help="Path to write FOUNDATION-HANDOFF.md (default: next to the lock).")
    p_freeze.add_argument("--created-at", default=None, help="Override created_at timestamp (for deterministic output).")
    p_freeze.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS, help="Output format (overrides global).")
    p_record = sub.add_parser("record-acceptance", help="Attach a successful exact-identity engine acceptance record to a frozen lock.")
    p_record.add_argument("--manifest", required=True, type=Path, help="Path to the exact foundation_manifest.json.")
    p_record.add_argument("--lock", required=True, type=Path, help="Path to the frozen foundation.lock.json.")
    p_record.add_argument("--acceptance", required=True, type=Path, help="Path to engine_acceptance.json or its artifact directory.")
    p_record.add_argument("--acceptance-manifest", type=Path, default=None, help="Legacy bridge: unchanged acceptance foundation_manifest.json captured by the acceptance report.")
    p_record.add_argument("--handoff", type=Path, default=None, help="Path to refresh FOUNDATION-HANDOFF.md (default: next to the lock).")
    p_record.add_argument("--created-at", default=None, help="Override timestamp for the audit history entry.")
    p_record.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS, help="Output format (overrides global).")
    p_compare = sub.add_parser("compare", help="Compare a manifest against a frozen lock.")
    p_compare.add_argument("--manifest", required=True, type=Path, help="Path to the newer foundation_manifest.json.")
    p_compare.add_argument("--lock", required=True, type=Path, help="Path to the frozen foundation.lock.json.")
    p_compare.add_argument("--artifact-dir", type=Path, default=None, help="Optional artifact directory for the newer manifest.")
    p_compare.add_argument("--acceptance", type=Path, default=None, help="Optional acceptance record for the newer manifest.")
    p_compare.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS, help="Output format (overrides global).")
    p_unfreeze = sub.add_parser("unfreeze", help="Return a frozen lock to candidate with a recorded reason.")
    p_unfreeze.add_argument("--lock", required=True, type=Path, help="Path to the frozen foundation.lock.json.")
    p_unfreeze.add_argument("--reason", required=True, help="Non-empty reason for unfreezing.")
    p_unfreeze.add_argument("--audit", type=Path, default=None, help="Path to the audit file (default: next to the lock).")
    p_unfreeze.add_argument("--created-at", default=None, help="Override timestamp (for deterministic output).")
    p_unfreeze.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS, help="Output format (overrides global).")
    p_handoff = sub.add_parser("handoff", help="Regenerate FOUNDATION-HANDOFF.md from a lock.")
    p_handoff.add_argument("--lock", required=True, type=Path, help="Path to foundation.lock.json.")
    p_handoff.add_argument("--manifest", type=Path, default=None, help="Optional foundation_manifest.json for extra detail.")
    p_handoff.add_argument("--output", type=Path, default=None, help="Path to write FOUNDATION-HANDOFF.md (default: next to the lock).")
    p_handoff.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS, help="Output format (overrides global).")
    return parser
def _emit(payload: dict, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in _text_lines(payload):
            print(line)
def _text_lines(payload: dict) -> list:
    kind = str(payload.get("command", ""))
    lines = []
    if kind == "candidate":
        lines.append("candidate ok=%s identity=%s" % (payload.get("ok"), payload.get("identity_hash", "")))
        lines.append("lock: %s" % payload.get("lock_path", ""))
        for reason in payload.get("reasons", []) or []:
            lines.append("reason: %s" % reason)
    elif kind == "freeze":
        lines.append("freeze ok=%s identity=%s" % (payload.get("ok"), payload.get("identity_hash", "")))
        lines.append("lock: %s" % payload.get("lock_path", ""))
        lines.append("handoff: %s" % payload.get("handoff_path", ""))
        for reason in payload.get("reasons", []) or []:
            lines.append("reason: %s" % reason)
    elif kind == "record-acceptance":
        lines.append("record-acceptance ok=%s identity=%s run=%s" % (payload.get("ok"), payload.get("identity_hash", ""), payload.get("run_id", "")))
        lines.append("lock: %s" % payload.get("lock_path", ""))
        lines.append("handoff: %s" % payload.get("handoff_path", ""))
        for reason in payload.get("reasons", []) or []:
            lines.append("reason: %s" % reason)
    elif kind == "compare":
        lines.append("status: %s breaking=%s differences=%d" % (payload.get("status"), payload.get("breaking"), len(payload.get("differences", []) or [])))
        lines.append("lock_identity: %s" % payload.get("lock_identity", ""))
        lines.append("manifest_identity: %s" % payload.get("manifest_identity", ""))
        for entry in payload.get("differences", []) or []:
            lines.append("%s [%s breaking=%s] %s" % (entry.get("path", ""), entry.get("change_class", ""), entry.get("breaking", False), entry.get("summary", "")))
            lines.append("  rerun: %s" % entry.get("rerun", ""))
    elif kind == "unfreeze":
        lines.append("unfreeze ok=%s reason=%s" % (payload.get("ok"), payload.get("reason", "")))
        lines.append("lock: %s" % payload.get("lock_path", ""))
        lines.append("audit: %s" % payload.get("audit_path", ""))
        for reason in payload.get("reasons", []) or []:
            lines.append("reason: %s" % reason)
    elif kind == "handoff":
        lines.append("handoff: %s" % payload.get("output", ""))
        lines.append("identity: %s" % payload.get("identity_hash", ""))
    else:
        lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return lines
def _fmt_of(args) -> str:
    choice = getattr(args, "format", None)
    if isinstance(choice, str) and choice in ("text", "json"):
        return choice
    return "text"
def cmd_candidate(args) -> int:
    fmt = _fmt_of(args)
    try:
        result = freeze_service.create_candidate(str(args.manifest), str(args.lock), artifact_dir=str(args.artifact_dir) if args.artifact_dir else None, created_at=args.created_at)
    except freeze_service.FoundationFreezeError as exc:
        _emit({"command": "candidate", "ok": False, "reasons": [str(exc)], "lock_path": str(args.lock), "identity_hash": ""}, fmt)
        return EXIT_USAGE
    except OSError as exc:
        _emit({"command": "candidate", "ok": False, "reasons": ["io error: %s" % exc], "lock_path": str(args.lock), "identity_hash": ""}, fmt)
        return EXIT_USAGE
    payload = {"command": "candidate", **dict(result)}
    _emit(payload, fmt)
    return EXIT_OK if result.get("ok") else EXIT_MISMATCH
def cmd_freeze(args) -> int:
    fmt = _fmt_of(args)
    try:
        result = freeze_service.freeze_foundation(str(args.manifest), str(args.lock), artifact_dir=str(args.artifact_dir) if args.artifact_dir else None, acceptance_path=str(args.acceptance) if args.acceptance else None, acceptance_manifest_path=str(args.acceptance_manifest) if args.acceptance_manifest else None, handoff_path=str(args.handoff) if args.handoff else None, created_at=args.created_at)
    except freeze_service.FoundationFreezeError as exc:
        _emit({"command": "freeze", "ok": False, "reasons": [str(exc)], "lock_path": str(args.lock), "handoff_path": str(args.handoff) if args.handoff else "", "identity_hash": ""}, fmt)
        return EXIT_USAGE
    except OSError as exc:
        _emit({"command": "freeze", "ok": False, "reasons": ["io error: %s" % exc], "lock_path": str(args.lock), "handoff_path": str(args.handoff) if args.handoff else "", "identity_hash": ""}, fmt)
        return EXIT_USAGE
    payload = {"command": "freeze", **dict(result)}
    _emit(payload, fmt)
    return EXIT_OK if result.get("ok") else EXIT_MISMATCH


def cmd_record_acceptance(args) -> int:
    fmt = _fmt_of(args)
    try:
        result = freeze_service.record_engine_acceptance(
            str(args.lock),
            str(args.manifest),
            str(args.acceptance),
            acceptance_manifest_path=str(args.acceptance_manifest) if args.acceptance_manifest else None,
            handoff_path=str(args.handoff) if args.handoff else None,
            created_at=args.created_at,
        )
    except freeze_service.FoundationFreezeError as exc:
        _emit({"command": "record-acceptance", "ok": False, "reasons": [str(exc)], "lock_path": str(args.lock), "handoff_path": str(args.handoff) if args.handoff else "", "identity_hash": ""}, fmt)
        return EXIT_USAGE
    except OSError as exc:
        _emit({"command": "record-acceptance", "ok": False, "reasons": ["io error: %s" % exc], "lock_path": str(args.lock), "handoff_path": str(args.handoff) if args.handoff else "", "identity_hash": ""}, fmt)
        return EXIT_USAGE
    payload = {"command": "record-acceptance", **dict(result)}
    _emit(payload, fmt)
    return EXIT_OK if result.get("ok") else EXIT_MISMATCH
def cmd_compare(args) -> int:
    fmt = _fmt_of(args)
    try:
        result = freeze_service.compare_with_frozen_lock(str(args.manifest), str(args.lock), artifact_dir=str(args.artifact_dir) if args.artifact_dir else None, acceptance_path=str(args.acceptance) if args.acceptance else None)
    except freeze_service.FoundationFreezeError as exc:
        _emit({"command": "compare", "status": "error", "breaking": False, "differences": [], "lock_identity": "", "manifest_identity": "", "reasons": [str(exc)]}, fmt)
        return EXIT_USAGE
    except OSError as exc:
        _emit({"command": "compare", "status": "error", "breaking": False, "differences": [], "lock_identity": "", "manifest_identity": "", "reasons": ["io error: %s" % exc]}, fmt)
        return EXIT_USAGE
    payload = {"command": "compare", **dict(result)}
    _emit(payload, fmt)
    return EXIT_OK if result.get("status") == "compatible" else EXIT_MISMATCH
def cmd_unfreeze(args) -> int:
    fmt = _fmt_of(args)
    if not str(args.reason or "").strip():
        _emit({"command": "unfreeze", "ok": False, "reasons": ["unfreeze requires a non-empty reason"], "lock_path": str(args.lock), "audit_path": str(args.audit) if args.audit else "", "reason": ""}, fmt)
        return EXIT_USAGE
    try:
        result = freeze_service.unfreeze_lock(str(args.lock), str(args.reason), audit_path=str(args.audit) if args.audit else None, created_at=args.created_at)
    except freeze_service.FoundationFreezeError as exc:
        _emit({"command": "unfreeze", "ok": False, "reasons": [str(exc)], "lock_path": str(args.lock), "audit_path": str(args.audit) if args.audit else "", "reason": str(args.reason)}, fmt)
        return EXIT_USAGE
    except OSError as exc:
        _emit({"command": "unfreeze", "ok": False, "reasons": ["io error: %s" % exc], "lock_path": str(args.lock), "audit_path": str(args.audit) if args.audit else "", "reason": str(args.reason)}, fmt)
        return EXIT_USAGE
    payload = {"command": "unfreeze", **dict(result)}
    _emit(payload, fmt)
    return EXIT_OK if result.get("ok") else EXIT_MISMATCH
def cmd_handoff(args) -> int:
    fmt = _fmt_of(args)
    try:
        lock = freeze_service.load_lock(str(args.lock))
    except freeze_service.FoundationFreezeError as exc:
        _emit({"command": "handoff", "output": str(args.output) if args.output else "", "identity_hash": "", "reasons": [str(exc)]}, fmt)
        return EXIT_USAGE
    manifest = None
    if args.manifest:
        try:
            manifest = freeze_service.load_manifest(str(args.manifest))
        except freeze_service.FoundationFreezeError as exc:
            _emit({"command": "handoff", "output": str(args.output) if args.output else "", "identity_hash": "", "reasons": [str(exc)]}, fmt)
            return EXIT_USAGE
    try:
        text = freeze_service.generate_handoff(lock, manifest)
    except freeze_service.FoundationFreezeError as exc:
        _emit({"command": "handoff", "output": str(args.output) if args.output else "", "identity_hash": "", "reasons": [str(exc)]}, fmt)
        return EXIT_USAGE
    output = Path(args.output) if args.output else (Path(str(args.lock)).parent / freeze_contract.HANDOFF_FILENAME)
    try:
        if output.parent and str(output.parent):
            output.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output.with_name(output.name + ".tmp-handoff")
        tmp_path.write_text(text, encoding="utf-8")
        import os as _os
        _os.replace(str(tmp_path), str(output))
    except OSError as exc:
        _emit({"command": "handoff", "output": str(output), "identity_hash": "", "reasons": ["io error: %s" % exc]}, fmt)
        return EXIT_USAGE
    try:
        identity = str((lock.get("identity") or {}).get("identity_hash", ""))
    except Exception:
        identity = ""
    _emit({"command": "handoff", "output": str(output), "identity_hash": identity}, fmt)
    return EXIT_OK
def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "candidate":
        return cmd_candidate(args)
    if args.command == "freeze":
        return cmd_freeze(args)
    if args.command == "record-acceptance":
        return cmd_record_acceptance(args)
    if args.command == "compare":
        return cmd_compare(args)
    if args.command == "unfreeze":
        return cmd_unfreeze(args)
    if args.command == "handoff":
        return cmd_handoff(args)
    parser.print_help()
    return EXIT_USAGE
if __name__ == "__main__":
    raise SystemExit(main())
