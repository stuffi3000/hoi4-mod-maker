"""
HOI4 硬规则中心 — 所有从 Paradox 官方文档抽出的硬规则集中在这里。

来源：参考/Map modding.txt（用户本地保存的官方 wiki）

任何修改这个文件的，都要在注释里写明出处行号或原文，避免凭记忆编规则。
其他模块（validator / exporter / generator）从这里读规则，禁止把数字硬编码到别处。
"""

from data.constants import MAP_WIDTH, MAP_HEIGHT
from ui.i18n import tr_pair


class Hoi4Rules:
    """HOI4 引擎对地图文件的硬性约束。所有字段是常量。"""

    # ───────────── BMP 文件格式 ─────────────
    # 来源：Map modding.txt 第 71-104 行
    BMP_BITDEPTH = {
        "provinces":    24,   # 24-bit RGB
        "heightmap":    8,    # 8-bit greyscale
        "world_normal": 24,
        "terrain":      8,    # 8-bit indexed
        "rivers":       8,    # 8-bit indexed
        "trees":        8,    # 8-bit indexed
        "cities":       8,    # 8-bit indexed
    }
    # 来源：Map modding.txt 第 206 行
    BMP_BOTTOM_UP = True  # 像素数据从下到上写
    BMP_NO_COMPRESSION = True

    # ───────────── 地图尺寸约束 ─────────────
    # 来源：Map modding.txt 第 206 行
    # "both length and width have to be a multiple of 256"
    MAP_DIM_MULTIPLE = 256

    # 来源：Map modding.txt 第 206 行
    # "the total area of the file in pixels cannot exceed 13 238 272"
    MAP_MAX_TOTAL_PIXELS = 13_238_272

    # 来源：Map modding.txt 第 151-153 行
    MAP_WRAPS_HORIZONTALLY = True
    MAP_WRAPS_VERTICALLY = False

    # ───────────── 省份规则 ─────────────
    # 来源：Map modding.txt 第 239 行
    # "NGraphics.MINIMUM_PROVINCE_SIZE_IN_PIXELS (8 by default)"
    MIN_PROVINCE_PIXELS = 8

    # 来源：Map modding.txt 第 238 行
    # "width/height of more than 1/8th of the total map width/height"
    PROVINCE_MAX_BBOX_RATIO = 1.0 / 8

    # 来源：Map modding.txt 第 230 行
    # "No more than 65536 different province borders... usually hit at about 21000"
    PROVINCE_HARD_MAX = 21000   # 必崩
    PROVINCE_SOFT_MAX = 14000   # 强烈建议上限
    PROVINCE_RECOMMENDED = 13000  # vanilla 量级

    # 来源：Map modding.txt 第 227 行
    # "Province IDs should go in order. While a gap... will create a different problem"
    PROVINCE_IDS_MUST_BE_CONTIGUOUS = True

    # 来源：Map modding.txt 第 237 行
    # "Map invalid X crossing. Four provinces share a common corner"
    FORBID_X_CROSSINGS = True

    # 来源：Map modding.txt 第 232 行
    # "These disjointed island provinces may also cause a game crash"
    FORBID_DISJOINTED_PIECES = True  # 一个 ID 必须是单连通块

    # 来源：Map modding.txt 第 257 行
    # "All land provinces must belong to a continent to avoid errors"
    LAND_REQUIRES_CONTINENT = True

    # ───────────── 省份类型与地形 ─────────────
    # 来源：Map modding.txt 第 224 行
    # "For lake provinces, terrain must be 'lakes' while for sea provinces it must be 'ocean'"
    REQUIRED_TERRAIN_BY_TYPE = {
        "lake": "lakes",
        "sea":  "ocean",
    }

    # 来源：Map modding.txt 第 225 行
    # 1.11+ 后 coastal 字段以 bitmap 邻接为准，definition.csv 的 coastal 字段被忽略
    COASTAL_DETERMINED_BY_BITMAP = True

    # ───────────── 河流规则 ─────────────
    # 来源：Map modding.txt 第 394 行
    # "Rivers must be exactly one pixel thick and only go in orthogonal directions"
    RIVER_PIXEL_WIDTH = 1
    RIVER_DIAGONAL_FORBIDDEN = True

    # 来源：Map modding.txt 第 396 行
    # "each river must have exactly one... green start marker"
    RIVER_REQUIRES_ONE_GREEN_SOURCE = True

    # 来源：Map modding.txt 第 412 行
    RIVER_INDEX_SMALL_MAX = 6   # 索引 0-6 是小河
    RIVER_INDEX_LARGE_MAX = 11  # 索引 7-11 是大河

    # ───────────── 编码 ─────────────
    LOCALIZATION_ENCODING = "utf-8-sig"  # UTF-8 with BOM

    # ═══════════════ 检查函数 ═══════════════

    @classmethod
    def check_map_dimensions(cls, w: int, h: int) -> list[str]:
        """检查地图尺寸是否符合 HOI4 约束。返回错误列表（空=合法）。"""
        errors = []
        if w % cls.MAP_DIM_MULTIPLE != 0:
            errors.append(tr_pair(f"地图宽度 {w} 不是 {cls.MAP_DIM_MULTIPLE} 的倍数", f"Map width {w} is not a multiple of {cls.MAP_DIM_MULTIPLE}"))
        if h % cls.MAP_DIM_MULTIPLE != 0:
            errors.append(tr_pair(f"地图高度 {h} 不是 {cls.MAP_DIM_MULTIPLE} 的倍数", f"Map height {h} is not a multiple of {cls.MAP_DIM_MULTIPLE}"))
        if w * h > cls.MAP_MAX_TOTAL_PIXELS:
            errors.append(
                tr_pair(f"地图总像素 {w*h} 超过 HOI4 上限 {cls.MAP_MAX_TOTAL_PIXELS}", f"Total map pixels {w*h} exceed HOI4's limit of {cls.MAP_MAX_TOTAL_PIXELS}")
            )
        return errors

    @classmethod
    def violates_too_large_box(cls, bbox_w: int, bbox_h: int,
                                map_w: int = MAP_WIDTH,
                                map_h: int = MAP_HEIGHT) -> bool:
        """单省份的 bbox 是否超过地图 1/8（TOO LARGE BOX 错误）。"""
        return (bbox_w > map_w * cls.PROVINCE_MAX_BBOX_RATIO
                or bbox_h > map_h * cls.PROVINCE_MAX_BBOX_RATIO)

    @classmethod
    def province_count_warning(cls, count: int) -> str:
        """返回省份总数对应的警告字符串，无问题返回空。"""
        if count > cls.PROVINCE_HARD_MAX:
            return tr_pair(f"危险：{count} > {cls.PROVINCE_HARD_MAX}，超过 HOI4 边界硬上限，必崩", f"Danger: {count} > {cls.PROVINCE_HARD_MAX}, exceeding HOI4's hard limit and guaranteed to crash")
        if count > cls.PROVINCE_SOFT_MAX:
            return tr_pair(f"警告：{count} > {cls.PROVINCE_SOFT_MAX}，HOI4 文档建议上限", f"Warning: {count} > {cls.PROVINCE_SOFT_MAX}, the limit recommended by HOI4 documentation")
        if count > cls.PROVINCE_RECOMMENDED:
            return tr_pair(f"提示：{count} 接近 vanilla {cls.PROVINCE_RECOMMENDED}-{cls.PROVINCE_SOFT_MAX} 推荐区间", f"Note: {count} is close to the recommended vanilla range of {cls.PROVINCE_RECOMMENDED}–{cls.PROVINCE_SOFT_MAX}")
        return ""
