"""HOI4 Hard Rules Center - All hard rules pulled from the official Paradox documentation are gathered here.

Source: Reference/Map modding.txt (official wiki saved locally by the user)

Anyone who modifies this file must indicate the source line number or original text in the comments to avoid making up rules from memory.
Other modules (validator/exporter/generator) read rules from here and are prohibited from hardcoding numbers elsewhere."""

from data.constants import MAP_WIDTH, MAP_HEIGHT

class Hoi4Rules:
    """The HOI4 engine has hard constraints on map files. All fields are constants."""

    # ───────────── BMP file format ─────────────
    # Source: Map modding.txt lines 71-104
    BMP_BITDEPTH = {
        "provinces":    24,   # 24-bit RGB
        "heightmap":    8,    # 8-bit greyscale
        "world_normal": 24,
        "terrain":      8,    # 8-bit indexed
        "rivers":       8,    # 8-bit indexed
        "trees":        8,    # 8-bit indexed
        "cities":       8,    # 8-bit indexed
    }
    # Source: Map modding.txt line 206
    BMP_BOTTOM_UP = True  # Pixel data is written from bottom to top
    BMP_NO_COMPRESSION = True

    # ───────────── Map size constraints ──────────────
    # Source: Map modding.txt line 206
    # "both length and width have to be a multiple of 256"
    MAP_DIM_MULTIPLE = 256

    # Source: Map modding.txt line 206
    # "the total area of the file in pixels cannot exceed 13 238 272"
    MAP_MAX_TOTAL_PIXELS = 13_238_272

    # Source: Map modding.txt lines 151-153
    MAP_WRAPS_HORIZONTALLY = True
    MAP_WRAPS_VERTICALLY = False

    # ──────────── Provincial Rules ─────────────
    # Source: Map modding.txt line 239
    # "NGraphics.MINIMUM_PROVINCE_SIZE_IN_PIXELS (8 by default)"
    MIN_PROVINCE_PIXELS = 8

    # Source: Map modding.txt line 238
    # "width/height of more than 1/8th of the total map width/height"
    PROVINCE_MAX_BBOX_RATIO = 1.0 / 8

    # Source: Map modding.txt line 230
    # "No more than 65536 different province borders... usually hit at about 21000"
    PROVINCE_HARD_MAX = 21000   # Will collapse
    PROVINCE_SOFT_MAX = 14000   # Highly recommended cap
    PROVINCE_RECOMMENDED = 13000  # vanilla magnitude

    # Source: Map modding.txt line 227
    # "Province IDs should go in order. While a gap... will create a different problem"
    PROVINCE_IDS_MUST_BE_CONTIGUOUS = True

    # Source: Map modding.txt line 237
    # "Map invalid X crossing. Four provinces share a common corner"
    FORBID_X_CROSSINGS = True

    # Source: Map modding.txt line 232
    # "These disjointed island provinces may also cause a game crash"
    FORBID_DISJOINTED_PIECES = True  # An ID must be a simply connected block

    # Source: Map modding.txt line 257
    # "All land provinces must belong to a continent to avoid errors"
    LAND_REQUIRES_CONTINENT = True

    # ───────────── Province types and terrain ─────────────
    # Source: Map modding.txt line 224
    # "For lake provinces, terrain must be 'lakes' while for sea provinces it must be 'ocean'"
    REQUIRED_TERRAIN_BY_TYPE = {
        "lake": "lakes",
        "sea":  "ocean",
    }

    # Source: Map modding.txt line 225
    # After 1.11+, the coastal field is based on the bitmap adjacency, and the coastal field of definition.csv is ignored.
    COASTAL_DETERMINED_BY_BITMAP = True

    # ───────────── River Rules ─────────────
    # Source: Map modding.txt line 394
    # "Rivers must be exactly one pixel thick and only go in orthogonal directions"
    RIVER_PIXEL_WIDTH = 1
    RIVER_DIAGONAL_FORBIDDEN = True

    # Source: Map modding.txt line 396
    # "each river must have exactly one... green start marker"
    RIVER_REQUIRES_ONE_GREEN_SOURCE = True

    # Source: Map modding.txt line 412
    RIVER_INDEX_SMALL_MAX = 6   # Index 0-6 is the river
    RIVER_INDEX_LARGE_MAX = 11  # Index 7-11 is a big river

    # ───────────── Coding ─────────────
    LOCALIZATION_ENCODING = "utf-8-sig"  # UTF-8 with BOM

    # ═══════════════ Check function ═══════════════

    @classmethod
    def check_map_dimensions(cls, w: int, h: int) -> list[str]:
        """Check that the map dimensions comply with HOI4 constraints. Returns a list of errors (empty = legal)."""
        errors = []
        if w % cls.MAP_DIM_MULTIPLE != 0:
            errors.append(f"Map width {w} is not a multiple of {cls.MAP_DIM_MULTIPLE}")
        if h % cls.MAP_DIM_MULTIPLE != 0:
            errors.append(f"Map height {h} is not a multiple of {cls.MAP_DIM_MULTIPLE}")
        if w * h > cls.MAP_MAX_TOTAL_PIXELS:
            errors.append(
                f"Total map pixels {w*h} exceed HOI4's limit of {cls.MAP_MAX_TOTAL_PIXELS}"
            )
        return errors

    @classmethod
    def violates_too_large_box(cls, bbox_w: int, bbox_h: int,
                                map_w: int = MAP_WIDTH,
                                map_h: int = MAP_HEIGHT) -> bool:
        """Return whether a province reaches the engine's one-eighth limit.

        Although the documentation says ``more than`` one eighth, the game
        rejects the exact boundary for some map sizes (notably 256 pixels on
        a 2048-pixel map).  Use the largest integer box that stays strictly
        below one eighth so validators and exports agree with the loader.
        """
        max_w = max(1, (int(map_w) - 1) // 8)
        max_h = max(1, (int(map_h) - 1) // 8)
        return bbox_w > max_w or bbox_h > max_h

    @classmethod
    def province_count_warning(cls, count: int) -> str:
        """Returns the warning string corresponding to the total number of provinces, and returns empty if there is no problem."""
        if count > cls.PROVINCE_HARD_MAX:
            return f"Danger: {count} > {cls.PROVINCE_HARD_MAX}, exceeding HOI4's hard limit and guaranteed to crash"
        if count > cls.PROVINCE_SOFT_MAX:
            return f"Warning: {count} > {cls.PROVINCE_SOFT_MAX}, the limit recommended by HOI4 documentation"
        if count > cls.PROVINCE_RECOMMENDED:
            return f"Note: {count} is close to the recommended vanilla range of {cls.PROVINCE_RECOMMENDED}–{cls.PROVINCE_SOFT_MAX}"
        return ""
