"""Complex test world generator — 3 continents + 6 terrains + 5 countries + ethos

Output D:/Documents/Paradox.../mod/WorldTest, alongside TestMOD."""
import os
import shutil
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from export.mod_exporter import export_full_mod
from data.constants import (
    MAP_WIDTH, MAP_HEIGHT, TILE_LAND, TILE_SEA,
    OCEAN_HEIGHT, SEA_LEVEL, LAND_BASE_HEIGHT,
)
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.managers.state import StateManager
from domain.managers.country import CountryManager, NationalSpirit

MOD_DIR = "D:/Documents/Paradox Interactive/Hearts of Iron IV/mod/WorldTest"
MOD_NAME = "WorldTest"

# ─── 1. Clean up old MODs ───────────────────────────────────
if os.path.exists(MOD_DIR):
    shutil.rmtree(MOD_DIR)
os.makedirs(MOD_DIR, exist_ok=True)
outer = os.path.join(os.path.dirname(MOD_DIR), f"{MOD_NAME}.mod")
if os.path.exists(outer):
    os.remove(outer)

# ─── 2. Construct complex tile_map (multiple continents + islands) ───────────────
H, W = MAP_HEIGHT, MAP_WIDTH  # 1024 × 2048
tile_map = np.full((H, W), TILE_SEA, dtype=np.uint8)

# Northern continent Boreas (cold mountains): y=80..380, x=200..900
tile_map[80:380, 200:900] = TILE_LAND
# Central continent Aurelia (core plain): y=350..680, x=300..1500
tile_map[350:680, 300:1500] = TILE_LAND
# There is a small amount of overlap between the northern and central land masses → the two are connected into one continent

# Crimsonia (Jungle), the big southern island: y=720..920, x=550..1300
tile_map[720:920, 550:1300] = TILE_LAND

# Estoria: y=480..680, x=50..220
tile_map[480:680, 50:220] = TILE_LAND

# Eastern island Drakonia: y=200..500, x=1700..1920
tile_map[200:500, 1700:1920] = TILE_LAND

# ─── 3. Construct terrain_map (terrain distribution) ─────────────────────
PI = TERRAIN_PALETTE_INDEX
terrain_map = np.full((H, W), PI["ocean"], dtype=np.uint8)
terrain_map[tile_map == TILE_LAND] = PI["plains"]  # Default land = plains

# Northern Boreas: Mountain + Forest
terrain_map[100:200, 250:850] = PI["mountain"]    # northern main range
terrain_map[200:280, 250:850][tile_map[200:280, 250:850] == TILE_LAND] = PI["hills"]
terrain_map[280:380, 300:850][tile_map[280:380, 300:850] == TILE_LAND] = PI["forest"]

# Aurelia Central: plains + hills + some forests + desert
terrain_map[400:500, 600:1000][tile_map[400:500, 600:1000] == TILE_LAND] = PI["hills"]
terrain_map[500:600, 350:600][tile_map[500:600, 350:600] == TILE_LAND] = PI["forest"]
terrain_map[450:600, 1100:1500][tile_map[450:600, 1100:1500] == TILE_LAND] = PI["desert"]

# Crimsonia South: jungle + marsh
terrain_map[720:920, 550:1300][tile_map[720:920, 550:1300] == TILE_LAND] = PI["jungle"]
terrain_map[820:900, 700:900][tile_map[820:900, 700:900] == TILE_LAND] = PI["marsh"]

# Estoria West Island: forest
terrain_map[480:680, 50:220][tile_map[480:680, 50:220] == TILE_LAND] = PI["forest"]

# Drakonia East Island: mountain + plains
terrain_map[200:350, 1700:1920][tile_map[200:350, 1700:1920] == TILE_LAND] = PI["mountain"]
terrain_map[350:500, 1700:1920][tile_map[350:500, 1700:1920] == TILE_LAND] = PI["hills"]

# ─── 4. Construct height_map (according to terrain)────────────────────────
height_map = np.full((H, W), OCEAN_HEIGHT, dtype=np.uint8)
height_map[tile_map == TILE_LAND] = LAND_BASE_HEIGHT
height_map[terrain_map == PI["hills"]] = 150
height_map[terrain_map == PI["forest"]] = 130
height_map[terrain_map == PI["desert"]] = 115
height_map[terrain_map == PI["jungle"]] = 125
height_map[terrain_map == PI["marsh"]] = 100
height_map[terrain_map == PI["mountain"]] = 220

# ─── 5. Construct a province map (Voronoi, avoid X-crossing)─────────
# The previous grid method had 4 connected corners at each corner = an X-crossing nightmare, which would also produce 1 pixel fragments after repair.
# Voronoi is naturally free of X-crossing.
from domain.generators.province import generate_provinces
province_map, pcount = generate_provinces(tile_map, target_count=500)
print(f"Provinces: {pcount}")

# ─── 6. Automatically divide State ────────────────────────────────────
state_mgr = StateManager()
state_mgr.auto_split(province_map, tile_map, per_state=4)
print(f"States: {len(state_mgr.states)}")

# Determine which country each State belongs to (by geographical center)
def state_centroid(state):
    """Compute the approximate center (cy, cx) of state"""
    if not state.provinces:
        return (0, 0)
    pts = []
    for p in state.provinces[:3]:  # Take the first 3 provinces to speed up
        ys, xs = np.where(province_map == p)
        if len(ys):
            pts.append((float(ys.mean()), float(xs.mean())))
    if not pts:
        return (0, 0)
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

# ─── 7. Create 5 countries + national spirit ───────────────────────
country_mgr = CountryManager()

