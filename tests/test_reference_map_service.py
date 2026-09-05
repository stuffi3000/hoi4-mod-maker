"""Reference-image generation and random-split regression tests."""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from commands.history import CommandHistory
from commands.map.apply_reference import ApplyReferenceLayersCommand
from commands.province.random_split import RandomSplitProvincesCommand
from data.constants import TILE_LAKE, TILE_LAND, TILE_SEA
from domain.managers.river import RIVER_SOURCE
from domain.managers.river import validate_rivers
from model.project import Project
from services.reference_map_service import (
    extract_reference_colors,
    generate_hydrology_from_rgb,
    generate_land_water_from_rgb,
    generate_provinces_from_rgb,
    suggest_reference_color_mapping,
    split_selected_provinces_randomly,
)


def test_land_water_and_outline_import() -> None:
    rgb = np.full((20, 30, 3), 255, dtype=np.uint8)
    rgb[2:18, 4:26] = (221, 136, 57)
    rgb[2:18, 15] = (140, 95, 40)

    tiles = generate_land_water_from_rgb(rgb)
    provinces, count = generate_provinces_from_rgb(
        rgb, tiles, min_region_pixels=4
    )

    assert np.all(tiles[:, :4] == TILE_SEA)
    assert np.all(tiles[3:17, 5:25] == TILE_LAND)
    assert count == 2
    assert set(np.unique(provinces)) == {0, 1, 2}
    assert np.all(provinces[tiles == TILE_SEA] == 0)
    assert np.all(provinces[tiles == TILE_LAND] > 0)


def test_explicit_color_roles_drive_land_water_and_provinces() -> None:
    rgb = np.full((24, 32, 3), (255, 255, 255), dtype=np.uint8)
    rgb[2:22, 3:29] = (220, 140, 55)
    rgb[2:22, 16] = (20, 20, 20)

    tiles = generate_land_water_from_rgb(
        rgb,
        land_colors=[(220, 140, 55)],
        water_colors=[(255, 255, 255)],
    )
    assert int(np.sum(tiles == TILE_LAND)) == 20 * 26

    provinces, count = generate_provinces_from_rgb(
        rgb,
        tiles,
        land_province_colors=[(20, 20, 20)],
        sea_province_colors=[],
        min_region_pixels=4,
    )
    assert count == 2
    assert set(np.unique(provinces[tiles == TILE_LAND])) == {1, 2}


def test_palette_preserves_rare_flat_map_colors_and_suggests_roles() -> None:
    rgb = np.full((30, 40, 3), (221, 136, 57), dtype=np.uint8)
    rgb[:, :4] = (255, 255, 255)
    rgb[:, 20] = (185, 121, 50)
    palette = extract_reference_colors(rgb, max_colors=8)
    colors = {entry.rgb for entry in palette}
    assert (185, 121, 50) in colors
    mapping = suggest_reference_color_mapping(rgb, "province", max_colors=8)
    assert (185, 121, 50) in mapping["land_province"]


def test_explicit_hydrology_roles_are_respected() -> None:
    rgb = np.full((48, 64, 3), (207, 213, 16), dtype=np.uint8)
    rgb[:, :5] = 255
    rgb[8:20, 15:29] = (190, 178, 151)
    rgb[32, 20:55] = (164, 113, 88)
    tiles = np.full((48, 64), TILE_LAND, dtype=np.uint8)
    tiles[:, :5] = TILE_SEA

    new_tiles, rivers, stats = generate_hydrology_from_rgb(
        rgb,
        tiles,
        lake_colors=[(190, 178, 151)],
        river_colors=[(164, 113, 88)],
        min_feature_pixels=4,
    )
    assert stats["lake_pixels"] > 100
    assert stats["river_pixels"] >= 20
    assert np.all(new_tiles[10:18, 17:27] == TILE_LAKE)
    assert np.any(rivers == RIVER_SOURCE)


