"""trees.bmp palette — 256-color BGRA palette extracted from vanilla.

The first 16 colors are meaningful:
  0 = no tree (black)
  1 = not used (red)
  2-4 = tropical trees (shallow forest / medium / dense)
  5-7 = temperate trees (sparse / medium / dense)
  8-10 = palm tree (sparse / medium / dense)
  11-15 = Other (Jungle, etc.)

`tree = { 3 4 7 10 }` of default.map defines which indexes are counted as "treed" by HOI4."""

# (R, G, B) — extracted from vanilla trees.bmp
TREES_PALETTE_RGB: list[tuple[int, int, int]] = [
    (  0,   0,   0),  # 0: no tree
    (255,   0,   0),  #  1: unused
    ( 30, 139, 109),  #  2: tropical sparse
    ( 18, 100,  78),  #  3: tropical medium  ← tree
    (  8,  58,  44),  #  4: tropical dense   ← tree
    ( 76, 156,  51),  #  5: temperate sparse
    ( 47, 120,  24),  #  6: temperate medium
    ( 20,  85,   0),  #  7: temperate dense  ← tree
    (154, 156,  51),  #  8: palm sparse
    (118, 120,  24),  #  9: palm medium
    ( 83,  85,   0),  # 10: palm dense       ← tree
    (255, 255,   0),  # 11: misc yellow
    (213, 160,   0),  # 12: misc gold
    (  0, 183,   0),  # 13: jungle sparse
    (  0, 128,   0),  # 14: jungle medium
    (  0,  60,   0),  # 15: jungle dense
]

# Completed to 256 colors (all black)
while len(TREES_PALETTE_RGB) < 256:
    TREES_PALETTE_RGB.append((0, 0, 0))

# BMP palette is in BGRA format
TREES_PALETTE_BGRA: list[bytes] = []
for r, g, b in TREES_PALETTE_RGB:
    TREES_PALETTE_BGRA.append(bytes([b, g, r, 0]))

TREES_PALETTE_BYTES = b"".join(TREES_PALETTE_BGRA)  # 1024 bytes


# Terrain type → trees.bmp index mapping (for automatic generation)
# Reference Map modding.txt §Trees (lines 419-470)
#
# ⚠️ vanilla trees.bmp actually only uses [0, 2, 3, 5, 6, 11, 28, 29]
# Illegal index (7, 14, etc.) The HOI4 engine cannot find the tree type and may crash.
# This mapping strictly uses vanilla legal indexes
TERRAIN_TO_TREE_INDEX: dict[str, int] = {
    "forest":   6,   # temperate medium (originally 7, not used in vanilla)
    "hills":    5,   # temperate sparse
    "jungle":  11,   # jungle impassable (originally 14, not used in vanilla)
    "marsh":    6,   # temperate medium
    "mountain": 0,   # no tree
    "plains":   0,   # No trees (no trees in plains by default)
    "desert":   0,
    "urban":    0,
    "ocean":    0,
    "lakes":    0,
}
