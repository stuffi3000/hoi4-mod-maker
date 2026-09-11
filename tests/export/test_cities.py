"""Regression tests for exported cosmetic city models."""

from __future__ import annotations

import struct

import numpy as np

from export.writers.map.buildings import write_empty_unitstacks
from export.writers.map.cities_bmp import write_cities_bmp


def test_cities_bmp_marks_urban_pixels_with_a_vanilla_header(tmp_path):
    terrain_map = np.array(
        [[13, 0, 13, 14], [0, 13, 0, 0]],
        dtype=np.uint8,
    )

    write_cities_bmp(str(tmp_path), terrain_map=terrain_map)
    raw = (tmp_path / "map" / "cities.bmp").read_bytes()

    assert raw[:2] == b"BM"
    assert struct.unpack_from("<I", raw, 10)[0] == 1074
    assert struct.unpack_from("<H", raw, 28)[0] == 8
    assert struct.unpack_from("<I", raw, 46)[0] == 255
    assert struct.unpack_from("<I", raw, 50)[0] == 255

    # BMP rows are stored bottom-up. Urban terrain becomes Western city group
    # 15; all other terrain remains the no-city index 0.
    assert list(raw[1074:]) == [0, 15, 0, 0, 15, 0, 15, 0]


def test_city_metadata_contains_mesh_groups(tmp_path):
    write_empty_unitstacks(str(tmp_path))

    cities = (tmp_path / "map" / "cities.txt").read_text(encoding="utf-8")
    assert cities.count("city_group = {") == 4
    assert '"westerngfx_house_1_1"' in cities
    assert '"french_city_4_01_entity"' in cities
    assert '"unciv_city_04_entity"' in cities
    assert (tmp_path / "map" / "unitstacks.txt").read_text() == ""
