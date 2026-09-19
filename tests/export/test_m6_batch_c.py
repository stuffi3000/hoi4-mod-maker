"""M6 Batch C: DDS strategy/capability, map-art matrix, visual regression."""
from __future__ import annotations

import json
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from domain import map_art_matrix as matrix
from domain.dds_format import (
    build_bgra8_header,
    build_dxt5_header,
    decide_dds_output,
    describe_encoder_capability,
    describe_profile_dds,
    downsample_rgba_box,
    encode_bc3_block,
    encode_bc3_payload,
    encode_dxt5_dds,
    encode_dxt5_payload,
    expected_bc_payload_size,
    generate_bc3_mip_chain,
    is_compatible_dds,
    parse_dds_header,
    strategy_for_asset,
)
from domain.export_contract import AssetResolution
from domain.game_profile import GameProfile, load_profile_from_file
from domain.validators.assets import validate_asset_integration
from export.stages.core_rasters import _can_restore_asset
from export.writers.map.colormap_dds import (
    generated_dds_satisfies_contract,
    read_dds_header_info,
    write_colormap_dds,
    write_fow_dds,
    write_water_colormap_dds,
)
from services.export_planner import (
    build_asset_resolutions,
    findings_for_asset_blockers,
    plan_export,
)
from services import visual_regression as vr


pytestmark = pytest.mark.unit

PROFILE_PATH = "data/game_profiles/hoi4_1_19.json"
WATER_0 = "map/terrain/colormap_water_0.dds"
COLORMAP = "map/terrain/colormap_rgb_cityemissivemask_a.dds"
FOW = "map/terrain/fow_rgb_waterspec_a.dds"


def _bundled_profile():
    return load_profile_from_file(PROFILE_PATH)


def _legacy_profile(**overrides):
    kwargs = dict(
        profile_id="test-m6c",
        display_name="M6C test profile",
        required_files=[],
        optional_files=[],
        deprecated_files=[],
    )
    kwargs.update(overrides)
    return GameProfile(**kwargs)


def _dxt5_bytes(width, height, mips=1):
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<I", header, 8, 0x100F)
    struct.pack_into("<I", header, 12, height)
    struct.pack_into("<I", header, 16, width)
    payload_size = expected_bc_payload_size(width, height, "DXT5", mips)
    struct.pack_into("<I", header, 20, payload_size)
    struct.pack_into("<I", header, 28, mips)
    struct.pack_into("<I", header, 76, 32)
    struct.pack_into("<I", header, 80, 0x4)
    header[84:88] = b"DXT5"
    struct.pack_into("<I", header, 108, 0x1000)
    return bytes(header) + bytes(payload_size)


def _bgra8_bytes(width, height, fill=0):
    return build_bgra8_header(width, height) + bytes([fill]) * width * height * 4