def test_hydrology_separates_broad_lakes_and_thin_rivers() -> None:
    rgb = np.full((48, 64, 3), (207, 213, 16), dtype=np.uint8)
    rgb[:, :5] = 255
    rgb[8:20, 15:29] = (150, 142, 122)  # broad inland-water body
    rgb[32, 20:55] = (150, 142, 122)    # thin river
    tiles = np.full((48, 64), TILE_LAND, dtype=np.uint8)
    tiles[:, :5] = TILE_SEA

    new_tiles, rivers, stats = generate_hydrology_from_rgb(
        rgb, tiles, lake_radius=3.0
    )

    assert stats["lake_pixels"] > 100
    assert stats["river_pixels"] >= 30
    assert np.all(new_tiles[10:18, 17:27] == TILE_LAKE)
    assert np.any(rivers == RIVER_SOURCE)
    assert int(np.sum(rivers == RIVER_SOURCE)) == stats["river_networks"]
    assert "passed" in validate_rivers(rivers, lang="en")[0]


def test_random_split_total_count_and_connectivity() -> None:
    province_map = np.zeros((24, 40), dtype=np.int32)
    province_map[2:22, 2:18] = 1
    province_map[2:22, 22:38] = 2

    result, parents = split_selected_provinces_randomly(
        province_map, {1, 2}, 6, seed=123
    )

    output_ids = set(np.unique(result)) - {0}
    assert len(output_ids) == 6
    assert len(parents) == 4
    for pid in output_ids:
        _, components = ndimage.label(result == pid)
        assert components == 1


def test_reference_layer_command_undo_and_redo() -> None:
    project = Project()
    project.map_data.tile_map = np.full((4, 5), TILE_SEA, dtype=np.uint8)
    replacement = np.full((4, 5), TILE_LAND, dtype=np.uint8)
    history = CommandHistory()
    history.execute(ApplyReferenceLayersCommand(
        project.map_data, {"tile_map": replacement}, "reference import"
    ))
    assert np.all(project.map_data.tile_map == TILE_LAND)
    assert history.undo()
    assert np.all(project.map_data.tile_map == TILE_SEA)
    assert history.redo()
    assert np.all(project.map_data.tile_map == TILE_LAND)


def test_province_reference_command_undoes_tile_snapshot() -> None:
    project = Project()
    project.map_data.tile_map = np.full((3, 4), TILE_LAND, dtype=np.uint8)
    project.map_data.province_map = np.zeros((3, 4), dtype=np.int32)
    project.map_data.tile_snapshot = None
    replacement = np.ones((3, 4), dtype=np.int32)
    history = CommandHistory()
    history.execute(ApplyReferenceLayersCommand(
        project.map_data, {"province_map": replacement}, "province reference"
    ))
    assert np.array_equal(project.map_data.tile_snapshot, project.map_data.tile_map)
    assert history.undo()
    assert project.map_data.tile_snapshot is None


def test_random_split_command_inherits_and_restores_metadata() -> None:
    project = Project()
    original = np.ones((12, 12), dtype=np.int32)
    project.map_data.province_map = original.copy()
    state = project.state_mgr.create_state([1])
    region = project.strategic_region_mgr.create_region("test")
    project.strategic_region_mgr.assign_province(1, region.id)
    project.map_data.provincial_terrain[1] = "forest"

    new_map, parents = split_selected_provinces_randomly(
        original, {1}, 4, seed=7
    )
    history = CommandHistory()
    history.execute(RandomSplitProvincesCommand(project, new_map, parents))

    new_ids = set(parents)
    assert new_ids.issubset(set(project.state_mgr.get_state(state.id).provinces))
    assert new_ids.issubset(set(project.strategic_region_mgr.get(region.id).province_ids))
    assert all(project.map_data.provincial_terrain[pid] == "forest" for pid in new_ids)

    assert history.undo()
    assert np.array_equal(project.map_data.province_map, original)
    assert project.state_mgr.get_state(state.id).provinces == [1]
    assert project.strategic_region_mgr.get(region.id).province_ids == [1]
