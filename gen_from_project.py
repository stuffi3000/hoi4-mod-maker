"""Load the map from the .hoi4proj saved by the user, complete the missing content, and export the playable MOD.

Usage: python gen_from_project.py <project path>"""
import os
import sys
import json
import zipfile
import shutil
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT, TILE_LAND, TILE_SEA, TILE_LAKE,
    OCEAN_HEIGHT, SEA_LEVEL, LAND_BASE_HEIGHT,
)
from data.terrain_types import TERRAIN_TYPES, TERRAIN_PALETTE_INDEX
from domain.managers.state import StateManager
from domain.managers.country import CountryManager
from export.mod_exporter import export_full_mod

# ─── Configuration ───
PROJECT_PATH = sys.argv[1] if len(sys.argv) > 1 else \
    "C:/Users/Administrator.SKY-20180310BMB/Desktop/Aurora/1.hoi4proj"
MOD_DIR = "D:/Documents/Paradox Interactive/Hearts of Iron IV/mod/WorldTest"
MOD_NAME = "WorldTest"

# ─── 1. Load project ───
print(f"Loading project: {PROJECT_PATH}")
with zipfile.ZipFile(PROJECT_PATH) as z:
    tile_map = np.load(z.open('tile_map.npy'))
    province_map = np.load(z.open('province_map.npy'))
    terrain_map = np.load(z.open('terrain_map.npy'))
    height_map = np.load(z.open('height_map.npy'))
    river_map = np.load(z.open('river_map.npy'))
    states_data = json.load(z.open('states.json'))
    countries_data = json.load(z.open('countries.json'))

H, W = tile_map.shape
pcount = int(province_map.max())
land_pixels = int(np.sum(tile_map == TILE_LAND))
sea_pixels = int(np.sum(tile_map == TILE_SEA))
print(f"Map: {W}x{H}, provinces: {pcount}, land: {land_pixels:,}, sea: {sea_pixels:,}")

# ─── 2. Automatically generate terrain (if all are default) ───
unique_terrain = np.unique(terrain_map)
print(f"Terrain indices: {unique_terrain.tolist()}")

# Correction: There should be no ocean terrain on land, change it to plains
land_mask = tile_map == TILE_LAND
ocean_idx = TERRAIN_PALETTE_INDEX["ocean"]  # 15
plains_idx = TERRAIN_PALETTE_INDEX["plains"]  # 0
bad_terrain = land_mask & (terrain_map == ocean_idx)
bad_count = int(np.sum(bad_terrain))
if bad_count > 0:
    terrain_map[bad_terrain] = plains_idx
    print(f"Fixed: changed {bad_count:,} land pixels from ocean terrain to plains")

# Fixed: There should not be land terrain on the ocean
sea_mask = tile_map == TILE_SEA
sea_bad = sea_mask & (terrain_map != ocean_idx)
sea_bad_count = int(np.sum(sea_bad))
if sea_bad_count > 0:
    terrain_map[sea_bad] = ocean_idx
    print(f"Fixed: changed {sea_bad_count:,} sea pixels to ocean terrain")

# ─── 3. Automatically generate height maps (if all are default) ───
land_mask = tile_map == TILE_LAND
if np.all(height_map[land_mask] == height_map[land_mask][0] if land_mask.any() else True):
    print("Heightmap is flat; generating it automatically...")
    from services.terrain_service import auto_height
    height_map = auto_height(tile_map)
else:
    print("Heightmap already contains terrain variation")

# ─── 4. State Manager ───
state_mgr = StateManager()
if states_data.get('states'):
    state_mgr.from_dict(states_data)
    print(f"Existing states: {len(state_mgr.states)}")
else:
    print("No states found; generating them automatically...")
    state_mgr.auto_split(province_map, tile_map, per_state=20)
    print(f"Generated states: {len(state_mgr.states)}")

# ─── 5. Country ───
country_mgr = CountryManager()
has_countries = bool(countries_data.get('countries', {}).get('countries'))
if has_countries:
    country_mgr.from_dict(countries_data)
    print(f"Existing countries: {list(country_mgr.countries.keys())}")
else:
    print("No countries found; creating a test country...")
    # Create a test country that owns all landmasses
    c = country_mgr.create_country("AAA", "Aurora", (60, 130, 220))
    c.ruling_party = "democratic"
    c.popularities = {"democratic": 60, "fascism": 10, "communism": 10, "neutrality": 20}

    # All states belong to AAA
    for sid in state_mgr.states:
        country_mgr.assign_state(sid, "AAA")
        state = state_mgr.get_state(sid)
        if state:
            state.owner_tag = "AAA"

    # Set up capital
    first_state = state_mgr.get_state(1)
    if first_state and first_state.provinces:
        c.capital = first_state.provinces[0]

    print(f"Created country AAA with {len(state_mgr.states)} states")

# ─── 6. Clean up old MODs ───
if os.path.exists(MOD_DIR):
    shutil.rmtree(MOD_DIR)
os.makedirs(MOD_DIR, exist_ok=True)

# ─── 7. Export ───
print(f"\nExporting to: {MOD_DIR}")
export_full_mod(
    tile_map=tile_map,
    province_map=province_map,
    output_dir=MOD_DIR,
    mod_name=MOD_NAME,
    tag="AAA",
    state_mgr=state_mgr,
    country_mgr=country_mgr,
    terrain_map=terrain_map,
    height_map=height_map,
)

file_count = sum(len(files) for _, _, files in os.walk(MOD_DIR))
print(f"\n[OK] Exported {MOD_NAME}: {file_count} files")
print("The mod is ready for in-game testing.")
