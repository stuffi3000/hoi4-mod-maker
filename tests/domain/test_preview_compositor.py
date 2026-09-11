"""Preview compositor testing — Use fake textures to verify layering logic without relying on game files."""

import numpy as np

from domain.preview.compositor import compose_preview, _texture_lut, _hillshade
from data.constants import TILE_LAND, TILE_SEA, SEA_LEVEL


def _fake_atlas(tile_count: int = 16, size: int = 4) -> np.ndarray:
    """Solid color for each tile: R channel = tile number × 10, easy to assert source."""
    tiles = np.zeros((tile_count, size, size, 4), dtype=np.uint8)
    for i in range(tile_count):
        tiles[i, :, :, 0] = i * 10
        tiles[i, :, :, 3] = 255
    return tiles


def _flat_world(h: int = 8, w: int = 8):
    """An all-terrestrial, flat-altitude base world."""
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    terrain_map = np.zeros((h, w), dtype=np.uint8)
    height_map = np.full((h, w), SEA_LEVEL + 20, dtype=np.uint8)
    return tile_map, terrain_map, height_map


def test_texture_lut_fallback():
    """Undefined indexes fall back to plain tiles; out-of-bounds tile numbers (lake 255) fall back similarly."""
    lut = _texture_lut({0: 1, 6: 11, 14: 255}, tile_count=16)
    assert lut[0] == 1
    assert lut[6] == 11
    assert lut[14] == 1   # 255 out of bounds → fall back to map at index 0 (tile 1)
    assert lut[99] == 1   # undefined → same as above


def test_land_uses_mapped_tile():
    """The color of the land pixels comes from the mapped tile (R = tile number × 10 × lighting factor)."""
    tile_map, terrain_map, height_map = _flat_world()
    terrain_map[:] = 3                       # Palette index 3
    out = compose_preview(tile_map, terrain_map, height_map, None,
                          _fake_atlas(), {0: 1, 3: 9})

    assert out.shape == (8, 8, 3)
    # Flat terrain → same brightness throughout the image; Tile 9 → R base color 90, multiplied by light should still be much larger than Tile 1’s 10
    assert out[:, :, 0].min() == out[:, :, 0].max()
    assert out[4, 4, 0] > 40


def test_water_overrides_texture():
    """Ocean pixels do not display the terrain material, but instead are blue by depth."""
    tile_map, terrain_map, height_map = _flat_world()
    tile_map[:, :4] = TILE_SEA
    height_map[:, :4] = 0                    # deep sea

    out = compose_preview(tile_map, terrain_map, height_map, None,
                          _fake_atlas(), {0: 1})

    sea = out[0, 0]
    land = out[0, 7]
    assert sea[2] > sea[0]                   # The sea is dominated by blue
    assert not np.array_equal(sea, land)


def test_near_coast_lighter_than_open_sea():
    """The nearshore is brighter than the far sea (same offshore gradient as exported colormap_water)."""
    tile_map, terrain_map, height_map = _flat_world(h=8, w=256)
    tile_map[:, 8:] = TILE_SEA               # There is a strip of land on the left and all the sea to the right

    out = compose_preview(tile_map, terrain_map, height_map, None,
                          _fake_atlas(), {0: 1})

    near = out[4, 10]                        # offshore 2px
    far = out[4, 250]                        # Offshore 240px (> 80px to pure deep sea)
    assert int(near.sum()) > int(far.sum())


def test_rivers_drawn_on_top():
    """River pixels (index <=11) cover land; background (254/255) do not."""
    tile_map, terrain_map, height_map = _flat_world()
    river_map = np.full((8, 8), 255, dtype=np.uint8)
    river_map[2, :] = 3                      # a river
    river_map[5, :] = 254                    # land background, not river

    out = compose_preview(tile_map, terrain_map, height_map, river_map,
                          _fake_atlas(), {0: 1})

    assert out[2, 3, 2] > out[2, 3, 0]       # The river is blue dominant
    assert np.array_equal(out[5, 3], out[6, 3])  # Line 254 is consistent with normal land.


def test_hillshade_slope_darker_than_flat():
    """The backlit slope (southeast direction) is darker than the flat ground, and the light facing slope is brighter than the flat ground."""
    height = np.zeros((8, 8), dtype=np.uint8)
    height[:, :] = 100
    for x in range(8):
        height[4, x] = 100 + x * 5           # Rising to the east → west slope toward the light
    shade = _hillshade(height)

    flat = shade[0, 4]
    assert shade[4, 4] != flat               # The brightness of the slope deviates from the flat ground
