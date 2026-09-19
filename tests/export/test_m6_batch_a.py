"""M6 Batch A: asset inventory, palette provenance, and structural files."""
from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from domain.export_contract import AssetResolution
from domain.game_profile import GameProfile
from export.bmp_writer import write_terrain_bmp
from export.stages.assets import run as run_assets_stage
from export.stages.base import StageContext
from export.writers.map.buildings import write_empty_unitstacks
from export.writers.map.cities_bmp import write_cities_bmp
from services.export_planner import build_asset_resolutions, plan_export
from services.game_assets import GameTarget


pytestmark = pytest.mark.unit


def _profile(*, deprecated=(), optional=()):
    return GameProfile(
        profile_id="test-m6",
        display_name="M6 test profile",
        required_files=["map/terrain.bmp"],
        optional_files=list(optional),
        deprecated_files=list(deprecated),
    )


def _fake_palette_bmp(path: Path, palette: bytes) -> None:
    header = bytearray(54)
    header[:2] = b"BM"
    struct.pack_into("<I", header, 10, 54)
    struct.pack_into("<H", header, 28, 8)
    path.write_bytes(bytes(header) + palette)


def test_asset_resolution_round_trips_legacy_and_extended_records():
    legacy = AssetResolution.from_dict({
        "rel_path": "map/example.dds",
        "disposition": "preserved",
        "provenance": "project-assets",
        "reason": "clean",
        "size": 4,
    })
    assert legacy.rel_path == "map/example.dds"
    assert legacy.disposition == "preserved"
    assert legacy.source == "project-assets"
    assert legacy.sha256 == ""

    extended = AssetResolution(
        "map/example.dds",
        "preserved",
        source="project-assets",
        sha256="a" * 64,
        output_owner="core_rasters",
        profile_rule="optional",
        dirty_reason="",
    )
    payload = extended.to_dict()
    assert payload["source"] == "project-assets"
    assert payload["sha256"] == "a" * 64
    assert payload["output_owner"] == "core_rasters"
    assert AssetResolution.from_dict(payload) == extended


def test_indexed_writers_use_the_explicit_game_target_palette(tmp_path):
    game_dir = tmp_path / "game"
    (game_dir / "map").mkdir(parents=True)
    palette = bytes((index * 7) % 256 for index in range(255 * 4))
    _fake_palette_bmp(game_dir / "map" / "terrain.bmp", palette)
    _fake_palette_bmp(game_dir / "map" / "cities.bmp", palette)
    target = GameTarget(install_dir=str(game_dir), source="explicit")

    write_terrain_bmp(np.zeros((2, 3), dtype=np.uint8), str(tmp_path / "terrain"), game_target=target)
    write_cities_bmp(str(tmp_path / "cities"), map_width=3, map_height=2, game_target=target)

    terrain_bytes = (tmp_path / "terrain" / "map" / "terrain.bmp").read_bytes()
    cities_bytes = (tmp_path / "cities" / "map" / "cities.bmp").read_bytes()
    assert terrain_bytes[54:54 + len(palette)] == palette
    assert cities_bytes[54:54 + len(palette)] == palette


def test_frozen_export_blocks_unresolved_required_palettes(tmp_path):
    tile_map = np.ones((16, 16), dtype=np.uint8)
    province_map = np.ones((16, 16), dtype=np.int32)
    target = GameTarget(install_dir=str(tmp_path / "missing-game"), source="explicit")

    plan = plan_export(
        tile_map,
        province_map,
        profile_name="acceptance",
        game_target=target,
        game_profile=_profile(),
        lifecycle="frozen",
        repair_policy="off",
    )

    assert any(
        finding.code == "export.palette.missing" and finding.severity == "blocker"
        for finding in plan.findings
    )
    assert any("required palette" in blocker for blocker in plan.blockers)


def test_structural_assets_preserve_clean_bytes_and_omit_missing_optionals(tmp_path):
    assets = {
        "map/airports.txt": b"airport { level = 2 }\r\n",
        "map/rocketsites.txt": b"rocket_site { level = 1 }\n",
        "map/cities.txt": b"custom city bytes\x00\xff",
    }
    write_empty_unitstacks(
        str(tmp_path),
        assets=assets,
        dirty_assets=set(),
        game_profile=_profile(optional=("map/airports.txt", "map/rocketsites.txt", "map/cities.txt")),
        profile_name="foundation",
    )

    assert (tmp_path / "map" / "airports.txt").read_bytes() == assets["map/airports.txt"]
    assert (tmp_path / "map" / "rocketsites.txt").read_bytes() == assets["map/rocketsites.txt"]
    assert (tmp_path / "map" / "cities.txt").read_bytes() == assets["map/cities.txt"]
    assert not (tmp_path / "map" / "rocket_sites.txt").exists()
    assert not (tmp_path / "map" / "colors.txt").exists()


def test_asset_inventory_marks_dirty_structural_files_unsupported():
    snapshot = SimpleNamespace(
        assets={
            "map/airports.txt": b"dirty",
            "map/cities.txt": b"clean",
        },
        dirty_assets=frozenset({"map/airports.txt"}),
    )
    profile = _profile(optional=("map/airports.txt", "map/cities.txt"))
    resolutions = build_asset_resolutions(snapshot, "foundation", profile)
    by_path = {item.rel_path: item for item in resolutions}

    assert by_path["map/airports.txt"].disposition == "unsupported"
    assert by_path["map/cities.txt"].disposition == "preserved"
    assert by_path["map/airports.txt"].output_owner == "placements"
    assert by_path["map/airports.txt"].dirty_reason


def test_frozen_export_blocks_dirty_structural_files_without_a_writer():
    tile_map = np.ones((16, 16), dtype=np.uint8)
    province_map = np.ones((16, 16), dtype=np.int32)
    target = GameTarget(install_dir=str(Path("missing-game")), source="explicit")

    plan = plan_export(
        tile_map,
        province_map,
        profile_name="acceptance",
        game_target=target,
        game_profile=_profile(optional=("map/airports.txt",)),
        assets={"map/airports.txt": b"edited"},
        dirty_assets={"map/airports.txt"},
        lifecycle="accepted",
        repair_policy="off",
    )

    assert any(
        finding.code == "export.structural.unsupported" and finding.severity == "blocker"
        for finding in plan.findings
    )
    assert any("dirty and has no regenerating writer" in blocker for blocker in plan.blockers)


def test_assets_stage_reports_resolution_state_and_missing_output(tmp_path):
    generated = AssetResolution("map/generated.bmp", "generated", output_owner="core_rasters")
    omitted = AssetResolution("map/optional.txt", "omitted", reason="not selected", output_owner="assets")
    unsupported = AssetResolution("map/dirty.txt", "unsupported", reason="no writer", output_owner="assets")
    ctx = StageContext(
        profile_name="foundation",
        output_dir=str(tmp_path),
        assets={},
        dirty_assets=set(),
        asset_resolutions=[generated, omitted, unsupported],
    )

    result = run_assets_stage(ctx)
    joined = "\n".join(result.notes)
    assert "map/generated.bmp: generated" in joined
    assert "file is absent" in joined
    assert "map/optional.txt: omitted" in joined
    assert "map/dirty.txt: unsupported" in joined
