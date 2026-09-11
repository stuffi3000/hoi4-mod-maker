"""HOI4 Map MOD Tool - Global Constant Definition"""

# Map size (must be a multiple of 256, otherwise HOI4 crashes — see refs/Troubleshooting.txt:100)
# Original 5632×2048
MAP_WIDTH = 5632
MAP_HEIGHT = 2048

# Map size defaults
MAP_SIZE_PRESETS = {
    "Small (2048×1024)": (2048, 1024),
    "Medium (3072×1536)": (3072, 1536),
    "Large (4096×2048)": (4096, 2048),
    "Vanilla (5632×2048)": (5632, 2048),
}


def set_map_size(width: int, height: int) -> None:
    """Update global map dimensions. Must be called before initializing the canvas array."""
    import data.constants as _mod
    _mod.MAP_WIDTH = width
    _mod.MAP_HEIGHT = height

# Province number range (vanilla 13382, HOI4 upper limit 21000, warning above 14000)
MIN_PROVINCES = 1000
MAX_PROVINCES = 15000
DEFAULT_PROVINCES = 12000

# Province minimum number of pixels
# HOI4 has a hard minimum of 8 pixels, but provinces <50 pixels will cause issues with buildings.txt coordinates
# The merge threshold is set to 50 when generating to ensure that each province is large enough
MIN_PROVINCE_PIXELS = 50

# Maximum number of provinces (HOI4 engine limit)
ENGINE_MAX_PROVINCES = 19000

# Heightmap parameters
SEA_LEVEL = 95          # sea level gray value
OCEAN_HEIGHT = 40       # Deep sea gray value
LAND_BASE_HEIGHT = 120  # Land basic gray value
MOUNTAIN_HEIGHT = 220   # Mountain gray value

# Canvas zoom range
ZOOM_MIN = 0.05
ZOOM_MAX = 10.0
ZOOM_STEP = 1.2

# Brush size range
BRUSH_MIN = 1
BRUSH_MAX = 100
BRUSH_DEFAULT = 10

# Parcel type (internal representation)
TILE_UNDEFINED = 0
TILE_LAND = 1
TILE_SEA = 2
TILE_LAKE = 3

# Parcel type name mapping
TILE_TYPE_NAMES = {
    TILE_UNDEFINED: "undefined",
    TILE_LAND: "land",
    TILE_SEA: "sea",
    TILE_LAKE: "lake",
}

# HOI4 definition.csv type name
PROVINCE_TYPE_LAND = "land"
PROVINCE_TYPE_SEA = "sea"
PROVINCE_TYPE_LAKE = "lake"

# Disabled colors (not allowed in HOI4)
FORBIDDEN_COLOR = (0, 0, 0)

# ════════════════════════════════════════════════════════════
# HOI4 Legal Ideology Whitelist
# ════════════════════════════════════════════════════════════
# Primary ideology (key used for set_politics.ruling_party and set_popularities)
# Source: vanilla common/ideologies/00_ideologies.txt
VALID_MAIN_IDEOLOGIES = ("neutrality", "democratic", "fascism", "communism")

# Ideology subtype (for country_leader.ideology field)
# Each main ideology corresponds to a default subtype, ensuring that the leader definition must be legal.
DEFAULT_IDEOLOGY_SUBTYPE = {
    "neutrality": "despotism",
    "democratic": "conservatism",
    "fascism": "nazism",
    "communism": "marxism",
}

# ════════════════════════════════════════════════════════════
# HOI4 legal 3D building type whitelist (buildings.txt available types)
# ════════════════════════════════════════════════════════════
# Source: entity building with spawn_point / has_pop_center = yes in vanilla common/buildings/00_buildings.txt
# Key: infrastructure / air_base / supply_hub and other state-level statistical buildings [cannot] be written to buildings.txt
# Only these "point buildings with 3D models" are legal, otherwise the engine will crash with MAP_ERROR
VALID_3D_BUILDING_TYPES = frozenset({
    "arms_factory", "industrial_complex", "air_base", "anti_air_building",
    "bunker", "coastal_bunker", "dockyard", "naval_base", "naval_base_spawn",
    "supply_node", "rocket_site", "rocket_site_spawn",
    "synthetic_refinery", "radar_station", "fuel_silo", "nuclear_reactor",
    "floating_harbor",
})

