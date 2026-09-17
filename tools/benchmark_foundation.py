"""Opt-in performance and traced-memory benchmark for the current exporter.

This command writes no repository files unless an explicit ``--json-output``
path is supplied.  The export directory must also be supplied explicitly.
Benchmark output is evidence for development documentation, not a CI timing
assertion.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from export.mod_exporter import export_full_mod
from export.verify_mod import ModVerifier
from services.export_service import pre_export_check_and_fix
from tools.foundation_baseline import load_project_context, project_summary


def _measure(label: str, callback: Callable[[], Any]) -> tuple[dict[str, Any], Any]:
    tracemalloc.start()
    started = time.perf_counter()
    value = callback()
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "label": label,
        "elapsed_seconds": round(elapsed, 3),
        "peak_traced_bytes": int(peak),
    }, value


def _export_context(context: dict[str, Any], output_dir: Path) -> None:
    managers = context["managers"]
    export_full_mod(
        tile_map=context["tile_map"],
        province_map=context["province_map"],
        output_dir=str(output_dir),
        mod_name="FoundationBenchmark",
        tag="AAA",
        state_mgr=managers["state"],
        country_mgr=managers["country"],
        terrain_map=context["terrain_map"],
        height_map=context["height_map"],
        river_map=context["river_map"],
        continent_mgr=managers["continent"],
        adjacency_mgr=managers["adjacency"],
        railway_mgr=managers["railway"],
        supply_mgr=managers["supply"],
        adjacency_rule_mgr=managers["adjacency_rule"],
        strategic_region_mgr=managers["strategic_region"],
        provincial_terrain=context["provincial_terrain"],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Explicit directory for the benchmark artifact",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional explicit path for the measurement report",
    )
    parser.add_argument(
        "--keep-output",
        action="store_true",
        help="Keep the generated artifact after measurement",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    preexisting_output = args.output_dir.exists()
    if preexisting_output:
        if not args.output_dir.is_dir():
            raise SystemExit(f"Benchmark output path is not a directory: {args.output_dir}")
        if any(args.output_dir.iterdir()):
            raise SystemExit(
                "Refusing to write into a non-empty benchmark directory: "
                f"{args.output_dir}"
            )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    measurements: list[dict[str, Any]] = []
    load_measurement, context = _measure(
        "project_load", lambda: load_project_context(args.project)
    )
    measurements.append(load_measurement)

    summary_measurement, summary = _measure(
        "project_statistics", lambda: project_summary(context)
    )
    measurements.append(summary_measurement)

    preflight_measurement, report = _measure(
        "pre_export_check_and_fix",
        lambda: pre_export_check_and_fix(
            context["tile_map"],
            context["province_map"],
            context["terrain_map"],
            context["managers"]["state"],
            context["managers"]["country"],
            continent_mgr=context["managers"]["continent"],
            strategic_region_mgr=context["managers"]["strategic_region"],
        ),
    )
    measurements.append(preflight_measurement)

    export_measurement, _ = _measure(
        "export_full_mod", lambda: _export_context(context, args.output_dir)
    )
    measurements.append(export_measurement)

    verify_measurement, verification = _measure(
        "mod_verifier", lambda: ModVerifier.verify_quiet(str(args.output_dir))
    )
    measurements.append(verify_measurement)
    errors, warnings = verification

    result = {
        "schema_version": 1,
        "project": str(args.project),
        "output_dir": str(args.output_dir),
        "measurements": measurements,
        "summary": summary,
        "pre_export": {
            "warnings": len(report.warnings),
            "fixed": len(report.fixed),
        },
        "verification": {
            "passed": not errors,
            "errors": len(errors),
            "warnings": len(warnings),
        },
        "memory_note": "peak_traced_bytes is Python tracemalloc allocation, not RSS",
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")

    if not args.keep_output and not preexisting_output:
        shutil.rmtree(args.output_dir)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
