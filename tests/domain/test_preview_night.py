"""Night scene layer test - darkening + urban city lights"""
import numpy as np

from domain.preview.night import apply_night_layer


def _day_image(h=16, w=16, value=160):
    return np.full((h, w, 3), value, dtype=np.uint8)


def test_night_darkens_everything():
    rgb = _day_image()
    out = apply_night_layer(rgb, np.zeros((16, 16), dtype=np.uint8))
    assert out.shape == rgb.shape
    assert int(out.max()) < 160          # The whole picture is darker than during the day


def test_urban_pixels_lit():
    rgb = _day_image()
    terrain = np.zeros((16, 16), dtype=np.uint8)
    terrain[6:10, 6:10] = 13             # urban (forest_13)
    out = apply_night_layer(rgb, terrain)
    city = out[8, 8].astype(int)
    dark = out[0, 0].astype(int)
    assert city.sum() > dark.sum() + 100  # The city is far brighter than the night
    assert city[0] > city[2]              # The light is warm (R > B)


def test_none_terrain_only_darkens():
    rgb = _day_image()
    out = apply_night_layer(rgb, None)
    assert int(out.max()) < 160