def _tile_map(size=16):
    tile = np.full((size, size), TILE_SEA, dtype=np.uint8)
    tile[:, size // 2 :] = TILE_LAND
    return tile


def test_capability_probe_is_explicit_and_dependency_free():
    first = describe_encoder_capability()
    second = describe_encoder_capability()
    assert first == second
    assert first["bgra8_uncompressed"] == "supported"
    assert first["bc3_dxt5"] == "supported"
    assert "DXT5" in first["mip_chain_writes"]
    assert first["deterministic"] is True
    assert first["network_required"] is False
    assert first["external_tools_required"] == ()
    assert first["provenance"]


def test_profile_dds_strategy_is_inspectable_and_deterministic():
    profile = _bundled_profile()
    first = describe_profile_dds(profile, 5632, 2048)
    second = describe_profile_dds(profile, 5632, 2048)
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    by_path = {item.rel_path: item for item in first}
    assert set(by_path) >= {WATER_0, COLORMAP, FOW}
    water = by_path[WATER_0]
    assert water.four_cc == "DXT5"
    assert (water.expected_width, water.expected_height) == (2816, 1024)
    assert water.mip_count == 1
    assert water.has_dx10_header is False
    assert water.can_generate is True
    assert water.encoder == "bc3-dxt5"
    assert water.encoder and water.provenance and water.reason
    assert by_path[FOW].mip_count == 12
    assert by_path[FOW].can_generate is True
    assert by_path[FOW].encoder == "bc3-dxt5"
    area = by_path[COLORMAP]
    assert area.four_cc == "BGRA8"
    assert area.can_generate is True
    assert (area.expected_width, area.expected_height) == (2816, 1024)


def test_bgra8_header_parses_against_the_spec():
    header = build_bgra8_header(8, 4)
    assert len(header) == 128
    info = parse_dds_header(header + bytes(8 * 4 * 4))
    assert info["width"] == 8
    assert info["height"] == 4
    assert info["four_cc"] == "BGRA8"
    assert info["mip_count"] == 1
    assert info["has_dx10_header"] is False
    assert info["payload_size"] == 8 * 4 * 4
    with pytest.raises(ValueError):
        parse_dds_header(b"not a dds file" + bytes(200))
    with pytest.raises(ValueError):
        parse_dds_header(b"DDS " + bytes(10))


def test_expected_bc_payload_math():
    assert expected_bc_payload_size(8, 8, "DXT5", 1) == 4 * 16
    assert expected_bc_payload_size(8, 8, "DXT1", 1) == 4 * 8
    assert expected_bc_payload_size(8, 8, "DXT5", 2) == 4 * 16 + 1 * 16
    assert expected_bc_payload_size(8, 8, "BGRA8", 1) is None


def test_generated_writers_emit_honest_bgra8(tmp_path):
    tile = _tile_map(16)
    write_water_colormap_dds(tile, str(tmp_path))
    write_fow_dds(tile, str(tmp_path))
    write_colormap_dds(tile, str(tmp_path))
    for name, dims in (
        ("colormap_water_0.dds", (8, 8)),
        ("colormap_water_1.dds", (4, 4)),
        ("colormap_water_2.dds", (2, 2)),
        ("fow_rgb_waterspec_a.dds", (8, 8)),
        ("colormap_rgb_cityemissivemask_a.dds", (8, 8)),
    ):
        info = read_dds_header_info(str(tmp_path / "map" / "terrain" / name))
        assert info["four_cc"] == "BGRA8", name
        assert info["four_cc"] != "DXT5", name
        assert (info["width"], info["height"]) == dims, name
        assert info["payload_size"] == dims[0] * dims[1] * 4, name


def test_generated_output_contract_check_never_mislabels():
    from domain.game_profile import DdsContract
    profile = _bundled_profile()
    tile = _tile_map(16)
    ok, reason = generated_dds_satisfies_contract(WATER_0, tile, profile)
    assert ok is True
    assert "DXT5" in reason
    ok, reason = generated_dds_satisfies_contract(FOW, tile, profile)
    assert ok is True
    assert "DXT5" in reason
    ok, _reason = generated_dds_satisfies_contract(COLORMAP, tile, profile)
    assert ok is True
    ok, _reason = generated_dds_satisfies_contract(
        WATER_0, tile, _legacy_profile()
    )
    assert ok is True
    dxt1_profile = _legacy_profile(
        dds={WATER_0: DdsContract(four_cc="DXT1", mip_count=1)},
    )
    ok, reason = generated_dds_satisfies_contract(WATER_0, tile, dxt1_profile)
    assert ok is False
    assert "DXT1" in reason


def test_dds_decisions_preserve_or_block():
    from domain.game_profile import DdsContract
    profile = _bundled_profile()
    water = strategy_for_asset(WATER_0, profile, 16, 16)
    assert (water.expected_width, water.expected_height) == (8, 8)
    assert water.can_generate is True
    assert water.encoder == "bc3-dxt5"
    assert water.requirement == "profile-contract"

    generated = decide_dds_output(water)
    assert generated.action == "generate"
    assert generated.provenance == "writer-generated"

    compatible = _dxt5_bytes(8, 8, 1)
    ok, _why = is_compatible_dds(compatible, water)
    assert ok is True
    preserved = decide_dds_output(water, imported_bytes=compatible)
    assert preserved.action == "preserve"

    dirty = decide_dds_output(water, imported_bytes=compatible, dirty=True)
    assert dirty.action == "generate"

    foreign = _bgra8_bytes(8, 8)
    ok, _why = is_compatible_dds(foreign, water)
    assert ok is False
    regenerated = decide_dds_output(water, imported_bytes=foreign)
    assert regenerated.action == "generate"

    dxt1_profile = _legacy_profile(
        dds={WATER_0: DdsContract(four_cc="DXT1", mip_count=1)},
    )
    dxt1_strategy = strategy_for_asset(WATER_0, dxt1_profile, 16, 16)
    assert dxt1_strategy.can_generate is False
    blocked = decide_dds_output(dxt1_strategy)
    assert blocked.action == "blocked"
    assert blocked.remedy
    assert blocked.provenance == "dds-capability"

    area = strategy_for_asset(COLORMAP, profile, 16, 16)
    assert area.can_generate is True
    generated = decide_dds_output(area)
    assert generated.action == "generate"
    kept = decide_dds_output(area, imported_bytes=_bgra8_bytes(8, 8))
    assert kept.action == "preserve"


def test_planner_dds_resolutions_block_freeze_not_draft():
    profile = _bundled_profile()
    tile = np.ones((16, 16), dtype=np.uint8)
    prov = np.ones((16, 16), dtype=np.int32)
    frozen = plan_export(
        tile, prov, profile_name="foundation", game_profile=profile,
        lifecycle="frozen", repair_policy="off",
    )
    by_path = {item.rel_path: item for item in frozen.asset_resolutions}
    assert by_path[WATER_0].disposition == "generated"
    assert by_path[WATER_0].provenance == "writer-generated"
    assert by_path[FOW].disposition == "generated"
    assert by_path[FOW].provenance == "writer-generated"
    assert by_path[COLORMAP].disposition == "generated"
    dds_blockers = [
        item for item in frozen.findings
        if item.code == "export.asset.blocked"
        and (WATER_0 in item.message or FOW in item.message)
    ]
    assert dds_blockers == []
    assert all(WATER_0 not in blocker for blocker in frozen.blockers)
    assert all(FOW not in blocker for blocker in frozen.blockers)

    draft = plan_export(
        tile, prov, profile_name="foundation", game_profile=profile,
        lifecycle="draft", repair_policy="off",
    )
    draft_by_path = {item.rel_path: item for item in draft.asset_resolutions}
    assert draft_by_path[WATER_0].disposition == "generated"
    assert draft_by_path[FOW].disposition == "generated"
    draft_dds_blockers = [
        item for item in draft.findings
        if item.code == "export.asset.blocked"
        and (WATER_0 in item.message or FOW in item.message)
    ]
    assert draft_dds_blockers == []
    assert draft.blocked is False


def test_custom_profile_without_dds_contract_keeps_legacy_behavior():
    snapshot = SimpleNamespace(assets={}, dirty_assets=frozenset())
    resolutions = build_asset_resolutions(snapshot, "foundation", _legacy_profile())
    by_path = {item.rel_path: item for item in resolutions}
    assert by_path[WATER_0].disposition == "generated"
    assert findings_for_asset_blockers(resolutions, _legacy_profile(), "frozen") == []


def test_matrix_paths_cover_generated_and_inherited_art():
    profile = _bundled_profile()
    paths = matrix.matrix_paths_for_profile(profile)
    assert paths == sorted(paths)
    assert set(matrix.GENERATED_DDS_ART) <= set(paths)
    assert set(matrix.KNOWN_INHERITED_MAP_ART) <= set(paths)
    assert matrix.family_for_path("map/terrain/atlas0.dds") == "atlas"
    assert matrix.family_for_path(WATER_0) == "colormap"
    assert matrix.family_for_path(FOW) == "fog-of-war"
    assert matrix.family_for_path("map/terrain/snow_01.dds") == "snow"
    assert matrix.family_for_path("map/provinces.bmp") == ""
    assert matrix.is_map_art_path("map/terrain/atlas0.dds") is True
    assert matrix.is_map_art_path("map/provinces.bmp") is False


def test_matrix_classification_is_deterministic_and_fully_reasoned():
    profile = _bundled_profile()
    tile = np.ones((16, 16), dtype=np.uint8)
    prov = np.ones((16, 16), dtype=np.int32)
    assets = {
        "map/terrain/atlas0.dds": b"fake-atlas-bytes",
        "map/terrain/snow_01.dds": b"fake-snow-bytes",
    }
    first = plan_export(
        tile, prov, profile_name="foundation", game_profile=profile,
        assets=assets, lifecycle="draft", repair_policy="off",
    )
    second = plan_export(
        tile, prov, profile_name="foundation", game_profile=profile,
        assets=dict(assets), lifecycle="draft", repair_policy="off",
    )
    assert [item.to_dict() for item in first.asset_resolutions] == [
        item.to_dict() for item in second.asset_resolutions
    ]
    by_path = {item.rel_path: item for item in first.asset_resolutions}
    for item in first.asset_resolutions:
        assert item.reason, item.rel_path
        assert item.provenance, item.rel_path
    assert by_path["map/terrain/atlas0.dds"].disposition == "preserved"
    assert by_path["map/terrain/snow_01.dds"].disposition == "preserved"
    inherited = by_path["map/terrain/atlas_normal0.dds"]
    assert inherited.disposition == "inherited"
    assert inherited.provenance == "game-install"
    assert inherited.reason
    assert set(assets) <= set(by_path)


def test_dirty_map_art_without_writer_is_blocked_not_dropped():
    snapshot = SimpleNamespace(
        assets={"map/terrain/atlas0.dds": b"edited"},
        dirty_assets=frozenset({"map/terrain/atlas0.dds"}),
    )
    resolutions = build_asset_resolutions(snapshot, "foundation", _legacy_profile())
    by_path = {item.rel_path: item for item in resolutions}
    assert by_path["map/terrain/atlas0.dds"].disposition == "blocked"
    assert by_path["map/terrain/atlas0.dds"].dirty_reason


def test_required_incompatible_asset_blocks_freeze():
    profile = _legacy_profile(required_files=["map/terrain/atlas0.dds"])
    tile = np.ones((16, 16), dtype=np.uint8)
    prov = np.ones((16, 16), dtype=np.int32)
    frozen = plan_export(
        tile, prov, profile_name="foundation", game_profile=profile,
        assets={"map/terrain/atlas0.dds": b"edited"},
        dirty_assets={"map/terrain/atlas0.dds"},
        lifecycle="frozen", repair_policy="off",
    )
    hits = [item for item in frozen.findings if item.code == "export.asset.blocked"]
    assert hits
    assert all(item.severity == "blocker" for item in hits)
    assert frozen.blocked is True

    draft = plan_export(
        tile, prov, profile_name="foundation", game_profile=profile,
        assets={"map/terrain/atlas0.dds": b"edited"},
        dirty_assets={"map/terrain/atlas0.dds"},
        lifecycle="draft", repair_policy="off",
    )
    assert draft.blocked is False
    assert any(
        item.code == "export.asset.blocked" and item.severity == "warning"
        for item in draft.findings
    )

    required_unsupported = findings_for_asset_blockers(
        [AssetResolution("map/terrain/atlas0.dds", "unsupported", reason="no writer")],
        profile, "accepted",
    )
    assert len(required_unsupported) == 1
    assert required_unsupported[0].severity == "blocker"


def test_required_missing_asset_blocks_freeze():
    profile = _legacy_profile(required_files=["map/ghost.txt"])
    tile = np.ones((16, 16), dtype=np.uint8)
    prov = np.ones((16, 16), dtype=np.int32)
    frozen = plan_export(
        tile, prov, profile_name="foundation", game_profile=profile,
        lifecycle="accepted", repair_policy="off",
    )
    hits = [item for item in frozen.findings if item.code == "export.asset.blocked"]
    assert any("map/ghost.txt" in item.message for item in hits)
    assert all(item.severity == "blocker" for item in hits)
    assert frozen.blocked is True
    draft = plan_export(
        tile, prov, profile_name="foundation", game_profile=profile,
        lifecycle="draft", repair_policy="off",
    )
    assert draft.blocked is False
    assert any(
        item.code == "export.asset.blocked" and item.severity == "warning"
        for item in draft.findings
    )


def test_validator_reports_blocked_as_disposition_problem():
    profile = GameProfile(
        profile_id="test-m6c",
        required_files=["map/example.dds"],
        optional_files=["map/optional.dds"],
    )
    findings = validate_asset_integration(
        profile=profile,
        asset_resolutions=[
            AssetResolution("map/example.dds", "blocked"),
            AssetResolution("map/optional.dds", "blocked"),
        ],
    )
    codes = [item.code for item in findings]
    assert "integration.asset_disposition" in codes
    assert "integration.asset_record" not in codes
    evidence = next(
        item.evidence for item in findings
        if item.code == "integration.asset_disposition"
    )
    assert "map/example.dds" in evidence and "blocked" in evidence

    clean = validate_asset_integration(
        profile=profile,
        asset_resolutions=[
            AssetResolution("map/example.dds", "generated"),
            AssetResolution("map/optional.dds", "blocked"),
        ],
    )
    assert clean == []


def test_assets_stage_reports_blocked_resolutions(tmp_path):
    from export.stages.assets import run as run_assets_stage
    from export.stages.base import StageContext

    ctx = StageContext(
        profile_name="foundation",
        output_dir=str(tmp_path),
        assets={},
        dirty_assets=set(),
        asset_resolutions=[
            AssetResolution("map/terrain/colormap_water_0.dds", "blocked",
                            provenance="dds-capability", reason="no encoder"),
        ],
    )
    result = run_assets_stage(ctx)
    joined = "\n".join(result.notes)
    assert "map/terrain/colormap_water_0.dds: blocked" in joined
    assert "no file written" in joined


def test_core_rasters_restores_only_planned_compatible_assets():
    path = COLORMAP
    ctx = SimpleNamespace(
        assets={path: b"incompatible-or-dirty-plan"},
        dirty_assets=set(),
        asset_resolutions=[AssetResolution(path, "generated")],
    )
    assert _can_restore_asset(ctx, path) is False
    ctx.asset_resolutions = [AssetResolution(path, "preserved")]
    assert _can_restore_asset(ctx, path) is True


def _solid_panel(value, width=4, height=3):
    return np.full((height, width, 3), value, dtype=np.uint8)


def test_contact_sheet_is_deterministic(tmp_path):
    panels = [
        ("red", _solid_panel((200, 20, 20))),
        ("green", _solid_panel((20, 200, 20), width=5, height=2)),
        ("gray", np.full((2, 2), 128, dtype=np.uint8)),
    ]
    first = vr.write_contact_sheet(str(tmp_path / "a.png"), panels)
    second = vr.write_contact_sheet(str(tmp_path / "b.png"), panels)
    assert (tmp_path / "a.png").read_bytes() == (tmp_path / "b.png").read_bytes()
    assert first.pop("path") == "a.png"
    assert second.pop("path") == "b.png"
    assert first == second
    assert first["schema"] == vr.SCHEMA
    assert first["panel_count"] == 3
    assert [entry["name"] for entry in first["panels"]] == ["red", "green", "gray"]
    assert (tmp_path / "a.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_miniature_handles_tiny_arrays_and_dds_panels():
    tiny = np.array([[[7, 8, 9]]], dtype=np.uint8)
    mini = vr.miniature(tiny, width=4, height=4)
    assert mini.shape == (4, 4, 3)
    assert (mini == (7, 8, 9)).all()

    payload = bytes([10, 20, 30, 255]) * (4 * 2)
    name, rgb = vr.panel_from_dds_bytes("water", build_bgra8_header(4, 2) + payload)
    assert name == "water"
    assert rgb.shape == (2, 4, 3)
    assert tuple(int(v) for v in rgb[0, 0]) == (30, 20, 10)

    with pytest.raises(ValueError):
        vr.panel_from_dds_bytes("water", _dxt5_bytes(8, 8, 1))
    with pytest.raises(ValueError):
        vr.contact_sheet([])
    with pytest.raises(ValueError):
        vr.miniature(_solid_panel((1, 2, 3)), width=0, height=4)


def test_approval_record_is_stable_and_validated():
    raster = _solid_panel((9, 9, 9), width=2, height=2)
    first = vr.summarize_raster("colormap", raster)
    second = vr.summarize_raster("colormap", raster)
    assert first == second
    record = vr.approval_record([first], "ab" * 32, status="pending")
    assert json.dumps(record, sort_keys=True) == json.dumps(
        vr.approval_record([dict(first)], "ab" * 32, status="pending"),
        sort_keys=True,
    )
    approved = vr.approval_record(
        [first], "ab" * 32, status="approved", reviewer="qa",
        note="looks right", created_at="2026-09-19T00:00:00+00:00",
    )
    assert approved["status"] == "approved"
    assert approved["reviewer"] == "qa"
    with pytest.raises(ValueError):
        vr.approval_record([first], "ab" * 32, status="signed-off")
    with pytest.raises(ValueError):
        vr.approval_record([first], "")


def test_visual_regression_is_opt_in():
    for rel in (
        "export/stages/core_rasters.py",
        "export/mod_exporter.py",
        "services/export_planner.py",
        "services/export_manifest.py",
    ):
        text = Path(rel).read_text(encoding="utf-8")
        assert "visual_regression" not in text, rel
    assert "opt-in" in (vr.__doc__ or "").lower()


def test_bc3_encoder_known_tiny_block_output_and_size():
    solid_red = np.full((4, 4, 4), (255, 0, 0, 255), dtype=np.uint8)
    block = encode_bc3_block(solid_red, order="RGBA")
    assert len(block) == 16
    assert block.hex() == "ffff00000000000000f800f800000000"
    assert expected_bc_payload_size(4, 4, "DXT5", 1) == 16
    payload = encode_bc3_payload(solid_red, order="RGBA")
    assert payload == block
    repeat = encode_bc3_block(
        np.ascontiguousarray(solid_red), order="RGBA"
    )
    assert repeat == block


def test_bc3_encoder_is_deterministic_and_handles_bgra_order():
    rng_pixels = (np.arange(8 * 8 * 4, dtype=np.int32) % 251).astype(np.uint8).reshape(8, 8, 4)
    first = encode_bc3_payload(rng_pixels, order="RGBA")
    second = encode_bc3_payload(rng_pixels, order="RGBA")
    assert first == second
    assert len(first) == expected_bc_payload_size(8, 8, "DXT5", 1)
    bgra = np.ascontiguousarray(rng_pixels[:, :, [2, 1, 0, 3]])
    assert encode_bc3_payload(bgra, order="BGRA") == first
    rgb_only = np.ascontiguousarray(rng_pixels[:, :, :3])
    opaque = np.concatenate(
        [rgb_only, np.full((8, 8, 1), 255, dtype=np.uint8)], axis=2
    )
    assert encode_bc3_payload(rgb_only, order="RGBA") == encode_bc3_payload(opaque, order="RGBA")
    with pytest.raises(ValueError):
        encode_bc3_payload(rng_pixels, order="ARGB")
    with pytest.raises(ValueError):
        encode_bc3_block(np.zeros((3, 4, 4), dtype=np.uint8))


def test_bc3_encoder_edge_dimensions_replicate_with_exact_sizes():
    for width, height in ((5, 2), (3, 7), (1, 1), (11, 4), (6, 6)):
        pixels = np.full((height, width, 4), (10, 20, 30, 40), dtype=np.uint8)
        payload = encode_bc3_payload(pixels, order="RGBA")
        assert len(payload) == expected_bc_payload_size(width, height, "DXT5", 1)
        assert payload == encode_bc3_payload(pixels, order="RGBA")
    tiny = np.full((1, 1, 4), (1, 2, 3, 4), dtype=np.uint8)
    assert len(encode_bc3_payload(tiny)) == 16


def test_bc3_mip_chain_payload_math_is_exact_and_deterministic():
    base = (np.arange(8 * 8 * 4, dtype=np.int32) % 251).astype(np.uint8).reshape(8, 8, 4)
    levels, payload = generate_bc3_mip_chain(base, mip_count=2, order="RGBA")
    assert levels == [(8, 8), (4, 4)]
    assert len(payload) == expected_bc_payload_size(8, 8, "DXT5", 2) == 80
    _levels2, payload2 = generate_bc3_mip_chain(base, mip_count=2, order="RGBA")
    assert payload2 == payload
    assert encode_dxt5_payload(base, mip_count=2, order="RGBA") == payload
    odd = np.full((3, 5, 4), (7, 8, 9, 200), dtype=np.uint8)
    odd_levels, odd_payload = generate_bc3_mip_chain(odd, mip_count=3, order="RGBA")
    assert odd_levels == [(5, 3), (2, 1), (1, 1)]
    assert len(odd_payload) == expected_bc_payload_size(5, 3, "DXT5", 3)
    shrunk = downsample_rgba_box(base, 4, 4)
    assert shrunk.shape == (4, 4, 4)
    assert (downsample_rgba_box(base, 8, 8) == base).all()


def test_dxt5_header_and_full_file_validate_against_contract():
    profile = _bundled_profile()
    pixels = np.full((8, 8, 4), (90, 55, 30, 255), dtype=np.uint8)
    header = build_dxt5_header(8, 8, 1)
    assert len(header) == 128
    full = encode_dxt5_dds(pixels, mip_count=1, order="RGBA")
    info = parse_dds_header(full)
    assert info["four_cc"] == "DXT5"
    assert (info["width"], info["height"]) == (8, 8)
    assert info["mip_count"] == 1
    assert info["has_dx10_header"] is False
    assert info["payload_size"] == expected_bc_payload_size(8, 8, "DXT5", 1)
    strategy = strategy_for_asset(WATER_0, profile, 16, 16)
    ok, _why = is_compatible_dds(full, strategy)
    assert ok is True
    fow_full = encode_dxt5_dds(pixels, mip_count=12, order="RGBA")
    fow_info = parse_dds_header(fow_full)
    assert fow_info["mip_count"] == 12
    assert fow_info["payload_size"] == expected_bc_payload_size(8, 8, "DXT5", 12)
    fow_strategy = strategy_for_asset(FOW, profile, 16, 16)
    assert fow_strategy.mip_count == 12
    with pytest.raises(ValueError):
        parse_dds_header(full[:64])
    truncated = full[:-1]
    ok, _why = is_compatible_dds(truncated, strategy)
    assert ok is False


def test_profile_aware_water_and_fow_writers_emit_contract_bytes(tmp_path):
    from export.writers.map.colormap_dds import (
        generated_dds_satisfies_contract as satisfies,
        read_dds_header_info as header_info,
        write_colormap_dds,
        write_fow_dds,
        write_water_colormap_dds,
    )
    profile = _bundled_profile()
    tile = _tile_map(16)
    write_water_colormap_dds(tile, str(tmp_path), profile=profile)
    write_fow_dds(tile, str(tmp_path), profile=profile)
    write_colormap_dds(tile, str(tmp_path), profile=profile)
    expectations = {
        "colormap_water_0.dds": ("DXT5", (8, 8), 1),
        "colormap_water_1.dds": ("DXT5", (4, 4), 1),
        "colormap_water_2.dds": ("DXT5", (2, 2), 1),
        "fow_rgb_waterspec_a.dds": ("DXT5", (8, 8), 12),
        "colormap_rgb_cityemissivemask_a.dds": ("BGRA8", (8, 8), 1),
    }
    for name, (four_cc, dims, mips) in expectations.items():
        raw = (tmp_path / "map" / "terrain" / name).read_bytes()
        info = header_info(raw)
        assert info["four_cc"] == four_cc, name
        assert (info["width"], info["height"]) == dims, name
        assert info["mip_count"] == mips, name
        assert info["payload_size"] == (
            dims[0] * dims[1] * 4 if four_cc == "BGRA8"
            else expected_bc_payload_size(dims[0], dims[1], "DXT5", mips)
        ), name
    for rel_path in (WATER_0, FOW, COLORMAP):
        ok, _reason = satisfies(rel_path, tile, profile)
        assert ok is True, rel_path
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    write_water_colormap_dds(tile, str(legacy_dir))
    write_fow_dds(tile, str(legacy_dir))
    for name in ("colormap_water_0.dds", "fow_rgb_waterspec_a.dds"):
        info = header_info(str(legacy_dir / "map" / "terrain" / name))
        assert info["four_cc"] == "BGRA8", name


def test_planner_preserves_compatible_imported_dxt5_and_regenerates_dirty():
    profile = _bundled_profile()
    tile = np.ones((16, 16), dtype=np.uint8)
    prov = np.ones((16, 16), dtype=np.int32)
    compatible = _dxt5_bytes(8, 8, 1)
    kept = plan_export(
        tile, prov, profile_name="foundation", game_profile=profile,
        assets={WATER_0: compatible}, lifecycle="frozen", repair_policy="off",
    )
    by_path = {item.rel_path: item for item in kept.asset_resolutions}
    assert by_path[WATER_0].disposition == "preserved"
    assert by_path[WATER_0].provenance == "project-assets"
    dirty_plan = plan_export(
        tile, prov, profile_name="foundation", game_profile=profile,
        assets={WATER_0: compatible}, dirty_assets={WATER_0},
        lifecycle="draft", repair_policy="off",
    )
    dirty_by_path = {item.rel_path: item for item in dirty_plan.asset_resolutions}
    assert dirty_by_path[WATER_0].disposition == "generated"
    mismatch_plan = plan_export(
        tile, prov, profile_name="foundation", game_profile=profile,
        assets={WATER_0: _bgra8_bytes(8, 8)}, lifecycle="draft",
        repair_policy="off",
    )
    mismatch_by_path = {item.rel_path: item for item in mismatch_plan.asset_resolutions}
    assert mismatch_by_path[WATER_0].disposition == "generated"


def test_unsupported_dxt1_contract_stays_blocked_with_remedy():
    from domain.game_profile import DdsContract
    dxt1_profile = _legacy_profile(
        dds={WATER_0: DdsContract(four_cc="DXT1", mip_count=1)},
    )
    tile = np.ones((16, 16), dtype=np.uint8)
    prov = np.ones((16, 16), dtype=np.int32)
    frozen = plan_export(
        tile, prov, profile_name="foundation", game_profile=dxt1_profile,
        lifecycle="frozen", repair_policy="off",
    )
    by_path = {item.rel_path: item for item in frozen.asset_resolutions}
    assert by_path[WATER_0].disposition == "blocked"
    assert by_path[WATER_0].provenance == "dds-capability"
    assert "Remedy" in by_path[WATER_0].reason
    hits = [
        item for item in frozen.findings
        if item.code == "export.asset.blocked" and WATER_0 in item.message
    ]
    assert hits
    assert all(item.severity == "blocker" for item in hits)
    assert frozen.blocked is True
    draft = plan_export(
        tile, prov, profile_name="foundation", game_profile=dxt1_profile,
        lifecycle="draft", repair_policy="off",
    )
    assert draft.blocked is False
    assert any(
        item.code == "export.asset.blocked" and item.severity == "warning"
        and WATER_0 in item.message
        for item in draft.findings
    )
