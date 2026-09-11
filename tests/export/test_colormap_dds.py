"""colormap_dds unit test — fow map channel semantics + city lights alpha"""
import os
import struct

import numpy as np

from data.constants import TILE_LAND, TILE_SEA
from export.writers.map.colormap_dds import write_colormap_dds, write_fow_dds


def _read_dds(path):
    """Read uncompressed BGRA8 DDS → (H, W, 4) ndarray"""
    with open(path, "rb") as f:
        header = f.read(128)
        assert header[:4] == b"DDS "
        h = struct.unpack_from("<I", header, 12)[0]
        w = struct.unpack_from("<I", header, 16)[0]
        data = np.frombuffer(f.read(), dtype=np.uint8)
    return data.reshape(h, w, 4)


def _half_land_map(size=64):
    """tile_map of left half sea and right half land"""
    m = np.full((size, size), TILE_SEA, dtype=np.uint8)
    m[:, size // 2:] = TILE_LAND
    return m


def test_fow_dds_channels(tmp_path):
    tile_map = _half_land_map()
    write_fow_dds(tile_map, str(tmp_path))
    px = _read_dds(os.path.join(tmp_path, "map", "terrain", "fow_rgb_waterspec_a.dds"))
    assert px.shape == (32, 32, 4)  # half of provinces
    sea_px = px[16, 2]      # deep sea
    land_px = px[16, 29]    # deep continent
    # RGB Grayscale: Lu Liang Hai Dark
    assert land_px[0] == land_px[1] == land_px[2]
    assert land_px[0] > sea_px[0]
    # alpha water reflection: sea > land
    assert sea_px[3] > land_px[3]


def test_fow_dds_height_brightens_land(tmp_path):
    tile_map = np.full((64, 64), TILE_LAND, dtype=np.uint8)
    height = np.full((64, 64), 100, dtype=np.uint8)
    height[:, 32:] = 220  # Right half of the mountain
    write_fow_dds(tile_map, str(tmp_path), height_map=height)
    px = _read_dds(os.path.join(tmp_path, "map", "terrain", "fow_rgb_waterspec_a.dds"))
    assert px[16, 29, 0] > px[16, 2, 0]  # Highlands are brighter


def test_colormap_city_lights_alpha(tmp_path):
    tile_map = _half_land_map()
    terrain = np.zeros((64, 64), dtype=np.uint8)
    terrain[28:36, 44:52] = 13  # An urban area on land (forest_13)
    write_colormap_dds(tile_map, str(tmp_path), terrain_map=terrain)
    px = _read_dds(
        os.path.join(tmp_path, "map", "terrain", "colormap_rgb_cityemissivemask_a.dds")
    )
    assert px[16, 24, 3] > 100   # urban center bright
    assert px[16, 2, 3] == 0     # No lights on the sea
    assert px[2, 30, 3] == 0     # There is no light on the land far away from the city


def test_colormap_no_urban_alpha_zero(tmp_path):
    tile_map = _half_land_map()
    terrain = np.zeros((64, 64), dtype=np.uint8)  # all plains
    write_colormap_dds(tile_map, str(tmp_path), terrain_map=terrain)
    px = _read_dds(
        os.path.join(tmp_path, "map", "terrain", "colormap_rgb_cityemissivemask_a.dds")
    )
    assert int(px[..., 3].max()) == 0
