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
import os
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
    parser.add_argument("--artifact-dir", type=Path, help="Acceptance mod directory under test.")
    parser.add_argument(
        "--amend-checklist",
        type=Path,
        default=None,
        metavar="RESULT",
        help="Amend a completed assisted result's checklist without launching HOI4; writes a sibling -amended report by default.",
    )
    parser.add_argument("--target", default="", help="Game target label recorded with the run.")
    parser.add_argument("--profile", default="acceptance", help="Export profile label recorded with the run.")
    parser.add_argument("--game-version", default="", help="Game version label recorded with the run.")
    parser.add_argument("--log", dest="logs", action="append", default=[], type=Path, help="Explicit log file to snapshot (repeatable).")
    parser.add_argument("--log-dir", type=Path, default=None, help="Directory providing the default HOI4 log names.")
    parser.add_argument("--allow-non-error-log-set", action="store_true", help="Explicitly use a non-error log set and disable the required error.log freshness check.")
    parser.add_argument("--activate-artifact", action="store_true", help="Temporarily enable only this artifact through HOI4's dlc_load.json for a direct executed run.")
    parser.add_argument("--hoi4-user-dir", type=Path, default=None, help="HOI4 user-data directory containing dlc_load.json, mod/, and logs/ (required with --activate-artifact).")
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
    parser.add_argument("--waive-check", dest="waived_checks", action="append", default=[], metavar="ID=REASON", help="Explicitly waive a checklist check with a reason (repeatable).")
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
        if check_id in notes:
            raise ValueError("check note id was provided more than once: %s" % check_id)
        notes[check_id] = note
    return notes


def parse_check_waivers(entries: Sequence[str]) -> dict[str, str]:
    """Parse ID=REASON checklist waivers and reject empty or duplicate input."""
    waivers: dict[str, str] = {}
    for entry in entries or ():
        text = str(entry)
        if "=" not in text:
            raise ValueError("check waiver %r must use ID=REASON form" % text)
        check_id, _, reason = text.partition("=")
        check_id = check_id.strip()
        reason = reason.strip()
        if not check_id:
            raise ValueError("check waiver %r has an empty check id" % text)
        if not reason:
            raise ValueError("check waiver for %s needs a non-empty reason" % check_id)
        if check_id in waivers:
            raise ValueError("check waiver id was provided more than once: %s" % check_id)
        waivers[check_id] = reason
    return waivers


def _path_key(path: str | Path) -> str:
    """Normalize a potentially absent log path for duplicate detection."""
    return os.path.normcase(str(Path(path).expanduser().resolve(strict=False)))


def _ensure_managed_system_log(
    log_paths: Sequence[str | Path],
    hoi4_user_dir: str | Path,
) -> list[str]:
    """Watch exactly the system.log belonging to the managed HOI4 user directory."""
    expected = Path(hoi4_user_dir).expanduser() / "logs" / "system.log"
    expected_key = _path_key(expected)
    result: list[str] = []
    seen: set[str] = set()
    for candidate in log_paths or ():
        text = str(candidate or "")
        if not text:
            continue
        key = _path_key(text)
        is_system_log = text.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].casefold() == "system.log"
        if is_system_log and key != expected_key:
            raise ValueError(
                "managed activation requires system.log under --hoi4-user-dir: %s" % expected
            )
        if key not in seen:
            result.append(text)
            seen.add(key)
    if expected_key not in seen:
        result.append(str(expected))
    return result


def _is_mod_override_arg(argument: str) -> bool:
    """Detect unsupported command-line mod overrides for managed activation."""
    value = str(argument or "").strip().casefold()
    return value in ("-mod", "--mod") or value.startswith(("-mod=", "--mod="))


