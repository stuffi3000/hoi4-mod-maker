"""Opt-in assisted engine-acceptance harness (M7.1 through M7.4).

Dry-run is the default: the harness verifies the acceptance artifact,
snapshots the selected logs, records the planned game command, evaluates
fresh-log findings, fresh saves, and the human checklist, then writes
engine_acceptance.json. Nothing is executed unless --execute is passed
together with --game-executable.

The harness never performs GUI or mouse automation. Old log content is never
treated as current evidence; only bytes appended after the pre-run snapshot
are classified.

Examples:
    python tools/run_engine_acceptance.py --artifact-dir tmp/acceptance_mod
    python tools/run_engine_acceptance.py --artifact-dir tmp/acceptance_mod --log-dir "C:/Users/me/Documents/Paradox Interactive/Hearts of Iron IV/logs"
    python tools/run_engine_acceptance.py --artifact-dir tmp/acceptance_mod --game-executable hoi4.exe --execute
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from domain import engine_acceptance as contract
from services import engine_acceptance_service as harness


EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    """Build the opt-in acceptance command parser with the short checklist."""
    parser = argparse.ArgumentParser(
        description="Assisted HOI4 engine-acceptance harness (dry-run by default).",
        epilog="Required in-game checklist (M7.4):\n" + contract.describe_checklist_short()
        + "\n\nBoundaries: " + contract.BOUNDARIES_TEXT,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--artifact-dir", required=True, type=Path, help="Acceptance mod directory under test.")
    parser.add_argument("--target", default="", help="Game target label recorded with the run.")
    parser.add_argument("--profile", default="acceptance", help="Export profile label recorded with the run.")
    parser.add_argument("--game-version", default="", help="Game version label recorded with the run.")
    parser.add_argument("--log", dest="logs", action="append", default=[], type=Path, help="Explicit log file to snapshot (repeatable).")
    parser.add_argument("--log-dir", type=Path, default=None, help="Directory providing the default HOI4 log names.")
    parser.add_argument("--archive-logs-to", type=Path, default=None, help="Copy pre-run log bytes aside for later proof.")
    parser.add_argument("--save-dir", type=Path, default=None, help="Directory watched for expected save files.")
    parser.add_argument("--save-name", dest="save_names", action="append", default=[], help="Expected save file name (repeatable).")
    parser.add_argument("--launch-via", choices=("auto", "direct", "steam"), default="auto", help="Launch directly or submit the game through Steam; auto uses Steam when no direct executable is supplied.")
    parser.add_argument("--game-executable", default="", help="Game or launcher executable for direct mode.")
    parser.add_argument("--steam-executable", default="", help="Steam executable; auto-discovered from --target when omitted.")
    parser.add_argument("--steam-app-id", default="394360", help="Steam AppID (default: HOI4 394360).")
    parser.add_argument("--skip-launcher", action="store_true", help="Bypass the Steam/Paradox launcher and run hoi4.exe directly; this is the unattended path.")
    parser.add_argument("--game-arg", dest="game_args", action="append", default=[], help="Game argument (repeatable, no shell).")
    parser.add_argument("--wait-for-process", default="", help="Process image that must appear for a launcher/Steam launch to count as started.")
    parser.add_argument("--startup-timeout-seconds", type=float, default=60.0, help="How long to wait for the observed game process to appear.")
    parser.add_argument("--cwd", default="", help="Working directory for an executed launch.")
    parser.add_argument("--env", dest="env_vars", action="append", default=[], metavar="NAME=VALUE", help="Environment entry for an executed launch (repeatable).")
    parser.add_argument("--timeout-seconds", type=float, default=0.0, help="Timeout for an executed launch; 0 waits for exit.")
    parser.add_argument("--expected-identity", default="", help="Expected manifest identity hash; mismatch blocks acceptance.")
    parser.add_argument("--expected-profile", default="", help="Expected manifest profile; mismatch is recorded.")
    parser.add_argument("--check", dest="checked", action="append", default=[], help="Checklist check id to record as done (repeatable).")
    parser.add_argument("--check-note", dest="check_notes", action="append", default=[], metavar="ID=TEXT", help="Note attached to a checklist check (repeatable).")
    parser.add_argument("--output", type=Path, default=None, help="Result path; defaults to <artifact-dir>/engine_acceptance.json.")
    parser.add_argument("--capture-limit", type=int, default=harness.MAX_OUTPUT_CHARS, help="Captured output bound per stream.")
    parser.add_argument("--execute", action="store_true", help="Opt in to executing the configured game command.")
    return parser


def parse_env_entries(entries: Sequence[str]) -> dict[str, str]:
    """Parse NAME=VALUE entries and bare inherited names into an env mapping."""
    parsed: dict[str, str] = {}
    inherit: list[str] = []
    for entry in entries or ():
        text = str(entry)
        if "=" in text:
            name, _, value = text.partition("=")
            name = name.strip()
            if not name:
                raise ValueError("environment entry %r has an empty name" % text)
            parsed[name] = value
        else:
            name = text.strip()
            if not name:
                raise ValueError("environment entry %r has an empty name" % text)
            inherit.append(name)
    import os as _os

    for name in inherit:
        if name in _os.environ and name not in parsed:
            parsed[name] = _os.environ[name]
    return parsed


def parse_check_notes(entries: Sequence[str]) -> dict[str, str]:
    """Parse ID=TEXT checklist notes into a mapping keyed by check id."""
    notes: dict[str, str] = {}
    for entry in entries or ():
        text = str(entry)
        if "=" not in text:
            raise ValueError("check note %r must use ID=TEXT form" % text)
        check_id, _, note = text.partition("=")
        check_id = check_id.strip()
        if not check_id:
            raise ValueError("check note %r has an empty check id" % text)
        notes[check_id] = note
    return notes


def print_summary(result: Mapping[str, Any], output_path: str) -> None:
    """Print the short deterministic run summary with the checklist state."""
    print("run_id: %s" % result.get("run_id", ""))
    print("mode: %s" % result.get("mode", ""))
    print("status: %s" % result.get("status", ""))
    artifact = result.get("artifact", {})
    if isinstance(artifact, dict):
        print("artifact files: %s fingerprint: %s" % (artifact.get("file_count", 0), str(artifact.get("fingerprint", ""))[:16]))
        manifest = artifact.get("manifest", {})
        if isinstance(manifest, dict):
            print("manifest: present=%s identity=%s profile=%s" % (manifest.get("present", False), manifest.get("identity_hash", ""), manifest.get("profile", "")))
        for mismatch in artifact.get("mismatch", []) or []:
            print("mismatch: %s expected=%s actual=%s" % (mismatch.get("field", ""), mismatch.get("expected", ""), mismatch.get("actual", "")))
    launch = result.get("launch", {})
    if isinstance(launch, dict):
        print("launch: mode=%s executed=%s argv=%s" % (launch.get("mode", ""), launch.get("executed", False), launch.get("argv", [])))
        if launch.get("launcher_detected"):
            print("launcher: detected=%s process=%s pids=%s" % (
                launch.get("launcher_detected", False),
                launch.get("launcher_process", ""),
                launch.get("launcher_pids", []),
            ))
    logs = result.get("logs", {})
    if isinstance(logs, dict):
        summary = logs.get("summary", {})
        if isinstance(summary, dict):
            print("log findings: total=%s errors=%s blockers=%s verdict=%s" % (summary.get("total", 0), summary.get("errors", 0), summary.get("blocker_count", 0), summary.get("verdict", "")))
    for save in result.get("saves", []) or []:
        print("save %s: %s" % (save.get("name", ""), save.get("status", "")))
    for entry in result.get("checklist", []) or []:
        mark = "x" if entry.get("checked", False) else " "
        print("[%s] %s: %s" % (mark, entry.get("check_id", ""), entry.get("title", "")))
    for reason in result.get("reasons", []) or []:
        print("reason: %s" % reason)
    print("result: %s" % output_path)


def main(argv: list[str] | None = None) -> int:
    """Run the harness from command-line arguments and return a process exit code."""
    args = build_parser().parse_args(argv)
    if args.save_names and not args.save_dir:
        print("Error: --save-name requires --save-dir.", file=sys.stderr)
        return EXIT_USAGE
    try:
        env_values = parse_env_entries(args.env_vars)
        check_notes = parse_check_notes(args.check_notes)
    except ValueError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    try:
        launch_config = None
        launch_via = str(args.launch_via or "auto")
        if launch_via == "auto":
            if args.game_executable:
                launch_via = "direct"
            elif args.target or args.steam_executable:
                launch_via = "steam"
            else:
                launch_via = "none"
        if launch_via == "steam":
            game_args = list(args.game_args)
            if args.skip_launcher:
                direct_executable = args.game_executable or harness.discover_game_executable(args.target)
                if not direct_executable:
                    raise ValueError("--skip-launcher requires --target containing hoi4.exe or --game-executable")
                launch_config = harness.build_launch_config(
                    executable=direct_executable,
                    args=tuple(game_args),
                    cwd=args.cwd or args.target or None,
                    env=env_values,
                    timeout_seconds=args.timeout_seconds,
                    wait_for_process=args.wait_for_process or "hoi4.exe",
                    startup_timeout_seconds=args.startup_timeout_seconds,
                )
            else:
                launch_config = harness.build_steam_launch_config(
                    app_id=args.steam_app_id,
                    game_args=tuple(game_args),
                    steam_executable=args.steam_executable,
                    target=args.target or None,
                    cwd=args.cwd or None,
                    env=env_values,
                    timeout_seconds=args.timeout_seconds,
                    wait_for_process=args.wait_for_process or "hoi4.exe",
                    startup_timeout_seconds=args.startup_timeout_seconds,
                )
        elif args.game_executable:
            launch_config = harness.build_launch_config(
                executable=args.game_executable,
                args=tuple(args.game_args),
                cwd=args.cwd or None,
                env=env_values,
                timeout_seconds=args.timeout_seconds,
                wait_for_process=args.wait_for_process,
                startup_timeout_seconds=args.startup_timeout_seconds,
            )
        elif args.execute:
            print("Error: --execute requires --game-executable or --launch-via steam.", file=sys.stderr)
            return EXIT_USAGE
        log_paths = harness.resolve_log_paths(explicit_logs=[str(item) for item in args.logs], log_dir=args.log_dir)
        result = harness.run_harness(
            artifact_dir=args.artifact_dir,
            target=args.target,
            profile=args.profile,
            game_version=args.game_version,
            log_paths=log_paths,
            archive_dir=args.archive_logs_to,
            save_dir=args.save_dir,
            save_names=tuple(args.save_names),
            launch_config=launch_config,
            launch_env=env_values,
            execute=bool(args.execute),
            checked=tuple(args.checked),
            check_notes=check_notes,
            expected_identity_hash=args.expected_identity,
            expected_profile=args.expected_profile,
            capture_limit=args.capture_limit,
        )
    except (OSError, ValueError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    output_path = args.output if args.output is not None else Path(args.artifact_dir) / harness.RESULT_FILENAME
    try:
        written = harness.write_result(output_path, result)
    except OSError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    print_summary(result, written)
    if str(result.get("status", "")) in ("passed", "dry_run"):
        return EXIT_OK
    return EXIT_INCOMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
