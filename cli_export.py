"""Command line export: python cli_export.py <project.hoi4proj> [output_dir] [--mod-name NAME]

Load data from .hoi4proj project files, automatically complete missing content, and export playable MODs."""
import os
import sys
import shutil
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.managers.state import StateManager
from domain.managers.country import CountryManager
from domain.managers.continent import ContinentManager
from domain.managers.adjacency import AdjacencyManager
from domain.managers.railway import RailwayManager
from domain.managers.supply_node import SupplyNodeManager
from domain.managers.adjacency_rule import AdjacencyRuleManager
from domain.managers.strategic_region import StrategicRegionManager
from domain.project_io import load_project
from export.mod_exporter import export_full_mod


DEFAULT_OUTPUT = "D:/Documents/Paradox Interactive/Hearts of Iron IV/mod/WorldTest"
DEFAULT_MOD_NAME = "WorldTest"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export an HOI4 MOD from a .hoi4proj project file"
    )
    parser.add_argument("project", help="Path to the .hoi4proj project file")
    parser.add_argument(
        "output_dir", nargs="?", default=DEFAULT_OUTPUT,
        help=f"Export directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--mod-name", default=DEFAULT_MOD_NAME,
        help=f"MOD name (default: {DEFAULT_MOD_NAME})",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Clear the output directory before exporting",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.project):
        print(f"Error: project file not found: {args.project}")
        sys.exit(1)

    # ── 1. Load project ──
    print(f"Loading project: {args.project}")
    state_mgr = StateManager()
    country_mgr = CountryManager()
    continent_mgr = ContinentManager()
    adjacency_mgr = AdjacencyManager()
    railway_mgr = RailwayManager()
    supply_mgr = SupplyNodeManager()
    adjacency_rule_mgr = AdjacencyRuleManager()
    strategic_region_mgr = StrategicRegionManager()

    tile_map, province_map, terrain_map, height_map, river_map, provincial_terrain, _tile_snapshot = \
        load_project(
            args.project,
            state_mgr, country_mgr,
            continent_mgr=continent_mgr,
            adjacency_mgr=adjacency_mgr,
            railway_mgr=railway_mgr,
            supply_mgr=supply_mgr,
            adjacency_rule_mgr=adjacency_rule_mgr,
            strategic_region_mgr=strategic_region_mgr,
        )

    H, W = tile_map.shape
    pcount = int(province_map.max())
    land_pixels = int(np.sum(tile_map == TILE_LAND))
    sea_pixels = int(np.sum(tile_map == TILE_SEA))
    print(f"Map: {W}x{H}, provinces: {pcount}, land pixels: {land_pixels:,}, sea pixels: {sea_pixels:,}")

    # ── 2. Synchronized terrain ──
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

    # ── 3. Automatically generate height map ──
    if height_map is not None and land_mask.any():
        land_heights = height_map[land_mask]
        if np.all(land_heights == land_heights[0]):
            print("Height map is flat; generating it automatically...")
            from services.terrain_service import auto_height
            height_map = auto_height(tile_map)

    # ── 4. Automatically generate State ──
    if not state_mgr.states:
        print("No states found; generating them automatically...")
        state_mgr.auto_split(province_map, tile_map, per_state=20)
        print(f"Generated states: {len(state_mgr.states)}")
    else:
        print(f"Existing states: {len(state_mgr.states)}")

    # ── 5. Automatically create countries ──
    if not country_mgr.countries:
        print("No countries found; creating a test country automatically...")
        c = country_mgr.create_country("AAA", "Aurora", (60, 130, 220))
        c.ruling_party = "democratic"
        c.popularities = {
            "democratic": 60, "fascism": 10,
            "communism": 10, "neutrality": 20,
        }
        for sid in state_mgr.states:
            country_mgr.assign_state(sid, "AAA")
            state = state_mgr.get_state(sid)
            if state:
                state.owner_tag = "AAA"
        first_state = state_mgr.get_state(1)
        if first_state and first_state.provinces:
            c.capital = first_state.provinces[0]
        print(f"Created country AAA with {len(state_mgr.states)} states")
    else:
        print(f"Existing countries: {list(country_mgr.countries.keys())}")

    # ── 6. Check & fill in default data before export ──
    from services.export_service import pre_export_check_and_fix, fill_default_state_data
    report = pre_export_check_and_fix(
        tile_map, province_map, terrain_map,
        state_mgr, country_mgr, continent_mgr,
        strategic_region_mgr=strategic_region_mgr,
    )
    if report.fixed:
        print("\n── Automatic fixes ──")
        for f in report.fixed:
            print(f"  [FIXED] {f}")
    if report.warnings:
        print("\n── Warnings ──")
        for w in report.warnings:
            print(f"  [WARNING] {w}")

    filled = fill_default_state_data(state_mgr, terrain_map, province_map, tile_map)
    if filled > 0:
        print(f"Filled {filled} states with default resources/buildings")

    # ── 7. Clean up old MODs ──
    if args.clean and os.path.exists(args.output_dir):
        shutil.rmtree(args.output_dir, ignore_errors=True)
        # There is a delay in rmtree on Windows, waiting for the directory to disappear.
        import time
        for _ in range(50):
            if not os.path.exists(args.output_dir):
                break
            time.sleep(0.1)
        print(f"Cleared: {args.output_dir}")
    os.makedirs(args.output_dir, exist_ok=True)

    # ── 8. Export ──
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
        provincial_terrain=provincial_terrain,
    )

    file_count = sum(len(files) for _, _, files in os.walk(args.output_dir))
    print(f"\n[OK] Exported {args.mod_name}: {file_count} files")
    print(f"Provinces: {pcount}, states: {len(state_mgr.states)}, "
          f"countries: {len(country_mgr.countries)}")

    # ── 9. Export verification ──
    print("\n── Export verification ──")
    critical_files = [
        "map/default.map", "map/provinces.bmp", "map/definition.csv",
        "map/terrain.bmp", "map/heightmap.bmp", "map/rivers.bmp",
        "map/buildings.txt", "map/positions.txt", "map/adjacencies.csv",
        "map/supply_nodes.txt", "map/railways.txt", "map/continent.txt",
        "descriptor.mod",
    ]
    missing = []
    for f in critical_files:
        path = os.path.join(args.output_dir, f)
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size == 0:
                print(f"  [EMPTY FILE] {f}")
                missing.append(f)
            else:
                print(f"  [OK] {f} ({size:,} bytes)")
        else:
            print(f"  [MISSING] {f}")
            missing.append(f)

    # Check directory
    for d in ["history/states", "history/countries", "common/country_tags"]:
        dp = os.path.join(args.output_dir, d)
        if os.path.isdir(dp):
            count = len(os.listdir(dp))
            print(f"  [OK] {d}/ ({count} files)")
        else:
            print(f"  [MISSING] {d}/")
            missing.append(d)

    # .mod launcher file
    mod_file = args.output_dir + ".mod"
    if os.path.exists(mod_file):
        print(f"  [OK] {os.path.basename(mod_file)}")
    else:
        print(f"  [MISSING] {os.path.basename(mod_file)}")
        missing.append(mod_file)

    if missing:
        print(f"\n[WARNING] {len(missing)} critical files are missing or empty!")
    else:
        print("\n[VALIDATION PASSED] All critical files are present and ready for an in-game test.")


if __name__ == "__main__":
    main()