def format_assisted_preflight(
    log_paths: Sequence[str | Path],
    save_names: Sequence[str],
    save_dir: str | Path | None,
    require_error_log: bool = True,
    waived_checks: Mapping[str, str] | None = None,
) -> str:
    """Render the human checklist and evidence policy before a blocking launch."""
    lines = ["Assisted-session preflight", "Required in-game checklist:"]
    waivers = dict(waived_checks or {})
    for check_id, title, detail in contract.REQUIRED_CHECKS:
        reason = str(waivers.get(check_id, "") or "").strip()
        if reason:
            lines.append("- [waived] %s: %s — %s" % (check_id, title, reason))
        else:
            lines.append("- [ ] %s: %s" % (check_id, title))
    if require_error_log:
        watched_error_logs = [
            str(path)
            for path in log_paths or ()
            if str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].casefold() == "error.log"
        ]
        lines.append(
            "Required error.log policy: it must be readable and generated or modified after the pre-run snapshot."
        )
        if watched_error_logs:
            lines.append("Watched error.log path(s): %s" % ", ".join(watched_error_logs))
        else:
            lines.append("Watched error.log path(s): none configured; the run will fail this requirement.")
    else:
        lines.append("Required error.log policy: disabled by explicit non-error log set.")
    if save_names:
        lines.append("Expected save name(s): %s" % ", ".join(str(name) for name in save_names))
    else:
        lines.append("Expected save name(s): none")
    lines.append("Save directory: %s" % (str(save_dir) if save_dir else "not configured"))
    return "\n".join(lines)


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
        required_error_log = logs.get("required_error_log", {})
        if isinstance(required_error_log, dict) and required_error_log.get("required"):
            print("required error.log: %s" % required_error_log.get("status", ""))
        active_dlc = logs.get("active_dlc", {})
        by_category = summary.get("by_category", {}) if isinstance(summary, dict) else {}
        if (
            isinstance(active_dlc, dict)
            and isinstance(by_category, dict)
            and int(by_category.get("dlc_unrelated", 0) or 0) > 0
        ):
            source = str(active_dlc.get("source", "") or "")
            source_name = source.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] if source else "not captured"
            count = active_dlc.get("count")
            print(
                "active DLC evidence: status=%s count=%s source=%s"
                % (active_dlc.get("status", "not_observed"), count if count is not None else "unknown", source_name)
            )
        active_mod = logs.get("active_mod", {})
        if isinstance(active_mod, dict) and active_mod.get("required"):
            print(
                "active mod proof: status=%s expected=%r count=%s names=%s"
                % (
                    active_mod.get("status", ""),
                    active_mod.get("expected_name", ""),
                    active_mod.get("count"),
                    active_mod.get("observed_names", []),
                )
            )
    for save in result.get("saves", []) or []:
        print("save %s: %s" % (save.get("name", ""), save.get("status", "")))
    checklist_summary = result.get("checklist_summary", {})
    if isinstance(checklist_summary, Mapping):
        print(
            "checklist: checked=%s waived=%s missing=%s"
            % (
                checklist_summary.get("checked", 0),
                checklist_summary.get("waived", 0),
                checklist_summary.get("missing", []),
            )
        )
    for entry in result.get("checklist", []) or []:
        if entry.get("waived", False):
            print(
                "[waived] %s: %s — reason: %s"
                % (entry.get("check_id", ""), entry.get("title", ""), entry.get("waiver_reason", ""))
            )
        else:
            mark = "x" if entry.get("checked", False) else " "
            print("[%s] %s: %s" % (mark, entry.get("check_id", ""), entry.get("title", "")))
    for reason in result.get("reasons", []) or []:
        print("reason: %s" % reason)
    print("result: %s" % output_path)


