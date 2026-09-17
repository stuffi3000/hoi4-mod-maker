"""Opt-in metadata-only foundation baseline capture.

Examples:
    python tools/capture_foundation_baseline.py \
        --project projects/Belgium_Map_v1_1.hoi4proj
    python tools/capture_foundation_baseline.py \
        --project projects/Belgium_Map_v1_1.hoi4proj \
        --game-install "C:/Program Files (x86)/Steam/steamapps/common/Hearts of Iron IV" \
        --inventory tests/fixtures/export_baseline.json \
        --output tmp/belgium-baseline.json

The command prints a report by default.  It refuses to overwrite an existing
report unless ``--replace`` is explicitly supplied, so committed fixtures are
never refreshed as a side effect of comparison.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.foundation_baseline import capture_summary, compare_baseline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--game-install", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="Write a new JSON report here; stdout is used when omitted",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Allow replacing an existing explicitly selected output report",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        metavar="BASELINE",
        help="Compare the captured report with a committed metadata fixture",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = capture_summary(
            args.project,
            inventory_source=args.inventory,
            game_install=args.game_install,
        )
        if args.compare is not None:
            with args.compare.open("r", encoding="utf-8") as file:
                expected = json.load(file)
            differences = compare_baseline(expected, report)
            if differences:
                print("Baseline changed:")
                for difference in differences:
                    print(f"- {difference}")
                return 1
            print("Baseline matches.")
            return 0

        encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output is None:
            sys.stdout.write(encoded)
            return 0
        if args.output.exists() and not args.replace:
            raise FileExistsError(
                f"Refusing to overwrite existing report: {args.output}; "
                "choose a new path or pass --replace explicitly"
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(f"Wrote metadata report: {args.output}")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
