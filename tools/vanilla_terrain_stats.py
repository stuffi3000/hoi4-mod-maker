"""Original terrain statistics extraction - quantifying the craftsmanship of P Society's art into parameters.

Extracted from terrain.bmp + heightmap.bmp of the game body:
1. The proportion of each type of graphic terrain (within the land)
2. Variant mixing ratio within each terrain family (forest A:B, desert A:B:C...)
3. Altitude distribution of each terrain (P25/P50/P75, relative to sea level)
4. Plaque granularity (border density: the higher the proportion of border pixels = the more fragmented the plaque)

The output numbers are used directly as target parameters for the "Conformal Landscape" generator —
The criterion for "well generated" = whether it is statistically close to the original version.

Usage: py tools/vanilla_terrain_stats.py"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from services.game_assets import find_hoi4_install, parse_water_palette_indices, TERRAIN_DEF_RELPATH
from data.terrain_types import GRAPHICAL_TERRAIN_BY_INDEX

SEA_LEVEL = 95  # Original sea level grayscale


def main() -> int:
    game = find_hoi4_install()
    if game is None:
        print("HOI4 installation directory was not found")
        return 1

    terrain = np.asarray(Image.open(os.path.join(game, "map/terrain.bmp")))
    height = np.asarray(Image.open(os.path.join(game, "map/heightmap.bmp")))
    with open(os.path.join(game, TERRAIN_DEF_RELPATH), encoding="utf-8-sig",
              errors="replace") as f:
        water_idx = parse_water_palette_indices(f.read())

    land = ~np.isin(terrain, list(water_idx))
    land_total = int(land.sum())
    print(f"Map {terrain.shape[1]}x{terrain.shape[0]}, land pixels {land_total:,}\n")

    # ── 1+2. Proportion & proportion of variants within the family ──
    counts = np.bincount(terrain[land].ravel(), minlength=256)
    family_members: dict[str, list[tuple[int, int]]] = defaultdict(list)
    print("── Graphical terrain share (land only) ──")
    for idx in np.nonzero(counts)[0]:
        n = int(counts[idx])
        gt = GRAPHICAL_TERRAIN_BY_INDEX.get(int(idx))
        name = f"{gt.id}({gt.type})" if gt else f"unregistered index {idx}"
        fam = gt.type if gt else f"idx{idx}"
        family_members[fam].append((int(idx), n))
        print(f"  idx {idx:>3} {name:<38} {n / land_total * 100:6.2f}%")

    print("\n── Variant mix within each terrain family ──")
    for fam, members in sorted(family_members.items()):
        if len(members) < 2:
            continue
        total = sum(n for _, n in members)
        ratio = " : ".join(
            f"idx{idx}={n / total * 100:.0f}%" for idx, n in
            sorted(members, key=lambda t: -t[1]))
        print(f"  {fam:<10} {ratio}")

    # ── 3. Altitude distribution of each terrain ──
    print("\n── Elevation distribution (relative to sea level, P25/P50/P75) ──")
    hf = height.astype(np.int32) - SEA_LEVEL
    for fam, members in sorted(family_members.items()):
        fam_mask = np.isin(terrain, [i for i, _ in members]) & land
        vals = hf[fam_mask]
        if vals.size < 1000:
            continue
        p25, p50, p75 = np.percentile(vals, [25, 50, 75])
        print(f"  {fam:<10} P25={p25:5.0f}  P50={p50:5.0f}  P75={p75:5.0f}")

    # ── 4. Patch granularity (boundary density) ──
    diff_h = (terrain[:, 1:] != terrain[:, :-1]) & land[:, 1:] & land[:, :-1]
    diff_v = (terrain[1:, :] != terrain[:-1, :]) & land[1:, :] & land[:-1, :]
    boundary_ratio = (int(diff_h.sum()) + int(diff_v.sum())) / max(land_total, 1)
    print("\n── Terrain patch granularity ──")
    print(f"  Terrain boundary density (boundary pixels/land pixels): {boundary_ratio:.3f}")
    print("  Higher values indicate smaller patches; generated maps should approach this value.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
