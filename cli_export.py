"""Command-line export for ``.hoi4proj`` project files.

Exit codes are intentionally stable:

* ``0`` — export completed and final output verification passed;
* ``1`` — command, project-load, or writer failure;
* ``2`` — the export ran, but final output validation found missing/empty files.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import TextIO

import numpy as np

from data.constants import TILE_LAND, TILE_SEA
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.managers.adjacency import AdjacencyManager
from domain.managers.adjacency_rule import AdjacencyRuleManager
from domain.managers.continent import ContinentManager
from domain.managers.country import CountryManager
from domain.managers.railway import RailwayManager
from domain.managers.state import StateManager
from domain.managers.strategic_region import StrategicRegionManager
from domain.managers.supply_node import SupplyNodeManager
from domain.managers.map_placement import MapPlacementManager
from domain.project_io import load_project, read_project_meta
from export.mod_exporter import export_full_mod


DEFAULT_OUTPUT = "D:/Documents/Paradox Interactive/Hearts of Iron IV/mod/WorldTest"
DEFAULT_MOD_NAME = "WorldTest"

EXIT_SUCCESS = 0
EXIT_COMMAND_ERROR = 1
EXIT_VALIDATION_ERROR = 2

CRITICAL_FILES = (
    "map/default.map",
    "map/provinces.bmp",
    "map/definition.csv",
    "map/terrain.bmp",
    "map/heightmap.bmp",
    "map/rivers.bmp",
    "map/buildings.txt",
    "map/positions.txt",
    "map/adjacencies.csv",
    "map/supply_nodes.txt",
    "map/railways.txt",
    "map/continent.txt",
    "descriptor.mod",
)

CRITICAL_DIRECTORIES = (
    "history/states",
    "history/countries",
    "common/country_tags",
)


def _safe_print(
    *values: object,
    sep: str = " ",
    end: str = "\n",
    file: TextIO | None = None,
    flush: bool = False,
) -> None:
    """Write a status line even when the terminal stream is ASCII-only."""

    stream = file if file is not None else sys.stdout
    text = sep.join(str(value) for value in values) + end
    try:
        stream.write(text)
    except UnicodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        try:
            safe_text = text.encode(encoding, errors="backslashreplace").decode(
                encoding, errors="replace"
            )
        except (LookupError, UnicodeError):
            safe_text = text.encode("ascii", errors="backslashreplace").decode("ascii")
        stream.write(safe_text)
    if flush and hasattr(stream, "flush"):
        stream.flush()


def configure_console_streams() -> None:
    """Prefer UTF-8 while leaving ``_safe_print`` as the encoding fallback."""

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            # Some embedded/redirected streams expose reconfigure but reject
            # the requested encoding. _safe_print still protects each write.
            continue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export an HOI4 MOD from a .hoi4proj project file",
        epilog=(
            "Profiles:\n"
            "  foundation  map-owned candidate package; no country/scenario content\n"
            "  acceptance  disposable playable test mod for the engine harness\n"
            "  scaffold    optional generated gameplay starting point\n"
            "  legacy_full compatibility profile for the pre-staged exporter\n\n"
            "Foundation workflow: plan a candidate, review findings and repairs, "
            "export the staged artifact, run static/engine acceptance, then use "
            "the foundation-freeze CLI/service to record the lock and handoff."
        ),
    )
    parser.add_argument("project", help="Path to the .hoi4proj project file")
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=DEFAULT_OUTPUT,
        help=f"Export directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--mod-name",
        default=DEFAULT_MOD_NAME,
        help=f"MOD name (default: {DEFAULT_MOD_NAME})",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clear the output directory before exporting",
    )
    parser.add_argument(
        "--profile",
        choices=("foundation", "acceptance", "scaffold", "legacy_full"),
        default="legacy_full",
        help="Export profile: foundation, acceptance, scaffold, or legacy_full (default: legacy_full)",
    )
    parser.add_argument(
        "--game-dir",
        default=None,
        help="Hearts of Iron IV installation directory (overrides project metadata)",
    )
    parser.add_argument(
        "--repair",
        choices=("off", "propose", "apply-safe"),
        default="apply-safe",
        help="Repair policy for planner exports (default: apply-safe)",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Copy the generated foundation manifest to PATH after export",
    )
    parser.add_argument(
        "--compare-lock",
        default=None,
        help="Compare the planned artifact with a foundation lock before writing output",
    )
    parser.add_argument(
        "--json-report",
        default=None,
        help="Write the plan/result JSON report to PATH",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing destination during staged promotion",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Move an existing destination to a timestamped backup during promotion",
    )
    parser.add_argument(
        "--keep-staging",
        action="store_true",
        help="Keep failed staging output for diagnostics",
    )
    parser.add_argument(
        "--acceptance-count",
        type=int,
        default=2,
        help="Number of deterministic test tags for the acceptance profile (default: 2)",
    )
    return parser


def verify_export(output_dir: str) -> list[str]:
    """Return missing/empty required output paths without printing or mutating."""

    missing: list[str] = []
    for relative_path in CRITICAL_FILES:
        path = os.path.join(output_dir, relative_path)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            missing.append(relative_path)

    for relative_path in CRITICAL_DIRECTORIES:
        path = os.path.join(output_dir, relative_path)
        if not os.path.isdir(path) or not os.listdir(path):
            missing.append(relative_path)

    launcher_mod = output_dir + ".mod"
    if not os.path.isfile(launcher_mod) or os.path.getsize(launcher_mod) == 0:
        missing.append(launcher_mod)
    return missing


def main(argv: list[str] | None = None) -> int:
    configure_console_streams()
    # Bind the safe writer locally so every status message in this function is
    # protected, including the Unicode status separators used by older output.
    print = _safe_print
    args = build_parser().parse_args(argv)

    if _uses_planner_path(args):
        return run_planner_export(args)

    if not os.path.isfile(args.project):
        print(f"Error: project file not found: {args.project}", file=sys.stderr)
        return EXIT_COMMAND_ERROR

    try:
        print(f"Loading project: {args.project}")
        state_mgr = StateManager()
        country_mgr = CountryManager()
        continent_mgr = ContinentManager()
        adjacency_mgr = AdjacencyManager()
        railway_mgr = RailwayManager()
        supply_mgr = SupplyNodeManager()
        adjacency_rule_mgr = AdjacencyRuleManager()
        strategic_region_mgr = StrategicRegionManager()
        map_placement_mgr = MapPlacementManager()

        (
            tile_map,
            province_map,
            terrain_map,
            height_map,
            river_map,
            provincial_terrain,
            _tile_snapshot,
        ) = load_project(
            args.project,
            state_mgr,
            country_mgr,
            continent_mgr=continent_mgr,
            adjacency_mgr=adjacency_mgr,
            railway_mgr=railway_mgr,
            supply_mgr=supply_mgr,
            adjacency_rule_mgr=adjacency_rule_mgr,
            strategic_region_mgr=strategic_region_mgr,
            map_placement_mgr=map_placement_mgr,
        )

        height, width = tile_map.shape
        try:
            project_meta = read_project_meta(args.project)
        except Exception:
            # Legacy projects and test doubles may not contain M1 metadata.
            project_meta = None
        from services.game_assets import resolve_game_target
        from services.game_profile_service import load_profile_for_target

        target_install = getattr(project_meta, "game_install_dir", None)
        target_profile_id = getattr(project_meta, "profile_id", None)
        game_target = resolve_game_target(
            target_install,
            profile_id=target_profile_id,
            source="project" if target_install else None,
        )
        profile = load_profile_for_target(game_target)
        dimensions = (int(width), int(height))
        province_count = int(province_map.max())
        land_pixels = int(np.sum(tile_map == TILE_LAND))
        sea_pixels = int(np.sum(tile_map == TILE_SEA))
        print(
            f"Map: {width}x{height}, provinces: {province_count}, "
            f"land pixels: {land_pixels:,}, sea pixels: {sea_pixels:,}"
        )

        # Synchronized terrain.
        ocean_idx = TERRAIN_PALETTE_INDEX["ocean"]
        plains_idx = TERRAIN_PALETTE_INDEX["plains"]
        land_mask = tile_map == TILE_LAND
        bad_land = land_mask & (terrain_map == ocean_idx)
        bad_count = int(np.sum(bad_land))
        if bad_count > 0:
            terrain_map[bad_land] = plains_idx
            print(f"Fixed {bad_count:,} land pixels with ocean terrain: ocean -> plains")

        sea_mask = tile_map == TILE_SEA
        sea_bad = sea_mask & (terrain_map != ocean_idx)
        sea_bad_count = int(np.sum(sea_bad))
        if sea_bad_count > 0:
            terrain_map[sea_bad] = ocean_idx
            print(f"Fixed {sea_bad_count:,} sea pixels with non-ocean terrain: -> ocean")

        # Automatically generate a height map only when the source is flat.
        if height_map is not None and land_mask.any():
            land_heights = height_map[land_mask]
            if np.all(land_heights == land_heights[0]):
                print("Height map is flat; generating it automatically...")
                from services.terrain_service import auto_height

                height_map = auto_height(tile_map)

        if not state_mgr.states:
            print("No states found; generating them automatically...")
            state_mgr.auto_split(province_map, tile_map, per_state=20)
            print(f"Generated states: {len(state_mgr.states)}")
        else:
            print(f"Existing states: {len(state_mgr.states)}")

        if not country_mgr.countries:
            print("No countries found; creating a test country automatically...")
            country = country_mgr.create_country("AAA", "Aurora", (60, 130, 220))
            country.ruling_party = "democratic"
            country.popularities = {
                "democratic": 60,
                "fascism": 10,
                "communism": 10,
                "neutrality": 20,
            }
            for state_id in state_mgr.states:
                country_mgr.assign_state(state_id, "AAA")
                state = state_mgr.get_state(state_id)
                if state:
                    state.owner_tag = "AAA"
            first_state = state_mgr.get_state(1)
            if first_state and first_state.provinces:
                country.capital = first_state.provinces[0]
            print(f"Created country AAA with {len(state_mgr.states)} states")
        else:
            print(f"Existing countries: {list(country_mgr.countries.keys())}")

        from services.export_service import fill_default_state_data, pre_export_check_and_fix

        report = pre_export_check_and_fix(
            tile_map,
            province_map,
            terrain_map,
            state_mgr,
            country_mgr,
            continent_mgr,
            strategic_region_mgr=strategic_region_mgr,
            game_target=game_target,
            profile=profile,
            dimensions=dimensions,
        )
        if report.fixed:
            print("\n── Automatic fixes ──")
            for fixed in report.fixed:
                print(f"  [FIXED] {fixed}")
        if report.warnings:
            print("\n── Warnings ──")
            for warning in report.warnings:
                print(f"  [WARNING] {warning}")

        filled = fill_default_state_data(
            state_mgr, terrain_map, province_map, tile_map
        )
        if filled > 0:
            print(f"Filled {filled} states with default resources/buildings")

        if args.clean and os.path.exists(args.output_dir):
            shutil.rmtree(args.output_dir)
            print(f"Cleared: {args.output_dir}")
        os.makedirs(args.output_dir, exist_ok=True)

        print(f"\nExporting to: {args.output_dir}")
        export_full_mod(
            tile_map=tile_map,
            province_map=province_map,
            output_dir=args.output_dir,
            mod_name=args.mod_name,
            tag="AAA",
            state_mgr=state_mgr,
            country_mgr=country_mgr,
            terrain_map=terrain_map,
            height_map=height_map,
            river_map=river_map,
            continent_mgr=continent_mgr,
            adjacency_mgr=adjacency_mgr,
            railway_mgr=railway_mgr,
            supply_mgr=supply_mgr,
            adjacency_rule_mgr=adjacency_rule_mgr,
            strategic_region_mgr=strategic_region_mgr,
            map_placement_mgr=map_placement_mgr,
            provincial_terrain=provincial_terrain,
            game_target=game_target,
            profile=profile,
            dimensions=dimensions,
        )
    except Exception as exc:  # CLI boundary: convert writer/load failures to a stable code.
        print(f"[ERROR] Export failed: {exc}", file=sys.stderr)
        return EXIT_COMMAND_ERROR

    file_count = sum(len(files) for _, _, files in os.walk(args.output_dir))
    print(f"\nExport wrote {file_count} files; running final verification...")
    try:
        missing = verify_export(args.output_dir)
    except Exception as exc:
        print(f"[ERROR] Final output verification failed: {exc}", file=sys.stderr)
        return EXIT_COMMAND_ERROR
    for relative_path in CRITICAL_FILES:
        path = os.path.join(args.output_dir, relative_path)
        if relative_path in missing:
            print(f"  [MISSING/EMPTY] {relative_path}")
        else:
            print(f"  [OK] {relative_path} ({os.path.getsize(path):,} bytes)")
    for relative_path in CRITICAL_DIRECTORIES:
        path = os.path.join(args.output_dir, relative_path)
        if relative_path in missing:
            print(f"  [MISSING/EMPTY] {relative_path}/")
        else:
            print(f"  [OK] {relative_path}/ ({len(os.listdir(path))} files)")
    launcher_mod = args.output_dir + ".mod"
    if launcher_mod in missing:
        print(f"  [MISSING/EMPTY] {os.path.basename(launcher_mod)}")
    else:
        print(f"  [OK] {os.path.basename(launcher_mod)}")

    if missing:
        print(f"\n[VALIDATION FAILED] {len(missing)} required output paths are missing or empty.")
        return EXIT_VALIDATION_ERROR

    print(f"\n[OK] Exported {args.mod_name}: {file_count} files")
    print(
        f"Provinces: {province_count}, states: {len(state_mgr.states)}, "
        f"countries: {len(country_mgr.countries)}"
    )
    print("[VALIDATION PASSED] All critical files are present and ready for an in-game test.")
    return EXIT_SUCCESS


PLANNER_REQUIRED_BY_PROFILE = {
    "foundation": (
        "map/default.map",
        "map/provinces.bmp",
        "map/definition.csv",
        "map/terrain.bmp",
        "map/heightmap.bmp",
        "map/rivers.bmp",
        "descriptor.mod",
    ),
    "acceptance": (
        "map/default.map",
        "map/provinces.bmp",
        "map/definition.csv",
        "map/terrain.bmp",
        "map/heightmap.bmp",
        "map/rivers.bmp",
        "descriptor.mod",
        "common/country_tags/99_acceptance_tags.txt",
    ),
    "scaffold": None,
    "legacy_full": None,
}


def _uses_planner_path(args) -> bool:
    if getattr(args, "profile", "legacy_full") != "legacy_full":
        return True
    for flag in ("game_dir", "manifest", "compare_lock", "json_report"):
        if getattr(args, flag, None):
            return True
    for flag in ("overwrite", "backup", "keep_staging"):
        if getattr(args, flag, False):
            return True
    return False


def _verify_planned_export(output_dir: str, profile_name: str) -> list:
    required = PLANNER_REQUIRED_BY_PROFILE.get(profile_name)
    if required is None:
        return verify_export(output_dir)
    missing = []
    for relative_path in required:
        path = os.path.join(output_dir, relative_path)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            missing.append(relative_path)
    launcher_mod = output_dir + ".mod"
    if not os.path.isfile(launcher_mod) or os.path.getsize(launcher_mod) == 0:
        missing.append(launcher_mod)
    return missing


_PLAN_REPORT_SOURCE = "planner"
_PLAN_REPORT_CONTEXT = "draft_preview"
_ARTIFACT_REPORT_SOURCE = "artifact"
_ARTIFACT_REPORT_CONTEXT = "draft_preview"


def _plan_validation_report(plan):
    from services.validation_service import report_from_findings
    findings = getattr(plan, "findings", ()) or ()
    return report_from_findings(
        findings,
        source=_PLAN_REPORT_SOURCE,
        context=_PLAN_REPORT_CONTEXT,
    )


def _artifact_validation_report(missing):
    from services.validation_service import report_from_verifier_messages
    messages = ["missing or empty: %s" % path for path in (missing or [])]
    return report_from_verifier_messages(
        messages,
        (),
        source=_ARTIFACT_REPORT_SOURCE,
        context=_ARTIFACT_REPORT_CONTEXT,
    )


def _format_validation_summary(report, label):
    counts = report.counts
    total = report.total
    noun = "finding" if total == 1 else "findings"
    return (
        "Validation report (%s): %d %s "
        "(info=%d, warning=%d, error=%d, blocker=%d)"
        % (
            label,
            total,
            noun,
            counts.get("info", 0),
            counts.get("warning", 0),
            counts.get("error", 0),
            counts.get("blocker", 0),
        )
    )


def _validation_detail_lines(report):
    lines = []
    for finding in report.findings:
        lines.append(
            "  [%s] %s: %s"
            % (str(finding.severity).upper(), finding.code, finding.message)
        )
    return lines


def _write_planner_json_report(path, plan, result, plan_report, artifact_report):
    import json
    payload = {
        "plan": plan.to_dict(),
        "result": result.to_dict() if result is not None else None,
        "validation_reports": {
            "plan": plan_report.to_dict() if plan_report is not None else None,
            "artifact": artifact_report.to_dict() if artifact_report is not None else None,
        },
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def run_planner_export(args) -> int:
    configure_console_streams()
    print = _safe_print
    if not os.path.isfile(args.project):
        print(f"Error: project file not found: {args.project}", file=sys.stderr)
        return EXIT_COMMAND_ERROR
    try:
        print(f"Loading project: {args.project}")
        state_mgr = StateManager()
        country_mgr = CountryManager()
        continent_mgr = ContinentManager()
        adjacency_mgr = AdjacencyManager()
        railway_mgr = RailwayManager()
        supply_mgr = SupplyNodeManager()
        adjacency_rule_mgr = AdjacencyRuleManager()
        strategic_region_mgr = StrategicRegionManager()
        map_placement_mgr = MapPlacementManager()
        (
            tile_map,
            province_map,
            terrain_map,
            height_map,
            river_map,
            provincial_terrain,
            _tile_snapshot,
        ) = load_project(
            args.project,
            state_mgr,
            country_mgr,
            continent_mgr=continent_mgr,
            adjacency_mgr=adjacency_mgr,
            railway_mgr=railway_mgr,
            supply_mgr=supply_mgr,
            adjacency_rule_mgr=adjacency_rule_mgr,
            strategic_region_mgr=strategic_region_mgr,
            map_placement_mgr=map_placement_mgr,
        )
        try:
            project_meta = read_project_meta(args.project)
        except Exception:
            project_meta = None
        from services.export_planner import format_plan_summary, plan_export
        height, width = tile_map.shape
        plan = plan_export(
            tile_map,
            province_map,
            terrain_map,
            height_map,
            river_map,
            state_mgr=state_mgr,
            country_mgr=country_mgr,
            continent_mgr=continent_mgr,
            adjacency_mgr=adjacency_mgr,
            railway_mgr=railway_mgr,
            supply_mgr=supply_mgr,
            adjacency_rule_mgr=adjacency_rule_mgr,
            strategic_region_mgr=strategic_region_mgr,
            map_placement_mgr=map_placement_mgr,
            provincial_terrain=provincial_terrain,
            project_meta=project_meta,
            profile_name=args.profile,
            game_dir=args.game_dir,
            repair_policy=args.repair,
            dimensions=(int(width), int(height)),
            mod_name=args.mod_name,
            tag="AAA",
            acceptance_count=int(args.acceptance_count or 0),
        )
        print(format_plan_summary(plan))
        plan_report = _plan_validation_report(plan)
        print(_format_validation_summary(plan_report, "plan"))
        for detail_line in _validation_detail_lines(plan_report):
            print(detail_line)
        if args.compare_lock:
            from services.export_manifest import build_manifest_dict, compare_with_lock
            comparison = compare_with_lock(
                build_manifest_dict(plan, []), args.compare_lock)
            for difference in comparison["differences"]:
                print(f"  [LOCK] {difference['field']}: lock={difference['lock']} "
                      f"manifest={difference['manifest']}")
            if comparison["breaking"]:
                print("Lock comparison found breaking differences; export refused",
                      file=sys.stderr)
                if args.json_report:
                    _write_planner_json_report(
                        args.json_report, plan, None, plan_report, None
                    )
                    print(f"JSON report: {args.json_report}")
                return EXIT_VALIDATION_ERROR
        if plan.blocked:
            for blocker in plan.blockers:
                print(f"  [BLOCKER] {blocker}", file=sys.stderr)
            if args.json_report:
                _write_planner_json_report(
                    args.json_report, plan, None, plan_report, None
                )
                print(f"JSON report: {args.json_report}")
            return EXIT_VALIDATION_ERROR
        from services.export_service import export_planned_mod
        result = export_planned_mod(
            plan,
            args.output_dir,
            overwrite=bool(args.overwrite or args.clean),
            backup=bool(args.backup),
            keep_failed=bool(args.keep_staging),
        )
        print(f"\nExport wrote {len(result.written_files)} files to: {result.output_dir}")
        if result.manifest_path:
            print(f"Manifest: {result.manifest_path}")
        if args.manifest and result.manifest_path:
            shutil.copy2(result.manifest_path, args.manifest)
            print(f"Manifest copied to: {args.manifest}")
    except Exception as exc:
        print(f"[ERROR] Export failed: {exc}", file=sys.stderr)
        return EXIT_COMMAND_ERROR
    missing = _verify_planned_export(args.output_dir, args.profile)
    artifact_report = _artifact_validation_report(missing)
    print(_format_validation_summary(artifact_report, "artifact"))
    for detail_line in _validation_detail_lines(artifact_report):
        print(detail_line)
    if args.json_report:
        _write_planner_json_report(
            args.json_report, plan, result, plan_report, artifact_report
        )
        print(f"JSON report: {args.json_report}")
    if missing:
        for relative_path in missing:
            print(f"  [MISSING/EMPTY] {relative_path}")
        return EXIT_VALIDATION_ERROR
    print("Final verification passed")
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