# BMP file constants
BMP_HEADER_SIZE = 14
BMP_INFO_HEADER_SIZE = 40
BMP_BITS_24 = 24
BMP_BITS_8 = 8

# Default MOD information
DEFAULT_MOD_NAME = "Fantasy World"
DEFAULT_MOD_VERSION = "0.1"
# Bottom line - use services.game_assets.resolve_supported_version() first when exporting
# Install the actual test version from the local game, only use this if it cannot be detected
DEFAULT_SUPPORTED_VERSION = "1.19.*"

# HOI4 path (user configurable)
DEFAULT_HOI4_PATH = "G:/SteamLibrary/steamapps/common/Hearts of Iron IV/"
DEFAULT_MOD_OUTPUT_PATH = "D:/Documents/Paradox Interactive/Hearts of Iron IV/mod/"


# ════════════════════════════════════════════════════════════
# Vanilla TAG blacklist (to avoid collision with vanilla countries)
# ════════════════════════════════════════════════════════════
# When a user creates a country, the TAG cannot match vanilla, otherwise:
# - Vanilla events/decisions/scripted_effects will trigger to our country when referencing the TAG with the same name
# - vanilla localization key (TAG=Germany, etc.) may override our country name
# The Fallback list is all vanilla TAGs from HOI4 1.17 as of 2026-05 (including D01-D75 dynamic slot)
_VANILLA_TAGS_FALLBACK = frozenset((
    "ABK ADU AFA AFG ALB ALG ALT ANG ANU AOI ARG ARM AST ASY ATJ AUS AZR BAH BAN BAR "
    "BAS BAY BEG BEL BHR BHU BIA BLC BLR BLZ BOL BOS BOT BRA BRD BRI BRM BRN BSK "
    "BLI BOU BUK BUL BYA CAM CAN CAR CAT CAY CBV CHA CHI CHL CHM CHR CHU CIN CIP CKK CMR "
    "COG COL COR COS CPS CRC CRI CRO CSA CUB CYP CZE D01 D02 D03 D04 D05 D06 D07 D08 "
    "D09 D10 D11 D12 D13 D14 D15 D16 D17 D18 D19 D20 D21 D22 D23 D24 D25 D26 D27 "
    "D28 D29 D30 D31 D32 D33 D34 D35 D36 D37 D38 D39 D40 D41 D42 D43 D44 D45 D46 "
    "D47 D48 D49 D50 D51 D52 D53 D54 D55 D56 D57 D58 D59 D60 D61 D62 D63 D64 D65 "
    "D66 D67 D68 D69 D70 D71 D72 D73 D74 D75 DAG DAH DDR DEN DIP DJI DNZ DOM DON "
    "ECU EGY ELS ENG EQG ERI EST ETH EVE EZO FER FIJ FIN FOR FRA FSA FSM GAB GAL "
    "GAM GAR GBA GDC GDL GEN GEO GER GHA GLC GNA GNB GOW GRE GRN GSM GUA GUM GXC GYA "
    "HAI HAN HAR HAW HBC HES HOL HON HRZ HUN HYD IAS ICE IMO INC INS INU IRE IRQ "
    "ISR ITA ITZ IVO JAM JAN JAP JOR KAL KAR KAS KAT KAZ KBK KEN KHA KHI KHL KHM "
    "KKP KLT KOL KOM KOR KOS KSH KUB KUM KUR KUW KYR LAO LAT LBA LBV LEB LIB LIT "
    "LUX MAC MAD MAL MAN MAY MEK MEL MEN MEX MIS MLD MLI MLT MLW MNT MOL MON MOR "
    "MPU MRT MYS MZB NAH NAV NEN NEP NGA NGR NIC NIR NMB NOA NOR NWF NXM NZL OCC "
    "OKN OMA ORO OVO PAK PAL PAN PAP PAR PER PHI PLU PNG POK POL POR PRC PRE PRU PSH "
    "PSR PUE QAT QEM QUE RAA RAJ RAN RAP RAR RAS RCG RCO RGB RHD RHI RIF RIG RJP "
    "RKA RKB RKC RKG RKH RKI RKK RKL RKM RKN RKO RKT RKU RKV RNA RNG ROA ROM RUS "
    "RUT RWA SAB SAF SAM SAR SAU SAX SCO SDL SEN SER SHL SHX SIA SIC SID SIE SIK "
    "SIL SIN SKK SLO SLV SMI SND SNG SOK SOL SOM SOV SPM SPR SRL SSI SUD SUR SWE SWI "
    "SYR TAH TAJ TAN TAT TAY THU TIB TIG TML TMS TNE TOG TOS TRA TRI TTS TUN TUR TZN "
    "UAE UBD UDM UGA UKR URG USA USB UZB VAN VEN VGE VIN VLA VOL WES WGR WIS WLA WLS "
    "WPG WUR XIC XSM YAK YAM YEM YUC YUG YUN ZAM ZIM"
).split())