def main(argv: list[str] | None = None) -> int:
    """Run the harness from command-line arguments and return a process exit code."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_args)
    if args.amend_checklist is not None:
        allowed = {"--amend-checklist", "--check", "--check-note", "--waive-check", "--output"}
        unexpected = [
            token.split("=", 1)[0]
            for token in raw_args
            if token.startswith("-") and token.split("=", 1)[0] not in allowed
        ]
        if unexpected:
            print(
                "Error: checklist amendment cannot be combined with run/launch options: %s"
                % ", ".join(dict.fromkeys(unexpected)),
                file=sys.stderr,
            )
            return EXIT_USAGE
        if args.artifact_dir is not None:
            print("Error: --artifact-dir is not used with --amend-checklist.", file=sys.stderr)
            return EXIT_USAGE
        try:
            check_notes = parse_check_notes(args.check_notes)
            waived_checks = parse_check_waivers(args.waived_checks)
            harness.normalize_checklist(
                checked=tuple(args.checked),
                notes=check_notes,
                waived_checks=waived_checks,
            )
            original = harness.load_result(args.amend_checklist)
            amended = harness.amend_checklist_result(
                original,
                checked=tuple(args.checked),
                waived_checks=waived_checks,
                check_notes=check_notes,
            )
            output_path = args.output or harness.amended_result_path(args.amend_checklist)
            source_key = os.path.normcase(str(args.amend_checklist.expanduser().resolve(strict=False)))
            output_key = os.path.normcase(str(output_path.expanduser().resolve(strict=False)))
            if source_key == output_key:
                raise ValueError("Amended output must not overwrite the source acceptance report.")
            if output_path.exists():
                raise ValueError("Amended output already exists; choose a new --output path: %s" % output_path)
            written = harness.write_result_exclusive(output_path, amended)
        except (OSError, ValueError) as exc:
            print("Error: %s" % exc, file=sys.stderr)
            return EXIT_USAGE
        print_summary(amended, written)
        if str(amended.get("status", "")) in ("passed", "dry_run"):
            return EXIT_OK
        return EXIT_INCOMPLETE

    if args.artifact_dir is None:
        print("Error: --artifact-dir is required for a normal harness run.", file=sys.stderr)
        return EXIT_USAGE
    if args.save_names and not args.save_dir:
        print("Error: --save-name requires --save-dir.", file=sys.stderr)
        return EXIT_USAGE
    try:
        env_values = parse_env_entries(args.env_vars)
        check_notes = parse_check_notes(args.check_notes)
        waived_checks = parse_check_waivers(args.waived_checks)
        harness.normalize_checklist(
            checked=tuple(args.checked),
            notes=check_notes,
            waived_checks=waived_checks,
        )
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
        if args.activate_artifact:
            if not args.execute:
                raise ValueError("--activate-artifact requires --execute")
            if args.hoi4_user_dir is None:
                raise ValueError("--activate-artifact requires --hoi4-user-dir")
            if not args.hoi4_user_dir.expanduser().is_absolute():
                raise ValueError("--hoi4-user-dir must be an absolute path")
            if launch_via != "direct" and not (launch_via == "steam" and args.skip_launcher):
                raise ValueError("--activate-artifact requires a direct launch or --launch-via steam --skip-launcher")
            if any(_is_mod_override_arg(item) for item in args.game_args):
                raise ValueError("managed activation uses dlc_load.json; do not pass the unsupported -mod argument")
        elif args.hoi4_user_dir is not None:
            raise ValueError("--hoi4-user-dir is only valid with --activate-artifact")
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
        if args.activate_artifact:
            log_paths = _ensure_managed_system_log(log_paths, args.hoi4_user_dir)
        if args.execute:
            print(format_assisted_preflight(
                log_paths=log_paths,
                save_names=args.save_names,
                save_dir=args.save_dir,
                require_error_log=not bool(args.allow_non_error_log_set),
                waived_checks=waived_checks,
            ))
            if args.activate_artifact:
                print(
                    "Required active-mod policy: fresh system.log must report exactly one active mod matching descriptor.mod."
                )
        run_kwargs = {
            "artifact_dir": args.artifact_dir,
            "target": args.target,
            "profile": args.profile,
            "game_version": args.game_version,
            "log_paths": log_paths,
            "archive_dir": args.archive_logs_to,
            "save_dir": args.save_dir,
            "save_names": tuple(args.save_names),
            "launch_config": launch_config,
            "launch_env": env_values,
            "execute": bool(args.execute),
            "checked": tuple(args.checked),
            "check_notes": check_notes,
            "waived_checks": waived_checks,
            "expected_identity_hash": args.expected_identity,
            "expected_profile": args.expected_profile,
            "capture_limit": args.capture_limit,
            "require_error_log": not bool(args.allow_non_error_log_set),
        }
        if args.activate_artifact:
            with harness.managed_artifact_activation(args.artifact_dir, args.hoi4_user_dir) as activation:
                print(
                    "Managed artifact activation: staging %r via %s"
                    % (activation["expected_mod_name"], activation["descriptor_reference"])
                )
                run_kwargs["managed_activation"] = {
                    "descriptor_name": activation["expected_mod_name"],
                    "descriptor_reference": activation["descriptor_reference"],
                }
                result = harness.run_harness(**run_kwargs)
        else:
            result = harness.run_harness(**run_kwargs)
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
