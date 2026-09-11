"""game_assets test - map parsing / atlas slicing / missing degradation.

Real game files are not included in CI: Integration tests are only run if there is a HOI4 installation on the machine."""

import json
import os

import numpy as np
import pytest

import services.game_assets as ga
from services.game_assets import (
    GameAssets, parse_terrain_to_texture, parse_graphical_terrain,
    parse_water_palette_indices, slice_atlas,
    TERRAIN_DEF_RELPATH, ATLAS_GRID,
)
from data.constants import DEFAULT_HOI4_PATH


# ═══════ Mapping table analysis ═══════

SAMPLE = """
categories =  {
    unknown = {
        color = { 255 0 0 }
    }
    forest = {
        color = { 89 199 85 }
        movement_cost = 1.5
        buildings_max_level = {
            bunker = 4
        }
        units = {
            attack = -0.15
        }
    }
}

terrain = {
    terrain_0   = { type = plains  color = { 	0	 } texture = 1 }
    desert      = { type = desert  color = { 3 } texture = 9 }
    multi       = { type = plains  color = { 20 21 } texture = 7 }  # multiple indices
    lake_14     = { type = lakes   color = { 14 } texture = 255 }
    ocean_15    = { type = ocean   color = { 15 } texture = 9 }
    city        = { type = urban   color = { 13 } texture = 10 spawn_city = yes }
}
"""


def test_parse_graphical_terrain_captures_type():
    """Each graphical terrain entry brings back type, which does not string across entries."""
    entries = parse_graphical_terrain(SAMPLE)
    by_texture = {e["texture"]: e["type"] for e in entries}
    assert by_texture[1] == "plains"
    assert by_texture[10] == "urban"
    assert len(entries) == 6


def test_parse_water_palette_indices():
    """Palette indexes of type ocean/lakes are recognized as water bodies."""
    assert parse_water_palette_indices(SAMPLE) == {14, 15}


def test_parse_graphical_terrain_entries():
    """Graphical terrain entries are parsed, with multiple indexes sharing the same tile number."""
    mapping = parse_terrain_to_texture(SAMPLE)
    assert mapping[0] == 1
    assert mapping[3] == 9
    assert mapping[20] == 7
    assert mapping[21] == 7
    assert mapping[13] == 10
    assert mapping[14] == 255  # The lake remains intact


def test_parse_ignores_categories_block():
    """RGB color (without texture) of the categories block is not mistaken for a palette index."""
    mapping = parse_terrain_to_texture(SAMPLE)
    # unknown's color = {255 0 0} If misparsed, index 255 will appear in the mapping
    assert 255 not in mapping
    assert 89 not in mapping  # The same goes for RGB of the forest category.


# ═══════ Gallery slice ═══════

def test_slice_atlas_row_major_order():
    """The 8×8 atlas is cut into 16 2×2 tiles on a 4×4 grid, arranged row-first."""
    atlas = np.zeros((8, 8, 4), dtype=np.uint8)
    # Each tile is populated with its own row-major number
    for row in range(4):
        for col in range(4):
            atlas[row * 2:(row + 1) * 2, col * 2:(col + 1) * 2] = row * 4 + col

    tiles = slice_atlas(atlas, grid=4)

    assert tiles.shape == (16, 2, 2, 4)
    for i in range(16):
        assert int(tiles[i].min()) == i == int(tiles[i].max())


# ═══════ missing downgrade ═══════

def test_missing_install_dir_degrades_to_none(tmp_path):
    """Directory does not exist: available() False, each getter returns None and logs the reason."""
    assets = GameAssets(install_dir=None)
    # find_hoi4_install may find the real installation on the local machine and force it to point to an empty directory to test for downgrade.
    assets.install_dir = None
    assert not assets.available()
    assert assets.terrain_to_texture() is None
    assert assets.atlas_tiles() is None
    assert assets.last_error != ""


def test_missing_file_degrades_to_none(tmp_path):
    """The directory exists but the file is missing: the getter returns None and records the path."""
    assets = GameAssets(install_dir=str(tmp_path))
    assert assets.terrain_to_texture() is None
    assert TERRAIN_DEF_RELPATH.split("/")[-1] in assets.last_error


# ═══════ Game directory persistence configuration ═══════

def _fake_game_dir(tmp_path):
    game = tmp_path / "game"
    (game / "common" / "terrain").mkdir(parents=True)
    (game / "common" / "terrain" / "00_terrain.txt").write_text(
        "terrain = { t = { type = plains color = { 0 } texture = 1 } }")
    return str(game)


def test_chosen_game_dir_persists_and_wins(tmp_path, monkeypatch):
    """Select the directory to write the configuration (keep the existing keys), and use it first for subsequent searches."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"language": "en"}', encoding="utf-8")
    monkeypatch.setattr(ga, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(ga, "_default_assets", None)
    game_dir = _fake_game_dir(tmp_path)

    assets = ga.set_default_install_dir(game_dir)

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["hoi4_game_dir"] == game_dir
    assert data["language"] == "en"          # Do not lose other settings
    assert ga.find_hoi4_install() == game_dir
    assert assets.install_dir == game_dir


def test_stale_config_game_dir_ignored(tmp_path, monkeypatch):
    """The directory in the configuration is invalid (the game was uninstalled/the drive letter was changed) → Ignore it and use the default search."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"hoi4_game_dir": "Z:/no/such/dir"}', encoding="utf-8")
    monkeypatch.setattr(ga, "CONFIG_PATH", str(cfg))
    assert ga._read_config_game_dir() is None


def test_detect_supported_version(tmp_path, monkeypatch):
    """Parse version from launcher-settings.json → 'primary.secondary.*'; bad data returns None."""
    game = _fake_game_dir(tmp_path)
    (tmp_path / "game" / "launcher-settings.json").write_text(
        '{"rawVersion": "1.19.2.0"}', encoding="utf-8")
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"hoi4_game_dir": "%s"}' % str(game).replace("\\", "\\\\"),
                   encoding="utf-8")
    monkeypatch.setattr(ga, "CONFIG_PATH", str(cfg))

    assert ga.detect_supported_version() == "1.19.*"
    assert ga.resolve_supported_version() == "1.19.*"

    # bad data → None, resolve fallback to default constant
    (tmp_path / "game" / "launcher-settings.json").write_text(
        '{"rawVersion": "abc"}', encoding="utf-8")
    from data.constants import DEFAULT_SUPPORTED_VERSION
    assert ga.detect_supported_version() is None
    assert ga.resolve_supported_version() == DEFAULT_SUPPORTED_VERSION


# ═══════ Real game file integration (native only) ═══════

_HAS_GAME = os.path.isfile(os.path.join(DEFAULT_HOI4_PATH, TERRAIN_DEF_RELPATH))


@pytest.mark.skipif(not _HAS_GAME, reason="HOI4 is not installed locally")
def test_real_game_assets_load():
    """Real game assets: The mapping table is not empty, and the atlas is 16 512×512 RGBA tiles."""
    assets = GameAssets()
    assert assets.available()

    mapping = assets.terrain_to_texture()
    assert mapping is not None
    # vanilla known mapping spot check (00_terrain.txt lines 324/331)
    assert mapping[0] == 1    # plain
    assert mapping[6] == 11   # Mountain

    tiles = assets.atlas_tiles()
    assert tiles is not None
    assert tiles.shape == (ATLAS_GRID * ATLAS_GRID, 512, 512, 4)

    normals = assets.atlas_normal_tiles()
    assert normals is not None
    assert normals.shape == tiles.shape
