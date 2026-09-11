"""Render 5.hoi4proj’s current terrain + height + sea and land, and draw a PNG with a coordinate grid.
After users read it, they can tell me which pixel range each country is in.

Output: Desktop/5_preview_grid.png"""
from __future__ import annotations

import os
import sys
from io import BytesIO
from zipfile import ZipFile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HOME = os.path.expanduser("~")
PROJECT_PATH = os.path.join(HOME, "Desktop", "Aurora", "5.hoi4proj")
OUT_PATH = os.path.join(HOME, "Desktop", "5_preview_grid.png")

GRID_STEP = 500  # Draw a grid every 500 pixels


def main() -> None:
    with ZipFile(PROJECT_PATH, "r") as zf:
        tile = np.load(BytesIO(zf.read("tile_map.npy")))
        hm = np.load(BytesIO(zf.read("height_map.npy")))
        terrain = np.load(BytesIO(zf.read("terrain_map.npy")))
    h, w = tile.shape
    print(f"Source: {w}x{h}")

    # ——Synthetic RGB image——
    # Land = colored by height grayscale + terrain type
    rgb = np.zeros((h, w, 3), dtype=np.uint8)

    # Ocean = deep blue
    sea_mask = tile == 2
    rgb[sea_mask] = [40, 70, 140]
    # lake = light blue
    lake_mask = tile == 3
    rgb[lake_mask] = [100, 140, 200]
    # Land = by height + terrain color
    land_mask = tile == 1

    # plain: green
    # Hills: yellow-green
    # Mountain: Brown
    # Snow Mountain: White
    plains_mask = land_mask & (hm < 130)
    hills_mask = land_mask & (hm >= 130) & (hm < 165)
    mountain_mask = land_mask & (hm >= 165) & (hm < 210)
    snow_mask = land_mask & (hm >= 210)

    rgb[plains_mask] = [90, 170, 80]
    rgb[hills_mask] = [180, 170, 70]
    rgb[mountain_mask] = [130, 110, 90]
    rgb[snow_mask] = [230, 230, 240]

    # Shrink to 1/4 (5632x2048 → 1408x512) for easy viewing
    scale = 4
    img = Image.fromarray(rgb).resize((w // scale, h // scale), Image.LANCZOS)
    draw = ImageDraw.Draw(img)

    # Draw coordinate grid
    nw, nh = img.size
    for x in range(0, w, GRID_STEP):
        xi = x // scale
        draw.line([(xi, 0), (xi, nh)], fill=(255, 0, 0, 128), width=1)
        draw.text((xi + 2, 2), f"{x}", fill=(255, 255, 0))
    for y in range(0, h, GRID_STEP):
        yi = y // scale
        draw.line([(0, yi), (nw, yi)], fill=(255, 0, 0, 128), width=1)
        draw.text((2, yi + 2), f"{y}", fill=(255, 255, 0))

    img.save(OUT_PATH, "PNG")
    print(f"Saved: {OUT_PATH}")
    print(f"Preview size: {nw}x{nh} (scale=1/{scale})")


if __name__ == "__main__":
    main()
