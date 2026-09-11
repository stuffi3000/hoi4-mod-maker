"""Preview rendering CLI — Use game textures to synthesize preview PNGs without opening the GUI.

Usage:
    py tools/render_preview.py <project.hoi4proj> [output.png] # Rendering project
    py tools/render_preview.py <project.hoi4proj> [output.png] --enrich # Demonstration: automatic terrain refinement
    py tools/render_preview.py vanilla [output.png] # Render the original game map

--enrich only refines the terrain in memory, with zero changes to the project file - for demonstration purposes.

M1 Acceptance Tool: View the synthesis effect directly, and also be used to troubleshoot preview problems in the future.
The vanilla mode is a controlled experiment: how the game draws vs how we draw the same data,
The gap is the gap in the synthetic formula and has nothing to do with the quality of the project data."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from data.constants import set_map_size, TILE_LAND, TILE_SEA
from domain.project_io import load_project
from domain.managers.state import StateManager
from domain.managers.country import CountryManager
from domain.preview.compositor import compose_preview
from services.game_assets import GameAssets


def _load_project_layers(proj_path: str, enrich: bool = False,
                         realheight: bool = False):
    tile_map, _pm, terrain_map, height_map, river_map, _pt, _snap = load_project(
        proj_path, StateManager(), CountryManager())
    if realheight:
        # Demonstration mode: Regenerate realistic height map in memory, do not write back to the project
        from domain.generators.heightmap import generate_realistic_heightmap
        height_map = generate_realistic_heightmap(tile_map)
    if enrich:
        # Demo mode: Automatically refine the terrain in memory, without writing back to the project
        from domain.generators.terrain_detail import generate_detailed_terrain
        terrain_map = generate_detailed_terrain(tile_map, height_map)
    # Self-made maps do not have hand-drawn tone maps → automatically generate climate tones by latitude/altitude
    from domain.preview.climate_tint import generate_climate_tint
    tint = generate_climate_tint(tile_map, height_map)
    return tile_map, terrain_map, height_map, river_map, tint


def _load_vanilla_layers(assets: GameAssets):
    """Read the three BMP + matching tone maps under the original game map/."""
    g = assets.install_dir
    terrain_map = np.asarray(Image.open(os.path.join(g, "map/terrain.bmp")))
    height_map = np.asarray(Image.open(os.path.join(g, "map/heightmap.bmp")))
    river_map = np.asarray(Image.open(os.path.join(g, "map/rivers.bmp")))

    water_idx = assets.water_palette_indices() or set()
    is_water = np.isin(terrain_map, list(water_idx))
    tile_map = np.where(is_water, TILE_SEA, TILE_LAND).astype(np.uint8)

    # Tone map is map half resolution, aligned at 2x magnification
    tint = assets.colormap_rgb()
    if tint is not None:
        fy = terrain_map.shape[0] // tint.shape[0]
        fx = terrain_map.shape[1] // tint.shape[1]
        if fy >= 1 and fx >= 1:
            tint = np.repeat(np.repeat(tint, fy, axis=0), fx, axis=1)
            tint = tint[:terrain_map.shape[0], :terrain_map.shape[1]]
        else:
            tint = None
    return tile_map, terrain_map, height_map, river_map, tint


def main() -> int:
    args = [a for a in sys.argv[1:] if a not in ("--enrich", "--realheight")]
    enrich = "--enrich" in sys.argv
    realheight = "--realheight" in sys.argv
    if not args:
        print(__doc__)
        return 2
    source = args[0]
    default_out = "preview_vanilla.png" if source == "vanilla" else "preview.png"
    out_path = args[1] if len(args) > 1 else default_out

    assets = GameAssets()
    if not assets.available():
        print("HOI4 installation directory was not found")
        return 1
    tiles = assets.atlas_tiles()
    mapping = assets.terrain_to_texture()
    if tiles is None or mapping is None:
        print(f"Failed to read game assets: {assets.last_error}")
        return 1

    t0 = time.perf_counter()
    if source == "vanilla":
        tile_map, terrain_map, height_map, river_map, tint = \
            _load_vanilla_layers(assets)
    else:
        tile_map, terrain_map, height_map, river_map, tint = \
            _load_project_layers(source, enrich=enrich, realheight=realheight)
    set_map_size(tile_map.shape[1], tile_map.shape[0])
    t1 = time.perf_counter()

    img = compose_preview(tile_map, terrain_map, height_map, river_map,
                          tiles, mapping, tint=tint)
    t2 = time.perf_counter()

    Image.fromarray(img).save(out_path)
    print(f"Load {t1 - t0:.1f}s | Compose {t2 - t1:.1f}s | "
          f"{img.shape[1]}x{img.shape[0]} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