# AAA Aurelia — Central Plains Power, Democracy, Blue
aurelia = country_mgr.create_country("AAA", "Aurelia", (60, 130, 220))
aurelia.ruling_party = "democratic"
aurelia.popularities = {"democratic": 65, "fascism": 10, "communism": 10, "neutrality": 15}
aurelia.national_spirits = [
    NationalSpirit(
        id="AAA_breadbasket_of_the_world",
        name="Breadbasket of the World",
        desc="Aurelia's broad plains feed countless people.",
        modifiers={
            "consumer_goods_factor": -0.05,
            "stability_factor": 0.10,
            "monthly_population": 0.10,
        },
    ),
    NationalSpirit(
        id="AAA_central_democracy",
        name="Beacon of the Republic",
        desc="Aurelian democracy shines across the known world.",
        modifiers={
            "political_power_gain": 0.15,
            "research_speed_factor": 0.05,
        },
    ),
]

# BBB Boreas — northern mountain cold country, neutral, white
boreas = country_mgr.create_country("BBB", "Boreas", (210, 220, 230))
boreas.ruling_party = "neutrality"
boreas.popularities = {"democratic": 15, "fascism": 5, "communism": 5, "neutrality": 75}
boreas.national_spirits = [
    NationalSpirit(
        id="BBB_mountain_fortress",
        name="Mountain Fortress",
        desc="Enemies falter before Boreas's snowy mountains.",
        modifiers={
            "army_core_defence_factor": 0.20,
            "winter_attrition_factor": -0.30,
            "supply_consumption_factor": 0.05,
        },
        picture="generic_morale_bonus",
    ),
]

# CCC Crimsonia — Southern Jungle Revolutionary State, communism, red
crimsonia = country_mgr.create_country("CCC", "Crimsonia", (200, 40, 50))
crimsonia.ruling_party = "communism"
crimsonia.popularities = {"democratic": 5, "fascism": 5, "communism": 75, "neutrality": 15}
crimsonia.national_spirits = [
    NationalSpirit(
        id="CCC_revolutionary_fervor",
        name="Revolutionary Fervor",
        desc="The people's anger sweeps through Crimsonia's jungles.",
        modifiers={
            "war_support_factor": 0.20,
            "army_morale_factor": 0.15,
            "production_speed_buildings_factor": 0.10,
        },
    ),
    NationalSpirit(
        id="CCC_jungle_warfare",
        name="Jungle Warfare Mastery",
        desc="Crimsonian warriors are one with the jungle.",
        modifiers={
            "jungle_attack_factor": 0.20,
            "jungle_defence_factor": 0.20,
        },
        picture="generic_acquire_tech",
    ),
]

# DDD Drakonia - East Island Mountain Militia, fascist, black
drakonia = country_mgr.create_country("DDD", "Drakonia", (40, 40, 50))
drakonia.ruling_party = "fascism"
drakonia.popularities = {"democratic": 5, "fascism": 75, "communism": 5, "neutrality": 15}
drakonia.national_spirits = [
    NationalSpirit(
        id="DDD_warrior_culture",
        name="Warrior Nation",
        desc="Drakonian children grow up with a sword in hand.",
        modifiers={
            "conscription": 0.025,
            "army_attack_factor": 0.10,
            "training_time_factor": -0.10,
        },
    ),
]

# EEE Estoria - West Island forest and ocean country, neutral, green
estoria = country_mgr.create_country("EEE", "Estoria", (60, 160, 90))
estoria.ruling_party = "neutrality"
estoria.popularities = {"democratic": 30, "fascism": 5, "communism": 5, "neutrality": 60}
estoria.national_spirits = [
    NationalSpirit(
        id="EEE_seafaring_tradition",
        name="Seafaring Tradition",
        desc="Estorian ships once sailed to the end of the world.",
        modifiers={
            "navy_max_range_factor": 0.15,
            "naval_speed_factor": 0.10,
            "production_speed_dockyard_factor": 0.10,
        },
        picture="generic_navy_bonus",
    ),
]

# ─── 8. Assign states to countries according to geographical location ────────────────────
def assign_country_by_position(cy, cx):
    # North (y<350) left → BBB
    if cy < 350 and cx < 1000:
        return "BBB"
    # East Island (x>1600) → DDD
    if cx > 1600:
        return "DDD"
    # West Island (x<260) → EEE
    if cx < 260:
        return "EEE"
    # South (y>700) → CCC
    if cy > 700:
        return "CCC"
    # All others belong to AAA
    return "AAA"

for sid, state in state_mgr.states.items():
    cy, cx = state_centroid(state)
    tag = assign_country_by_position(cy, cx)
    country_mgr.assign_state(sid, tag)
    state.owner_tag = tag

# Set the capital: Each country chooses the first province of its first state as its capital
for tag, c in country_mgr.countries.items():
    state_ids = country_mgr.get_states_of_country(tag)
    if state_ids:
        first_state = state_mgr.get_state(state_ids[0])
        if first_state and first_state.provinces:
            c.capital = first_state.provinces[0]

# Print country distribution
print("\n=== Countries and territory ===")
for tag, c in country_mgr.countries.items():
    sids = country_mgr.get_states_of_country(tag)
    print(f"  {tag} {c.name:12s} → {len(sids):3d} states  party={c.ruling_party:12s}  spirits={len(c.national_spirits)}")

# ─── 9. Call the exporter ───────────────────────────────────
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

print(f"\n[OK] WorldTest MOD: {MOD_DIR}")
file_count = sum(len(files) for _, _, files in os.walk(MOD_DIR))
print(f"     Files: {file_count}")