_VANILLA_TAGS_CACHE: frozenset[str] | None = None


def get_vanilla_tags() -> frozenset[str]:
    """Get all TAGs occupied by vanilla (frozenset). The results are cached until the end of the process.

    Prioritize dynamically reading the country_tags directory of vanilla (automatically obtain the latest after DLC is updated),
    If it cannot be read, use hard-coded fallback (1.17 as of 2026-05)."""
    global _VANILLA_TAGS_CACHE
    if _VANILLA_TAGS_CACHE is not None:
        return _VANILLA_TAGS_CACHE

    import json
    import os
    import re
    tags = set(_VANILLA_TAGS_FALLBACK)
    tags_dirs = [os.path.join(DEFAULT_HOI4_PATH, "common", "country_tags")]
    # The editor stores the selected Steam installation separately from this
    # module's historical default path.  Read it here as well so exports see
    # country tags added by the installed game/DLC and can provide matching
    # histories when ``history/countries`` is replaced.
    config_path = os.path.join(os.path.expanduser("~"), ".hoi4_map_maker.json")
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            configured_path = json.load(config_file).get("hoi4_game_dir")
        if configured_path:
            configured_tags_dir = os.path.join(
                os.fspath(configured_path), "common", "country_tags"
            )
            if configured_tags_dir not in tags_dirs:
                tags_dirs.insert(0, configured_tags_dir)
    except (OSError, TypeError, ValueError):
        pass

    for tags_dir in tags_dirs:
        if os.path.isdir(tags_dir):
            tag_pat = re.compile(r"^\s*([A-Z][A-Z0-9]{2})\s*=")
            for fn in os.listdir(tags_dir):
                if not fn.endswith(".txt"):
                    continue
                try:
                    with open(os.path.join(tags_dir, fn), "r",
                              encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            m = tag_pat.match(line)
                            if m:
                                tags.add(m.group(1))
                except OSError:
                    pass
    _VANILLA_TAGS_CACHE = frozenset(tags)
    return _VANILLA_TAGS_CACHE


def is_vanilla_tag(tag: str) -> bool:
    """Whether TAG is occupied by vanilla (case insensitive)."""
    return tag.upper() in get_vanilla_tags()

# Full conversion MOD replacement path
# Only replace directories where we actually provide full content or intentionally empty them to avoid loading original content that references old map data.
# Unreplaced directories will continue to use the original content (game_rules, modifiers, etc.).
REPLACE_PATHS = [
    # The exporter produces complete replacements for these map, history,
    # country, bookmark, character, and event directories.  Keeping these
    # paths in one list makes descriptor.mod and the launcher-facing .mod file
    # agree on the content that the export owns.
    "map/strategicregions",
    "map/supplyareas",
    "history/states",
    "history/countries",
    "history/units",
]
