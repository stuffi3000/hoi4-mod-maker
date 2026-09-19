"""common/defines/01_mod_defines.lua writer.

Full conversion mods must cover some NDefines, otherwise the AI crashes on divide-by-zero on non-standard maps.
Main questions:
- The Air Force AI uses (number of pixels * coefficient) as a divisor, and the strategic area is divided by zero if it is too small
- Naval AI attempts to land/patrol areas that don't exist
- Supply system references mismatched province numbers

Strategy: Conservative coverage, only changing the parameters that will crash, not changing the game balance."""

from __future__ import annotations

import os


LEGACY_MAX_PROVINCES_FLOOR = 25000


def resolve_max_provinces(province_count: int, min_provinces=None) -> int:
    """Resolve NDefines MAX_PROVINCES without unconditional flooring (M9.2)."""
    count = int(province_count or 0)
    if min_provinces is None:
        return count + 100
    return max(count + 100, int(min_provinces))


def write_defines_lua(output_dir: str, province_count: int = 0, min_provinces: int = LEGACY_MAX_PROVINCES_FLOOR) -> None:
    """Generate common/defines/01_mod_defines.lua."""
    d = os.path.join(output_dir, "common", "defines")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "01_mod_defines.lua")

    with open(path, "w", encoding="utf-8") as f:
        f.write(_generate_defines(province_count, min_provinces=min_provinces))


def _generate_defines(province_count: int, min_provinces: int = LEGACY_MAX_PROVINCES_FLOOR) -> str:
    return f"""\
NDefines.NGame.MAX_PROVINCES = {resolve_max_provinces(province_count, min_provinces)}
NDefines.NAir.AIR_REGION_SUPERIORITY_PIXEL_SCALE = 0.01
NDefines.NSupply.RAILWAY_BASE_FLOW = 10.0
"""
