"""
HOI4 地图 MOD 工具 — 全局常量定义
"""

# 地图尺寸（必须是 256 的倍数，否则 HOI4 崩溃 — 见 参考/Troubleshooting.txt:100）
# 原版 5632×2048
MAP_WIDTH = 5632
MAP_HEIGHT = 2048

# 地图尺寸预设
MAP_SIZE_PRESETS = {
    "小 (2048×1024)": (2048, 1024),
    "中 (3072×1536)": (3072, 1536),
    "大 (4096×2048)": (4096, 2048),
    "原版 (5632×2048)": (5632, 2048),
}


def set_map_size(width: int, height: int) -> None:
    """更新全局地图尺寸。必须在初始化画布数组之前调用。"""
    import data.constants as _mod
    _mod.MAP_WIDTH = width
    _mod.MAP_HEIGHT = height

# 省份数量范围 (vanilla 13382, HOI4 上限 21000, 14000 以上警告)
MIN_PROVINCES = 1000
MAX_PROVINCES = 15000
DEFAULT_PROVINCES = 12000

# 省份最小像素数
# HOI4 硬性最低 8 像素，但 <50 像素的省份会导致 buildings.txt 坐标问题
# 生成时合并阈值设 50，确保每个省份足够大
MIN_PROVINCE_PIXELS = 50

# 省份数量上限（HOI4 引擎限制）
ENGINE_MAX_PROVINCES = 19000

# 高度图参数
SEA_LEVEL = 95          # 海平面灰度值
OCEAN_HEIGHT = 40       # 深海灰度值
LAND_BASE_HEIGHT = 120  # 陆地基础灰度值
MOUNTAIN_HEIGHT = 220   # 山地灰度值

# 画布缩放范围
ZOOM_MIN = 0.05
ZOOM_MAX = 10.0
ZOOM_STEP = 1.2

# 画笔大小范围
BRUSH_MIN = 1
BRUSH_MAX = 100
BRUSH_DEFAULT = 10

# 地块类型（内部表示）
TILE_UNDEFINED = 0
TILE_LAND = 1
TILE_SEA = 2
TILE_LAKE = 3

# 地块类型名称映射
TILE_TYPE_NAMES = {
    TILE_UNDEFINED: "undefined",
    TILE_LAND: "land",
    TILE_SEA: "sea",
    TILE_LAKE: "lake",
}

# HOI4 definition.csv 类型名
PROVINCE_TYPE_LAND = "land"
PROVINCE_TYPE_SEA = "sea"
PROVINCE_TYPE_LAKE = "lake"

# 禁用颜色（HOI4 不允许使用）
FORBIDDEN_COLOR = (0, 0, 0)

# ════════════════════════════════════════════════════════════
# HOI4 合法意识形态白名单
# ════════════════════════════════════════════════════════════
# 主意识形态（用于 set_politics.ruling_party 和 set_popularities 的键）
# 来源：vanilla common/ideologies/00_ideologies.txt
VALID_MAIN_IDEOLOGIES = ("neutrality", "democratic", "fascism", "communism")

# 意识形态子类型（用于 country_leader.ideology 字段）
# 每个主意识形态对应一个默认子类型，保证 leader 定义一定合法
DEFAULT_IDEOLOGY_SUBTYPE = {
    "neutrality": "despotism",
    "democratic": "conservatism",
    "fascism": "nazism",
    "communism": "marxism",
}

# ════════════════════════════════════════════════════════════
# HOI4 合法 3D 建筑类型白名单（buildings.txt 可用类型）
# ════════════════════════════════════════════════════════════
# 来源：vanilla common/buildings/00_buildings.txt 中 spawn_point / has_pop_center = yes 的实体建筑
# 关键：infrastructure / air_base / supply_hub 等 state-level 统计建筑【不能】写入 buildings.txt
# 只有这些"有 3D 模型的点位建筑"合法，否则引擎会 MAP_ERROR 崩溃
VALID_3D_BUILDING_TYPES = frozenset({
    "arms_factory", "industrial_complex", "air_base", "anti_air_building",
    "bunker", "coastal_bunker", "dockyard", "naval_base", "naval_base_spawn",
    "supply_node", "rocket_site", "rocket_site_spawn",
    "synthetic_refinery", "radar_station", "fuel_silo", "nuclear_reactor",
    "floating_harbor",
})

# BMP 文件常量
BMP_HEADER_SIZE = 14
BMP_INFO_HEADER_SIZE = 40
BMP_BITS_24 = 24
BMP_BITS_8 = 8

# 默认 MOD 信息
DEFAULT_MOD_NAME = "Fantasy World"
DEFAULT_MOD_VERSION = "0.1"
# 兜底值 — 导出时优先用 services.game_assets.resolve_supported_version()
# 从本机游戏安装实测版本, 检测不到才用这个
DEFAULT_SUPPORTED_VERSION = "1.19.*"

# HOI4 路径（用户可配置）
DEFAULT_HOI4_PATH = "G:/SteamLibrary/steamapps/common/Hearts of Iron IV/"
DEFAULT_MOD_OUTPUT_PATH = "D:/Documents/Paradox Interactive/Hearts of Iron IV/mod/"


# ════════════════════════════════════════════════════════════
# Vanilla TAG 黑名单（避免与 vanilla 国家撞车）
# ════════════════════════════════════════════════════════════
# 用户创建国家时, TAG 不能撞 vanilla, 否则:
#   - vanilla 的 events/decisions/scripted_effects 引用同名 TAG 时会触发到我们国家
#   - vanilla 的 localisation key (TAG=Germany 等) 可能覆盖我们的国名
# Fallback 列表是 HOI4 1.17 截至 2026-05 的全部 vanilla TAG (含 D01-D75 dynamic slot)
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
    """获取 vanilla 占用的所有 TAG (frozenset). 结果缓存到进程结束.

    优先动态读 vanilla 的 country_tags 目录 (DLC 更新后自动获取最新),
    读不到则用硬编码 fallback (1.17 截至 2026-05).
    """
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
    """TAG 是否被 vanilla 占用 (大小写不敏感)."""
    return tag.upper() in get_vanilla_tags()

# 全转换 MOD 替换路径
# 只替换我们实际提供完整内容或有意清空的目录，避免加载引用旧地图数据的原版内容。
# 未替换的目录会继续使用原版内容（game_rules、modifiers 等）。
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
